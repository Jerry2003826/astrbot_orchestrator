"""本地沙盒测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from astrbot_orchestrator_v5.sandbox.local_sandbox import LocalSandbox
from astrbot_orchestrator_v5.sandbox.types import ExecChunk, ExecResult
from astrbot_orchestrator_v5.shared.path_safety import UnsafePathError

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


class DummyProcess:
    """最小可用的 subprocess 替身。"""

    def __init__(self) -> None:
        """初始化默认返回值。"""

        self.returncode = 0

    async def communicate(self) -> tuple[bytes, bytes]:
        """返回空输出。"""

        return (b"", b"")

    async def wait(self) -> int:
        """返回退出码。"""

        return self.returncode


class StreamlessProcess:
    """没有 stdout/stderr 流的进程替身。"""

    def __init__(self) -> None:
        """初始化空流与退出码。"""

        self.stdout = None
        self.stderr = None
        self.returncode = 0

    async def wait(self) -> int:
        """返回退出码。"""

        return self.returncode


async def collect_chunks(chunks: Any) -> list[ExecChunk]:
    """收集流式执行结果。"""

    return [chunk async for chunk in chunks]


@pytest.mark.asyncio
async def test_local_sandbox_mode_and_lifecycle_manage_started_flag(tmp_path: Path) -> None:
    """本地沙盒应暴露 local 模式并正确切换启动状态。"""

    sandbox = LocalSandbox(cwd=str(tmp_path))

    assert sandbox.mode == "local"
    assert sandbox._started is False
    assert tmp_path.exists()

    await sandbox.astart()
    assert sandbox._started is True

    await sandbox.astop()
    assert sandbox._started is False


@pytest.mark.asyncio
async def test_local_sandbox_exec_python_extracts_images_and_errors(tmp_path: Path) -> None:
    """Python 执行应提取 image 标签、保留 stderr，并返回成功退出码。"""

    sandbox = LocalSandbox(cwd=str(tmp_path))
    code = (
        "import sys\n"
        "print('<image>img-base64</image>')\n"
        "print('visible-output')\n"
        "print('warn-output', file=sys.stderr)\n"
    )

    result = await sandbox.aexec(code)

    assert result.text == "visible-output"
    assert result.images == ["img-base64"]
    assert result.errors == "warn-output\n"
    assert result.exit_code == 0
    assert result.kernel == "ipython"


@pytest.mark.asyncio
async def test_local_sandbox_exec_bash_uses_custom_workdir(tmp_path: Path) -> None:
    """bash 执行应使用传入的工作目录。"""

    sandbox = LocalSandbox(cwd=str(tmp_path))
    work_dir = tmp_path / "nested"
    work_dir.mkdir()

    result = await sandbox.aexec("pwd", kernel="bash", cwd=str(work_dir))

    assert result.text.strip() == str(work_dir)
    assert result.exit_code == 0
    assert result.kernel == "bash"


@pytest.mark.asyncio
async def test_local_sandbox_exec_returns_timeout_result(
    monkeypatch: "MonkeyPatch",
    tmp_path: Path,
) -> None:
    """执行超时时应返回统一超时结果。"""

    sandbox = LocalSandbox(cwd=str(tmp_path))

    async def fake_create_subprocess_exec(*args: Any, **kwargs: Any) -> DummyProcess:
        """返回一个假的进程对象。"""

        del args
        del kwargs
        return DummyProcess()

    async def fake_wait_for(awaitable: Any, timeout: float | None = None) -> tuple[bytes, bytes]:
        """模拟超时。"""

        del timeout
        close_awaitable = getattr(awaitable, "close", None)
        if callable(close_awaitable):
            close_awaitable()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    result = await sandbox.aexec("print('x')", timeout=0.5)

    assert result.exit_code == -1
    assert result.errors == "执行超时（0.5秒）"
    assert result.kernel == "ipython"


@pytest.mark.asyncio
async def test_local_sandbox_exec_returns_error_on_subprocess_failure(
    monkeypatch: "MonkeyPatch",
    tmp_path: Path,
) -> None:
    """创建 subprocess 失败时应返回错误结果。"""

    sandbox = LocalSandbox(cwd=str(tmp_path))

    async def fake_create_subprocess_exec(*args: Any, **kwargs: Any) -> DummyProcess:
        """模拟创建进程失败。"""

        del args
        del kwargs
        raise RuntimeError("spawn failed")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = await sandbox.aexec("print('x')")

    assert result.exit_code == -1
    assert result.errors == "spawn failed"


@pytest.mark.asyncio
async def test_local_sandbox_stream_exec_emits_stdout_stderr_and_status(tmp_path: Path) -> None:
    """流式执行应依次产出 stdout、stderr 与状态块。"""

    sandbox = LocalSandbox(cwd=str(tmp_path))
    code = "import sys\nprint('out-line')\nprint('err-line', file=sys.stderr)\n"

    chunks = await collect_chunks(sandbox.astream_exec(code))

    assert [chunk.type for chunk in chunks] == ["stdout", "stderr", "status"]
    assert chunks[0].content == "out-line\n"
    assert chunks[1].content == "err-line\n"
    assert chunks[2].content == "exit_code=0"


@pytest.mark.asyncio
async def test_local_sandbox_stream_exec_supports_bash_kernel(tmp_path: Path) -> None:
    """流式执行应支持 bash 内核。"""

    sandbox = LocalSandbox(cwd=str(tmp_path))

    chunks = await collect_chunks(sandbox.astream_exec("printf 'bash-out\\n'", kernel="bash"))

    assert chunks[0].type == "stdout"
    assert chunks[0].content == "bash-out\n"
    assert chunks[-1].content == "exit_code=0"


@pytest.mark.asyncio
async def test_local_sandbox_stream_exec_handles_missing_streams(
    monkeypatch: "MonkeyPatch",
    tmp_path: Path,
) -> None:
    """缺少 stdout/stderr 流时仍应返回状态块。"""

    sandbox = LocalSandbox(cwd=str(tmp_path))

    async def fake_create_subprocess_exec(*args: Any, **kwargs: Any) -> StreamlessProcess:
        """返回没有输出流的进程对象。"""

        del args
        del kwargs
        return StreamlessProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    chunks = await collect_chunks(sandbox.astream_exec("print('x')"))

    assert len(chunks) == 1
    assert chunks[0].type == "status"
    assert chunks[0].content == "exit_code=0"


@pytest.mark.asyncio
async def test_local_sandbox_stream_exec_returns_timeout_chunk(
    monkeypatch: "MonkeyPatch",
    tmp_path: Path,
) -> None:
    """流式执行超时时应返回 stderr 块。"""

    sandbox = LocalSandbox(cwd=str(tmp_path))

    async def fake_create_subprocess_exec(*args: Any, **kwargs: Any) -> DummyProcess:
        """模拟创建进程时直接超时。"""

        del args
        del kwargs
        raise asyncio.TimeoutError()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    chunks = await collect_chunks(sandbox.astream_exec("print('x')", timeout=1.5))

    assert len(chunks) == 1
    assert chunks[0].type == "stderr"
    assert chunks[0].content == "执行超时（1.5秒）"


@pytest.mark.asyncio
async def test_local_sandbox_stream_exec_returns_error_chunk_on_exception(
    monkeypatch: "MonkeyPatch",
    tmp_path: Path,
) -> None:
    """流式执行异常时应返回 stderr 错误块。"""

    sandbox = LocalSandbox(cwd=str(tmp_path))

    async def fake_create_subprocess_exec(*args: Any, **kwargs: Any) -> DummyProcess:
        """模拟执行失败。"""

        del args
        del kwargs
        raise RuntimeError("stream failed")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    chunks = await collect_chunks(sandbox.astream_exec("print('x')"))

    assert len(chunks) == 1
    assert chunks[0].type == "stderr"
    assert chunks[0].content == "stream failed"


@pytest.mark.asyncio
async def test_local_sandbox_rejects_path_traversal_on_upload(tmp_path: Path) -> None:
    """上传文件时应拒绝路径穿越。"""

    sandbox = LocalSandbox(cwd=str(tmp_path))

    with pytest.raises(UnsafePathError):
        await sandbox.aupload("../escape.txt", "boom")


@pytest.mark.asyncio
async def test_local_sandbox_uploads_downloads_and_lists_files_within_workspace(
    tmp_path: Path,
) -> None:
    """安全路径应可上传、下载，并按路径排序列出文件。"""

    sandbox = LocalSandbox(cwd=str(tmp_path))

    text_file = await sandbox.aupload("safe/output.txt", "hello")
    binary_file = await sandbox.aupload("safe/bytes.bin", b"\x00\x01")
    (tmp_path / "safe" / "nested").mkdir()
    downloaded = await sandbox.adownload("safe/output.txt")
    listed = await sandbox.alist_files("safe")

    assert text_file.path == "safe/output.txt"
    assert binary_file.size == 2
    assert downloaded.path == "safe/output.txt"
    assert downloaded.content == b"hello"
    assert [item.path for item in listed] == ["safe/bytes.bin", "safe/output.txt"]


@pytest.mark.asyncio
async def test_local_sandbox_download_missing_file_raises(tmp_path: Path) -> None:
    """下载不存在文件时应抛出 FileNotFoundError。"""

    sandbox = LocalSandbox(cwd=str(tmp_path))

    with pytest.raises(FileNotFoundError, match="文件不存在"):
        await sandbox.adownload("missing.txt")


@pytest.mark.asyncio
async def test_local_sandbox_list_files_returns_empty_for_invalid_or_missing_path(
    tmp_path: Path,
) -> None:
    """非法路径或不存在目录应返回空列表。"""

    sandbox = LocalSandbox(cwd=str(tmp_path))

    assert await sandbox.alist_files("../escape") == []
    assert await sandbox.alist_files("missing") == []


@pytest.mark.asyncio
async def test_local_sandbox_install_and_list_packages_delegate_to_exec(
    monkeypatch: "MonkeyPatch",
    tmp_path: Path,
) -> None:
    """包管理接口应通过 aexec 委托到 bash 执行。"""

    sandbox = LocalSandbox(cwd=str(tmp_path))
    calls: list[tuple[str, str]] = []

    async def fake_aexec(
        code: str,
        kernel: str = "ipython",
        timeout: float | None = None,
        cwd: str | None = None,
    ) -> ExecResult:
        """记录命令并返回预设结果。"""

        del timeout
        del cwd
        calls.append((code, kernel))
        if code.startswith("pip install"):
            return ExecResult(text="done", exit_code=0, kernel=kernel)
        return ExecResult(text="httpx\nrich\n", exit_code=0, kernel=kernel)

    monkeypatch.setattr(sandbox, "aexec", fake_aexec)

    install_result = await sandbox.ainstall("httpx", "rich")
    packages = await sandbox.alist_packages()

    assert install_result == "httpx rich installed successfully"
    assert packages == ["httpx", "rich"]
    assert calls == [
        ("pip install httpx rich", "bash"),
        ("pip list --format=columns 2>/dev/null | tail -n +3 | awk '{print $1}'", "bash"),
    ]


@pytest.mark.asyncio
async def test_local_sandbox_install_returns_prefixed_error_on_failure(
    monkeypatch: "MonkeyPatch",
    tmp_path: Path,
) -> None:
    """安装失败时应返回带前缀的错误文本。"""

    sandbox = LocalSandbox(cwd=str(tmp_path))

    async def fake_aexec(
        code: str,
        kernel: str = "ipython",
        timeout: float | None = None,
        cwd: str | None = None,
    ) -> ExecResult:
        """返回失败结果。"""

        del code
        del kernel
        del timeout
        del cwd
        return ExecResult(errors="pip boom", exit_code=1, kernel="bash")

    monkeypatch.setattr(sandbox, "aexec", fake_aexec)

    result = await sandbox.ainstall("broken")

    assert result == "安装失败: pip boom"
