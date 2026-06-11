"""astrbot.core.platform 测试桩。"""

from .astr_message_event import AstrMessageEvent
from .astrbot_message import AstrBotMessage, MessageMember, MessageType
from .platform_metadata import PlatformMetadata

__all__ = [
    "AstrBotMessage",
    "AstrMessageEvent",
    "MessageMember",
    "MessageType",
    "PlatformMetadata",
]
