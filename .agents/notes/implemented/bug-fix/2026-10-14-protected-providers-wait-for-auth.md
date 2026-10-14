# 受保护路由先确认身份，再挂载数据 Provider

## Problem

#181 的切号验收在 staging 两次观察到：工作台账号菜单退出后，立即在登录表单输入另一有效账号，按钮短暂显示登录中，随后恢复可点且没有错误；刷新仍未登录，完整刷新后再登录则成功。HTTP 记录显示退出后出现一次 subscription/me 401，随后 login 200。这个时序在旧认证边界中已可发生，不归因为 #223 新增的偏好逻辑。

四条受保护 route 将 ProtectedProviders 放在 ProtectedRoute 外。退出时 AuthIdentityQueryBoundary 用 anonymous key 重挂当前树，MaterialLibraryProvider 的权益 query 尚未被路由阻挡，发出无凭据订阅请求。若该 401 在新登录仍等待响应时由客户端处理，apiClient 的 missing_token 清理发出 auth:logout，递增认证代次；随后成功登录响应被正确的过期请求检查拒绝，Login 又按现有约定静默忽略 AbortError。

真实 App 回归已捕获事件顺序：user_initiated 登出 → anonymous subscription 请求 → B login 请求 → missing_token 登出 → login 成功响应消费。结果停留 /login，认证存储为空。页面、菜单、Provider、Router 和 API client 均用真实实现，只替换 HTTP/统计边界。

相关决定：[登出后的回跳目标按账号归属](2026-10-10-relogin-return-target-owner.md)。账号回跳归属与晚响应隔离继续保留。

## Decision

将 Dashboard、ProjectEditor、ProjectDashboardPage、MaterialDetailPage 四条同构 route 改为 ProtectedRoute 包住 ProtectedProviders。先完成身份与原有引导检查，再挂载会发账号请求的数据 Provider；未登录时直接执行原有登录跳转。

ProtectedRoute 只依赖认证、位置、翻译与 persona query，不依赖这些 Provider 的 context。AuthProvider 仍在身份边界上方，认证代次、显式退出、401 刷新、回跳 attempt 和最新会话隔离均不改。不重试登录，不强制刷新，不新增状态或依赖。

## Alternatives considered

- **无凭据请求的 401 只 reject，不广播登出。** 能在 API client 层阻止匿名失败取消正在建立的登录；但本次已有明确误挂载来源，直接修正路由顺序可避免无意义的受保护请求，并保留现有缺失凭据清理合同。
- **只给素材库权益 query 增加 user 条件。** 改动集中且能挡住已观察到的请求；但 Provider 本就只属于受保护页，其他账号副作用同样应在身份确认后挂载。现有外层路由检查已经表达这个边界，无需各 hook 重复增加认证判断。
- **忽略 auth:logout 或重试登录。** 能掩盖这次静默取消；但会破坏真实退出和更新认证请求对旧响应的隔离，或重复提交登录，因此不采用。

## Consequences

收益：退出期间不再创建匿名订阅请求，新登录不会被这条旧路由副作用取消。代价：首次进入受保护页时，项目和权益加载要等引导状态确认后再开始，失去此前的一部分并行；不增加请求。

## Verification

先补 actual App + Dashboard 菜单回归，strict 与非 strict 均在修复前复现上述完整事件链，成功 HTTP 响应之后认证仍为空。修复后两种模式都完成唯一一次 B login，进入 dashboard、持久认证归 B；匿名阶段订阅请求为零，只有显式退出事件。既有返回目标、真实退出取消 pending login、晚到旧账号响应隔离继续验证。

6 个相关测试文件 212 项通过（App 实际续接、guards、Provider、文件重开、AuthContext 生命周期、API client 会话隔离）；受影响文件 ESLint、build:typecheck（tsc -b、Vite 和静态页面构建）、git diff --check 通过。未缓存身份的旧 eager 前提已改为验证认证前不发订阅请求；缓存身份的 A1 旋转及旧初始化晚到隔离仍保留。
