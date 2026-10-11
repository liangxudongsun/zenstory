"""任务计划板只把确实写出对应产物的任务标为 done（I09）。

线上：「撰寫第2-5集劇本」只写了第2集、「第一卷正文（第1-119章）」只写了 4 章，收尾时工作流把
in_progress 任务无条件改成 done。现在按本请求实际写出、仍存在且有正文的文件核对。
"""

from __future__ import annotations

import importlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.graph.writing_graph import (
    _auto_finalize_task_board_on_completion,
    _build_completion_task_payload,
    _existing_written_titles,
)
from agent.openai_agents.repeat_read_guard import ReadPlan, RepeatReadGuard
from agent.tools.file_ops.project import ProjectOperations
from agent.tools.mcp_tools import ToolContext
from agent.tools.task_progress import format_units, task_unit_spec, title_units

pytestmark = pytest.mark.unit


def _range_task(status: str = "in_progress", **extra) -> dict:
    return {"task": "撰寫第2-5集劇本", "status": status, **extra}


# ------------------------------------------------------------ 收尾 payload


def test_partial_range_stays_in_progress_with_written_and_pending_parts():
    payload = _build_completion_task_payload([_range_task()], ["第2集 暗流"])

    assert payload == [
        {
            "task": "撰寫第2-5集劇本",
            "status": "in_progress",
            "done_units": [2],
            "progress": "已写：第2集；待写：第3–5集",
        }
    ]


def test_range_completed_across_requests_is_marked_done():
    task = _range_task(done_units=[2, 3], progress="已写：第2–3集；待写：第4–5集")

    payload = _build_completion_task_payload([task], ["第4集", "第五集 收网"])

    assert payload == [{"task": "撰寫第2-5集劇本", "status": "done"}]


def test_fully_written_range_is_done():
    titles = ["第1章 开端", "第2章", "第3章"]
    payload = _build_completion_task_payload(
        [{"task": "第一卷正文（第1-3章）", "status": "in_progress"}], titles
    )
    assert payload is not None and payload[0]["status"] == "done"


def test_nothing_written_changes_nothing():
    assert _build_completion_task_payload([_range_task()], []) is None
    assert _build_completion_task_payload([{"task": "整理设定", "status": "in_progress"}], []) is None


def test_range_with_no_matching_file_is_left_alone():
    assert _build_completion_task_payload([_range_task()], ["人物小传"]) is None


def test_artifact_task_needs_that_artifact():
    """U095 形状：任务产出物是总纲，本请求只写了世界观设定。"""
    task = {"task": "写总纲初稿", "status": "in_progress", "artifact": "《总纲》"}

    assert _build_completion_task_payload([task], ["世界观与成长体系"]) is None
    done = _build_completion_task_payload([task], ["总纲"])
    assert done is not None and done[0]["status"] == "done"


def test_plain_task_is_done_when_something_was_written_and_pending_untouched():
    tasks = [
        {"task": "整理人物关系", "status": "in_progress"},
        {"task": "写第6集", "status": "pending"},
    ]

    payload = _build_completion_task_payload(tasks, ["人物关系"])

    assert payload == [
        {"task": "整理人物关系", "status": "done"},
        {"task": "写第6集", "status": "pending"},
    ]


# ------------------------------------------------------------ 收尾调用


def _guard_with_write(file_id: str = "f2", title: str = "第2集") -> RepeatReadGuard:
    guard = RepeatReadGuard()
    guard.observe(
        "create_file",
        ReadPlan(arguments=json.dumps({"title": title})),
        json.dumps({"status": "success", "data": {"id": file_id, "title": title}}),
    )
    return guard


@pytest.mark.asyncio
async def test_finalize_without_any_write_does_not_touch_the_board():
    update = AsyncMock()
    ToolContext.set_context(session=None, user_id="u", project_id="p", session_id="s")
    try:
        with (
            patch(
                "services.infra.task_board_service.task_board_service.get_tasks",
                return_value=[_range_task()],
            ),
            patch("agent.graph.writing_graph.update_project", update),
        ):
            assert await _auto_finalize_task_board_on_completion(RepeatReadGuard()) == []
            assert await _auto_finalize_task_board_on_completion(None) == []
    finally:
        ToolContext.clear_context()
    update.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalize_records_partial_progress_from_existing_files():
    update = AsyncMock(return_value={"content": []})
    ToolContext.set_context(session=None, user_id="u", project_id="p", session_id="s")
    try:
        with (
            patch(
                "services.infra.task_board_service.task_board_service.get_tasks",
                return_value=[_range_task()],
            ),
            patch(
                "agent.graph.writing_graph._existing_written_titles", return_value=["第2集"]
            ) as titles,
            patch("agent.graph.writing_graph.update_project", update),
        ):
            events = await _auto_finalize_task_board_on_completion(_guard_with_write())
    finally:
        ToolContext.clear_context()

    titles.assert_called_once_with(["f2"])
    sent = update.await_args.args[0]["tasks"]
    assert sent[0]["status"] == "in_progress"
    assert sent[0]["progress"] == "已写：第2集；待写：第3–5集"
    assert events and events[0].data["input"]["tasks"] == sent


def test_existing_written_titles_skips_deleted_and_empty_files(db_session):
    from models import File

    def _file(title: str, content: str, *, deleted: bool = False) -> str:
        row = File(
            project_id="project-task-board",
            title=title,
            content=content,
            file_type="script",
            is_deleted=deleted,
        )
        db_session.add(row)
        db_session.commit()
        db_session.refresh(row)
        return row.id

    ids = [
        _file("第2集", "正文"),
        _file("第3集", "   "),
        _file("第4集", "正文", deleted=True),
    ]
    ToolContext.set_context(
        session=db_session, user_id="u", project_id="project-task-board", session_id="s"
    )
    try:
        assert _existing_written_titles(ids) == ["第2集"]
    finally:
        ToolContext.clear_context()


# ------------------------------------------------- 模型自己标 done 时的提醒


def _mock_task_board(monkeypatch, previous_tasks):
    module = importlib.import_module("services.infra.task_board_service")
    service = MagicMock()
    service.get_tasks.return_value = previous_tasks
    service.save_tasks.return_value = True
    monkeypatch.setattr(module, "task_board_service", service)
    return service


def _ops_with_titles(rows: list[tuple[str, str]]) -> ProjectOperations:
    session = MagicMock()
    session.exec.return_value.all.return_value = rows
    return ProjectOperations(session=session, user_id="u")


def test_model_marking_a_partial_range_done_gets_a_warning(monkeypatch):
    _mock_task_board(monkeypatch, [_range_task()])
    ops = _ops_with_titles([("第2集", "正文"), ("第3集", "")])

    result = ops.execute_update_plan(
        session_id="s", tasks=[_range_task(status="done")], user_id="u", project_id="p"
    )

    assert result["status"] == "success"
    assert result["unverified_done"] == [{"task": "撰寫第2-5集劇本", "missing": "第3–5集"}]
    assert "缺第3–5集" in result["message"]
    assert "如实告诉作者" in result["message"]


def test_model_marking_a_written_range_done_has_no_warning(monkeypatch):
    _mock_task_board(monkeypatch, [_range_task()])
    ops = _ops_with_titles([(f"第{n}集", "正文") for n in range(2, 6)])

    result = ops.execute_update_plan(
        session_id="s", tasks=[_range_task(status="done")], user_id="u", project_id="p"
    )

    assert "unverified_done" not in result
    assert result["message"] == "任务计划板已更新"


def test_task_that_was_already_done_is_not_rechecked(monkeypatch):
    _mock_task_board(monkeypatch, [_range_task(status="done")])
    ops = _ops_with_titles([])

    result = ops.execute_update_plan(
        session_id="s", tasks=[_range_task(status="done")], user_id="u", project_id="p"
    )

    assert "unverified_done" not in result
    ops.session.exec.assert_not_called()


# ------------------------------------------------------------ 编号解析


@pytest.mark.parametrize(
    ("text", "unit", "numbers"),
    [
        ("撰寫第2-5集劇本", "集", {2, 3, 4, 5}),
        ("第一卷正文（第1-119章）", "章", set(range(1, 120))),
        ("卷二到卷五大纲", "卷", {2, 3, 4, 5}),
        ("写第四至十二集", "集", set(range(4, 13))),
        ("写第3章", "章", {3}),
    ],
)
def test_task_unit_spec(text, unit, numbers):
    spec = task_unit_spec(text)
    assert spec is not None
    assert spec.unit == unit
    assert set(spec.numbers) == numbers


def test_task_without_numbers_has_no_spec():
    assert task_unit_spec("整理人物关系") is None


def test_title_units_and_format():
    assert title_units(["第2集 开端", "第03集", "第1-10章大纲"], "集") == {2, 3}
    assert title_units(["卷二：风起", "第三卷"], "卷") == {2, 3}
    assert format_units({2, 3, 4, 6, 8, 9}, "集") == "第2–4、6、8–9集"


def test_board_prompt_shows_recorded_progress(monkeypatch):
    from agent.core.message_manager import MessageManager

    _mock_task_board(
        monkeypatch,
        [_range_task(progress="已写：第2集；待写：第3–5集"), {"task": "收尾", "status": "pending"}],
    )
    manager = MessageManager.__new__(MessageManager)
    manager.user_id = "u"
    manager.project_id = "p"

    text = "\n".join(manager._build_task_board_section("s", force_en=False))

    assert "🔄 撰寫第2-5集劇本（已写：第2集；待写：第3–5集）" in text
    assert "⏳ 收尾" in text
