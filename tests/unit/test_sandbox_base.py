"""CodeSandbox 抽象基类测试。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from astrbot_orchestrator_v5.sandbox.base import CodeSandbox
from astrbot_orchestrator_v5.sandbox.types import ExecChunk, ExecResult, SandboxFile

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


class StubSandbox(CodeSandbox):
    """用于测试抽象基类默认实现的沙盒替身。"""

    def __init__(self) -> None:
        """初始化调用记录与预置结果。"""

        super().__init__(session_id="session-x", cwd="/workspace/demo", timeout=12.0)
        self.exec_calls: list[tuple[str, str, float | None, str | None]] = []
        self.exec_results: dict[tuple[str, str], ExecResult] = {}
        self.exec_errors: dict[tuple[str, str], Exception] = {}
        self.download_calls: list[str] = []
        self.download_results: dict[str, SandboxFile] = {}
        self.upload_calls: list[tuple[str, bytes | str, float | None]] = []
        self.listed_files: list[SandboxFile] = []

    @property
    def mode(self) -> str:
        """返回测试模式名。"""

        return "stub"

    async def aexec(
        self,
        code: str,
        kernel: str = "ipython",
        timeout: float | None = None,
        cwd: str | None = None,
    ) -> ExecResult:
        """记录执行调用并返回预设结果。"""

        self.exec_calls.append((code, kernel, timeout, cwd))
        key = (code, kernel)
        if key in self.exec_errors:
            raise self.exec_errors[key]
        return self.exec_results.get(key, ExecResult(text="", kernel=kernel))

    async def astream_exec(
        self,
        code: str,
        kernel: str = "ipython",
        timeout: float | None = None,
        cwd: str | None = None,
    ):
        """返回一个最小流式执行块。"""

        del code
        del kernel
        del timeout
        del cwd
        yield ExecChunk(type="stdout", content="chunk")

    async def aupload(
        self,
        remote_path: str,
        content: bytes | str,
        timeout: float | None = None,
    ) -> SandboxFile:
        """记录上传调用并返回文件对象。"""

        self.upload_calls.append((remote_path, content, timeout))
        content_bytes = content if isinstance(content, bytes) else content.encode("utf-8")
        return SandboxFile(path=remote_path, size=len(content_bytes), content=content_bytes)

    async def adownload(
        self,
        remote_path: str,
        timeout: float | None = None,
    ) -> SandboxFile:
        """记录下载调用并返回预设文件。"""

        del timeout
        self.download_calls.append(remote_path)
        return self.download_results.get(remote_path, SandboxFile(path=remote_path, size=0))

    async def alist_files(
        self,
        path: str = ".",
    ) -> list[SandboxFile]:
        """返回预设文件列表。"""

        del path
        return list(self.listed_files)


@pytest.mark.asyncio
async def test_code_sandbox_context_manager_updates_started_flag() -> None:
    """上下文管理器应正确切换沙盒启动状态。"""

    sandbox = StubSandbox()

    assert sandbox._started is False
    async with sandbox as entered:
        assert entered is sandbox
        assert sandbox._started is True
        assert sandbox.session_id == "session-x"
        assert sandbox.cwd == "/workspace/demo"
        assert sandbox.timeout == 12.0
    assert sandbox._started is False


@pytest.mark.asyncio
async def test_code_sandbox_file_from_url_runs_download_script() -> None:
    """从 URL 下载文件应生成安全的 Python 下载脚本并返回文件对象。"""

    sandbox = StubSandbox()
    sandbox.download_results['assets/"logo".png'] = SandboxFile(
        path='assets/"logo".png',
        size=4,
        content=b"data",
    )

    result = await sandbox.afile_from_url(
        url='https://example.com/file?q="x"',
        file_path='assets/"logo".png',
    )

    assert result.path == 'assets/"logo".png'
    assert sandbox.download_calls == ['assets/"logo".png']
    executed_code, kernel, timeout, cwd = sandbox.exec_calls[0]
    assert (
        'async with client.stream(\'GET\', "https://example.com/file?q=\\"x\\"")' in executed_code
    )
    assert 'with open("/workspace/demo/assets/\\"logo\\".png", \'wb\') as f:' in executed_code
    assert kernel == "ipython"
    assert timeout is None
    assert cwd is None


@pytest.mark.asyncio
async def test_code_sandbox_install_and_list_packages_use_bash_exec() -> None:
    """包安装与列表查询应复用 bash 执行接口。"""

    sandbox = StubSandbox()
    sandbox.exec_results[("pip install httpx rich", "bash")] = ExecResult(
        text="installed",
        exit_code=0,
        kernel="bash",
    )
    sandbox.exec_results[("pip list --format=columns | tail -n +3 | cut -d ' ' -f 1", "bash")] = (
        ExecResult(text="httpx\nrich\n", exit_code=0, kernel="bash")
    )

    install_result = await sandbox.ainstall("httpx", "rich")
    packages = await sandbox.alist_packages()

    assert install_result == "httpx rich installed successfully"
    assert packages == ["httpx", "rich"]


@pytest.mark.asyncio
async def test_code_sandbox_install_returns_error_text_on_failure() -> None:
    """包安装失败时应返回错误文本。"""

    sandbox = StubSandbox()
    sandbox.exec_results[("pip install broken", "bash")] = ExecResult(
        errors="install failed",
        exit_code=1,
        kernel="bash",
    )

    result = await sandbox.ainstall("broken")

    assert result == "install failed"


@pytest.mark.asyncio
async def test_code_sandbox_show_variables_reads_each_value() -> None:
    """变量展示应先列变量名，再逐个读取变量值。"""

    sandbox = StubSandbox()
    sandbox.exec_results[("%who", "ipython")] = ExecResult(text="alpha beta", kernel="ipython")
    sandbox.exec_results[("print(alpha, end='')", "ipython")] = ExecResult(
        text="1",
        kernel="ipython",
    )
    sandbox.exec_results[("print(beta, end='')", "ipython")] = ExecResult(
        text="'two'",
        kernel="ipython",
    )

    variables = await sandbox.ashow_variables()

    assert variables == {"alpha": "1", "beta": "'two'"}


@pytest.mark.asyncio
async def test_code_sandbox_show_variables_returns_empty_when_session_clean() -> None:
    """没有变量时应返回空字典。"""

    sandbox = StubSandbox()
    sandbox.exec_results[("%who", "ipython")] = ExecResult(text="", kernel="ipython")

    variables = await sandbox.ashow_variables()

    assert variables == {}


@pytest.mark.asyncio
async def test_code_sandbox_restart_healthcheck_and_status_fallbacks() -> None:
    """状态查询应在包列表或变量读取失败时回退到空结果。"""

    sandbox = StubSandbox()
    sandbox.exec_results[("echo ok", "bash")] = ExecResult(text="ok", kernel="bash")
    sandbox.exec_errors[("pip list --format=columns | tail -n +3 | cut -d ' ' -f 1", "bash")] = (
        RuntimeError("pip error")
    )
    sandbox.exec_errors[("%who", "ipython")] = RuntimeError("who error")

    # 默认 arestart 实现是 astop()+astart() 的幂等循环，不再依赖
    # 不存在的 IPython 内核魔法 %restart。
    assert sandbox._started is False
    await sandbox.astart()
    assert sandbox._started is True
    await sandbox.arestart()
    assert sandbox._started is True
    assert all(call[0] != "%restart" for call in sandbox.exec_calls)

    health = await sandbox.ahealthcheck()
    status = await sandbox.astatus()

    assert health == "healthy"
    assert status.healthy is True
    assert status.mode == "stub"
    assert status.session_id == "session-x"
    assert status.packages == []
    assert status.variables == {}


@pytest.mark.asyncio
async def test_code_sandbox_healthcheck_returns_error_on_exception() -> None:
    """健康检查异常时应返回 error。"""

    sandbox = StubSandbox()
    sandbox.exec_errors[("echo ok", "bash")] = RuntimeError("boom")

    result = await sandbox.ahealthcheck()

    assert result == "error"


@pytest.mark.asyncio
async def test_code_sandbox_keep_alive_polls_healthcheck_and_sleeps(
    monkeypatch: "MonkeyPatch",
) -> None:
    """保活逻辑应按分钟数重复健康检查并休眠。"""

    sandbox = StubSandbox()
    sandbox.exec_results[("echo ok", "bash")] = ExecResult(text="ok", kernel="bash")
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        """记录休眠时长而不真正等待。"""

        sleep_calls.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    await sandbox.akeep_alive(minutes=3)

    assert [call[0] for call in sandbox.exec_calls] == ["echo ok", "echo ok", "echo ok"]
    assert sleep_calls == [60, 60, 60]
