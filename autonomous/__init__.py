"""
自主能力模块

实现 Agent 的自主能力：
- 插件市场搜索/安装
- Skill 动态创建
- MCP 配置管理
- 自我 Debug
- 执行环境管理
"""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "PluginManagerTool",
    "SkillCreatorTool",
    "MCPConfiguratorTool",
    "SelfDebugger",
    "ExecutionManager",
]

_MODULE_MAP = {
    "PluginManagerTool": ".plugin_manager",
    "SkillCreatorTool": ".skill_creator",
    "MCPConfiguratorTool": ".mcp_configurator",
    "SelfDebugger": ".debugger",
    "ExecutionManager": ".executor",
}


def __getattr__(name: str):
    """按需加载自主能力模块，减少测试时的宿主依赖。"""

    module_name = _MODULE_MAP.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
