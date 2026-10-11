"""写完 </file> 就结束 run 时同一个 agent 接着写（I08），回复说改了却没有写入时补一轮或更正（I09）。

流式写文件协议把正文放在回复文字里；openai-agents 把不带工具调用的回复当作最终输出，模型写完
一个文件没在同一次回复里接着调用 create_file 时，run 就停在 </file>：计划里没写的文件、给作者的
总结都没写，作者看到的回复是空的或只剩开场句。fake agent 按 runner 的事件形状模拟。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from agent.core.workflow_events import StreamEvent, StreamEventType
from agent.graph.completion_evidence import (
    author_text_outside_files,
    ends_on_file_block,
    find_unbacked_change_claim,
)
from agent.openai_agents.repeat_read_guard import ReadPlan
from agent.tools.mcp_tools import ToolContext

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def _text(text: str) -> StreamEvent:
    return StreamEvent(type=StreamEventType.TEXT, data={"text": text})


def _tool(call_id: str, name: str, *, failed: bool = False) -> list[StreamEvent]:
    payload = {"status": "error", "error": "boom"} if failed else {"status": "success"}
    return [
        StreamEvent(
            type=StreamEventType.TOOL_USE,
            data={"id": call_id, "name": name, "status": "complete", "input": {}},
        ),
        StreamEvent(
            type=StreamEventType.TOOL_RESULT,
            data={
                "tool_use_id": call_id,
                "name": name,
                "result": {"content": [{"type": "text", "text": json.dumps(payload)}]},
            },
        ),
    ]


def _create(state, call_id: str, file_id: str, title: str) -> list[StreamEvent]:
    """一次成功的 create_file：台账记账（runner 做的事）+ 工具事件。"""
    state["repeat_read_guard"].observe(
        "create_file",
        ReadPlan(arguments=json.dumps({"title": title})),
        json.dumps({"status": "success", "data": {"id": file_id, "title": title}}),
    )
    return _tool(call_id, "create_file")


def _file(body: str) -> StreamEvent:
    return _text(f"<file>\n{body}\n</file>\n")


async def _run(
    fake_agent,
    *,
    message: str = "把后面几集都写了",
    initial: str = "writer",
    workflow_agents: list[str] | None = None,
    routing_metadata: dict | None = None,
    max_iterations: int = 12,
    tasks: list[dict] | None = None,
) -> list[StreamEvent]:
    from agent.graph.writing_graph import run_writing_workflow_streaming

    router_result = {
        "current_agent": initial,
        "workflow_plan": "standard" if workflow_agents else "quick",
        "workflow_agents": list(workflow_agents or []),
        "routing_metadata": routing_metadata or {"agent_type": initial},
    }
    state = {"user_message": message, "messages": [], "system_prompt": ""}
    ToolContext.set_context(session=None, user_id="u", project_id="p", session_id="s")
    try:
        with (
            patch("agent.graph.writing_graph.router_node", AsyncMock(return_value=router_result)),
            patch("agent.graph.writing_graph.run_streaming_agent", new=fake_agent),
            patch("agent.tools.mcp_tools.ToolContext.refresh_file_inventory", return_value={}),
            patch(
                "services.infra.task_board_service.task_board_service.get_tasks",
                return_value=list(tasks or []),
            ),
            patch(
                "agent.graph.writing_graph._auto_finalize_task_board_on_completion",
                AsyncMock(return_value=[]),
            ),
        ):
            return [
                event
                async for event in run_writing_workflow_streaming(
                    state=state,
                    thread_id="t",
                    max_iterations=max_iterations,
                    auto_review_threshold=10**9,
                )
            ]
    finally:
        ToolContext.clear_context()


def _visible_text(events: list[StreamEvent]) -> str:
    return "".join(
        str(event.data.get("text") or "") for event in events if event.type == StreamEventType.TEXT
    )


# ---------------------------------------------------------------- I08: 续写


async def test_writer_that_stops_at_file_close_continues_and_summarizes():
    """U076 形状：要写完剩下几集，只写了第2集就停在 </file>；同一轮里接着写完并给总结。"""
    runs: list[tuple[str, str]] = []

    async def fake_agent(state, agent_type, *_args, **_kwargs):
        runs.append((agent_type, str(state.get("user_message") or "")))
        if len(runs) == 1:
            yield _text("我先写第2集。")
            for event in _create(state, "c1", "f2", "第2集 暗流"):
                yield event
            yield _file("第二集正文。" * 20)
        elif len(runs) == 2:
            for event in _create(state, "c2", "f3", "第3集 摊牌"):
                yield event
            yield _file("第三集正文。" * 20)
            yield _text("第2集、第3集都写好了，各约 120 字。")

    events = await _run(
        fake_agent,
        tasks=[{"task": "撰写第2-3集剧本", "status": "in_progress"}],
        routing_metadata={"agent_type": "writer", "scope": "第2-3集"},
    )

    assert [agent for agent, _ in runs] == ["writer", "writer"]
    continuation = runs[1][1]
    assert "上一次回复写完 </file> 就结束了" in continuation
    assert "《第2集 暗流》" in continuation
    assert "撰写第2-3集剧本（进行中）" in continuation
    assert "第2-3集" in continuation
    # 作者最后看到的是总结，不是空回复或开场句。
    assert author_text_outside_files(_visible_text(events)).endswith("各约 120 字。")
    assert not any(event.type == StreamEventType.ITERATION_EXHAUSTED for event in events)


async def test_planner_finishes_its_plan_before_the_planned_writer_runs():
    """U088 形状：规划师计划建卷二到卷五，只建了卷二就停在 </file>；先续写，再交给 writer。"""
    runs: list[str] = []

    async def fake_agent(state, agent_type, *_args, **_kwargs):
        runs.append(agent_type)
        if agent_type == "planner" and runs.count("planner") == 1:
            for event in _create(state, "p1", "v2", "卷二大纲"):
                yield event
            yield _file("卷二规划。" * 20)
        elif agent_type == "planner":
            for event in _create(state, "p2", "v3", "卷三大纲"):
                yield event
            yield _file("卷三规划。" * 20)
            yield _text("卷二、卷三大纲已写好。")
        else:
            yield _text("第一章写好了。")

    await _run(fake_agent, initial="planner", workflow_agents=["writer"])

    assert runs == ["planner", "planner", "writer"]


async def test_reply_with_summary_after_file_close_is_not_continued():
    runs: list[str] = []

    async def fake_agent(state, agent_type, *_args, **_kwargs):
        runs.append(agent_type)
        for event in _create(state, "c1", "f2", "第2集"):
            yield event
        yield _file("第二集正文。" * 20)
        yield _text("第2集写好了，约 120 字。")

    await _run(fake_agent)

    assert runs == ["writer"]


async def test_last_iteration_does_not_schedule_a_continuation():
    runs: list[str] = []

    async def fake_agent(state, agent_type, *_args, **_kwargs):
        runs.append(agent_type)
        for event in _create(state, "c1", "f2", "第2集"):
            yield event
        yield _file("第二集正文。" * 20)

    events = await _run(fake_agent, max_iterations=1)

    assert runs == ["writer"]
    assert any(event.type == StreamEventType.ITERATION_EXHAUSTED for event in events)


async def test_file_block_without_a_create_file_in_the_run_is_not_continued():
    """没有 create_file 的 <file> 块（U074）不归续写管：这一轮没有新建文件可接。"""
    runs: list[str] = []

    async def fake_agent(_state, agent_type, *_args, **_kwargs):
        runs.append(agent_type)
        yield _file("短剧改编方案。" * 20)

    await _run(fake_agent)

    assert runs == ["writer"]


async def test_rework_writer_that_stops_at_file_close_continues():
    """U076 06:20 形状：审稿人交回返修后 writer 写了两集就停在 </file>（不再自动送审）。"""
    runs: list[str] = []

    async def fake_agent(state, agent_type, *_args, **_kwargs):
        runs.append(agent_type)
        if agent_type == "quality_reviewer":
            yield _text("第2集结尾要补。")
            yield StreamEvent(
                type=StreamEventType.HANDOFF,
                data={"target_agent": "writer", "reason": "返修", "context": "补第2集结尾，再写第3集"},
            )
            return
        writer_runs = runs.count("writer")
        if writer_runs == 1:
            yield _text("第2集写好了。")
            yield StreamEvent(
                type=StreamEventType.HANDOFF,
                data={"target_agent": "quality_reviewer", "reason": "请审稿", "context": "请审稿"},
            )
        elif writer_runs == 2:
            for event in _create(state, "c3", "f3", "第3集"):
                yield event
            yield _file("第三集正文。" * 20)
        else:
            yield _text("第3集写好了，第2集结尾也补上了。")

    await _run(fake_agent)

    assert runs == ["writer", "quality_reviewer", "writer", "writer"]


# ------------------------------------------------- I09: 说改了，本请求却没有写入


async def test_claimed_revert_without_any_write_reruns_the_agent_once():
    """U044 形状：作者只是解释断句，回复「已还原」却零工具调用。"""
    runs: list[tuple[str, str]] = []

    async def fake_agent(state, agent_type, *_args, **_kwargs):
        runs.append((agent_type, str(state.get("user_message") or "")))
        if len(runs) == 1:
            yield _text("已还原：第二章那句仍作原文，别处未动。\n[TASK_COMPLETE]")
        else:
            for event in _tool("e1", "edit_file"):
                yield event
            yield _text("把刚才加的逗号删掉了，第二章那句恢复成你的原文。")

    events = await _run(fake_agent, message="我只是在解释断句")

    assert [agent for agent, _ in runs] == ["writer", "writer"]
    assert "你刚才对作者说「已还原」" in runs[1][1]
    assert "没有任何文件或项目信息被实际修改" in runs[1][1]
    assert "更正：这一轮实际没有修改" not in _visible_text(events)


async def test_repeated_unbacked_claim_gets_a_correction_notice():
    runs: list[str] = []

    async def fake_agent(_state, agent_type, *_args, **_kwargs):
        runs.append(agent_type)
        yield _text("已录入项目记忆。")

    events = await _run(fake_agent, message="记住主角叫陈默")

    assert runs == ["writer", "writer"]
    assert _visible_text(events).count("更正：这一轮实际没有修改任何文件或项目信息。") == 1


async def test_unbacked_claim_on_read_only_request_is_corrected_without_rerun():
    runs: list[str] = []

    async def fake_agent(_state, agent_type, *_args, **_kwargs):
        runs.append(agent_type)
        yield _text("已保存到第二章。")

    events = await _run(
        fake_agent,
        message="只回答，不要改文件",
        routing_metadata={"agent_type": "writer", "read_only": True},
    )

    assert runs == ["writer"]
    assert "更正：这一轮实际没有修改任何文件或项目信息。" in _visible_text(events)


async def test_claim_backed_by_a_successful_write_is_left_alone():
    runs: list[str] = []

    async def fake_agent(_state, agent_type, *_args, **_kwargs):
        runs.append(agent_type)
        for event in _tool("e1", "edit_file"):
            yield event
        yield _text("已改好第二章的称呼。")

    events = await _run(fake_agent)

    assert runs == ["writer"]
    assert "更正" not in _visible_text(events)


async def test_claim_after_only_failed_writes_is_rechecked():
    runs: list[str] = []

    async def fake_agent(_state, agent_type, *_args, **_kwargs):
        runs.append(agent_type)
        if len(runs) == 1:
            for event in _tool("e1", "edit_file", failed=True):
                yield event
            yield _text("已改好第二章的称呼。")
        else:
            yield _text("刚才的修改没有成功，第二章还没改。")

    await _run(fake_agent)

    assert runs == ["writer", "writer"]


async def test_reviewer_wording_is_not_checked():
    """审稿人没有写权限，它说的「已修改」指别人改的内容。"""
    runs: list[str] = []

    async def fake_agent(_state, agent_type, *_args, **_kwargs):
        runs.append(agent_type)
        yield _text("第二章已修改的部分读起来顺了。")

    events = await _run(fake_agent, initial="quality_reviewer", message="审一下第二章")

    assert runs == ["quality_reviewer"]
    assert "更正" not in _visible_text(events)


# ------------------------------------------------------------ 文字信号


@pytest.mark.parametrize(
    ("tail", "expected"),
    [
        ("<file>\n正文\n</file>\n", True),
        ("<file>\n正文\n</file>\n[TASK_COMPLETE]", True),
        ("<file>\n正文\n</file>\n<file>\n</file>\n", True),
        ("<file>\n正文\n</file>\n写好了第2集。", False),
        ("<file>\n\n</file>\n", False),
        ("只是一句话", False),
        ("", False),
    ],
)
async def test_ends_on_file_block(tail, expected):
    assert ends_on_file_block(tail) is expected


@pytest.mark.parametrize(
    ("text", "claim"),
    [
        ("收到。\n\n已还原：第二章那句仍作原文。", "已还原"),
        ("已录入项目记忆。", "已录入"),
        ("兩處都已經刪除了。", "已經刪除"),
        ("第二章改好了。", "改好了"),
        ("你之前已修改的第二章很好。", None),
        ("上一轮已经写好第一章。", None),
        ("这段还没保存。", None),
        ("<file>\n已保存\n</file>\n", None),
        ("你觉得接下来会发生什么？我认为雷池会认他。", None),
    ],
)
async def test_find_unbacked_change_claim(text, claim):
    assert find_unbacked_change_claim(text) == claim
