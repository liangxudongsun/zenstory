# Agent Note: 法律页面首屏与工作台 Logo 返回路径

## Problem

用户报告 `/privacy-policy` 和 `/terms-of-service` 打开时闪现 plain text，左上角 Logo 返回组织站。`build-site-layout.mjs` 将没有布局的英文 `<main><article>` 填进应用壳，React 随后重新渲染中文页面；`PublicHeader` 的 `/` 在组织站域名下自然落到组织首页。

## Decision

- 生产构建的两个法律 URL 直接输出完整静态页，复用现有 `site-shell.mjs` 与阻塞加载的 `/org/org.css`，不带 React 应用 bundle，不再替换首屏正文。
- 沿用工作台文档的单 URL 双语阅读方式，中文正文在前、完整英文正文在后，标记各自 lang，语言入口指向正文锚点。文本从已有两份 `privacy.json` 读取，条款内容不改写；canonical 和域名边界保持不变。
- 共享站点壳允许单页指定顶部品牌链接，仅法律页指向工作台首页，组织页保留原链接。React PublicHeader 用同一域名配对规则决定 Logo 返回路径，官网返回 app，预览官网返回 app-preview，本地与工作台保持站内首页。
- 截图检查发现旧预渲染器把 `subsections.content` 对象当作字符串，输出 `[object Object]` 并漏掉 2.2 内容数据。只把字符串 content 当正文，对象继续递归，补回原有小节和列表；回归覆盖正文完整性与转义。

## Alternatives considered

- **仅给预渲染正文加样式。** 最强理由是改动最少、保留 React 切换语言。拒绝：仍会从构建期英文内容跳到浏览器语言内容，正文和导航也会重新布局；法律阅读不需要应用运行时。
- **把法律 URL 改到 app 域名。** 最强理由是所有相对链接自然回到工作台。拒绝：现有公开 canonical、注册条款链接和索引 URL 都应保留；独立调整 Logo 即可。

## Consequences

收益：无 JavaScript 也可阅读完整双语条款，首屏样式和导航稳定，Logo 返回预期工作台。代价：部署版法律页采用现有组织站阅读样式，语言切换滚动到对应正文；开发模式保留原 React 页。延续 [静态文档决定](../architecture/2026-09-14-workbench-docs-on-org-shell.md) 的方式，法律页成为相同的单 URL 双语例外。

另发现现有服务条款第 7 条仍写默认自动续费，与产品展示的一次性付款不一致。本批保持原文，只修渲染和导航；法律文案需另行修订。

## Verification

- `node --test .../site-layout.test.mjs .../org-pages.test.mjs`：25 项通过，覆盖双语正文、嵌套 content 小节、转义、无应用脚本、阻塞样式表与品牌链接，组织页合同保持通过。
- `vitest run .../site-domain.test.ts .../PublicHeader.test.tsx`：16 项通过，覆盖生产、预览、本地工作台首页配对与现有导航行为。
- `legal-pages-static.spec.ts` 在本地最终构建、已安装 Chrome 上 4 项通过：两页 × 390/1440px，关闭 JavaScript，延迟 CSS 600ms，断言 first-contentful-paint 不早于 CSS responseEnd，并实点品牌链接至 app 根地址（目的页面使用测试响应）。
- ESLint、token/i18n lint、`build:typecheck` 和 domain finalizer 通过。截图存于 Codex visualization 的 `zenstory-ui` 目录。未运行云端 CI 或部署。
