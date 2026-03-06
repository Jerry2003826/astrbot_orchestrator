"""请求级运行时上下文测试。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

from astrbot_orchestrator_v5.runtime.request_context import RequestContext

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture
    from _pytest.fixtures import FixtureRequest
    from _pytest.logging import LogCaptureFixture
    from _pytest.monkeypatch import MonkeyPatch
    from pytest_mock.plugin import MockerFixture

    _PYTEST_TYPE_IMPORTS = (
        CaptureFixture,
        FixtureRequest,
        LogCaptureFixture,
        MonkeyPatch,
        MockerFixture,
    )


class DummyEvent:
    """最小化事件替身。"""

    role = "admin"
    session_id = "session-1"
    unified_msg_origin = "umo-1"

    def get_sender_id(self) -> str:
        """返回模拟发送者 ID。"""

        return "user-1"


def test_request_context_from_event_builds_admin_policy() -> None:
    """事件上下文应自动生成管理员策略。"""

    request_context = RequestContext.from_event(
        user_request="创建一个 Skill",
        provider_id="provider-a",
        event=DummyEvent(),
        metadata={"entrypoint": "agent"},
    )

    assert request_context.user_id == "user-1"
    assert request_context.session_id == "session-1"
    assert request_context.unified_msg_origin == "umo-1"
    assert request_context.policy.allow_file_write is True
    assert request_context.metadata["entrypoint"] == "agent"


def test_request_context_round_trips_legacy_context() -> None:
    """新旧上下文之间应能稳定互转。"""

    legacy_context = {
        "user_id": "user-2",
        "session": "session-2",
        "umo": "umo-2",
        "is_admin": False,
        "request_id": "req-1",
        "trace_id": "trace-xyz",
    }

    request_context = RequestContext.from_legacy(
        user_request="只读问题",
        provider_id="provider-b",
        context=legacy_context,
    )

    exported = request_context.to_legacy_context()

    assert request_context.request_id == "req-1"
    assert request_context.policy.allow_code_execution is False
    assert exported["trace_id"] == "trace-xyz"
    assert exported["is_admin"] is False


def test_request_context_from_legacy_only_uses_event_role_for_admin() -> None:
    """旧上下文里的裸露 is_admin 标记不应再被直接信任。"""

    member_context = RequestContext.from_legacy(
        user_request="执行敏感操作",
        provider_id="provider-c",
        context={"is_admin": True, "event": SimpleNamespace(role="member")},
    )
    admin_context = RequestContext.from_legacy(
        user_request="执行敏感操作",
        provider_id="provider-c",
        context={"is_admin": False, "event": SimpleNamespace(role="admin")},
    )

    assert member_context.is_admin is False
    assert admin_context.is_admin is True
