# Agent Note: 生成中点「新对话」先确认、走服务端停止；中断的一轮写明写进了哪些文件

Status: implemented

补充 `architecture/2026-10-09-stop-output-definition-and-round-outcome.md`（终态 `stop_outcome`、离开确认）与 `feature/2026-10-09-stop-guard-progress-and-leave-prompt.md`（离开确认）。停止协议、计费口径、空白占位文件规则都不变。

## Problem

10.10.1（#163）上线后，空回复 / 中断的一轮从 15–21% 降到约 1.7%，复盘（I01）剩下两处代码缺口：

1. **生成中点聊天面板右上角的「新对话」(+) 没有任何确认。** `handleNewSession` 先在服务端建新会话，再调 `useAgentStream.reset()`，`reset()` 直接 abort 连接，不经过 `POST /agent/stop`。服务端于是按断线（`client_disconnected`）收尾，作者看到的是「已中断」而不是「已停止」；而且新会话建在旧一轮还在跑的时候。离开确认（`useLeaveWhileGenerating`）只拦路由跳转，拦不到这个按钮。U095 那一轮（确认设定，14 秒内另开新会话）就是这条路径。
2. **中断 / 停止的一轮已经写了文件时，作者只看到「已中断 · 已写入的内容已保存」**，不知道写了什么。U088：`create_file` 带正文写好了第 2 章，回复只剩开场白「我先看卷一细纲里第2章的要求。」，连接断开后作者再没回来；U060、U063 同样有产出却没有汇总。`stop_outcome` 只有 `saved_output: true`，没有文件信息。

核对其余「不是路由跳转的 reset / abort」：聊天面板没有切换历史会话的入口；快捷卡片、建议芯片、重新发送、重试都经 `startRound`，生成中直接被 `isStreaming` 挡掉，不会中止当前一轮；切项目是路由跳转，已由离开确认拦截。需要处理的只有「新对话」。

## Decision

### 生成中点「新对话」（`ChatPanel.tsx`、`LeaveWhileGeneratingDialog.tsx`、`useAgentStream.ts`、`agentApi.ts`）

- 不在生成：照旧直接新建。
- 生成中：弹与离开确认同一个对话框（`LeaveWhileGeneratingDialog intent="newChat"`）：标题「AI 还在写」，正文「开始新对话会先停止这一轮。还没写出内容的话，这一轮不计入今日 AI 消息。」，已写出内容时为「……已经写出的内容会保存，这一轮计入今日 AI 消息。」，Pro 不提每日条数。「继续等」是主按钮，「停止并开始新对话」是次要按钮。确认框打开时这一轮自己结束：改为「这一轮已经结束 / 现在开始新对话不会中断任何内容」，按钮「开始新对话 / 取消」。
- 作者确认后走停止按钮的同一条路（`stopRound`，由原 `handleCancel` 抽出）：先让编辑器存下未保存的字，存不下时停止请求带 `keep_file_ids`，再 `stop()` 请求服务端停止；然后**等这一轮的连接真正关闭**（`useAgentStream.whenStreamClosed()`），才建新会话、`reset()`。服务端因此按作者停止收尾（`user_stopped`，按现有规则无产出退还、移除本轮空白占位文件），`done` 之后的 `quota_refunded` 也照常送达，文件树刷新、额度标签更新。
- 已经在「正在停止…」时点「新对话」：不再询问，等这一轮收尾后新建。等待期间再点「新对话」不重复触发；等待结束时已切到别的项目则不新建。
- 等待期间（直到新会话建好前）**不能发送**：`done` 一到 `isStreaming` 就变成 false，但连接还开着（退还、移除占位文件、`quota_refunded`）。这时发出的消息会在旧会话里开一轮，并让等待提前落定，随后新对话的 `reset()` 不经确认就掐断刚发的这一轮，又回到按断线结算。所以 `ChatPanel` 用 `newChatPending`（state，配同名 ref 挡同一 tick 的调用）把等待状态并进 `sendDisabled`、`startRound` / `handleSendMessage` 的入口判断；输入框在整个等待期间都显示停止按钮的「正在停止…」和处理中占位文案。快捷卡片、建议芯片、重试都经 `startRound`，一并挡住；草稿照旧可写。
- `whenStreamClosed`：`streamAgentRequest` 新增 `onClosed`（`fetchStream` 结束后调用一次，无论是服务端关闭、出错还是被中止）；`useAgentStream` 为每次请求记一个「连接已关闭」的 promise，前端自己 abort（`reset` / `cancel` / 切项目 / 卸载 / 新一轮）时也立即落定。没有进行中的请求时立即返回。最多等 `STOP_GRACE_MS`（5 秒）：这是防止服务端在 `done` 之后迟迟不关连接时把「新对话」卡住的上限，不是修复手段；到点后照样新建，`reset()` 断开连接，此时服务端已经收到停止请求，仍按作者停止结算。

### 终态列出本轮写入的文件（`agent/core/round_outcome.py`、`api/agent.py`、`RoundEndNote.tsx`、`lib/chatRoundEnd.ts`）

- 服务端新增 `RoundWrittenFiles`，与 `StreamBillingTracker` 一起作为 `SSEStreamPump.on_item` 观察这一轮的每一帧（只解析 `tool_result` / `file_created` / `file_content` 三种帧）。口径与 `write_succeeded` 一致：`create_file` 带非空正文新建、流式正文非空、`edit_file` 真的改了文字（`mutation_applied`，旧格式看 `edits_applied`）。只建空文件、读文件、失败的调用、文件夹不算。
- 字数用 `utils.text_metrics.count_words`（与编辑器同一口径），按本轮写进这个文件的全部正文（`create_file` 带的正文 + 流式正文拼起来）计算，切在两帧之间的英文单词只算一次。本轮用 `edit_file` 改过的文件只改了几处，整篇字数无从得知，不给字数。
- 幂等复用（`reused_existing`）命中本来就有正文的文件：中断后的流式残稿会被截断覆盖保护拒绝落库，所以不把它列成「已保存」。「本来就有正文」与 `StreamAdapter._resolve_original_content_length` 同一判据：`original_content_length > 0`、`content` 非空，或 `content_elided` 为真。不能只看 `content`：生产里复用分支的 tool result 经 `mcp_tools._elide_reused_file_content` 把 `content` 省略成 `""`，只留 `content_elided` / `original_content_length`，前端收到的帧就是这个形状。复用到的是空白文件（原本长度 0）时，流式正文会正常落库，照常列出并计字。
- `_finalize_stopped_round` 写终态时 `build_stop_outcome(..., written_files=...)`，`stop_outcome.written_files = [{id, title, words?}]`，按第一次写入的先后排列；没有可列的文件时不写这个键。只有 `parallel_execute` 写章、`delete_file`、`update_project` 这类帧里拿不到文件的写入，`saved_output` 照旧为真、列表为空。
- 前端 `parseRoundStopOutcome` 读出 `writtenFiles: {title, words | null}[]`（没有标题的项丢掉，旧消息为空数组）。`RoundEndNote` 在计入且 `savedOutput` 时：有文件就写「已保存《第2章 入宅》3,120 字」，多个用「、」连接，最多点名 3 个，其余写「等 N 个文件」；字数为 0 或未知时只写书名号标题。没有文件时照旧「已写入的内容已保存」。英文界面用英文引号与 `words`、`and N more`。字数按界面语言加千分位。
- **停止当场也列出文件（补丁，同日真实模型浏览器实测后）。** 实测发现停止后不刷新时只看到 ChatPanel 的通用说明「已停止 · 已写入的内容已保存 · 本条计入今日 AI 消息」，文件列表要刷新后才由 `RoundEndNote` 显示。现在停止路径的 `done` 帧多带 `written_files`（与之后落库的 `stop_outcome.written_files` 同一个 `RoundWrittenFiles.files()`，停止时源生成器已经不再出帧，两份一致；列表为空时不带这个键）。`useAgentStream` 用同一个 `parseWrittenFiles` 读进 `completionMeta.writtenFiles`，`ChatPanel` 的停止说明（`chat-user-stop-note`）有文件时改用与 `RoundEndNote` 共用的 `formatSavedFiles`，写「已停止 · 已保存《雨夜》1,039 字 · 本条计入今日 AI 消息」；仍只有这一条说明，不另加终态行。兼容：旧前端忽略多出的字段；旧服务端不带字段时照旧显示「已写入的内容已保存」。断线（`client_disconnected`）不覆盖：连接已经断了，服务端没有帧可发；前端要显示只能在断线后再拉一次历史，而终态是后台任务写入、何时落库没有保证，断线时往往也连不上服务端。停止请求超时后前端自己断开（`STOP_GRACE_MS`）的一轮同理，仍是通用说明，刷新后才列文件。测试：`test_stopped_round_done_frame_names_the_written_files_like_the_stop_outcome`（done 与 stop_outcome 的列表相同，退还的停止轮 done 不带这个键）、`useAgentStream.test.ts`（done 的 written_files 进 `completionMeta`，旧服务端不带时没有这个字段）、`ChatPanel.mount.test.tsx`（停止当场只有一条说明，写明《雨夜》1,039 字）。

## Alternatives considered

- **生成中直接禁用「新对话」按钮。** 最强理由：最简单，没有新对话框，不可能误触。没采用：作者想换话题时只能先找到停止按钮、等停下再点，按钮灰着也不说为什么；离开页面已经是「先问再走」，同一件事两种做法更难懂。
- **确认后只发 `/agent/stop` 就立刻 `reset()` 新建。** 最强理由：不必新加「连接关闭」信号，新对话出现得更快。没采用：`reset()` 会掐掉 `done` 之后的 `quota_refunded`，前端收不到移除的空白文件（文件树里留着已删除的章节）和退还说明；服务端还在收尾时就建新会话也容易撞上会话占用。等连接关闭通常只多几百毫秒。
- **让 `reset()` 自己在生成中改走服务端停止。** 最强理由：所有调用 `reset()` 的地方一次覆盖。没采用：`reset()` 是同步清状态，切项目、卸载时也用它，那些场景不能等；把它变成异步会牵动整个聊天面板的时序。
- **终态里的字数在结算后从数据库读文件正文再算。** 最强理由：反映最终落库的内容，标题也是最新的。没采用：断线后的残稿补存是后台任务，和终态写入谁先完成没有保证，读库可能读到补存前的空文件；帧里的正文就是这一轮写下的内容，确定、可测。
- **停止当场（连接还开着）就在停止说明里列文件。** 最强理由：作者不用刷新就能看到。没采用：停止当场消息气泡里已经有每个文件的写入卡片；真正看不到的是断线、刷新后的一轮，终态行就是给这种情况的。（实测后改为采用：写入卡片不说字数、不一定都在视野里，作者停止后看到的仍是笼统一句，见 Decision 里的补丁。）

## Consequences

- 收益：生成中点「新对话」不再悄悄掐断这一轮；作者确认后这一轮记为作者停止，按现有规则退还或计入，空白占位文件照常移除并刷新文件树。刷新或回到项目后，中断 / 停止的一轮写明写进了哪几个文件、各多少字，作者知道第 2 章其实已经写好了。
- 代价：确认后「新对话」要等这一轮收尾（通常几百毫秒，最多 5 秒），期间输入框显示「正在停止…」。停止前 run id 还没拿到（发送后极短时间内）时 `stop()` 只能断开，这一轮仍按断线结算，与停止按钮相同。
- 代价：`stop_outcome` 多了 `written_files`（每个文件一个 id、标题、字数），一轮写很多文件时消息元数据变大，但只有停止 / 断线的一轮才写。服务端每帧多一次事件名判断，三种帧多一次 JSON 解析。并行写章、删除、改项目信息的一轮列表为空，仍只显示「已写入的内容已保存」。流式写进本来就有正文的复用文件不列出，即使它在中断前已经完整写完并保存（宁可少说，不说错）。断线的一轮仍只在刷新、重进项目后列出文件；作者停止的一轮停止当场就列出（见上面的补丁）。
- 范围外：断线后让这一轮在后台跑完、回来时重新接上（I01 建议 2）不在本批；离开确认与「新对话」确认理论上可能同时打开（生成中先点「新对话」再按后退）。

## Verification

- 后端：`cd apps/server && .venv312/bin/python -m pytest tests/test_agent/test_round_outcome.py tests/test_api/test_agent_stream_hardening.py tests/test_agent/test_stop_output_definition.py tests/test_agent/test_stream_launch_hardening.py tests/test_api/test_agent.py -q --no-cov`：`RoundWrittenFiles` 列出带正文新建的章节及字数、跨帧流式正文按整段计字、空白占位 / 读文件 / 失败 / 文件夹 / 没改动的编辑不算、编辑过的文件不给字数、复用已有正文的文件不列（帧用生产形状：真实的 `_elide_reused_file_content` + `tool_result_event(...).to_sse()`，`content` 为空、只剩 `content_elided` / `original_content_length`；另测只有 `original_content_length` 的情况）、复用空白分集照常列出、按第一次写入排序；`build_stop_outcome` 没有文件时不写 `written_files`；作者停止（流式正文）与断线（U088：`create_file` 带正文后断开）的终态都带 `written_files`。新用例在改动前失败。`ruff check` 通过。
- 前端：`pnpm --dir apps/web exec vitest run src/components/__tests__/ChatPanel.mount.test.tsx src/components/__tests__/ChatPanel.newSessionLifetime.test.tsx src/components/__tests__/RoundEnd.test.tsx src/components/__tests__/MessageList.test.tsx src/hooks/__tests__/useAgentStream.test.ts src/lib/__tests__/agentApi.test.ts src/hooks/__tests__/useLeaveWhileGenerating.test.tsx`：生成中点「新对话」先弹确认、确认前什么都不断开，确认后先 `stop()`、等连接关闭再建新会话和 `reset()`，`done` 之后、新会话建好之前发送被挡住（不开新一轮、不清草稿，输入框显示「正在停止…」），「继续等」不停止；不生成时直接新建；`whenStreamClosed` 在没有请求时立即返回、`done` 之后仍等后续帧直到连接关闭、断开时落定、最多等 5 秒；`onClosed` 在最后一帧之后、被中止时各调用一次；终态行列出文件与字数、最多点名 3 个、旧消息照旧；新对话确认框的文案与按钮。`pnpm --dir apps/web lint`、`lint:i18n-keys`、`lint:tokens`、`build:typecheck` 通过。
- 未做浏览器 / staging 实测（无登录态 staging E2E），未调用真实模型。
