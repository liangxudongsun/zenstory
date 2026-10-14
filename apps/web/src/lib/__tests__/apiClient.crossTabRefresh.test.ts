import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../logger', () => ({ logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() } }));

const jwt = (claims: Record<string, unknown>) => `header.${btoa(JSON.stringify(claims))}.signature`;
const pair = (sub = 'owner', family = 'family', jti = 'old', expired = false) => ({
  accessToken: jwt({ sub, typ: 'access', exp: Date.now() / 1000 + 3600 }),
  refreshToken: jwt({ sub, family_id: family, jti, typ: 'refresh', exp: Date.now() / 1000 + (expired ? -10 : 86400) }),
});
const store = (tokens: ReturnType<typeof pair>) => {
  localStorage.setItem('access_token', tokens.accessToken);
  localStorage.setItem('refresh_token', tokens.refreshToken);
};

beforeEach(() => {
  vi.resetModules();
  localStorage.clear();
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 409 }));
});
afterEach(() => {
  Reflect.deleteProperty(navigator, 'locks');
  vi.unstubAllGlobals();
});

function pausedLock() {
  let release!: () => void;
  const ready = new Promise<void>(resolve => { release = resolve; });
  const request = vi.fn(async (_name: string, callback: () => Promise<boolean>) => {
    await ready;
    return callback();
  });
  Object.defineProperty(navigator, 'locks', { value: { request }, configurable: true });
  return { request, release };
}

describe('cross-tab refresh ownership', () => {
  it('uses the same-family result committed by the tab that owned the browser lock', async () => {
    const original = pair();
    const replacement = pair('owner', 'family', 'new');
    store(original);
    const lock = pausedLock();
    const { tryRefreshToken, resolveOwnedAuthSession } = await import('../apiClient');
    const pending = tryRefreshToken();
    try {
      expect(lock.request).toHaveBeenCalledOnce();
      store(replacement);
    } finally { lock.release(); }
    expect(await pending).toBe(true);
    expect(fetch).not.toHaveBeenCalled();
    expect(resolveOwnedAuthSession(original.accessToken, original.refreshToken)).toEqual(replacement);
  });

  it.each(['different-user', 'new-login-family', 'wrong-access-user', 'malformed', 'expired', 'logout'])(
    'does not adopt or overwrite %s while queued for the browser lock', async scenario => {
      const original = pair();
      store(original);
      const lock = pausedLock();
      const { tryRefreshToken, resolveOwnedAuthSession } = await import('../apiClient');
      const pending = tryRefreshToken();
      try {
        expect(lock.request).toHaveBeenCalledOnce();
        const replacement = scenario === 'different-user' ? pair('other')
          : scenario === 'new-login-family' ? pair('owner', 'new-family')
          : scenario === 'expired' ? pair('owner', 'family', 'new', true)
          : pair('owner', 'family', 'new');
        store(replacement);
        if (scenario === 'wrong-access-user') localStorage.setItem('access_token', pair('other').accessToken);
        if (scenario === 'malformed') localStorage.setItem('refresh_token', 'malformed');
        if (scenario === 'logout') localStorage.clear();
      } finally { lock.release(); }
      const before = [localStorage.getItem('access_token'), localStorage.getItem('refresh_token')];
      expect(await pending).toBe(false);
      expect(fetch).not.toHaveBeenCalled();
      expect([localStorage.getItem('access_token'), localStorage.getItem('refresh_token')]).toEqual(before);
      expect(resolveOwnedAuthSession(original.accessToken, original.refreshToken)).toBeNull();
    },
  );

  it('retries a late original 401 with the matching family already refreshed in another tab', async () => {
    const original = pair();
    const replacement = pair('owner', 'family', 'new');
    store(original);
    let respond!: (response: unknown) => void;
    vi.mocked(fetch).mockImplementationOnce(() => new Promise(resolve => { respond = resolve; }))
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ ok: true }) } as Response);
    const { apiCall } = await import('../apiClient');
    const pending = apiCall('/api/shared-session-probe');
    store(replacement);
    respond({ ok: false, status: 401, json: async () => ({}) });
    expect(await pending).toEqual({ ok: true });
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(vi.mocked(fetch).mock.calls.every(([, options]) => !options?.method || options.method === 'GET')).toBe(true);
    expect(vi.mocked(fetch).mock.calls[1][1]?.headers).toMatchObject({ Authorization: `Bearer ${replacement.accessToken}` });
  });

  it('preserves credentials on a rotation conflict when Web Locks are unavailable', async () => {
    const original = pair();
    store(original);
    const { tryRefreshToken } = await import('../apiClient');
    expect(await tryRefreshToken()).toBe(false);
    expect(fetch).toHaveBeenCalledOnce();
    expect(localStorage.getItem('refresh_token')).toBe(original.refreshToken);
    expect(localStorage.getItem('access_token')).toBe(original.accessToken);
  });
});
