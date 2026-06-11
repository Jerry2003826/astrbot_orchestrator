"""AstrBot 全自主智能体编排器（官方 Agent 体系版）。

- 默认聊天：通过 ``context.add_llm_tools`` 注册 FunctionTool，
  由 AstrBot 默认 Agent 自然语言调用（无需自研路由）。
- ``/agent``：AgentRunner 调 ``context.tool_loop_agent`` 执行多步任务。
- 子代理：预设模板经 DynamicAgentManager 写入官方
  ``subagent_orchestrator`` 配置，由官方 HandoffTool 体系执行。
"""

from collections.abc import AsyncIterator
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.star.filter.command import GreedyStr

from .entrypoints import CommandHandlers
from .runtime.container import RuntimeContainer

ADMIN = filter.PermissionType.ADMIN


@register(
    name="astrbot_plugin_orchestrator",
    desc="全自主智能体编排器 - 基于官方 tool_loop_agent + FunctionTool + HandoffTool",
    version="4.0.0",
    author="lijiarui",
)
class OrchestratorPlugin(Star):
    """全自主智能体编排器插件入口。"""

    def __init__(
        self,
        context: Context,
        config: AstrBotConfig | None = None,
    ) -> None:
        super().__init__(context)
        self.config = config if config is not None else AstrBotConfig()
        self.runtime: RuntimeContainer | None = None
        self.command_handlers: CommandHandlers | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """装配运行时、注册 FunctionTool、同步子代理模板。"""

        if self._initialized:
            return

        logger.info("初始化全自主智能体编排器 v4...")
        self.runtime = RuntimeContainer.build(self.context, self.config)
        self.command_handlers = CommandHandlers(
            context=self.context,
            runtime=self.runtime,
        )

        if self.runtime.tools:
            self.context.add_llm_tools(*self.runtime.tools)
            logger.info("已注册 %d 个 FunctionTool", len(self.runtime.tools))

        if self._config_bool("enable_dynamic_agents", True):
            manager = self.runtime.dynamic_agent_manager
            if manager is not None:
                try:
                    result = await manager.sync_templates_to_host()
                    logger.info("子代理模板同步: %s", result)
                except Exception:
                    logger.warning("子代理模板同步失败", exc_info=True)

        self._initialized = True
        logger.info("全自主智能体编排器初始化完成")

    async def terminate(self) -> None:
        """插件卸载时释放沙盒等资源。"""

        if self.runtime is not None:
            await self.runtime.astop()
        self._initialized = False
        logger.info("全自主智能体编排器已停止")

    def _config_bool(self, key: str, default: bool) -> bool:
        value = self.config.get(key)
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "是", "开启"}
        return bool(value)

    def _handlers(self) -> CommandHandlers:
        if self.command_handlers is None:
            raise RuntimeError("命令处理器未初始化")
        return self.command_handlers

    # ==================================================================
    # /agent
    # ==================================================================
    @filter.command("agent")
    async def cmd_agent(self, event: AstrMessageEvent, task: GreedyStr = "") -> AsyncIterator[Any]:
        """全自主执行任务；也支持 status/templates/sync 子查询"""

        async for result in self._handlers().handle_agent(event, str(task)):
            yield result

    # ==================================================================
    # /plugin
    # ==================================================================
    @filter.command_group("plugin")
    def plugin_group(self):
        """插件管理指令组"""

    @plugin_group.command("search")
    async def cmd_plugin_search(
        self, event: AstrMessageEvent, keyword: GreedyStr = ""
    ) -> AsyncIterator[Any]:
        """搜索插件市场"""

        async for result in self._handlers().plugin_search(event, str(keyword)):
            yield result

    @plugin_group.command("list")
    async def cmd_plugin_list(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        """列出已安装插件"""

        async for result in self._handlers().plugin_list(event):
            yield result

    @plugin_group.command("proxy")
    async def cmd_plugin_proxy(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        """查看 GitHub 加速代理配置"""

        async for result in self._handlers().plugin_proxy(event):
            yield result

    @filter.permission_type(ADMIN)
    @plugin_group.command("install")
    async def cmd_plugin_install(
        self, event: AstrMessageEvent, url: GreedyStr = ""
    ) -> AsyncIterator[Any]:
        """安装插件（管理员）"""

        async for result in self._handlers().plugin_install(event, str(url)):
            yield result

    @filter.permission_type(ADMIN)
    @plugin_group.command("remove")
    async def cmd_plugin_remove(
        self, event: AstrMessageEvent, name: str = ""
    ) -> AsyncIterator[Any]:
        """卸载插件（管理员）"""

        async for result in self._handlers().plugin_remove(event, name):
            yield result

    @filter.permission_type(ADMIN)
    @plugin_group.command("update")
    async def cmd_plugin_update(
        self, event: AstrMessageEvent, name: str = ""
    ) -> AsyncIterator[Any]:
        """更新插件（管理员）"""

        async for result in self._handlers().plugin_update(event, name):
            yield result

    # ==================================================================
    # /skill
    # ==================================================================
    @filter.command_group("skill")
    def skill_group(self):
        """Skill 管理指令组"""

    @filter.permission_type(ADMIN)
    @skill_group.command("list")
    async def cmd_skill_list(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        """列出全部 Skill（管理员）"""

        async for result in self._handlers().skill_list(event):
            yield result

    @skill_group.command("create")
    async def cmd_skill_create(
        self, event: AstrMessageEvent, name: GreedyStr = ""
    ) -> AsyncIterator[Any]:
        """创建 Skill 的引导"""

        async for result in self._handlers().skill_create(event, str(name)):
            yield result

    @filter.permission_type(ADMIN)
    @skill_group.command("read")
    async def cmd_skill_read(
        self, event: AstrMessageEvent, name: GreedyStr = ""
    ) -> AsyncIterator[Any]:
        """读取 Skill 内容（管理员）"""

        async for result in self._handlers().skill_read(event, str(name)):
            yield result

    @filter.permission_type(ADMIN)
    @skill_group.command("delete")
    async def cmd_skill_delete(
        self, event: AstrMessageEvent, name: GreedyStr = ""
    ) -> AsyncIterator[Any]:
        """删除 Skill（管理员）"""

        async for result in self._handlers().skill_delete(event, str(name)):
            yield result

    # ==================================================================
    # /mcp（管理员）
    # ==================================================================
    @filter.command_group("mcp")
    def mcp_group(self):
        """MCP 服务器管理指令组"""

    @filter.permission_type(ADMIN)
    @mcp_group.command("list")
    async def cmd_mcp_list(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        """列出 MCP 服务器（管理员）"""

        async for result in self._handlers().mcp_list(event):
            yield result

    @filter.permission_type(ADMIN)
    @mcp_group.command("add")
    async def cmd_mcp_add(
        self, event: AstrMessageEvent, name: str = "", url: str = ""
    ) -> AsyncIterator[Any]:
        """添加 MCP 服务器（管理员）"""

        async for result in self._handlers().mcp_add(event, name, url):
            yield result

    @filter.permission_type(ADMIN)
    @mcp_group.command("remove")
    async def cmd_mcp_remove(self, event: AstrMessageEvent, name: str = "") -> AsyncIterator[Any]:
        """移除 MCP 服务器（管理员）"""

        async for result in self._handlers().mcp_remove(event, name):
            yield result

    @filter.permission_type(ADMIN)
    @mcp_group.command("test")
    async def cmd_mcp_test(self, event: AstrMessageEvent, name: str = "") -> AsyncIterator[Any]:
        """测试 MCP 服务器连通性（管理员）"""

        async for result in self._handlers().mcp_test(event, name):
            yield result

    @filter.permission_type(ADMIN)
    @mcp_group.command("tools")
    async def cmd_mcp_tools(self, event: AstrMessageEvent, name: str = "") -> AsyncIterator[Any]:
        """列出 MCP 服务器的工具（管理员）"""

        async for result in self._handlers().mcp_tools(event, name):
            yield result

    # ==================================================================
    # /exec（管理员）
    # ==================================================================
    @filter.command_group("exec")
    def exec_group(self):
        """快速执行指令组"""

    @filter.permission_type(ADMIN)
    @exec_group.command("config")
    async def cmd_exec_config(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        """查看执行模式配置（管理员）"""

        async for result in self._handlers().exec_config(event):
            yield result

    @filter.permission_type(ADMIN)
    @exec_group.command("run")
    async def cmd_exec_run(
        self, event: AstrMessageEvent, command: GreedyStr = ""
    ) -> AsyncIterator[Any]:
        """自动模式执行命令（管理员）"""

        async for result in self._handlers().exec_run(event, str(command), "auto"):
            yield result

    @filter.permission_type(ADMIN)
    @exec_group.command("local")
    async def cmd_exec_local(
        self, event: AstrMessageEvent, command: GreedyStr = ""
    ) -> AsyncIterator[Any]:
        """本地执行命令（管理员）"""

        async for result in self._handlers().exec_run(event, str(command), "local"):
            yield result

    @filter.permission_type(ADMIN)
    @exec_group.command("sandbox")
    async def cmd_exec_sandbox(
        self, event: AstrMessageEvent, command: GreedyStr = ""
    ) -> AsyncIterator[Any]:
        """沙盒执行命令（管理员）"""

        async for result in self._handlers().exec_run(event, str(command), "sandbox"):
            yield result

    @filter.permission_type(ADMIN)
    @exec_group.command("python")
    async def cmd_exec_python(
        self, event: AstrMessageEvent, code: GreedyStr = ""
    ) -> AsyncIterator[Any]:
        """执行 Python 代码（管理员）"""

        async for result in self._handlers().exec_run(event, str(code), "python"):
            yield result

    # ==================================================================
    # /sandbox（管理员）
    # ==================================================================
    @filter.command_group("sandbox")
    def sandbox_group(self):
        """沙盒管理指令组"""

    @filter.permission_type(ADMIN)
    @sandbox_group.command("status")
    async def cmd_sandbox_status(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        """沙盒健康检查（管理员）"""

        async for result in self._handlers().sandbox_status(event):
            yield result

    @filter.permission_type(ADMIN)
    @sandbox_group.command("exec")
    async def cmd_sandbox_exec(
        self, event: AstrMessageEvent, code: GreedyStr = ""
    ) -> AsyncIterator[Any]:
        """沙盒执行 Python（管理员）"""

        async for result in self._handlers().sandbox_exec(event, str(code), "ipython"):
            yield result

    @filter.permission_type(ADMIN)
    @sandbox_group.command("bash")
    async def cmd_sandbox_bash(
        self, event: AstrMessageEvent, code: GreedyStr = ""
    ) -> AsyncIterator[Any]:
        """沙盒执行 Shell（管理员）"""

        async for result in self._handlers().sandbox_exec(event, str(code), "bash"):
            yield result

    @filter.permission_type(ADMIN)
    @sandbox_group.command("stream")
    async def cmd_sandbox_stream(
        self, event: AstrMessageEvent, code: GreedyStr = ""
    ) -> AsyncIterator[Any]:
        """沙盒流式执行（管理员）"""

        async for result in self._handlers().sandbox_stream(event, str(code)):
            yield result

    @filter.permission_type(ADMIN)
    @sandbox_group.command("files")
    async def cmd_sandbox_files(
        self, event: AstrMessageEvent, path: str = "."
    ) -> AsyncIterator[Any]:
        """列出沙盒文件（管理员）"""

        async for result in self._handlers().sandbox_files(event, path):
            yield result

    @filter.permission_type(ADMIN)
    @sandbox_group.command("upload")
    async def cmd_sandbox_upload(
        self, event: AstrMessageEvent, path: str = "", content: GreedyStr = ""
    ) -> AsyncIterator[Any]:
        """写入沙盒文件（管理员）"""

        async for result in self._handlers().sandbox_upload(event, path, str(content)):
            yield result

    @filter.permission_type(ADMIN)
    @sandbox_group.command("download")
    async def cmd_sandbox_download(
        self, event: AstrMessageEvent, path: GreedyStr = ""
    ) -> AsyncIterator[Any]:
        """读取沙盒文件（管理员）"""

        async for result in self._handlers().sandbox_download(event, str(path)):
            yield result

    @filter.permission_type(ADMIN)
    @sandbox_group.command("install")
    async def cmd_sandbox_install(
        self, event: AstrMessageEvent, packages: GreedyStr = ""
    ) -> AsyncIterator[Any]:
        """安装 Python 包（管理员）"""

        async for result in self._handlers().sandbox_install(event, str(packages)):
            yield result

    @filter.permission_type(ADMIN)
    @sandbox_group.command("packages")
    async def cmd_sandbox_packages(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        """列出已安装包（管理员）"""

        async for result in self._handlers().sandbox_packages(event):
            yield result

    @filter.permission_type(ADMIN)
    @sandbox_group.command("variables")
    async def cmd_sandbox_variables(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        """查看会话变量（管理员）"""

        async for result in self._handlers().sandbox_variables(event):
            yield result

    @filter.permission_type(ADMIN)
    @sandbox_group.command("restart")
    async def cmd_sandbox_restart(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        """重启沙盒（管理员）"""

        async for result in self._handlers().sandbox_restart(event):
            yield result

    @filter.permission_type(ADMIN)
    @sandbox_group.command("url")
    async def cmd_sandbox_url(
        self, event: AstrMessageEvent, url: str = "", save_path: str = ""
    ) -> AsyncIterator[Any]:
        """从 URL 下载文件到沙盒（管理员）"""

        async for result in self._handlers().sandbox_url(event, url, save_path):
            yield result

    # ==================================================================
    # /debug（管理员）
    # ==================================================================
    @filter.command_group("debug")
    def debug_group(self):
        """诊断指令组"""

    @filter.permission_type(ADMIN)
    @debug_group.command("status")
    async def cmd_debug_status(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        """系统状态（管理员）"""

        async for result in self._handlers().debug_status(event):
            yield result

    @filter.permission_type(ADMIN)
    @debug_group.command("logs")
    async def cmd_debug_logs(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        """最近错误（管理员）"""

        async for result in self._handlers().debug_logs(event):
            yield result

    @filter.permission_type(ADMIN)
    @debug_group.command("analyze")
    async def cmd_debug_analyze(
        self, event: AstrMessageEvent, problem: GreedyStr = ""
    ) -> AsyncIterator[Any]:
        """分析问题（管理员）"""

        async for result in self._handlers().debug_analyze(event, str(problem)):
            yield result
