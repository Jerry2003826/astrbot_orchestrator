"""
MCP 桥接器

读取 AstrBot 已配置的 MCP 服务器和工具
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MCPBridge:
    """
    MCP 桥接器

    通过 AstrBot 的 FunctionToolManager 读取已注册的 MCP 工具
    支持多种 API 访问方式，确保版本兼容性
    """

    def __init__(self, context):
        """
        初始化

        Args:
            context: AstrBot Context 对象
        """
        self.context = context
        self._tools_cache: List[Dict] = []
        self._servers_cache: Dict[str, Any] = {}
        self._cache_valid = False

    def _get_tool_manager(self):
        """
        获取 AstrBot 的 FunctionToolManager

        尝试多种方式获取，确保版本兼容性：
        1. 使用公开 API: context.get_llm_tool_manager()
        2. 从 provider_manager 获取
        3. 从其他可能的路径获取
        """
        # 方法1: 使用公开 API (推荐)
        if hasattr(self.context, "get_llm_tool_manager"):
            try:
                manager = self.context.get_llm_tool_manager()
                if manager:
                    logger.debug("通过 get_llm_tool_manager() 获取工具管理器")
                    return manager
            except Exception as e:
                logger.debug(f"get_llm_tool_manager() 失败: {e}")

        # 方法2: 从 provider_manager 获取
        if hasattr(self.context, "provider_manager"):
            try:
                provider_mgr = self.context.provider_manager
                if hasattr(provider_mgr, "llm_tools"):
                    logger.debug("通过 provider_manager.llm_tools 获取工具管理器")
                    return provider_mgr.llm_tools
            except Exception as e:
                logger.debug(f"provider_manager.llm_tools 失败: {e}")

        # 方法3: 尝试直接访问内部属性 (最后手段)
        try:
            tool_mgr = getattr(self.context, "_llm_tool_manager", None)
            if tool_mgr:
                logger.debug("通过 _llm_tool_manager 获取工具管理器")
                return tool_mgr
        except Exception as e:
            logger.debug(f"_llm_tool_manager 失败: {e}")

        logger.warning("无法获取 FunctionToolManager，MCP 功能可能不可用")
        return None

    def _extract_tools_from_func_list(self, tool_manager) -> List[Dict[str, Any]]:
        """
        从 func_list 提取所有工具（包括 MCP 工具）

        Args:
            tool_manager: 工具管理器

        Returns:
            工具列表
        """
        tools = []
        func_list = getattr(tool_manager, "func_list", [])

        for tool in func_list:
            try:
                tool_info = {
                    "name": getattr(tool, "name", str(tool)),
                    "description": getattr(tool, "description", "") or "",
                    "parameters": getattr(tool, "parameters", {}),
                    "type": "tool",
                }

                # 检查是否是 MCP 工具
                if hasattr(tool, "server_name") or hasattr(tool, "_mcp_client"):
                    tool_info["type"] = "mcp_tool"
                    tool_info["server"] = getattr(
                        tool, "server_name", getattr(tool, "_mcp_client_name", "unknown")
                    )

                tools.append(tool_info)
            except Exception as e:
                logger.debug(f"解析工具失败: {e}")

        return tools

    def _extract_tools_from_mcp_clients(
        self, tool_manager
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        从 mcp_client_dict 提取 MCP 工具

        Args:
            tool_manager: 工具管理器

        Returns:
            MCP 工具列表
        """
        tools = []
        servers_info = {}

        # 尝试不同的属性名
        client_attrs = ["mcp_client_dict", "mcp_clients", "_mcp_clients", "mcp_client_map"]
        mcp_clients = None

        for attr in client_attrs:
            if hasattr(tool_manager, attr):
                mcp_clients = getattr(tool_manager, attr)
                if mcp_clients:
                    logger.debug(f"找到 MCP 客户端字典: {attr}")
                    break

        if not mcp_clients:
            logger.debug("未找到 MCP 客户端字典")
            return tools, servers_info

        for server_name, client in mcp_clients.items():
            try:
                # 检查客户端是否活跃
                is_active = getattr(client, "active", True)
                client_tools = getattr(client, "tools", [])
                servers_info[server_name] = {"active": is_active, "tool_count": len(client_tools)}

                if not is_active:
                    continue

                for mcp_tool in client_tools:
                    tool_info = {
                        "name": getattr(mcp_tool, "name", str(mcp_tool)),
                        "description": getattr(mcp_tool, "description", "") or "",
                        "server": server_name,
                        "parameters": getattr(
                            mcp_tool, "inputSchema", getattr(mcp_tool, "parameters", {})
                        ),
                        "type": "mcp_tool",
                    }
                    tools.append(tool_info)

            except Exception as e:
                logger.warning(f"解析 MCP 服务器 {server_name} 失败: {e}")

        return tools, servers_info

    def list_tools(self) -> List[Dict[str, Any]]:
        """
        列出所有可用的 MCP 工具

        Returns:
            MCP 工具列表
        """
        if self._cache_valid:
            return self._tools_cache

        tools = []
        servers_info = {}
        tool_manager = self._get_tool_manager()

        if tool_manager:
            # 方法1: 从 func_list 获取
            try:
                func_tools = self._extract_tools_from_func_list(tool_manager)
                # 只保留 MCP 工具
                mcp_tools_from_func = [t for t in func_tools if t.get("type") == "mcp_tool"]
                tools.extend(mcp_tools_from_func)
                logger.debug(f"从 func_list 获取到 {len(mcp_tools_from_func)} 个 MCP 工具")
            except Exception as e:
                logger.debug(f"从 func_list 提取失败: {e}")

            # 方法2: 从 mcp_client_dict 获取 (可能获取到更多)
            try:
                mcp_tools, servers = self._extract_tools_from_mcp_clients(tool_manager)
                if mcp_tools:
                    # 合并，避免重复
                    existing_names = {t["name"] for t in tools}
                    for t in mcp_tools:
                        if t["name"] not in existing_names:
                            tools.append(t)
                    servers_info.update(servers)
                    logger.debug(f"从 mcp_client_dict 获取到 {len(mcp_tools)} 个工具")
            except Exception as e:
                logger.error(f"读取 MCP 工具失败: {e}")

        self._tools_cache = tools
        self._servers_cache = servers_info
        # 修复 Bug X：仅在获取到实际数据时才标记缓存有效,避免首次调用时
        # FunctionToolManager 还未就绪导致本进程永久返回空列表。
        # 和 Round 4 Bug U（plugin_manager）/ Bug V（skill_loader）保持同一模式。
        if tools or servers_info:
            self._cache_valid = True

        logger.info(f"共发现 {len(tools)} 个 MCP 工具，来自 {len(servers_info)} 个服务器")
        return tools

    def list_servers(self) -> Dict[str, Any]:
        """
        列出所有 MCP 服务器

        Returns:
            服务器信息字典
        """
        if not self._cache_valid:
            self.list_tools()  # 触发缓存更新
        return self._servers_cache

    def get_tool(self, name: str) -> Optional[Dict[str, Any]]:
        """获取指定工具"""
        tools = self.list_tools()
        for tool in tools:
            if tool["name"] == name:
                return tool
        return None

    def get_tools_by_server(self, server_name: str) -> List[Dict[str, Any]]:
        """获取指定服务器的所有工具"""
        tools = self.list_tools()
        return [t for t in tools if t.get("server") == server_name]

    def build_tools_prompt(self) -> str:
        """
        构建 MCP 工具提示词（供 LLM 使用）

        Returns:
            工具描述的提示词
        """
        tools = self.list_tools()

        if not tools:
            return ""

        lines = ["## 可用 MCP 工具"]

        # 按服务器分组
        by_server: Dict[str, List] = {}
        for tool in tools:
            server = tool.get("server", "unknown")
            if server not in by_server:
                by_server[server] = []
            by_server[server].append(tool)

        for server, server_tools in by_server.items():
            lines.append(f"\n### {server}")
            for tool in server_tools:
                lines.append(f"- **{tool['name']}**: {tool['description']}")

        return "\n".join(lines)

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """
        调用 MCP 工具

        Args:
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            工具执行结果
        """
        tool_manager = self._get_tool_manager()
        if not tool_manager:
            raise RuntimeError("MCP 工具管理器不可用")

        # 查找工具
        tool_info = self.get_tool(tool_name)
        if not tool_info:
            raise ValueError(f"工具不存在: {tool_name}")

        server_name = tool_info.get("server")

        # 尝试多种方式获取 MCP 客户端
        client = None
        client_attrs = ["mcp_client_dict", "mcp_clients", "_mcp_clients", "mcp_client_map"]

        for attr in client_attrs:
            mcp_clients = getattr(tool_manager, attr, {})
            if mcp_clients and server_name in mcp_clients:
                client = mcp_clients[server_name]
                logger.debug(f"通过 {attr} 找到 MCP 客户端: {server_name}")
                break

        if not client:
            raise ValueError(f"MCP 服务器不存在: {server_name}")

        # 尝试多种调用方法
        try:
            # 方法1: call_tool_with_reconnect
            if hasattr(client, "call_tool_with_reconnect"):
                result = await client.call_tool_with_reconnect(
                    tool_name=tool_name, arguments=arguments
                )
                return result

            # 方法2: call_tool
            if hasattr(client, "call_tool"):
                result = await client.call_tool(tool_name=tool_name, arguments=arguments)
                return result

            # 方法3: invoke
            if hasattr(client, "invoke"):
                result = await client.invoke(tool_name, arguments)
                return result

            raise RuntimeError(f"MCP 客户端没有可用的调用方法: {type(client)}")

        except Exception as e:
            logger.error(f"调用 MCP 工具 {tool_name} 失败: {e}")
            raise

    def invalidate_cache(self):
        """使缓存失效"""
        self._cache_valid = False
        self._tools_cache = []
        self._servers_cache = {}
