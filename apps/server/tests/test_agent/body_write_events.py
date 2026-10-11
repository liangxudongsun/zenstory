"""测试用的「写进正文类文件」工具事件（自动质检门只看 draft / script 的写入，见 body_writes.py）。"""

from __future__ import annotations

import json

from agent.core.workflow_events import StreamEvent, StreamEventType


def _result(call_id: str, name: str, payload: dict) -> StreamEvent:
    return StreamEvent(
        type=StreamEventType.TOOL_RESULT,
        data={
            "tool_use_id": call_id,
            "name": name,
            "result": {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]},
        },
    )


def create_file_events(
    file_id: str = "draft-1", title: str = "第五章", file_type: str = "draft", *, call_id: str | None = None
) -> list[StreamEvent]:
    """create_file 成功（正文随后以 <file>…</file> 写出）。"""
    call_id = call_id or f"create-{file_id}"
    return [
        StreamEvent(
            type=StreamEventType.TOOL_USE,
            data={
                "id": call_id,
                "name": "create_file",
                "status": "complete",
                "input": {"title": title, "file_type": file_type},
            },
        ),
        _result(
            call_id,
            "create_file",
            {"status": "success", "data": {"id": file_id, "title": title, "file_type": file_type, "content": ""}},
        ),
    ]


def edit_file_events(
    call_id: str,
    text: str,
    *,
    file_id: str = "draft-1",
    title: str = "第五章",
    file_type: str = "draft",
    status: str = "success",
) -> list[StreamEvent]:
    """edit_file 往文件末尾追加 text；status="error" 时是一次失败的写入。"""
    payload: dict = (
        {"status": "success", "data": {"id": file_id, "title": title, "file_type": file_type}}
        if status == "success"
        else {"status": "error", "error": "database is locked"}
    )
    return [
        StreamEvent(
            type=StreamEventType.TOOL_USE,
            data={
                "id": call_id,
                "name": "edit_file",
                "status": "complete",
                "input": {"id": file_id, "edits": [{"op": "append", "text": text}]},
            },
        ),
        _result(call_id, "edit_file", payload),
    ]
