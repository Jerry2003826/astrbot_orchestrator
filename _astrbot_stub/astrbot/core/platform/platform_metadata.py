"""astrbot.core.platform.platform_metadata 测试桩。"""

from dataclasses import dataclass


@dataclass
class PlatformMetadata:
    name: str
    description: str = ""
    id: str = ""
