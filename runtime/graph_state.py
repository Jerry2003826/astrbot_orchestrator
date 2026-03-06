"""面向编排器的显式状态对象。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .request_context import RequestContext


@dataclass(slots=True)
class OrchestratorGraphState:
    """描述一次编排请求在图式执行中的共享状态。"""

    request_context: RequestContext
    thinking_steps: list[str] = field(default_factory=list)
    intent: dict[str, Any] = field(default_factory=dict)
    plan: list[Any] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    used_subagents: bool = False

    @property
    def request_id(self) -> str:
        """返回请求 ID。"""

        return self.request_context.request_id

    @property
    def request_text(self) -> str:
        """返回用户请求文本。"""

        return self.request_context.request_text

    @property
    def provider_id(self) -> str:
        """返回当前绑定的 provider_id。"""

        return self.request_context.provider_id

    @property
    def event(self) -> Any | None:
        """返回当前请求关联的事件对象。"""

        return self.request_context.event

    @property
    def is_admin(self) -> bool:
        """返回当前请求是否具备管理员权限。"""

        return self.request_context.is_admin

    def add_step(self, step: str) -> None:
        """记录一条执行轨迹。"""

        self.thinking_steps.append(step)
