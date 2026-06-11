"""MCP 服务器配置能力的 FunctionTool 封装（复用 autonomous/mcp_configurator.py）。"""

from __future__ import annotations

from typing import Any

from .base import OrchestratorTool, obj_schema, str_prop


class McpListTool(OrchestratorTool):
    requires_admin = False

    def __init__(self, runtime: Any) -> None:
        super().__init__(
            runtime,
            name="mcp_list",
            description="列出已配置的 MCP 服务器及其连接状态。",
            parameters=obj_schema({}),
        )

    async def run(self, event: Any) -> str:
        return self.runtime.mcp_tool.list_servers()


class McpAddTool(OrchestratorTool):
    def __init__(self, runtime: Any) -> None:
        super().__init__(
            runtime,
            name="mcp_add",
            description=(
                "添加一个 MCP 服务器（管理员）。支持 SSE / Streamable HTTP 远程服务器，"
                "传入名称与 URL；可选 headers 用于鉴权（值支持 $ENV_VAR 环境变量引用）。"
            ),
            parameters=obj_schema(
                {
                    "name": str_prop("MCP 服务器名称（标识符）"),
                    "url": str_prop("服务器 URL（http/https）"),
                    "transport": {
                        "type": "string",
                        "description": "传输协议，默认 sse",
                        "enum": ["sse", "streamable_http"],
                    },
                    "headers": {
                        "type": "object",
                        "description": "可选的 HTTP 请求头（如 Authorization）",
                        "additionalProperties": {"type": "string"},
                    },
                },
                required=["name", "url"],
            ),
        )

    async def run(
        self,
        event: Any,
        name: str,
        url: str,
        transport: str = "sse",
        headers: dict[str, str] | None = None,
    ) -> str:
        if denied := self.check_permission(event):
            return denied
        return await self.runtime.mcp_tool.add_server(
            name, url, transport=transport, headers=headers
        )


class McpRemoveTool(OrchestratorTool):
    def __init__(self, runtime: Any) -> None:
        super().__init__(
            runtime,
            name="mcp_remove",
            description="移除一个已配置的 MCP 服务器（管理员）。",
            parameters=obj_schema(
                {"name": str_prop("要移除的 MCP 服务器名称")},
                required=["name"],
            ),
        )

    async def run(self, event: Any, name: str) -> str:
        if denied := self.check_permission(event):
            return denied
        return await self.runtime.mcp_tool.remove_server(name)


class McpTestTool(OrchestratorTool):
    def __init__(self, runtime: Any) -> None:
        super().__init__(
            runtime,
            name="mcp_test",
            description="测试指定 MCP 服务器的连通性并返回可用工具数（管理员）。",
            parameters=obj_schema(
                {"name": str_prop("要测试的 MCP 服务器名称")},
                required=["name"],
            ),
        )

    async def run(self, event: Any, name: str) -> str:
        if denied := self.check_permission(event):
            return denied
        return await self.runtime.mcp_tool.test_server(name)


class McpListToolsTool(OrchestratorTool):
    requires_admin = False

    def __init__(self, runtime: Any) -> None:
        super().__init__(
            runtime,
            name="mcp_list_tools",
            description="列出指定 MCP 服务器提供的全部工具。",
            parameters=obj_schema(
                {"server_name": str_prop("MCP 服务器名称")},
                required=["server_name"],
            ),
        )

    async def run(self, event: Any, server_name: str) -> str:
        return self.runtime.mcp_tool.list_tools(server_name)
