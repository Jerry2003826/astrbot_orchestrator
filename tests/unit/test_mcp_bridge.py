"""MCPBridge 单元测试。"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from astrbot_orchestrator_v5.orchestrator.mcp_bridge import MCPBridge

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture
    from _pytest.fixtures import FixtureRequest
    from _pytest.logging import LogCaptureFixture
    from _pytest.monkeypatch import MonkeyPatch
    from pytest_mock.plugin import MockerFixture

    _PYTEST_TYPE_IMPORTS = (
        CaptureFixture,
        FixtureRequest,
        LogCaptureFixture,
        MonkeyPatch,
        MockerFixture,
    )


class FakeMcpClient:
    """MCP 客户端替身。"""

    def __init__(
        self,
        *,
        active: bool,
        tools: list[Any],
        result: Any = None,
    ) -> None:
        """保存客户端状态和工具列表。"""

        self.active = active
        self.tools = tools
        self.result = result if result is not None else {"ok": True}
        self.calls: list[dict[str, Any]] = []

    async def call_tool_with_reconnect(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        """记录工具调用并返回预设结果。"""

        self.calls.append({"tool_name": tool_name, "arguments": arguments})
        return self.result


class FakeToolManager:
    """FunctionToolManager 替身。"""

    def __init__(
        self,
        mcp_client_dict: dict[str, FakeMcpClient],
        *,
        error: Exception | None = None,
    ) -> None:
        """初始化客户端映射和异常行为。"""

        self.mcp_client_dict = mcp_client_dict
        self.error = error

    @property
    def mcp_client_dict(self) -> dict[str, FakeMcpClient]:
        """返回客户端映射，必要时抛出异常。"""

        if self.error is not None:
            raise self.error
        return self._mcp_client_dict

    @mcp_client_dict.setter
    def mcp_client_dict(self, value: dict[str, FakeMcpClient]) -> None:
        """设置客户端映射。"""

        self._mcp_client_dict = value


def make_context(tool_manager: Any | None = None) -> Any:
    """构造带可选工具管理器的上下文。"""

    context = SimpleNamespace()
    if tool_manager is not None:
        setattr(
            context,
            "provider_manager",
            SimpleNamespace(llm_tools=tool_manager),
        )
    return context


def make_tool(
    name: str,
    description: str | None = None,
    input_schema: dict[str, Any] | None = None,
) -> Any:
    """构造测试用 MCP 工具对象。"""

    tool = SimpleNamespace(name=name, description=description)
    if input_schema is not None:
        setattr(tool, "inputSchema", input_schema)
    return tool


def test_mcp_bridge_get_tool_manager_covers_success_and_missing_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """工具管理器访问应覆盖成功和缺失 provider_manager 的告警路径。"""

    manager = FakeToolManager({})
    bridge = MCPBridge(context=make_context(manager))
    missing_bridge = MCPBridge(context=make_context())

    caplog.set_level(logging.WARNING)

    assert bridge._get_tool_manager() is manager
    assert missing_bridge._get_tool_manager() is None
    assert "无法获取 FunctionToolManager" in caplog.text


def test_mcp_bridge_list_tools_servers_and_queries_cover_cache_and_error_paths(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """工具枚举应覆盖缓存、服务器摘要、查询与异常路径。"""

    alpha_tool = make_tool("alpha", "first tool", {"type": "object"})
    beta_tool = make_tool("beta", None)
    tool_manager = FakeToolManager(
        {
            "server-a": FakeMcpClient(active=True, tools=[alpha_tool, beta_tool]),
            "server-b": FakeMcpClient(active=False, tools=[make_tool("ignored")]),
        }
    )
    bridge = MCPBridge(context=make_context(tool_manager))

    first_tools = bridge.list_tools()
    second_tools = bridge.list_tools()
    servers = bridge.list_servers()

    assert first_tools == [
        {
            "name": "alpha",
            "description": "first tool",
            "server": "server-a",
            "parameters": {"type": "object"},
            "type": "mcp_tool",
        },
        {
            "name": "beta",
            "description": "",
            "server": "server-a",
            "parameters": {},
            "type": "mcp_tool",
        },
    ]
    assert second_tools is first_tools
    assert servers == {
        "server-a": {"active": True, "tool_count": 2},
        "server-b": {"active": False, "tool_count": 1},
    }
    assert bridge.get_tool("alpha") == first_tools[0]
    assert bridge.get_tool("missing") is None
    assert bridge.get_tools_by_server("server-a") == first_tools
    assert bridge.get_tools_by_server("server-b") == []

    caplog.set_level(logging.ERROR)
    error_bridge = MCPBridge(
        context=make_context(FakeToolManager({}, error=RuntimeError("broken tool manager")))
    )

    assert error_bridge.list_tools() == []
    assert error_bridge.list_servers() == {}
    assert "读取 MCP 工具失败: broken tool manager" in caplog.text

    cold_bridge = MCPBridge(context=make_context())
    assert cold_bridge.list_servers() == {}
    assert cold_bridge.list_tools() == []


def test_mcp_bridge_build_tools_prompt_covers_empty_and_grouped_rendering() -> None:
    """工具提示词应覆盖空状态和按服务器分组展示。"""

    bridge = MCPBridge(context=make_context())
    bridge._tools_cache = []
    bridge._cache_valid = True
    assert bridge.build_tools_prompt() == ""

    bridge._tools_cache = [
        {"name": "alpha", "description": "first", "server": "server-a"},
        {"name": "beta", "description": "second", "server": "server-a"},
        {"name": "gamma", "description": "third", "server": "server-b"},
    ]

    rendered = bridge.build_tools_prompt()

    assert "## 可用 MCP 工具" in rendered
    assert "\n### server-a" in rendered
    assert "- **alpha**: first" in rendered
    assert "- **gamma**: third" in rendered


@pytest.mark.asyncio
async def test_mcp_bridge_call_tool_covers_missing_manager_tool_server_and_success() -> None:
    """工具调用应覆盖所有前置校验与成功路径。"""

    no_manager_bridge = MCPBridge(context=make_context())
    with pytest.raises(RuntimeError, match="MCP 工具管理器不可用"):
        await no_manager_bridge.call_tool("alpha", {})

    alpha_client = FakeMcpClient(active=True, tools=[make_tool("alpha")], result={"value": 1})
    success_bridge = MCPBridge(context=make_context(FakeToolManager({"server-a": alpha_client})))
    missing_tool_bridge = MCPBridge(context=make_context(FakeToolManager({})))
    missing_server_bridge = MCPBridge(context=make_context(FakeToolManager({})))
    missing_server_bridge._tools_cache = [
        {
            "name": "alpha",
            "description": "",
            "server": "server-a",
            "parameters": {},
            "type": "mcp_tool",
        }
    ]
    missing_server_bridge._cache_valid = True

    with pytest.raises(ValueError, match="工具不存在: alpha"):
        await missing_tool_bridge.call_tool("alpha", {})

    with pytest.raises(ValueError, match="MCP 服务器不存在: server-a"):
        await missing_server_bridge.call_tool("alpha", {"q": "hello"})

    result = await success_bridge.call_tool("alpha", {"q": "hello"})

    assert result == {"value": 1}
    assert alpha_client.calls == [{"tool_name": "alpha", "arguments": {"q": "hello"}}]


def test_mcp_bridge_invalidate_cache_clears_cached_tools_and_servers() -> None:
    """缓存失效应清空工具和服务器缓存。"""

    bridge = MCPBridge(context=make_context())
    bridge._cache_valid = True
    bridge._tools_cache = [{"name": "alpha"}]
    bridge._servers_cache = {"server-a": {"active": True}}

    bridge.invalidate_cache()

    assert bridge._cache_valid is False
    assert bridge._tools_cache == []
    assert bridge._servers_cache == {}
