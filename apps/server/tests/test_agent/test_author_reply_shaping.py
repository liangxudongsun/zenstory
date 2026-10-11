"""作者看到的回复只有一份总结、字数用编辑器的数（I03 / I05 回归，全部 mock，不调用模型）。

- 被审稿取代的 writer 总结不进作者看到的回复（writing_graph CHAT_HOLD + StreamAdapter）
- IDLE 下独占一行的 <file> / </file> 不进对话（StreamProcessor）
- 自动质检门只看本轮写进 draft / script 的字数（body_writes）
- 送审交接带编辑器字数和作者在本会话 / 项目设定里说过的篇幅要求
- 同一个 agent 隔着工具调用的两段文字之间补空行（AgentTextShaper）

测试文本都是自己构造的，不来自真实作品。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agent.core.events import EventType
from agent.core.workflow_events import CHAT_HOLD_BEGIN, CHAT_HOLD_DISCARD, StreamEvent, StreamEventType
from tests.test_agent.body_write_events import create_file_events, edit_file_events

BODY = "林晚推开铁门，炉火映着她的侧脸。" * 30  # 450 字
WRITER_SUMMARY = "第三章写好了，共 2781 字。\n\n- 开头补了雨夜\n\n接着可以回：\n- 写第四章"
REVIEWER_SUMMARY = "《第三章》写好了，编辑器字数 450。\n\n可以接着写第四章。\n[TASK_COMPLETE]"


def _text(text: str) -> StreamEvent:
    return StreamEvent(type=StreamEventType.TEXT, data={"text": text})


def _handoff(target: str, context: str) -> StreamEvent:
    return StreamEvent(
        type=StreamEventType.HANDOFF,
        data={
            "target_agent": target,
            "reason": "第三章有一句和第一章重复，改一下",
            "context": context,
            "handoff_packet": {
                "target_agent": target,
                "reason": "第三章有一句和第一章重复，改一下",
                "context": context,
                "completed": [],
                "todo": ["改第三章结尾那句"],
                "evidence": [],
            },
        },
    )


def _writer_writes_chapter(*, summary: str = WRITER_SUMMARY, body: str = BODY):
    events = [*create_file_events("draft-3", "第三章"), _text(f"<file>{body}</file>\n\n"), _text(summary)]
    return events


async def _run_graph(fake_agent, *, generation_mode: str = "", session=None, project_id="p", session_id="s"):
    from agent.graph.writing_graph import run_writing_workflow_streaming
    from agent.tools.mcp_tools import ToolContext

    router = AsyncMock(return_value={"current_agent": "writer", "workflow_plan": "quick", "workflow_agents": []})
    ToolContext.set_context(
        session=session, user_id="u", project_id=project_id, session_id=session_id, author_message="写第三章"
    )
    state = {
        "user_message": "写第三章",
        "router_message": "写第三章",
        "messages": [{"role": "user", "content": "写第三章"}],
        "system_prompt": "",
        "generation_mode": generation_mode,
    }
    try:
        with (
            patch.dict("os.environ", {"AGENT_ENABLE_GRAPH_AUTO_REVIEW": "true"}),
            patch("agent.graph.writing_graph.router_node", router),
            patch("agent.graph.writing_graph.run_streaming_agent", new=fake_agent),
            patch("agent.tools.mcp_tools.ToolContext.refresh_file_inventory", return_value={}),
            patch(
                "agent.graph.writing_graph._auto_finalize_task_board_on_completion",
                AsyncMock(return_value=[]),
            ),
        ):
            return [
                event
                async for event in run_writing_workflow_streaming(
                    state=state, thread_id="t", auto_review_threshold=100
                )
            ]
    finally:
        ToolContext.clear_pending_empty_file()


async def _author_visible_text(graph_events: list[StreamEvent]) -> str:
    """把图的事件按生产顺序交给 StreamAdapter，拼出作者看到（也是存进历史）的回复正文。"""
    from agent.stream_adapter import create_stream_adapter

    adapter = create_stream_adapter(project_id="p", user_id="u", process_file_markers=True)
    adapter._save_file_content = AsyncMock(return_value=True)

    async def _events():
        for event in graph_events:
            yield event

    chunks = [
        sse.data.get("text", "")
        async for sse in adapter.process_workflow_events(_events())
        if sse.type == EventType.CONTENT
    ]
    return "".join(chunks)


# ------------------------------------------------------------- 一份总结（I03）


@pytest.mark.asyncio
@pytest.mark.unit
async def test_writer_summary_superseded_by_review_is_not_shown_to_author():
    """自动送审时 writer 的总结（含估算的「2781 字」）不出现，作者只看到审稿人那一份。"""
    calls: list[str] = []

    async def fake_agent(state, agent_type, *_args, **_kwargs):
        calls.append(agent_type)
        if agent_type == "writer":
            for event in _writer_writes_chapter():
                yield event
            return
        yield _text(REVIEWER_SUMMARY)

    events = await _run_graph(fake_agent)

    assert calls == ["writer", "quality_reviewer"]
    kinds = [(e.type, e.data.get("action")) for e in events if e.type in (StreamEventType.CHAT_HOLD, StreamEventType.HANDOFF)]
    assert kinds == [
        (StreamEventType.CHAT_HOLD, CHAT_HOLD_BEGIN),
        (StreamEventType.CHAT_HOLD, CHAT_HOLD_DISCARD),
        (StreamEventType.HANDOFF, None),
    ]

    visible = await _author_visible_text(events)
    assert "2781" not in visible
    assert "第三章写好了，共" not in visible
    assert "编辑器字数 450" in visible
    assert visible.count("写好了") == 1, "作者只看到一份总结"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_writer_summary_is_shown_when_no_review_follows():
    """快速模式不送审：writer 的回复照常流式给作者（不扣）。"""

    async def fake_agent(state, agent_type, *_args, **_kwargs):
        for event in _writer_writes_chapter(summary="第三章写好了。"):
            yield event

    events = await _run_graph(fake_agent, generation_mode="fast")

    assert not any(e.type == StreamEventType.CHAT_HOLD for e in events)
    assert "第三章写好了。" in await _author_visible_text(events)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_held_summary_is_released_when_review_does_not_follow():
    """写完正文后先扣住文字，但正文太短不送审：扣着的文字照常放给作者，不丢。"""

    async def fake_agent(state, agent_type, *_args, **_kwargs):
        for event in _writer_writes_chapter(body="短短一段。", summary="补了一句。"):
            yield event

    events = await _run_graph(fake_agent)

    assert [e.data.get("action") for e in events if e.type == StreamEventType.CHAT_HOLD] == [CHAT_HOLD_BEGIN]
    assert "补了一句。" in await _author_visible_text(events)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_rework_writer_is_told_its_earlier_summary_was_not_shown():
    """审稿人交回返修：writer 被告知送检前的说明作者没看到，修完的回复是唯一一份总结。"""
    from agent.graph.writing_graph import WRITER_REWORK_AFTER_SUPERSEDED_NOTE

    messages: list[str] = []

    async def fake_agent(state, agent_type, *_args, **_kwargs):
        messages.append(state["user_message"])
        if agent_type == "writer" and len(messages) == 1:
            for event in _writer_writes_chapter():
                yield event
            return
        if agent_type == "quality_reviewer":
            yield _handoff("writer", "把结尾那句换个写法")
            return
        for event in edit_file_events("fix-1", "她把炉门带上。", file_id="draft-3", title="第三章"):
            yield event
        yield _text("第三章结尾改好了，现在 452 字。")

    events = await _run_graph(fake_agent)

    assert len(messages) == 3
    assert WRITER_REWORK_AFTER_SUPERSEDED_NOTE in messages[2]
    visible = await _author_visible_text(events)
    assert "2781" not in visible
    assert "现在 452 字" in visible


# ------------------------------------------------------------- 独占一行的标签（I03）


@pytest.mark.asyncio
@pytest.mark.unit
async def test_lone_close_tag_after_summary_does_not_reach_chat():
    """U082 的形态：正文收尾后又读了一次文件，总结末尾单独一行「</file>」。"""
    from agent.stream_adapter import create_stream_adapter

    adapter = create_stream_adapter(project_id="p", user_id="u", process_file_markers=True)
    adapter._save_file_content = AsyncMock(return_value=True)
    events = [
        *create_file_events("draft-3", "第三章"),
        _text("<file>正文。</file>\n\n第三章写好了，我再通读一遍。"),
        StreamEvent(
            type=StreamEventType.TOOL_USE,
            data={"id": "q1", "name": "query_files", "status": "complete", "input": {"id": "draft-3"}},
        ),
        _text("第三章按倒叙写完。\n\n接着可以回：\n- 写第四章\n</fi"),
        _text("le>\n\n我先读取第三章当前全文。"),
        StreamEvent(type=StreamEventType.MESSAGE_END, data={}),
    ]

    async def _events():
        for event in events:
            yield event

    chat = "".join(
        [sse.data.get("text", "") async for sse in adapter.process_workflow_events(_events()) if sse.type == EventType.CONTENT]
    )

    assert "</file>" not in chat
    assert "- 写第四章\n\n我先读取第三章当前全文。" in chat


@pytest.mark.unit
@pytest.mark.parametrize(
    "chunks, expected",
    [
        (["示例：\n```\n</file>\n```\n"], "示例：\n```\n</file>\n```\n"),
        (["写成 `</file>` 就行\n"], "写成 `</file>` 就行\n"),
        (["正文要用 <file> 包起来\n"], "正文要用 <file> 包起来\n"),
        (["结尾\n<file>\n第二段\n"], "结尾\n第二段\n"),
    ],
)
def test_lone_tag_rule_keeps_literal_tags(chunks, expected):
    from agent.core.stream_processor import StreamProcessor

    proc = StreamProcessor()
    out = "".join(proc.process_content(chunk).conversation_content for chunk in chunks)
    out += proc.finalize_on_stream_end().conversation_content
    assert out == expected


# ------------------------------------------------------------- 自动质检门（I03）


@pytest.mark.asyncio
@pytest.mark.unit
async def test_long_reply_after_outline_edit_is_not_auto_reviewed():
    """改大纲（outline）时说明写得再长，也不送审。"""
    calls: list[str] = []

    async def fake_agent(state, agent_type, *_args, **_kwargs):
        calls.append(agent_type)
        for event in edit_file_events("e1", "第三章改成倒叙。", file_id="outline-1", title="卷一大纲", file_type="outline"):
            yield event
        yield _text("大纲改好了。" + "这一卷的节奏调整说明。" * 60)

    events = await _run_graph(fake_agent)

    assert calls == ["writer"]
    assert not any(e.type == StreamEventType.HANDOFF for e in events)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_small_draft_fix_with_long_explanation_is_not_auto_reviewed():
    """正文只改了几个字，说明却很长：按写进正文的字数判断，不送审。"""
    calls: list[str] = []

    async def fake_agent(state, agent_type, *_args, **_kwargs):
        calls.append(agent_type)
        for event in edit_file_events("e1", "老锻", file_id="draft-3", title="第三章"):
            yield event
        yield _text("把「老段」改成了「老锻」。" + "前后文里这个名字的用法说明。" * 60)

    await _run_graph(fake_agent)

    assert calls == ["writer"]


@pytest.mark.asyncio
@pytest.mark.unit
async def test_short_chat_after_long_streamed_body_is_auto_reviewed():
    calls: list[str] = []

    async def fake_agent(state, agent_type, *_args, **_kwargs):
        calls.append(agent_type)
        if agent_type == "writer":
            for event in _writer_writes_chapter(summary="写好了。"):
                yield event
            return
        yield _text(REVIEWER_SUMMARY)

    await _run_graph(fake_agent)

    assert calls == ["writer", "quality_reviewer"]


# ------------------------------------------------------------- 字数与篇幅要求（I05）


@pytest.fixture
def project_with_history(db_session):
    from models import ChatMessage, ChatSession, File, Project, User

    user = User(
        email="reply_shaping@example.com",
        username="replyshaping",
        hashed_password="x",
        name="Reply Shaping",
        email_verified=True,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    project = Project(
        name="Reply Shaping",
        owner_id=user.id,
        project_type="novel",
        writing_style="第一人称，每章约2500字左右",
    )
    db_session.add(project)
    db_session.commit()
    chat = ChatSession(user_id=user.id, project_id=project.id)
    db_session.add(chat)
    db_session.commit()
    for content in ("写一部都市小说，单章约 2000 字。", "好的"):
        db_session.add(ChatMessage(session_id=chat.id, role="user", content=content))
    db_session.commit()
    chapter = File(project_id=project.id, title="第三章", content=BODY, file_type="draft")
    db_session.add(chapter)
    db_session.commit()
    db_session.refresh(chapter)
    return {"project": project, "chat": chat, "chapter": chapter}


@pytest.mark.asyncio
@pytest.mark.unit
async def test_review_handoff_carries_editor_count_and_earlier_length_requirements(db_session, project_with_history):
    """writer 交接写「约2800字」，审稿人拿到编辑器字数，以及本会话早先和项目设定里的篇幅要求。"""
    from agent.graph.writing_graph import BODY_WORD_COUNT_HEADER, LENGTH_REQUIREMENT_HEADER
    from utils.text_metrics import count_words

    chapter = project_with_history["chapter"]
    reviewer_messages: list[str] = []

    async def fake_agent(state, agent_type, *_args, **_kwargs):
        if agent_type == "writer":
            state["repeat_read_guard"]._record_write(chapter.id, "第三章")
            for event in edit_file_events("e1", BODY, file_id=chapter.id, title="第三章"):
                yield event
            yield _text("第三章写好了，约2800字，我再通读核对一遍。")
            yield _handoff("quality_reviewer", "第三章约2800字，请检查")
            return
        reviewer_messages.append(state["user_message"])
        yield _text(REVIEWER_SUMMARY)

    events = await _run_graph(
        fake_agent,
        session=db_session,
        project_id=project_with_history["project"].id,
        session_id=project_with_history["chat"].id,
    )

    assert len(reviewer_messages) == 1
    message = reviewer_messages[0]
    counts = message.split(BODY_WORD_COUNT_HEADER + "\n", 1)[1]
    assert counts.startswith(f"- 《第三章》{count_words(BODY)} 字\n")
    requirements = message.split(LENGTH_REQUIREMENT_HEADER + "\n", 1)[1]
    assert "「写一部都市小说，单章约 2000 字」（作者在本会话说过）" in requirements
    assert "「第一人称，每章约2500字左右」（项目写作风格）" in requirements
    packet = next(e for e in events if e.type == StreamEventType.HANDOFF).data["handoff_packet"]
    assert f"《第三章》编辑器字数 {count_words(BODY)}" in packet["evidence"]


@pytest.mark.unit
def test_find_length_requirements_quotes_only_length_clauses():
    from agent.graph.review_evidence import find_length_requirements

    found = find_length_requirements(
        [
            ("项目写作风格", "节奏快。每集约500-900字，台词短"),
            ("作者在本会话说过", "主角叫陈默。他写了三千字的检讨"),
            ("作者在本会话说过", "第一章字数太少了，没有2500字"),
            ("作者本轮原话", "还得改，每章字数要求1000字以上"),
            ("作者本轮原话", "还得改，每章字数要求1000字以上"),
        ]
    )

    assert found == [
        "「每集约500-900字，台词短」（项目写作风格）",
        "「第一章字数太少了，没有2500字」（作者在本会话说过）",
        "「还得改，每章字数要求1000字以上」（作者本轮原话）",
    ]


# ------------------------------------------------------------- 段落分隔（I03）


@pytest.mark.unit
def test_segments_of_one_agent_separated_by_tool_calls_are_not_glued():
    from agent.core.author_facing_text import AgentTextShaper

    shaper = AgentTextShaper(previous_text="", drop_english_narration=True)
    out = shaper.feed("正在读取第三章。")
    out += shaper.end_segment(before_tool_call=True)
    out += shaper.feed("正在核对细纲。")
    out += shaper.end_segment(before_tool_call=True)
    out += shaper.feed("<file>正文</file>")
    out += shaper.end_segment(before_tool_call=False)

    assert out == "正在读取第三章。\n\n正在核对细纲。<file>正文</file>"


@pytest.mark.unit
def test_body_write_tracker_counts_only_successful_body_writes():
    import json

    from agent.graph.body_writes import BodyWriteTracker, body_words_written

    tracker = BodyWriteTracker()
    text = ""
    parallel_input = {
        "tasks": [
            {"type": "write_chapter", "params": {"title": "第四章", "content": "雨停了。" * 10, "parent_id": "d"}},
            {"type": "edit_file", "params": {"id": "lore-1", "edits": [{"op": "append", "text": "设定" * 50}]}},
            {"type": "write_chapter", "params": {"title": "第五章", "content": "失败的章节" * 20, "parent_id": "d"}},
        ]
    }
    parallel_result = {
        "status": "success",
        "data": {
            "tasks": [
                {"type": "write_chapter", "status": "completed", "result": {"data": {"id": "c4", "file_type": "draft"}}},
                {"type": "edit_file", "status": "completed", "result": {"data": {"id": "lore-1", "file_type": "lore"}}},
                {"type": "write_chapter", "status": "failed", "result": None},
            ]
        },
    }
    events = [
        *create_file_events("draft-3", "第三章"),
        StreamEvent(type=StreamEventType.TOOL_USE, data={"id": "p1", "name": "parallel_execute", "status": "complete", "input": parallel_input}),
        StreamEvent(
            type=StreamEventType.TOOL_RESULT,
            data={"tool_use_id": "p1", "name": "parallel_execute", "result": {"content": [{"type": "text", "text": json.dumps(parallel_result, ensure_ascii=False)}]}},
        ),
        *edit_file_events("e-bad", "写不进去" * 50, file_id="draft-3", status="error"),
    ]
    for event in events[:2]:
        tracker.observe(event, text_length=len(text))
    text += "<file>" + "她笑了。" * 5 + "</file>\n\n写好了。"
    for event in events[2:]:
        tracker.observe(event, text_length=len(text))

    writes = tracker.finish(text)

    assert [(w.file_id, w.words, w.full_body) for w in writes] == [("draft-3", 15, True), ("c4", 30, True)]
    assert body_words_written(writes) == 45
