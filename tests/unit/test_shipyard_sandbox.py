"""ShipyardSandbox 适配层测试。"""

from __future__ import annotations

import asyncio
import base64
import builtins
from collections.abc import AsyncIterator
import shlex
import sys
from types import ModuleType
from typing import TYPE_CHECKING, Any

import pytest

from astrbot_orchestrator_v5.sandbox.shipyard_sandbox import ShipyardSandbox
from astrbot_orchestrator_v5.sandbox.types import ExecChunk, ExecResult

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


def make_module(name: str, **attributes: Any) -> ModuleType:
    """创建带指定属性的假模块。"""

    module = ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def make_package(name: str) -> ModuleType:
    """创建可用于 sys.modules 注入的包模块。"""

    module = ModuleType(name)
    module.__path__ = []  # type: ignore[attr-defined]
    return module


def install_get_booter(monkeypatch: "MonkeyPatch", get_booter: Any) -> None:
    """向导入系统注入 AstrBot computer_client 替身。"""

    monkeypatch.setitem(sys.modules, "astrbot", make_package("astrbot"))
    monkeypatch.setitem(sys.modules, "astrbot.core", make_package("astrbot.core"))
    monkeypatch.setitem(
        sys.modules,
        "astrbot.core.computer",
        make_package("astrbot.core.computer"),
    )
    monkeypatch.setitem(
        sys.modules,
        "astrbot.core.computer.computer_client",
        make_module(
            "astrbot.core.computer.computer_client",
            get_booter=get_booter,
        ),
    )


class FakeEvent:
    """仅暴露 unified_msg_origin 的事件替身。"""

    def __init__(self, unified_msg_origin: str = "umo-demo") -> None:
        """保存统一消息来源。"""

        self.unified_msg_origin = unified_msg_origin


class FakeShell:
    """可记录调用并按顺序返回结果的 shell 替身。"""

    def __init__(
        self,
        results: list[Any],
        raise_timeout_type_error: bool = False,
    ) -> None:
        """初始化预设结果与可选的 timeout 回退行为。"""

        self.results = list(results)
        self.raise_timeout_type_error = raise_timeout_type_error
        self.calls: list[tuple[str, int | None]] = []
        self._raised_timeout_error = False

    async def exec(
        self,
        command: str,
        timeout: int | None = None,
    ) -> Any:
        """记录执行参数并返回预设值。"""

        self.calls.append((command, timeout))
        if self.raise_timeout_type_error and timeout is not None and not self._raised_timeout_error:
            self._raised_timeout_error = True
            raise TypeError("timeout not supported")
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeBooter:
    """仅携带 shell 接口的 booter 替身。"""

    def __init__(self, shell: FakeShell) -> None:
        """保存 shell 对象。"""

        self.shell = shell


async def collect_chunks(generator: AsyncIterator[ExecChunk]) -> list[ExecChunk]:
    """收集异步生成器中的所有执行块。"""

    return [chunk async for chunk in generator]


def test_shipyard_mode_property_returns_shipyard() -> None:
    """ShipyardSandbox 的 mode 属性应固定返回 shipyard。"""

    sandbox = ShipyardSandbox()

    assert sandbox.mode == "shipyard"


@pytest.mark.asyncio
async def test_shipyard_get_booter_caches_result(monkeypatch: "MonkeyPatch") -> None:
    """_get_booter 应仅在首次调用时访问 AstrBot 接口。"""

    calls: list[tuple[Any, Any]] = []
    booter = FakeBooter(FakeShell(results=[]))

    async def fake_get_booter(context: Any, umo: Any) -> FakeBooter:
        """记录上下文与消息来源。"""

        calls.append((context, umo))
        return booter

    install_get_booter(monkeypatch, fake_get_booter)
    sandbox = ShipyardSandbox(context="ctx", event=FakeEvent("umo-x"))

    first = await sandbox._get_booter()
    second = await sandbox._get_booter()

    assert first is booter
    assert second is booter
    assert calls == [("ctx", "umo-x")]


@pytest.mark.asyncio
async def test_shipyard_get_booter_wraps_import_error(monkeypatch: "MonkeyPatch") -> None:
    """缺少 computer_client 时应抛出清晰的运行时错误。"""

    original_import = builtins.__import__

    def fake_import(
        name: str,
        globals_dict: dict[str, Any] | None = None,
        locals_dict: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        """对目标模块模拟导入失败。"""

        if name.startswith("astrbot.core.computer.computer_client"):
            raise ImportError("missing")
        return original_import(name, globals_dict, locals_dict, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    sandbox = ShipyardSandbox(context="ctx", event=None)

    with pytest.raises(RuntimeError, match="computer_client"):
        await sandbox._get_booter()


@pytest.mark.asyncio
async def test_shipyard_get_booter_reraises_unexpected_error(
    monkeypatch: "MonkeyPatch",
) -> None:
    """获取 booter 的未知异常应原样继续抛出。"""

    async def fake_get_booter(context: Any, umo: Any) -> FakeBooter:
        """模拟获取 booter 时的运行时错误。"""

        del context
        del umo
        raise RuntimeError("booter down")

    install_get_booter(monkeypatch, fake_get_booter)
    sandbox = ShipyardSandbox(context="ctx", event=FakeEvent("umo-x"))

    with pytest.raises(RuntimeError, match="booter down"):
        await sandbox._get_booter()


@pytest.mark.asyncio
async def test_shipyard_start_and_stop_manage_lifecycle(monkeypatch: "MonkeyPatch") -> None:
    """启动和停止应切换 started 标志并创建工作目录。"""

    sandbox = ShipyardSandbox(context="ctx", cwd="/workspace/demo app")
    shell_calls: list[tuple[str, float | None]] = []
    booter_calls = 0

    async def fake_get_booter() -> object:
        """返回一个占位 booter。"""

        nonlocal booter_calls
        booter_calls += 1
        return object()

    async def fake_shell_exec(
        command: str,
        timeout: float | None = None,
    ) -> dict[str, str]:
        """记录 shell 命令。"""

        shell_calls.append((command, timeout))
        return {"stdout": ""}

    monkeypatch.setattr(sandbox, "_get_booter", fake_get_booter)
    monkeypatch.setattr(sandbox, "_shell_exec", fake_shell_exec)

    await sandbox.astart()
    assert sandbox._started is True
    assert booter_calls == 1
    assert shell_calls == [("mkdir -p '/workspace/demo app'", None)]

    sandbox._booter = object()
    await sandbox.astop()
    assert sandbox._started is False
    assert sandbox._booter is None


@pytest.mark.asyncio
async def test_shipyard_shell_exec_retries_and_normalizes_results(
    monkeypatch: "MonkeyPatch",
) -> None:
    """shell 执行应兼容 timeout 回退、JSON 字符串与非字典结果。"""

    shell = FakeShell(
        results=[
            '{"stdout": "ok", "stderr": "", "exit_code": 0}',
            "plain output",
            123,
        ],
        raise_timeout_type_error=True,
    )
    booter = FakeBooter(shell)
    sandbox = ShipyardSandbox()

    async def fake_get_booter() -> FakeBooter:
        """返回固定 booter。"""

        return booter

    monkeypatch.setattr(sandbox, "_get_booter", fake_get_booter)

    json_result = await sandbox._shell_exec("echo one", timeout=7)
    text_result = await sandbox._shell_exec("echo two", timeout=8)
    other_result = await sandbox._shell_exec("echo three", timeout=9)

    assert json_result == {"stdout": "ok", "stderr": "", "exit_code": 0}
    assert text_result == {"stdout": "plain output", "stderr": "", "exit_code": 0}
    assert other_result == {"stdout": "123", "stderr": "", "exit_code": 0}
    assert shell.calls == [
        ("echo one", 7),
        ("echo one", None),
        ("echo two", 8),
        ("echo three", 9),
    ]


@pytest.mark.asyncio
async def test_shipyard_aexec_quotes_bash_workdir_and_formats_result(
    monkeypatch: "MonkeyPatch",
) -> None:
    """bash 执行应对工作目录加引号并整理 output/error 字段。"""

    sandbox = ShipyardSandbox(cwd="/workspace/demo app", timeout=12.0)
    shell_calls: list[tuple[str, float | None]] = []
    wait_calls: list[float] = []

    async def fake_shell_exec(
        command: str,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """返回带 output/error 字段的执行结果。"""

        shell_calls.append((command, timeout))
        return {"output": " hello \n", "error": " warn \n", "returncode": "2"}

    async def fake_wait_for(awaitable: Any, timeout: float) -> Any:
        """直接等待协程并记录外层超时值。"""

        wait_calls.append(timeout)
        return await awaitable

    monkeypatch.setattr(sandbox, "_shell_exec", fake_shell_exec)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    result = await sandbox.aexec("echo hi", kernel="bash")

    assert shell_calls == [("cd '/workspace/demo app' && echo hi", 12.0)]
    assert wait_calls == [17.0]
    assert result.text == "hello"
    assert result.errors == "warn"
    assert result.exit_code == 2
    assert result.kernel == "bash"


@pytest.mark.asyncio
async def test_shipyard_aexec_wraps_python_code_in_command(
    monkeypatch: "MonkeyPatch",
) -> None:
    """Python 内核执行应包装成 python3 -c 命令并转义单引号。"""

    sandbox = ShipyardSandbox(cwd="/workspace/my app", timeout=6.0)
    shell_calls: list[tuple[str, float | None]] = []

    async def fake_shell_exec(
        command: str,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """记录命令并返回成功结果。"""

        shell_calls.append((command, timeout))
        return {"stdout": "x", "stderr": "", "exit_code": 0}

    async def fake_wait_for(awaitable: Any, timeout: float) -> Any:
        """直接转发到底层 awaitable。"""

        del timeout
        return await awaitable

    monkeypatch.setattr(sandbox, "_shell_exec", fake_shell_exec)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    result = await sandbox.aexec("print('x')", kernel="ipython")

    assert shell_calls[0][0].startswith("cd '/workspace/my app' && python3 -c '")
    assert "python3 -c" in shell_calls[0][0]
    assert "'\\''" in shell_calls[0][0]
    assert result.text == "x"
    assert result.errors == ""
    assert result.exit_code == 0


@pytest.mark.asyncio
async def test_shipyard_aexec_returns_timeout_result(monkeypatch: "MonkeyPatch") -> None:
    """外层等待超时时应返回统一的超时执行结果。"""

    sandbox = ShipyardSandbox(timeout=5.0)

    async def fake_shell_exec(
        command: str,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """返回一个永远不会被消费的占位结果。"""

        del command
        del timeout
        return {"stdout": "ignored"}

    async def fake_wait_for(awaitable: Any, timeout: float) -> Any:
        """主动关闭协程并抛出超时异常。"""

        del timeout
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(sandbox, "_shell_exec", fake_shell_exec)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    result = await sandbox.aexec("sleep 10", kernel="bash")

    assert result.text == ""
    assert result.errors == "执行超时（5.0秒）"
    assert result.exit_code == -1
    assert result.kernel == "bash"


@pytest.mark.asyncio
async def test_shipyard_aexec_returns_error_result_on_exception(
    monkeypatch: "MonkeyPatch",
) -> None:
    """底层执行异常时应回收为错误执行结果。"""

    sandbox = ShipyardSandbox(timeout=5.0)

    async def fake_shell_exec(
        command: str,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """模拟底层执行失败。"""

        del command
        del timeout
        raise RuntimeError("boom")

    async def fake_wait_for(awaitable: Any, timeout: float) -> Any:
        """直接等待 awaitable。"""

        del timeout
        return await awaitable

    monkeypatch.setattr(sandbox, "_shell_exec", fake_shell_exec)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    result = await sandbox.aexec("echo hi", kernel="bash")

    assert result.text == ""
    assert result.errors == "boom"
    assert result.exit_code == -1
    assert result.kernel == "bash"


@pytest.mark.asyncio
async def test_shipyard_stream_exec_emits_status_stdout_stderr_and_images() -> None:
    """流式执行应拆分 stdout/stderr 行并在前后附带状态块。"""

    sandbox = ShipyardSandbox()

    async def fake_aexec(
        code: str,
        kernel: str = "ipython",
        timeout: float | None = None,
        cwd: str | None = None,
    ) -> ExecResult:
        """返回一个包含文本、错误与图片的执行结果。"""

        del code
        del kernel
        del timeout
        del cwd
        return ExecResult(
            text="line-1\nline-2",
            errors="err-1\nerr-2",
            images=["img-data"],
            exit_code=3,
        )

    sandbox.aexec = fake_aexec  # type: ignore[method-assign]

    chunks = await collect_chunks(sandbox.astream_exec("echo hi", kernel="bash"))

    assert [(chunk.type, chunk.content) for chunk in chunks] == [
        ("status", "开始执行..."),
        ("stdout", "line-1\n"),
        ("stdout", "line-2\n"),
        ("stderr", "err-1\n"),
        ("stderr", "err-2\n"),
        ("image", "img-data"),
        ("status", "exit_code=3"),
    ]


@pytest.mark.asyncio
async def test_shipyard_stream_exec_skips_empty_sections() -> None:
    """当执行结果为空时，流式接口只应输出开始和结束状态。"""

    sandbox = ShipyardSandbox()

    async def fake_aexec(
        code: str,
        kernel: str = "ipython",
        timeout: float | None = None,
        cwd: str | None = None,
    ) -> ExecResult:
        """返回一个没有输出内容的成功结果。"""

        del code
        del kernel
        del timeout
        del cwd
        return ExecResult(text="", errors="", images=[], exit_code=0)

    sandbox.aexec = fake_aexec  # type: ignore[method-assign]

    chunks = await collect_chunks(sandbox.astream_exec("echo hi", kernel="bash"))

    assert [(chunk.type, chunk.content) for chunk in chunks] == [
        ("status", "开始执行..."),
        ("status", "exit_code=0"),
    ]


@pytest.mark.asyncio
async def test_shipyard_upload_writes_base64_and_handles_invalid_stat(
    monkeypatch: "MonkeyPatch",
) -> None:
    """上传应先建目录，再写入 base64 内容，并在 stat 失败时回退大小。"""

    sandbox = ShipyardSandbox(cwd="/workspace/demo app")
    commands: list[str] = []

    async def fake_shell_exec(
        command: str,
        timeout: float | None = None,
    ) -> dict[str, str]:
        """按命令返回上传阶段的结果。"""

        del timeout
        commands.append(command)
        if command.startswith("stat -c %s"):
            return {"stdout": "invalid-size"}
        return {"stdout": ""}

    monkeypatch.setattr(sandbox, "_shell_exec", fake_shell_exec)

    uploaded = await sandbox.aupload("nested/hello.txt", "hi")
    b64_value = base64.b64encode(b"hi").decode("ascii")

    assert commands == [
        "mkdir -p '/workspace/demo app/nested'",
        (
            "printf %s "
            f"{shlex.quote(b64_value)} | base64 -d > '/workspace/demo app/nested/hello.txt'"
        ),
        "stat -c %s '/workspace/demo app/nested/hello.txt' 2>/dev/null || echo -1",
    ]
    assert uploaded.path == "nested/hello.txt"
    assert uploaded.size == -1


@pytest.mark.asyncio
async def test_shipyard_download_raises_for_missing_file(monkeypatch: "MonkeyPatch") -> None:
    """下载缺失文件时应抛出 FileNotFoundError。"""

    sandbox = ShipyardSandbox(cwd="/workspace/demo")
    commands: list[str] = []

    async def fake_shell_exec(
        command: str,
        timeout: float | None = None,
    ) -> dict[str, str]:
        """返回文件缺失结果。"""

        del timeout
        commands.append(command)
        return {"stdout": "missing"}

    monkeypatch.setattr(sandbox, "_shell_exec", fake_shell_exec)

    with pytest.raises(FileNotFoundError, match="missing.txt"):
        await sandbox.adownload("missing.txt")

    assert commands == [
        f"test -f {shlex.quote('/workspace/demo/missing.txt')} && echo exists || echo missing"
    ]


@pytest.mark.asyncio
async def test_shipyard_download_decodes_base64_content(monkeypatch: "MonkeyPatch") -> None:
    """下载文件时应优先使用 base64 读取二进制内容。"""

    sandbox = ShipyardSandbox(cwd="/workspace/demo")
    encoded = base64.b64encode(b"\x00\x01data").decode("ascii")
    responses = [
        {"stdout": "exists"},
        {"stdout": encoded},
    ]

    async def fake_shell_exec(
        command: str,
        timeout: float | None = None,
    ) -> dict[str, str]:
        """按顺序返回存在检查和 base64 内容。"""

        del command
        del timeout
        return responses.pop(0)

    monkeypatch.setattr(sandbox, "_shell_exec", fake_shell_exec)

    downloaded = await sandbox.adownload("bin/data.bin")

    assert downloaded.path == "bin/data.bin"
    assert downloaded.content == b"\x00\x01data"
    assert downloaded.size == 6


@pytest.mark.asyncio
async def test_shipyard_download_falls_back_to_cat_when_base64_invalid(
    monkeypatch: "MonkeyPatch",
) -> None:
    """base64 解析失败时应回退到普通文本读取。"""

    sandbox = ShipyardSandbox(cwd="/workspace/demo")
    commands: list[str] = []
    responses = [
        {"stdout": "exists"},
        {"stdout": "%%%invalid%%%"},
        {"stdout": "plain-text"},
    ]

    async def fake_shell_exec(
        command: str,
        timeout: float | None = None,
    ) -> dict[str, str]:
        """记录命令并按顺序返回预设值。"""

        del timeout
        commands.append(command)
        return responses.pop(0)

    monkeypatch.setattr(sandbox, "_shell_exec", fake_shell_exec)

    downloaded = await sandbox.adownload("logs/output.txt")

    assert downloaded.content == b"plain-text"
    assert downloaded.size == 10
    assert commands == [
        (
            f"test -f {shlex.quote('/workspace/demo/logs/output.txt')}"
            " && echo exists || echo missing"
        ),
        f"base64 {shlex.quote('/workspace/demo/logs/output.txt')}",
        f"cat {shlex.quote('/workspace/demo/logs/output.txt')}",
    ]


@pytest.mark.asyncio
async def test_shipyard_list_files_parses_relative_paths_and_sizes(
    monkeypatch: "MonkeyPatch",
) -> None:
    """列文件应从 shell 输出中提取相对路径和字节大小。"""

    sandbox = ShipyardSandbox(cwd="/workspace/demo")
    commands: list[str] = []

    async def fake_shell_exec(
        command: str,
        timeout: float | None = None,
    ) -> dict[str, str]:
        """返回模拟 find/du 输出。"""

        del timeout
        commands.append(command)
        return {"stdout": "/workspace/demo/nested/a.txt 1K\n/workspace/demo/nested/b.bin 1.5M\n"}

    monkeypatch.setattr(sandbox, "_shell_exec", fake_shell_exec)

    files = await sandbox.alist_files("nested")

    assert commands == [
        (
            f"find {shlex.quote('/workspace/demo/nested')} -maxdepth 1 -type f "
            "-exec du -h {} + 2>/dev/null | awk '{print $2, $1}' | sort"
        )
    ]
    assert [(file.path, file.size) for file in files] == [
        ("nested/a.txt", 1024),
        ("nested/b.bin", int(1.5 * 1024**2)),
    ]


@pytest.mark.asyncio
async def test_shipyard_list_files_returns_empty_for_blank_or_invalid_output(
    monkeypatch: "MonkeyPatch",
) -> None:
    """空输出、非法行和根目录自身条目都不应生成文件对象。"""

    sandbox = ShipyardSandbox(cwd="/workspace/demo")
    responses = [
        {"stdout": ""},
        {"stdout": "/workspace/demo 1K\nmalformed-line\n"},
    ]

    async def fake_shell_exec(
        command: str,
        timeout: float | None = None,
    ) -> dict[str, str]:
        """返回空列表与无效列表两种 shell 输出。"""

        del command
        del timeout
        return responses.pop(0)

    monkeypatch.setattr(sandbox, "_shell_exec", fake_shell_exec)

    assert await sandbox.alist_files() == []
    assert await sandbox.alist_files() == []


def test_shipyard_parse_size_handles_units_and_invalid_values() -> None:
    """文件大小解析应支持常见单位并拒绝非法值。"""

    assert ShipyardSandbox._parse_size("1K") == 1024
    assert ShipyardSandbox._parse_size("1.5M") == int(1.5 * 1024**2)
    assert ShipyardSandbox._parse_size("bad") == -1


@pytest.mark.asyncio
async def test_shipyard_install_and_list_packages_use_bash_exec(
    monkeypatch: "MonkeyPatch",
) -> None:
    """安装与列包应委托给 bash aexec，并返回格式化结果。"""

    sandbox = ShipyardSandbox()
    calls: list[tuple[str, str, float | None, str | None]] = []

    async def fake_aexec(
        code: str,
        kernel: str = "ipython",
        timeout: float | None = None,
        cwd: str | None = None,
    ) -> ExecResult:
        """按命令返回成功、失败或列包结果。"""

        calls.append((code, kernel, timeout, cwd))
        if code == "pip install httpx":
            return ExecResult(text="installed", exit_code=0, kernel=kernel)
        if code == "pip install broken":
            return ExecResult(errors="boom", exit_code=1, kernel=kernel)
        return ExecResult(text="pytest\nruff\n", exit_code=0, kernel=kernel)

    sandbox.aexec = fake_aexec  # type: ignore[method-assign]

    assert await sandbox.ainstall("httpx") == "httpx installed successfully"
    assert await sandbox.ainstall("broken") == "安装失败: boom"
    assert await sandbox.alist_packages() == ["pytest", "ruff"]
    assert calls == [
        ("pip install httpx", "bash", None, None),
        ("pip install broken", "bash", None, None),
        (
            "pip list --format=columns 2>/dev/null | tail -n +3 | awk '{print $1}'",
            "bash",
            None,
            None,
        ),
    ]


@pytest.mark.asyncio
async def test_shipyard_variables_and_restart_behaviour(monkeypatch: "MonkeyPatch") -> None:
    """Shipyard 变量接口应返回空，并在重启时重新获取 booter。"""

    sandbox = ShipyardSandbox()
    calls = 0
    new_booter = object()
    sandbox._booter = object()

    async def fake_get_booter() -> object:
        """记录重启后的 booter 获取。"""

        nonlocal calls
        calls += 1
        sandbox._booter = new_booter
        return new_booter

    monkeypatch.setattr(sandbox, "_get_booter", fake_get_booter)

    assert await sandbox.ashow_variables() == {}
    await sandbox.arestart()

    assert calls == 1
    assert sandbox._booter is new_booter
