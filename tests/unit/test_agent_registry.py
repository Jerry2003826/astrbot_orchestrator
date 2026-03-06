"""AgentRegistry 单元测试。"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from astrbot_orchestrator_v5.orchestrator.agent_registry import AgentRecord, AgentRegistry

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


def make_record(agent_id: str, name: str, created_at: datetime) -> AgentRecord:
    """构造测试用 AgentRecord。"""

    return AgentRecord(
        agent_id=agent_id,
        name=name,
        role="code",
        status="running",
        created_at=created_at,
        spec=SimpleNamespace(name=name),
        metadata={"source": "test"},
    )


def test_agent_registry_summary_returns_empty_message_when_no_agents() -> None:
    """空注册表应返回无动态代理提示。"""

    registry = AgentRegistry()

    assert registry.list() == []
    assert registry.get("missing") is None
    assert registry.remove("missing") is None
    assert registry.summary() == "暂无动态 SubAgent"


def test_agent_registry_register_update_list_remove_and_summary() -> None:
    """注册表应支持增删改查与状态摘要。"""

    registry = AgentRegistry()
    first = make_record("agent-1", "code_agent", datetime(2024, 1, 1, 9, 30, 0))
    second = make_record("agent-2", "review_agent", datetime(2024, 1, 1, 9, 31, 0))

    registry.register(first)
    registry.register(second)
    registry.update_status("agent-1", "completed")
    registry.update_status("missing", "failed")

    listed = registry.list()
    removed = registry.remove("agent-2")
    summary = registry.summary()

    assert listed == [first, second]
    assert registry.get("agent-1") is first
    assert first.status == "completed"
    assert removed is second
    assert registry.get("agent-2") is None
    assert "当前动态 SubAgent：" in summary
    assert "- code_agent (code) [completed] @ 09:30:00" in summary
