# Agent Note: One author-facing summary per reply, auto review only for body writes, and editor word counts for the reviewer

Status: implemented

关联：
- [2026-10-09-agent-text-no-english-narration-or-glue](2026-10-09-agent-text-no-english-narration-or-glue.md)（AgentTextShaper，本 note 在它上面补「同一 agent 隔着工具调用的分隔」）
- [2026-10-08-agent-review-gating-and-handoff-details](2026-10-08-agent-review-gating-and-handoff-details.md)（当时列为「本批没做」的「自动质检门只统计正文和写工具文本」在这里做了）
- [2026-10-09-agent-word-count-matches-editor](2026-10-09-agent-word-count-matches-editor.md)（工具已给出编辑器口径的 `word_count`；本 note 把它送到审稿人手里，并让审稿人看到更早的篇幅要求）
- [2026-10-10-empty-file-pair-after-close](2026-10-10-empty-file-pair-after-close.md)、[2026-10-10-same-reply-file-body-unblocks-next-create](2026-10-10-same-reply-file-body-unblocks-next-create.md)（IDLE 下 `<file>` 的处理，见 Decision 第 4 条的范围说明）

证据来源：10-10 / 10-11 生产对话审计（I03、I05）。对话记录含作者作品，不进仓库；测试文本全部自己构造。

## Problem

**I03：作者看到的回复是几个 agent 的输出首尾相连。** 10.10.6 之后仍能看到：

1. 两份总结、字数矛盾（U082 10-10 14:52：先报「2781 字」，中间夹一个「</file>」，返修后又报「现在 2238 字（原 2640 字）」）。根因：
   - `service.py` 把每个 agent 的 content 事件都拼进 `assistant_response`，没有任何地方合并或取代前一个 agent 的总结；
   - 自动质检门在 writer 跑完以后才决定送审，writer 写正文时并不知道后面还有审稿，照常写完整总结；审稿人通过时按提示词再写一份，交回返修时返修 writer 又写一份。
2. 孤立的 `</file>`：`StreamProcessor` 在 IDLE（没有进行中的捕获）时把对话原样放出，只在刚收尾的窗口里丢弃精确的空 `<file></file>`，单独一行的 `</file>` 照常进气泡和历史。
3. 自动质检门按 `len(agent_content)`（writer 本轮全部输出文字的字符数）+「动过写工具」判定，不看写的是什么文件：改大纲、设定、角色卡、文档时说明写长一点就被送审（10-10 11:55 U085、17:49 U088、18:24 / 18:48 U091、10-11 09:17 U095）。
4. 同一个 agent 隔着工具调用的两段文字在保存的回复里首尾相连（U094 一连五句「正在…」）。直播时工具卡片把它们分开，历史和复制出去的是拼起来的一段。

**I05：字数自报与实际不符、篇幅不足审稿也通过。**

1. writer 用 `<file>` 流式写正文时，`</file>` 后面的总结和正文在同一次模型输出里，此时还没有任何工具结果，只能估（U075「约1900字」实际 1369，U070「约2800字」实际 1762，U091「约1400字」实际 986）。这份估计既给了作者，也写进了 writer 给审稿人的交接说明。
2. 审稿人的客观缺陷只认「没达到用户原话里明确的篇幅」，被理解成「作者本轮原话」：作者第一条消息说过的「单章约 2000 字」、写进项目写作风格的「每集約500-900字」都不算（U075 1369 对 2000 被判通过，U070「作者本轮没有指定篇幅，不按篇幅返工」，U084 多集不到 300 字没拦）。

## Decision

**1. 被审稿取代的 writer 总结不给作者看（`writing_graph` + `StreamAdapter`）**

- 新增内部事件 `StreamEventType.CHAT_HOLD`（`data.action` 为 `begin` / `discard`），只在图和适配器之间，不发给前端。
- writer run 满足「非快速模式、非只读、不是审稿人交回的返修、审查轮数未到上限」时，第一次成功写进正文类文件（见第 3 条）后，图发 `CHAT_HOLD(begin)`。适配器从此把 StreamProcessor 判定为**对话**的文字扣住（`<file>` 正文照常流到编辑器、照常落库）。
- 本轮真的交给 quality_reviewer（自动质检门、writer 显式送审、计划交接都算）时，图在 HANDOFF 之前发 `CHAT_HOLD(discard)`，扣着的文字丢掉；直播气泡和存进历史的回复里都没有这份总结。审稿人的交接信息里加一段「[作者看到的回复]」：作者没看到内容创作者的说明，不需要再改时它的回复是唯一一份总结，作者需要知道的取舍一并写进去。审稿人交回返修时，返修 writer 的交接信息里同样说明「你送检前的说明作者没看到」，字数只用 `new_word_count`。
- 不送审时（正文不够阈值、writer 以完成标记结束、到了最后一轮等）不丢：适配器在下一个 AGENT_SELECTED / HANDOFF / WORKFLOW_STOPPED / WORKFLOW_COMPLETE / ITERATION_EXHAUSTED / STEERING_RECEIVED / ERROR 事件之前、或流结束时原样放出。
- 被丢掉的文字仍在 writer 的 run 输出里，图的提问判断、完成判定、审稿人回放的历史都照常看得到。

**2. IDLE 下独占一行的 `<file>` / `</file>` 不进对话（`StreamProcessor`）**

- 没有进行中的捕获时，逐行判断：整行只是一个 `<file>` 或 `</file>`（允许首尾空白、标签内空白、大小写变体）、且不在 ``` 围栏里，整行连同换行丢掉，记 WARNING「Dropping a lone <file>/</file> line outside any file capture」。
- 跨 chunk 时行首可能是标签前缀的文字（如「</fi」）先扣住，这一行一旦不可能是单独的标签就立刻放行，普通文字不延后；扣着的前缀在换行、agent / 流结束、新捕获开始前判定（`is_active` 因此也包含它，适配器既有的 finalize 调用点照常交还）。
- 行内提到的（「正文要用 <file> 包起来」）、反引号包着的、围栏里的都原样保留；不在 IDLE 下剥离 `<file>…</file>` **块**：正文内容仍原样出现在对话里，只去掉标签那一行。

**3. 自动质检门只看本轮写进正文类文件的字数（新模块 `agent/graph/body_writes.py`）**

- `BodyWriteTracker` 跟着 writer run 的 TOOL_USE / TOOL_RESULT 记下成功写进 draft / script 的内容：create_file 之后第一段 `<file>…</file>` 正文；edit_file 的 edits 里 `new` / `text`（delete 不算）；parallel_execute 的 write_chapter（`content`）与 edit_file 子任务。edit_file 部分成功但确实改了文件也算；失败、`all_failed` 不算。字数用 `count_words`。
- 自动质检门条件从「`len(agent_content) >= 阈值` 且动过写工具 / 出现过 `<file>`」改为「`body_words_written >= 阈值`」。阈值仍是 `AGENT_AUTO_REVIEW_THRESHOLD_CHARS`（500），WRITER_PROMPT 本来就把它写成「超过 500 字」。纠偏轮照旧接续被打断那一轮的记录。
- 删掉不再使用的 `writer_used_write_tools` / `writer_emitted_file_markers` / `_tool_result_failed`。

**4. 送审交接给审稿人确定的字数和篇幅要求（`writing_graph`、`review_evidence.find_length_requirements`）**

- `[本轮正文字数（编辑器口径）]`：本请求写过的 draft / script 落库后的 `count_words`（读不到时退回 tracker 记下的整份正文字数），并写进交接包 evidence（「《第三章》编辑器字数 2238」）。说明里写明交接说明和对话里的字数是写作时的估计，只用这里的数。
- `[作者的篇幅要求]`：从项目简介 / 写作风格 / 备注、本会话作者最近 40 条消息、本轮原话里摘出同时带「数字 + 字」和篇幅用语（每章、单章、每集、字数、左右、以上…）的短分句（≤60 字），按先后、去重，最多 6 条，原话照录并标来源。只摘原话、不换算成数字下结论，由审稿人对照实际字数判断。
- 两次读取都在送审预算（0.5 秒）内的工作线程里做，失败或超时只记 WARNING，照常送审。

**5. 提示词（`prompts/subagents.py`）**

- writer：篇幅目标包括本会话早先说过的和项目设定里写的；一次写多章 / 多集每章都要写够，写不下就少写几章；刚写完 `</file>` 的同一次回复里不报字数；返修后的回复是作者看到的唯一一份总结。
- reviewer：客观缺陷「没达到作者明确的篇幅」包括本会话早先说过的、项目设定里写的，批量写的逐章对照；报字数只用交接里的编辑器字数或工具 `word_count`，不转述内容创作者自己写的字数；自动检查通过时它的回复是唯一一份总结。

**6. 段落分隔（`AgentTextShaper`）**：同一个 agent 隔着工具调用的下一段文字前补空行（之前没以空行结束时），以 `<` 开头的一段（`<file>` 正文）不补。

## Alternatives considered

- **只改提示词，让 writer 写完正文先不写总结。** 最强理由：从源头少写一份，不用扣文字。没选：writer 写正文时不知道后面会不会送审（门在它跑完后才判定），而且提示词早有「送审前只写一句进度」，生产里仍是两份总结；提示词只能降低概率。
- **在 `service.py` 落库时去掉被取代的总结。** 最强理由：改动最小，历史干净。没选：直播气泡已经显示过这份总结，只改历史会让作者看到的和刷新后看到的不一致；前端也不会用落库内容替换直播内容。
- **writer 写完正文后的文字一律等 run 结束再一次性发出。** 最强理由：不需要新事件。没选：快速模式、不送审的情况也要等，流式体验倒退；现在只在「可能送审」的 run 里、且只在写完正文之后才扣。
- **把扣住的总结压成一句进度留给作者。** 最强理由：作者在审稿期间看得到进度。没选：第一句往往就是估算的字数（U082「共 2781 字」）；交接气泡已经显示「接下来由质量审稿人继续：正文写好了，检查一遍质量」。
- **服务端把总结里的「约N字」改成真实字数。** 最强理由：所有路径都能拿到真实数字。没选：一段话里常同时出现目标字数、原来的字数、差额（「目标2000字，现在1369字，比原来多300字」），按正则替换会改错；需要准确数字的场景（送审）已由交接里的编辑器字数覆盖。
- **把篇幅要求解析成数字，在 `[自动检测：需核对]` 里直接标「低于目标」。** 最强理由：确定性更强。没选：「8000字左右的短篇」是全篇还是单章、「扩到2500」是对哪一章说的，只看字面判断不了；先把原话和实际字数交给审稿人，误报成本更低。
- **在前端过滤 `</file>`、折叠前一个 agent 的文字。** 最强理由：只动展示层。没选：历史、复制、导出和下一轮给模型的上下文都还是原样；前端也不在本包范围。
- **全局剥离 IDLE 下的 `<file>…</file>`。** 最强理由：一次清干净。没选：会吞掉作者需要看到的正文（模型误把已保存的正文贴进对话时，丢掉的是证据），也会误删叙述里的字面标签；现在只去掉独占一行的标签。

## Consequences

- 收益：自动送审时作者只看到审稿人（或返修 writer）写的一份总结，不再出现两份字数不同的总结；单独一行的 `</file>` 不进气泡和历史；改大纲、设定、角色卡、回答问题不再被送审；审稿人拿到编辑器字数和作者更早说过的篇幅要求，「作者本轮没说篇幅」不再是放过短章的理由。
- 代价：
  - 可能送审的 writer run 写完正文后，它的文字要等送审判定：送审时不显示，不送审时在下一个边界事件才一次性出现，位置会排在之后的工具卡片后面。
  - 作者在扣留期间按停止，扣着的文字不进历史（取消路径只保存已发出的内容）。
  - 空文件纠偏轮之前扣住的文字会在纠偏轮开始时放出，如果纠偏轮后又送审，这一种罕见路径仍可能出现两份总结；返修 writer 自己再显式送审（违反提示词）时它的总结也不扣。
  - 正文和总结都由审稿人写时，writer 的写作取舍要靠审稿人转述；提示词和交接说明都要求它转述，但不能保证。
  - 自动质检门现在按正文字数，edit_file 只算这次写进去的文字：大段替换润色会送审，改几个字不送审；正文改动很多但每处都很短的润色可能达不到阈值。
  - 篇幅要求是规则摘取：没有「数字 + 字」的说法（「再长一点」）、超过 60 字的长句、中文大写数字以外的写法会漏；偶尔会把不是要求的句子摘进来（标了来源，由审稿人判断）。
  - 不送审路径（快速模式、短改动）里 writer 在 `</file>` 后写的字数仍可能是估计；提示词要求这时不报字数，不能保证。
  - `test_stream_processor.py` 里几条「独占一行的 `<file>` 原样交还」的期望改成丢掉该行；各测试里模拟写工具的 helper 改为带 `file_type` 和写入文本（`tests/test_agent/body_write_events.py`），因为门不再接受「没写正文的写工具调用」。

## Verification

- `cd apps/server && .venv312/bin/python -m pytest tests/test_agent/test_author_reply_shaping.py -q --no-cov`：16 个用例。其中 10 个在改动前的代码上失败（被取代的总结不进作者看到的回复、短正文不送审时照常放出、返修 writer 收到说明、U082 形态的单独 `</file>`、独占一行的 `<file>` 丢掉、改大纲 / 小改正文不送审、送审交接带编辑器字数与本会话 / 项目设定里的篇幅要求、篇幅分句摘取、同一 agent 段落分隔），5 个守卫用例前后都通过（快速模式照常显示、字面标签保留、长正文短说明照常送审），另有 1 个 `BodyWriteTracker` 单测（create_file 正文、parallel write_chapter 计入，设定文件和失败写入不计）。
- `pytest tests/test_agent -n 8`：全部通过（含更新后的既有用例）。
- 未做真实模型调用，未在 staging 验证；直播时扣留与放出的时序只由适配器级测试覆盖。
