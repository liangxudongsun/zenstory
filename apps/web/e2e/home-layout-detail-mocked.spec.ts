import { test, expect } from '@playwright/test';
import { mockResponsiveApp, responsiveUser } from './fixtures-responsive';

const widths = [320, 390, 768, 1024, 1280, 1920];

for (const width of [390, 768, 1920]) {
  test(`a long account name leaves room for quota at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockResponsiveApp(page);
    const user = { ...responsiveUser, nickname: 'StorywriterWithAVeryLongUnbrokenDisplayName' };
    await page.addInitScript(user => localStorage.setItem('user', JSON.stringify(user)), user);
    await page.route('**/api/auth/me', route => route.fulfill({ json: user }));
    await page.goto('/dashboard');
    await expect(page.locator('h1')).toContainText(user.nickname);
    const heading = (await page.locator('h1').boundingBox())!;
    const section = (await page.locator('.dashboard-start').boundingBox())!;
    expect(heading.x).toBeGreaterThanOrEqual(section.x);
    expect(heading.x + heading.width).toBeLessThanOrEqual(section.x + section.width);
    expect(await page.locator('h1').evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    if (width >= 768) {
      const quota = (await page.getByText('今日 AI 消息', { exact: false }).boundingBox())!;
      expect(heading.x + heading.width + 12).toBeLessThanOrEqual(quota.x);
    }
  });
}

for (const width of widths) {
  test(`dashboard sections share the same edges at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockResponsiveApp(page);
    await page.goto('/dashboard');
    await expect(page.getByTestId('project-card').first()).toBeVisible();
    const start = (await page.locator('.dashboard-start').boundingBox())!;
    const composer = (await page.getByTestId('dashboard-composer').boundingBox())!;
    const projects = (await page.getByTestId('project-card').first().locator('..').boundingBox())!;
    for (const area of [composer, projects]) {
      expect(Math.abs(area.x - start.x)).toBeLessThanOrEqual(1);
      expect(Math.abs(area.x + area.width - start.x - start.width)).toBeLessThanOrEqual(1);
    }
    const formats = await page.locator('[data-tour-id="dashboard-project-type-tabs"] button').all();
    const action = (await page.getByTestId('create-project-button').boundingBox())!;
    for (const format of formats) {
      const bounds = (await format.boundingBox())!;
      const separated = bounds.x + bounds.width <= action.x || action.x + action.width <= bounds.x || bounds.y + bounds.height <= action.y || action.y + action.height <= bounds.y;
      expect(separated).toBe(true);
    }
  });

  for (const language of ['zh', 'en']) {
    test(`demo controls have distinct spacing at ${width}px in ${language}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.emulateMedia({ reducedMotion: 'no-preference' });
      await page.addInitScript(lang => localStorage.setItem('zenstory-language', lang), language);
      await page.goto('/');
      const pause = page.getByRole('button', { name: language === 'zh' ? '暂停演示' : 'Pause demo', exact: true });
      await pause.click();
      const resume = page.getByRole('button', { name: language === 'zh' ? '继续演示' : 'Resume demo', exact: true });
      await expect(resume).toBeVisible();
      const bounds = (await resume.boundingBox())!;
      const scenes = await page.locator('[role="region"] button[aria-pressed]').all();
      expect(scenes).toHaveLength(3);
      for (const scene of scenes) {
        const box = (await scene.boundingBox())!;
        expect(bounds.y - box.y - box.height).toBeGreaterThanOrEqual(12);
      }
      await scenes[2].click();
      await expect(scenes[2]).toHaveAttribute('aria-pressed', 'true');
      await resume.click();
      await expect(pause).toBeVisible();
    });
  }
}
