"""astrbot.core.star.star 测试桩（StarMetadata 与注册表）。"""

from dataclasses import dataclass, field
from typing import Any

star_registry: list["StarMetadata"] = []
star_map: dict[str, "StarMetadata"] = {}


@dataclass
class StarMetadata:
    name: str | None = None
    author: str | None = None
    desc: str | None = None
    short_desc: str | None = None
    version: str | None = None
    repo: str | None = None

    star_cls_type: type | None = None
    module_path: str | None = None
    star_cls: Any = None
    module: Any = None
    root_dir_name: str | None = None
    reserved: bool = False
    activated: bool = True
    config: Any = None

    star_handler_full_names: list[str] = field(default_factory=list)
    display_name: str | None = None
    logo_path: str | None = None
    support_platforms: list[str] = field(default_factory=list)
    astrbot_version: str | None = None

    def __str__(self) -> str:
        return f"Plugin {self.name} ({self.version}) by {self.author}: {self.desc}"

    __repr__ = __str__
