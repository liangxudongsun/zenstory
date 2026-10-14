# Agent Note: 代理说明以 AGENTS.md 为正本，CLAUDE.md 只做导入

Status: implemented

关联：[2026-10-07-agent-environment-contract](2026-10-07-agent-environment-contract.md)（AGENTS.md 作为共同操作规范；本条只改入口形式和专项说明的位置，不改其中的发布与巡检边界）。

## Problem

- 根 CLAUDE.md 用链接让代理「先读 AGENTS.md」，又在末尾重述了一遍发布边界，其中「正文恢复 / 上传存储这一批只到测试环境」已经过时（该批次的提交 f217fdbd 从 prod-v2026.10.07.2 起包含在每个正式版本标签里），AGENTS.md 也有同一句。代理会按过时的批次范围拦下已发布的工作。
- 写作 agent 的专项说明只有 `apps/server/agent/CLAUDE.md`。Codex 等按 AGENTS.md 分层查找说明的代理找不到它；AGENTS.md 里「the nearest agent guide」也指不到它。
- 这份专项说明与代码脱节：目录图把 `openai_agents/` 放在 `llm/` 下、写着 LangGraph、列出不存在的 `novel.py` 等提示文件和 `file_updated` 事件，「添加 Agent 类型」只列了 3 处（实际要改 9 处以上），约 100 行按日期堆叠的实现日志与决策记录重复。

## Decision

- 根 CLAUDE.md 第一行用 `@AGENTS.md` 导入，保留 DESIGN.md、agent 专项说明、发布运维文档和决策记录四个入口，删掉重述的批次范围与巡检句。AGENTS.md 删掉过时的「This draft-recovery/storage batch is staging-only.」，保留「测试环境授权不等于正式环境授权」的通用规则；当前批次的范围写在任务或交接里，不写进长期合同。
- AGENTS.md 明确指向 `apps/server/agent/AGENTS.md`，并把「organizational identity」写成具体规则：zenstory.ai 是组织站（自有 paper/ink 视觉，见 DESIGN.md），创作者用 app.zenstory.ai，不把组织站改成面向写手；用户可见文字写作「ZenStory」（见 [2026-10-09-brand-written-zenstory](2026-10-09-brand-written-zenstory.md)）。
- `apps/server/agent/CLAUDE.md` 用 `git mv` 改名为 `apps/server/agent/AGENTS.md`，原位置留一行 `@AGENTS.md`。README / README_EN 与根 CLAUDE.md 的链接改指 AGENTS.md；历史决策记录里提到的旧路径保持原样。
- 专项说明按当前代码重写：目录图、请求与流的五步、运行预算、协作与路由、用户范围与交接的不变量（每条一句规则 + 负责的代码 + 决策记录链接）、流的终止 / 停止 / 计费（SSE 事件类型以 `core/events.py` 的 `EventType` 为准）、上下文、工具、提示词、添加工具 / 添加 Agent 类型的完整清单、调试入口。所有路径、符号和链接都对照仓库核对过。

## Alternatives considered

- **保留 CLAUDE.md 为正本，另建 AGENTS.md 指过去**：改动最小，历史记录里的路径全部有效。没采用：两份入口文件迟早又各写各的；Claude Code 支持 `@` 导入，正本放在两类代理都会自动发现的 AGENTS.md 只需维护一份。
- **在 CLAUDE.md 里继续重述发布边界**：Claude 不读 AGENTS.md 时也能看到。没采用：`@AGENTS.md` 导入后整份合同已在上下文里，重述只会再产生一处过时文本。
- **专项说明保留按日期记录的实现细节**：信息最全，不必点开链接。没采用：同样的事实已在决策记录里，日志式条目让关键不变量难找，也随实现变动而过时；改为一句规则加链接，细节以记录为准。

## Consequences

收益：Claude Code 与 Codex 读到同一份根合同和同一份 agent 说明；过时的批次范围不再拦截已发布的工作；新增工具或 agent 类型时有完整的落点清单。代价：专项说明不再复述每条行为的全部细节，改行为前要点开对应决策记录；历史记录里的 `agent/CLAUDE.md` 指向的是一行导入，需要再跳一次。纯文档改动，不改产品行为，没有新增测试。
