"""astrbot.core.star.star_tools 测试桩，对齐 v4.25.5 StarTools。"""

import inspect
import os
from pathlib import Path
from typing import Any, ClassVar

from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .star import star_map


class StarTools:
    _context: ClassVar[Any] = None

    @classmethod
    def initialize(cls, context: Any) -> None:
        cls._context = context

    @classmethod
    async def send_message(cls, session: Any, message_chain: Any) -> bool:
        if cls._context is None:
            raise ValueError("StarTools not initialized")
        return await cls._context.send_message(session, message_chain)

    @classmethod
    def activate_llm_tool(cls, name: str) -> bool:
        if cls._context is None:
            raise ValueError("StarTools not initialized")
        return cls._context.activate_llm_tool(name)

    @classmethod
    def deactivate_llm_tool(cls, name: str) -> bool:
        if cls._context is None:
            raise ValueError("StarTools not initialized")
        return cls._context.deactivate_llm_tool(name)

    @classmethod
    def get_data_dir(cls, plugin_name: str | None = None) -> Path:
        """返回 data/plugin_data/{plugin_name} 的绝对路径，必要时自动创建。"""
        if not plugin_name:
            frame = inspect.currentframe()
            module = None
            if frame:
                frame = frame.f_back
                module = inspect.getmodule(frame)
            if not module:
                raise RuntimeError("无法获取调用者模块信息")
            metadata = star_map.get(module.__name__, None)
            if not metadata:
                raise RuntimeError(f"无法获取模块 {module.__name__} 的元数据信息")
            plugin_name = metadata.name

        if not plugin_name:
            raise ValueError("无法获取插件名称")

        data_dir = Path(os.path.join(get_astrbot_data_path(), "plugin_data", plugin_name))
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir.resolve()
