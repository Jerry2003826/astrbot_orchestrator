"""简化版 Prompt -> Model -> Parser 运行时原语。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from string import Template
from typing import Any, Awaitable, Callable, Generic, Protocol, TypeVar, cast

TOutput = TypeVar("TOutput", covariant=True)


class OutputParser(Protocol[TOutput]):
    """输出解析器协议。"""

    def parse(self, text: str) -> TOutput:
        """解析模型原始文本输出。"""


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    """使用 `$var` 占位符的轻量 Prompt 模板。"""

    template: str

    def render(self, variables: dict[str, Any]) -> str:
        """渲染模板变量。"""

        normalized = {key: str(value) for key, value in variables.items()}
        return Template(self.template).substitute(normalized)


@dataclass(frozen=True, slots=True)
class TextOutputParser:
    """文本输出解析器。"""

    strip_code_fences: bool = False

    def parse(self, text: str) -> str:
        """解析文本输出。"""

        return _strip_markdown_code_fences(text) if self.strip_code_fences else text


@dataclass(frozen=True, slots=True)
class JsonOutputParser(Generic[TOutput]):
    """JSON 输出解析器。"""

    def parse(self, text: str) -> TOutput:
        """解析 Markdown 包裹的 JSON 输出。"""

        cleaned = _strip_markdown_code_fences(text).strip()
        return cast(TOutput, json.loads(cleaned))


@dataclass(frozen=True, slots=True)
class CallableOutputParser(Generic[TOutput]):
    """将普通函数包装成输出解析器。"""

    parse_fn: Callable[[str], TOutput]

    def parse(self, text: str) -> TOutput:
        """执行自定义解析逻辑。"""

        return self.parse_fn(text)


@dataclass(slots=True)
class PromptModelParserPipeline(Generic[TOutput]):
    """轻量版声明式链路：Prompt -> Model -> Parser。"""

    prompt_template: PromptTemplate
    model_runner: Callable[[str, str, str | None], Awaitable[str]]
    output_parser: OutputParser[TOutput]
    system_prompt: str | None = None

    async def ainvoke(self, provider_id: str, variables: dict[str, Any]) -> TOutput:
        """异步执行整条链并返回解析结果。"""

        prompt = self.prompt_template.render(variables)
        raw_output = await self.model_runner(provider_id, prompt, self.system_prompt)
        return self.output_parser.parse(raw_output)


def _strip_markdown_code_fences(text: str) -> str:
    """移除 Markdown 代码围栏，便于解析 JSON 或纯文本。"""

    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if not lines:
        return stripped

    if lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()
