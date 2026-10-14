# Agent Note: 缺失构建资源保留真实 404

## Problem

#215 中两个过期的 `/assets/AdminRoute-*.js` 返回 `200 text/html`。Vercel 的文件查找未命中后，应用域名的最终 SPA rewrite 把资源请求交给了应用 HTML，触发模块 MIME 错误。

## Decision

在现有最终 rewrite 的排除项中加入完整的 `assets` 路径段。存在的构建资源继续由文件系统提供；缺失资源不再匹配 SPA fallback，由平台返回 404。生成并提交对应 `vercel.json`，契约测试覆盖两个实际失败路径、嵌套资源和 App 深链，以及正式/预览域名边界。

延续 [刷新前保留草稿](2026-10-07-editor-draft-recovery-on-chunk-reload.md) 的既有 Vite 权威错误入口、单次重载与同步快照，不扩大错误文案匹配或引入资产缓存。

## Alternatives considered

- **增加 MIME 错误文案匹配。** 最强理由：直接识别事件里出现的浏览器错误。未采用：现有 `vite:preloadError` 已按权威信号触发恢复，文案匹配不能纠正服务器把脚本回退成 HTML 的路由错误。
- **保留所有旧构建资源。** 最强理由：旧页面可以继续加载此前版本的模块。未采用：需要额外资源保存和清理策略，超出本次静态资源回退修复；现有恢复路径负责版本切换。

## Consequences

缺失模块获得准确 HTTP 状态，正常 App 深链和其他路由继续沿用现有规则。配置契约与真实构建的本地浏览器验证不能替代 Vercel Preview 对最终 SHA 的资源/MIME、深链和保护验收；生产推广仍遵循独立发布授权。
