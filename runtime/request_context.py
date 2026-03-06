"""请求级运行时上下文原语。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    """描述一次请求允许执行的副作用边界。"""

    is_admin: bool = False
    allow_side_effects: bool = False
    allow_file_write: bool = False
    allow_code_execution: bool = False
    allow_skill_mutation: bool = False
    allow_mcp_config: bool = False
    allow_plugin_management: bool = False

    @classmethod
    def from_admin(cls, is_admin: bool) -> "ExecutionPolicy":
        """根据管理员身份构建默认执行策略。"""

        return cls(
            is_admin=is_admin,
            allow_side_effects=is_admin,
            allow_file_write=is_admin,
            allow_code_execution=is_admin,
            allow_skill_mutation=is_admin,
            allow_mcp_config=is_admin,
            allow_plugin_management=is_admin,
        )


@dataclass(frozen=True, slots=True)
class RequestContext:
    """封装一次用户请求的运行时状态。"""

    request_text: str
    provider_id: str
    request_id: str = field(default_factory=lambda: uuid4().hex)
    user_id: str = ""
    session_id: str = ""
    unified_msg_origin: str = ""
    event: Any | None = None
    policy: ExecutionPolicy = field(default_factory=ExecutionPolicy)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_admin(self) -> bool:
        """返回当前请求是否具备管理员权限。"""

        return self.policy.is_admin

    @classmethod
    def from_event(
        cls,
        user_request: str,
        provider_id: str,
        event: Any,
        metadata: Mapping[str, Any] | None = None,
    ) -> "RequestContext":
        """从 AstrBot 事件对象构建请求上下文。"""

        is_admin = getattr(event, "role", "") == "admin"
        sender_id = ""
        if hasattr(event, "get_sender_id"):
            sender_id = str(event.get_sender_id())

        return cls(
            request_text=user_request,
            provider_id=provider_id,
            user_id=sender_id,
            session_id=str(getattr(event, "session_id", "") or ""),
            unified_msg_origin=str(getattr(event, "unified_msg_origin", "") or ""),
            event=event,
            policy=ExecutionPolicy.from_admin(is_admin),
            metadata=dict(metadata or {}),
        )

    @classmethod
    def from_legacy(
        cls,
        user_request: str,
        provider_id: str,
        context: Mapping[str, Any] | None = None,
    ) -> "RequestContext":
        """从旧版字典上下文兼容构建请求上下文。"""

        legacy_context = dict(context or {})
        event = legacy_context.get("event")
        reserved_keys = {"user_id", "session", "umo", "is_admin", "event", "request_id"}
        metadata = {key: value for key, value in legacy_context.items() if key not in reserved_keys}
        event_is_admin = getattr(event, "role", "") == "admin" if event is not None else False

        return cls(
            request_text=user_request,
            provider_id=provider_id,
            request_id=str(legacy_context.get("request_id") or uuid4().hex),
            user_id=str(legacy_context.get("user_id") or ""),
            session_id=str(legacy_context.get("session") or ""),
            unified_msg_origin=str(legacy_context.get("umo") or ""),
            event=event,
            policy=ExecutionPolicy.from_admin(event_is_admin),
            metadata=metadata,
        )

    def with_provider(self, provider_id: str) -> "RequestContext":
        """返回绑定新 provider 的上下文副本。"""

        return replace(self, provider_id=provider_id)

    def to_legacy_context(self) -> dict[str, Any]:
        """导出为旧版 orchestrator 兼容字典。"""

        legacy = {
            "user_id": self.user_id,
            "session": self.session_id,
            "umo": self.unified_msg_origin,
            "is_admin": self.is_admin,
            "event": self.event,
            "request_id": self.request_id,
        }
        legacy.update(self.metadata)
        return legacy
