"""作者停止 / 断线的一轮怎样收尾：助手消息 id、终态落库、空白占位文件。

见 ``.agents/notes/implemented/architecture/2026-10-09-stop-output-definition-and-round-outcome.md``。

- :class:`RunOutcome` 由 api/agent.py 创建并传给 ``AgentService.process_stream``：
  路由层在取消运行之前写入 ``stop_kind``（``user_stopped`` / ``client_disconnected``），
  service 在取消路径补存部分历史时据此落库 ``stop_reason``，并且即使这一轮什么都
  没产出也写一条助手消息，刷新后作者才看得到「已停止」；落库后通过
  :meth:`RunOutcome.resolve_message_id` 把助手消息 id 交回路由层，停止路径的
  ``done`` 帧据此带上 ``assistant_message_id``。
- :func:`record_round_outcome` 在计费结算之后把结果（是否计入、写入的内容是否保存、
  写进了哪些文件、移除了哪些空白文件）写进这条助手消息的 ``message_metadata.stop_outcome``。
- :class:`RoundWrittenFiles` 和计费 tracker 一起观察这一轮发出的每一帧，记下写进了正文
  的文件（标题、能确定时的字数），停止 / 断线的终态据此告诉作者写了什么。
- :func:`remove_empty_placeholders` 只在这一轮被退还时调用：移除这一轮 ``create_file``
  新建、到现在仍然没有正文的文件。已有正文的、复用的、之前就存在的文件一律不动。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from agent.constants import coerce_bool
from agent.core.stream_billing import _parse_sse as parse_sse_frame
from utils.logger import get_logger, log_with_context
from utils.text_metrics import count_words

logger = get_logger(__name__)

STOP_KIND_USER_STOPPED = "user_stopped"
STOP_KIND_CLIENT_DISCONNECTED = "client_disconnected"
STOP_KINDS: frozenset[str] = frozenset({STOP_KIND_USER_STOPPED, STOP_KIND_CLIENT_DISCONNECTED})
# 写终态时可以被停止原因覆盖的 stop_reason：没有原因、或本来就是取消类的原因。
# 其余（例如可「继续」的 max_turns_exceeded、run_deadline_exceeded）说明这一轮在停止
# 之前已经按自己的方式结束并落库，保留原值，「继续」入口才不会丢。
_OVERWRITABLE_STOP_REASONS: frozenset[str] = frozenset({"", "cancelled", *STOP_KINDS})


@dataclass
class RunOutcome:
    """路由层与 process_stream 之间共享的这一轮收尾信息（同一事件循环内使用）。"""

    stop_kind: str | None = None
    # 作者停止时编辑器里还有没存下的字的文件（前端停止前的保存失败或超时，随 /stop 送来）：
    # 这一轮被退还时不当作空白占位文件移除，见 :meth:`removable`。
    keep_file_ids: set[str] = field(default_factory=set)
    # 取消时补存的正文包含控制标记尾部缓冲，可能比已发出的 file_content 更长。
    # None 表示该文件补存失败；消息 id 交回前由 service 填入保存回执。
    saved_file_word_counts: dict[str, int | None] = field(default_factory=dict)
    _message_id: asyncio.Future[str | None] | None = field(default=None, repr=False)

    def removable(self, candidates: list[dict[str, str]]) -> list[dict[str, str]]:
        """去掉作者编辑器里还有未保存文字的文件，剩下的才交给 remove_empty_placeholders。"""
        if not self.keep_file_ids:
            return candidates
        return [item for item in candidates if item.get("id") not in self.keep_file_ids]

    def _future(self) -> asyncio.Future[str | None]:
        if self._message_id is None:
            self._message_id = asyncio.get_running_loop().create_future()
        return self._message_id

    def resolve_message_id(self, message_id: str | None) -> None:
        """这一轮的助手消息落库了（或确定不会落库：None）。只有第一次调用生效。"""
        try:
            future = self._future()
        except RuntimeError:  # 没有运行中的事件循环
            return
        if not future.done():
            future.set_result(message_id if isinstance(message_id, str) and message_id else None)

    async def wait_message_id(self, timeout_s: float) -> str | None:
        """等这一轮的助手消息 id；超时或不会落库时返回 None。

        等待中的请求被取消（客户端断开）时照常抛出 CancelledError，交给调用方的断线路径。
        """
        try:
            return await asyncio.wait_for(asyncio.shield(self._future()), timeout=timeout_s)
        except TimeoutError:
            return None


# RoundWrittenFiles 关心的帧；其余帧（content、thinking、心跳……）不解析 JSON。
_WRITTEN_FILE_EVENTS: frozenset[str] = frozenset({"tool_result", "file_created", "file_content"})
_FOLDER_FILE_TYPE = "folder"


@dataclass
class _WrittenFile:
    title: str
    # 本轮写进这个文件的正文（create_file 带的正文 + 流式正文）；字数据此按编辑器口径计算。
    body: str = ""
    # 本轮还用 edit_file 改过它：只改了其中几处，整篇字数无从得知，不报字数。
    edited: bool = False


@dataclass
class RoundWrittenFiles:
    """这一轮写进了正文的文件，按第一次写入的先后排列。

    口径与 ``StreamBillingTracker.write_succeeded`` 一致（见 agent.core.stream_billing）：
    ``create_file`` 带非空正文新建、流式正文非空、``edit_file`` 真的改了文字才算；只建了
    空文件、读文件、失败的调用、文件夹都不算。另外两点：

    - 幂等复用（``reused_existing``）命中一个本来就有正文的文件时，中断后的残稿会被截断
      覆盖保护拒绝落库（见 agent/stream_adapter.py），这里不把它列成「已保存」。
    - ``parallel_execute`` 的子任务帧、``delete_file``、``update_project`` 不带可列给作者的
      文件，不在列表里；这类一轮仍有 ``saved_output``，前端照旧只说「已写入的内容已保存」。
    """

    _files: dict[str, _WrittenFile] = field(default_factory=dict)
    # create_file / file_created 里见过的标题：流式正文帧只带 file_id。
    _titles: dict[str, str] = field(default_factory=dict)
    # 复用时本来就有正文的文件：流式残稿不一定落库。
    _kept_bodies: set[str] = field(default_factory=set)

    def observe(self, frame: Any) -> None:
        if not isinstance(frame, str) or not frame.startswith("event:"):
            return
        event_type = frame[6 : frame.find("\n")].strip() if "\n" in frame else ""
        if event_type not in _WRITTEN_FILE_EVENTS:
            return
        _, data = parse_sse_frame(frame)
        payload = data if isinstance(data, dict) else {}
        if event_type == "file_created":
            self._remember_title(payload.get("file_id"), payload.get("title"))
        elif event_type == "file_content":
            self._observe_chunk(payload)
        else:
            self._observe_tool_result(payload)

    def files(
        self,
        *,
        final_word_counts: dict[str, int | None] | None = None,
        include_words: bool = True,
    ) -> list[dict[str, Any]]:
        """[{id, title, words?}]：字数只在本轮写下的就是整篇正文时给出。"""
        listed: list[dict[str, Any]] = []
        final_word_counts = final_word_counts or {}
        file_ids = dict.fromkeys([
            *self._files,
            *(fid for fid in final_word_counts if fid in self._titles and fid not in self._kept_bodies),
        ])
        for file_id in file_ids:
            if file_id in final_word_counts and final_word_counts[file_id] is None:
                continue
            item = self._files.get(file_id, _WrittenFile(title=self._titles.get(file_id, "")))
            entry: dict[str, Any] = {"id": file_id, "title": item.title or self._titles.get(file_id, "")}
            if include_words and not item.edited:
                entry["words"] = final_word_counts.get(file_id, count_words(item.body))
            listed.append(entry)
        return listed

    def _remember_title(self, file_id: Any, title: Any) -> None:
        if isinstance(file_id, str) and file_id and isinstance(title, str) and title:
            self._titles[file_id] = title
            if file_id in self._files and not self._files[file_id].title:
                self._files[file_id].title = title

    def _entry(self, file_id: str) -> _WrittenFile:
        if file_id not in self._files:
            self._files[file_id] = _WrittenFile(title=self._titles.get(file_id, ""))
        return self._files[file_id]

    def _observe_chunk(self, payload: dict[str, Any]) -> None:
        file_id = payload.get("file_id")
        chunk = str(payload.get("chunk") or "")
        if not isinstance(file_id, str) or not file_id or file_id in self._kept_bodies:
            return
        if file_id not in self._files and not chunk.strip():
            return
        self._entry(file_id).body += chunk

    def _observe_tool_result(self, payload: dict[str, Any]) -> None:
        if payload.get("status") != "success":
            return
        tool_name = payload.get("tool_name")
        data = payload.get("data")
        data = data if isinstance(data, dict) else {}
        file_id = data.get("id")
        if not isinstance(file_id, str) or not file_id:
            return
        if tool_name == "create_file":
            if data.get("file_type") == _FOLDER_FILE_TYPE:
                return
            self._remember_title(file_id, data.get("title"))
            content = str(data.get("content") or "")
            if coerce_bool(data.get("reused_existing")):
                if _reused_file_had_body(data, content):
                    self._kept_bodies.add(file_id)
                return
            if content.strip():
                self._entry(file_id).body += content
        elif tool_name == "edit_file":
            mutation_applied = data.get("mutation_applied")
            edits_applied = data.get("edits_applied")
            if mutation_applied is False or (
                not isinstance(mutation_applied, bool)
                and isinstance(edits_applied, int)
                and edits_applied <= 0
            ):
                return
            self._remember_title(file_id, data.get("title"))
            self._entry(file_id).edited = True


def _reused_file_had_body(data: dict[str, Any], content: str) -> bool:
    """复用到的文件原本是否已有正文——与 StreamAdapter 截断覆盖保护同一判据。

    生产里复用分支的 content 会被 mcp_tools._elide_reused_file_content 省略成 ""，
    只留 content_elided / original_content_length；StreamAdapter 也是按
    original_content_length（缺失时退回 content 长度）判定「原本非空」，不能只看 content。
    """
    try:
        original_length = int(data.get("original_content_length") or 0)
    except (TypeError, ValueError):
        original_length = 0
    return original_length > 0 or bool(content) or data.get("content_elided") is True


def remove_empty_placeholders(
    project_id: str,
    candidates: list[dict[str, str]],
) -> list[dict[str, str]]:
    """移除这一轮新建、到现在仍然没有正文的文件（软删除）；返回真正移除了的 {id, title}。

    调用方保证 ``candidates`` 只来自本轮 ``create_file`` 新建的空文件（见
    StreamBillingTracker.removable_placeholders）。这里在项目锁内逐个再查一次：
    文件仍在本项目、没被删、不是文件夹、正文为空、没有子节点，才移除。任何异常只记日志，
    不影响已经完成的退还。
    """
    if not candidates:
        return []
    from sqlmodel import select

    from config.datetime_utils import advance_timestamp, utcnow
    from database import create_session, is_postgres
    from models import File
    from services.file_tree_rules import lock_project_for_files

    removed: list[dict[str, str]] = []
    try:
        with create_session() as session:
            lock_project_for_files(session, project_id, exclusive=True)
            for candidate in candidates:
                file_id = candidate.get("id")
                if not file_id:
                    continue
                query = select(File).where(File.id == file_id)
                if is_postgres:
                    query = query.with_for_update(key_share=True)
                file = session.exec(query.execution_options(populate_existing=True)).first()
                if (
                    file is None
                    or file.project_id != project_id
                    or file.is_deleted
                    or file.file_type == "folder"
                    or (file.content or "").strip()
                ):
                    continue
                has_children = session.exec(
                    select(File.id).where(File.parent_id == file.id, File.is_deleted == False)  # noqa: E712
                ).first()
                if has_children is not None:
                    continue
                now = utcnow()
                file.is_deleted = True
                file.deleted_at = now
                file.updated_at = advance_timestamp(file.updated_at, now=now)
                session.add(file)
                removed.append({"id": file.id, "title": file.title or candidate.get("title", "")})
            session.commit()
    except Exception as exc:
        log_with_context(
            logger,
            30,  # WARNING
            "Failed to remove empty placeholder files after a refunded stop",
            project_id=project_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return []

    if removed:
        log_with_context(
            logger,
            20,  # INFO
            "Removed empty placeholder files after a refunded stop",
            project_id=project_id,
            removed_count=len(removed),
        )
    return removed


def build_stop_outcome(
    *,
    stop_kind: str,
    charged: bool,
    saved_output: bool,
    removed_files: list[dict[str, str]] | None = None,
    written_files: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """落库到 message_metadata.stop_outcome 的结构（前端 RoundEndNote 读取）。

    ``written_files``（:meth:`RoundWrittenFiles.files`）为空时不写这个键：旧消息和拿不到
    文件的写入（并行写章、删除）在前端照旧只显示「已写入的内容已保存」。
    """
    outcome: dict[str, Any] = {
        "reason": stop_kind,
        "charged": charged,
        "saved_output": saved_output,
    }
    titles = [item.get("title", "") for item in removed_files or [] if item.get("title")]
    if titles:
        outcome["removed_files"] = titles
    if written_files:
        outcome["written_files"] = written_files
    return outcome


def record_round_outcome(message_id: str, *, stop_kind: str, outcome: dict[str, Any]) -> bool:
    """把停止 / 断线的结果写进助手消息的 message_metadata；返回是否写成。"""
    from database import create_session
    from models import ChatMessage

    try:
        with create_session() as session:
            message = session.get(ChatMessage, message_id)
            if message is None or message.role != "assistant":
                return False
            try:
                metadata = json.loads(message.message_metadata) if message.message_metadata else {}
            except (TypeError, ValueError):
                metadata = {}
            if not isinstance(metadata, dict):
                metadata = {}
            existing_reason = metadata.get("stop_reason")
            if not isinstance(existing_reason, str) or existing_reason in _OVERWRITABLE_STOP_REASONS:
                metadata["stop_reason"] = stop_kind
            metadata["stop_outcome"] = outcome
            message.message_metadata = json.dumps(metadata, ensure_ascii=False)
            session.add(message)
            session.commit()
            return True
    except Exception as exc:
        log_with_context(
            logger,
            30,  # WARNING
            "Failed to record stopped round outcome",
            message_id=message_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return False


__all__ = [
    "STOP_KINDS",
    "STOP_KIND_CLIENT_DISCONNECTED",
    "STOP_KIND_USER_STOPPED",
    "RoundWrittenFiles",
    "RunOutcome",
    "build_stop_outcome",
    "record_round_outcome",
    "remove_empty_placeholders",
]
