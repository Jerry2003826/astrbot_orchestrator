"""AstrBot 命令处理层。"""

from __future__ import annotations

import json
import logging
import traceback
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from ..runtime.container import RuntimeContainer
from ..runtime.request_context import RequestContext
from ..sandbox.types import ExecResult

logger = logging.getLogger(__name__)

BuildRequestContext = Callable[[Any, str, str, str], RequestContext]
TComponent = TypeVar("TComponent")


@dataclass(slots=True)
class CommandHandlers:
    """统一封装 AstrBot 命令处理逻辑。"""

    context: Any
    runtime: RuntimeContainer
    build_request_context: BuildRequestContext

    async def handle_agent(self, event: Any) -> AsyncIterator[Any]:
        """处理 `/agent` 命令。"""

        user_request = event.message_str.strip()
        if not user_request:
            yield event.plain_result(self.get_agent_help_message())
            return

        if user_request.lower() in {"status", "agents", "subagents", "子代理", "状态"}:
            if self.runtime.meta_orchestrator:
                yield event.plain_result(self.runtime.meta_orchestrator.status())
            else:
                yield event.plain_result("❌ SubAgent 编排器未初始化")
            return

        if user_request.lower() in {
            "templates",
            "template",
            "subagent templates",
            "子代理模板",
        }:
            if self.runtime.dynamic_agent_manager:
                templates = self.runtime.dynamic_agent_manager.get_template_config()
                yield event.plain_result(
                    "📦 SubAgent 默认模板配置:\n\n```json\n"
                    + json.dumps(templates, ensure_ascii=False, indent=2)
                    + "\n```\n\n"
                    + "💡 可通过插件配置项 `subagent_template_overrides` 覆盖模板"
                )
            else:
                yield event.plain_result("❌ SubAgent 模板未初始化")
            return

        orchestrator = self._require_component(self.runtime.orchestrator, "orchestrator")
        yield event.plain_result("🤖 正在分析任务，请稍候...")

        try:
            provider_id = await self._get_provider_id(event)
            request_context = self.build_request_context(
                event,
                user_request,
                provider_id,
                "agent",
            )
            result = await orchestrator.process_request(request_context)
            yield event.plain_result(result["answer"])
        except Exception as exc:
            logger.error("Agent 执行失败: %s", exc, exc_info=True)
            debugger = self.runtime.debugger
            if debugger is not None:
                try:
                    debug_result = await debugger.analyze_error(
                        error=exc,
                        traceback_info=traceback.format_exc(),
                        context={"request": user_request},
                    )
                    yield event.plain_result(
                        f"❌ 执行出错: {str(exc)}\n\n🔍 自动分析:\n{debug_result}"
                    )
                    return
                except Exception as debug_exc:
                    logger.debug("自动诊断失败，回退到普通错误输出: %s", debug_exc)
            yield event.plain_result(f"❌ 执行出错: {str(exc)}")

    async def handle_plugin(self, event: Any) -> AsyncIterator[Any]:
        """处理 `/plugin` 命令。"""

        args = event.message_str.strip().split(maxsplit=1)
        if not args:
            yield event.plain_result(self.get_plugin_help_message())
            return

        plugin_tool = self._require_component(self.runtime.plugin_tool, "plugin_tool")
        action = args[0].lower()
        param = args[1] if len(args) > 1 else ""

        if action == "search":
            yield event.plain_result(f"🔍 正在搜索插件: {param}...")
            yield event.plain_result(await plugin_tool.search_plugins(param))
            return

        if action == "install":
            if self._is_not_admin(event):
                yield event.plain_result("❌ 只有管理员可以安装插件")
                return
            yield event.plain_result(
                f"📥 正在安装插件: {param}...\n💡 使用 AstrBot 配置的 GitHub 加速"
            )
            yield event.plain_result(await plugin_tool.install_plugin(param))
            return

        if action == "list":
            yield event.plain_result(await plugin_tool.list_plugins())
            return

        if action == "remove":
            if self._is_not_admin(event):
                yield event.plain_result("❌ 只有管理员可以卸载插件")
                return
            yield event.plain_result(await plugin_tool.remove_plugin(param))
            return

        if action == "update":
            if self._is_not_admin(event):
                yield event.plain_result("❌ 只有管理员可以更新插件")
                return
            yield event.plain_result(f"🔄 正在更新插件: {param}...")
            yield event.plain_result(await plugin_tool.update_plugin(param))
            return

        if action == "proxy":
            yield event.plain_result(plugin_tool.get_available_proxies())
            return

        yield event.plain_result("无效命令，请使用 /plugin 查看帮助")

    async def handle_skill(self, event: Any) -> AsyncIterator[Any]:
        """处理 `/skill` 命令。"""

        args = event.message_str.strip().split(maxsplit=1)
        if not args:
            yield event.plain_result(self.get_skill_help_message())
            return

        skill_tool = self._require_component(self.runtime.skill_tool, "skill_tool")
        action = args[0].lower()
        param = args[1] if len(args) > 1 else ""

        if action == "list":
            yield event.plain_result(skill_tool.list_skills())
            return

        if action == "create":
            if not param:
                yield event.plain_result("请提供 Skill 名称")
                return
            yield event.plain_result(
                f"📝 准备创建 Skill: {param}\n\n"
                "请描述这个 Skill 的功能，我会帮你自动生成 SKILL.md 文件。\n"
                "例如：这是一个查询天气的 Skill，支持查询全国主要城市的天气..."
            )
            return

        if action == "read":
            yield event.plain_result(skill_tool.read_skill(param))
            return

        if action == "delete":
            if self._is_not_admin(event):
                yield event.plain_result("❌ 只有管理员可以删除 Skill")
                return
            yield event.plain_result(skill_tool.delete_skill(param))
            return

        yield event.plain_result("无效命令，请使用 /skill 查看帮助")

    async def handle_mcp(self, event: Any) -> AsyncIterator[Any]:
        """处理 `/mcp` 命令。"""

        args = event.message_str.strip().split()
        if not args:
            yield event.plain_result(self.get_mcp_help_message())
            return

        mcp_tool = self._require_component(self.runtime.mcp_tool, "mcp_tool")
        action = args[0].lower()

        if action == "list":
            yield event.plain_result(mcp_tool.list_servers())
            return

        if action == "add" and len(args) >= 3:
            if self._is_not_admin(event):
                yield event.plain_result("❌ 只有管理员可以添加 MCP")
                return
            yield event.plain_result(await mcp_tool.add_server(args[1], args[2]))
            return

        if action == "remove" and len(args) >= 2:
            if self._is_not_admin(event):
                yield event.plain_result("❌ 只有管理员可以移除 MCP")
                return
            yield event.plain_result(await mcp_tool.remove_server(args[1]))
            return

        if action == "test" and len(args) >= 2:
            yield event.plain_result(await mcp_tool.test_server(args[1]))
            return

        if action == "tools" and len(args) >= 2:
            yield event.plain_result(mcp_tool.list_tools(args[1]))
            return

        yield event.plain_result("无效命令，请使用 /mcp 查看帮助")

    async def handle_exec(self, event: Any) -> AsyncIterator[Any]:
        """处理 `/exec` 命令。"""

        if self._is_not_admin(event):
            yield event.plain_result("❌ 只有管理员可以执行代码")
            return

        args = event.message_str.strip().split(maxsplit=1)
        if not args:
            yield event.plain_result(self.get_exec_help_message())
            return

        executor = self._require_component(self.runtime.executor, "executor")
        mode = args[0].lower()
        code = args[1] if len(args) > 1 else ""

        if mode == "config":
            yield event.plain_result(executor.get_current_mode_info())
            return

        if mode not in {"local", "sandbox", "python"}:
            yield event.plain_result(await executor.execute(event.message_str.strip(), event))
            return

        if not code:
            yield event.plain_result("请提供要执行的代码或命令")
            return

        if mode == "local":
            yield event.plain_result(await executor.execute_local(code, event))
            return

        if mode == "sandbox":
            yield event.plain_result(await executor.execute_sandbox(code, event))
            return

        yield event.plain_result(await executor.execute_python(code, event))

    async def handle_debug(self, event: Any) -> AsyncIterator[Any]:
        """处理 `/debug` 命令。"""

        debugger = self._require_component(self.runtime.debugger, "debugger")
        args = event.message_str.strip().split(maxsplit=1)
        action = args[0].lower() if args else "status"
        param = args[1] if len(args) > 1 else ""

        if action == "status":
            yield event.plain_result(await debugger.get_system_status())
            return

        if action == "logs":
            yield event.plain_result(debugger.get_recent_errors())
            return

        if action == "analyze":
            provider_id = await self._get_provider_id(event)
            yield event.plain_result(await debugger.analyze_problem(param, provider_id))
            return

        yield event.plain_result(self.get_debug_help_message())

    async def handle_sandbox(self, event: Any) -> AsyncIterator[Any]:
        """处理 `/sandbox` 命令。"""

        if self._is_not_admin(event):
            yield event.plain_result("❌ 只有管理员可以操作沙盒")
            return

        args = event.message_str.strip().split(maxsplit=1)
        if not args:
            yield event.plain_result(self.get_sandbox_help_message())
            return

        executor = self._require_component(self.runtime.executor, "executor")
        action = args[0].lower()
        param = args[1] if len(args) > 1 else ""

        if action == "status":
            yield event.plain_result(await executor.healthcheck(event))
            return

        if action == "exec":
            if not param:
                yield event.plain_result("请提供要执行的 Python 代码")
                return
            yield event.plain_result("⏳ 正在执行...")
            exec_result = await executor.exec_code(param, event, kernel="ipython")
            yield event.plain_result(self.format_exec_result(exec_result))
            return

        if action == "bash":
            if not param:
                yield event.plain_result("请提供要执行的 Shell 命令")
                return
            yield event.plain_result("⏳ 正在执行...")
            exec_result = await executor.exec_code(param, event, kernel="bash")
            yield event.plain_result(self.format_exec_result(exec_result))
            return

        if action == "stream":
            if not param:
                yield event.plain_result("请提供要执行的代码")
                return
            yield event.plain_result("⏳ 流式执行中...")
            chunks = await executor.exec_code(
                param,
                event,
                kernel="ipython",
                stream=True,
            )
            output_parts: list[str] = []
            async for chunk in chunks:
                output_parts.append(str(chunk))
            yield event.plain_result("".join(output_parts) if output_parts else "(无输出)")
            return

        if action == "files":
            yield event.plain_result(await executor.list_files(param or ".", event))
            return

        if action == "upload":
            parts = param.split(maxsplit=1)
            if len(parts) < 2:
                yield event.plain_result("用法: `/sandbox upload <文件路径> <内容>`")
                return
            yield event.plain_result(await executor.write_file(parts[0], parts[1], event))
            return

        if action == "download":
            if not param:
                yield event.plain_result("请提供文件路径")
                return
            yield event.plain_result(await executor.read_file(param, event))
            return

        if action == "install":
            if not param:
                yield event.plain_result("请提供要安装的包名")
                return
            yield event.plain_result(f"📦 正在安装: {param}...")
            result = await executor.install_packages(param.split(), event)
            yield event.plain_result(f"📦 {result}")
            return

        if action == "packages":
            yield event.plain_result(await self._render_package_list(event))
            return

        if action == "variables":
            yield event.plain_result(await self._render_variable_list(event))
            return

        if action == "restart":
            yield event.plain_result(await executor.restart_sandbox(event))
            return

        if action == "url":
            parts = param.split(maxsplit=1)
            if len(parts) < 2:
                yield event.plain_result("用法: `/sandbox url <URL> <保存路径>`")
                return
            url, file_path = parts
            yield event.plain_result(f"⬇️ 正在下载: {url}...")
            try:
                sandbox_file = await executor.download_from_url(url, file_path, event)
                yield event.plain_result(
                    f"✅ 文件已下载: `{sandbox_file.path}` ({sandbox_file.size_human})"
                )
            except Exception as exc:
                yield event.plain_result(f"❌ 下载失败: {str(exc)}")
            return

        yield event.plain_result(self.get_sandbox_help_message())

    def format_exec_result(self, result: Any) -> str:
        """格式化执行结果文本。"""

        if not isinstance(result, ExecResult):
            return str(result)

        lines: list[str] = []
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

    def get_agent_help_message(self) -> str:
        """返回 `/agent` 帮助文本。"""

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
• `/sandbox` - CodeSandbox 沙盒管理
• `/debug` - 诊断问题

**示例：**
• `/agent 帮我找一个翻译插件并安装`
• `/agent 写一个查询天气的 Skill`
• `/sandbox exec import sys; print(sys.version)`
"""

    def get_plugin_help_message(self) -> str:
        """返回 `/plugin` 帮助文本。"""

        return (
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

    def get_skill_help_message(self) -> str:
        """返回 `/skill` 帮助文本。"""

        return (
            "📚 Skill 管理\n\n"
            "用法:\n"
            "  /skill list           - 列出所有 Skill\n"
            "  /skill create <名称>  - 创建新 Skill\n"
            "  /skill edit <名称>    - 编辑 Skill\n"
            "  /skill delete <名称>  - 删除 Skill\n"
            "  /skill read <名称>    - 查看内容"
        )

    def get_mcp_help_message(self) -> str:
        """返回 `/mcp` 帮助文本。"""

        return (
            "🔌 MCP 配置管理\n\n"
            "用法:\n"
            "  /mcp list            - 列出所有 MCP 服务\n"
            "  /mcp add <名称> <url> - 添加 MCP 服务\n"
            "  /mcp remove <名称>   - 移除 MCP 服务\n"
            "  /mcp test <名称>     - 测试连接\n"
            "  /mcp tools <名称>    - 查看工具列表"
        )

    def get_exec_help_message(self) -> str:
        """返回 `/exec` 帮助文本。"""

        return (
            "🖥️ **代码执行**\n\n"
            "执行环境由 AstrBot 全局配置决定（配置文件 → 使用电脑能力）\n\n"
            "**用法:**\n"
            "  `/exec <命令>`          - 使用全局配置执行\n"
            "  `/exec local <命令>`    - 强制本地执行\n"
            "  `/exec sandbox <命令>`  - 强制沙盒执行\n"
            "  `/exec python <代码>`   - 执行 Python\n"
            "  `/exec config`          - 查看当前配置"
        )

    def get_debug_help_message(self) -> str:
        """返回 `/debug` 帮助文本。"""

        return (
            "🐛 Debug 工具\n\n"
            "用法:\n"
            "  /debug status    - 系统状态\n"
            "  /debug logs      - 错误日志\n"
            "  /debug analyze <问题> - 分析问题"
        )

    def get_sandbox_help_message(self) -> str:
        """返回 `/sandbox` 帮助文本。"""

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

    async def _render_package_list(self, event: Any) -> str:
        """渲染已安装包列表。"""

        executor = self._require_component(self.runtime.executor, "executor")
        try:
            packages = await executor.list_packages(event)
        except Exception as exc:
            return f"❌ 获取包列表失败: {str(exc)}"

        if not packages:
            return "📦 暂无已安装的包"

        pkg_list = "\n".join([f"  • {package}" for package in packages[:50]])
        total = len(packages)
        suffix = f"\n  ... 还有 {total - 50} 个" if total > 50 else ""
        return f"📦 **已安装的 Python 包** ({total} 个)\n\n{pkg_list}{suffix}"

    async def _render_variable_list(self, event: Any) -> str:
        """渲染会话变量列表。"""

        executor = self._require_component(self.runtime.executor, "executor")
        try:
            variables = await executor.show_variables(event)
        except Exception as exc:
            return f"❌ 获取变量失败: {str(exc)}"

        if not variables:
            return "📊 当前会话无变量"

        var_list = "\n".join([f"  • `{key}` = {value}" for key, value in variables.items()])
        return f"📊 **会话变量**\n\n{var_list}"

    async def _get_provider_id(self, event: Any) -> str:
        """根据消息事件解析 provider_id。"""

        provider_id = await self.context.get_current_chat_provider_id(umo=event.unified_msg_origin)
        return cast(str, provider_id)

    @staticmethod
    def _is_not_admin(event: Any) -> bool:
        """判断当前事件是否非管理员。"""

        return getattr(event, "role", "") != "admin"

    @staticmethod
    def _require_component(component: TComponent | None, name: str) -> TComponent:
        """确保运行时组件已就绪。"""

        if component is None:
            raise RuntimeError(f"运行时组件未初始化: {name}")
        return component
