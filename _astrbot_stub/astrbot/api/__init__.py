"""astrbot.api 测试桩，对齐 v4.25.5 导出面。"""

from astrbot import logger
from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.star.register import register_agent as agent
from astrbot.core.star.register import register_llm_tool as llm_tool

__all__ = [
    "AstrBotConfig",
    "FunctionTool",
    "ToolSet",
    "agent",
    "llm_tool",
    "logger",
]
