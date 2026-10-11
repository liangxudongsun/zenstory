# Agent Note: 回答提问时沿用负责任务的 agent，不沿用送审带来的审稿人

Status: implemented

相关：`bug-fix/2026-10-08-agent-routing-continuity.md`（路由落库、「继续」直达、回答提问时沿用上一轮路由）和 `bug-fix/2026-10-08-agent-router-previous-turn-context.md`（LLM 路由看得到上一轮）。本 note 只改「沿用哪个 agent」，其余规则不变。

## Problem

I16：10-10 至 10-11，5 个会话里出现 7 次。writer 写完后经自动质量门控或主动送审交给 quality_reviewer，审稿人在结尾提问（「要不要按这条调？」）。作者回答后，下一轮被交给 quality_reviewer。审稿人没有 create_file / edit_file，调用报「不在可用工具集」后才转给 planner / writer，白跑一个 agent。U095 里审稿人思考了很久后客户端断开，作者确认的三条设定都没落进文件。

原因：

- `service.py` 每收到一个 `agent_selected` 都覆盖 `routing["last_agent"]`。审稿人是这一轮最后说话的 agent，于是落库成 `last_agent=quality_reviewer`。
- `router.inherit_routing_after_clarification` 取 `last_agent or initial_agent`，作者的简短回答就沿用了审稿人。LLM 路由那条路（`_previous_routing_summary`）也把 `last_agent=quality_reviewer` 交给路由器，提示词又说「有 last_agent 时用它」。

## Decision

- `service.routing_from_router_decided` 多落一个 `owner_agent`，表示负责这一轮任务的 agent，初值是 `initial_agent`。之后每个 `agent_selected` 照旧更新 `last_agent`（最后说话的 agent，「继续」直达和状态卡仍用它）。只有选中的不是 quality_reviewer，或者本轮一开始就交给审稿人（`initial_agent == quality_reviewer`）时，才更新 `owner_agent`。交接来的审稿人只是在审别人的稿，任务仍归交给它的 writer / planner；审稿人再把返工交给 writer 时，`owner_agent` 变成 writer。
- `router.task_owner_agent(routing)`：`last_agent` 是 quality_reviewer、而上一轮不是审稿任务（`initial_agent` 不是审稿人，`workflow_type` 不是 review_only）时，用 `owner_agent`；旧数据没有 `owner_agent`，回落到 `initial_agent`，再没有就用 writer。其余情况沿用 `last_agent`。上一轮明确是审稿任务时照旧沿用审稿人。
- `inherit_routing_after_clarification` 用 `task_owner_agent` 选 agent。`_previous_routing_summary` 交给 LLM 路由的 `last_agent` 也换成它，状态卡上的 lastAgent 是审稿人时同样换掉，所以路由提示词「有 last_agent 时用它」不用改，就会指向负责任务的 agent。
- 没改 `resume_route_after_exhaustion`（「继续」直达）：被截停时正在干活的就是状态卡上的 agent，审稿人审到一半被截停，「继续」恢复的仍是审稿人。

## Alternatives considered

- **审稿人是自动门控带来的就不更新 `last_agent`（评审建议 1 的第一种写法）。** 最强理由：不加字段，所有读 `last_agent` 的地方一起生效。没采用：`last_agent` 还有「最后说话的 agent」这层意思，「继续」直达在没有状态卡时会回落到它；不更新的话，审稿人被截停后「继续」恢复的是 writer，而 writer 已经写完，会重新送审，或干脆重写一遍。writer 主动 `handoff_to_agent` 送审（U079 就是这样）也不经过自动门控的标记，只认「自动质量门控」会漏掉。
- **路由出结果后再检查一遍：路由到审稿人、又不是只读、作者的回答像是确认或修改要求时，改成 writer（评审建议 4）。** 最强理由：LLM 路由自己判成审稿人时也能兜住。没采用：这是对结果打补丁，根因是落库的「上一轮 agent」本身错了；修好之后，LLM 路由看到的也是负责任务的 agent。「像确认」的判断又是一套关键词，会误伤作者真想让审稿人再看一遍的情况。
- **只在 router 端推断（审稿人不是 initial_agent 时用 initial_agent），不改落库。** 最强理由：不动 service，旧数据也能修好。没采用为唯一方案：planner 交给 writer、writer 再送审时，负责任务的是 writer，但 initial_agent 是 planner，作者确认的修改会交给 planner。所以落库 `owner_agent`，只在旧数据上用 initial_agent 回落。

## Consequences

- 收益：writer 写完被审稿、审稿人在结尾提问时，作者的「可以」「按第三条改」回到 writer，不再先跑一遍没有写工具的审稿人再转交；作者确认的设定不会因为审稿人空转、断线而丢掉。上一轮本身是审稿任务时行为不变。
- 代价：`message_metadata.routing` 多一个字段（约 25 字节）。旧消息没有 `owner_agent`，planner → writer → 审稿的旧数据会回落到 planner，planner 可以再交给 writer。审稿人本来就有转交能力，作者回答的确实是审稿意见本身（「你再细查一下第3章」）时，现在先到 writer，writer 可以再送审。

## Verification

`cd apps/server && .venv312/bin/python -m pytest tests/test_agent/test_agent_routing_continuity.py -q --no-cov`：

- 旧数据（initial writer、last 审稿人）和新数据（initial planner、owner writer、last 审稿人）在问句收尾后回「可以」，都沿用 writer；LLM 路由的上一轮摘要里 `last_agent` 也是 writer。review_only 的上一轮仍沿用审稿人。
- `process_stream` 落库：writer 之后选中审稿人，`last_agent=quality_reviewer`、`owner_agent=writer`。经 `SessionLoader` 读回后，回答沿用 writer。
- 只读审查被截停后「继续」仍恢复为只读审稿人（`owner_agent=quality_reviewer`）。

改动前，前两条里 writer 的用例和落库用例都会失败。
