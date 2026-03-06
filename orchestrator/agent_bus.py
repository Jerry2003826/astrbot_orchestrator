"""
Agent 间通信总线
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional


@dataclass
class AgentMessage:
    """表示一条可共享给其他 Agent 的消息。"""

    sender: str
    content: str
    target: Optional[str]
    created_at: datetime


class AgentMessageBus:
    """简单的内存消息总线，用于 SubAgent 之间共享信息"""

    def __init__(self) -> None:
        """初始化消息存储。"""

        self._messages: List[AgentMessage] = []

    def publish(self, sender: str, content: str, target: Optional[str] = None) -> None:
        """发布一条消息到总线。"""

        self._messages.append(
            AgentMessage(
                sender=sender,
                content=content,
                target=target,
                created_at=datetime.now(timezone.utc),
            )
        )

    def get_messages(self, target: Optional[str] = None, limit: int = 20) -> List[AgentMessage]:
        """获取最近的共享消息。"""

        if target:
            messages = [m for m in self._messages if m.target in (None, target)]
        else:
            messages = list(self._messages)
        return messages[-limit:]

    def format_messages(self, target: Optional[str] = None, limit: int = 10) -> str:
        """将共享消息格式化为上下文字符串。"""

        messages = self.get_messages(target, limit)
        if not messages:
            return ""
        lines = ["共享上下文消息："]
        for msg in messages:
            timestamp = msg.created_at.strftime("%H:%M:%S")
            target_info = f" -> {msg.target}" if msg.target else ""
            lines.append(f"[{timestamp}] {msg.sender}{target_info}: {msg.content}")
        return "\n".join(lines)
