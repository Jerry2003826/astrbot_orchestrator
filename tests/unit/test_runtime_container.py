"""RuntimeContainer 运行时装配测试。"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import TYPE_CHECKING, Any

import pytest

from astrbot_orchestrator_v5.runtime.container import RuntimeContainer

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


def make_module(name: str, **attributes: Any) -> ModuleType:
    """创建带指定属性的假模块。"""

    module = ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def build_recording_class(class_name: str) -> type[Any]:
    """创建记录构造参数的测试替身类。"""

    class RecordingClass:
        """记录最近一次实例化参数。"""

        instances: list[Any] = []

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            """保存初始化参数。"""

            self.args = args
            self.kwargs = kwargs
            self.__class__.instances.append(self)

    RecordingClass.__name__ = class_name
    return RecordingClass


class ExecutorWithStop:
    """带可观察 astop 行为的执行器替身。"""

    def __init__(self, error: Exception | None = None) -> None:
        """保存预设异常。"""

        self.error = error
        self.calls = 0

    async def astop(self) -> None:
        """记录停止调用并按需抛错。"""

        self.calls += 1
        if self.error is not None:
            raise self.error


def test_runtime_container_build_calls_steps_in_order(
    monkeypatch: "MonkeyPatch",
) -> None:
    """build 应按固定顺序装配各阶段组件。"""

    order: list[str] = []

    def fake_build_core_tools(self: RuntimeContainer) -> None:
        """记录 core 装配。"""

        order.append("core")

    def fake_build_workflow_components(self: RuntimeContainer) -> None:
        """记录 workflow 装配。"""

        order.append("workflow")

    def fake_build_subagent_components(self: RuntimeContainer) -> None:
        """记录 subagent 装配。"""

        order.append("subagent")

    def fake_build_orchestrator(self: RuntimeContainer) -> None:
        """记录 orchestrator 装配。"""

        order.append("orchestrator")

    monkeypatch.setattr(RuntimeContainer, "_build_core_tools", fake_build_core_tools)
    monkeypatch.setattr(
        RuntimeContainer, "_build_workflow_components", fake_build_workflow_components
    )
    monkeypatch.setattr(
        RuntimeContainer, "_build_subagent_components", fake_build_subagent_components
    )
    monkeypatch.setattr(RuntimeContainer, "_build_orchestrator", fake_build_orchestrator)

    container = RuntimeContainer.build(context="ctx", config={"enabled": True})

    assert container.context == "ctx"
    assert container.config == {"enabled": True}
    assert order == ["core", "workflow", "subagent", "orchestrator"]


def test_runtime_container_export_attributes_returns_all_runtime_components() -> None:
    """导出属性应完整暴露旧插件对象需要的组件映射。"""

    values = {
        "artifact_service": "artifact",
        "skill_loader": "skill-loader",
        "mcp_bridge": "mcp-bridge",
        "workflow_engine": "workflow",
        "dynamic_agent_manager": "dynamic-agent-manager",
        "task_analyzer": "task-analyzer",
        "capability_builder": "capability-builder",
        "agent_coordinator": "agent-coordinator",
        "meta_orchestrator": "meta-orchestrator",
        "orchestrator": "orchestrator",
        "plugin_tool": "plugin-tool",
        "skill_tool": "skill-tool",
        "mcp_tool": "mcp-tool",
        "debugger": "debugger",
        "executor": "executor",
    }
    container = RuntimeContainer(context="ctx", config="cfg", **values)

    assert container.export_attributes() == values


@pytest.mark.asyncio
async def test_runtime_container_astop_calls_executor_stop_when_available() -> None:
    """容器停止时应委托执行器的 astop。"""

    executor = ExecutorWithStop()
    container = RuntimeContainer(context="ctx", config="cfg", executor=executor)

    await container.astop()

    assert executor.calls == 1


@pytest.mark.asyncio
async def test_runtime_container_astop_ignores_missing_or_failing_executor_stop() -> None:
    """没有 astop 或 astop 抛错时，容器停止不应继续抛出异常。"""

    container_without_stop = RuntimeContainer(context="ctx", config="cfg", executor=object())
    container_with_error = RuntimeContainer(
        context="ctx",
        config="cfg",
        executor=ExecutorWithStop(error=RuntimeError("stop failed")),
    )

    await container_without_stop.astop()
    await container_with_error.astop()

    assert container_with_error.executor is not None
    assert container_with_error.executor.calls == 1


def test_runtime_container_build_core_tools_wires_effectful_components(
    monkeypatch: "MonkeyPatch",
) -> None:
    """基础工具装配应将上下文和配置注入各个副作用组件。"""

    ArtifactService = build_recording_class("ArtifactService")
    SelfDebugger = build_recording_class("SelfDebugger")
    ExecutionManager = build_recording_class("ExecutionManager")
    MCPConfiguratorTool = build_recording_class("MCPConfiguratorTool")
    PluginManagerTool = build_recording_class("PluginManagerTool")
    SkillCreatorTool = build_recording_class("SkillCreatorTool")
    MCPBridge = build_recording_class("MCPBridge")
    AstrBotSkillLoader = build_recording_class("AstrBotSkillLoader")

    monkeypatch.setitem(
        sys.modules,
        "astrbot_orchestrator_v5.artifacts",
        make_module("astrbot_orchestrator_v5.artifacts", ArtifactService=ArtifactService),
    )
    monkeypatch.setitem(
        sys.modules,
        "astrbot_orchestrator_v5.autonomous.debugger",
        make_module(
            "astrbot_orchestrator_v5.autonomous.debugger",
            SelfDebugger=SelfDebugger,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "astrbot_orchestrator_v5.autonomous.executor",
        make_module(
            "astrbot_orchestrator_v5.autonomous.executor",
            ExecutionManager=ExecutionManager,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "astrbot_orchestrator_v5.autonomous.mcp_configurator",
        make_module(
            "astrbot_orchestrator_v5.autonomous.mcp_configurator",
            MCPConfiguratorTool=MCPConfiguratorTool,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "astrbot_orchestrator_v5.autonomous.plugin_manager",
        make_module(
            "astrbot_orchestrator_v5.autonomous.plugin_manager",
            PluginManagerTool=PluginManagerTool,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "astrbot_orchestrator_v5.autonomous.skill_creator",
        make_module(
            "astrbot_orchestrator_v5.autonomous.skill_creator",
            SkillCreatorTool=SkillCreatorTool,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "astrbot_orchestrator_v5.orchestrator.mcp_bridge",
        make_module("astrbot_orchestrator_v5.orchestrator.mcp_bridge", MCPBridge=MCPBridge),
    )
    monkeypatch.setitem(
        sys.modules,
        "astrbot_orchestrator_v5.orchestrator.skill_loader",
        make_module(
            "astrbot_orchestrator_v5.orchestrator.skill_loader",
            AstrBotSkillLoader=AstrBotSkillLoader,
        ),
    )

    container = RuntimeContainer(context="ctx", config={"debug": True})
    container._build_core_tools()

    assert container.artifact_service is not None
    assert container.skill_loader is not None
    assert container.mcp_bridge is not None
    assert container.plugin_tool is not None
    assert container.skill_tool is not None
    assert container.mcp_tool is not None
    assert container.debugger is not None
    assert container.executor is not None
    # agent_projects 路径优先级见 RuntimeContainer._get_plugin_projects_dir:
    # ENV > context.get_plugin_data_dir > <cwd>/data/agent_projects > /AstrBot/data/agent_projects
    assert len(container.artifact_service.args) == 1
    assert container.artifact_service.args[0].endswith("agent_projects")
    assert container.skill_loader.args == ("ctx",)
    assert container.mcp_bridge.args == ("ctx",)
    assert container.plugin_tool.args == ("ctx",)
    assert container.skill_tool.args == ("ctx",)
    assert container.mcp_tool.args == ("ctx",)
    assert container.debugger.args == ("ctx",)
    assert container.executor.args == ("ctx", {"debug": True})


def test_runtime_container_build_workflow_components_uses_existing_dependencies(
    monkeypatch: "MonkeyPatch",
) -> None:
    """工作流装配应复用已创建的 Skill/MCP 组件。"""

    WorkflowEngine = build_recording_class("WorkflowEngine")
    monkeypatch.setitem(
        sys.modules,
        "astrbot_orchestrator_v5.workflow.engine",
        make_module("astrbot_orchestrator_v5.workflow.engine", WorkflowEngine=WorkflowEngine),
    )

    container = RuntimeContainer(
        context="ctx",
        config="cfg",
        skill_loader="skill-loader",
        mcp_bridge="mcp-bridge",
    )
    container._build_workflow_components()

    assert container.workflow_engine is not None
    assert container.workflow_engine.kwargs == {
        "context": "ctx",
        "skill_loader": "skill-loader",
        "mcp_bridge": "mcp-bridge",
    }


def test_runtime_container_build_subagent_components_wires_cross_dependencies(
    monkeypatch: "MonkeyPatch",
) -> None:
    """SubAgent 装配应按依赖关系串起分析器、能力构建器和协调器。"""

    AgentCoordinator = build_recording_class("AgentCoordinator")
    AgentCapabilityBuilder = build_recording_class("AgentCapabilityBuilder")
    DynamicAgentManager = build_recording_class("DynamicAgentManager")
    MetaOrchestrator = build_recording_class("MetaOrchestrator")
    TaskAnalyzer = build_recording_class("TaskAnalyzer")

    monkeypatch.setitem(
        sys.modules,
        "astrbot_orchestrator_v5.orchestrator.agent_coordinator",
        make_module(
            "astrbot_orchestrator_v5.orchestrator.agent_coordinator",
            AgentCoordinator=AgentCoordinator,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "astrbot_orchestrator_v5.orchestrator.capability_builder",
        make_module(
            "astrbot_orchestrator_v5.orchestrator.capability_builder",
            AgentCapabilityBuilder=AgentCapabilityBuilder,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "astrbot_orchestrator_v5.orchestrator.dynamic_agent_manager",
        make_module(
            "astrbot_orchestrator_v5.orchestrator.dynamic_agent_manager",
            DynamicAgentManager=DynamicAgentManager,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "astrbot_orchestrator_v5.orchestrator.meta_orchestrator",
        make_module(
            "astrbot_orchestrator_v5.orchestrator.meta_orchestrator",
            MetaOrchestrator=MetaOrchestrator,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "astrbot_orchestrator_v5.orchestrator.task_analyzer",
        make_module(
            "astrbot_orchestrator_v5.orchestrator.task_analyzer",
            TaskAnalyzer=TaskAnalyzer,
        ),
    )

    container = RuntimeContainer(
        context="ctx",
        config={"provider": "demo"},
        artifact_service="artifact",
        skill_tool="skill-tool",
        mcp_tool="mcp-tool",
        executor="executor",
    )
    container._build_subagent_components()

    assert container.dynamic_agent_manager is not None
    assert container.task_analyzer is not None
    assert container.capability_builder is not None
    assert container.agent_coordinator is not None
    assert container.meta_orchestrator is not None
    assert container.dynamic_agent_manager.args == ("ctx", {"provider": "demo"})
    assert container.task_analyzer.args == ("ctx", {"provider": "demo"})
    assert container.capability_builder.kwargs == {
        "context": "ctx",
        "skill_tool": "skill-tool",
        "mcp_tool": "mcp-tool",
        "executor": "executor",
    }
    assert container.agent_coordinator.kwargs == {
        "context": "ctx",
        "capability_builder": container.capability_builder,
        "config": {"provider": "demo"},
        "artifact_service": "artifact",
    }
    assert container.meta_orchestrator.kwargs == {
        "context": "ctx",
        "task_analyzer": container.task_analyzer,
        "agent_manager": container.dynamic_agent_manager,
        "coordinator": container.agent_coordinator,
        "config": {"provider": "demo"},
        "artifact_service": "artifact",
    }


def test_runtime_container_build_orchestrator_uses_built_dependencies(
    monkeypatch: "MonkeyPatch",
) -> None:
    """主编排器装配应复用容器中已准备好的各项依赖。"""

    DynamicOrchestrator = build_recording_class("DynamicOrchestrator")
    monkeypatch.setitem(
        sys.modules,
        "astrbot_orchestrator_v5.orchestrator.core",
        make_module(
            "astrbot_orchestrator_v5.orchestrator.core",
            DynamicOrchestrator=DynamicOrchestrator,
        ),
    )

    container = RuntimeContainer(
        context="ctx",
        config={"provider": "demo"},
        skill_loader="skill-loader",
        mcp_bridge="mcp-bridge",
        workflow_engine="workflow-engine",
        plugin_tool="plugin-tool",
        skill_tool="skill-tool",
        mcp_tool="mcp-tool",
        debugger="debugger",
        executor="executor",
        meta_orchestrator="meta-orchestrator",
    )
    container._build_orchestrator()

    assert container.orchestrator is not None
    assert container.orchestrator.kwargs == {
        "context": "ctx",
        "skill_loader": "skill-loader",
        "mcp_bridge": "mcp-bridge",
        "workflow_engine": "workflow-engine",
        "plugin_tool": "plugin-tool",
        "skill_tool": "skill-tool",
        "mcp_tool": "mcp-tool",
        "debugger": "debugger",
        "executor": "executor",
        "meta_orchestrator": "meta-orchestrator",
        "config": {"provider": "demo"},
    }
