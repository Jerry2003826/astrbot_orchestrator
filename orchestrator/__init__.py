"""
编排器核心模块

基于 AstrBot 原生能力构建
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .agent_coordinator import AgentCoordinator
    from .capability_builder import AgentCapabilityBuilder
    from .core import DynamicOrchestrator
    from .dynamic_agent_manager import DynamicAgentManager
    from .mcp_bridge import MCPBridge
    from .meta_orchestrator import MetaOrchestrator
    from .skill_loader import AstrBotSkillLoader
    from .task_analyzer import TaskAnalyzer

_MODULE_BY_EXPORT = {
    "AgentCoordinator": "agent_coordinator",
    "AgentCapabilityBuilder": "capability_builder",
    "AstrBotSkillLoader": "skill_loader",
    "DynamicAgentManager": "dynamic_agent_manager",
    "DynamicOrchestrator": "core",
    "MCPBridge": "mcp_bridge",
    "MetaOrchestrator": "meta_orchestrator",
    "TaskAnalyzer": "task_analyzer",
}

__all__ = [
    "DynamicOrchestrator",
    "AstrBotSkillLoader",
    "MCPBridge",
    "MetaOrchestrator",
    "DynamicAgentManager",
    "TaskAnalyzer",
    "AgentCoordinator",
    "AgentCapabilityBuilder",
]


def __getattr__(name: str) -> Any:
    """按需加载导出符号，避免包导入副作用与循环依赖。"""

    module_name = _MODULE_BY_EXPORT.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    try:
        module = import_module(f".{module_name}", __name__)
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("astrbot"):
            globals()[name] = None
            return None
        raise

    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """返回支持的导出符号。"""

    return sorted(set(globals()) | set(__all__))
