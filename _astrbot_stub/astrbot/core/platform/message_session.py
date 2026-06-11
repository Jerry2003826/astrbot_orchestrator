"""astrbot.core.platform.message_session 测试桩。"""

from dataclasses import dataclass

from .astrbot_message import MessageType


@dataclass
class MessageSession:
    platform_name: str
    message_type: MessageType
    session_id: str

    def __str__(self) -> str:
        return f"{self.platform_name}:{self.message_type.value}:{self.session_id}"

    @staticmethod
    def from_str(session_str: str) -> "MessageSession":
        platform_name, message_type, session_id = session_str.split(":", 2)
        return MessageSession(
            platform_name=platform_name,
            message_type=MessageType(message_type),
            session_id=session_id,
        )


MessageSesion = MessageSession
