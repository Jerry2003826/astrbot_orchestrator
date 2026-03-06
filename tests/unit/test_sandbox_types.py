"""CodeSandbox 类型对象测试。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from astrbot_orchestrator_v5.sandbox.types import ExecChunk, ExecResult, SandboxFile, SandboxStatus

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


def test_exec_result_success_only_when_exit_zero_and_no_errors() -> None:
    """执行结果成功标记应同时依赖退出码和错误文本。"""

    ok_result = ExecResult(text="hello", exit_code=0)
    error_result = ExecResult(text="hello", errors="boom", exit_code=0)
    failed_result = ExecResult(text="hello", exit_code=1)

    assert ok_result.success is True
    assert error_result.success is False
    assert failed_result.success is False


def test_exec_result_string_representation_renders_text_errors_and_images() -> None:
    """执行结果字符串应按文本、错误、图片数量顺序输出。"""

    result = ExecResult(
        text="hello",
        errors="boom",
        images=["img-1", "img-2"],
        exit_code=1,
    )

    assert str(result) == "hello\n[ERROR] boom\n[2 image(s)]"
    assert str(ExecResult()) == "(no output)"


def test_exec_chunk_string_returns_raw_content() -> None:
    """流式块字符串化应直接返回内容本身。"""

    chunk = ExecChunk(type="stderr", content="traceback line")

    assert str(chunk) == "traceback line"


def test_sandbox_file_exposes_name_extension_and_string_value() -> None:
    """文件对象应正确暴露名称、扩展名与字符串表示。"""

    file_obj = SandboxFile(path="assets/logo.png", size=12, content=b"png-bytes")

    assert file_obj.name == "logo.png"
    assert file_obj.extension == ".png"
    assert str(file_obj) == "assets/logo.png (12.0 B)"


def test_sandbox_file_size_human_handles_unknown_and_scaled_units() -> None:
    """文件大小应支持 unknown、KB 与 PB 等单位格式化。"""

    unknown_file = SandboxFile(path="unknown.bin", size=-1)
    kb_file = SandboxFile(path="bundle.js", size=1536)
    pb_file = SandboxFile(path="archive.bin", size=1024**5)

    assert unknown_file.size_human == "unknown"
    assert kb_file.size_human == "1.5 KB"
    assert pb_file.size_human == "1.0 PB"


def test_sandbox_status_string_reflects_health_state() -> None:
    """状态对象字符串应反映模式、健康状态与会话 ID。"""

    healthy = SandboxStatus(healthy=True, mode="shipyard", session_id="session-1")
    unhealthy = SandboxStatus(healthy=False, mode="local", session_id="session-2")

    assert str(healthy) == "Sandbox(shipyard) ✅ healthy session=session-1"
    assert str(unhealthy) == "Sandbox(local) ❌ unhealthy session=session-2"
