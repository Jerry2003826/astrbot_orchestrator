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
        """获取 AstrBot 的 FunctionToolManager"""
        try:
            return self.context.provider_manager.llm_tools
        except AttributeError:
            logger.warning("无法获取 FunctionToolManager")
            return None
    
    def list_tools(self) -> List[Dict[str, Any]]:
        """
        列出所有可用的 MCP 工具
        
        Returns:
            MCP 工具列表
        """
        if self._cache_valid:
            return self._tools_cache
        
        tools = []
        tool_manager = self._get_tool_manager()
        
        if tool_manager:
            try:
                # 获取 MCP 客户端
                mcp_clients = getattr(tool_manager, 'mcp_client_dict', {})
                
                for server_name, client in mcp_clients.items():
                    if not client.active:
                        continue
                    
                    for mcp_tool in client.tools:
                        tools.append({
                            "name": mcp_tool.name,
                            "description": mcp_tool.description or "",
                            "server": server_name,
                            "parameters": mcp_tool.inputSchema if hasattr(mcp_tool, 'inputSchema') else {},
                            "type": "mcp_tool"
                        })
                
                self._servers_cache = {
                    name: {"active": client.active, "tool_count": len(client.tools)}
                    for name, client in mcp_clients.items()
                }
                
            except Exception as e:
                logger.error(f"读取 MCP 工具失败: {e}")
        
        self._tools_cache = tools
        self._cache_valid = True
        
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
        mcp_clients = getattr(tool_manager, 'mcp_client_dict', {})
        
        if server_name not in mcp_clients:
            raise ValueError(f"MCP 服务器不存在: {server_name}")
        
        client = mcp_clients[server_name]
        
        # 调用工具
        result = await client.call_tool_with_reconnect(
            tool_name=tool_name,
            arguments=arguments
        )
        
        return result
    
    def invalidate_cache(self):
        """使缓存失效"""
        self._cache_valid = False
        self._tools_cache = []
        self._servers_cache = {}
