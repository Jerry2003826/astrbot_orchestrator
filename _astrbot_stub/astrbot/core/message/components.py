"""astrbot.core.message.components 测试桩（最小组件集）。"""

from dataclasses import dataclass


class BaseMessageComponent:
    pass


@dataclass
class Plain(BaseMessageComponent):
    text: str


@dataclass
class Image(BaseMessageComponent):
    file: str = ""

    @classmethod
    def fromURL(cls, url: str) -> "Image":
        return cls(file=url)

    @classmethod
    def fromFileSystem(cls, path: str) -> "Image":
        return cls(file=path)


@dataclass
class At(BaseMessageComponent):
    qq: str = ""
    name: str = ""
