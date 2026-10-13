"""Workflow streaming event types for the writing graph.

These events are the internal graph/runner contract consumed by the SSE
stream adapter. They are provider-neutral and must not depend on any LLM SDK.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StreamEventType(Enum):
    """Types of internal workflow streaming events."""

    TEXT = "text"
    THINKING = "thinking"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    MESSAGE_START = "message_start"
    MESSAGE_END = "message_end"
    ERROR = "error"
    AGENT_SELECTED = "agent_selected"
    HANDOFF = "handoff"
    ITERATION_EXHAUSTED = "iteration_exhausted"
    ROUTER_THINKING = "router_thinking"
    ROUTER_DECIDED = "router_decided"
    WORKFLOW_STOPPED = "workflow_stopped"
    WORKFLOW_COMPLETE = "workflow_complete"
    STEERING_RECEIVED = "steering_received"
    # 图 → StreamAdapter 的内部控制事件，不发给前端：data["action"] 为
    # CHAT_HOLD_BEGIN / CHAT_HOLD_DISCARD。begin 之后的对话文字先扣在适配器里，
    # discard 丢掉扣着的文字；其余情况在下一个 agent / 交接 / 收尾事件前原样放出。
    # 见 StreamAdapter._handle_chat_hold 与 writing_graph 的「被审稿取代的总结」。
    CHAT_HOLD = "chat_hold"


CHAT_HOLD_BEGIN = "begin"
CHAT_HOLD_DISCARD = "discard"


@dataclass
class StreamEvent:
    """Internal workflow streaming event."""

    type: StreamEventType
    data: dict[str, Any] = field(default_factory=dict)
