import { StrictMode } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FirstWorkEntry } from './FirstWorkEntry';
import type { FirstWorkState } from '../../lib/firstWorkApi';
const mocks = vi.hoisted(() => ({ get: vi.fn(), initialize: vi.fn(), refresh: vi.fn(async () => {}) }));
vi.mock('../../lib/firstWorkApi', async original => ({ ...await original<typeof import('../../lib/firstWorkApi')>(), firstWorkApi: mocks }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }) }));
const state: FirstWorkState = { status: 'pending', project_id: null, file_id: null, available: false, static_guidance: false,
  opened_at: null, first_manual_write_at: null, first_ai_requested_at: null };
const created: FirstWorkState = { ...state, status: 'created', project_id: 'project', file_id: 'draft', available: true, static_guidance: true };
function mount(client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return render(<StrictMode><QueryClientProvider client={client}><MemoryRouter><FirstWorkEntry userId="author" preferredType="short" onCreated={mocks.refresh} /></MemoryRouter></QueryClientProvider></StrictMode>);
}
beforeEach(() => { vi.clearAllMocks(); mocks.get.mockResolvedValue(state); mocks.initialize.mockResolvedValue(created); });
describe('dashboard-only first-work initialization lifecycle', () => {
  it('initializes once through StrictMode replay and only reads persisted results on a later visit', async () => {
    const view = mount();
    await screen.findByRole('button', { name: 'firstWork.open' });
    expect(mocks.initialize).toHaveBeenCalledTimes(1);
    expect(mocks.initialize).toHaveBeenCalledWith('short', 'en');
    view.unmount(); mocks.get.mockResolvedValue(created);
    mount();
    await screen.findByRole('button', { name: 'firstWork.open' });
    expect(mocks.initialize).toHaveBeenCalledTimes(1);
  });
  it('never initializes when rollout is disabled, onboarding is unfinished or an author already has work', async () => {
    for (const status of ['disabled', 'ineligible', 'waiting_onboarding', 'waiting_verification', 'skipped_existing'] as const) {
      mocks.get.mockResolvedValue({ ...state, status });
      const view = mount();
      await waitFor(() => expect(mocks.get).toHaveBeenCalled());
      expect(mocks.initialize).not.toHaveBeenCalled();
      view.unmount(); mocks.get.mockClear();
    }
  });
  it('does not reload project providers after leaving while initialization is in flight', async () => {
    let finish!: (value: FirstWorkState) => void;
    mocks.initialize.mockReturnValue(new Promise(yes => { finish = yes; }));
    const view = mount();
    await waitFor(() => expect(mocks.initialize).toHaveBeenCalledTimes(1));
    view.unmount();
    finish(created);
    await Promise.resolve(); await Promise.resolve();
    expect(mocks.refresh).not.toHaveBeenCalled();
  });
});
