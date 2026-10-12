# Agent Note: 重复 create_file 同一个还空着的待写文件时返回那个文件，不再按「一次只能流式写入一个文件」拒绝

Status: implemented

关联：[2026-10-10-same-reply-file-body-unblocks-next-create](2026-10-10-same-reply-file-body-unblocks-next-create.md)（该 note 明确把「同一个文件的重复 create_file」留在范围外，3c 未确认已修好）、[2026-10-03-agent-tool-failure-circuit-breaker](2026-10-03-agent-tool-failure-circuit-breaker.md)（空文件守卫与 `pending_empty_file_unwritten`）、[2026-10-10-file-streaming-protocol-two-replies](2026-10-10-file-streaming-protocol-two-replies.md)（两次回复的流式协议）。

## Problem

审计 I18：create_file(X) 成功建出空文件后，模型在下一次回复里没有以 `<file>` 开头写正文，而是用同样的标题、类型、父目录再调一次 create_file(X)。空文件守卫 `_PendingEmptyFileState.try_reserve` 只要还有没写出正文的条目就拒绝，从不核对挡路的条目是不是本次要建的同一个文件，于是返回「上一个文件「X」正文还是空的，一次只能流式写入一个文件」。#166 之后线上仍出现（一个回合 7 次，最晚 10-11），共十几个会话；每次多烧一整轮全上下文调用，前端 `classifyToolFailure` 不认识这个类型，作者看到一张通用失败卡，个别回合随后中断。

已核实：被拒的调用与挡路的文件是同一个文件（同标题），不是跨文件的链式违规；`file_ops/crud.py` 的剧本分集幂等复用在守卫之后才执行，到不了这些调用。

## Decision

- `_PendingEmptyFileState.sole_unwritten_entry()`：没有建库途中的占坑、并且恰好只有一个未写出正文的条目时返回它。
- `mcp_tools._repeat_of_pending_empty_file`：create_file 占坑失败后先判断是否重复。条件同时成立才算：上面那个条目存在；标题相同；库里那一行仍在本项目、未删除、正文为空、标题相同；请求的 `parent_id` 与该行一致；请求的 `file_type`（缺省 draft）与该行一致，或该行是 crud 规范化出来的 script、请求是 draft/document。成立时返回那个文件：`status=success`、`mutation_applied=false`、`content=""`、不带 `reused_existing`，另加 `next_step`：「已经建好，正文还是空的。不要再调用 create_file，接下来直接以 <file> 开头写它的正文」。不新增条目、不建新文件；StreamAdapter 按既有逻辑为同一个 file_id 重新进入等待 `<file>` 的状态，计费跟踪把它记为同一个本轮新建空文件（字典幂等），前端 `startFileStreaming` 对同一 id 也是幂等的。记一条 INFO 日志 `agent.create_file.same_title_repeat` 观察频率。
- 其他情况照旧拒绝：挡路的是别的文件、类型或父目录不同、有并发建库中的占坑、有两个以上未写条目。
- 测试：重复同一文件返回同一 id 且库里只有一份；同标题不同类型 / 不同父目录仍被拒；有建库中的占坑时仍被拒（`tests/test_agent/test_mcp_tools.py`）。

## Alternatives considered

- **只改提示词里的正确/错误示例**（I18 建议第 2 条）：最强理由是从模型行为源头减少重复调用。没在本包做：那几行属于流式协议，由另一个修复包负责；而且模型重复调用时它要的就是那个文件，工具按文件身份返回它才是正确语义，提示词改了也需要工具这样处理。
- **前端把 `pending_empty_file_unwritten` 显示成非失败卡**：最强理由是作者不再看到「没做成」。只是掩盖：多出的一轮调用和中断仍在，而且会把跨文件的真实违规也藏起来。
- **重复时自动帮模型写正文 / 自动重试**：用户明确不接受用重试代替根因修复，也没有正文可写。
- **放宽 `try_reserve`，同标题就放行进 crud**：会在 crud 里再建一个同名空文件（小说章节没有幂等复用），重复空文件正是守卫要防的。

## Consequences

- 收益：同一文件的重复 create_file 不再报错、不再出失败卡，模型拿到明确的「直接写正文」提示；守卫对真实的跨文件违规不变。
- 代价与剩余：
  - 前端会再收到一次同 id 的 `file_created` 和一张「已创建」工具卡（与第一次相同的文件）；没有改卡片展示。
  - 重复调用本身仍会占一次工具往返（只是不再失败）；模型为什么重复调用由流式协议提示词那边处理，本条不宣称模型不再重复调用。
  - 第一次调用若被 crud 规范化了父目录（例如把章节 id 当 parent 传进来后上挂到文件夹），模型照原参数重复时父目录对不上，仍会被拒，与改动前一样。
  - 同一条回复里 `<file>X</file>` 之后再 create_file(X) 的路径（条目已标记 streamed）不经过这里，仍按 2026-10-10 note 描述的方式处理。
