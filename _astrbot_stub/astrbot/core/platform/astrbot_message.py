"""astrbot.core.platform.astrbot_message 测试桩。"""

from dataclasses import dataclass, field
import enum
from typing import Any


class MessageType(enum.Enum):
    GROUP_MESSAGE = "GroupMessage"
    FRIEND_MESSAGE = "FriendMessage"
    OTHER_MESSAGE = "OtherMessage"


@dataclass
class MessageMember:
    user_id: str
    nickname: str | None = None


@dataclass
class AstrBotMessage:
    type: MessageType | None = None
    self_id: str = ""
    session_id: str = ""
    message_id: str = ""
    group_id: str = ""
    sender: MessageMember | None = None
    message: list[Any] = field(default_factory=list)
    message_str: str = ""
    raw_message: Any = None
    timestamp: int = 0
