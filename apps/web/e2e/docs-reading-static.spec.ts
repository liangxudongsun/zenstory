import { test, expect } from './fixtures/static-site';
import AxeBuilder from '@axe-core/playwright';
import { docsNavigation } from '../src/data/docsNavigation';

const routes = ['/docs', ...docsNavigation.flatMap(section => section.children?.map(item => item.path) ?? [])];
test.use({ javaScriptEnabled: false });
test.beforeEach(async ({ page }) => {
  await page.route('https://fonts.googleapis.com/**', route => route.fulfill({ contentType: 'text/css', body: '' }));
  await page.route('https://fonts.gstatic.com/**', route => route.abort());
});

for (const width of [390, 1280]) {
  test(`all documentation reads within ${width}px without app JavaScript`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    for (const route of routes) {
      await test.step(route, async () => {
        await page.goto(route + '/');
        await expect(page.locator('#zh h1')).toBeVisible();
        await expect(page.locator('#en h2').first()).toBeAttached();
        expect(await page.evaluate(() => document.documentElement.scrollWidth), route).toBeLessThanOrEqual(width);
        const title = await page.locator('#zh h1').boundingBox();
        expect(title!.y, `${route}: title reachable before scrolling`).toBeLessThan(500);
        for (const lang of ['zh', 'en']) {
          const text = await page.locator(`#${lang}`).innerText();
          expect(text.trim().length, `${route}: ${lang} article`).toBeGreaterThan(40);
        }
      });
    }
    expect(errors).toEqual([]);
  });
}

test('phone contents opens by keyboard and English links keep the reading language', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/docs/');
  const contents = page.locator('.docs-mobile-index');
  await contents.locator('summary').press('Enter');
  await expect(contents).toHaveAttribute('open', '');
  await contents.getByRole('link', { name: '编辑器使用', exact: true }).click();
  await expect(page).toHaveURL(/\/docs\/user-guide\/editor$/);
  await page.getByRole('link', { name: 'EN', exact: true }).click();
  await page.locator('#en').getByRole('link', { name: 'AI assistant', exact: true }).click();
  await expect(page).toHaveURL(/\/docs\/user-guide\/ai-assistant#en$/);
  await expect(page.locator('#en h2').first()).toBeInViewport();
 });

test.describe('Documentation accessibility', () => {
  test.use({ javaScriptEnabled: true });
  test('editor guide has no serious accessibility violations on phone and desktop', async ({ page }) => {
    for (const width of [390, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto('/docs/user-guide/editor/');
      const audit = await new AxeBuilder({ page }).analyze();
      expect(audit.violations.filter(v => ['critical', 'serious'].includes(v.impact ?? '')).map(v => v.id)).toEqual([]);
    }
  });
});
