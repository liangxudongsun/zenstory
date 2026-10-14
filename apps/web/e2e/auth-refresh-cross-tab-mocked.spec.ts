import { expect, test, type BrowserContext, type Page } from '@playwright/test';

type Client = Pick<typeof import('../src/lib/apiClient'), 'apiCall' | 'tryRefreshToken' | 'resolveOwnedAuthSession'>;
type ProbeWindow = Window & { authProbe: Client; pendingAuthProbe: Promise<unknown> };
const jwt = (claims: Record<string, unknown>) => `header.${Buffer.from(JSON.stringify(claims)).toString('base64url')}.signature`;
const pair = (sub = 'owner', family = 'family', jti = 'old') => ({
  accessToken: jwt({ sub, typ: 'access', exp: Date.now() / 1000 + 3600, jti }),
  refreshToken: jwt({ sub, family_id: family, jti, typ: 'refresh', exp: Date.now() / 1000 + 86400 }),
});

async function loadProbe(page: Page) {
  await page.goto('/__refresh_probe');
  await page.evaluate(async () => {
    const modulePath = '/src/lib/apiClient.ts';
    (window as ProbeWindow).authProbe = await import(modulePath);
  });
  expect(await page.evaluate(() => Boolean(navigator.locks))).toBe(true);
}

async function mockRefresh(context: BrowserContext) {
  const original = pair();
  const rotated = pair('owner', 'family', 'rotated');
  let entered!: () => void;
  let release!: () => void;
  const started = new Promise<void>(resolve => { entered = resolve; });
  const gate = new Promise<void>(resolve => { release = resolve; });
  const requests: unknown[] = [];
  await context.route('**/__refresh_probe', route => route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>Authentication probe</title>' }));
  await context.route('**/api/auth/refresh', async route => {
    requests.push(route.request().postDataJSON());
    entered();
    await gate;
    await route.fulfill({ status: requests.length === 1 ? 200 : 401, contentType: 'application/json', body: JSON.stringify({
      access_token: rotated.accessToken, refresh_token: rotated.refreshToken, user: { id: 'owner', username: 'writer' },
    }) });
  });
  await context.route('**/api/refresh-probe', route => {
    const ownsNew = route.request().headers().authorization === `Bearer ${rotated.accessToken}`;
    return route.fulfill({ status: ownsNew ? 200 : 401, contentType: 'application/json', body: JSON.stringify({ ok: ownsNew }) });
  });
  return { original, rotated, requests, started, release };
}

async function store(page: Page, tokens: ReturnType<typeof pair> | null) {
  await page.evaluate(value => {
    if (!value) { localStorage.clear(); return; }
    localStorage.setItem('access_token', value.accessToken);
    localStorage.setItem('refresh_token', value.refreshToken);
  }, tokens);
}

async function start(page: Page, apiCall = false) {
  await page.evaluate(callApi => {
    const probe = window as ProbeWindow;
    probe.pendingAuthProbe = callApi ? probe.authProbe.apiCall('/api/refresh-probe') : probe.authProbe.tryRefreshToken();
  }, apiCall);
}

async function waitForQueuedTab(page: Page) {
  await expect.poll(() => page.evaluate(async () => (await navigator.locks.query()).pending?.filter(lock => lock.name === 'zenstory-auth-refresh').length)).toBe(1);
}

test('two real tabs recover their original API request with one native browser-locked refresh', async ({ context, page }) => {
  const mock = await mockRefresh(context);
  const other = await context.newPage();
  await Promise.all([loadProbe(page), loadProbe(other)]);
  await store(page, mock.original);
  try {
    await start(page, true);
    await mock.started;
    await start(other, true);
    await waitForQueuedTab(page);
  } finally { mock.release(); }
  const results = await Promise.all([page, other].map(tab => tab.evaluate(() => (window as ProbeWindow).pendingAuthProbe)));
  expect(results).toEqual([{ ok: true }, { ok: true }]);
  expect(mock.requests).toEqual([{ refresh_token: mock.original.refreshToken }]);
  for (const tab of [page, other]) {
    expect(await tab.evaluate(original => (window as ProbeWindow).authProbe.resolveOwnedAuthSession(original.accessToken, original.refreshToken), mock.original)).toEqual(mock.rotated);
  }
});

for (const change of ['logout', 'other-user', 'new-login-family'] as const) {
  test(`queued tab cannot restore or overwrite ${change}`, async ({ context, page }) => {
    const mock = await mockRefresh(context);
    const other = await context.newPage();
    await Promise.all([loadProbe(page), loadProbe(other)]);
    await store(page, mock.original);
    const replacement = change === 'logout' ? null : change === 'other-user' ? pair('other') : pair('owner', 'new-family');
    try {
      await start(page);
      await mock.started;
      await start(other);
      await waitForQueuedTab(page);
      await store(page, replacement);
    } finally { mock.release(); }
    expect(await Promise.all([page, other].map(tab => tab.evaluate(() => (window as ProbeWindow).pendingAuthProbe)))).toEqual([false, false]);
    expect(mock.requests).toHaveLength(1);
    expect(await page.evaluate(() => ({ accessToken: localStorage.getItem('access_token'), refreshToken: localStorage.getItem('refresh_token') }))).toEqual(replacement ?? { accessToken: null, refreshToken: null });
  });
}
