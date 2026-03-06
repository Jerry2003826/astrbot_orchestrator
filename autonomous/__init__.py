"""
自主能力模块

实现 Agent 的自主能力：
- 插件市场搜索/安装
- Skill 动态创建
- MCP 配置管理
- 自我 Debug
- 执行环境管理
"""

from .plugin_manager import PluginManagerTool
from .skill_creator import SkillCreatorTool
from .mcp_configurator import MCPConfiguratorTool
from .debugger import SelfDebugger
from .executor import ExecutionManager

__all__ = [
    "PluginManagerTool",
    "SkillCreatorTool",
    "MCPConfiguratorTool",
    "SelfDebugger",
    "ExecutionManager"
]
