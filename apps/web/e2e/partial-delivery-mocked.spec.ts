import { test, expect } from '@playwright/test';
import { mockResponsiveApi, responsiveUser } from './fixtures-responsive';

const written = [{ id: 'draft-1', title: 'Lin Zhou', words: 120 }];
const unwritten = [{ id: 'draft-2', title: 'Zhou Nian' }];
const tools = [written[0], unwritten[0]].map(file => ({ id: `create-${file.id}`, name: 'create_file',
  arguments: { title: file.title }, status: 'success', result: { ...file, content: '', file_type: 'character' } }));
const saved = { id: 'partial-assistant', session_id: 'partial-session', role: 'assistant', content: '',
  created_at: '2026-10-14T14:00:00Z', tool_calls: JSON.stringify(tools), metadata: JSON.stringify({
    stop_outcome: { reason: 'error', charged: true, saved_output: true, written_files: written, unwritten_files: unwritten },
  }) };

const cases = [390, 768, 1440].flatMap(width => ['zh', 'en'].flatMap(language => ['light', 'dark'].map(theme => ({ width, language, theme, terminal: 'error' }))));
cases.push({ width: 390, language: 'en', theme: 'dark', terminal: 'done' });
for (const { width, language, theme, terminal } of cases) {
  test(`partial delivery stays accurate and usable at ${width} ${language} ${theme} ${terminal}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await mockResponsiveApi(page);
    await page.addInitScript(({ user, language, theme }) => {
      localStorage.setItem('zenstory-language', language);
      localStorage.setItem('zenstory-theme', theme);
      localStorage.setItem('user', JSON.stringify(user));
      localStorage.setItem('access_token', 'local-partial-fixture');
      localStorage.setItem('refresh_token', 'local-partial-fixture');
      localStorage.setItem('auth_validated_at', String(Date.now()));
    }, { user: responsiveUser, language, theme });
    let finished = false, submissions = 0;
    await page.route('**/api/v1/chat/session/*/recent**', route => route.fulfill({ json: finished ? [{ ...saved, metadata: JSON.stringify({ stop_outcome: { reason: terminal === 'done' ? 'incomplete' : 'error', charged: true, saved_output: true, written_files: written, unwritten_files: unwritten } }) }] : [] }));
    await page.route('**/api/v1/files/draft-1', route => route.fulfill({ json: { id: 'draft-1', project_id: 'responsive-project-0',
      title: 'Lin Zhou', file_type: 'character', content: 'Lin Zhou ' + 'story '.repeat(118),
      parent_id: null, order: 0, created_at: '2026-10-14T14:00:00Z', updated_at: '2026-10-14T14:00:00Z' } }));
    await page.route('**/api/v1/agent/stream', async route => {
      submissions++;
      const events: Array<[string, unknown]> = [];
      for (const tool of tools) events.push(['tool_call', { tool_use_id: tool.id, tool_name: tool.name, arguments: tool.arguments }],
        ['tool_result', { tool_use_id: tool.id, tool_name: tool.name, status: 'success', data: tool.result }]);
      events.push([terminal, { message: 'Upstream timed out', code: 'ERR_AGENT_UPSTREAM_TIMEOUT', retryable: true, assistant_message_id: saved.id, session_id: saved.session_id,
        written_files: written, unwritten_files: unwritten }]);
      finished = true;
      await route.fulfill({ contentType: 'text/event-stream', body: events.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join('') });
    });
    await page.goto('/project/responsive-project-0');
    if (width < 768) await page.locator('#chat-tab').click();
    const chat = page.locator('[data-testid="chat-panel"], #chat-panel');
    await page.getByTestId('chat-input').fill('Write two character sheets');
    await page.getByTestId('send-button').click();
    const savedText = language === 'zh' ? '已保存《Lin Zhou》120 字' : 'Saved "Lin Zhou" (120 words)';
    const unfinishedText = language === 'zh' ? '未确认保存《Zhou Nian》' : 'Save not confirmed: "Zhou Nian"';
    await expect(chat).toContainText(unfinishedText);
    if (terminal === 'error') {
      await expect(chat.getByRole('button', { name: language === 'zh' ? '重试' : 'Retry', exact: true })).toBeVisible();
      await expect(chat.getByTestId('round-end-note')).toHaveCount(0);
    } else {
      await expect(chat.getByTestId('round-end-note')).toHaveCount(1);
      await expect(chat.getByRole('button', { name: 'Retry', exact: true })).toHaveCount(0);
    }
    await expect(page.getByTestId('next-step-card')).toHaveCount(0);
    await page.getByTestId('chat-input').fill('Continue only Zhou Nian later');
    await expect(page.getByTestId('chat-input')).toHaveValue('Continue only Zhou Nian later');
    await page.screenshot({ path: `${process.env.AUDIT_SHOTS || test.info().outputDir}/partial-${width}-${language}-${theme}-${terminal}-live.jpg`, type: 'jpeg', fullPage: false });
    await chat.getByRole('button', { name: 'Lin Zhou', exact: true }).click();
    if (width < 768) await page.locator('#chat-tab').click();
    await expect(page.getByTestId('chat-input')).toHaveValue('Continue only Zhou Nian later');
    expect(submissions).toBe(1);
    await page.reload();
    if (width < 768) await page.locator('#chat-tab').click();
    await expect(page.getByTestId('round-end-note')).toContainText(unfinishedText);
    await expect(page.getByTestId('round-end-note')).toContainText(language === 'zh' ? savedText : 'Saved');
    expect(submissions).toBe(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `${process.env.AUDIT_SHOTS || test.info().outputDir}/partial-${width}-${language}-${theme}-${terminal}-history.jpg`, type: 'jpeg', fullPage: false });
  });
}
