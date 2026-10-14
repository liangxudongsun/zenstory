import { beforeEach, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { usePaidPlanWhenOpen } from '../usePaidPlanWhenOpen';

vi.mock('../../lib/subscriptionApi', () => ({
  subscriptionApi: { getStatus: vi.fn() },
  subscriptionQueryKeys: { status: () => ['subscription-status', JSON.parse(localStorage.getItem('user') ?? '{}').id] },
}));
beforeEach(() => localStorage.clear());
it.each([['free', 'pro'], ['pro', 'free']])('does not reuse account A tier %s for account B tier %s', async (from, to) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(['subscription-status', 'a'], { tier: from });
  client.setQueryData(['subscription-status', 'b'], { tier: to });
  localStorage.setItem('user', JSON.stringify({ id: 'a' }));
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const { result, rerender } = renderHook(() => usePaidPlanWhenOpen(true), { wrapper });
  await act(async () => { await Promise.resolve(); });
  expect(result.current.isPaid).toBe(from !== 'free');
  localStorage.setItem('user', JSON.stringify({ id: 'b' }));
  rerender();
  await act(async () => { await Promise.resolve(); });
  expect(result.current).toEqual({ isPaid: to !== 'free', resolved: true });
});

it('cancels account A lookup and cannot apply its late answer over account B', async () => {
  const { subscriptionApi } = await import('../../lib/subscriptionApi');
  let answerA!: (value: {tier: string}) => void;
  let answerB!: (value: {tier: string}) => void;
  vi.mocked(subscriptionApi.getStatus)
    .mockReturnValueOnce(new Promise(resolve => { answerA = resolve as typeof answerA; }))
    .mockReturnValueOnce(new Promise(resolve => { answerB = resolve as typeof answerB; }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  localStorage.setItem('user', JSON.stringify({id: 'a'}));
  const wrapper = ({children}: {children: ReactNode}) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const {result, rerender} = renderHook(() => usePaidPlanWhenOpen(true), {wrapper});
  localStorage.setItem('user', JSON.stringify({id: 'b'}));
  rerender();
  await act(async () => { answerB({tier: 'pro'}); });
  expect(result.current).toEqual({isPaid: true, resolved: true});
  await act(async () => { answerA({tier: 'free'}); });
  expect(result.current).toEqual({isPaid: true, resolved: true});
});

it('does not carry account A paid tier into a failed lookup for account B', async () => {
  const { subscriptionApi } = await import('../../lib/subscriptionApi');
  vi.mocked(subscriptionApi.getStatus).mockRejectedValue(new Error('Unavailable'));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(['subscription-status', 'a'], {tier: 'pro'});
  localStorage.setItem('user', JSON.stringify({id: 'a'}));
  const wrapper = ({children}: {children: ReactNode}) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const {result, rerender} = renderHook(() => usePaidPlanWhenOpen(true), {wrapper});
  localStorage.setItem('user', JSON.stringify({id: 'b'}));
  rerender();
  await act(async () => { await Promise.resolve(); });
  expect(result.current).toEqual({isPaid: false, resolved: true});
});
