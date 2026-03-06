"""Prompt/Model/Parser 运行时链测试。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from astrbot_orchestrator_v5.runtime.pipeline import (
    CallableOutputParser,
    JsonOutputParser,
    PromptModelParserPipeline,
    PromptTemplate,
    TextOutputParser,
    _strip_markdown_code_fences,
)

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture
    from _pytest.fixtures import FixtureRequest
    from _pytest.logging import LogCaptureFixture
    from _pytest.monkeypatch import MonkeyPatch
    from pytest_mock.plugin import MockerFixture

    _PYTEST_TYPE_IMPORTS = (
        CaptureFixture,
        FixtureRequest,
        LogCaptureFixture,
        MonkeyPatch,
        MockerFixture,
    )


@pytest.mark.asyncio
async def test_prompt_model_parser_pipeline_renders_prompt_and_parses_json() -> None:
    """管道应渲染 prompt，并解析 Markdown 包裹的 JSON。"""

    captured: dict[str, str | None] = {}

    async def model_runner(provider_id: str, prompt: str, system_prompt: str | None) -> str:
        captured["provider_id"] = provider_id
        captured["prompt"] = prompt
        captured["system_prompt"] = system_prompt
        return '```json\n{"intent": "reasoning"}\n```'

    pipeline = PromptModelParserPipeline[dict[str, str]](
        prompt_template=PromptTemplate("问题：$question"),
        model_runner=model_runner,
        output_parser=JsonOutputParser(),
        system_prompt="只返回 JSON",
    )

    result = await pipeline.ainvoke(
        provider_id="provider-x",
        variables={"question": "什么是 LCEL？"},
    )

    assert result == {"intent": "reasoning"}
    assert captured["provider_id"] == "provider-x"
    assert captured["prompt"] == "问题：什么是 LCEL？"
    assert captured["system_prompt"] == "只返回 JSON"


def test_runtime_pipeline_text_and_callable_output_parsers_cover_branches() -> None:
    """文本与可调用解析器应覆盖 strip 与自定义解析分支。"""

    raw_parser = TextOutputParser(strip_code_fences=False)
    fenced_parser = TextOutputParser(strip_code_fences=True)
    callable_parser = CallableOutputParser[int](parse_fn=lambda text: len(text))

    assert raw_parser.parse("```json\nhello\n```") == "```json\nhello\n```"
    assert fenced_parser.parse("```json\nhello\n```") == "hello"
    assert callable_parser.parse("hello") == 5


def test_runtime_pipeline_strip_markdown_code_fences_handles_plain_and_unclosed_text() -> None:
    """剥离围栏应覆盖普通文本、无结束围栏等路径。"""

    assert _strip_markdown_code_fences("plain text") == "plain text"
    assert _strip_markdown_code_fences("```json\n{\"a\": 1}") == '{"a": 1}'


def test_runtime_pipeline_strip_markdown_code_fences_covers_defensive_branches() -> None:
    """防御性分支应在异常字符串实现下保持稳定。"""

    class EmptyLinesStr(str):
        """模拟 `splitlines()` 返回空列表的极端字符串。"""

        def strip(self, chars: str | None = None) -> "EmptyLinesStr":
            """返回自身，便于继续走自定义逻辑。"""

            del chars
            return self

        def splitlines(self, keepends: bool = False) -> list[str]:
            """返回空列表。"""

            del keepends
            return []

    class NonFenceFirstLineStr(str):
        """模拟首行不是代码围栏的极端字符串。"""

        def strip(self, chars: str | None = None) -> "NonFenceFirstLineStr":
            """返回自身，便于继续走自定义逻辑。"""

            del chars
            return self

        def splitlines(self, keepends: bool = False) -> list[str]:
            """返回一个不以围栏开头的首行。"""

            del keepends
            return ["not-fence", "payload"]

    assert _strip_markdown_code_fences(EmptyLinesStr("```")) == "```"
    assert _strip_markdown_code_fences(NonFenceFirstLineStr("```")) == "not-fence\npayload"
