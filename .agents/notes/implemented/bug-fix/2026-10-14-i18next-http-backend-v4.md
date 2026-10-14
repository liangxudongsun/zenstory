# 翻译 HTTP backend 升级到 4.0.2

## Problem

PR #149 的翻译加载依赖升级仍未进入 main，两份锁文件实际解析到 i18next-http-backend 3.0.6。上游 4.0.2 修复特殊语言/命名空间值的 URL 注入，并在 v4 删除 cross-fetch fallback。当前应用固定使用带前导路径的 `/locales/{{lng}}/{{ns}}.json`、限定中英两种语言，不满足公告所述模板注入前提；本次是依赖升级，不声称已复现应用攻击。

## Decision

将现有 web 依赖声明与 pnpm/npm 两份锁统一为 4.0.2。只更新目标包与移除不再引用的 cross-fetch、node-fetch 2 及其独占的 URL 解析依赖，保留其他包版本、peer 上下文和 workspace importer。沿用 CI/Docker 的 Node 20 和现代浏览器提供的 fetch，不加 polyfill、不改变本地化配置或界面。

补充一条真实本地 HTTP 回归：用实际中英 locale JSON，验证冷启动、切换到另一语言、切回后的已加载资源复用。已有语言入口优先级与切换组件测试继续使用，不以只验证 mock 回调代替加载传输。

## Alternatives considered

- 继续停在 v3：现配置不满足本次安全公告的触发条件，能避免主版本迁移；但已具备 v4 要求的运行环境，保留旧 fallback 没有现有产品需求，采用有界升级和实际加载验证。
- 整份采用旧 PR 的锁文件：曾有旧 CI 结果，操作直接；但包含与目标无关的 peer 上下文重排，也不能代替当前 main 验证，改为只调整目标依赖图并检查其他节点完全相同。
- 添加 fetch polyfill：可支持缺少 fetch 的旧宿主；当前支持环境已提供 fetch，新增依赖与兼容路径没有必要。

## Consequences

翻译文件仍经现有 HTTP 路径加载，中英文入口和本地存储优先级不变。应用不再为该依赖携带 cross-fetch fallback；不提供原来未声明支持的旧浏览器兼容承诺。未启用模型、访问生产或改变发布流程。

## Verification

新增真实 HTTP 回归先在 3.0.6 通过，再用与锁完整性一致的实际 4.0.2 包运行。相关四文件九项回归、i18n 键检查、ESLint、TypeScript 与完整构建通过；ESLint 只有既有 useAgentStream 未使用 disable warning。pnpm 10.29.3 的 frozen/offline lock 校验通过，结构化对比确认所有保留的包节点及非目标 importer 完全一致。本地 Chrome 另验证390宽中文、1440宽英文的冷启动及双向切换；两种locale的common/auth文件均返回200 JSON，没有脚本错误或横向溢出，没有API或模型请求。截图和详细验证保存在私有运行receipt；最终CI与部署由后续合并批次执行。

来源：[上游安全公告](https://github.com/i18next/i18next-http-backend/security/advisories/GHSA-xvq9-wjp8-hwqf)、[4.0.2 迁移说明](https://github.com/i18next/i18next-http-backend/blob/v4.0.2/README.md)。
