# ZenStory 仓库文档

按使用场景选择入口。用户指南与网站共用一份内容源；这里维护开发、部署和运维说明。

## 使用工作台

- [中文用户指南](../apps/web/docs/README.md) · [English user guide](../apps/web/docs/en/README.md)
- [在线文档](https://zenstory.ai/docs)：与上述 Markdown 内容源对应
- [网页快速入门](../apps/web/docs/getting-started/quick-start.md)
- [编辑、保存与草稿恢复](../apps/web/docs/user-guide/editor.md)
- [订阅权益](../apps/web/docs/user-guide/billing-benefits.md)

## 开发与维护

| 指南 | 用途 |
| --- | --- |
| [开发入口](development/README.md) | 仓库结构、运行与检查命令 |
| [E2E 与 CI](development/e2e.md) | 本地测试入口、线上门禁与失败定位 |
| [异步页面状态](ui-async-state-standard.md) | 加载、空态、错误和后台刷新 |
| [写作配置维护](agent-writing-guidance.md) | 数据库提示词、官方技能与内容更新 |
| [网站内容维护](content/README.md) | 指南内容源、编辑流程和批次记录 |
| [截图说明](screenshots/README.md) | 现有图片用途与更新方法 |

## 部署与运维

- [Docker Compose](docker-compose.md)：本地快速启动与自托管完整部署
- [发布流程](ops/release-ci-cd.md)：CI、预发布、生产 tag、迁移与 worker 排空
- [域名与静态页面路由](ops/domain-migration.md)：组织站、工作台和 API 的边界

## 历史记录

[历史目录](archive/README.md)汇总日期化设计、实施计划、QA 和内容批次。记录只证明当时的方案或验证，不代表当前线上状态，也不作为待执行任务。

新行为决策遵循根目录 [AGENTS.md](../AGENTS.md)，记录在 `.agents/notes/`。当前 UI 规范见 [DESIGN.md](../DESIGN.md)。
