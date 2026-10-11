# Agent Note: Continue the agent after a run ends at `</file>`; complete tasks only against real writes; change claims via a prompt rule

Status: implemented

关联：[2026-10-10-file-streaming-protocol-two-replies](2026-10-10-file-streaming-protocol-two-replies.md)（两次回复的协议描述，本次只改第 5 步）、[2026-10-10-same-reply-file-body-unblocks-next-create](2026-10-10-same-reply-file-body-unblocks-next-create.md)（同一回复里 `</file>` + create_file 的链式写法，不变）、[2026-10-10-empty-file-pair-after-close](2026-10-10-empty-file-pair-after-close.md)、[2026-10-08-agent-review-gating-and-handoff-details](2026-10-08-agent-review-gating-and-handoff-details.md)（自动质检门，本次未改）。

证据来源：本批审计的 I08 / I09 记录与真实对话（仓库外，含用户作品，未复制进仓库；测试用自造文本）。

## Problem

**I08：多文件任务写完一个文件这一轮就结束。** r5（#166）/ r6（#170）之后仍有 10 个回合最后一次工具调用是成功的 create_file、最终回复为空或只剩开场句（U076 要写完剩下几集只写了第2、3集；U088 计划建卷二到卷五只建了卷二；U070、U082、U089 只剩开场句）。

已证实的机制（读码）：

1. 流式写文件协议把正文放在**回复文字**里：第 1 次回复只发 create_file，第 2 次回复以 `<file>` 写正文。
2. openai-agents 的 run loop 把「不带工具调用的回复」当作最终输出、直接结束 run；runner 的 `tool_use_behavior` 只额外**增加**停止条件（控制流工具、熔断、预算），没有「还没写完」的继续条件。模型写完 `</file>` 没在同一次回复里接着调用 create_file 时，run 就停在这里——这不是模型决定收尾，而是协议让正文这次回复成了最后一次回复。
3. graph 也不接：没有计划交接、不满足自动质检门（返修稿 / 规划师都不满足）时直接 `current_agent_type=None` 结束；`base.py` 第 5 步「之后可以继续回复用户或创建下一个文件」把接着写和写总结都说成可选。
4. `<file>` 里的文字全进了文件，`</file>` 之后什么都没写时，作者看到的就是空回复或开场句。

链式写法并非总失败（U076 06:35 一次 run 写完了 6–12 集），取决于模型写完 `</file>` 后有没有在同一次回复里接着调用工具；服务端此前对「没接着调用」没有任何补偿。

**I09：完成声明与实际产出不一致。**

- A（工作流自己造成）：`_build_completion_task_payload` 把所有 in_progress 任务无条件改成 done，`_auto_finalize_task_board_on_completion` 在 `[TASK_COMPLETE]` 收尾和审查轮数上限时写回任务板。U084「撰寫第2-5集劇本」只写了第2集、U091「第一卷正文（第1-119章）」只写了 4 章，都由这一步标成 done。`execute_update_plan` 只校验格式，不对照文件。
- B（回复里的话没人核对）：U044 作者只是在解释断句，AI 回「已还原」却零工具调用，之前加的逗号还在；U029「已录入项目记忆」同样零调用。完成判定只看 `[TASK_COMPLETE]`，请求级读写台账（`RepeatReadGuard.files_written / write_succeeded`）只用于交接说明和计费。

## Decision

**1. 写完 `</file>` 就结束 run → 同一个 agent 接着跑一轮（根因修复，`graph/writing_graph.py`）**

- `graph/completion_evidence.ends_on_file_block(tail)`：最后一次工具调用之后的文字以一段非空、已闭合的 `<file>` 正文结束（之后只有空白、完成标记或空的 `<file></file>`）。
- 条件：当前 agent 有写权限；本次 run 有 create_file 调用且没有失败（runner 对每次调用都发 TOOL_RESULT）；没有待补写的空文件（空文件纠偏分支照旧优先）；没有显式交接、暂存的交接、澄清、无效交接、工具轮数耗尽、错误；不是只读 / 先问清楚的请求；`iteration < max_iterations`。
- 交接说明（`_file_stream_continuation_context`，以 `FILE_STREAM_CONTINUATION_MARKER` 开头）带本请求已保存的文件标题（不要重写）、作者范围（router scope）、任务板上 pending / in_progress 的任务（含记录的进度）；要求还有没写的接着 create_file，写完 `</file>` 后同一回复里接着建下一个或写总结，全部写完就用 1–3 行告诉作者实际写了哪些文件、各多少字，没写完的如实说明。运行中途到达的 steering 一并提醒。
- 放在计划交接和自动质检门之前：规划师写完卷三再交给 writer；writer 的正文、正文写入记录（p2 的 `writer_body_writes`）经 `carried_*` 接续，自动质检门按整轮判断（门的条件本身未改）；返修稿续写后仍是返修稿，不送审。
- 终止性：每一轮续写都必须真的新建并写完一个文件才会再续；不新增上限，受既有 `max_iterations` 约束，最后一轮不续，照旧走协作轮数耗尽卡片。
- 提示词（辅助，不是修复本身）：`base.py` 第 5 步改为「`</file>` 之后在同一次回复里接着做下一步：还有没写的就 create_file，写完就写总结，回复不要停在 `</file>`」；交互规范 3 的「延迟总结」同义补一句。两次回复的第 1、2 步描述不变。

**2. 任务板只按实际产物收尾（I09-A）**

- `_auto_finalize_task_board_on_completion(guard)`：本请求台账里没有写过的文件 id → 不补；否则查这些文件中**仍存在且有正文**的标题（`_existing_written_titles`，删掉的、空的不算），再交给 `_build_completion_task_payload(tasks, titles)`：
  - 任务描述 / artifact 里有编号（`tools/task_progress.task_unit_spec`：「第2-5集」「第二至第五集」「卷二到卷五」「第一卷正文（第1-119章）」取范围、几种单位取编号最多的那种）：范围内每个编号都有对应标题（`title_units`，含标题里的范围）才 done；只写了一部分保持 in_progress，写入 `done_units` 和 `progress`「已写：第2集；待写：第3–5集」；一个都没对上不动。
  - 跨请求累计：`done_units` / `progress` 不在工具 schema 里，模型只看到渲染成文字的任务板，每次重存（U084 每个请求开头都重存「第2-5集 in_progress」）都不会带上。`execute_update_plan._carry_recorded_progress` 把旧任务板上同名任务（去首尾空白后完全相同；模型照抄渲染出的「（已写：…）」后缀时先去掉）记下的 `done_units` / `progress` 接到新任务上；标为 done 的不接，这次自己带了 `done_units` 的（工作流收尾那次）以它为准。任务改名（「第2-5集」改成「第2-6集」）时进度不接，任务停在 in_progress、只算以后写的编号——宁可少算。
  - 收尾时前几轮记下的编号再对一次项目里现存且有正文的文件（`_live_project_titles`，只在有 `done_units` 时查）：作者在两次请求之间删掉的那一集不再算已写。
  - 编号只认工作流在写入时记下的，不拿项目里已有的同编号文件凑数：「重写第2-5集」开始前这几集都在，按现有文件算会只重写一集就标 done，正是 I09 要修的那种假完成。
  - 有 artifact 没编号：写出了这个文件（去书名号空白后互相包含）才 done。
  - 都没有：本请求写出了文件才 done（保留原行为里有证据的那部分）。
  - pending 不动。
- `message_manager` 任务板段把 `progress` 附在任务后面，下一轮模型能看到哪些还没写。
- `execute_update_plan`：模型自己把带编号的任务**新**标为 done、项目里（未删除且有正文的文件标题）缺其中编号时，结果里返回 `unverified_done` 并在 message 里要求如实告诉作者哪些没写。只提醒不拒绝（见 Alternatives）。

**3. 回复里的修改声明靠提示词约束，不做文字检测（I09-B，负责人决定）**

- `prompts/base.py` 统一执行协议「查询、执行、核对」里原有一条「按实际工具结果报告……不能把构思、待办或失败操作说成已经保存」，在它上面加强，不另起一条：只有本轮对应的工具调用成功后，才对作者说已保存、已还原、已修改或已录入；本轮没有改动任何内容时，直接说没有改。所有角色共用这段协议。
- 服务端不识别回复里的修改声明，也不为它补轮或追加更正。p1 一度实现过这种检测（见 Alternatives），合入前由负责人否决并整段删除：对这类「软」的 AI 行为，负责人不要正则 / 文字识别代码，要一条简单的提示词规则。
- 这一条只降低说错的频率，不保证不说错；U044「已还原」、U029「已录入项目记忆」这类回复在模型不遵守提示词时仍会出现，线上要继续观察。

## Alternatives considered

- **在 runner 里把 `</file>` 结尾的回复当成非最终输出（同一个 SDK run 内续跑）**：最贴近 SDK 语义，但 0.17.x 的 `tool_use_behavior` 只在有工具结果时被调用，纯文本回复没有钩子；要在 runner 里另起一个 `Runner.run_streamed` 并处理 MESSAGE_START/END、用量、钩子、steering，改动面大。graph 边界已有同形状的续跑（空文件纠偏、规划补写、steering 追加轮），复用最小。
- **只改提示词让模型必须接着写**：r5 之后线上仍复现；提示词只能降低频率，不能补偿模型没接着调用工具的那一次。保留为辅助。
- **按任务板 pending/in_progress 判断「还没做完」就续跑**：任务板是模型自己写的，常常过期或粒度很粗（「第1-119章」），据此续跑会在作者只要一章时继续往下写；改为只在「run 停在写完的文件上」这一协议层信号上续跑，范围和任务只作为续写轮的参考信息。
- **空回复时由系统拼一段总结（标题 + 字数）**：能保证不空，但内容是机械的，也与 p2 包的总结合并改动重叠；续写轮让模型自己写总结。最后一轮无法续写时仍可能为空，由协作轮数耗尽卡片说明。
- **`execute_update_plan` 直接拒绝未核实的 done**：任务板会更真实，但标题不带编号的文件对不上号时模型永远标不了 done，下一轮提示里任务一直是进行中，模型可能重写已完成的章节；而 done 不能改回 in_progress（现有校验），拒绝后也没有合法的更正路径。改为提醒。
- **收尾时把 current_phase 也改成「已完成第2集，第3-5集待写」**：current_phase 是整字段覆盖的项目信息，自动改写会冲掉模型 / 作者写的阶段说明；任务板 tasks-only 更新本来就会按正文标题前推 current_phase，本次不再加。
- **范围任务按项目里现存的全部文件标题核对（不靠 `done_units` 累计）**：不怕模型重存任务板，但「重写 / 修改第2-5集」这类任务开始前文件都在，只改一集就会被标 done；改为在 `execute_update_plan` 接住同名任务的记录，并按现存文件剔除已删掉的编号。
- **服务端识别回复里的修改声明并核对实际写入（p1 实现过，被否决）**：`completion_evidence.find_unbacked_change_claim` 用简繁体正则找「已还原 / 已保存 / 改好了 / 已录入」这类说本轮改了东西的话，排除现状描述（「第1-3章都已写好」）、问句、否定、他人主语和「记住了」；本请求没有任何写工具成功时，同一个 agent 补一轮（每请求一次）真的去改或向作者更正，不能补时追加一句「更正：这一轮实际没有修改任何文件或项目信息」。最有力的理由：判断依据是真实写入记录而不是模型自述，提示词约束不住的那一次（U044 零工具调用却回「已还原」）也能被抓住，作者看到的是先说错、再更正，而不是一句没人核对的假话；只在本请求零写入时才看，写过文件的请求不受影响。否决理由：这是对软行为的文字模式识别，误判（带「了」的现状描述）和漏判（「第二章已还原」、把字句、英文回复）都靠不断加正则修补，规则越来越长、越来越难推断；误判时作者会看到一句莫名其妙的更正，还多一次模型调用。负责人选择用一条提示词规则代替，接受模型偶尔不遵守的风险。

## Consequences

- 「把后面几集都写了」类请求在一次请求里写完计划内的文件并有总结，不再需要作者连发「继续」；每次续写多一次 agent 迭代（AGENT_SELECTED 事件、协作轮数计数照旧），计划很长时可能用完 12 轮协作上限后照旧提示继续。
- 续写会多花模型调用：只有 run 恰好停在写完的文件上才触发，正常写了总结的回合没有额外调用。
- 任务板不再出现「只写了第2集，第2-5集 done」；标题不带编号、写了编号范围的任务现在会停在 in_progress（原来被无条件标 done），需要模型自己更新，或下一轮按 progress 继续。
- 修改声明：只有提示词约束，没有服务端核对；模型不遵守时，回复里的「已还原 / 已保存」仍可能与实际写入不符，作者要自己看文件。
- 任务名被模型改写（换了字、换了范围）时，前几轮的进度接不上，任务停在 in_progress，需要模型或作者自己更新。
- 已知未覆盖（交给后续）：没有 create_file 目标就输出的 `<file>` 块进入对话（U074，stream_processor 归 p2）；返修交回 writer 后只说一句「我先读取…」就没有工具调用地结束（U076 06:35）；删除旧文件、写 current_phase「已重设完成」排在实际写入之前（U076-89e9815c）；回复说「交接给写作者」却没调用 handoff（U056）；current_phase 自由文本声明（U095）。
- 本地测试全部 mock 模型，没有真实模型对照；线上效果要用诊断账号观察「run 停在 `</file>`」后的续写轮是否接着写、是否给出总结。
