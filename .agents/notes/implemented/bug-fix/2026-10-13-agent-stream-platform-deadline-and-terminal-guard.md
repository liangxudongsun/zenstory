# Agent 流时限对齐平台连接上限，终态后的尾流异常不再改写结果

Status: implemented（issue #183）

## Problem

- `AGENT_RUN_WALL_CLOCK_TIMEOUT_S` 默认 1200 秒，Railway staging 与 production 均未覆盖。Railway 公开 HTTP 连接最多 15 分钟，持续传输或心跳也不能延长。正式站前端直连 `api.zenstory.ai`，运行超过 15 分钟时平台先断开，应用的 `ERR_AGENT_RUN_TIMEOUT` 终态、结算与 `quota_refunded` 帧来不及送达，前端只得到通用读取错误。
- `agentApi.ts` 收到 `done` 或服务端 `error` 后仍要继续读尾帧（`quota_refunded`）。这时连接被重置，`reader.read()` 拒绝，catch 只判断取消，仍调用 `onError("STREAM_ERROR")`：已完成或作者停止的一轮又显示失败与重试入口，服务端错误码被覆盖。遥测的 `settled` 只挡住重复统计，挡不住界面回调。`onDone` 自身抛错也被报成网络读取失败。

## Decision

- 默认时限改为 780 秒，`config/agent_runtime.py` 记录 `RAILWAY_HTTP_CONNECTION_LIMIT_S = 900`。两分钟余量覆盖取消后台生成、发超时终态、退还结算与退还帧；仍可用同名环境变量调整。原有的超时收尾（补存部分历史、有产出计费、无产出退还）不变，不自动续跑或重发。回归测试约束默认值至少比平台上限早 120 秒结束。
- `receivedTerminalEvent` 提到 `try` 外。终态之后的读取、解析或回调异常不再调用 `onError`，界面保留完成、停止或原服务端错误；之后仍继续处理已到达的 `quota_refunded`。这类异常记为独立的 `ai_chat_tail_failed`（带阶段与异常类型，不带正文），不影响单轮只结算一次的 `ai_chat_*` 结果统计；回调抛错另外以 `AgentStreamCallbackError` 上报异常并写错误日志，不伪装成网络失败，也不静默吞掉。终态前的 fetch/read/parse/callback 失败与取消行为不变。`useAgentStream` 的 `onDone` 用 `try/finally` 收尾：处理中途抛错时仍结束流式状态，并在尚未提交时补发一次 `finalizeStream()` 释放文件只读锁，异常继续交给 agentApi 记诊断。

## Alternatives considered

- **收到 `done` 后立即 abort 读流**：最强理由是彻底避开尾流异常。被否：会丢掉终态之后才到达的 `quota_refunded` 与移除空白文件信息，作者看不到「本轮不计入」。
- **只在平台层延长连接**：最强理由是零代码。被否：Railway 的 15 分钟是平台硬上限，不能配置；心跳只能防空闲断开。
- **把时限设到 870 秒左右贴近上限**：最强理由是给长任务更多时间。被否：取消、补存与退还结算需要等待数据库和后台任务，余量过小时仍可能被平台先切断，结果又变成无终态断线。

## Consequences

- 收益：超长运行由应用先发出明确终态并完成结算；已经完成、停止或报错的一轮不会被尾流断开改写；回调缺陷可以单独定位。
- 代价：13 分钟以上的长任务会比以前早约 7 分钟收尾，作者需要主动继续。新增一个诊断事件名。具体某一次边缘断连的根因仍需按请求关联服务端日志判断，本次不据此宣称所有网络错误同源。

## Verification

`apps/web`：`vitest run src/lib/__tests__/agentStreamTelemetry.test.ts src/lib/__tests__/agentApi.test.ts` 覆盖 `done → read 拒绝`、作者停止 `done → read 拒绝`、`server error → read 拒绝`、`done → quota_refunded → read 拒绝`、`onDone` 抛错与终态前读取失败；去掉保护后终态后的 5 例失败。`src/hooks/__tests__/useAgentStream.test.ts` 覆盖 done 处理中途抛错后流式状态结束、`onComplete` 只调用一次。`apps/server`：`pytest tests/test_agent/test_stream_launch_hardening.py tests/test_api/test_agent_stream_hardening.py`，含时限默认值约束与超时终态退款。
