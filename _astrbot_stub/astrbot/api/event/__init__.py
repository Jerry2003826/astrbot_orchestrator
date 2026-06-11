"""astrbot.api.event 测试桩，对齐 v4.25.5 导出面。"""

from astrbot.core.message.message_event_result import (
    CommandResult,
    EventResultType,
    MessageChain,
    MessageEventResult,
    ResultContentType,
)
from astrbot.core.platform import AstrMessageEvent

__all__ = [
    "AstrMessageEvent",
    "CommandResult",
    "EventResultType",
    "MessageChain",
    "MessageEventResult",
    "ResultContentType",
]
