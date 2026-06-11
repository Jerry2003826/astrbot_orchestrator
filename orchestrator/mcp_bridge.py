"""MCP 桥接器。

收敛到 4.25.5 官方 API：``context.get_llm_tool_manager()`` 单一路径，
通过 ``FunctionToolManager.mcp_client_dict`` 读取 MCP 服务器与工具。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from astrbot.api import logger


class MCPBridge:
    """读取 AstrBot 已配置的 MCP 服务器与工具，并支持直接调用。"""

    CALL_TIMEOUT_SECONDS = 60

    def __init__(self, context: Any) -> None:
        self.context = context

    def _get_tool_manager(self) -> Any | None:
        """获取官方 FunctionToolManager。"""

        try:
            return self.context.get_llm_tool_manager()
        except Exception as exc:
            logger.warning("get_llm_tool_manager() 失败，MCP 功能不可用: %s", exc)
            return None

    def _mcp_clients(self) -> dict[str, Any]:
        tool_manager = self._get_tool_manager()
        return dict(getattr(tool_manager, "mcp_client_dict", None) or {})

    def list_tools(self) -> list[dict[str, Any]]:
        """列出所有可用的 MCP 工具。"""

        tools: list[dict[str, Any]] = []
        for server_name, client in self._mcp_clients().items():
            try:
                if not getattr(client, "active", True):
                    continue
                for mcp_tool in getattr(client, "tools", None) or []:
                    tools.append(
                        {
                            "name": getattr(mcp_tool, "name", str(mcp_tool)),
                            "description": getattr(mcp_tool, "description", "") or "",
                            "server": server_name,
                            "parameters": getattr(
                                mcp_tool,
                                "inputSchema",
                                getattr(mcp_tool, "parameters", {}),
                            ),
                            "type": "mcp_tool",
                        }
                    )
            except Exception as exc:
                logger.warning("解析 MCP 服务器 %s 失败: %s", server_name, exc)

        logger.debug("共发现 %d 个 MCP 工具", len(tools))
        return tools

    def list_servers(self) -> dict[str, Any]:
        """列出所有 MCP 服务器及其状态。"""

        servers: dict[str, Any] = {}
        for server_name, client in self._mcp_clients().items():
            servers[server_name] = {
                "active": getattr(client, "active", True),
                "tool_count": len(getattr(client, "tools", None) or []),
            }
        return servers

    def get_tool(self, name: str) -> dict[str, Any] | None:
        """获取指定工具。"""

        for tool in self.list_tools():
            if tool["name"] == name:
                return tool
        return None

    def get_tools_by_server(self, server_name: str) -> list[dict[str, Any]]:
        """获取指定服务器的所有工具。"""

        return [t for t in self.list_tools() if t.get("server") == server_name]

    def build_tools_prompt(self) -> str:
        """构建 MCP 工具提示词（供 LLM 使用）。"""

        tools = self.list_tools()
        if not tools:
            return ""

        lines = ["## 可用 MCP 工具"]
        by_server: dict[str, list[dict[str, Any]]] = {}
        for tool in tools:
            by_server.setdefault(tool.get("server", "unknown"), []).append(tool)

        for server, server_tools in by_server.items():
            lines.append(f"\n### {server}")
            lines.extend(f"- **{tool['name']}**: {tool['description']}" for tool in server_tools)
        return "\n".join(lines)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """调用 MCP 工具（带官方自动重连）。"""

        tool_info = self.get_tool(tool_name)
        if not tool_info:
            raise ValueError(f"工具不存在: {tool_name}")

        server_name = tool_info.get("server")
        client = self._mcp_clients().get(str(server_name))
        if client is None:
            raise ValueError(f"MCP 服务器不存在: {server_name}")

        try:
            return await client.call_tool_with_reconnect(
                tool_name=tool_name,
                arguments=arguments,
                read_timeout_seconds=timedelta(seconds=self.CALL_TIMEOUT_SECONDS),
            )
        except Exception as exc:
            logger.error("调用 MCP 工具 %s 失败: %s", tool_name, exc)
            raise

    def invalidate_cache(self) -> None:
        """兼容旧接口：现直接读宿主状态，无缓存可失效。"""
