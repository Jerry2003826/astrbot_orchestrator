"""命令处理层测试。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from astrbot_orchestrator_v5.entrypoints.command_handlers import CommandHandlers
from astrbot_orchestrator_v5.sandbox.types import ExecChunk, ExecResult, SandboxFile

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture
    from _pytest.fixtures import FixtureRequest
    from _pytest.logging import LogCaptureFixture
    from _pytest.monkeypatch import MonkeyPatch
    from pytest_mock.plugin import MockerFixture

    from tests.conftest import FakeContext, FakeEvent

    _PYTEST_TYPE_IMPORTS = (
        CaptureFixture,
        FixtureRequest,
        LogCaptureFixture,
        MonkeyPatch,
        MockerFixture,
    )


class FakeExecutor:
    """命令处理层测试用执行器替身。"""

    def __init__(self) -> None:
        """初始化记录容器。"""

        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.download_error: Exception | None = None
        self.list_packages_error: Exception | None = None
        self.show_variables_error: Exception | None = None
        self.health_result = "sandbox-health"
        self.read_result = "downloaded-content"
        self.write_result = "✅ 已创建"
        self.install_result = "installed ok"
        self.restart_result = "sandbox restarted"
        self.packages: list[str] = ["requests", "numpy"]
        self.variables: dict[str, Any] = {"token": "'abc'"}

    def get_current_mode_info(self) -> str:
        """返回固定模式信息。"""

        self.calls.append(("get_current_mode_info", (), {}))
        return "mode-info"

    async def execute(self, command: str, event: Any) -> str:
        """记录默认执行调用。"""

        self.calls.append(("execute", (command, event), {}))
        return "default-exec"

    async def execute_local(self, command: str, event: Any) -> str:
        """记录本地执行调用。"""

        self.calls.append(("execute_local", (command, event), {}))
        return "local-exec"

    async def execute_sandbox(self, command: str, event: Any) -> str:
        """记录沙盒执行调用。"""

        self.calls.append(("execute_sandbox", (command, event), {}))
        return "sandbox-exec"

    async def execute_python(self, command: str, event: Any) -> str:
        """记录 Python 执行调用。"""

        self.calls.append(("execute_python", (command, event), {}))
        return "python-exec"

    async def exec_code(
        self,
        code: str,
        event: Any,
        kernel: str = "ipython",
        stream: bool = False,
    ) -> Any:
        """返回普通或流式执行结果。"""

        self.calls.append(("exec_code", (code, event), {"kernel": kernel, "stream": stream}))
        if stream:

            async def _generator():
                yield ExecChunk(type="stdout", content="part-1")
                yield ExecChunk(type="stdout", content="part-2")

            return _generator()
        return ExecResult(text="hello", exit_code=0, kernel=kernel)

    async def healthcheck(self, event: Any) -> str:
        """记录沙盒健康检查调用。"""

        self.calls.append(("healthcheck", (event,), {}))
        return self.health_result

    async def list_files(self, path: str, event: Any) -> str:
        """记录文件列表调用。"""

        self.calls.append(("list_files", (path, event), {}))
        return f"files:{path}"

    async def write_file(self, file_path: str, content: str, event: Any) -> str:
        """记录文件写入调用。"""

        self.calls.append(("write_file", (file_path, content, event), {}))
        return self.write_result

    async def read_file(self, file_path: str, event: Any) -> str:
        """记录文件读取调用。"""

        self.calls.append(("read_file", (file_path, event), {}))
        return self.read_result

    async def install_packages(self, packages: list[str], event: Any) -> str:
        """记录安装包调用。"""

        self.calls.append(("install_packages", (packages, event), {}))
        return self.install_result

    async def list_packages(self, event: Any) -> list[str]:
        """记录查询包列表调用。"""

        self.calls.append(("list_packages", (event,), {}))
        if self.list_packages_error is not None:
            raise self.list_packages_error
        return list(self.packages)

    async def show_variables(self, event: Any) -> dict[str, Any]:
        """记录查询变量调用。"""

        self.calls.append(("show_variables", (event,), {}))
        if self.show_variables_error is not None:
            raise self.show_variables_error
        return dict(self.variables)

    async def restart_sandbox(self, event: Any) -> str:
        """记录重启沙盒调用。"""

        self.calls.append(("restart_sandbox", (event,), {}))
        return self.restart_result

    async def download_from_url(self, url: str, file_path: str, event: Any) -> SandboxFile:
        """记录 URL 下载调用。"""

        self.calls.append(("download_from_url", (url, file_path, event), {}))
        if self.download_error is not None:
            raise self.download_error
        return SandboxFile(path=file_path, size=3)


class FakeChatContext:
    """返回固定 provider_id 的上下文替身。"""

    def __init__(self, provider_id: str = "provider-x") -> None:
        """保存 provider_id 与调用记录。"""

        self.provider_id = provider_id
        self.calls: list[str] = []

    async def get_current_chat_provider_id(self, umo: str) -> str:
        """根据消息来源返回固定 provider_id。"""

        self.calls.append(umo)
        return self.provider_id


class FakeOrchestrator:
    """记录请求上下文的编排器替身。"""

    def __init__(
        self,
        result: dict[str, str] | None = None,
        error: Exception | None = None,
    ) -> None:
        """保存返回值或异常。"""

        self.result = result or {"answer": "agent-ok"}
        self.error = error
        self.calls: list[Any] = []

    async def process_request(self, request_context: Any) -> dict[str, str]:
        """记录请求并返回预设结果。"""

        self.calls.append(request_context)
        if self.error is not None:
            raise self.error
        return dict(self.result)


class FakeMetaOrchestrator:
    """返回固定状态文本的 SubAgent 编排器替身。"""

    def status(self) -> str:
        """返回固定状态。"""

        return "subagent-status"


class FakeDynamicAgentManager:
    """返回固定模板配置的动态代理管理器替身。"""

    def get_template_config(self) -> dict[str, dict[str, str]]:
        """返回模板配置。"""

        return {"review": {"name": "review_agent", "system_prompt": "审查代码"}}


class FakeDebugger:
    """调试器替身。"""

    def __init__(self) -> None:
        """初始化记录。"""

        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def get_system_status(self) -> str:
        """返回系统状态。"""

        self.calls.append(("get_system_status", (), {}))
        return "debug-status"

    def get_recent_errors(self) -> str:
        """返回最近错误。"""

        self.calls.append(("get_recent_errors", (), {}))
        return "recent-errors"

    async def analyze_problem(self, problem: str, provider_id: str) -> str:
        """返回问题分析结果。"""

        self.calls.append(("analyze_problem", (problem, provider_id), {}))
        return f"analysis:{problem}:{provider_id}"

    async def analyze_error(
        self,
        error: Exception,
        traceback_info: str,
        context: dict[str, Any],
    ) -> str:
        """返回异常分析结果。"""

        self.calls.append(
            (
                "analyze_error",
                (str(error), traceback_info),
                {"context": dict(context)},
            )
        )
        return "debug-analysis"


class FailingDebugger(FakeDebugger):
    """自动诊断失败的调试器替身。"""

    async def analyze_error(
        self,
        error: Exception,
        traceback_info: str,
        context: dict[str, Any],
    ) -> str:
        """抛出诊断异常，覆盖普通错误回退分支。"""

        del error, traceback_info, context
        raise RuntimeError("debug failed")


class FakePluginTool:
    """插件工具替身。"""

    async def search_plugins(self, keyword: str) -> str:
        """返回搜索结果。"""

        return f"search:{keyword}"

    async def install_plugin(self, url: str) -> str:
        """返回安装结果。"""

        return f"install:{url}"

    async def list_plugins(self) -> str:
        """返回插件列表。"""

        return "plugin-list"

    async def remove_plugin(self, name: str) -> str:
        """返回卸载结果。"""

        return f"remove:{name}"

    async def update_plugin(self, name: str) -> str:
        """返回更新结果。"""

        return f"update:{name}"

    def get_available_proxies(self) -> str:
        """返回代理列表。"""

        return "proxy-list"


class FakeSkillTool:
    """Skill 工具替身。"""

    def list_skills(self) -> str:
        """返回 Skill 列表。"""

        return "skill-list"

    def read_skill(self, name: str) -> str:
        """返回 Skill 内容。"""

        return f"skill:{name}"

    def delete_skill(self, name: str) -> str:
        """返回删除结果。"""

        return f"delete-skill:{name}"


class FakeMcpTool:
    """MCP 工具替身。"""

    def list_servers(self) -> str:
        """返回 MCP 服务列表。"""

        return "mcp-list"

    async def add_server(self, name: str, url: str) -> str:
        """返回添加结果。"""

        return f"add:{name}:{url}"

    async def remove_server(self, name: str) -> str:
        """返回移除结果。"""

        return f"remove:{name}"

    async def test_server(self, name: str) -> str:
        """返回测试结果。"""

        return f"test:{name}"

    def list_tools(self, name: str) -> str:
        """返回工具列表。"""

        return f"tools:{name}"


async def collect_results(stream: AsyncIterator[Any]) -> list[Any]:
    """收集异步生成器中的所有结果。"""

    return [item async for item in stream]


@pytest.mark.asyncio
async def test_command_handlers_agent_returns_help_for_empty_request(
    fake_context: "FakeContext",
    fake_event: "FakeEvent",
) -> None:
    """空请求应返回 `/agent` 帮助文本。"""

    handlers = CommandHandlers(
        context=fake_context,
        runtime=SimpleNamespace(meta_orchestrator=None, dynamic_agent_manager=None, debugger=None),
        build_request_context=lambda *_args: None,
    )
    fake_event.message_str = ""

    results = [item async for item in handlers.handle_agent(fake_event)]

    assert len(results) == 1
    assert "全自主智能体编排器" in results[0]


@pytest.mark.asyncio
async def test_command_handlers_plugin_install_requires_admin(
    fake_context: "FakeContext",
    fake_event: "FakeEvent",
) -> None:
    """非管理员安装插件请求应被拒绝。"""

    handlers = CommandHandlers(
        context=fake_context,
        runtime=SimpleNamespace(plugin_tool=SimpleNamespace()),
        build_request_context=lambda *_args: None,
    )
    fake_event.message_str = "install https://example.com/repo"
    fake_event.role = "member"

    results = [item async for item in handlers.handle_plugin(fake_event)]

    assert results == ["❌ 只有管理员可以安装插件"]


@pytest.mark.asyncio
async def test_command_handlers_exec_config_returns_mode_info(
    fake_context: "FakeContext",
    fake_event: "FakeEvent",
) -> None:
    """`/exec config` 应返回执行环境信息。"""

    executor = FakeExecutor()
    handlers = CommandHandlers(
        context=fake_context,
        runtime=SimpleNamespace(executor=executor),
        build_request_context=lambda *_args: None,
    )
    fake_event.message_str = "config"
    fake_event.role = "admin"

    results = [item async for item in handlers.handle_exec(fake_event)]

    assert results == ["mode-info"]
    assert executor.calls == [("get_current_mode_info", (), {})]


@pytest.mark.asyncio
async def test_command_handlers_exec_local_delegates_to_executor(
    fake_context: "FakeContext",
    fake_event: "FakeEvent",
) -> None:
    """`/exec local` 应调用本地执行分支。"""

    executor = FakeExecutor()
    handlers = CommandHandlers(
        context=fake_context,
        runtime=SimpleNamespace(executor=executor),
        build_request_context=lambda *_args: None,
    )
    fake_event.message_str = "local ls -la"
    fake_event.role = "admin"

    results = [item async for item in handlers.handle_exec(fake_event)]

    assert results == ["local-exec"]
    assert executor.calls == [("execute_local", ("ls -la", fake_event), {})]


@pytest.mark.asyncio
async def test_command_handlers_exec_default_mode_delegates_to_execute(
    fake_context: "FakeContext",
    fake_event: "FakeEvent",
) -> None:
    """未知 `/exec` 模式应回退到默认 execute 分支。"""

    executor = FakeExecutor()
    handlers = CommandHandlers(
        context=fake_context,
        runtime=SimpleNamespace(executor=executor),
        build_request_context=lambda *_args: None,
    )
    fake_event.message_str = "ls -la"
    fake_event.role = "admin"

    results = [item async for item in handlers.handle_exec(fake_event)]

    assert results == ["default-exec"]
    assert executor.calls == [("execute", ("ls -la", fake_event), {})]


@pytest.mark.asyncio
async def test_command_handlers_sandbox_stream_joins_chunk_output(
    fake_context: "FakeContext",
    fake_event: "FakeEvent",
) -> None:
    """`/sandbox stream` 应拼接所有流式输出片段。"""

    executor = FakeExecutor()
    handlers = CommandHandlers(
        context=fake_context,
        runtime=SimpleNamespace(executor=executor),
        build_request_context=lambda *_args: None,
    )
    fake_event.message_str = "stream print('ok')"
    fake_event.role = "admin"

    results = [item async for item in handlers.handle_sandbox(fake_event)]

    assert results == ["⏳ 流式执行中...", "part-1part-2"]
    assert executor.calls == [
        ("exec_code", ("print('ok')", fake_event), {"kernel": "ipython", "stream": True})
    ]


@pytest.mark.asyncio
async def test_command_handlers_sandbox_url_reports_downloaded_file(
    fake_context: "FakeContext",
    fake_event: "FakeEvent",
) -> None:
    """`/sandbox url` 成功时应返回文件下载结果。"""

    executor = FakeExecutor()
    handlers = CommandHandlers(
        context=fake_context,
        runtime=SimpleNamespace(executor=executor),
        build_request_context=lambda *_args: None,
    )
    fake_event.message_str = "url https://example.com/logo.png assets/logo.png"
    fake_event.role = "admin"

    results = [item async for item in handlers.handle_sandbox(fake_event)]

    assert results == [
        "⬇️ 正在下载: https://example.com/logo.png...",
        "✅ 文件已下载: `assets/logo.png` (3.0 B)",
    ]
    assert executor.calls == [
        (
            "download_from_url",
            ("https://example.com/logo.png", "assets/logo.png", fake_event),
            {},
        )
    ]


@pytest.mark.asyncio
async def test_command_handlers_agent_status_returns_meta_orchestrator_status(
    fake_event: "FakeEvent",
) -> None:
    """`/agent status` 应直接返回 SubAgent 状态。"""

    handlers = CommandHandlers(
        context=FakeChatContext(),
        runtime=SimpleNamespace(
            meta_orchestrator=FakeMetaOrchestrator(),
            dynamic_agent_manager=None,
            debugger=None,
        ),
        build_request_context=lambda *_args: None,
    )
    fake_event.message_str = "status"

    results = await collect_results(handlers.handle_agent(fake_event))

    assert results == ["subagent-status"]


@pytest.mark.asyncio
async def test_command_handlers_agent_templates_returns_template_config(
    fake_event: "FakeEvent",
) -> None:
    """`/agent templates` 应返回模板 JSON 文本。"""

    handlers = CommandHandlers(
        context=FakeChatContext(),
        runtime=SimpleNamespace(
            meta_orchestrator=None,
            dynamic_agent_manager=FakeDynamicAgentManager(),
            debugger=None,
        ),
        build_request_context=lambda *_args: None,
    )
    fake_event.message_str = "templates"

    results = await collect_results(handlers.handle_agent(fake_event))

    assert len(results) == 1
    assert "SubAgent 默认模板配置" in results[0]
    assert '"review"' in results[0]
    assert "subagent_template_overrides" in results[0]


@pytest.mark.asyncio
async def test_command_handlers_agent_status_and_templates_report_missing_components(
    fake_event: "FakeEvent",
) -> None:
    """状态与模板命令在组件缺失时应返回明确错误。"""

    handlers = CommandHandlers(
        context=FakeChatContext(),
        runtime=SimpleNamespace(meta_orchestrator=None, dynamic_agent_manager=None, debugger=None),
        build_request_context=lambda *_args: None,
    )

    fake_event.message_str = "status"
    assert await collect_results(handlers.handle_agent(fake_event)) == [
        "❌ SubAgent 编排器未初始化"
    ]

    fake_event.message_str = "templates"
    assert await collect_results(handlers.handle_agent(fake_event)) == ["❌ SubAgent 模板未初始化"]


@pytest.mark.asyncio
async def test_command_handlers_agent_builds_request_context_and_returns_answer(
    fake_event: "FakeEvent",
) -> None:
    """正常 agent 请求应解析 provider 并返回执行结果。"""

    context = FakeChatContext(provider_id="provider-y")
    orchestrator = FakeOrchestrator(result={"answer": "agent-success"})
    build_calls: list[tuple[Any, str, str, str]] = []

    def build_request_context(
        event: Any, request: str, provider_id: str, source: str
    ) -> dict[str, Any]:
        """记录请求上下文构建参数。"""

        build_calls.append((event, request, provider_id, source))
        return {"request": request, "provider_id": provider_id, "source": source}

    handlers = CommandHandlers(
        context=context,
        runtime=SimpleNamespace(orchestrator=orchestrator, debugger=None),
        build_request_context=build_request_context,
    )
    fake_event.message_str = "帮我写一个示例"

    results = await collect_results(handlers.handle_agent(fake_event))

    assert results == ["🤖 正在分析任务，请稍候...", "agent-success"]
    assert context.calls == [fake_event.unified_msg_origin]
    assert build_calls == [(fake_event, "帮我写一个示例", "provider-y", "agent")]
    assert orchestrator.calls == [
        {"request": "帮我写一个示例", "provider_id": "provider-y", "source": "agent"}
    ]


@pytest.mark.asyncio
async def test_command_handlers_agent_error_uses_debugger_analysis(
    fake_event: "FakeEvent",
) -> None:
    """agent 执行报错时应回退到自动诊断文本。"""

    handlers = CommandHandlers(
        context=FakeChatContext(),
        runtime=SimpleNamespace(
            orchestrator=FakeOrchestrator(error=RuntimeError("boom")),
            debugger=FakeDebugger(),
        ),
        build_request_context=lambda *_args: {"request": "ctx"},
    )
    fake_event.message_str = "触发异常"

    results = await collect_results(handlers.handle_agent(fake_event))

    assert results[0] == "🤖 正在分析任务，请稍候..."
    assert "❌ 执行出错: boom" in results[1]
    assert "🔍 自动分析" in results[1]
    assert "debug-analysis" in results[1]


@pytest.mark.asyncio
async def test_command_handlers_agent_error_falls_back_when_debugger_fails(
    fake_event: "FakeEvent",
) -> None:
    """自动诊断失败时应回退到普通错误文本。"""

    handlers = CommandHandlers(
        context=FakeChatContext(),
        runtime=SimpleNamespace(
            orchestrator=FakeOrchestrator(error=RuntimeError("boom")),
            debugger=FailingDebugger(),
        ),
        build_request_context=lambda *_args: {"request": "ctx"},
    )
    fake_event.message_str = "触发异常"

    results = await collect_results(handlers.handle_agent(fake_event))

    assert results == ["🤖 正在分析任务，请稍候...", "❌ 执行出错: boom"]


@pytest.mark.asyncio
async def test_command_handlers_agent_error_falls_back_without_debugger(
    fake_event: "FakeEvent",
) -> None:
    """缺少 debugger 时应直接返回普通错误文本。"""

    handlers = CommandHandlers(
        context=FakeChatContext(),
        runtime=SimpleNamespace(
            orchestrator=FakeOrchestrator(error=RuntimeError("boom")),
            debugger=None,
        ),
        build_request_context=lambda *_args: {"request": "ctx"},
    )
    fake_event.message_str = "触发异常"

    results = await collect_results(handlers.handle_agent(fake_event))

    assert results == ["🤖 正在分析任务，请稍候...", "❌ 执行出错: boom"]


@pytest.mark.asyncio
async def test_command_handlers_plugin_routes_multiple_actions(
    fake_event: "FakeEvent",
) -> None:
    """`/plugin` 应覆盖搜索、列表、代理、更新和无效命令分支。"""

    handlers = CommandHandlers(
        context=FakeChatContext(),
        runtime=SimpleNamespace(plugin_tool=FakePluginTool()),
        build_request_context=lambda *_args: None,
    )
    fake_event.role = "admin"

    cases = [
        ("search weather", ["🔍 正在搜索插件: weather...", "search:weather"]),
        ("list", ["plugin-list"]),
        ("proxy", ["proxy-list"]),
        ("update demo-plugin", ["🔄 正在更新插件: demo-plugin...", "update:demo-plugin"]),
        ("oops", ["无效命令，请使用 /plugin 查看帮助"]),
    ]

    for message, expected in cases:
        fake_event.message_str = message
        assert await collect_results(handlers.handle_plugin(fake_event)) == expected


@pytest.mark.asyncio
async def test_command_handlers_plugin_covers_help_install_remove_and_update_denials(
    fake_event: "FakeEvent",
) -> None:
    """`/plugin` 应覆盖帮助、安装、卸载与非管理员更新拒绝。"""

    handlers = CommandHandlers(
        context=FakeChatContext(),
        runtime=SimpleNamespace(plugin_tool=FakePluginTool()),
        build_request_context=lambda *_args: None,
    )

    fake_event.message_str = ""
    help_results = await collect_results(handlers.handle_plugin(fake_event))
    assert len(help_results) == 1
    assert "插件管理" in help_results[0]

    fake_event.role = "admin"
    fake_event.message_str = "install https://example.com/repo"
    assert await collect_results(handlers.handle_plugin(fake_event)) == [
        "📥 正在安装插件: https://example.com/repo...\n💡 使用 AstrBot 配置的 GitHub 加速",
        "install:https://example.com/repo",
    ]

    fake_event.role = "member"
    fake_event.message_str = "remove demo-plugin"
    assert await collect_results(handlers.handle_plugin(fake_event)) == [
        "❌ 只有管理员可以卸载插件"
    ]

    fake_event.role = "admin"
    assert await collect_results(handlers.handle_plugin(fake_event)) == ["remove:demo-plugin"]

    fake_event.role = "member"
    fake_event.message_str = "update demo-plugin"
    assert await collect_results(handlers.handle_plugin(fake_event)) == [
        "❌ 只有管理员可以更新插件"
    ]


@pytest.mark.asyncio
async def test_command_handlers_skill_routes_multiple_actions(
    fake_event: "FakeEvent",
) -> None:
    """`/skill` 应覆盖列表、创建、读取、删除和拒绝分支。"""

    handlers = CommandHandlers(
        context=FakeChatContext(),
        runtime=SimpleNamespace(skill_tool=FakeSkillTool()),
        build_request_context=lambda *_args: None,
    )

    fake_event.message_str = "list"
    assert await collect_results(handlers.handle_skill(fake_event)) == ["skill-list"]

    fake_event.message_str = "create weather"
    create_results = await collect_results(handlers.handle_skill(fake_event))
    assert len(create_results) == 1
    assert "准备创建 Skill: weather" in create_results[0]

    fake_event.message_str = "read weather"
    assert await collect_results(handlers.handle_skill(fake_event)) == ["skill:weather"]

    fake_event.message_str = "delete weather"
    fake_event.role = "member"
    assert await collect_results(handlers.handle_skill(fake_event)) == [
        "❌ 只有管理员可以删除 Skill"
    ]

    fake_event.role = "admin"
    assert await collect_results(handlers.handle_skill(fake_event)) == ["delete-skill:weather"]


@pytest.mark.asyncio
async def test_command_handlers_skill_covers_help_missing_name_and_invalid_action(
    fake_event: "FakeEvent",
) -> None:
    """`/skill` 应覆盖帮助、缺少名称和无效命令分支。"""

    handlers = CommandHandlers(
        context=FakeChatContext(),
        runtime=SimpleNamespace(skill_tool=FakeSkillTool()),
        build_request_context=lambda *_args: None,
    )

    fake_event.message_str = ""
    help_results = await collect_results(handlers.handle_skill(fake_event))
    assert len(help_results) == 1
    assert "Skill 管理" in help_results[0]

    fake_event.message_str = "create"
    assert await collect_results(handlers.handle_skill(fake_event)) == ["请提供 Skill 名称"]

    fake_event.message_str = "oops"
    assert await collect_results(handlers.handle_skill(fake_event)) == [
        "无效命令，请使用 /skill 查看帮助"
    ]


@pytest.mark.asyncio
async def test_command_handlers_mcp_routes_multiple_actions(
    fake_event: "FakeEvent",
) -> None:
    """`/mcp` 应覆盖列表、添加、测试、工具和无效命令分支。"""

    handlers = CommandHandlers(
        context=FakeChatContext(),
        runtime=SimpleNamespace(mcp_tool=FakeMcpTool()),
        build_request_context=lambda *_args: None,
    )

    fake_event.message_str = "list"
    assert await collect_results(handlers.handle_mcp(fake_event)) == ["mcp-list"]

    fake_event.message_str = "add search https://example.com/mcp"
    fake_event.role = "member"
    assert await collect_results(handlers.handle_mcp(fake_event)) == ["❌ 只有管理员可以添加 MCP"]

    fake_event.role = "admin"
    assert await collect_results(handlers.handle_mcp(fake_event)) == [
        "add:search:https://example.com/mcp"
    ]

    fake_event.message_str = "test search"
    assert await collect_results(handlers.handle_mcp(fake_event)) == ["test:search"]

    fake_event.message_str = "tools search"
    assert await collect_results(handlers.handle_mcp(fake_event)) == ["tools:search"]

    fake_event.message_str = "unknown"
    assert await collect_results(handlers.handle_mcp(fake_event)) == [
        "无效命令，请使用 /mcp 查看帮助"
    ]


@pytest.mark.asyncio
async def test_command_handlers_mcp_covers_help_and_remove_permissions(
    fake_event: "FakeEvent",
) -> None:
    """`/mcp` 应覆盖帮助、移除拒绝和移除成功分支。"""

    handlers = CommandHandlers(
        context=FakeChatContext(),
        runtime=SimpleNamespace(mcp_tool=FakeMcpTool()),
        build_request_context=lambda *_args: None,
    )

    fake_event.message_str = ""
    help_results = await collect_results(handlers.handle_mcp(fake_event))
    assert len(help_results) == 1
    assert "MCP 配置管理" in help_results[0]

    fake_event.role = "member"
    fake_event.message_str = "remove search"
    assert await collect_results(handlers.handle_mcp(fake_event)) == ["❌ 只有管理员可以移除 MCP"]

    fake_event.role = "admin"
    assert await collect_results(handlers.handle_mcp(fake_event)) == ["remove:search"]


@pytest.mark.asyncio
async def test_command_handlers_exec_covers_help_permissions_and_modes(
    fake_event: "FakeEvent",
) -> None:
    """`/exec` 应覆盖帮助、权限校验、缺参和 sandbox/python 分支。"""

    executor = FakeExecutor()
    handlers = CommandHandlers(
        context=FakeChatContext(),
        runtime=SimpleNamespace(executor=executor),
        build_request_context=lambda *_args: None,
    )

    fake_event.message_str = ""
    fake_event.role = "admin"
    help_results = await collect_results(handlers.handle_exec(fake_event))
    assert len(help_results) == 1
    assert "代码执行" in help_results[0]

    fake_event.message_str = "sandbox print('x')"
    fake_event.role = "member"
    assert await collect_results(handlers.handle_exec(fake_event)) == ["❌ 只有管理员可以执行代码"]

    fake_event.role = "admin"
    fake_event.message_str = "sandbox"
    assert await collect_results(handlers.handle_exec(fake_event)) == ["请提供要执行的代码或命令"]

    fake_event.message_str = "sandbox ls"
    assert await collect_results(handlers.handle_exec(fake_event)) == ["sandbox-exec"]

    fake_event.message_str = "python print('ok')"
    assert await collect_results(handlers.handle_exec(fake_event)) == ["python-exec"]


@pytest.mark.asyncio
async def test_command_handlers_debug_routes_status_logs_analyze_and_help(
    fake_event: "FakeEvent",
) -> None:
    """`/debug` 应覆盖状态、日志、分析与帮助分支。"""

    handlers = CommandHandlers(
        context=FakeChatContext(provider_id="provider-z"),
        runtime=SimpleNamespace(debugger=FakeDebugger()),
        build_request_context=lambda *_args: None,
    )

    fake_event.message_str = "status"
    assert await collect_results(handlers.handle_debug(fake_event)) == ["debug-status"]

    fake_event.message_str = "logs"
    assert await collect_results(handlers.handle_debug(fake_event)) == ["recent-errors"]

    fake_event.message_str = "analyze 网络超时"
    assert await collect_results(handlers.handle_debug(fake_event)) == [
        "analysis:网络超时:provider-z"
    ]

    fake_event.message_str = "oops"
    help_results = await collect_results(handlers.handle_debug(fake_event))
    assert len(help_results) == 1
    assert "Debug 工具" in help_results[0]


@pytest.mark.asyncio
async def test_command_handlers_sandbox_exec_and_bash_use_formatter(
    fake_event: "FakeEvent",
) -> None:
    """`/sandbox exec` 和 `/sandbox bash` 应输出格式化结果。"""

    executor = FakeExecutor()
    handlers = CommandHandlers(
        context=FakeChatContext(),
        runtime=SimpleNamespace(executor=executor),
        build_request_context=lambda *_args: None,
    )
    fake_event.role = "admin"

    fake_event.message_str = "exec print('ok')"
    exec_results = await collect_results(handlers.handle_sandbox(fake_event))
    assert exec_results == [
        "⏳ 正在执行...",
        "**输出:**\n```\nhello\n```\n\n✅ 成功 | 内核: ipython",
    ]

    fake_event.message_str = "bash echo hi"
    bash_results = await collect_results(handlers.handle_sandbox(fake_event))
    assert bash_results == [
        "⏳ 正在执行...",
        "**输出:**\n```\nhello\n```\n\n✅ 成功 | 内核: bash",
    ]


@pytest.mark.asyncio
async def test_command_handlers_sandbox_covers_permission_help_and_missing_params(
    fake_event: "FakeEvent",
) -> None:
    """`/sandbox` 应覆盖权限拒绝、帮助和缺少参数的提示。"""

    executor = FakeExecutor()
    handlers = CommandHandlers(
        context=FakeChatContext(),
        runtime=SimpleNamespace(executor=executor),
        build_request_context=lambda *_args: None,
    )

    fake_event.role = "member"
    fake_event.message_str = "status"
    assert await collect_results(handlers.handle_sandbox(fake_event)) == [
        "❌ 只有管理员可以操作沙盒"
    ]

    fake_event.role = "admin"
    fake_event.message_str = ""
    help_results = await collect_results(handlers.handle_sandbox(fake_event))
    assert len(help_results) == 1
    assert "CodeSandbox 沙盒管理" in help_results[0]

    cases = [
        ("exec", ["请提供要执行的 Python 代码"]),
        ("bash", ["请提供要执行的 Shell 命令"]),
        ("stream", ["请提供要执行的代码"]),
        ("url https://example.com/logo.png", ["用法: `/sandbox url <URL> <保存路径>`"]),
    ]
    for message, expected in cases:
        fake_event.message_str = message
        assert await collect_results(handlers.handle_sandbox(fake_event)) == expected


@pytest.mark.asyncio
async def test_command_handlers_sandbox_file_install_and_restart_actions(
    fake_event: "FakeEvent",
) -> None:
    """`/sandbox` 应覆盖文件、安装和重启分支。"""

    executor = FakeExecutor()
    handlers = CommandHandlers(
        context=FakeChatContext(),
        runtime=SimpleNamespace(executor=executor),
        build_request_context=lambda *_args: None,
    )
    fake_event.role = "admin"

    fake_event.message_str = "status"
    assert await collect_results(handlers.handle_sandbox(fake_event)) == ["sandbox-health"]

    fake_event.message_str = "files src"
    assert await collect_results(handlers.handle_sandbox(fake_event)) == ["files:src"]

    fake_event.message_str = "upload"
    assert await collect_results(handlers.handle_sandbox(fake_event)) == [
        "用法: `/sandbox upload <文件路径> <内容>`"
    ]

    fake_event.message_str = "upload notes.txt hello"
    assert await collect_results(handlers.handle_sandbox(fake_event)) == ["✅ 已创建"]

    fake_event.message_str = "download"
    assert await collect_results(handlers.handle_sandbox(fake_event)) == ["请提供文件路径"]

    fake_event.message_str = "download notes.txt"
    assert await collect_results(handlers.handle_sandbox(fake_event)) == ["downloaded-content"]

    fake_event.message_str = "install"
    assert await collect_results(handlers.handle_sandbox(fake_event)) == ["请提供要安装的包名"]

    fake_event.message_str = "install numpy pandas"
    assert await collect_results(handlers.handle_sandbox(fake_event)) == [
        "📦 正在安装: numpy pandas...",
        "📦 installed ok",
    ]

    fake_event.message_str = "restart"
    assert await collect_results(handlers.handle_sandbox(fake_event)) == ["sandbox restarted"]


@pytest.mark.asyncio
async def test_command_handlers_sandbox_packages_and_variables_renderers(
    fake_event: "FakeEvent",
) -> None:
    """包列表与变量列表渲染应覆盖正常、空列表与错误路径。"""

    executor = FakeExecutor()
    executor.packages = [f"pkg_{index}" for index in range(51)]
    executor.variables = {"alpha": 1, "beta": "'two'"}
    handlers = CommandHandlers(
        context=FakeChatContext(),
        runtime=SimpleNamespace(executor=executor),
        build_request_context=lambda *_args: None,
    )
    fake_event.role = "admin"

    fake_event.message_str = "packages"
    package_results = await collect_results(handlers.handle_sandbox(fake_event))
    assert len(package_results) == 1
    assert "已安装的 Python 包" in package_results[0]
    assert "还有 1 个" in package_results[0]

    fake_event.message_str = "variables"
    variable_results = await collect_results(handlers.handle_sandbox(fake_event))
    assert len(variable_results) == 1
    assert "`alpha` = 1" in variable_results[0]
    assert "`beta` = 'two'" in variable_results[0]

    executor.packages = []
    fake_event.message_str = "packages"
    assert await collect_results(handlers.handle_sandbox(fake_event)) == ["📦 暂无已安装的包"]

    executor.list_packages_error = RuntimeError("pkg failed")
    assert await handlers._render_package_list(fake_event) == "❌ 获取包列表失败: pkg failed"

    executor.variables = {}
    executor.list_packages_error = None
    fake_event.message_str = "variables"
    assert await collect_results(handlers.handle_sandbox(fake_event)) == ["📊 当前会话无变量"]

    executor.show_variables_error = RuntimeError("var failed")
    assert await handlers._render_variable_list(fake_event) == "❌ 获取变量失败: var failed"


@pytest.mark.asyncio
async def test_command_handlers_sandbox_url_failure_and_invalid_help(
    fake_event: "FakeEvent",
) -> None:
    """URL 下载失败与未知子命令应返回明确提示。"""

    executor = FakeExecutor()
    executor.download_error = RuntimeError("network down")
    handlers = CommandHandlers(
        context=FakeChatContext(),
        runtime=SimpleNamespace(executor=executor),
        build_request_context=lambda *_args: None,
    )
    fake_event.role = "admin"

    fake_event.message_str = "url https://example.com/logo.png assets/logo.png"
    assert await collect_results(handlers.handle_sandbox(fake_event)) == [
        "⬇️ 正在下载: https://example.com/logo.png...",
        "❌ 下载失败: network down",
    ]

    fake_event.message_str = "unknown"
    help_results = await collect_results(handlers.handle_sandbox(fake_event))
    assert len(help_results) == 1
    assert "CodeSandbox 沙盒管理" in help_results[0]


def test_command_handlers_format_exec_result_handles_execresult_and_plain_value() -> None:
    """执行结果格式化应处理长文本、错误、图片和普通值。"""

    handlers = CommandHandlers(
        context=FakeChatContext(),
        runtime=SimpleNamespace(),
        build_request_context=lambda *_args: None,
    )
    long_result = ExecResult(
        text="a" * 3100,
        errors="b" * 1600,
        images=["img-1", "img-2"],
        exit_code=1,
        kernel="bash",
    )

    formatted = handlers.format_exec_result(long_result)

    assert "**输出:**" in formatted
    assert "**错误:**" in formatted
    assert "📷 生成了 2 张图片" in formatted
    assert "❌ 失败 (exit_code=1) | 内核: bash" in formatted
    assert "..." in formatted
    assert handlers.format_exec_result("raw-value") == "raw-value"


def test_command_handlers_format_exec_result_covers_error_only_and_success_without_output() -> None:
    """格式化器应覆盖只有错误和完全无输出的情况。"""

    handlers = CommandHandlers(
        context=FakeChatContext(),
        runtime=SimpleNamespace(),
        build_request_context=lambda *_args: None,
    )
    error_only = ExecResult(errors="traceback", exit_code=2, kernel="python")
    empty_result = ExecResult(exit_code=0, kernel="ipython")

    formatted_error = handlers.format_exec_result(error_only)

    assert "**输出:**" not in formatted_error
    assert "**错误:**" in formatted_error
    assert "❌ 失败 (exit_code=2) | 内核: python" in formatted_error
    assert handlers.format_exec_result(empty_result) == "\n✅ 成功 | 内核: ipython"


def test_command_handlers_require_component_raises_for_missing_runtime_part() -> None:
    """组件缺失时应抛出明确的运行时异常。"""

    handlers = CommandHandlers(
        context=FakeChatContext(),
        runtime=SimpleNamespace(),
        build_request_context=lambda *_args: None,
    )

    with pytest.raises(RuntimeError, match="运行时组件未初始化: executor"):
        handlers._require_component(None, "executor")
