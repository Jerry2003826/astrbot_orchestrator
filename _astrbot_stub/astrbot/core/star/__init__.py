"""astrbot.core.star 测试桩。"""

from .base import Star
from .context import Context
from .star import StarMetadata, star_map, star_registry
from .star_tools import StarTools

__all__ = [
    "Context",
    "Star",
    "StarMetadata",
    "StarTools",
    "star_map",
    "star_registry",
]
