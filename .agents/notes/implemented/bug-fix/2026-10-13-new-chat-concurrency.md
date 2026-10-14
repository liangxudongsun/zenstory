# 新对话创建的并发与失败恢复

## Problem

#193：重复点击新对话会重叠 POST，部分唯一索引只保护一个活动会话，读后插入的竞态仍返回 409；失败时界面和服务端活动会话可能脱节。

## Decision

前端用同步 ref 加可见 pending 状态拦截重复点击，创建完成前暂停发送，保留可继续编辑的草稿。创建失败时提示并只读重新加载当前活动会话历史，读失败则显示重试并暂停发送，不自动重试创建或模型请求。继续保留项目切换、卸载和中途停止的请求代际保护。

PostgreSQL 的新建/获取、Agent requested-id 解析、MessageManager 无 session-id 兜底共用 user+project 事务 advisory lock，在活动会话读写之前取得，提交或回滚后释放；不新增 Session，不代替 owning helper 的事务提交。SQLite 不增加锁或改变既有提前提交。审计全部 ChatSession 构造点；Loader 与建议服务只读取/修复旧数据，不创建会话。

## Alternatives considered

- 只禁用按钮最小，但多标签页和其他创建路径仍可能冲突；前后端都修。
- 仅捕获 IntegrityError 再读活动会话无需协作锁，但破坏 owning transaction 并可能掩盖其他完整性错误；使用按账号项目串行化，保留真正的错误。
- 锁全局或整张表更简单，但不同作者、不同项目互不相关；用事务级分组锁。

## Consequences

无需迁移，不变更历史、额度、在途结算或 requested session-id 的归属规则。测试先复现客户端重复提交和真实 PostgreSQL 唯一索引冲突，再验证所有活动创建路径与跨项目请求边界。

## Verification

客户端同步双击与失败后活动历史恢复回归先失败后通过；StrictMode 与普通挂载共 28 个真实 ChatPanel 生命周期案例通过，含失败读重试只 GET、输入保留与旧项目响应隔离。受影响前端回归 203 项通过。独占本地 PostgreSQL 17 临时库以部分唯一索引和真实 SQL 读交错先复现九种 409/UniqueViolation，修复后 13 种组合通过，含 requested-id 新建/重新激活与显式旧 session 消息在途保存；不调用模型。SQLite/API/Agent/MessageManager 44 项已有回归通过。CI 的独立串行 PostgreSQL lane 纳入并发测试，默认未配置显式测试库时跳过。完整 typecheck/build、受影响 ESLint/Ruff 与 token/i18n 检查通过。
