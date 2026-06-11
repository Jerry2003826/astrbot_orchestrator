"""AstrBot 命令处理层。

命令参数由 AstrBot 框架按类型注入（command_group + GreedyStr），
本层方法接收显式参数，不再手工解析 event.message_str；
管理员权限由 main.py 的 @filter.permission_type 装饰器保证。
"""

from __future__ import annotations

from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
import time
import traceback
from typing import Any, TypeVar

from astrbot.api import logger
from astrbot.core.log import LogManager

from ..runtime.container import RuntimeContainer
from ..sandbox.types import ExecResult
from ..shared.path_utils import get_plugin_data_dir

audit_logger = LogManager.GetLogger("astrbot_orchestrator.security_audit")

TComponent = TypeVar("TComponent")
_AUDIT_VALUE_LIMIT = 160


@dataclass(frozen=True, slots=True)
class RateLimitRule:
    """命令入口级别的固定窗口限流规则。"""

    limit: int
    window_seconds: float
    message: str


@dataclass(slots=True)
class CommandRateLimiter:
    """简单的内存限流器，按 actor + scope 记录请求窗口。"""

    clock: Callable[[], float] = time.monotonic
    _buckets: dict[str, deque[float]] = field(default_factory=dict)

    def allow(self, key: str, *, limit: int, window_seconds: float) -> bool:
        """检查并登记当前请求。"""

        now = self.clock()
        bucket = self._buckets.setdefault(key, deque())
        cutoff = now - window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= limit:
            return False

        bucket.append(now)
        return True


_RATE_LIMIT_RULES = {
    "agent": RateLimitRule(12, 60.0, "⏳ Agent 请求过于频繁，请稍后再试"),
    "plugin.search": RateLimitRule(15, 60.0, "⏳ 插件搜索过于频繁，请稍后再试"),
    "plugin.admin": RateLimitRule(8, 60.0, "⏳ 插件管理操作过于频繁，请稍后再试"),
    "skill.admin": RateLimitRule(10, 60.0, "⏳ Skill 管理操作过于频繁，请稍后再试"),
    "mcp.admin": RateLimitRule(8, 60.0, "⏳ MCP 管理操作过于频繁，请稍后再试"),
    "debug": RateLimitRule(10, 60.0, "⏳ Debug 请求过于频繁，请稍后再试"),
    "exec": RateLimitRule(8, 60.0, "⏳ 执行请求过于频繁，请稍后再试"),
    "sandbox": RateLimitRule(12, 60.0, "⏳ 沙盒操作过于频繁，请稍后再试"),
}


@dataclass(slots=True)
class CommandHandlers:
    """统一封装 AstrBot 命令处理逻辑。"""

    context: Any
    runtime: RuntimeContainer
    rate_limiter: CommandRateLimiter = field(default_factory=CommandRateLimiter)

    # ------------------------------------------------------------------
    # /agent
    # ------------------------------------------------------------------
    async def handle_agent(self, event: Any, task: str) -> AsyncIterator[Any]:
        """处理 `/agent <task>`。"""

        user_request = task.strip()
        if not user_request:
            yield event.plain_result(self.get_agent_help_message())
            return

        if user_request.lower() in {"status", "agents", "subagents", "子代理", "状态"}:
            async for result in self.agent_status(event):
                yield result
            return

        if user_request.lower() in {
            "templates",
            "template",
            "subagent templates",
            "子代理模板",
        }:
            async for result in self.agent_templates(event):
                yield result
            return

        if user_request.lower() in {"sync", "同步模板"}:
            async for result in self.agent_sync(event):
                yield result
            return

        agent_runner = self._require_component(self.runtime.agent_runner, "agent_runner")
        if limited := self._check_rate_limit(event, "agent", "agent", "run"):
            yield event.plain_result(limited)
            return

        yield event.plain_result("🤖 正在执行任务，请稍候...")

        try:
            answer = await agent_runner.run(event, user_request)
            yield self._plain_result_with_audit(
                event,
                command="agent",
                action="run",
                result_text=answer,
            )
        except Exception as exc:
            self._audit_security_event(event, command="agent", action="run", outcome="error")
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

    async def agent_status(self, event: Any) -> AsyncIterator[Any]:
        """展示官方 subagent handoff 状态。"""

        manager = self._require_component(
            self.runtime.dynamic_agent_manager, "dynamic_agent_manager"
        )
        yield event.plain_result(manager.status_report())

    async def agent_templates(self, event: Any) -> AsyncIterator[Any]:
        """展示 subagent 预设模板。"""

        manager = self._require_component(
            self.runtime.dynamic_agent_manager, "dynamic_agent_manager"
        )
        yield event.plain_result(manager.templates_report())

    async def agent_sync(self, event: Any) -> AsyncIterator[Any]:
        """处理 `/agent sync`：把预设模板注册为官方子代理（管理员）。"""

        if not event.is_admin():
            yield event.plain_result("⛔ 仅管理员可以同步子代理模板")
            return
        manager = self._require_component(
            self.runtime.dynamic_agent_manager, "dynamic_agent_manager"
        )
        result = await manager.sync_templates_to_host()
        yield self._plain_result_with_audit(
            event,
            command="agent",
            action="sync",
            result_text=result,
        )

    # ------------------------------------------------------------------
    # /plugin
    # ------------------------------------------------------------------
    async def plugin_search(self, event: Any, keyword: str) -> AsyncIterator[Any]:
        """处理 `/plugin search <关键词>`。"""

        keyword = keyword.strip()
        if not keyword:
            yield event.plain_result("用法: `/plugin search <关键词>`")
            return
        plugin_tool = self._require_component(self.runtime.plugin_tool, "plugin_tool")
        if limited := self._check_rate_limit(
            event, "plugin.search", "plugin", "search", target=keyword
        ):
            yield event.plain_result(limited)
            return
        yield event.plain_result(f"🔍 正在搜索插件: {keyword}...")
        result = await plugin_tool.search_plugins(keyword)
        yield self._plain_result_with_audit(
            event,
            command="plugin",
            action="search",
            result_text=result,
            target=keyword,
        )

    async def plugin_install(self, event: Any, url: str) -> AsyncIterator[Any]:
        """处理 `/plugin install <url>`（管理员）。"""

        url = url.strip()
        if not url:
            yield event.plain_result("用法: `/plugin install <仓库地址>`")
            return
        plugin_tool = self._require_component(self.runtime.plugin_tool, "plugin_tool")
        if limited := self._check_rate_limit(
            event, "plugin.admin", "plugin", "install", target=url
        ):
            yield event.plain_result(limited)
            return
        yield event.plain_result(f"📥 正在安装插件: {url}...\n💡 使用 AstrBot 配置的 GitHub 加速")
        result = await plugin_tool.install_plugin(url)
        yield self._plain_result_with_audit(
            event,
            command="plugin",
            action="install",
            result_text=result,
            target=url,
        )

    async def plugin_list(self, event: Any) -> AsyncIterator[Any]:
        """处理 `/plugin list`。"""

        plugin_tool = self._require_component(self.runtime.plugin_tool, "plugin_tool")
        yield event.plain_result(await plugin_tool.list_plugins())

    async def plugin_remove(self, event: Any, name: str) -> AsyncIterator[Any]:
        """处理 `/plugin remove <名称>`（管理员）。"""

        name = name.strip()
        if not name:
            yield event.plain_result("用法: `/plugin remove <插件名>`")
            return
        plugin_tool = self._require_component(self.runtime.plugin_tool, "plugin_tool")
        if limited := self._check_rate_limit(
            event, "plugin.admin", "plugin", "remove", target=name
        ):
            yield event.plain_result(limited)
            return
        result = await plugin_tool.remove_plugin(name)
        yield self._plain_result_with_audit(
            event,
            command="plugin",
            action="remove",
            result_text=result,
            target=name,
        )

    async def plugin_update(self, event: Any, name: str) -> AsyncIterator[Any]:
        """处理 `/plugin update <名称>`（管理员）。"""

        name = name.strip()
        if not name:
            yield event.plain_result("用法: `/plugin update <插件名>`")
            return
        plugin_tool = self._require_component(self.runtime.plugin_tool, "plugin_tool")
        if limited := self._check_rate_limit(
            event, "plugin.admin", "plugin", "update", target=name
        ):
            yield event.plain_result(limited)
            return
        yield event.plain_result(f"🔄 正在更新插件: {name}...")
        result = await plugin_tool.update_plugin(name)
        yield self._plain_result_with_audit(
            event,
            command="plugin",
            action="update",
            result_text=result,
            target=name,
        )

    async def plugin_proxy(self, event: Any) -> AsyncIterator[Any]:
        """处理 `/plugin proxy`。"""

        plugin_tool = self._require_component(self.runtime.plugin_tool, "plugin_tool")
        yield event.plain_result(plugin_tool.get_available_proxies())

    # ------------------------------------------------------------------
    # /skill
    # ------------------------------------------------------------------
    async def skill_list(self, event: Any) -> AsyncIterator[Any]:
        """处理 `/skill list`（管理员）。"""

        skill_tool = self._require_component(self.runtime.skill_tool, "skill_tool")
        if limited := self._check_rate_limit(event, "skill.admin", "skill", "list"):
            yield event.plain_result(limited)
            return
        result = skill_tool.list_skills()
        yield self._plain_result_with_audit(
            event,
            command="skill",
            action="list",
            result_text=result,
        )

    async def skill_create(self, event: Any, name: str) -> AsyncIterator[Any]:
        """处理 `/skill create <名称>`。"""

        name = name.strip()
        if not name:
            yield event.plain_result("请提供 Skill 名称")
            return
        yield event.plain_result(
            f"📝 准备创建 Skill: {name}\n\n"
            "请描述这个 Skill 的功能，我会帮你自动生成 SKILL.md 文件。\n"
            "例如：这是一个查询天气的 Skill，支持查询全国主要城市的天气..."
        )

    async def skill_read(self, event: Any, name: str) -> AsyncIterator[Any]:
        """处理 `/skill read <名称>`（管理员）。"""

        name = name.strip()
        if not name:
            yield event.plain_result("用法: `/skill read <名称>`")
            return
        skill_tool = self._require_component(self.runtime.skill_tool, "skill_tool")
        if limited := self._check_rate_limit(event, "skill.admin", "skill", "read", target=name):
            yield event.plain_result(limited)
            return
        result = skill_tool.read_skill(name)
        yield self._plain_result_with_audit(
            event,
            command="skill",
            action="read",
            result_text=result,
            target=name,
        )

    async def skill_delete(self, event: Any, name: str) -> AsyncIterator[Any]:
        """处理 `/skill delete <名称>`（管理员）。"""

        name = name.strip()
        if not name:
            yield event.plain_result("用法: `/skill delete <名称>`")
            return
        skill_tool = self._require_component(self.runtime.skill_tool, "skill_tool")
        if limited := self._check_rate_limit(event, "skill.admin", "skill", "delete", target=name):
            yield event.plain_result(limited)
            return
        result = skill_tool.delete_skill(name)
        yield self._plain_result_with_audit(
            event,
            command="skill",
            action="delete",
            result_text=result,
            target=name,
        )

    # ------------------------------------------------------------------
    # /mcp（管理员）
    # ------------------------------------------------------------------
    async def mcp_list(self, event: Any) -> AsyncIterator[Any]:
        """处理 `/mcp list`。"""

        mcp_tool = self._require_component(self.runtime.mcp_tool, "mcp_tool")
        if limited := self._check_rate_limit(event, "mcp.admin", "mcp", "list"):
            yield event.plain_result(limited)
            return
        result = mcp_tool.list_servers()
        yield self._plain_result_with_audit(
            event,
            command="mcp",
            action="list",
            result_text=result,
        )

    async def mcp_add(self, event: Any, name: str, url: str) -> AsyncIterator[Any]:
        """处理 `/mcp add <名称> <url>`。"""

        name, url = name.strip(), url.strip()
        if not name or not url:
            yield event.plain_result("用法: `/mcp add <名称> <url>`")
            return
        mcp_tool = self._require_component(self.runtime.mcp_tool, "mcp_tool")
        if limited := self._check_rate_limit(event, "mcp.admin", "mcp", "add", target=name):
            yield event.plain_result(limited)
            return
        result = await mcp_tool.add_server(name, url)
        yield self._plain_result_with_audit(
            event,
            command="mcp",
            action="add",
            result_text=result,
            target=name,
        )

    async def mcp_remove(self, event: Any, name: str) -> AsyncIterator[Any]:
        """处理 `/mcp remove <名称>`。"""

        name = name.strip()
        if not name:
            yield event.plain_result("用法: `/mcp remove <名称>`")
            return
        mcp_tool = self._require_component(self.runtime.mcp_tool, "mcp_tool")
        if limited := self._check_rate_limit(event, "mcp.admin", "mcp", "remove", target=name):
            yield event.plain_result(limited)
            return
        result = await mcp_tool.remove_server(name)
        yield self._plain_result_with_audit(
            event,
            command="mcp",
            action="remove",
            result_text=result,
            target=name,
        )

    async def mcp_test(self, event: Any, name: str) -> AsyncIterator[Any]:
        """处理 `/mcp test <名称>`。"""

        name = name.strip()
        if not name:
            yield event.plain_result("用法: `/mcp test <名称>`")
            return
        mcp_tool = self._require_component(self.runtime.mcp_tool, "mcp_tool")
        if limited := self._check_rate_limit(event, "mcp.admin", "mcp", "test", target=name):
            yield event.plain_result(limited)
            return
        result = await mcp_tool.test_server(name)
        yield self._plain_result_with_audit(
            event,
            command="mcp",
            action="test",
            result_text=result,
            target=name,
        )

    async def mcp_tools(self, event: Any, name: str) -> AsyncIterator[Any]:
        """处理 `/mcp tools <名称>`。"""

        name = name.strip()
        if not name:
            yield event.plain_result("用法: `/mcp tools <名称>`")
            return
        mcp_tool = self._require_component(self.runtime.mcp_tool, "mcp_tool")
        if limited := self._check_rate_limit(event, "mcp.admin", "mcp", "tools", target=name):
            yield event.plain_result(limited)
            return
        result = mcp_tool.list_tools(name)
        yield self._plain_result_with_audit(
            event,
            command="mcp",
            action="tools",
            result_text=result,
            target=name,
        )

    # ------------------------------------------------------------------
    # /exec（管理员）
    # ------------------------------------------------------------------
    async def exec_config(self, event: Any) -> AsyncIterator[Any]:
        """处理 `/exec config`。"""

        executor = self._require_component(self.runtime.executor, "executor")
        result = executor.get_current_mode_info()
        yield self._plain_result_with_audit(
            event,
            command="exec",
            action="config",
            result_text=result,
        )

    async def exec_run(
        self,
        event: Any,
        command: str,
        mode: str = "auto",
    ) -> AsyncIterator[Any]:
        """处理 `/exec run|local|sandbox|python <命令>`。"""

        command = command.strip()
        if not command:
            yield event.plain_result("请提供要执行的代码或命令")
            return
        executor = self._require_component(self.runtime.executor, "executor")
        if limited := self._check_rate_limit(event, "exec", "exec", mode):
            yield event.plain_result(limited)
            return

        if mode == "local":
            result = await executor.execute_local(command, event)
        elif mode == "sandbox":
            result = await executor.execute_sandbox(command, event)
        elif mode == "python":
            result = await executor.execute_python(command, event)
        else:
            result = await executor.execute(command, event)
        yield self._plain_result_with_audit(
            event,
            command="exec",
            action="run",
            result_text=result,
            target=mode,
        )

    # ------------------------------------------------------------------
    # /debug（管理员）
    # ------------------------------------------------------------------
    async def debug_status(self, event: Any) -> AsyncIterator[Any]:
        """处理 `/debug status`。"""

        debugger = self._require_component(self.runtime.debugger, "debugger")
        if limited := self._check_rate_limit(event, "debug", "debug", "status"):
            yield event.plain_result(limited)
            return
        result = await debugger.get_system_status()
        yield self._plain_result_with_audit(
            event,
            command="debug",
            action="status",
            result_text=result,
        )

    async def debug_logs(self, event: Any) -> AsyncIterator[Any]:
        """处理 `/debug logs`。"""

        debugger = self._require_component(self.runtime.debugger, "debugger")
        if limited := self._check_rate_limit(event, "debug", "debug", "logs"):
            yield event.plain_result(limited)
            return
        result = debugger.get_recent_errors()
        yield self._plain_result_with_audit(
            event,
            command="debug",
            action="logs",
            result_text=result,
        )

    async def debug_analyze(self, event: Any, problem: str) -> AsyncIterator[Any]:
        """处理 `/debug analyze <问题描述>`。"""

        problem = problem.strip()
        if not problem:
            yield event.plain_result("用法: `/debug analyze <问题描述>`")
            return
        debugger = self._require_component(self.runtime.debugger, "debugger")
        if limited := self._check_rate_limit(event, "debug", "debug", "analyze"):
            yield event.plain_result(limited)
            return
        provider_id = await self._get_provider_id(event)
        result = await debugger.analyze_problem(problem, provider_id)
        yield self._plain_result_with_audit(
            event,
            command="debug",
            action="analyze",
            result_text=result,
        )

    # ------------------------------------------------------------------
    # /sandbox（管理员）
    # ------------------------------------------------------------------
    async def sandbox_status(self, event: Any) -> AsyncIterator[Any]:
        """处理 `/sandbox status`。"""

        executor = self._require_component(self.runtime.executor, "executor")
        if limited := self._check_rate_limit(event, "sandbox", "sandbox", "status"):
            yield event.plain_result(limited)
            return
        result = await executor.healthcheck(event)
        yield self._plain_result_with_audit(
            event,
            command="sandbox",
            action="status",
            result_text=result,
        )

    async def sandbox_exec(
        self, event: Any, code: str, kernel: str = "ipython"
    ) -> AsyncIterator[Any]:
        """处理 `/sandbox exec|bash <代码>`。"""

        code = code.strip()
        if not code:
            yield event.plain_result(
                "请提供要执行的 Python 代码" if kernel == "ipython" else "请提供要执行的 Shell 命令"
            )
            return
        executor = self._require_component(self.runtime.executor, "executor")
        action = "exec" if kernel == "ipython" else "bash"
        if limited := self._check_rate_limit(event, "sandbox", "sandbox", action):
            yield event.plain_result(limited)
            return
        yield event.plain_result("⏳ 正在执行...")
        exec_result = await executor.exec_code(code, event, kernel=kernel)
        result = self.format_exec_result(exec_result)
        yield self._plain_result_with_audit(
            event,
            command="sandbox",
            action=action,
            result_text=result,
        )

    async def sandbox_stream(self, event: Any, code: str) -> AsyncIterator[Any]:
        """处理 `/sandbox stream <代码>`。"""

        code = code.strip()
        if not code:
            yield event.plain_result("请提供要执行的代码")
            return
        executor = self._require_component(self.runtime.executor, "executor")
        if limited := self._check_rate_limit(event, "sandbox", "sandbox", "stream"):
            yield event.plain_result(limited)
            return
        yield event.plain_result("⏳ 流式执行中...")
        chunks = await executor.exec_code(code, event, kernel="ipython", stream=True)
        output_parts: list[str] = []
        async for chunk in chunks:
            output_parts.append(str(chunk))
        result = "".join(output_parts) if output_parts else "(无输出)"
        yield self._plain_result_with_audit(
            event,
            command="sandbox",
            action="stream",
            result_text=result,
        )

    async def sandbox_files(self, event: Any, path: str = ".") -> AsyncIterator[Any]:
        """处理 `/sandbox files [路径]`。"""

        path = path.strip() or "."
        executor = self._require_component(self.runtime.executor, "executor")
        if limited := self._check_rate_limit(event, "sandbox", "sandbox", "files", target=path):
            yield event.plain_result(limited)
            return
        result = await executor.list_files(path, event)
        yield self._plain_result_with_audit(
            event,
            command="sandbox",
            action="files",
            result_text=result,
            target=path,
        )

    async def sandbox_upload(self, event: Any, path: str, content: str) -> AsyncIterator[Any]:
        """处理 `/sandbox upload <路径> <内容>`。"""

        path = path.strip()
        if not path or not content:
            yield event.plain_result("用法: `/sandbox upload <文件路径> <内容>`")
            return
        executor = self._require_component(self.runtime.executor, "executor")
        if limited := self._check_rate_limit(event, "sandbox", "sandbox", "upload", target=path):
            yield event.plain_result(limited)
            return
        result = await executor.write_file(path, content, event)
        yield self._plain_result_with_audit(
            event,
            command="sandbox",
            action="upload",
            result_text=result,
            target=path,
        )

    async def sandbox_download(self, event: Any, path: str) -> AsyncIterator[Any]:
        """处理 `/sandbox download <路径>`。"""

        path = path.strip()
        if not path:
            yield event.plain_result("请提供文件路径")
            return
        executor = self._require_component(self.runtime.executor, "executor")
        if limited := self._check_rate_limit(event, "sandbox", "sandbox", "download", target=path):
            yield event.plain_result(limited)
            return
        result = await executor.read_file(path, event)
        yield self._plain_result_with_audit(
            event,
            command="sandbox",
            action="download",
            result_text=result,
            target=path,
        )

    async def sandbox_install(self, event: Any, packages: str) -> AsyncIterator[Any]:
        """处理 `/sandbox install <包名>`。"""

        packages = packages.strip()
        if not packages:
            yield event.plain_result("请提供要安装的包名")
            return
        executor = self._require_component(self.runtime.executor, "executor")
        if limited := self._check_rate_limit(event, "sandbox", "sandbox", "install"):
            yield event.plain_result(limited)
            return
        yield event.plain_result(f"📦 正在安装: {packages}...")
        result = await executor.install_packages(packages.split(), event)
        yield self._plain_result_with_audit(
            event,
            command="sandbox",
            action="install",
            result_text=f"📦 {result}",
            target=packages,
        )

    async def sandbox_packages(self, event: Any) -> AsyncIterator[Any]:
        """处理 `/sandbox packages`。"""

        if limited := self._check_rate_limit(event, "sandbox", "sandbox", "packages"):
            yield event.plain_result(limited)
            return
        result = await self._render_package_list(event)
        yield self._plain_result_with_audit(
            event,
            command="sandbox",
            action="packages",
            result_text=result,
        )

    async def sandbox_variables(self, event: Any) -> AsyncIterator[Any]:
        """处理 `/sandbox variables`。"""

        if limited := self._check_rate_limit(event, "sandbox", "sandbox", "variables"):
            yield event.plain_result(limited)
            return
        result = await self._render_variable_list(event)
        yield self._plain_result_with_audit(
            event,
            command="sandbox",
            action="variables",
            result_text=result,
        )

    async def sandbox_restart(self, event: Any) -> AsyncIterator[Any]:
        """处理 `/sandbox restart`。"""

        executor = self._require_component(self.runtime.executor, "executor")
        if limited := self._check_rate_limit(event, "sandbox", "sandbox", "restart"):
            yield event.plain_result(limited)
            return
        result = await executor.restart_sandbox(event)
        yield self._plain_result_with_audit(
            event,
            command="sandbox",
            action="restart",
            result_text=result,
        )

    async def sandbox_url(self, event: Any, url: str, save_path: str) -> AsyncIterator[Any]:
        """处理 `/sandbox url <URL> <保存路径>`。"""

        url, save_path = url.strip(), save_path.strip()
        if not url or not save_path:
            yield event.plain_result("用法: `/sandbox url <URL> <保存路径>`")
            return
        executor = self._require_component(self.runtime.executor, "executor")
        if limited := self._check_rate_limit(event, "sandbox", "sandbox", "url", target=save_path):
            yield event.plain_result(limited)
            return
        yield event.plain_result(f"⬇️ 正在下载: {url}...")
        try:
            sandbox_file = await executor.download_from_url(url, save_path, event)
            yield self._plain_result_with_audit(
                event,
                command="sandbox",
                action="url",
                result_text=f"✅ 文件已下载: `{sandbox_file.path}` ({sandbox_file.size_human})",
                target=save_path,
            )
        except Exception as exc:
            yield self._plain_result_with_audit(
                event,
                command="sandbox",
                action="url",
                result_text=f"❌ 下载失败: {str(exc)}",
                target=save_path,
            )

    # ------------------------------------------------------------------
    # 渲染与帮助
    # ------------------------------------------------------------------
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

        return """🤖 **全自主智能体编排器 v4.0.0**

基于 AstrBot 官方 Agent 体系（tool_loop_agent + FunctionTool + 子代理 Handoff）。

**核心能力：**
• 🔍 搜索并安装插件
• ✍️ 创建和编辑 Skill
• 🔌 配置 MCP 服务
• 🐛 自动诊断和修复问题
• 🖥️ local/sandbox 代码执行

**常用命令：**
• `/agent <任务>` - 全自主执行任务
• `/agent status` - 查看子代理 Handoff 状态
• `/agent templates` - 查看预设子代理模板
• `/agent sync` - 注册预设子代理（管理员）
• `/plugin search|install|list|remove|update|proxy` - 插件管理
• `/skill list|create|read|delete` - Skill 管理
• `/mcp list|add|remove|test|tools` - MCP 配置
• `/exec run|local|sandbox|python|config` - 快速执行代码
• `/sandbox ...` - 沙盒管理
• `/debug status|logs|analyze` - 诊断问题

**示例：**
• `/agent 帮我找一个翻译插件并安装`
• `/agent 写一个查询天气的 Skill`
• `/sandbox exec import sys; print(sys.version)`

💡 普通聊天中也可直接让默认助手调用本插件注册的工具完成上述操作。
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
        return str(provider_id)

    # ------------------------------------------------------------------
    # 审计与限流
    # ------------------------------------------------------------------
    def _plain_result_with_audit(
        self,
        event: Any,
        *,
        command: str,
        action: str,
        result_text: str,
        target: str | None = None,
        detail: str | None = None,
    ) -> Any:
        """记录审计结果后构造返回消息。"""

        self._record_command_result(
            event,
            command=command,
            action=action,
            result_text=result_text,
            target=target,
            detail=detail,
        )
        return event.plain_result(result_text)

    def _record_command_result(
        self,
        event: Any,
        *,
        command: str,
        action: str,
        result_text: str,
        target: str | None = None,
        detail: str | None = None,
    ) -> None:
        """根据返回结果分类记录审计事件。"""

        if result_text.startswith("❌"):
            outcome = "error"
        elif result_text.startswith("⚠️"):
            outcome = "warning"
        else:
            outcome = "success"

        self._audit_security_event(
            event,
            command=command,
            action=action,
            outcome=outcome,
            target=target,
            detail=detail,
        )

    def _check_rate_limit(
        self,
        event: Any,
        scope: str,
        command: str,
        action: str,
        target: str | None = None,
    ) -> str | None:
        """按 sender 维度执行固定窗口限流。"""

        rule = _RATE_LIMIT_RULES[scope]
        actor_id = self._get_actor_id(event)
        key = f"{scope}:{actor_id}"
        if self.rate_limiter.allow(key, limit=rule.limit, window_seconds=rule.window_seconds):
            return None

        self._audit_security_event(
            event,
            command=command,
            action=action,
            outcome="rate_limited",
            target=target,
            detail=f"{rule.limit}/{int(rule.window_seconds)}s",
        )
        return rule.message

    def _audit_security_event(
        self,
        event: Any,
        *,
        command: str,
        action: str,
        outcome: str,
        target: str | None = None,
        detail: str | None = None,
    ) -> None:
        """写入结构化安全审计日志。"""

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": command,
            "action": action,
            "outcome": outcome,
            "actor_id": self._get_actor_id(event),
            "role": self._sanitize_audit_value(getattr(event, "role", "")),
            "session_id": self._sanitize_audit_value(getattr(event, "session_id", "")),
            "message_origin": self._sanitize_audit_value(getattr(event, "unified_msg_origin", "")),
            "target": self._sanitize_audit_value(target),
            "detail": self._sanitize_audit_value(detail),
        }
        serialized = json.dumps(record, ensure_ascii=False, sort_keys=True)

        log_path = self._get_audit_log_path()
        if log_path:
            try:
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
                with open(log_path, "a", encoding="utf-8") as handle:
                    handle.write(serialized + "\n")
            except OSError as exc:
                logger.warning("写入安全审计日志失败: %s", exc)

        log_method = (
            audit_logger.warning
            if outcome in {"denied", "error", "rate_limited"}
            else audit_logger.info
        )
        log_method("security_audit %s", serialized)

    def _get_audit_log_path(self) -> str | None:
        """解析安全审计日志落盘路径（data/plugin_data/astrbot_orchestrator_v5/）。"""

        try:
            data_dir = get_plugin_data_dir()
        except Exception as exc:
            logger.debug("获取插件数据目录失败，跳过审计日志落盘: %s", exc)
            return None
        return os.path.join(str(data_dir), "security_audit.jsonl")

    @staticmethod
    def _sanitize_audit_value(value: Any) -> str | None:
        """限制审计字段长度并移除换行。"""

        if value is None:
            return None

        text = str(value).replace("\r", " ").replace("\n", " ").strip()
        if not text:
            return None
        if len(text) > _AUDIT_VALUE_LIMIT:
            return text[:_AUDIT_VALUE_LIMIT] + "..."
        return text

    @staticmethod
    def _get_actor_id(event: Any) -> str:
        """优先按 sender_id 记录 actor。"""

        get_sender_id = getattr(event, "get_sender_id", None)
        if callable(get_sender_id):
            try:
                resolved_sender_id = get_sender_id()
            except Exception:
                resolved_sender_id = None
            if resolved_sender_id:
                return str(resolved_sender_id)

        for attr in ("session_id", "unified_msg_origin"):
            value = getattr(event, attr, None)
            if value:
                return str(value)

        return "unknown"

    @staticmethod
    def _require_component(component: TComponent | None, name: str) -> TComponent:
        """确保运行时组件已就绪。"""

        if component is None:
            raise RuntimeError(f"运行时组件未初始化: {name}")
        return component
