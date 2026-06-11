"""RuntimeContainer 装配测试。"""

from __future__ import annotations

import pytest

from astrbot_orchestrator_v5.runtime.container import RuntimeContainer
from tests.conftest import FakeContext


def test_build_assembles_all_components(fake_context: FakeContext) -> None:
    container = RuntimeContainer.build(fake_context, {})

    assert container.artifact_service is not None
    assert container.skill_loader is not None
    assert container.mcp_bridge is not None
    assert container.workflow_engine is not None
    assert container.plugin_tool is not None
    assert container.skill_tool is not None
    assert container.mcp_tool is not None
    assert container.debugger is not None
    assert container.executor is not None
    assert container.dynamic_agent_manager is not None
    assert container.agent_runner is not None

    # AgentRunner 复用容器内的工具与产物服务
    assert container.agent_runner.tools is not None
    assert container.agent_runner.artifact_service is container.artifact_service


def test_build_tools_follow_config_gates(fake_context: FakeContext) -> None:
    container = RuntimeContainer.build(
        fake_context,
        {
            "enable_plugin_management": False,
            "enable_code_execution": False,
        },
    )

    names = {tool.name for tool in container.tools}
    assert "plugin_search" not in names
    assert "sandbox_exec_python" not in names
    assert "skill_list" in names
    assert "mcp_list" in names


def test_legacy_components_removed(fake_context: FakeContext) -> None:
    container = RuntimeContainer.build(fake_context, {})

    for legacy in (
        "orchestrator",
        "meta_orchestrator",
        "task_analyzer",
        "agent_coordinator",
        "capability_builder",
    ):
        assert not hasattr(container, legacy), f"遗留组件未删除: {legacy}"


@pytest.mark.asyncio
async def test_astop_delegates_to_executor(fake_context: FakeContext) -> None:
    container = RuntimeContainer.build(fake_context, {})
    stopped: list[bool] = []

    async def fake_astop() -> None:
        stopped.append(True)

    container.executor.astop = fake_astop  # type: ignore[method-assign]
    await container.astop()

    assert stopped == [True]


@pytest.mark.asyncio
async def test_async_context_manager_stops_runtime(fake_context: FakeContext) -> None:
    stopped: list[bool] = []

    async with RuntimeContainer.build(fake_context, {}) as container:

        async def fake_astop() -> None:
            stopped.append(True)

        container.executor.astop = fake_astop  # type: ignore[method-assign]

    assert stopped == [True]
