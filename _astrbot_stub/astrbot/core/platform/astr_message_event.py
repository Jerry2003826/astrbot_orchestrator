"""astrbot.core.platform.astr_message_event 测试桩。

对齐 v4.25.5 AstrMessageEvent 的构造签名与本插件用到的方法子集。
关键语义：`message_str` 是完整的消息纯文本（含指令名本身），
唤醒阶段只会去除唤醒前缀，不会去除指令名。
"""

from typing import Any

from astrbot.core.message.message_event_result import (
    MessageChain,
    MessageEventResult,
)

from .astrbot_message import AstrBotMessage, MessageType
from .message_session import MessageSession
from .platform_metadata import PlatformMetadata


class AstrMessageEvent:
    def __init__(
        self,
        message_str: str,
        message_obj: AstrBotMessage,
        platform_meta: PlatformMetadata,
        session_id: str,
    ) -> None:
        self.message_str = message_str
        self.message_obj = message_obj
        self.platform_meta = platform_meta
        self.role = "member"
        self.is_wake = False
        self.is_at_or_wake_command = False
        self.call_llm = True
        self.session = MessageSession(
            platform_name=platform_meta.name,
            message_type=message_obj.type or MessageType.FRIEND_MESSAGE,
            session_id=session_id,
        )
        self._extras: dict[str, Any] = {}
        self._result: MessageEventResult | None = None
        self._force_stopped = False
        self.sent_messages: list[MessageChain] = []
        """桩专用：记录 send() 发送的消息链，便于测试断言。"""

    # ------------------------------------------------------------------
    # 会话与发送者
    # ------------------------------------------------------------------
    @property
    def unified_msg_origin(self) -> str:
        return str(self.session)

    @property
    def session_id(self) -> str:
        return self.session.session_id

    def get_platform_name(self) -> str:
        return self.platform_meta.name

    def get_platform_id(self) -> str:
        return self.platform_meta.id

    def get_self_id(self) -> str:
        return getattr(self.message_obj, "self_id", "")

    def get_sender_id(self) -> str:
        sender = getattr(self.message_obj, "sender", None)
        if sender and isinstance(getattr(sender, "user_id", None), str):
            return sender.user_id
        return ""

    def get_sender_name(self) -> str:
        sender = getattr(self.message_obj, "sender", None)
        nickname = getattr(sender, "nickname", None) if sender else None
        return str(nickname or "")

    def get_group_id(self) -> str:
        return getattr(self.message_obj, "group_id", "")

    def is_private_chat(self) -> bool:
        return (self.message_obj.type or MessageType.FRIEND_MESSAGE) == (MessageType.FRIEND_MESSAGE)

    def get_message_str(self) -> str:
        return self.message_str

    def get_message_outline(self) -> str:
        return self.message_str

    # ------------------------------------------------------------------
    # 权限与唤醒
    # ------------------------------------------------------------------
    def is_wake_up(self) -> bool:
        return self.is_wake

    def is_admin(self) -> bool:
        return self.role == "admin"

    def should_call_llm(self, call_llm: bool) -> None:
        self.call_llm = call_llm

    # ------------------------------------------------------------------
    # 额外信息
    # ------------------------------------------------------------------
    def set_extra(self, key: str, value: Any) -> None:
        self._extras[key] = value

    def get_extra(self, key: str | None = None, default: Any = None) -> Any:
        if key is None:
            return self._extras
        return self._extras.get(key, default)

    def clear_extra(self) -> None:
        self._extras.clear()

    # ------------------------------------------------------------------
    # 结果与事件传播
    # ------------------------------------------------------------------
    def make_result(self) -> MessageEventResult:
        return MessageEventResult()

    def plain_result(self, text: str) -> MessageEventResult:
        return MessageEventResult().message(text)

    def image_result(self, url_or_path: str) -> MessageEventResult:
        result = MessageEventResult()
        if url_or_path.startswith("http"):
            return result.url_image(url_or_path)
        return result.file_image(url_or_path)

    def chain_result(self, chain: list[Any]) -> MessageEventResult:
        result = MessageEventResult()
        result.chain = chain
        return result

    def set_result(self, result: MessageEventResult | str) -> None:
        if isinstance(result, str):
            result = MessageEventResult().message(result)
        self._result = result

    def get_result(self) -> MessageEventResult | None:
        return self._result

    def clear_result(self) -> None:
        self._result = None

    def stop_event(self) -> None:
        self._force_stopped = True
        if self._result is None:
            self.set_result(MessageEventResult().stop_event())
        else:
            self._result.stop_event()

    def continue_event(self) -> None:
        self._force_stopped = False
        if self._result is not None:
            self._result.continue_event()

    def is_stopped(self) -> bool:
        if self._force_stopped:
            return True
        if self._result is None:
            return False
        return self._result.is_stopped()

    # ------------------------------------------------------------------
    # 平台适配
    # ------------------------------------------------------------------
    async def send(self, message: MessageChain) -> None:
        self.sent_messages.append(message)

    async def send_streaming(self, generator: Any, use_fallback: bool = False) -> None:
        raise NotImplementedError("stub")
