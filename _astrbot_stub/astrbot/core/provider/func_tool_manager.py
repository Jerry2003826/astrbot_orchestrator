"""astrbot.core.provider.func_tool_manager 测试桩，对齐 v4.25.5 公开方法。

MCP 生命周期方法（enable/disable/test）在桩中默认抛 NotImplementedError，
测试应按需替换为 Fake；配置读写方法是可用的（落到桩数据目录）。
"""

import asyncio
import json
import os
from typing import Any

from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

DEFAULT_MCP_CONFIG: dict[str, Any] = {"mcpServers": {}}

FuncTool = FunctionTool


class FunctionToolManager:
    def __init__(self) -> None:
        self.func_list: list[FunctionTool] = []
        """All tools include mcp tools and plugin tools, except astrbot builtin tools."""
        self.mcp_client_dict: dict[str, Any] = {}
        """真实实现为只读视图；桩用普通 dict 方便测试注入。"""

    def empty(self) -> bool:
        return len(self.func_list) == 0

    def add_tool(self, tool: FunctionTool) -> None:
        self.remove_func(tool.name)
        self.func_list.append(tool)

    def add_func(self, name: str, func_args: list, desc: str, handler: Any) -> None:
        params: dict[str, Any] = {"type": "object", "properties": {}}
        for param in func_args:
            p = dict(param)
            p.pop("name", None)
            params["properties"][param["name"]] = p
        self.remove_func(name)
        self.func_list.append(
            FunctionTool(name=name, parameters=params, description=desc, handler=handler)
        )

    def remove_func(self, name: str) -> None:
        for i, f in enumerate(self.func_list):
            if f.name == name:
                self.func_list.pop(i)
                break

    def get_func(self, name: str) -> FunctionTool | None:
        for f in reversed(self.func_list):
            if f.name == name and getattr(f, "active", True):
                return f
        for f in reversed(self.func_list):
            if f.name == name:
                return f
        return None

    def get_builtin_tool(self, tool: Any) -> FunctionTool:
        raise KeyError(f"Builtin tool {tool} is not registered in stub.")

    def get_full_tool_set(self) -> ToolSet:
        toolset = ToolSet()
        for tool in self.func_list:
            toolset.add_tool(tool)
        return toolset

    def activate_llm_tool(self, name: str, star_map: dict | None = None) -> bool:
        tool = self.get_func(name)
        if tool is None:
            return False
        tool.active = True
        return True

    def deactivate_llm_tool(self, name: str) -> bool:
        tool = self.get_func(name)
        if tool is None:
            return False
        tool.active = False
        return True

    # ------------------------------------------------------------------
    # MCP
    # ------------------------------------------------------------------
    @property
    def mcp_config_path(self) -> str:
        return os.path.join(get_astrbot_data_path(), "mcp_server.json")

    def load_mcp_config(self) -> dict:
        if not os.path.exists(self.mcp_config_path):
            os.makedirs(os.path.dirname(self.mcp_config_path), exist_ok=True)
            with open(self.mcp_config_path, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_MCP_CONFIG, f, ensure_ascii=False, indent=4)
            return json.loads(json.dumps(DEFAULT_MCP_CONFIG))
        with open(self.mcp_config_path, encoding="utf-8") as f:
            return json.load(f)

    def save_mcp_config(self, config: dict) -> bool:
        with open(self.mcp_config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        return True

    async def init_mcp_clients(self, *args: Any, **kwargs: Any) -> None:
        return None

    @staticmethod
    async def test_mcp_server_connection(config: dict) -> list[str]:
        raise NotImplementedError("stub")

    async def enable_mcp_server(
        self,
        name: str,
        config: dict,
        shutdown_event: asyncio.Event | None = None,
        timeout: float | int | str | None = None,
    ) -> None:
        raise NotImplementedError("stub")

    async def disable_mcp_server(
        self,
        name: str | None = None,
        timeout: float = 10,
    ) -> None:
        raise NotImplementedError("stub")
