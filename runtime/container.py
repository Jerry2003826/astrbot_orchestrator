"""插件运行时容器。"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, Any, TypedDict

if TYPE_CHECKING:
    from ..artifacts.service import ArtifactService
    from ..autonomous.debugger import SelfDebugger
    from ..autonomous.executor import ExecutionManager
    from ..autonomous.mcp_configurator import MCPConfiguratorTool
    from ..autonomous.plugin_manager import PluginManagerTool
    from ..autonomous.skill_creator import SkillCreatorTool
    from ..orchestrator.agent_coordinator import AgentCoordinator
    from ..orchestrator.capability_builder import AgentCapabilityBuilder
    from ..orchestrator.core import DynamicOrchestrator
    from ..orchestrator.dynamic_agent_manager import DynamicAgentManager
    from ..orchestrator.mcp_bridge import MCPBridge
    from ..orchestrator.meta_orchestrator import MetaOrchestrator
    from ..orchestrator.skill_loader import AstrBotSkillLoader
    from ..orchestrator.task_analyzer import TaskAnalyzer
    from ..workflow.engine import WorkflowEngine

logger = logging.getLogger(__name__)


class _ExportAttributes(TypedDict, total=False):
    """``export_attributes()`` 返回的组件映射结构。"""

    artifact_service: ArtifactService
    skill_loader: AstrBotSkillLoader
    mcp_bridge: MCPBridge
    workflow_engine: WorkflowEngine
    dynamic_agent_manager: DynamicAgentManager
    task_analyzer: TaskAnalyzer
    capability_builder: AgentCapabilityBuilder
    agent_coordinator: AgentCoordinator
    meta_orchestrator: MetaOrchestrator
    orchestrator: DynamicOrchestrator
    plugin_tool: PluginManagerTool
    skill_tool: SkillCreatorTool
    mcp_tool: MCPConfiguratorTool
    debugger: SelfDebugger
    executor: ExecutionManager


@dataclass(slots=True)
class RuntimeContainer:
    """集中装配插件核心依赖，降低 `main.py` 初始化耦合。"""

    context: Any
    config: Any
    artifact_service: ArtifactService | None = None
    skill_loader: AstrBotSkillLoader | None = None
    mcp_bridge: MCPBridge | None = None
    workflow_engine: WorkflowEngine | None = None
    dynamic_agent_manager: DynamicAgentManager | None = None
    task_analyzer: TaskAnalyzer | None = None
    capability_builder: AgentCapabilityBuilder | None = None
    agent_coordinator: AgentCoordinator | None = None
    meta_orchestrator: MetaOrchestrator | None = None
    orchestrator: DynamicOrchestrator | None = None
    plugin_tool: PluginManagerTool | None = None
    skill_tool: SkillCreatorTool | None = None
    mcp_tool: MCPConfiguratorTool | None = None
    debugger: SelfDebugger | None = None
    executor: ExecutionManager | None = None

    @classmethod
    def build(cls, context: Any, config: Any) -> "RuntimeContainer":
        """构建完整运行时容器。"""

        container = cls(context=context, config=config)
        container._build_core_tools()
        container._build_workflow_components()
        container._build_subagent_components()
        container._build_orchestrator()
        return container

    def export_attributes(self) -> _ExportAttributes:
        """导出给旧版插件对象绑定的组件映射。"""

        return {
            "artifact_service": self.artifact_service,
            "skill_loader": self.skill_loader,
            "mcp_bridge": self.mcp_bridge,
            "workflow_engine": self.workflow_engine,
            "dynamic_agent_manager": self.dynamic_agent_manager,
            "task_analyzer": self.task_analyzer,
            "capability_builder": self.capability_builder,
            "agent_coordinator": self.agent_coordinator,
            "meta_orchestrator": self.meta_orchestrator,
            "orchestrator": self.orchestrator,
            "plugin_tool": self.plugin_tool,
            "skill_tool": self.skill_tool,
            "mcp_tool": self.mcp_tool,
            "debugger": self.debugger,
            "executor": self.executor,
        }

    async def astop(self) -> None:
        """停止运行时中的可清理资源。"""

        stop_executor = getattr(self.executor, "astop", None)
        if stop_executor is None:
            return

        try:
            await stop_executor()
        except Exception as exc:
            logger.debug("停止执行器资源失败，忽略并继续: %s", exc)

    async def __aenter__(self) -> "RuntimeContainer":
        """异步上下文管理器入口。"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """异步上下文管理器出口 — 释放沙盒资源。"""
        await self.astop()

    def _get_plugin_projects_dir(self) -> str:
        """获取插件的项目存储目录。

        尝试 ``context.get_plugin_data_dir()`` 后再委托给统一的
        :func:`~shared.path_utils.resolve_projects_dir`，保持全局一致的
        回退链。
        """
        from pathlib import Path

        prefer: str | None = None

        if hasattr(self.context, "get_plugin_data_dir"):
            try:
                plugin_dir = self.context.get_plugin_data_dir()
                if plugin_dir:
                    prefer = str(Path(str(plugin_dir)) / "projects")
            except Exception as exc:
                logger.debug("获取插件数据目录失败，尝试回退: %s", exc)

        from ..shared import resolve_projects_dir

        return resolve_projects_dir(
            prefer_dir=prefer,
            plugin_root=Path(__file__).resolve().parent.parent,
        )

    def _build_core_tools(self) -> None:
        """构建与副作用相关的基础工具。"""

        from ..artifacts import ArtifactService
        from ..autonomous.debugger import SelfDebugger
        from ..autonomous.executor import ExecutionManager
        from ..autonomous.mcp_configurator import MCPConfiguratorTool
        from ..autonomous.plugin_manager import PluginManagerTool
        from ..autonomous.skill_creator import SkillCreatorTool
        from ..orchestrator.mcp_bridge import MCPBridge
        from ..orchestrator.skill_loader import AstrBotSkillLoader

        # 使用插件目录下的 projects 文件夹
        projects_dir = self._get_plugin_projects_dir()
        self.artifact_service = ArtifactService(projects_dir)
        self.skill_loader = AstrBotSkillLoader(self.context)
        self.mcp_bridge = MCPBridge(self.context)
        self.plugin_tool = PluginManagerTool(self.context)
        self.skill_tool = SkillCreatorTool(self.context)
        self.mcp_tool = MCPConfiguratorTool(self.context)
        self.debugger = SelfDebugger(self.context)
        self.executor = ExecutionManager(self.context, self.config)

    def _build_workflow_components(self) -> None:
        """构建工作流相关组件。"""

        from ..workflow.engine import WorkflowEngine

        self.workflow_engine = WorkflowEngine(
            context=self.context,
            skill_loader=self.skill_loader,
            mcp_bridge=self.mcp_bridge,
        )

    def _build_subagent_components(self) -> None:
        """构建动态 SubAgent 相关组件。"""

        from ..orchestrator.agent_coordinator import AgentCoordinator
        from ..orchestrator.capability_builder import AgentCapabilityBuilder
        from ..orchestrator.dynamic_agent_manager import DynamicAgentManager
        from ..orchestrator.meta_orchestrator import MetaOrchestrator
        from ..orchestrator.task_analyzer import TaskAnalyzer

        self.dynamic_agent_manager = DynamicAgentManager(self.context, self.config)
        self.task_analyzer = TaskAnalyzer(self.context, self.config)
        self.capability_builder = AgentCapabilityBuilder(
            context=self.context,
            skill_tool=self.skill_tool,
            mcp_tool=self.mcp_tool,
            executor=self.executor,
        )
        self.agent_coordinator = AgentCoordinator(
            context=self.context,
            capability_builder=self.capability_builder,
            config=self.config,
            artifact_service=self.artifact_service,
        )
        self.meta_orchestrator = MetaOrchestrator(
            context=self.context,
            task_analyzer=self.task_analyzer,
            agent_manager=self.dynamic_agent_manager,
            coordinator=self.agent_coordinator,
            config=self.config,
            artifact_service=self.artifact_service,
        )

    def _build_orchestrator(self) -> None:
        """构建主编排器。"""

        from ..orchestrator.core import DynamicOrchestrator

        self.orchestrator = DynamicOrchestrator(
            context=self.context,
            skill_loader=self.skill_loader,
            mcp_bridge=self.mcp_bridge,
            workflow_engine=self.workflow_engine,
            plugin_tool=self.plugin_tool,
            skill_tool=self.skill_tool,
            mcp_tool=self.mcp_tool,
            debugger=self.debugger,
            executor=self.executor,
            meta_orchestrator=self.meta_orchestrator,
            config=self.config,
        )
