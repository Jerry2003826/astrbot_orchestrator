"""命令处理层测试（官方化后形态）。

命令参数由框架注入（main.py 的 command_group + GreedyStr），
本层只验证业务转发、限流与安全审计。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from astrbot_orchestrator_v5.entrypoints.command_handlers import (
    CommandHandlers,
    CommandRateLimiter,
)
from astrbot_orchestrator_v5.sandbox.types import ExecResult
from tests.conftest import FakeContext, FakeEvent, collect_results


class FakeAgentRunner:
    def __init__(self, answer: str = "agent-answer") -> None:
        self.answer = answer
        self.calls: list[tuple[Any, str]] = []

    async def run(self, event: Any, task: str) -> str:
        self.calls.append((event, task))
        return self.answer


class FakeManager:
    def __init__(self) -> None:
        self.synced = 0

    def status_report(self) -> str:
        return "status-report"

    def templates_report(self) -> str:
        return "templates-report"

    async def sync_templates_to_host(self) -> str:
        self.synced += 1
        return "已注册 5 个预设子代理"


class FakePluginTool:
    async def search_plugins(self, keyword: str) -> str:
        return f"found:{keyword}"

    async def install_plugin(self, url: str) -> str:
        return f"installed:{url}"

    async def list_plugins(self) -> str:
        return "plugin-list"

    async def remove_plugin(self, name: str) -> str:
        return f"removed:{name}"

    async def update_plugin(self, name: str) -> str:
        return f"updated:{name}"

    def get_available_proxies(self) -> str:
        return "proxies"


class FakeSkillTool:
    def list_skills(self) -> str:
        return "skill-list"

    def read_skill(self, name: str) -> str:
        return f"skill:{name}"

    def delete_skill(self, name: str) -> str:
        return f"deleted:{name}"


class FakeMcpTool:
    def list_servers(self) -> str:
        return "mcp-list"

    async def add_server(self, name: str, url: str) -> str:
        return f"added:{name}:{url}"

    async def remove_server(self, name: str) -> str:
        return f"removed:{name}"

    async def test_server(self, name: str) -> str:
        return f"tested:{name}"

    def list_tools(self, name: str) -> str:
        return f"tools:{name}"


class FakeExecutor:
    def get_current_mode_info(self) -> str:
        return "mode-info"

    async def execute(self, command: str, event: Any) -> str:
        return f"auto:{command}"

    async def execute_local(self, command: str, event: Any) -> str:
        return f"local:{command}"

    async def execute_sandbox(self, command: str, event: Any) -> str:
        return f"sandbox:{command}"

    async def execute_python(self, command: str, event: Any) -> str:
        return f"python:{command}"

    async def exec_code(self, code: str, event: Any, kernel: str = "ipython", stream: bool = False):
        return ExecResult(text=f"ran:{code}", exit_code=0, kernel=kernel)

    async def healthcheck(self, event: Any = None) -> str:
        return "healthy"


class FakeDebugger:
    async def get_system_status(self) -> str:
        return "system-status"

    def get_recent_errors(self, limit: int = 10) -> str:
        return "recent-errors"

    async def analyze_problem(self, problem: str, provider_id: str) -> str:
        return f"analysis:{problem}"

    async def analyze_error(self, **kwargs: Any) -> str:
        return "auto-analysis"


def build_handlers(
    fake_context: FakeContext,
    tmp_path: Any = None,
    **overrides: Any,
) -> CommandHandlers:
    runtime = SimpleNamespace(
        agent_runner=overrides.get("agent_runner", FakeAgentRunner()),
        dynamic_agent_manager=overrides.get("manager", FakeManager()),
        plugin_tool=overrides.get("plugin_tool", FakePluginTool()),
        skill_tool=overrides.get("skill_tool", FakeSkillTool()),
        mcp_tool=overrides.get("mcp_tool", FakeMcpTool()),
        executor=overrides.get("executor", FakeExecutor()),
        debugger=overrides.get("debugger", FakeDebugger()),
    )
    return CommandHandlers(context=fake_context, runtime=runtime)


# ----------------------------------------------------------------------
# /agent
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_agent_runs_task(fake_context: FakeContext, fake_event: FakeEvent) -> None:
    runner = FakeAgentRunner("最终答案")
    handlers = build_handlers(fake_context, agent_runner=runner)

    outputs = await collect_results(handlers.handle_agent(fake_event, "做点事"))

    assert runner.calls == [(fake_event, "做点事")]
    assert any("正在执行任务" in text for text in outputs)
    assert outputs[-1] == "最终答案"


@pytest.mark.asyncio
async def test_handle_agent_empty_shows_help(
    fake_context: FakeContext, fake_event: FakeEvent
) -> None:
    handlers = build_handlers(fake_context)

    outputs = await collect_results(handlers.handle_agent(fake_event, "  "))

    assert len(outputs) == 1
    assert "全自主智能体编排器" in outputs[0]


@pytest.mark.asyncio
async def test_handle_agent_status_and_templates(
    fake_context: FakeContext, fake_event: FakeEvent
) -> None:
    handlers = build_handlers(fake_context)

    status = await collect_results(handlers.handle_agent(fake_event, "status"))
    templates = await collect_results(handlers.handle_agent(fake_event, "templates"))

    assert status == ["status-report"]
    assert templates == ["templates-report"]


@pytest.mark.asyncio
async def test_handle_agent_sync_requires_admin(
    fake_context: FakeContext,
) -> None:
    manager = FakeManager()
    handlers = build_handlers(fake_context, manager=manager)

    member = FakeEvent(message_str="agent sync", role="member")
    outputs = await collect_results(handlers.handle_agent(member, "sync"))
    assert any("仅管理员" in text for text in outputs)
    assert manager.synced == 0

    admin = FakeEvent(message_str="agent sync", role="admin")
    outputs = await collect_results(handlers.handle_agent(admin, "sync"))
    assert any("已注册" in text for text in outputs)
    assert manager.synced == 1


@pytest.mark.asyncio
async def test_handle_agent_error_falls_back_to_debugger(
    fake_context: FakeContext, fake_event: FakeEvent
) -> None:
    class BoomRunner:
        async def run(self, event: Any, task: str) -> str:
            raise RuntimeError("boom")

    handlers = build_handlers(fake_context, agent_runner=BoomRunner())

    outputs = await collect_results(handlers.handle_agent(fake_event, "task"))

    assert any("执行出错" in text and "auto-analysis" in text for text in outputs)


# ----------------------------------------------------------------------
# /plugin、/skill、/mcp
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plugin_commands(fake_context: FakeContext, fake_event: FakeEvent) -> None:
    handlers = build_handlers(fake_context)

    search = await collect_results(handlers.plugin_search(fake_event, "天气"))
    assert search[-1] == "found:天气"

    install = await collect_results(handlers.plugin_install(fake_event, "https://x/repo"))
    assert install[-1] == "installed:https://x/repo"

    listed = await collect_results(handlers.plugin_list(fake_event))
    assert listed == ["plugin-list"]


@pytest.mark.asyncio
async def test_plugin_search_requires_keyword(
    fake_context: FakeContext, fake_event: FakeEvent
) -> None:
    handlers = build_handlers(fake_context)

    outputs = await collect_results(handlers.plugin_search(fake_event, "  "))

    assert "用法" in outputs[0]


@pytest.mark.asyncio
async def test_skill_and_mcp_commands(fake_context: FakeContext, fake_event: FakeEvent) -> None:
    handlers = build_handlers(fake_context)

    assert (await collect_results(handlers.skill_list(fake_event)))[-1] == "skill-list"
    assert (await collect_results(handlers.skill_read(fake_event, "s1")))[-1] == "skill:s1"
    assert (await collect_results(handlers.mcp_add(fake_event, "srv", "https://u")))[-1] == (
        "added:srv:https://u"
    )
    assert (await collect_results(handlers.mcp_tools(fake_event, "srv")))[-1] == "tools:srv"


# ----------------------------------------------------------------------
# /exec、/sandbox、/debug
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exec_run_modes(fake_context: FakeContext, fake_event: FakeEvent) -> None:
    handlers = build_handlers(fake_context)

    auto = await collect_results(handlers.exec_run(fake_event, "ls", "auto"))
    local = await collect_results(handlers.exec_run(fake_event, "ls", "local"))
    sandbox = await collect_results(handlers.exec_run(fake_event, "ls", "sandbox"))
    py = await collect_results(handlers.exec_run(fake_event, "print(1)", "python"))

    assert auto[-1] == "auto:ls"
    assert local[-1] == "local:ls"
    assert sandbox[-1] == "sandbox:ls"
    assert py[-1] == "python:print(1)"


@pytest.mark.asyncio
async def test_sandbox_exec_formats_result(
    fake_context: FakeContext, fake_event: FakeEvent
) -> None:
    handlers = build_handlers(fake_context)

    outputs = await collect_results(handlers.sandbox_exec(fake_event, "print(1)", "ipython"))

    assert any("ran:print(1)" in text for text in outputs)
    assert any("✅ 成功" in text for text in outputs)


@pytest.mark.asyncio
async def test_debug_commands(fake_context: FakeContext, fake_event: FakeEvent) -> None:
    handlers = build_handlers(fake_context)

    status = await collect_results(handlers.debug_status(fake_event))
    logs = await collect_results(handlers.debug_logs(fake_event))
    analyze = await collect_results(handlers.debug_analyze(fake_event, "卡死了"))

    assert status[-1] == "system-status"
    assert logs[-1] == "recent-errors"
    assert analyze[-1] == "analysis:卡死了"


# ----------------------------------------------------------------------
# 限流与审计
# ----------------------------------------------------------------------


def test_rate_limiter_fixed_window() -> None:
    now = [0.0]
    limiter = CommandRateLimiter(clock=lambda: now[0])

    assert limiter.allow("k", limit=2, window_seconds=60)
    assert limiter.allow("k", limit=2, window_seconds=60)
    assert not limiter.allow("k", limit=2, window_seconds=60)

    now[0] = 61.0
    assert limiter.allow("k", limit=2, window_seconds=60)


@pytest.mark.asyncio
async def test_rate_limit_blocks_after_threshold(
    fake_context: FakeContext, fake_event: FakeEvent
) -> None:
    handlers = build_handlers(fake_context)

    last: list[str] = []
    for _ in range(16):
        last = await collect_results(handlers.plugin_search(fake_event, "kw"))
    assert any("过于频繁" in text for text in last)


@pytest.mark.asyncio
async def test_audit_log_written_to_plugin_data_dir(
    fake_context: FakeContext,
    fake_event: FakeEvent,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from astrbot_orchestrator_v5.entrypoints import command_handlers as module

    monkeypatch.setattr(module, "get_plugin_data_dir", lambda: tmp_path)
    handlers = build_handlers(fake_context)

    await collect_results(handlers.plugin_search(fake_event, "kw"))

    audit_file = tmp_path / "security_audit.jsonl"
    assert audit_file.exists()
    record = json.loads(audit_file.read_text(encoding="utf-8").splitlines()[-1])
    assert record["command"] == "plugin"
    assert record["action"] == "search"
    assert record["outcome"] == "success"
    assert record["actor_id"] == "user-1"
