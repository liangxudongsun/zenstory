import React, { useEffect, useRef, useSyncExternalStore } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { BrowserRouter, Route, Routes, useParams } from 'react-router-dom';
import { ProjectProvider, useProject } from '../../contexts/ProjectContext';
import { useLeaveWhileGenerating } from '../../hooks/useLeaveWhileGenerating';
import { hasAnyUnprotectedDeletedDraft, setUnprotectedDeletedDraft, subscribeDeletedDraftProtection } from '../../lib/fileRemovalEvents';
import { LeaveWhileGeneratingDialog } from '../LeaveWhileGeneratingDialog';
import { ProjectSwitcher } from '../ProjectSwitcher';

const auth = vi.hoisted(() => ({ user: { id: 'navigation-owner' } }));

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => auth }));
vi.mock('../../hooks/useMediaQuery', () => ({ useIsMobile: () => false }));
vi.mock('../../lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock('../../lib/api', () => ({ projectApi: { getAll: vi.fn(async () => [
  { id: 'project-1', name: 'Original novel', project_type: 'novel', updated_at: '2026-10-13' },
  { id: 'project-2', name: 'Other novel', project_type: 'novel', updated_at: '2026-10-12' },
]) } }));

function GuardedWorkspace() {
  const { projectId } = useParams();
  const { currentProjectId, setCurrentProjectId, selectedItem, setSelectedItem } = useProject();
  const selectedInitially = useRef(false);
  // The project route owns context changes, as App's ensureProject effect does.
  useEffect(() => {
    if (projectId) setCurrentProjectId(projectId);
  }, [projectId, setCurrentProjectId]);
  useEffect(() => {
    if (!selectedInitially.current && currentProjectId === 'project-1') {
      selectedInitially.current = true;
      setSelectedItem({ id: 'retained-file', title: 'Chapter', type: 'draft' });
    }
  }, [currentProjectId, setSelectedItem]);
  const unprotected = useSyncExternalStore(subscribeDeletedDraftProtection,
    hasAnyUnprotectedDeletedDraft, () => false);
  const guard = useLeaveWhileGenerating(unprotected);
  return <>
    <ProjectSwitcher />
    <output data-testid="current-project">{currentProjectId}</output>
    <output data-testid="selected-file">{selectedItem?.id}</output>
    <LeaveWhileGeneratingDialog open={guard.leavePending} unprotectedDraft={unprotected}
      roundEnded={guard.roundEnded} producedOutput={false} showDailyCount={false}
      onStay={guard.cancelLeave} onLeave={guard.confirmLeave} />
  </>;
}

beforeEach(() => {
  localStorage.clear();
  window.history.replaceState({}, '', '/project/project-1');
});
afterEach(async () => {
  act(() => setUnprotectedDeletedDraft('project-1', false));
  cleanup();
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
});

it.each(['stay', 'leave'] as const)('keeps project and file untouched until the existing leave guard chooses %s', async choice => {
  render(<BrowserRouter><ProjectProvider><Routes><Route path="/project/:projectId" element={<GuardedWorkspace />} /></Routes></ProjectProvider></BrowserRouter>);
  await waitFor(() => expect(screen.getByTestId('selected-file')).toHaveTextContent('retained-file'));
  act(() => setUnprotectedDeletedDraft('project-1', true));
  fireEvent.click(screen.getByRole('button', { name: /Original novel/ }));
  fireEvent.click(screen.getByText('Other novel'));
  expect(await screen.findByRole('dialog')).toHaveTextContent('editor:deletedFile.leaveMessage');
  expect(window.location.pathname).toBe('/project/project-1');
  expect(screen.getByTestId('current-project')).toHaveTextContent('project-1');
  expect(screen.getByTestId('selected-file')).toHaveTextContent('retained-file');
  fireEvent.click(screen.getByTestId(choice === 'stay' ? 'leave-dialog-stay' : 'leave-dialog-leave'));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  await waitFor(() => expect(window.location.pathname).toBe(`/project/project-${choice === 'stay' ? '1' : '2'}`));
  expect(screen.getByTestId('current-project')).toHaveTextContent(choice === 'stay' ? 'project-1' : 'project-2');
  if (choice === 'stay') expect(screen.getByTestId('selected-file')).toHaveTextContent('retained-file');
});
