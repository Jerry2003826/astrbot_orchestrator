"""astrbot.core.star.filter.event_message_type 测试桩。"""

import enum
from typing import Any

from . import HandlerFilter


class EventMessageTypeEnum(enum.Enum):
    GROUP_MESSAGE = enum.auto()
    PRIVATE_MESSAGE = enum.auto()
    OTHER_MESSAGE = enum.auto()


class EventMessageType(enum.Flag):
    GROUP_MESSAGE = enum.auto()
    PRIVATE_MESSAGE = enum.auto()
    OTHER_MESSAGE = enum.auto()
    ALL = GROUP_MESSAGE | PRIVATE_MESSAGE | OTHER_MESSAGE


class EventMessageTypeFilter(HandlerFilter):
    def __init__(self, event_message_type: EventMessageType) -> None:
        self.event_message_type = event_message_type

    def filter(self, event: Any, cfg: Any) -> bool:
        return True
