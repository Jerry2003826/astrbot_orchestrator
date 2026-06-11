"""tools/ 包（FunctionTool 封装）测试。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from astrbot_orchestrator_v5.tools import build_orchestrator_tools
from astrbot_orchestrator_v5.tools.base import PERMISSION_DENIED, OrchestratorTool
from astrbot_orchestrator_v5.tools.mcp_tools import McpAddTool
from astrbot_orchestrator_v5.tools.plugin_tools import (
    PluginInstallTool,
    PluginSearchTool,
)
from astrbot_orchestrator_v5.tools.sandbox_tools import (
    SandboxExecPythonTool,
    SandboxInstallPackagesTool,
)
from astrbot_orchestrator_v5.tools.skill_tools import SkillCreateTool
from astrbot_orchestrator_v5.tools.workflow_tools import WorkflowRunTool
from tests.conftest import FakeEvent


def admin_event() -> FakeEvent:
    return FakeEvent(message_str="x", role="admin")


def member_event() -> FakeEvent:
    return FakeEvent(message_str="x", role="member")


class RecordingPluginTool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def search_plugins(self, keyword: str) -> str:
        self.calls.append(("search", keyword))
        return f"found:{keyword}"

    async def install_plugin(self, url: str) -> str:
        self.calls.append(("install_url", url))
        return f"installed:{url}"

    async def install_from_market(self, name: str) -> str:
        self.calls.append(("install_market", name))
        return f"market:{name}"


# ----------------------------------------------------------------------
# 构建与配置开关
# ----------------------------------------------------------------------


def test_build_orchestrator_tools_full_set() -> None:
    runtime = SimpleNamespace()
    tools = build_orchestrator_tools(runtime, {})

    names = {tool.name for tool in tools}
    assert {
        "plugin_search",
        "plugin_install",
        "skill_create",
        "mcp_add",
        "sandbox_exec_python",
        "sandbox_file_write",
        "debug_status",
        "workflow_run",
    } <= names
    assert all(isinstance(tool, OrchestratorTool) for tool in tools)
    assert all(tool.runtime is runtime for tool in tools)


def test_build_orchestrator_tools_respects_config_gates() -> None:
    config = {
        "enable_plugin_management": False,
        "enable_skill_creation": False,
        "enable_mcp_config": True,
        "enable_code_execution": False,
        "enable_self_debug": False,
        "enable_workflows": False,
    }
    tools = build_orchestrator_tools(SimpleNamespace(), config)

    names = {tool.name for tool in tools}
    assert names == {"mcp_list", "mcp_add", "mcp_remove", "mcp_test", "mcp_list_tools"}


def test_tool_schemas_are_valid_object_schemas() -> None:
    for tool in build_orchestrator_tools(SimpleNamespace(), {}):
        assert tool.parameters["type"] == "object"
        assert isinstance(tool.parameters.get("properties", {}), dict)
        assert tool.description


# ----------------------------------------------------------------------
# 权限门控
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_tool_rejects_non_admin() -> None:
    runtime = SimpleNamespace(executor=None)
    tool = SandboxExecPythonTool(runtime)

    result = await tool.run(member_event(), code="print(1)")

    assert result == PERMISSION_DENIED


@pytest.mark.asyncio
async def test_public_tool_allows_non_admin() -> None:
    plugin_tool = RecordingPluginTool()
    runtime = SimpleNamespace(plugin_tool=plugin_tool)
    tool = PluginSearchTool(runtime)

    result = await tool.run(member_event(), keyword="天气")

    assert result == "found:天气"


@pytest.mark.asyncio
async def test_admin_flags_match_expectation() -> None:
    tools = build_orchestrator_tools(SimpleNamespace(), {})
    by_name = {tool.name: tool for tool in tools}

    public = {
        "plugin_search",
        "plugin_list",
        "skill_list",
        "skill_read",
        "mcp_list",
        "mcp_list_tools",
        "workflow_list",
    }
    for name, tool in by_name.items():
        assert tool.requires_admin == (name not in public), name


# ----------------------------------------------------------------------
# 转发行为
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plugin_install_routes_url_vs_market_name() -> None:
    plugin_tool = RecordingPluginTool()
    tool = PluginInstallTool(SimpleNamespace(plugin_tool=plugin_tool))

    assert await tool.run(admin_event(), repo_url="https://github.com/a/b") == (
        "installed:https://github.com/a/b"
    )
    assert await tool.run(admin_event(), repo_url="weather_plugin") == "market:weather_plugin"
    assert plugin_tool.calls[0][0] == "install_url"
    assert plugin_tool.calls[1][0] == "install_market"


@pytest.mark.asyncio
async def test_skill_create_forwards_arguments() -> None:
    calls: list[Any] = []

    class FakeSkillTool:
        async def create_skill(self, name: str, description: str, content: str) -> str:
            calls.append((name, description, content))
            return "created"

    tool = SkillCreateTool(SimpleNamespace(skill_tool=FakeSkillTool()))

    result = await tool.run(admin_event(), name="demo", description="d", content="# c")

    assert result == "created"
    assert calls == [("demo", "d", "# c")]


@pytest.mark.asyncio
async def test_mcp_add_passes_transport_and_headers() -> None:
    calls: list[Any] = []

    class FakeMcpTool:
        async def add_server(self, name, url, transport="sse", headers=None) -> str:
            calls.append((name, url, transport, headers))
            return "added"

    tool = McpAddTool(SimpleNamespace(mcp_tool=FakeMcpTool()))

    await tool.run(
        admin_event(),
        name="srv",
        url="https://u",
        transport="streamable_http",
        headers={"Authorization": "$TOKEN"},
    )

    assert calls == [("srv", "https://u", "streamable_http", {"Authorization": "$TOKEN"})]


@pytest.mark.asyncio
async def test_sandbox_install_packages_forwards_list() -> None:
    calls: list[Any] = []

    class FakeExecutor:
        async def install_packages(self, packages, event) -> str:
            calls.append(packages)
            return "ok"

    tool = SandboxInstallPackagesTool(SimpleNamespace(executor=FakeExecutor()))

    await tool.run(admin_event(), packages=["requests", "numpy"])

    assert calls == [["requests", "numpy"]]


@pytest.mark.asyncio
async def test_workflow_run_reports_state() -> None:
    class FakeState:
        status = "completed"
        error = None
        variables = {"result": "42", "_provider_id": None}

    class FakeEngine:
        def get_workflow(self, workflow_id: str) -> Any:
            return object() if workflow_id == "wf1" else None

        async def execute(self, workflow_id: str, initial_input=None) -> Any:
            return FakeState()

    tool = WorkflowRunTool(SimpleNamespace(workflow_engine=FakeEngine()))

    missing = await tool.run(admin_event(), workflow_id="nope")
    assert "不存在" in missing

    result = await tool.run(admin_event(), workflow_id="wf1", inputs={"a": 1})
    assert "completed" in result
    assert "42" in result
    assert "_provider_id" not in result
