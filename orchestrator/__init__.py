"""编排器模块（官方 Agent 体系版）。

保留：AgentRunner（tool_loop_agent 薄层）、DynamicAgentManager
（官方 subagent 配置适配器）、SkillLoader、MCPBridge、代码提取等支撑组件。
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .agent_runner import AgentRunner
    from .dynamic_agent_manager import DynamicAgentManager
    from .mcp_bridge import MCPBridge
    from .skill_loader import AstrBotSkillLoader

_MODULE_BY_EXPORT = {
    "AgentRunner": "agent_runner",
    "AstrBotSkillLoader": "skill_loader",
    "DynamicAgentManager": "dynamic_agent_manager",
    "MCPBridge": "mcp_bridge",
}

__all__ = [
    "AgentRunner",
    "AstrBotSkillLoader",
    "DynamicAgentManager",
    "MCPBridge",
]


def __getattr__(name: str) -> Any:
    """按需加载导出符号，避免包导入副作用与循环依赖。"""

    module_name = _MODULE_BY_EXPORT.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
