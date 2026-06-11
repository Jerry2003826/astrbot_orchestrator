"""main.py（插件入口）测试。

stub 装饰器把注册信息记录在函数属性 ``__astrbot_handlers__`` 上，
据此断言命令树与权限声明；运行时行为通过 FakeContext 验证。
"""

from __future__ import annotations

from typing import Any

from astrbot.api.event import filter as astr_filter
import pytest

from astrbot_orchestrator_v5.main import OrchestratorPlugin
from tests.conftest import FakeContext, FakeEvent, collect_results


def handler_records(fn: Any) -> list[dict[str, Any]]:
    return list(getattr(fn, "__astrbot_handlers__", []))


def command_record(fn: Any) -> dict[str, Any]:
    for record in handler_records(fn):
        if record.get("type") == "command":
            return record
    raise AssertionError(f"{fn.__name__} 未注册为 command")


def has_admin_permission(fn: Any) -> bool:
    return any(
        record.get("type") == "permission"
        and record.get("permission_type") == astr_filter.PermissionType.ADMIN
        for record in handler_records(fn)
    )


# ----------------------------------------------------------------------
# 注册形态
# ----------------------------------------------------------------------


def test_command_tree_registration() -> None:
    cls = OrchestratorPlugin

    assert command_record(cls.cmd_agent) == {
        "type": "command",
        "name": "agent",
        "alias": set(),
        "group": None,
    }

    expectations = {
        cls.cmd_plugin_search: ("plugin", "search"),
        cls.cmd_plugin_install: ("plugin", "install"),
        cls.cmd_skill_list: ("skill", "list"),
        cls.cmd_mcp_add: ("mcp", "add"),
        cls.cmd_exec_run: ("exec", "run"),
        cls.cmd_sandbox_exec: ("sandbox", "exec"),
        cls.cmd_debug_status: ("debug", "status"),
    }
    for fn, (group, name) in expectations.items():
        record = command_record(fn)
        assert record["group"] == group, fn.__name__
        assert record["name"] == name, fn.__name__


def test_admin_permission_declarations() -> None:
    cls = OrchestratorPlugin

    admin_handlers = [
        cls.cmd_plugin_install,
        cls.cmd_plugin_remove,
        cls.cmd_plugin_update,
        cls.cmd_skill_list,
        cls.cmd_skill_read,
        cls.cmd_skill_delete,
        cls.cmd_mcp_list,
        cls.cmd_mcp_add,
        cls.cmd_mcp_remove,
        cls.cmd_mcp_test,
        cls.cmd_mcp_tools,
        cls.cmd_exec_config,
        cls.cmd_exec_run,
        cls.cmd_exec_local,
        cls.cmd_exec_sandbox,
        cls.cmd_exec_python,
        cls.cmd_sandbox_status,
        cls.cmd_sandbox_exec,
        cls.cmd_sandbox_bash,
        cls.cmd_sandbox_upload,
        cls.cmd_debug_status,
        cls.cmd_debug_logs,
        cls.cmd_debug_analyze,
    ]
    for fn in admin_handlers:
        assert has_admin_permission(fn), f"{fn.__name__} 缺少 ADMIN permission_type"

    public_handlers = [
        cls.cmd_agent,
        cls.cmd_plugin_search,
        cls.cmd_plugin_list,
        cls.cmd_plugin_proxy,
        cls.cmd_skill_create,
    ]
    for fn in public_handlers:
        assert not has_admin_permission(fn), f"{fn.__name__} 不应要求 ADMIN"


def test_no_natural_language_router_left() -> None:
    import astrbot_orchestrator_v5.main as main_module

    source_names = dir(OrchestratorPlugin)
    assert not any("natural_language" in name for name in source_names)
    assert not hasattr(main_module.OrchestratorPlugin, "handle_natural_language_agent")


# ----------------------------------------------------------------------
# initialize / terminate
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initialize_registers_tools_and_syncs_subagents(
    fake_context: FakeContext,
) -> None:
    plugin = OrchestratorPlugin(fake_context, {"enable_dynamic_agents": True})

    await plugin.initialize()

    tool_names = {tool.name for tool in fake_context.llm_tools.func_list}
    assert "plugin_search" in tool_names
    assert "sandbox_exec_python" in tool_names

    handoffs = {h.name for h in fake_context.subagent_orchestrator.handoffs}
    assert "transfer_to_code_agent" in handoffs

    # 幂等
    await plugin.initialize()
    assert len([t for t in fake_context.llm_tools.func_list if t.name == "plugin_search"]) == 1


@pytest.mark.asyncio
async def test_initialize_skips_subagent_sync_when_disabled(
    fake_context: FakeContext,
) -> None:
    plugin = OrchestratorPlugin(fake_context, {"enable_dynamic_agents": False})

    await plugin.initialize()

    assert fake_context.subagent_orchestrator.handoffs == []


@pytest.mark.asyncio
async def test_initialize_respects_tool_gates(fake_context: FakeContext) -> None:
    plugin = OrchestratorPlugin(
        fake_context,
        {
            "enable_plugin_management": False,
            "enable_dynamic_agents": False,
        },
    )

    await plugin.initialize()

    tool_names = {tool.name for tool in fake_context.llm_tools.func_list}
    assert "plugin_search" not in tool_names
    assert "skill_list" in tool_names


@pytest.mark.asyncio
async def test_terminate_stops_runtime(fake_context: FakeContext) -> None:
    plugin = OrchestratorPlugin(fake_context, {"enable_dynamic_agents": False})
    await plugin.initialize()

    stopped: list[bool] = []

    async def fake_astop() -> None:
        stopped.append(True)

    # RuntimeContainer 是 slots dataclass，方法不可覆盖；替换底层 executor.astop
    plugin.runtime.executor.astop = fake_astop  # type: ignore[method-assign]
    await plugin.terminate()

    assert stopped == [True]
    assert plugin._initialized is False


# ----------------------------------------------------------------------
# 命令转发
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cmd_agent_forwards_to_handlers(fake_context: FakeContext) -> None:
    plugin = OrchestratorPlugin(fake_context, {"enable_dynamic_agents": False})
    await plugin.initialize()

    captured: list[tuple[Any, str]] = []

    class FakeRunner:
        async def run(self, event: Any, task: str) -> str:
            captured.append((event, task))
            return "done"

    # CommandHandlers/RuntimeContainer 方法均为 slots 只读，替换数据字段
    plugin.runtime.agent_runner = FakeRunner()  # type: ignore[assignment]

    event = FakeEvent(message_str="agent 帮我装插件")
    outputs = await collect_results(plugin.cmd_agent(event, "帮我装插件"))

    assert captured == [(event, "帮我装插件")]
    assert outputs[-1] == "done"


@pytest.mark.asyncio
async def test_handlers_raise_before_initialize(fake_context: FakeContext) -> None:
    plugin = OrchestratorPlugin(fake_context, {})
    event = FakeEvent(message_str="agent x")

    with pytest.raises(RuntimeError, match="未初始化"):
        async for _ in plugin.cmd_agent(event, "x"):
            pass
