"""
AstrBot 全自主智能体编排器

实现目标：所有操作都可以通过聊天完成
- 搜索插件市场，自己安装插件
- 自己写 Skill
- 自己编写/配置 MCP
- 出问题自己 debug
- 选择 local 或 sandbox 执行
"""

from collections.abc import AsyncIterator
import json
import logging
from typing import Any

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from .autonomous.debugger import SelfDebugger
from .autonomous.executor import ExecutionManager
from .autonomous.mcp_configurator import MCPConfiguratorTool
from .autonomous.plugin_manager import PluginManagerTool
from .autonomous.skill_creator import SkillCreatorTool
from .entrypoints import CommandHandlers
from .orchestrator.agent_coordinator import AgentCoordinator
from .orchestrator.capability_builder import AgentCapabilityBuilder
from .orchestrator.core import DynamicOrchestrator
from .orchestrator.dynamic_agent_manager import DynamicAgentManager
from .orchestrator.mcp_bridge import MCPBridge
from .orchestrator.meta_orchestrator import MetaOrchestrator
from .orchestrator.skill_loader import AstrBotSkillLoader
from .orchestrator.task_analyzer import TaskAnalyzer
from .runtime.container import RuntimeContainer
from .runtime.request_context import RequestContext
from .workflow.engine import WorkflowEngine

logger = logging.getLogger(__name__)


@register(
    name="astrbot_orchestrator",
    desc="全自主智能体编排器 - 通过聊天完成所有操作（CodeSandbox 增强版）",
    version="3.0.0",
    author="lijiarui",
)
class OrchestratorPlugin(Star):
    """
    AstrBot 全自主智能体编排器

    核心能力：
    - 🔍 搜索插件市场，自动安装插件
    - ✍️ 动态创建/编辑 Skill
    - 🔌 配置 MCP 服务器
    - 🐛 自我诊断和 Debug
    - 🖥️ 选择 local/sandbox 执行环境
    """

    def __init__(
        self,
        context: Context,
        config: AstrBotConfig | None = None,
    ) -> None:
        """初始化插件入口及其运行时占位属性。"""

        super().__init__(context)

        self.config = config or AstrBotConfig()

        # 核心组件
        self.orchestrator: DynamicOrchestrator = None
        self.meta_orchestrator: MetaOrchestrator = None
        self.skill_loader: AstrBotSkillLoader = None
        self.mcp_bridge: MCPBridge = None
        self.workflow_engine: WorkflowEngine = None
        self.dynamic_agent_manager: DynamicAgentManager = None
        self.task_analyzer: TaskAnalyzer = None
        self.agent_coordinator: AgentCoordinator = None
        self.capability_builder: AgentCapabilityBuilder = None

        # 自主能力组件
        self.plugin_tool: PluginManagerTool = None
        self.skill_tool: SkillCreatorTool = None
        self.mcp_tool: MCPConfiguratorTool = None
        self.debugger: SelfDebugger = None
        self.executor: ExecutionManager = None
        self.runtime: RuntimeContainer | None = None
        self.command_handlers: CommandHandlers | None = None

        self._initialized = False

    def _bind_runtime_components(self, runtime: RuntimeContainer) -> None:
        """将运行时容器中的组件显式绑定到插件实例，保留类型可追踪性。"""

        attrs = runtime.export_attributes()

        self.orchestrator = attrs.get("orchestrator")
        self.meta_orchestrator = attrs.get("meta_orchestrator")
        self.skill_loader = attrs.get("skill_loader")
        self.mcp_bridge = attrs.get("mcp_bridge")
        self.workflow_engine = attrs.get("workflow_engine")
        self.dynamic_agent_manager = attrs.get("dynamic_agent_manager")
        self.task_analyzer = attrs.get("task_analyzer")
        self.agent_coordinator = attrs.get("agent_coordinator")
        self.capability_builder = attrs.get("capability_builder")
        self.plugin_tool = attrs.get("plugin_tool")
        self.skill_tool = attrs.get("skill_tool")
        self.mcp_tool = attrs.get("mcp_tool")
        self.debugger = attrs.get("debugger")
        self.executor = attrs.get("executor")

    def _build_request_context(
        self,
        event: AstrMessageEvent,
        user_request: str,
        provider_id: str,
        entrypoint: str,
    ) -> RequestContext:
        """为一次命令调用构建请求级运行时上下文。"""

        return RequestContext.from_event(
            user_request=user_request,
            provider_id=provider_id,
            event=event,
            metadata={"entrypoint": entrypoint},
        )

    def _get_command_handlers(self) -> CommandHandlers:
        """返回已初始化的命令处理器。"""

        if self.command_handlers is None:
            raise RuntimeError("命令处理器未初始化")
        return self.command_handlers

    async def initialize(self) -> None:
        """插件初始化"""
        if self._initialized:
            return

        logger.info("初始化全自主智能体编排器...")
        self.runtime = RuntimeContainer.build(self.context, self.config)
        self._bind_runtime_components(self.runtime)
        self.command_handlers = CommandHandlers(
            context=self.context,
            runtime=self.runtime,
            build_request_context=self._build_request_context,
        )

        self._initialized = True

        # 调试日志：检查配置
        logger.info("全自主智能体编排器初始化完成")
        logger.info(
            "配置检查: enable_dynamic_agents=%s, force_subagents=%s",
            self.config.get("enable_dynamic_agents"),
            self.config.get("force_subagents_for_complex_tasks"),
        )


    def _config_bool(self, key: str, default: bool) -> bool:
        """读取布尔配置，兼容 AstrBotConfig 缺省值。"""

        value = self.config.get(key)
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "是", "开启"}
        return bool(value)

    def _config_str(self, key: str, default: str) -> str:
        """读取字符串配置，兼容 AstrBotConfig 缺省值。"""

        value = self.config.get(key)
        if value is None or value == "":
            return default
        return str(value).strip()

    def _should_skip_natural_language_router(self, event: AstrMessageEvent) -> bool:
        """判断是否跳过自然语言路由的前置安全边界。"""

        if not self._config_bool("enable_natural_language_control", True):
            return True

        text = (event.message_str or "").strip()
        if not text or text.startswith("/"):
            return True

        scope = self._config_str("natural_language_router_scope", "direct").lower()
        if scope in {"all", "all_messages", "all-messages", "所有", "全量"}:
            return False

        return not (
            event.is_private_chat()
            or bool(getattr(event, "is_at_or_wake_command", False))
            or bool(getattr(event, "is_wake", False))
        )

    async def _get_router_provider_id(
        self,
        handlers: CommandHandlers,
        event: AstrMessageEvent,
    ) -> str:
        """解析自然语言路由使用的模型提供商。"""

        configured_provider = self._config_str("llm_provider", "")
        if configured_provider:
            return configured_provider
        return await handlers._get_provider_id(event)

    async def _route_natural_language_agent_request(
        self,
        event: AstrMessageEvent,
        provider_id: str,
    ) -> str | None:
        """让 LLM 判断普通消息是否应该交给自主编排器。"""

        if self._should_skip_natural_language_router(event):
            return None

        message = (event.message_str or "").strip()
        is_direct = (
            event.is_private_chat()
            or bool(getattr(event, "is_at_or_wake_command", False))
            or bool(getattr(event, "is_wake", False))
        )
        prompt = f"""你是 AstrBot 的消息路由器，需要判断一条普通聊天消息是否应该交给“自主智能体编排器”。

自主智能体编排器适合处理：
- 用户要求安装、搜索、配置、卸载、更新插件
- 用户要求配置 MCP、创建/编辑 Skill、运行代码或命令、调试日志/报错
- 用户要求创建文件、写网页/程序/脚本、搭建项目、生成可落地的技术产物
- 用户要求多步骤排查、操作服务器、检查系统状态、修复问题

不要交给编排器的情况：
- 普通闲聊、情绪陪伴、角色扮演、日常问答
- 只需要模型直接回答的知识性问题
- 模糊、不像是在请求执行任务的句子
- 群聊中没有明显对机器人发出的任务请求

上下文：
- 私聊或已 @/唤醒机器人: {is_direct}
- 用户身份: {getattr(event, "role", "")}
- 消息文本: {message}

只输出一个 JSON 对象，不要解释，不要 markdown。字段要求：
- route_to_agent: boolean，只有需要交给编排器时为 true
- rewritten_request: string，route_to_agent=true 时把用户真实任务改写成简洁明确的中文；否则为空字符串
- reason: string，一句话说明路由原因
"""

        try:
            response = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
                system_prompt="你是严格的 JSON 路由分类器，只输出 JSON。",
            )
            decision = self._parse_router_decision(response.completion_text)
        except Exception as exc:
            logger.warning("自然语言 LLM 路由失败，放行给默认聊天流程: %s", exc, exc_info=True)
            return None

        if not decision.get("route_to_agent"):
            logger.debug("自然语言 LLM 路由未命中: %s", decision.get("reason"))
            return None

        rewritten = str(decision.get("rewritten_request") or "").strip()
        if not rewritten:
            rewritten = message
        logger.info("自然语言 LLM 路由命中: %s", str(decision.get("reason") or "")[:120])
        return rewritten

    @staticmethod
    def _parse_router_decision(text: str) -> dict[str, Any]:
        """解析路由模型返回的 JSON。"""

        raw = (text or "").strip()
        if raw.startswith("```json"):
            raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
        elif raw.startswith("```"):
            raw = raw.split("```", 1)[1].split("```", 1)[0].strip()
        if "{" in raw and "}" in raw:
            raw = raw[raw.find("{") : raw.rfind("}") + 1]
        data = json.loads(raw)
        route_value = data.get("route_to_agent", False)
        if isinstance(route_value, str):
            route_value = route_value.strip().lower() in {"1", "true", "yes", "y", "是", "需要", "route"}
        return {
            "route_to_agent": bool(route_value),
            "rewritten_request": str(data.get("rewritten_request") or ""),
            "reason": str(data.get("reason") or ""),
        }

    @filter.regex(r"(?s).+")
    async def handle_natural_language_agent(
        self,
        event: AstrMessageEvent,
    ) -> AsyncIterator[Any]:
        """
        自然语言控制入口。

        捕获普通消息后交给 LLM 路由器判断；只有模型判定为技术执行任务时才复用 `/agent`。
        """

        await self.initialize()
        handlers = self._get_command_handlers()
        provider_id = await self._get_router_provider_id(handlers, event)
        user_request = await self._route_natural_language_agent_request(event, provider_id)
        if user_request is None:
            return

        original_message = event.message_str
        event.message_str = user_request
        event.should_call_llm(False)
        try:
            async for result in handlers.handle_agent(event):
                yield result
        finally:
            event.message_str = original_message

    @filter.command("agent")
    async def handle_agent(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        """
        全自主 Agent - 可以执行任何操作

        用法: /agent <任务描述>

        示例:
        - /agent 帮我搜索有什么好用的翻译插件
        - /agent 帮我写一个查询天气的 Skill
        - /agent 帮我配置一个联网搜索的 MCP
        - /agent 为什么刚才的代码报错了，帮我修复
        - /agent 用沙盒运行这段 Python 代码
        """
        await self.initialize()
        handlers = self._get_command_handlers()
        async for result in handlers.handle_agent(event):
            yield result

    @filter.command("plugin")
    async def handle_plugin(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        """
        插件管理

        用法:
        - /plugin search <关键词>   搜索插件市场
        - /plugin install <url>     安装插件（管理员，自动使用 GitHub 加速）
        - /plugin list              列出已安装插件
        - /plugin remove <名称>     卸载插件（管理员）
        - /plugin update <名称>     更新插件（管理员）
        - /plugin proxy             查看 GitHub 加速设置
        """
        await self.initialize()
        handlers = self._get_command_handlers()
        async for result in handlers.handle_plugin(event):
            yield result

    @filter.command("skill")
    async def handle_skill(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        """
        Skill 管理

        用法:
        - /skill list                列出所有 Skill（管理员）
        - /skill create <名称>       创建新 Skill（交互式）
        - /skill edit <名称>         编辑 Skill
        - /skill delete <名称>       删除 Skill（管理员）
        - /skill read <名称>         查看 Skill 内容（管理员）
        """
        await self.initialize()
        handlers = self._get_command_handlers()
        async for result in handlers.handle_skill(event):
            yield result

    @filter.command("mcp")
    async def handle_mcp(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        """
        MCP 配置管理

        用法:
        - /mcp list                  列出所有 MCP 服务（管理员）
        - /mcp add <名称> <url>      添加 MCP 服务（管理员）
        - /mcp remove <名称>         移除 MCP 服务（管理员）
        - /mcp test <名称>           测试 MCP 连接（管理员）
        - /mcp tools <名称>          查看 MCP 工具（管理员）
        """
        await self.initialize()
        handlers = self._get_command_handlers()
        async for result in handlers.handle_mcp(event):
            yield result

    @filter.command("exec")
    async def handle_exec(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        """
        执行代码/命令（使用 AstrBot 全局沙盒配置）

        用法:
        - /exec <命令>             使用全局配置执行
        - /exec local <命令>       强制本地执行
        - /exec sandbox <命令>     强制沙盒执行
        - /exec python <代码>      执行 Python 代码
        - /exec config             查看当前执行环境配置
        """
        await self.initialize()
        handlers = self._get_command_handlers()
        async for result in handlers.handle_exec(event):
            yield result

    @filter.command("debug")
    async def handle_debug(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        """
        自我诊断和 Debug（管理员）

        用法:
        - /debug status        查看系统状态
        - /debug logs          查看最近错误日志
        - /debug analyze <问题描述>  分析问题
        """
        await self.initialize()
        handlers = self._get_command_handlers()
        async for result in handlers.handle_debug(event):
            yield result

    @filter.command("sandbox")
    async def handle_sandbox(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        """
        CodeSandbox 沙盒管理（类似 CodeBox API）

        用法:
        - /sandbox status              沙盒健康状态
        - /sandbox exec <代码>         执行 Python 代码
        - /sandbox bash <命令>         执行 Shell 命令
        - /sandbox files [路径]        列出沙盒文件
        - /sandbox upload <路径> <内容> 上传文件
        - /sandbox download <路径>     下载文件
        - /sandbox install <包名>      安装 Python 包
        - /sandbox packages            列出已安装包
        - /sandbox variables           查看会话变量
        - /sandbox restart             重启沙盒
        - /sandbox url <url> <路径>    从 URL 下载文件到沙盒
        """
        await self.initialize()
        handlers = self._get_command_handlers()
        async for result in handlers.handle_sandbox(event):
            yield result

    async def terminate(self) -> None:
        """插件停用时清理沙盒资源"""
        if self.runtime is not None:
            await self.runtime.astop()
        logger.info("全自主智能体编排器已停用")
