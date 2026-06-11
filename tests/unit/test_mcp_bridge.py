"""MCPBridge（官方 get_llm_tool_manager 单一路径）测试。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from astrbot_orchestrator_v5.orchestrator.mcp_bridge import MCPBridge


class FakeMcpTool:
    def __init__(self, name: str, description: str = "", schema: Any = None) -> None:
        self.name = name
        self.description = description
        self.inputSchema = schema or {"type": "object"}


class FakeClient:
    def __init__(
        self,
        tools: list[FakeMcpTool] | None = None,
        active: bool = True,
    ) -> None:
        self.tools = tools or []
        self.active = active
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.raise_on_call: Exception | None = None

    async def call_tool_with_reconnect(
        self, tool_name: str, arguments: dict[str, Any], read_timeout_seconds: Any
    ) -> str:
        if self.raise_on_call is not None:
            raise self.raise_on_call
        self.calls.append((tool_name, arguments))
        return f"result:{tool_name}"


class FakeBridgeContext:
    def __init__(self, clients: dict[str, Any] | None = None, broken: bool = False) -> None:
        self._clients = clients or {}
        self._broken = broken

    def get_llm_tool_manager(self) -> Any:
        if self._broken:
            raise RuntimeError("manager unavailable")
        return SimpleNamespace(mcp_client_dict=self._clients)


def make_bridge(clients: dict[str, Any] | None = None, broken: bool = False) -> MCPBridge:
    return MCPBridge(FakeBridgeContext(clients, broken))


def test_list_tools_reads_active_clients_only() -> None:
    bridge = make_bridge(
        {
            "alpha": FakeClient([FakeMcpTool("a1", "tool a1"), FakeMcpTool("a2")]),
            "beta": FakeClient([FakeMcpTool("b1")], active=False),
        }
    )

    tools = bridge.list_tools()

    names = {t["name"] for t in tools}
    assert names == {"a1", "a2"}
    assert all(t["server"] == "alpha" for t in tools)
    assert all(t["type"] == "mcp_tool" for t in tools)


def test_list_tools_returns_empty_when_manager_unavailable() -> None:
    bridge = make_bridge(broken=True)

    assert bridge.list_tools() == []
    assert bridge.list_servers() == {}


def test_list_servers_reports_status_and_counts() -> None:
    bridge = make_bridge(
        {
            "alpha": FakeClient([FakeMcpTool("a1")]),
            "beta": FakeClient([], active=False),
        }
    )

    servers = bridge.list_servers()

    assert servers == {
        "alpha": {"active": True, "tool_count": 1},
        "beta": {"active": False, "tool_count": 0},
    }


def test_get_tool_and_by_server() -> None:
    bridge = make_bridge({"alpha": FakeClient([FakeMcpTool("a1", "desc")])})

    assert bridge.get_tool("a1")["description"] == "desc"
    assert bridge.get_tool("missing") is None
    assert [t["name"] for t in bridge.get_tools_by_server("alpha")] == ["a1"]
    assert bridge.get_tools_by_server("other") == []


def test_build_tools_prompt_groups_by_server() -> None:
    bridge = make_bridge(
        {
            "alpha": FakeClient([FakeMcpTool("a1", "tool a1")]),
            "beta": FakeClient([FakeMcpTool("b1", "tool b1")]),
        }
    )

    prompt = bridge.build_tools_prompt()

    assert "## 可用 MCP 工具" in prompt
    assert "### alpha" in prompt
    assert "- **b1**: tool b1" in prompt

    assert make_bridge().build_tools_prompt() == ""


@pytest.mark.asyncio
async def test_call_tool_uses_official_reconnect_api() -> None:
    client = FakeClient([FakeMcpTool("a1")])
    bridge = make_bridge({"alpha": client})

    result = await bridge.call_tool("a1", {"x": 1})

    assert result == "result:a1"
    assert client.calls == [("a1", {"x": 1})]


@pytest.mark.asyncio
async def test_call_tool_raises_for_unknown_tool_or_server() -> None:
    bridge = make_bridge({"alpha": FakeClient([FakeMcpTool("a1")])})

    with pytest.raises(ValueError, match="工具不存在"):
        await bridge.call_tool("missing", {})


@pytest.mark.asyncio
async def test_call_tool_propagates_client_errors() -> None:
    client = FakeClient([FakeMcpTool("a1")])
    client.raise_on_call = RuntimeError("connection lost")
    bridge = make_bridge({"alpha": client})

    with pytest.raises(RuntimeError, match="connection lost"):
        await bridge.call_tool("a1", {})
