"""
AstrBot 动态智能体编排器插件

支持工作流、Skill、多模型选择的智能体编排系统
"""

from typing import Any

__version__ = "3.0.0"
__author__ = "lijiarui"

try:
    from .main import OrchestratorPlugin
except ModuleNotFoundError as exc:
    if exc.name and exc.name.startswith("astrbot"):
        OrchestratorPlugin: Any = None
    else:
        raise

__all__ = ["OrchestratorPlugin"]
