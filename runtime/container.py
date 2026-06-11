"""插件运行时容器。

集中装配能力实现（autonomous/*、workflow、artifacts）、FunctionTool 集合
与官方化的 AgentRunner / DynamicAgentManager。自研规划/协调/元编排组件
已随 tool_loop_agent 迁移删除。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from astrbot.api import logger

if TYPE_CHECKING:
    from ..artifacts.service import ArtifactService
    from ..autonomous.debugger import SelfDebugger
    from ..autonomous.executor import ExecutionManager
    from ..autonomous.mcp_configurator import MCPConfiguratorTool
    from ..autonomous.plugin_manager import PluginManagerTool
    from ..autonomous.skill_creator import SkillCreatorTool
    from ..orchestrator.agent_runner import AgentRunner
    from ..orchestrator.dynamic_agent_manager import DynamicAgentManager
    from ..orchestrator.mcp_bridge import MCPBridge
    from ..orchestrator.skill_loader import AstrBotSkillLoader
    from ..workflow.engine import WorkflowEngine


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
    plugin_tool: PluginManagerTool | None = None
    skill_tool: SkillCreatorTool | None = None
    mcp_tool: MCPConfiguratorTool | None = None
    debugger: SelfDebugger | None = None
    executor: ExecutionManager | None = None
    agent_runner: AgentRunner | None = None
    tools: list[Any] = field(default_factory=list)

    @classmethod
    def build(cls, context: Any, config: Any) -> "RuntimeContainer":
        """构建完整运行时容器。"""

        container = cls(context=context, config=config)
        container._build_capabilities()
        container._build_tools()
        container._build_agent_layer()
        return container

    async def astop(self) -> None:
        """停止运行时中的可清理资源（执行器与各能力持有的 HTTP 会话）。"""

        for component in (self.executor, self.plugin_tool, self.mcp_tool):
            stop = getattr(component, "astop", None) or getattr(component, "aclose", None)
            if stop is None:
                continue
            try:
                await stop()
            except Exception as exc:
                logger.debug("停止运行时资源失败，忽略并继续: %s", exc)

    async def __aenter__(self) -> "RuntimeContainer":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.astop()

    def _build_capabilities(self) -> None:
        """构建能力实现层（副作用能力 + 工作流）。"""

        from ..artifacts import ArtifactService
        from ..autonomous.debugger import SelfDebugger
        from ..autonomous.executor import ExecutionManager
        from ..autonomous.mcp_configurator import MCPConfiguratorTool
        from ..autonomous.plugin_manager import PluginManagerTool
        from ..autonomous.skill_creator import SkillCreatorTool
        from ..orchestrator.mcp_bridge import MCPBridge
        from ..orchestrator.skill_loader import AstrBotSkillLoader
        from ..shared import resolve_projects_dir
        from ..workflow.engine import WorkflowEngine

        self.artifact_service = ArtifactService(resolve_projects_dir())
        self.skill_loader = AstrBotSkillLoader(self.context)
        self.mcp_bridge = MCPBridge(self.context)
        self.plugin_tool = PluginManagerTool(self.context)
        self.skill_tool = SkillCreatorTool(self.context)
        self.mcp_tool = MCPConfiguratorTool(self.context)
        self.debugger = SelfDebugger(self.context)
        self.executor = ExecutionManager(self.context, self.config)
        self.workflow_engine = WorkflowEngine(
            context=self.context,
            skill_loader=self.skill_loader,
            mcp_bridge=self.mcp_bridge,
        )

    def _build_tools(self) -> None:
        """按配置开关构建 FunctionTool 集合。"""

        from ..tools import build_orchestrator_tools

        self.tools = build_orchestrator_tools(self, self.config)

    def _build_agent_layer(self) -> None:
        """构建官方化的 Agent 执行层与子代理适配器。"""

        from ..orchestrator.agent_runner import AgentRunner
        from ..orchestrator.dynamic_agent_manager import DynamicAgentManager

        self.dynamic_agent_manager = DynamicAgentManager(self.context, self.config)
        self.agent_runner = AgentRunner(
            context=self.context,
            config=self.config,
            tools=self.tools,
            artifact_service=self.artifact_service,
        )
