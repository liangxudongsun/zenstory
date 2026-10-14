import { StrictMode } from 'react'
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QuotaBadge } from '../subscription/QuotaBadge'
import { ChatQuotaCard } from '../subscription/ChatQuotaCard'
import { UpgradePromptModal } from '../subscription/UpgradePromptModal'
import type { QuotaResponse } from '../../types/subscription'

const events = vi.hoisted(() => ({ expose: vi.fn(), click: vi.fn() }))
vi.mock('../../lib/upgradeAnalytics', () => ({ trackUpgradeExpose: events.expose, trackUpgradeClick: events.click }))
vi.mock('../../hooks/usePaidPlanWhenOpen', () => ({ usePaidPlanWhenOpen: () => ({ isPaid: false, resolved: true }) }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({
  i18n: { language: 'en' },
  t: (key: string, fallback?: string | Record<string, unknown>, options?: Record<string, unknown>) => {
    const values = typeof fallback === 'object' ? fallback : options
    const text = typeof fallback === 'string' ? fallback : String(fallback?.defaultValue ?? key)
    return text.replace(/{{(\w+)}}/g, (_, name: string) => String(values?.[name] ?? ''))
  },
}) }))

const resetAt = '2026-10-14T16:00:00Z'
const quota = (used = 3, reset = resetAt) => ({ ai_conversations: { used, limit: 3, reset_at: reset }, projects: { used: 1, limit: 3 } }) as QuotaResponse
const client = () => {
  const result = new QueryClient({ defaultOptions: { queries: { enabled: false, retry: false } } })
  result.setQueryData(['subscription-quota', 'a'], quota())
  result.setQueryData(['subscription-quota', 'b'], quota())
  return result
}
const flush = async () => { await act(async () => { await Promise.resolve() }) }
const body = (q: QueryClient, children: React.ReactNode) => <QueryClientProvider client={q}><StrictMode>{children}</StrictMode></QueryClientProvider>

beforeEach(() => { vi.stubGlobal('IntersectionObserver', undefined); Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' }); localStorage.setItem('user', JSON.stringify({ id: 'a' })); events.expose.mockClear() })
afterEach(async () => { cleanup(); await flush(); localStorage.removeItem('user'); vi.unstubAllGlobals() })

describe('upgrade visibility accounting', () => {
  it('classifies badge and card separately and coalesces a continuous remount and polling', async () => {
    const q = client()
    const first = render(body(q, <><QuotaBadge /><ChatQuotaCard limit={3} resetAt={resetAt} /></>))
    expect(events.expose.mock.calls.map(call => call[1])).toEqual(['badge', 'card'])
    first.unmount()
    render(body(q, <><QuotaBadge /><ChatQuotaCard limit={3} resetAt={resetAt} /></>))
    await act(async () => { q.setQueryData(['subscription-quota', 'a'], quota()) })
    expect(events.expose).toHaveBeenCalledTimes(2)
  })

  it('records a real disappearance and reappearance instead of deduping the whole session', async () => {
    const q = client()
    const first = render(body(q, <ChatQuotaCard limit={3} resetAt={resetAt} />))
    first.unmount()
    await flush()
    render(body(q, <ChatQuotaCard limit={3} resetAt={resetAt} />))
    expect(events.expose).toHaveBeenCalledTimes(2)
  })

  it('isolates account, quota period, stage, and placement', async () => {
    const q = client()
    const view = render(body(q, <QuotaBadge />))
    localStorage.setItem('user', JSON.stringify({ id: 'b' }))
    view.rerender(body(q, <QuotaBadge />))
    await act(async () => { q.setQueryData(['subscription-quota', 'b'], quota(2)) })
    await waitFor(() => expect(events.expose).toHaveBeenCalledTimes(3))
    await act(async () => { q.setQueryData(['subscription-quota', 'b'], quota(2, '2026-10-15T16:00:00Z')) })
    await waitFor(() => expect(events.expose).toHaveBeenCalledTimes(4))
    view.rerender(body(q, <><QuotaBadge /><QuotaBadge compact /></>))
    expect(events.expose).toHaveBeenCalledTimes(5)
  })

  it('does not count a badge outside the viewport until it becomes visible', async () => {
    let notify!: IntersectionObserverCallback
    vi.stubGlobal('IntersectionObserver', class { constructor(callback: IntersectionObserverCallback) { notify = callback } observe() {} disconnect() {} })
    render(body(client(), <QuotaBadge />))
    expect(events.expose).not.toHaveBeenCalled()
    await act(async () => { notify([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver) })
    expect(events.expose).toHaveBeenCalledTimes(1)
  })

  it('keeps an observed surface continuous across asynchronous observer initialization after remount', async () => {
    let notify!: IntersectionObserverCallback
    vi.stubGlobal('IntersectionObserver', class { constructor(callback: IntersectionObserverCallback) { notify = callback } observe() {} disconnect() {} })
    const q = client()
    const first = render(body(q, <QuotaBadge />))
    await act(async () => { notify([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver) })
    first.unmount()
    render(body(q, <QuotaBadge />))
    await flush()
    await act(async () => { notify([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver) })
    expect(events.expose).toHaveBeenCalledTimes(1)
    await act(async () => { notify([{ isIntersecting: false } as IntersectionObserverEntry], {} as IntersectionObserver) })
    await flush()
    await act(async () => { notify([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver) })
    expect(events.expose).toHaveBeenCalledTimes(2)
  })

  it('counts modal reopen separately but not StrictMode or continuous remount', async () => {
    const props = { open: true, onClose: vi.fn(), title: 'Limit', description: 'Wait for reset', primaryLabel: 'Pro', onPrimary: vi.fn(), source: 'chat_quota_blocked' }
    const first = render(body(client(), <UpgradePromptModal {...props} />))
    expect(screen.getByRole('dialog')).toBeVisible()
    first.unmount()
    const view = render(body(client(), <UpgradePromptModal {...props} />))
    expect(events.expose).toHaveBeenCalledTimes(1)
    view.rerender(body(client(), <UpgradePromptModal {...props} open={false} />))
    await flush()
    view.rerender(body(client(), <UpgradePromptModal {...props} />))
    expect(events.expose).toHaveBeenCalledTimes(2)
  })
})
