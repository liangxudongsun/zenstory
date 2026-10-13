# 保留工作台内文档，共用内容来源

## Problem

用户要求保留 App 的文档。现有正式域名规则把 app.zenstory.ai/docs 强制跳到组织站；React 阅读器及搜索虽仍在代码中，线上却无法使用。组织站静态文档仍适合公开阅读和非 JS 抓取。

## Decision

两边保留阅读入口，共用 apps/web/docs 的同一套中英文 Markdown 与 docsNavigation。App 使用现有 React DocsPage、搜索和语言设置；组织站保留完整静态双语阅读器。docs 成为共享路由，取消生产和预发布 App 到组织站的强制跳转。Vercel 成品将组织站静态正文移入 _site/docs，通过组织域名专用重写读取；App 的 /docs 留给 SPA，避免文件系统静态页抢占。公开索引规范地址仍指向组织站，保持既有公开 URL。

这是对 [工作台文档静态组织壳](../architecture/2026-09-14-workbench-docs-on-org-shell.md) 中“React 阅读器只保留给开发构建”决定的调整。其静态公开阅读与构建期死链检查继续保留。

## Alternatives considered

- App 只链接组织站：维护和部署简单，但用户明确要求工作台保留自己的文档。
- 组织站只链接 App：只剩一个阅读地址，但既有公开文档 URL 与无需 JS 的完整正文会丢失。
- 两边维护独立副本：可各自定制，但操作说明会再次漂移，重复维护无益。

## Consequences

用户在当前站点内阅读，内容只维护一次。构建多一个静态目录搬移与按域名重写；回归检查须同时覆盖应用路由和静态组织文档。配额、权限、存储与发布规则不变。
