"""
MCP 配置管理工具

功能：
- 添加/移除 MCP 服务器
- 测试 MCP 连接
- 查看 MCP 工具列表
"""

import os
import json
import logging
import aiohttp
from typing import Dict, List, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class MCPConfiguratorTool:
    """
    MCP 配置管理工具
    
    管理 AstrBot 的 MCP 服务器配置
    """
    
    def __init__(self, context):
        self.context = context
    
    def _get_tool_manager(self):
        """获取 FunctionToolManager"""
        try:
            return self.context.provider_manager.llm_tools
        except AttributeError:
            return None
    
    def _get_mcp_config_path(self) -> str:
        """获取 MCP 配置文件路径"""
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path
            return os.path.join(get_astrbot_data_path(), "mcp_config.json")
        except ImportError:
            return os.path.expanduser("~/.astrbot/data/mcp_config.json")
    
    def _load_mcp_config(self) -> Dict:
        """加载 MCP 配置"""
        config_path = self._get_mcp_config_path()
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        
        return {"mcpServers": {}}
    
    def _save_mcp_config(self, config: Dict):
        """保存 MCP 配置"""
        config_path = self._get_mcp_config_path()
        
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    
    def list_servers(self) -> str:
        """列出所有 MCP 服务器"""
        tool_manager = self._get_tool_manager()
        
        lines = ["🔌 MCP 服务器列表：\n"]
        
        # 从 FunctionToolManager 获取活跃的 MCP 客户端
        if tool_manager:
            mcp_clients = getattr(tool_manager, 'mcp_client_dict', {})
            
            if mcp_clients:
                for name, client in mcp_clients.items():
                    status = "✅" if client.active else "❌"
                    tool_count = len(client.tools)
                    lines.append(f"{status} **{name}** ({tool_count} 工具)")
            else:
                lines.append("暂无活跃的 MCP 服务器")
        
        # 从配置文件获取
        config = self._load_mcp_config()
        servers = config.get("mcpServers", {})
        
        if servers:
            lines.append("\n📋 配置的服务器：")
            for name, cfg in servers.items():
                active = cfg.get("active", True)
                url = cfg.get("url", "")[:50]
                status = "✅" if active else "❌"
                lines.append(f"{status} {name}: {url}...")
        
        lines.append("\n💡 添加命令: `/mcp add <名称> <url>`")
        
        return "\n".join(lines)
    
    async def add_server(
        self,
        name: str,
        url: str,
        transport: str = "sse",
        headers: Optional[Dict] = None
    ) -> str:
        """
        添加 MCP 服务器
        
        Args:
            name: 服务器名称
            url: 服务器 URL
            transport: 传输类型 (sse/streamable_http)
            headers: 可选的请求头
        """
        try:
            config = self._load_mcp_config()
            
            # 检查是否已存在
            if name in config.get("mcpServers", {}):
                return f"❌ MCP 服务器 `{name}` 已存在，请使用其他名称"
            
            # 添加配置
            server_config = {
                "url": url,
                "transport": transport,
                "active": True
            }
            
            if headers:
                server_config["headers"] = headers
            
            config.setdefault("mcpServers", {})[name] = server_config
            
            # 保存配置
            self._save_mcp_config(config)
            
            # 尝试启用
            tool_manager = self._get_tool_manager()
            if tool_manager:
                try:
                    await tool_manager.enable_mcp_server(name=name, config=server_config)
                except Exception as e:
                    return f"⚠️ MCP 服务器 `{name}` 已添加到配置，但启用失败: {str(e)}\n\n请检查 URL 是否正确，或重启 AstrBot"
            
            return f"✅ MCP 服务器 `{name}` 添加成功！\n\nURL: {url}\n传输: {transport}"
            
        except Exception as e:
            logger.error(f"添加 MCP 服务器失败: {e}")
            return f"❌ 添加失败: {str(e)}"
    
    async def remove_server(self, name: str) -> str:
        """移除 MCP 服务器"""
        try:
            config = self._load_mcp_config()
            
            if name not in config.get("mcpServers", {}):
                return f"❌ MCP 服务器 `{name}` 不存在"
            
            # 从配置中移除
            del config["mcpServers"][name]
            self._save_mcp_config(config)
            
            # 禁用
            tool_manager = self._get_tool_manager()
            if tool_manager:
                try:
                    mcp_clients = getattr(tool_manager, 'mcp_client_dict', {})
                    if name in mcp_clients:
                        await mcp_clients[name].cleanup()
                        del mcp_clients[name]
                except Exception as e:
                    logger.warning(f"禁用 MCP 客户端失败: {e}")
            
            return f"✅ MCP 服务器 `{name}` 已移除"
            
        except Exception as e:
            return f"❌ 移除失败: {str(e)}"
    
    async def test_server(self, name: str) -> str:
        """测试 MCP 服务器连接"""
        config = self._load_mcp_config()
        
        if name not in config.get("mcpServers", {}):
            return f"❌ MCP 服务器 `{name}` 不存在"
        
        server_config = config["mcpServers"][name]
        url = server_config.get("url", "")
        transport = server_config.get("transport", "sse")
        headers = server_config.get("headers", {})
        
        try:
            async with aiohttp.ClientSession() as session:
                if transport == "streamable_http":
                    # Streamable HTTP 测试
                    test_payload = {
                        "jsonrpc": "2.0",
                        "method": "initialize",
                        "id": 0,
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "test", "version": "1.0"}
                        }
                    }
                    async with session.post(
                        url,
                        headers={**headers, "Content-Type": "application/json"},
                        json=test_payload,
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:
                        if resp.status == 200:
                            return f"✅ MCP 服务器 `{name}` 连接正常！\n\nURL: {url}\n状态: HTTP {resp.status}"
                        else:
                            return f"❌ 连接失败: HTTP {resp.status}"
                else:
                    # SSE 测试
                    async with session.get(
                        url,
                        headers={**headers, "Accept": "text/event-stream"},
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:
                        if resp.status == 200:
                            return f"✅ MCP 服务器 `{name}` 连接正常！\n\nURL: {url}\n状态: HTTP {resp.status}"
                        else:
                            return f"❌ 连接失败: HTTP {resp.status}"
                            
        except asyncio.TimeoutError:
            return f"❌ 连接超时: {url}"
        except Exception as e:
            return f"❌ 连接失败: {str(e)}"
    
    def list_tools(self, server_name: str) -> str:
        """列出指定服务器的工具"""
        tool_manager = self._get_tool_manager()
        
        if not tool_manager:
            return "❌ 工具管理器不可用"
        
        mcp_clients = getattr(tool_manager, 'mcp_client_dict', {})
        
        if server_name not in mcp_clients:
            return f"❌ MCP 服务器 `{server_name}` 未连接或不存在"
        
        client = mcp_clients[server_name]
        tools = client.tools
        
        if not tools:
            return f"🔌 MCP 服务器 `{server_name}` 暂无工具"
        
        lines = [f"🔌 **{server_name}** 的工具列表 ({len(tools)} 个)：\n"]
        
        for tool in tools:
            name = tool.name
            desc = tool.description[:60] if tool.description else "无描述"
            lines.append(f"• **{name}**")
            lines.append(f"  {desc}...")
        
        return "\n".join(lines)
    
    async def create_mcp_from_description(
        self,
        name: str,
        user_description: str,
        provider_id: str
    ) -> str:
        """
        根据用户描述推荐或生成 MCP 配置
        """
        prompt = f"""用户想要配置一个 MCP 服务来实现以下功能：

{user_description}

请分析用户需求，并推荐合适的 MCP 服务：

1. 如果有现成的公开 MCP 服务可以满足需求，请给出：
   - 服务名称
   - 服务 URL
   - 如何配置

2. 如果需要自己搭建 MCP 服务，请给出：
   - 推荐的实现方式
   - 需要的工具/库
   - 基本配置步骤

常见的公开 MCP 服务：
- 网页搜索: Tavily、Brave Search 等
- 代码执行: E2B 等
- 文件操作: 本地 MCP 服务

请给出具体的建议和配置方法。"""

        try:
            response = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
                system_prompt="你是一个 MCP 协议专家，熟悉各种 MCP 服务的配置。"
            )
            
            return response.completion_text
            
        except Exception as e:
            logger.error(f"生成 MCP 建议失败: {e}")
            return f"❌ 分析失败: {str(e)}"


import asyncio  # 需要在文件顶部
