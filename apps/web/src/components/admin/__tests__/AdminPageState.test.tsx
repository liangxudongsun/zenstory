import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AdminPageState } from '../AdminPageState';

describe('admin query feedback', () => {
  it('announces loading without showing an empty result', () => {
    render(<AdminPageState isLoading loadingText="Loading records">Records</AdminPageState>);
    expect(screen.getByRole('status')).toHaveTextContent('Loading records');
    expect(screen.queryByText('Records')).not.toBeInTheDocument();
  });
  it('announces errors and provides an explicit retry', () => {
    const retry = vi.fn();
    render(<AdminPageState isError errorText="Records unavailable" retryText="Retry" onRetry={retry}>Records</AdminPageState>);
    expect(screen.getByRole('alert')).toHaveTextContent('Records unavailable');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(retry).toHaveBeenCalledOnce();
  });
});
