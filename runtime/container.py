"""插件运行时容器。"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RuntimeContainer:
    """集中装配插件核心依赖，降低 `main.py` 初始化耦合。"""

    context: Any
    config: Any
    artifact_service: Any | None = None
    skill_loader: Any | None = None
    mcp_bridge: Any | None = None
    workflow_engine: Any | None = None
    dynamic_agent_manager: Any | None = None
    task_analyzer: Any | None = None
    capability_builder: Any | None = None
    agent_coordinator: Any | None = None
    meta_orchestrator: Any | None = None
    orchestrator: Any | None = None
    plugin_tool: Any | None = None
    skill_tool: Any | None = None
    mcp_tool: Any | None = None
    debugger: Any | None = None
    executor: Any | None = None

    @classmethod
    def build(cls, context: Any, config: Any) -> "RuntimeContainer":
        """构建完整运行时容器。"""

        container = cls(context=context, config=config)
        container._build_core_tools()
        container._build_workflow_components()
        container._build_subagent_components()
        container._build_orchestrator()
        return container

    def export_attributes(self) -> dict[str, Any]:
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

    def _get_plugin_projects_dir(self) -> str:
        """获取插件的项目存储目录。

        优先级:
            1. `ASTRBOT_DATA_DIR` 环境变量 (容器/自定义部署)
            2. `context.get_plugin_data_dir()` — AstrBot 新版注入的插件独立数据目录
            3. `<cwd>/data/agent_projects` — `astrbot init` 后的标准布局
            4. 最后才回退到 `/AstrBot/data/agent_projects` (官方 Docker 镜像约定)
        """
        import os
        from pathlib import Path

        candidates: list[str] = []

        env_root = os.environ.get("ASTRBOT_DATA_DIR") or os.environ.get("ASTRBOT_ROOT")
        if env_root:
            candidates.append(os.path.join(env_root, "agent_projects"))

        plugin_dir = None
        if hasattr(self.context, "get_plugin_data_dir"):
            try:
                plugin_dir = self.context.get_plugin_data_dir()
            except Exception as exc:
                logger.debug("获取插件数据目录失败，尝试回退: %s", exc)
        if plugin_dir:
            candidates.append(os.path.join(str(plugin_dir), "projects"))

        cwd_data = Path.cwd() / "data" / "agent_projects"
        candidates.append(str(cwd_data))

        candidates.append("/AstrBot/data/agent_projects")

        chosen: str | None = None
        for path in candidates:
            try:
                os.makedirs(path, exist_ok=True)
            except OSError as exc:
                logger.debug("无法在 %s 创建 agent_projects: %s", path, exc)
                continue
            chosen = path
            break

        if chosen is None:
            # 所有候选都不可写 —— 回退到自带的臨时目录,确保不再抛出
            import tempfile

            chosen = tempfile.mkdtemp(prefix="astrbot_orchestrator_projects_")
            logger.warning("所有标准位置都不可写，使用临时目录: %s", chosen)

        logger.info("插件项目目录: %s", chosen)
        return chosen

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
