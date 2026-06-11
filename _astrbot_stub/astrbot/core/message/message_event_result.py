"""astrbot.core.message.message_event_result 测试桩，对齐 v4.25.5。"""

from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
import enum

from astrbot.core.message.components import BaseMessageComponent, Image, Plain


@dataclass
class MessageChain:
    chain: list[BaseMessageComponent] = field(default_factory=list)
    use_t2i_: bool | None = None
    use_markdown_: bool | None = None
    type: str | None = None

    def message(self, message: str) -> "MessageChain":
        self.chain.append(Plain(message))
        return self

    def url_image(self, url: str) -> "MessageChain":
        self.chain.append(Image.fromURL(url))
        return self

    def file_image(self, path: str) -> "MessageChain":
        self.chain.append(Image.fromFileSystem(path))
        return self

    def get_plain_text(self, with_other_comps_mark: bool = False) -> str:
        if not with_other_comps_mark:
            return " ".join(comp.text for comp in self.chain if isinstance(comp, Plain))
        texts = []
        for comp in self.chain:
            if isinstance(comp, Plain):
                texts.append(comp.text)
            else:
                texts.append(f"[{comp.__class__.__name__}]")
        return " ".join(texts)


class EventResultType(enum.Enum):
    CONTINUE = enum.auto()
    STOP = enum.auto()


class ResultContentType(enum.Enum):
    LLM_RESULT = enum.auto()
    AGENT_RUNNER_ERROR = enum.auto()
    GENERAL_RESULT = enum.auto()
    STREAMING_RESULT = enum.auto()
    STREAMING_FINISH = enum.auto()


@dataclass
class MessageEventResult(MessageChain):
    result_type: EventResultType | None = field(
        default_factory=lambda: EventResultType.CONTINUE,
    )
    result_content_type: ResultContentType | None = field(
        default_factory=lambda: ResultContentType.GENERAL_RESULT,
    )
    async_stream: AsyncGenerator | None = None

    def stop_event(self) -> "MessageEventResult":
        self.result_type = EventResultType.STOP
        return self

    def continue_event(self) -> "MessageEventResult":
        self.result_type = EventResultType.CONTINUE
        return self

    def is_stopped(self) -> bool:
        return self.result_type == EventResultType.STOP

    def set_result_content_type(self, typ: ResultContentType) -> "MessageEventResult":
        self.result_content_type = typ
        return self

    def is_llm_result(self) -> bool:
        return self.result_content_type == ResultContentType.LLM_RESULT


CommandResult = MessageEventResult
