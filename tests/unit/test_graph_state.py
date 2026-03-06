"""图状态对象测试。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

from astrbot_orchestrator_v5.runtime.graph_state import OrchestratorGraphState
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


def test_orchestrator_graph_state_exposes_request_properties() -> None:
    """图状态应暴露请求级只读属性。"""

    request_context = RequestContext.from_legacy(
        user_request="帮我分析需求",
        provider_id="provider-a",
        context={"event": SimpleNamespace(role="admin"), "request_id": "req-123"},
    )

    state = OrchestratorGraphState(request_context=request_context)
    state.add_step("🧠 开始分析")

    assert state.request_id == "req-123"
    assert state.request_text == "帮我分析需求"
    assert state.provider_id == "provider-a"
    assert state.is_admin is True
    assert state.thinking_steps == ["🧠 开始分析"]
