# 请求时限到达先发终态，再等取消清理与真实结算

## Problem

#183 的 [PR186 决定](2026-10-13-agent-stream-platform-deadline-and-terminal-guard.md) 已把默认时限改为780秒并保护前端终态，但 pump._stop_for_deadline 仍先等 producer 取消收尾，再抛给 API 发送 error。受控慢清理跨过模拟 edge 时，终态仍被挡住；不能把默认余量常量当作已验证的到达保证。

## Decision

API 提供现有 timeout error 的 frame factory；pump 观察到时限先标记 deadline、发一次取消并发出该真实终态，再等 producer。frame 与原源帧一样经 on_item 记账，已收到其他终态则不追加 timeout。后续异常路径看到已发终态，不重复发送。

取消幂等，不因尾流断开再取消正在进行的清理。会话 lease 仍由原生产者/后台补存释放，不提前解锁。连接仍在时照旧等 producer 收尾后按真实产出结算、实际返还后才发 quota_refunded。终态后断线且 producer 未停时，用现有后台任务集合保留延后结算：先等 producer，再决定是否返还，日志在等待时 charged=null/settlement_pending=true，不虚报结算。清理后额外记真实后台结算结果；timeout 原因不被断线覆盖。慢退款等待途中断线也保留该原因和原 shield 退款。

## Alternatives considered

- 继续靠120秒余量：改动最少，但可控制的清理等待可以越过任何有限余量，已被回归复现。
- 不等清理立即返还并解锁：能快收连接，但可能在旧生产者仍写入时接受新任务，且在最终产出不明时提前返还；只提前发超时事实，真实清理和结算继续。
- 新增异步任务/自动重试系统：可以另开连接查询任务，但扩大产品与存储协议；沿用现有显式继续和后台补存。

## Consequences

观察到deadline且事件循环可运行时，终态不再被清理/退款等待吞掉。慢DB或取消仍可能晚于平台连接结束，不能承诺所有内容已保存或所有退款已送达；背景结算/补存继续持有并保持可诊断。受控 gate 测试覆盖慢取消跨模拟edge、真实内存lease排他、保存延后/失败的合成产物、慢退款、终态后断线、单次终态和结算顺序。PR186 的 onDone 回调异常诊断与前端尾流保护已有独立测试，未重复改写。
