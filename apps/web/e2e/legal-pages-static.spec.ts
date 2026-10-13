import { test, expect } from '@playwright/test';

// Run against the finalized build, not the Vite development SPA.
test.use({ javaScriptEnabled: false });

for (const path of ['/privacy-policy', '/terms-of-service']) {
  for (const width of [390, 1440]) {
    test(`${path} has a styled first paint and an app-home logo at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.route('https://fonts.googleapis.com/**', route => route.fulfill({ contentType: 'text/css', body: '' }));
      await page.route('https://fonts.gstatic.com/**', route => route.abort());
      await page.route('**/org/org.css', async route => {
        await new Promise(resolve => setTimeout(resolve, 600));
        await route.continue();
      });
      const requests: string[] = [];
      page.on('request', request => requests.push(request.url()));
      await page.goto(path + '/');
      const title = path === '/privacy-policy' ? '隐私政策' : '服务条款';
      await expect(page.getByRole('heading', { level: 1, name: title, exact: true })).toBeVisible();
      await expect(page.locator('#legal-zh')).toBeVisible();
      await expect(page.locator('main')).not.toContainText('[object Object]');
      if (path === '/privacy-policy') await expect(page.getByRole('heading', { name: '2.2 内容数据', exact: true })).toBeAttached();
      await expect(page.locator('#legal-en')).toBeAttached();
      await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(245, 241, 231)');
      await expect.poll(() => page.evaluate(() => {
        const paint = performance.getEntriesByName('first-contentful-paint')[0];
        const css = performance.getEntriesByType('resource').find(entry => entry.name.endsWith('/org/org.css')) as PerformanceResourceTiming | undefined;
        return Boolean(paint && css && paint.startTime >= css.responseEnd);
      })).toBe(true);
      expect(await page.locator('h1').evaluate(el => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(30);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      expect(requests.filter(url => /\/assets\/.*\.js|\/api\//.test(url))).toEqual([]);
      await page.getByRole('link', { name: 'EN', exact: true }).click();
      await expect(page).toHaveURL(/#legal-en$/);
      const logo = page.locator('header .brand');
      await expect(logo).toHaveAttribute('href', 'https://app.zenstory.ai/');
      await page.route('https://app.zenstory.ai/', route => route.fulfill({ contentType: 'text/html', body: '<main>Workbench home</main>' }));
      await logo.click();
      await expect(page).toHaveURL('https://app.zenstory.ai/');
    });
  }
}
