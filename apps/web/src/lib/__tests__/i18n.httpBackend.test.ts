import { createServer, type Server } from 'node:http';
import { readFile } from 'node:fs/promises';
import type { AddressInfo } from 'node:net';
import { resolve } from 'node:path';
import i18next from 'i18next';
import Backend from 'i18next-http-backend';
import { afterEach, describe, expect, it } from 'vitest';

describe('translation HTTP backend', () => {
  let server: Server | undefined;

  afterEach(async () => {
    if (!server) return;
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) => server!.close(error => error ? reject(error) : resolve()));
    server = undefined;
  });

  it('loads real locale JSON on a cold start and switches languages without a fetch polyfill', async () => {
    const requests: string[] = [];
    const localeFiles = new Map(await Promise.all(['zh', 'en'].map(async lang => [
      `/locales/${lang}/common.json`,
      await readFile(resolve('public/locales', lang, 'common.json'), 'utf8'),
    ] as const)));
    server = createServer((request, response) => {
      const path = request.url ?? '';
      if (request.method === 'GET') requests.push(path);
      const content = localeFiles.get(path);
      response.writeHead(content ? 200 : 404, {
        'content-type': 'application/json',
        'access-control-allow-origin': '*',
      });
      response.end(content ?? '{}');
    });
    await new Promise<void>(resolve => server!.listen(0, '127.0.0.1', resolve));
    const origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
    const instance = i18next.createInstance().use(Backend);

    await instance.init({
      lng: 'zh',
      fallbackLng: false,
      supportedLngs: ['zh', 'en'],
      ns: ['common'],
      defaultNS: 'common',
      backend: { loadPath: `${origin}/locales/{{lng}}/{{ns}}.json` },
    });
    expect(instance.t('language.zh')).toBe('中文');
    await instance.changeLanguage('en');
    expect(instance.t('language.en')).toBe('EN');
    await instance.changeLanguage('zh');
    expect(instance.t('language.zh')).toBe('中文');
    expect(requests).toEqual(['/locales/zh/common.json', '/locales/en/common.json']);
  });
});
