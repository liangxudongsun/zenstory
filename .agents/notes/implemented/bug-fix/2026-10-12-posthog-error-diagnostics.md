# 近期 PostHog 错误修复与归因

## Problem

近七天 83 条事件中，31 条通用流错误无法保留失败阶段；部分样本服务端已完成或记录客户端断开，不能当作模型失败。24 条 DOM 错误中的技能页帧定位到 PublicSkillCard 条件裸文本：浏览器翻译替换文本节点后 React 删除旧节点触发 NotFoundError。7 条资源加载失败中旧 Admin chunk 已返回 HTML；OAuth 早期 state 拒绝没有细分原因，安全校验不可放宽。

## Decision

技能按钮动态文字用稳定元素承载，并用真实 DOM 的翻译替换回归验证。流式错误仅记录 fetch/read/parse/callback/response 阶段、白名单异常类型与 request/run ID，不记录原始错误文本或用户内容；已中止 signal 视为取消，继续保护余额清算和最后 SSE 帧。支持 Firefox 动态 import 错误识别，保留草稿保护和单次重载。OAuth 失败返回固定阶段和关联 ID，前端只收白名单、先清理 URL，再上报。

## Alternatives considered

- 全局修改 DOM 删除或吞掉所有 DOM 错误：能掩盖崩溃，但会让 React 状态与 DOM 脱节；只修复已复现的组件边界。
- 自动重试生成请求：可以遮住短暂断线，但可能重复付费和写作；不采用。
- 放宽 OAuth nonce/cookie：可能减少早期拒绝，却破坏 CSRF 保护；只提升定位能力。

## Consequences

修复可复现问题，剩余网络/浏览器错误能区分阶段；历史通用事件不能倒推出缺失的原始原因，不宣称全部是服务端失败。
