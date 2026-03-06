"""SelfDebugger 单元测试。"""

from __future__ import annotations

import builtins
import json
import sys
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

import astrbot_orchestrator_v5.autonomous.debugger as debugger_module
from astrbot_orchestrator_v5.autonomous.debugger import SelfDebugger

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


class FakeDebugContext:
    """提供调试器所需最小接口的上下文替身。"""

    def __init__(
        self,
        llm_responses: list[str] | None = None,
        llm_error: Exception | None = None,
        stars: list[Any] | None = None,
        providers: list[Any] | None = None,
        mcp_clients: dict[str, Any] | None = None,
        status_error: Exception | None = None,
    ) -> None:
        """保存 LLM 返回值与系统状态数据。"""

        self._llm_responses = list(llm_responses or [])
        self._llm_error = llm_error
        self._stars = list(stars or [])
        self._status_error = status_error
        self.llm_calls: list[dict[str, Any]] = []
        self.provider_manager = SimpleNamespace(
            get_all_providers=lambda: list(providers or []),
            llm_tools=SimpleNamespace(mcp_client_dict=mcp_clients or {}),
        )

    async def llm_generate(self, **kwargs: Any) -> SimpleNamespace:
        """记录 LLM 调用并返回预设结果。"""

        self.llm_calls.append(kwargs)
        if self._llm_error is not None:
            raise self._llm_error
        text = self._llm_responses.pop(0) if self._llm_responses else ""
        return SimpleNamespace(completion_text=text)

    def get_all_stars(self) -> list[Any]:
        """返回插件列表或按需抛出异常。"""

        if self._status_error is not None:
            raise self._status_error
        return list(self._stars)


@pytest.fixture(autouse=True)
def reset_error_history() -> None:
    """每个测试前清空共享错误历史。"""

    SelfDebugger._error_history.clear()


def test_self_debugger_get_recent_errors_returns_empty_message() -> None:
    """没有错误记录时应返回空历史提示。"""

    debugger = SelfDebugger(context=FakeDebugContext())

    assert debugger.get_recent_errors() == "📋 暂无错误记录"


def test_self_debugger_record_error_and_limit_recent_errors() -> None:
    """记录错误后应按倒序渲染最近错误，并遵守 limit。"""

    debugger = SelfDebugger(context=FakeDebugContext())

    try:
        raise ValueError("first boom")
    except Exception as error:
        SelfDebugger.record_error(error, {"step": "first"})

    try:
        raise KeyError("second boom")
    except Exception as error:
        SelfDebugger.record_error(error, {"step": "second"})

    rendered = debugger.get_recent_errors(limit=1)

    assert "KeyError" in rendered
    assert "ValueError" not in rendered
    assert "second boom" in rendered
    assert SelfDebugger._error_history[-1]["context"] == {"step": "second"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_fragments"),
    [
        (
            ConnectionError("dns failure"),
            ["🔍 **网络连接问题**", "检查网络连接是否正常", "考虑增加超时时间"],
        ),
        (
            PermissionError("权限不足"),
            ["🔍 **权限问题**", "管理员权限", "文件/目录权限"],
        ),
        (
            ModuleNotFoundError("No module named 'httpx'"),
            ["🔍 **缺少依赖: httpx**", "pip install httpx"],
        ),
        (
            json.JSONDecodeError("Expecting value", "x", 0),
            ["🔍 **JSON 解析错误**", "检查 API 响应格式"],
        ),
        (
            AttributeError("'NoneType' object has no attribute 'x'"),
            ["🔍 **属性访问错误**", "对象可能为 None"],
        ),
        (
            KeyError("missing"),
            ["🔍 **键不存在**", "使用 .get() 方法避免错误"],
        ),
        (
            ValueError("plain boom"),
            ["🔍 **ValueError**", "- 错误信息: plain boom"],
        ),
    ],
)
async def test_self_debugger_analyze_error_classifies_common_errors(
    error: Exception,
    expected_fragments: list[str],
) -> None:
    """错误分析应对常见异常给出对应诊断。"""

    debugger = SelfDebugger(context=FakeDebugContext())

    result = await debugger.analyze_error(error=error, traceback_info="", context={"request": "demo"})

    for fragment in expected_fragments:
        assert fragment in result
    assert len(SelfDebugger._error_history) == 1


@pytest.mark.asyncio
async def test_self_debugger_analyze_error_extracts_relevant_traceback_lines() -> None:
    """错误分析应只保留最近几条关键堆栈信息。"""

    debugger = SelfDebugger(context=FakeDebugContext())
    traceback_info = "\n".join(
        [
            "noise line",
            'File "/tmp/old.py", line 1, in old',
            "astrbot.module.old",
            'File "/tmp/new.py", line 2, in new',
            "astrbot.module.new",
            'File "/tmp/latest.py", line 3, in latest',
        ]
    )

    result = await debugger.analyze_error(
        error=ValueError("boom"),
        traceback_info=traceback_info,
        context=None,
    )

    assert "📍 **错误位置:**" in result
    assert "/tmp/old.py" not in result
    assert "astrbot.module.old" in result
    assert "/tmp/new.py" in result
    assert "/tmp/latest.py" in result


@pytest.mark.asyncio
async def test_self_debugger_analyze_error_ignores_traceback_without_relevant_lines() -> None:
    """没有关键行的 traceback 不应追加错误位置区块。"""

    debugger = SelfDebugger(context=FakeDebugContext())

    result = await debugger.analyze_error(
        error=ValueError("boom"),
        traceback_info="plain line 1\nplain line 2",
        context=None,
    )

    assert "📍 **错误位置:**" not in result


@pytest.mark.asyncio
async def test_self_debugger_get_system_status_reports_runtime_details(
    monkeypatch: "MonkeyPatch",
) -> None:
    """系统状态应包含 Python、内存、插件、模型和 MCP 信息。"""

    psutil_module = ModuleType("psutil")
    psutil_module.virtual_memory = lambda: SimpleNamespace(percent=42)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "psutil", psutil_module)

    try:
        raise RuntimeError("boom")
    except Exception as error:
        SelfDebugger.record_error(error)

    context = FakeDebugContext(
        stars=[SimpleNamespace(activated=True), SimpleNamespace(activated=False)],
        providers=[object(), object()],
        mcp_clients={
            "a": SimpleNamespace(active=True),
            "b": SimpleNamespace(active=False),
        },
    )
    debugger = SelfDebugger(context=context)

    result = await debugger.get_system_status()

    assert "• Python:" in result
    assert "• 内存: 42% 使用" in result
    assert "• 插件: 1 个激活" in result
    assert "• 模型提供商: 2 个" in result
    assert "• MCP 服务: 1 个连接" in result
    assert "• 最近错误: 1 条" in result


@pytest.mark.asyncio
async def test_self_debugger_get_system_status_handles_import_and_context_errors(
    monkeypatch: "MonkeyPatch",
) -> None:
    """缺少 psutil 或上下文异常时应回退到兜底文本。"""

    original_import = builtins.__import__

    def fake_import(
        name: str,
        globals_dict: dict[str, Any] | None = None,
        locals_dict: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        """只对 psutil 模块模拟导入失败。"""

        if name == "psutil":
            raise ImportError("missing")
        return original_import(name, globals_dict, locals_dict, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    debugger = SelfDebugger(
        context=FakeDebugContext(status_error=RuntimeError("ctx broken")),
    )

    result = await debugger.get_system_status()

    assert "• 内存: 无法获取 (需要 psutil)" in result
    assert "• AstrBot 状态: 部分获取失败 (ctx broken)" in result
    assert "• 最近错误: 0 条" in result


@pytest.mark.asyncio
async def test_self_debugger_analyze_problem_builds_prompt_and_returns_llm_text(
    monkeypatch: "MonkeyPatch",
) -> None:
    """问题分析应组合系统状态与最近错误，并调用 LLM。"""

    context = FakeDebugContext(llm_responses=["analysis-result"])
    debugger = SelfDebugger(context=context)

    async def fake_get_system_status(self: SelfDebugger) -> str:
        """返回固定系统状态文本。"""

        del self
        return "status-ok"

    def fake_get_recent_errors(self: SelfDebugger, limit: int = 10) -> str:
        """返回固定错误历史文本。"""

        del self
        assert limit == 5
        return "errors-ok"

    monkeypatch.setattr(SelfDebugger, "get_system_status", fake_get_system_status)
    monkeypatch.setattr(SelfDebugger, "get_recent_errors", fake_get_recent_errors)

    result = await debugger.analyze_problem("服务启动失败", "provider-x")

    assert result == "analysis-result"
    llm_call = context.llm_calls[0]
    assert llm_call["chat_provider_id"] == "provider-x"
    assert "服务启动失败" in llm_call["prompt"]
    assert "status-ok" in llm_call["prompt"]
    assert "errors-ok" in llm_call["prompt"]
    assert "AstrBot 技术支持专家" in llm_call["system_prompt"]


@pytest.mark.asyncio
async def test_self_debugger_analyze_problem_returns_error_when_llm_fails(
    monkeypatch: "MonkeyPatch",
) -> None:
    """问题分析失败时应返回统一错误提示。"""

    context = FakeDebugContext(llm_error=RuntimeError("llm down"))
    debugger = SelfDebugger(context=context)

    async def fake_get_system_status(self: SelfDebugger) -> str:
        """返回固定系统状态文本。"""

        del self
        return "status-ok"

    def fake_get_recent_errors(self: SelfDebugger, limit: int = 10) -> str:
        """返回固定错误历史文本。"""

        del self
        del limit
        return "errors-ok"

    monkeypatch.setattr(SelfDebugger, "get_system_status", fake_get_system_status)
    monkeypatch.setattr(SelfDebugger, "get_recent_errors", fake_get_recent_errors)

    result = await debugger.analyze_problem("服务启动失败", "provider-x")

    assert result == "❌ 分析失败: llm down"


@pytest.mark.asyncio
async def test_self_debugger_suggest_fix_builds_prompt_and_returns_llm_text(
    monkeypatch: "MonkeyPatch",
) -> None:
    """修复建议应带上错误信息、代码上下文和 traceback。"""

    context = FakeDebugContext(llm_responses=["fix-result"])
    debugger = SelfDebugger(context=context)
    monkeypatch.setattr(debugger_module.traceback, "format_exc", lambda: "traceback-line")

    result = await debugger.suggest_fix(
        error=ValueError("boom"),
        code_context="print(1)",
        provider_id="provider-y",
    )

    assert result == "fix-result"
    llm_call = context.llm_calls[0]
    assert llm_call["chat_provider_id"] == "provider-y"
    assert "ValueError" in llm_call["prompt"]
    assert "boom" in llm_call["prompt"]
    assert "print(1)" in llm_call["prompt"]
    assert "traceback-line" in llm_call["prompt"]
    assert llm_call["system_prompt"] == "你是一个 Python 调试专家。"


@pytest.mark.asyncio
async def test_self_debugger_suggest_fix_returns_error_when_llm_fails(
    monkeypatch: "MonkeyPatch",
) -> None:
    """修复建议失败时应返回统一兜底提示。"""

    context = FakeDebugContext(llm_error=RuntimeError("llm down"))
    debugger = SelfDebugger(context=context)
    monkeypatch.setattr(debugger_module.traceback, "format_exc", lambda: "traceback-line")

    result = await debugger.suggest_fix(
        error=ValueError("boom"),
        code_context="print(1)",
        provider_id="provider-z",
    )

    assert result == "❌ 无法生成修复建议: llm down"
