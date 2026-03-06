"""执行门面与沙盒客户端测试。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from astrbot_orchestrator_v5.autonomous.execution_facades import (
    ExecutionAccessPolicy,
    LegacyExecutionFacade,
    SandboxApiClient,
)
from astrbot_orchestrator_v5.autonomous.execution_support import (
    ExecutionCommandPolicy,
    ExecutionFormatter,
)
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


class FakeEvent:
    """仅包含角色信息的事件替身。"""

    def __init__(self, role: str) -> None:
        """保存当前角色。"""

        self.role = role


class FakeSandbox:
    """支持执行、文件与状态接口的沙盒替身。"""

    def __init__(self) -> None:
        """初始化默认状态。"""

        self.cwd = "/workspace"
        self.mode = "local"
        self.exec_calls: list[tuple[str, str]] = []
        self.files: dict[str, bytes] = {"demo.txt": b"hello"}
        self.restarted = False

    async def aexec(self, code: str, kernel: str = "ipython") -> ExecResult:
        """记录执行命令并返回固定结果。"""

        self.exec_calls.append((kernel, code))
        if "netstat" in code:
            return ExecResult(text="端口未被占用", exit_code=0, kernel=kernel)
        return ExecResult(text="ok", exit_code=0, kernel=kernel)

    def astream_exec(self, code: str, kernel: str = "ipython"):
        """返回流式执行结果。"""

        del code
        del kernel

        async def _generator():
            yield ExecChunk(type="stdout", content="chunk")

        return _generator()

    async def aupload(self, remote_path: str, content: bytes | str) -> SandboxFile:
        """写入文件并返回元数据。"""

        encoded = content.encode("utf-8") if isinstance(content, str) else content
        self.files[remote_path] = encoded
        return SandboxFile(path=remote_path, size=len(encoded), content=None)

    async def adownload(self, remote_path: str) -> SandboxFile:
        """读取文件内容。"""

        if remote_path not in self.files:
            raise FileNotFoundError(remote_path)
        content = self.files[remote_path]
        return SandboxFile(path=remote_path, size=len(content), content=content)

    async def alist_files(self, path: str) -> list[SandboxFile]:
        """返回目录文件列表。"""

        del path
        return [
            SandboxFile(path=file_path, size=len(content), content=None)
            for file_path, content in self.files.items()
        ]

    async def ainstall(self, *packages: str) -> str:
        """模拟安装包。"""

        return "installed: " + ", ".join(packages)

    async def alist_packages(self) -> list[str]:
        """返回已安装包列表。"""

        return ["pytest", "ruff"]

    async def ashow_variables(self) -> dict[str, str]:
        """返回会话变量。"""

        return {"hello": "world"}

    async def afile_from_url(self, url: str, file_path: str) -> SandboxFile:
        """模拟 URL 下载。"""

        self.files[file_path] = url.encode("utf-8")
        return SandboxFile(path=file_path, size=len(url), content=None)

    async def ahealthcheck(self) -> str:
        """返回健康状态。"""

        return "healthy"

    async def arestart(self) -> None:
        """记录重启动作。"""

        self.restarted = True


class FakeRuntime:
    """仅返回固定沙盒的运行时替身。"""

    def __init__(self, sandbox: FakeSandbox) -> None:
        """保存沙盒对象。"""

        self.sandbox = sandbox
        self.calls: list[str | None] = []
        self.requests: list[tuple[Any, str | None, str | None]] = []

    async def get_sandbox(
        self,
        event: Any = None,
        mode: str | None = None,
        session_id: str | None = None,
    ) -> FakeSandbox:
        """返回预置沙盒。"""

        self.requests.append((event, mode, session_id))
        self.calls.append(mode)
        return self.sandbox


def build_async_raiser(error: Exception) -> Any:
    """构造一个始终抛出指定异常的异步替身函数。"""

    async def _raiser(*args: Any, **kwargs: Any) -> Any:
        """忽略参数并抛出预设异常。"""

        del args
        del kwargs
        raise error

    return _raiser


def build_facade() -> tuple[SandboxApiClient, LegacyExecutionFacade, FakeSandbox, FakeRuntime]:
    """构造测试用客户端与兼容门面。"""

    sandbox = FakeSandbox()
    runtime = FakeRuntime(sandbox)
    api_client = SandboxApiClient(runtime=runtime)  # type: ignore[arg-type]
    facade = LegacyExecutionFacade(
        api_client=api_client,
        formatter=ExecutionFormatter(show_process=False),
        command_policy=ExecutionCommandPolicy(),
    )
    return api_client, facade, sandbox, runtime


def test_execution_access_policy_requires_admin() -> None:
    """权限策略应正确识别管理员。"""

    policy = ExecutionAccessPolicy()

    assert policy.is_admin(FakeEvent("admin")) is True
    assert policy.is_admin(FakeEvent("user")) is False
    assert policy.require_admin(FakeEvent("admin"), "denied") is None
    assert policy.require_admin(FakeEvent("user"), "denied") == "denied"


@pytest.mark.asyncio
async def test_sandbox_api_client_supports_regular_and_stream_exec() -> None:
    """低层客户端应支持普通执行与流式执行。"""

    api_client, _, sandbox, runtime = build_facade()

    result = await api_client.exec_code("print('ok')", FakeEvent("admin"), kernel="ipython")
    stream = await api_client.exec_code(
        "print('ok')",
        FakeEvent("admin"),
        kernel="ipython",
        stream=True,
    )
    chunks = [chunk async for chunk in stream]

    assert isinstance(result, ExecResult)
    assert result.text == "ok"
    assert chunks[0].content == "chunk"
    assert sandbox.exec_calls[0] == ("ipython", "print('ok')")
    assert runtime.calls[:2] == [None, None]


@pytest.mark.asyncio
async def test_sandbox_api_client_routes_support_operations() -> None:
    """低层客户端应正确代理文件、包、变量与 URL 下载接口。"""

    api_client, _, sandbox, runtime = build_facade()
    event = FakeEvent("admin")

    acquired = await api_client.get_sandbox(event=event, mode="shipyard", session_id="session-1")
    run_sandbox, run_result = await api_client.run_code(
        "echo ok",
        event,
        kernel="bash",
        mode="local",
    )
    upload_sandbox, uploaded_file = await api_client.upload_file("notes/demo.txt", "hello", event)
    downloaded_file = await api_client.download_file("notes/demo.txt", event)
    listed_files = await api_client.list_sandbox_files(".", event)
    install_result = await api_client.install_packages(["httpx", "rich"], event)
    packages = await api_client.list_packages(event)
    variables = await api_client.show_variables(event)
    url_file = await api_client.download_from_url(
        "https://example.com/demo.txt",
        "downloads/demo.txt",
        event,
    )

    assert acquired is sandbox
    assert run_sandbox is sandbox
    assert upload_sandbox is sandbox
    assert run_result.text == "ok"
    assert uploaded_file.path == "notes/demo.txt"
    assert downloaded_file.content == b"hello"
    assert "notes/demo.txt" in [file_obj.path for file_obj in listed_files]
    assert install_result == "installed: httpx, rich"
    assert packages == ["pytest", "ruff"]
    assert variables == {"hello": "world"}
    assert url_file.path == "downloads/demo.txt"
    assert sandbox.files["downloads/demo.txt"] == b"https://example.com/demo.txt"
    assert runtime.requests[:3] == [
        (event, "shipyard", "session-1"),
        (event, "local", None),
        (event, None, None),
    ]


@pytest.mark.asyncio
async def test_legacy_execution_facade_denies_non_admin_shell_execution() -> None:
    """非管理员不应通过旧 shell 接口执行命令。"""

    _, facade, _, _ = build_facade()

    result = await facade.execute("ls -la", FakeEvent("user"))

    assert result == "❌ 只有管理员可以执行命令"


@pytest.mark.asyncio
async def test_legacy_execution_facade_write_and_read_file() -> None:
    """旧文件接口应支持跳过鉴权写入并正确读取内容。"""

    _, facade, sandbox, _ = build_facade()

    write_result = await facade.write_file(
        file_path="notes/todo.txt",
        content="hello",
        event=FakeEvent("user"),
        skip_auth=True,
    )
    read_result = await facade.read_file("notes/todo.txt", FakeEvent("user"))
    list_result = await facade.list_files("notes", FakeEvent("user"))

    assert "📂 绝对路径: `/workspace/notes/todo.txt`" in write_result
    assert "hello" in read_result
    assert "notes/todo.txt" in list_result
    assert sandbox.files["notes/todo.txt"] == b"hello"


@pytest.mark.asyncio
async def test_legacy_execution_facade_executes_shell_python_and_auto_modes() -> None:
    """旧兼容门面应覆盖 shell、python 与自动执行的成功路径。"""

    _, facade, sandbox, runtime = build_facade()
    event = FakeEvent("admin")

    shell_result = await facade.execute("pwd", event)
    local_result = await facade.execute_local("pwd", event)
    sandbox_result = await facade.execute_sandbox("pwd", event)
    python_result = await facade.execute_python("print(1)", event, force_mode="local")
    auto_shell_result = await facade.auto_execute("echo hi", event, code_type="shell")
    auto_python_result = await facade.auto_execute("print(2)", event, code_type="python")

    assert "🖥️ **LOCAL 执行结果**" in shell_result
    assert "命令: `pwd`" in local_result
    assert "🖥️ **SHIPYARD 执行结果**" in sandbox_result
    assert "命令: `python: print(1)...`" in python_result
    assert "命令: `echo hi`" in auto_shell_result
    assert "命令: `print(2)`" in auto_python_result
    assert sandbox.exec_calls == [
        ("bash", "pwd"),
        ("bash", "pwd"),
        ("bash", "pwd"),
        ("ipython", "print(1)"),
        ("bash", "echo hi"),
        ("ipython", "print(2)"),
    ]
    assert runtime.calls[-6:] == [None, "local", "shipyard", "local", None, None]


@pytest.mark.asyncio
async def test_legacy_execution_facade_denies_non_admin_variants() -> None:
    """非管理员应被拒绝访问受保护的旧执行接口。"""

    _, facade, _, _ = build_facade()
    event = FakeEvent("user")

    assert await facade.execute_local("pwd", event) == "❌ 只有管理员可以执行本地命令"
    assert await facade.execute_sandbox("pwd", event) == "❌ 只有管理员可以执行命令"
    assert await facade.execute_python("print(1)", event) == "❌ 只有管理员可以执行代码"
    assert await facade.write_file("notes/a.txt", "hello", event) == "❌ 只有管理员可以写入文件"
    assert await facade.start_web_server("/tmp/demo", 8000, event) == "❌ 只有管理员可以启动服务"


@pytest.mark.asyncio
async def test_legacy_execution_facade_formats_shell_failures(
    monkeypatch: "MonkeyPatch",
) -> None:
    """shell 执行失败时应返回统一错误前缀，沙盒模式带专属提示。"""

    _, facade, _, _ = build_facade()
    event = FakeEvent("admin")
    monkeypatch.setattr(SandboxApiClient, "run_code", build_async_raiser(RuntimeError("boom")))

    assert await facade.execute("pwd", event) == "❌ 执行失败: boom"
    assert await facade.execute_local("pwd", event) == "❌ 执行失败: boom"
    assert await facade.execute_sandbox("pwd", event) == "❌ 沙盒执行失败: boom"


@pytest.mark.asyncio
async def test_legacy_execution_facade_python_and_auto_error_paths(
    monkeypatch: "MonkeyPatch",
) -> None:
    """Python 执行与自动执行应处理危险命令和底层异常。"""

    _, facade, _, _ = build_facade()
    event = FakeEvent("admin")

    assert await facade.auto_execute("rm -rf /", event) == "❌ 检测到潜在危险命令，已拒绝执行"

    monkeypatch.setattr(SandboxApiClient, "run_code", build_async_raiser(RuntimeError("boom")))

    assert await facade.execute_python("print(1)", event) == "❌ 执行失败: boom"
    assert await facade.auto_execute("echo hi", event) == "❌ 执行失败: boom"


@pytest.mark.asyncio
async def test_legacy_execution_facade_file_error_paths(
    monkeypatch: "MonkeyPatch",
) -> None:
    """文件写入、读取和列目录失败时应返回兼容错误文本。"""

    _, facade, _, _ = build_facade()
    event = FakeEvent("admin")

    monkeypatch.setattr(SandboxApiClient, "upload_file", build_async_raiser(RuntimeError("disk full")))
    assert await facade.write_file("notes/a.txt", "hello", event) == "❌ 创建文件失败: disk full"

    monkeypatch.setattr(
        SandboxApiClient,
        "download_file",
        build_async_raiser(FileNotFoundError("notes/a.txt")),
    )
    assert await facade.read_file("notes/a.txt", event) == "❌ 文件不存在: notes/a.txt"

    monkeypatch.setattr(SandboxApiClient, "download_file", build_async_raiser(RuntimeError("read boom")))
    assert await facade.read_file("notes/a.txt", event) == "❌ 读取失败: read boom"

    monkeypatch.setattr(
        SandboxApiClient,
        "list_sandbox_files",
        build_async_raiser(RuntimeError("list boom")),
    )
    assert await facade.list_files("notes", event) == "❌ 列出文件失败: list boom"


@pytest.mark.asyncio
async def test_legacy_execution_facade_service_and_status_error_paths(
    monkeypatch: "MonkeyPatch",
) -> None:
    """服务启动、健康检查、重启和端口检查失败时应返回兼容错误。"""

    _, facade, _, _ = build_facade()
    event = FakeEvent("admin")

    monkeypatch.setattr(SandboxApiClient, "run_code", build_async_raiser(RuntimeError("run boom")))
    assert await facade.start_web_server("/tmp/demo", 8000, event) == "❌ 启动失败: run boom"
    assert await facade.check_port(8000, event) == "❌ 检查失败: run boom"

    monkeypatch.setattr(SandboxApiClient, "get_sandbox", build_async_raiser(RuntimeError("offline")))
    assert await facade.healthcheck(event) == "❌ 沙盒不可用: offline"
    assert await facade.restart_sandbox(event) == "❌ 重启失败: offline"


@pytest.mark.asyncio
async def test_legacy_execution_facade_start_server_healthcheck_and_restart() -> None:
    """旧兼容门面应能启动服务、查看健康状态并重启沙盒。"""

    _, facade, sandbox, _ = build_facade()

    start_result = await facade.start_web_server(
        project_path="/tmp/demo project",
        port=8000,
        event=FakeEvent("admin"),
        framework="fastapi",
    )
    health_result = await facade.healthcheck(FakeEvent("admin"))
    restart_result = await facade.restart_sandbox(FakeEvent("admin"))
    port_result = await facade.check_port(8000, FakeEvent("admin"))

    assert "框架: fastapi" in start_result
    assert "cd '/tmp/demo project'" in sandbox.exec_calls[0][1]
    assert health_result == "✅ 沙盒状态: healthy (模式: local)"
    assert restart_result == "✅ 沙盒已重启 (模式: local)"
    assert port_result == "端口未被占用"
    assert sandbox.restarted is True
