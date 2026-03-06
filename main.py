"""
AstrBot 全自主智能体编排器

实现目标：所有操作都可以通过聊天完成
- 搜索插件市场，自己安装插件
- 自己写 Skill
- 自己编写/配置 MCP
- 出问题自己 debug
- 选择 local 或 sandbox 执行
"""

import json
import logging
import asyncio
import traceback
from typing import Any, Dict, List, Optional

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain
from astrbot.api import AstrBotConfig

# 使用相对导入
from .orchestrator.core import DynamicOrchestrator
from .orchestrator.skill_loader import AstrBotSkillLoader
from .orchestrator.mcp_bridge import MCPBridge
from .orchestrator.meta_orchestrator import MetaOrchestrator
from .orchestrator.dynamic_agent_manager import DynamicAgentManager
from .orchestrator.task_analyzer import TaskAnalyzer
from .orchestrator.agent_coordinator import AgentCoordinator
from .orchestrator.capability_builder import AgentCapabilityBuilder
from .workflow.engine import WorkflowEngine

# 自主能力模块
from .autonomous.plugin_manager import PluginManagerTool
from .autonomous.skill_creator import SkillCreatorTool
from .autonomous.mcp_configurator import MCPConfiguratorTool
from .autonomous.debugger import SelfDebugger
from .autonomous.executor import ExecutionManager

logger = logging.getLogger(__name__)


@register(
    name="astrbot_orchestrator",
    desc="全自主智能体编排器 - 通过聊天完成所有操作（CodeSandbox 增强版）",
    version="3.0.0",
    author="Your Name"
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
    
    def __init__(self, context: Context, config: AstrBotConfig = None):
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
        
        self._initialized = False
    
    async def initialize(self):
        """插件初始化"""
        if self._initialized:
            return
        
        logger.info("初始化全自主智能体编排器...")
        
        # 基础组件
        self.skill_loader = AstrBotSkillLoader(self.context)
        self.mcp_bridge = MCPBridge(self.context)
        
        # 自主能力组件
        self.plugin_tool = PluginManagerTool(self.context)
        self.skill_tool = SkillCreatorTool(self.context)
        self.mcp_tool = MCPConfiguratorTool(self.context)
        self.debugger = SelfDebugger(self.context)
        self.executor = ExecutionManager(self.context, self.config)
        
        # 工作流引擎
        self.workflow_engine = WorkflowEngine(
            context=self.context,
            skill_loader=self.skill_loader,
            mcp_bridge=self.mcp_bridge
        )

        # 动态 SubAgent 组件
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
        )
        self.meta_orchestrator = MetaOrchestrator(
            context=self.context,
            task_analyzer=self.task_analyzer,
            agent_manager=self.dynamic_agent_manager,
            coordinator=self.agent_coordinator,
            config=self.config,
        )
        
        # 核心编排器
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
            config=self.config
        )
        
        self._initialized = True
        
        # 调试日志：检查配置
        logger.info("全自主智能体编排器初始化完成")
        logger.info("配置检查: enable_dynamic_agents=%s, force_subagents=%s",
                    self.config.get("enable_dynamic_agents"),
                    self.config.get("force_subagents_for_complex_tasks"))
    
    @filter.command("agent")
    async def handle_agent(self, event: AstrMessageEvent):
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
        
        user_request = event.message_str.strip()
        if not user_request:
            yield event.plain_result(self._get_help_message())
            return

        if user_request.lower() in ["status", "agents", "subagents", "子代理", "状态"]:
            if self.meta_orchestrator:
                yield event.plain_result(self.meta_orchestrator.status())
            else:
                yield event.plain_result("❌ SubAgent 编排器未初始化")
            return

        if user_request.lower() in ["templates", "template", "subagent templates", "子代理模板"]:
            if self.dynamic_agent_manager:
                templates = self.dynamic_agent_manager.get_template_config()
                yield event.plain_result(
                    "📦 SubAgent 默认模板配置:\n\n```json\n"
                    + json.dumps(templates, ensure_ascii=False, indent=2)
                    + "\n```\n\n"
                    "💡 可通过插件配置项 `subagent_template_overrides` 覆盖模板"
                )
            else:
                yield event.plain_result("❌ SubAgent 模板未初始化")
            return
        
        yield event.plain_result("🤖 正在分析任务，请稍候...")
        
        try:
            umo = event.unified_msg_origin
            provider_id = await self.context.get_current_chat_provider_id(umo=umo)
            
            # 判断用户是否是管理员
            is_admin = event.role == "admin"
            
            result = await self.orchestrator.process_autonomous(
                user_request=user_request,
                provider_id=provider_id,
                context={
                    "user_id": str(event.get_sender_id()),
                    "umo": umo,
                    "session": event.session_id,
                    "is_admin": is_admin,
                    "event": event
                }
            )
            
            yield event.plain_result(result["answer"])
            
        except Exception as e:
            logger.error(f"Agent 执行失败: {e}", exc_info=True)
            
            # 尝试自我 debug
            try:
                debug_result = await self.debugger.analyze_error(
                    error=e,
                    traceback_info=traceback.format_exc(),
                    context={"request": user_request}
                )
                yield event.plain_result(
                    f"❌ 执行出错: {str(e)}\n\n"
                    f"🔍 自动分析:\n{debug_result}"
                )
            except Exception:
                yield event.plain_result(f"❌ 执行出错: {str(e)}")
    
    @filter.command("plugin")
    async def handle_plugin(self, event: AstrMessageEvent):
        """
        插件管理
        
        用法:
        - /plugin search <关键词>   搜索插件市场
        - /plugin install <url>     安装插件（自动使用 GitHub 加速）
        - /plugin list              列出已安装插件
        - /plugin remove <名称>     卸载插件
        - /plugin update <名称>     更新插件
        - /plugin proxy             查看 GitHub 加速设置
        """
        await self.initialize()
        
        args = event.message_str.strip().split(maxsplit=1)
        
        if not args:
            yield event.plain_result(
                "📦 插件管理\n\n"
                "用法:\n"
                "  /plugin search <关键词>  - 搜索插件\n"
                "  /plugin install <url>    - 安装插件\n"
                "  /plugin list             - 已安装列表\n"
                "  /plugin remove <名称>    - 卸载插件\n"
                "  /plugin update <名称>    - 更新插件\n"
                "  /plugin proxy            - GitHub 加速设置\n\n"
                "💡 安装时自动使用 AstrBot 配置的 GitHub 加速"
            )
            return
        
        action = args[0].lower()
        param = args[1] if len(args) > 1 else ""
        
        if action == "search":
            yield event.plain_result(f"🔍 正在搜索插件: {param}...")
            result = await self.plugin_tool.search_plugins(param)
            yield event.plain_result(result)
        
        elif action == "install":
            if event.role != "admin":
                yield event.plain_result("❌ 只有管理员可以安装插件")
                return
            yield event.plain_result(f"📥 正在安装插件: {param}...\n💡 使用 AstrBot 配置的 GitHub 加速")
            result = await self.plugin_tool.install_plugin(param)
            yield event.plain_result(result)
        
        elif action == "list":
            result = await self.plugin_tool.list_plugins()
            yield event.plain_result(result)
        
        elif action == "remove":
            if event.role != "admin":
                yield event.plain_result("❌ 只有管理员可以卸载插件")
                return
            result = await self.plugin_tool.remove_plugin(param)
            yield event.plain_result(result)
        
        elif action == "update":
            if event.role != "admin":
                yield event.plain_result("❌ 只有管理员可以更新插件")
                return
            yield event.plain_result(f"🔄 正在更新插件: {param}...")
            result = await self.plugin_tool.update_plugin(param)
            yield event.plain_result(result)
        
        elif action == "proxy":
            result = self.plugin_tool.get_available_proxies()
            yield event.plain_result(result)
        
        else:
            yield event.plain_result("无效命令，请使用 /plugin 查看帮助")
    
    @filter.command("skill")
    async def handle_skill(self, event: AstrMessageEvent):
        """
        Skill 管理
        
        用法:
        - /skill list                列出所有 Skill
        - /skill create <名称>       创建新 Skill（交互式）
        - /skill edit <名称>         编辑 Skill
        - /skill delete <名称>       删除 Skill
        - /skill read <名称>         查看 Skill 内容
        """
        await self.initialize()
        
        args = event.message_str.strip().split(maxsplit=1)
        
        if not args:
            yield event.plain_result(
                "📚 Skill 管理\n\n"
                "用法:\n"
                "  /skill list           - 列出所有 Skill\n"
                "  /skill create <名称>  - 创建新 Skill\n"
                "  /skill edit <名称>    - 编辑 Skill\n"
                "  /skill delete <名称>  - 删除 Skill\n"
                "  /skill read <名称>    - 查看内容"
            )
            return
        
        action = args[0].lower()
        param = args[1] if len(args) > 1 else ""
        
        if action == "list":
            result = self.skill_tool.list_skills()
            yield event.plain_result(result)
        
        elif action == "create":
            if not param:
                yield event.plain_result("请提供 Skill 名称")
                return
            yield event.plain_result(
                f"📝 准备创建 Skill: {param}\n\n"
                f"请描述这个 Skill 的功能，我会帮你自动生成 SKILL.md 文件。\n"
                f"例如：这是一个查询天气的 Skill，支持查询全国主要城市的天气..."
            )
            # 进入交互模式（实际实现需要状态管理）
        
        elif action == "read":
            result = self.skill_tool.read_skill(param)
            yield event.plain_result(result)
        
        elif action == "delete":
            if event.role != "admin":
                yield event.plain_result("❌ 只有管理员可以删除 Skill")
                return
            result = self.skill_tool.delete_skill(param)
            yield event.plain_result(result)
        
        else:
            yield event.plain_result("无效命令，请使用 /skill 查看帮助")
    
    @filter.command("mcp")
    async def handle_mcp(self, event: AstrMessageEvent):
        """
        MCP 配置管理
        
        用法:
        - /mcp list                  列出所有 MCP 服务
        - /mcp add <名称> <url>      添加 MCP 服务
        - /mcp remove <名称>         移除 MCP 服务
        - /mcp test <名称>           测试 MCP 连接
        - /mcp tools <名称>          查看 MCP 工具
        """
        await self.initialize()
        
        args = event.message_str.strip().split()
        
        if not args:
            yield event.plain_result(
                "🔌 MCP 配置管理\n\n"
                "用法:\n"
                "  /mcp list            - 列出所有 MCP 服务\n"
                "  /mcp add <名称> <url> - 添加 MCP 服务\n"
                "  /mcp remove <名称>   - 移除 MCP 服务\n"
                "  /mcp test <名称>     - 测试连接\n"
                "  /mcp tools <名称>    - 查看工具列表"
            )
            return
        
        action = args[0].lower()
        
        if action == "list":
            result = self.mcp_tool.list_servers()
            yield event.plain_result(result)
        
        elif action == "add" and len(args) >= 3:
            if event.role != "admin":
                yield event.plain_result("❌ 只有管理员可以添加 MCP")
                return
            name, url = args[1], args[2]
            result = await self.mcp_tool.add_server(name, url)
            yield event.plain_result(result)
        
        elif action == "remove" and len(args) >= 2:
            if event.role != "admin":
                yield event.plain_result("❌ 只有管理员可以移除 MCP")
                return
            result = await self.mcp_tool.remove_server(args[1])
            yield event.plain_result(result)
        
        elif action == "test" and len(args) >= 2:
            result = await self.mcp_tool.test_server(args[1])
            yield event.plain_result(result)
        
        elif action == "tools" and len(args) >= 2:
            result = self.mcp_tool.list_tools(args[1])
            yield event.plain_result(result)
        
        else:
            yield event.plain_result("无效命令，请使用 /mcp 查看帮助")
    
    @filter.command("exec")
    async def handle_exec(self, event: AstrMessageEvent):
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
        
        if event.role != "admin":
            yield event.plain_result("❌ 只有管理员可以执行代码")
            return
        
        args = event.message_str.strip().split(maxsplit=1)
        
        if not args:
            yield event.plain_result(
                "🖥️ **代码执行**\n\n"
                "执行环境由 AstrBot 全局配置决定（配置文件 → 使用电脑能力）\n\n"
                "**用法:**\n"
                "  `/exec <命令>`          - 使用全局配置执行\n"
                "  `/exec local <命令>`    - 强制本地执行\n"
                "  `/exec sandbox <命令>`  - 强制沙盒执行\n"
                "  `/exec python <代码>`   - 执行 Python\n"
                "  `/exec config`          - 查看当前配置"
            )
            return
        
        mode = args[0].lower()
        code = args[1] if len(args) > 1 else ""
        
        # 查看当前配置
        if mode == "config":
            result = self.executor.get_current_mode_info()
            yield event.plain_result(result)
            return
        
        # 如果第一个参数不是已知的模式，则作为命令使用全局配置执行
        if mode not in ["local", "sandbox", "python"]:
            # 整个消息作为命令
            code = event.message_str.strip()
            result = await self.executor.execute(code, event)
            yield event.plain_result(result)
            return
        
        if not code:
            yield event.plain_result("请提供要执行的代码或命令")
            return
        
        if mode == "local":
            result = await self.executor.execute_local(code, event)
            yield event.plain_result(result)
        
        elif mode == "sandbox":
            result = await self.executor.execute_sandbox(code, event)
            yield event.plain_result(result)
        
        elif mode == "python":
            result = await self.executor.execute_python(code, event)
            yield event.plain_result(result)
    
    @filter.command("debug")
    async def handle_debug(self, event: AstrMessageEvent):
        """
        自我诊断和 Debug
        
        用法:
        - /debug status        查看系统状态
        - /debug logs          查看最近错误日志
        - /debug analyze <问题描述>  分析问题
        """
        await self.initialize()
        
        args = event.message_str.strip().split(maxsplit=1)
        action = args[0].lower() if args else "status"
        param = args[1] if len(args) > 1 else ""
        
        if action == "status":
            result = await self.debugger.get_system_status()
            yield event.plain_result(result)
        
        elif action == "logs":
            result = self.debugger.get_recent_errors()
            yield event.plain_result(result)
        
        elif action == "analyze":
            umo = event.unified_msg_origin
            provider_id = await self.context.get_current_chat_provider_id(umo=umo)
            result = await self.debugger.analyze_problem(param, provider_id)
            yield event.plain_result(result)
        
        else:
            yield event.plain_result(
                "🐛 Debug 工具\n\n"
                "用法:\n"
                "  /debug status    - 系统状态\n"
                "  /debug logs      - 错误日志\n"
                "  /debug analyze <问题> - 分析问题"
            )
    
    @filter.command("sandbox")
    async def handle_sandbox(self, event: AstrMessageEvent):
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
        
        if event.role != "admin":
            yield event.plain_result("❌ 只有管理员可以操作沙盒")
            return
        
        args = event.message_str.strip().split(maxsplit=1)
        
        if not args:
            yield event.plain_result(self._get_sandbox_help())
            return
        
        action = args[0].lower()
        param = args[1] if len(args) > 1 else ""
        
        if action == "status":
            result = await self.executor.healthcheck(event)
            yield event.plain_result(result)
        
        elif action == "exec":
            if not param:
                yield event.plain_result("请提供要执行的 Python 代码")
                return
            yield event.plain_result("⏳ 正在执行...")
            exec_result = await self.executor.exec_code(param, event, kernel="ipython")
            yield event.plain_result(self._format_exec_result(exec_result))
        
        elif action == "bash":
            if not param:
                yield event.plain_result("请提供要执行的 Shell 命令")
                return
            yield event.plain_result("⏳ 正在执行...")
            exec_result = await self.executor.exec_code(param, event, kernel="bash")
            yield event.plain_result(self._format_exec_result(exec_result))
        
        elif action == "stream":
            if not param:
                yield event.plain_result("请提供要执行的代码")
                return
            yield event.plain_result("⏳ 流式执行中...")
            chunks = await self.executor.exec_code(param, event, kernel="ipython", stream=True)
            output_parts = []
            async for chunk in chunks:
                output_parts.append(str(chunk))
            yield event.plain_result("".join(output_parts) if output_parts else "(无输出)")
        
        elif action == "files":
            path = param or "."
            result = await self.executor.list_files(path, event)
            yield event.plain_result(result)
        
        elif action == "upload":
            parts = param.split(maxsplit=1)
            if len(parts) < 2:
                yield event.plain_result("用法: `/sandbox upload <文件路径> <内容>`")
                return
            file_path, content = parts[0], parts[1]
            result = await self.executor.write_file(file_path, content, event)
            yield event.plain_result(result)
        
        elif action == "download":
            if not param:
                yield event.plain_result("请提供文件路径")
                return
            result = await self.executor.read_file(param, event)
            yield event.plain_result(result)
        
        elif action == "install":
            if not param:
                yield event.plain_result("请提供要安装的包名")
                return
            yield event.plain_result(f"📦 正在安装: {param}...")
            packages = param.split()
            result = await self.executor.install_packages(packages, event)
            yield event.plain_result(f"📦 {result}")
        
        elif action == "packages":
            try:
                packages = await self.executor.list_packages(event)
                if packages:
                    pkg_list = "\n".join([f"  • {p}" for p in packages[:50]])
                    total = len(packages)
                    yield event.plain_result(
                        f"📦 **已安装的 Python 包** ({total} 个)\n\n{pkg_list}"
                        + (f"\n  ... 还有 {total - 50} 个" if total > 50 else "")
                    )
                else:
                    yield event.plain_result("📦 暂无已安装的包")
            except Exception as e:
                yield event.plain_result(f"❌ 获取包列表失败: {str(e)}")
        
        elif action == "variables":
            try:
                variables = await self.executor.show_variables(event)
                if variables:
                    var_list = "\n".join([f"  • `{k}` = {v}" for k, v in variables.items()])
                    yield event.plain_result(f"📊 **会话变量**\n\n{var_list}")
                else:
                    yield event.plain_result("📊 当前会话无变量")
            except Exception as e:
                yield event.plain_result(f"❌ 获取变量失败: {str(e)}")
        
        elif action == "restart":
            result = await self.executor.restart_sandbox(event)
            yield event.plain_result(result)
        
        elif action == "url":
            parts = param.split(maxsplit=1)
            if len(parts) < 2:
                yield event.plain_result("用法: `/sandbox url <URL> <保存路径>`")
                return
            url, file_path = parts[0], parts[1]
            yield event.plain_result(f"⬇️ 正在下载: {url}...")
            try:
                sf = await self.executor.download_from_url(url, file_path, event)
                yield event.plain_result(f"✅ 文件已下载: `{sf.path}` ({sf.size_human})")
            except Exception as e:
                yield event.plain_result(f"❌ 下载失败: {str(e)}")
        
        else:
            yield event.plain_result(self._get_sandbox_help())
    
    def _format_exec_result(self, result) -> str:
        """格式化 ExecResult 为消息文本"""
        from .sandbox.types import ExecResult
        if not isinstance(result, ExecResult):
            return str(result)
        
        lines = []
        if result.text:
            output = result.text[:3000] + "..." if len(result.text) > 3000 else result.text
            lines.append(f"**输出:**\n```\n{output}\n```")
        
        if result.errors:
            errors = result.errors[:1500] + "..." if len(result.errors) > 1500 else result.errors
            lines.append(f"**错误:**\n```\n{errors}\n```")
        
        if result.images:
            lines.append(f"📷 生成了 {len(result.images)} 张图片")
        
        status = "✅ 成功" if result.success else f"❌ 失败 (exit_code={result.exit_code})"
        lines.append(f"\n{status} | 内核: {result.kernel}")
        
        return "\n".join(lines) if lines else "(无输出)"
    
    def _get_sandbox_help(self) -> str:
        return """🐳 **CodeSandbox 沙盒管理**

类似 CodeBox API 的统一代码执行环境。

**执行代码:**
• `/sandbox exec <Python代码>` - 执行 Python
• `/sandbox bash <Shell命令>` - 执行 Shell
• `/sandbox stream <代码>` - 流式执行

**文件管理:**
• `/sandbox files [路径]` - 列出文件
• `/sandbox upload <路径> <内容>` - 上传文件
• `/sandbox download <路径>` - 下载文件
• `/sandbox url <URL> <路径>` - 从 URL 下载

**包管理:**
• `/sandbox install <包名>` - 安装 Python 包
• `/sandbox packages` - 列出已安装包

**会话管理:**
• `/sandbox variables` - 查看会话变量
• `/sandbox status` - 沙盒状态
• `/sandbox restart` - 重启沙盒
"""

    def _get_help_message(self) -> str:
        return """🤖 **全自主智能体编排器 v3.0** (CodeSandbox 增强版)

我可以帮你完成几乎任何操作，只需要用自然语言描述即可。

**核心能力：**
• 🔍 搜索并安装插件
• ✍️ 创建和编辑 Skill
• 🔌 配置 MCP 服务
• 🐛 自动诊断和修复问题
• 🐳 CodeSandbox 代码执行（类似 CodeBox API）

**常用命令：**
• `/agent <任务>` - 全自主执行任务
• `/agent status` - 查看动态 SubAgent 状态
• `/plugin` - 插件管理
• `/skill` - Skill 管理
• `/mcp` - MCP 配置
• `/exec` - 快速执行代码
• `/sandbox` - 🆕 CodeSandbox 沙盒管理
• `/debug` - 诊断问题

**🆕 CodeSandbox 功能：**
• `/sandbox exec print('hello')` - 执行 Python
• `/sandbox bash ls -la` - 执行 Shell
• `/sandbox install numpy` - 安装包
• `/sandbox files` - 列出文件
• `/sandbox upload test.py print('hi')` - 上传文件
• `/sandbox download test.py` - 下载文件

**示例：**
• `/agent 帮我找一个翻译插件并安装`
• `/agent 写一个查询天气的 Skill`
• `/sandbox exec import sys; print(sys.version)`
"""
    
    async def terminate(self):
        """插件停用时清理沙盒资源"""
        if self.executor and hasattr(self.executor, '_sandbox_cache'):
            for sandbox in self.executor._sandbox_cache.values():
                try:
                    await sandbox.astop()
                except Exception:
                    pass
            self.executor._sandbox_cache.clear()
        logger.info("全自主智能体编排器已停用")
