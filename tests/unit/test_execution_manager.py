"""ExecutionManager 委托层测试。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from astrbot_orchestrator_v5.autonomous.executor import ExecutionManager
from astrbot_orchestrator_v5.sandbox.types import ExecResult, SandboxFile

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


class FakeContext:
    """最小上下文替身。"""

    def get_config(self) -> dict[str, Any]:
        """返回空配置。"""

        return {}


class FakeRuntime:
    """记录运行时委托调用。"""

    def __init__(self) -> None:
        """初始化记录容器。"""

        self.cache_size = 3
        self.is_inside = True
        self.get_sandbox_calls: list[tuple[Any, str | None, str | None]] = []
        self.stopped = False

    async def get_sandbox(
        self,
        event: Any = None,
        mode: str | None = None,
        session_id: str | None = None,
    ) -> str:
        """记录获取沙盒请求。"""

        self.get_sandbox_calls.append((event, mode, session_id))
        return "sandbox-instance"

    def detect_mode(self) -> str:
        """返回固定模式。"""

        return "shipyard"

    def is_inside_sandbox(self) -> bool:
        """返回固定宿主状态。"""

        return self.is_inside

    async def astop(self) -> None:
        """记录 stop 调用。"""

        self.stopped = True


class FakeApiClient:
    """记录 API 客户端委托调用。"""

    def __init__(self) -> None:
        """初始化返回值。"""

        self.exec_calls: list[tuple[str, str, bool]] = []
        self.upload_calls: list[tuple[str, bytes | str]] = []
        self.download_calls: list[str] = []

    async def exec_code(
        self,
        code: str,
        event: Any,
        kernel: str = "ipython",
        stream: bool = False,
    ) -> ExecResult:
        """记录 exec_code 调用。"""

        del event
        self.exec_calls.append((code, kernel, stream))
        return ExecResult(text="ok", exit_code=0, kernel=kernel)

    async def upload_file(
        self,
        remote_path: str,
        content: bytes | str,
        event: Any,
    ) -> tuple[str, SandboxFile]:
        """记录上传调用。"""

        del event
        self.upload_calls.append((remote_path, content))
        return "sandbox", SandboxFile(path=remote_path, size=1)

    async def download_file(self, remote_path: str, event: Any) -> SandboxFile:
        """记录下载调用。"""

        del event
        self.download_calls.append(remote_path)
        return SandboxFile(path=remote_path, size=1, content=b"x")

    async def list_sandbox_files(self, path: str, event: Any) -> list[SandboxFile]:
        """返回固定文件列表。"""

        del event
        return [SandboxFile(path=path, size=1)]

    async def install_packages(self, packages: list[str], event: Any) -> str:
        """返回固定安装结果。"""

        del event
        return ",".join(packages)

    async def list_packages(self, event: Any) -> list[str]:
        """返回固定包列表。"""

        del event
        return ["pytest"]

    async def show_variables(self, event: Any) -> dict[str, str]:
        """返回固定变量列表。"""

        del event
        return {"k": "v"}

    async def download_from_url(self, url: str, file_path: str, event: Any) -> SandboxFile:
        """返回固定 URL 下载结果。"""

        del event
        return SandboxFile(path=file_path, size=len(url))


class FakeLegacyFacade:
    """记录旧兼容门面调用。"""

    def __init__(self) -> None:
        """初始化调用记录。"""

        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def execute(self, command: str, event: Any) -> str:
        """记录 execute 调用。"""

        self.calls.append(("execute", (command, event), {}))
        return "execute-result"

    async def execute_local(self, command: str, event: Any) -> str:
        """记录 execute_local 调用。"""

        self.calls.append(("execute_local", (command, event), {}))
        return "execute-local-result"

    async def execute_sandbox(self, command: str, event: Any) -> str:
        """记录 execute_sandbox 调用。"""

        self.calls.append(("execute_sandbox", (command, event), {}))
        return "execute-sandbox-result"

    async def execute_python(self, code: str, event: Any, force_mode: str | None = None) -> str:
        """记录 execute_python 调用。"""

        self.calls.append(("execute_python", (code, event), {"force_mode": force_mode}))
        return "execute-python-result"

    async def auto_execute(self, code: str, event: Any, code_type: str = "shell") -> str:
        """记录 auto_execute 调用。"""

        self.calls.append(("auto_execute", (code, event), {"code_type": code_type}))
        return "auto-execute-result"

    async def write_file(
        self,
        file_path: str,
        content: str,
        event: Any,
        skip_auth: bool = False,
    ) -> str:
        """记录 write_file 调用。"""

        self.calls.append(
            ("write_file", (file_path, content, event), {"skip_auth": skip_auth})
        )
        return "write-file-result"

    async def read_file(self, file_path: str, event: Any) -> str:
        """记录 read_file 调用。"""

        self.calls.append(("read_file", (file_path, event), {}))
        return "read-file-result"

    async def list_files(self, dir_path: str, event: Any) -> str:
        """记录 list_files 调用。"""

        self.calls.append(("list_files", (dir_path, event), {}))
        return "list-files-result"

    async def start_web_server(
        self,
        project_path: str,
        port: int,
        event: Any,
        framework: str = "python",
    ) -> str:
        """记录 start_web_server 调用。"""

        self.calls.append(
            (
                "start_web_server",
                (project_path, port, event),
                {"framework": framework},
            )
        )
        return "start-server-result"

    async def healthcheck(self, event: Any = None) -> str:
        """记录 healthcheck 调用。"""

        self.calls.append(("healthcheck", (event,), {}))
        return "healthcheck-result"

    async def restart_sandbox(self, event: Any) -> str:
        """记录 restart_sandbox 调用。"""

        self.calls.append(("restart_sandbox", (event,), {}))
        return "restart-result"

    async def check_port(self, port: int, event: Any) -> str:
        """记录 check_port 调用。"""

        self.calls.append(("check_port", (port, event), {}))
        return "check-port-result"


@pytest.mark.asyncio
async def test_execution_manager_delegates_runtime_and_api_calls() -> None:
    """应将 runtime 与 api 相关调用转发到对应组件。"""

    manager = ExecutionManager(context=FakeContext(), config={"show_thinking_process": False})
    fake_runtime = FakeRuntime()
    fake_api = FakeApiClient()
    manager.sandbox_runtime = fake_runtime  # type: ignore[assignment]
    manager.api_client = fake_api  # type: ignore[assignment]

    sandbox = await manager.get_sandbox(event="evt", mode="local", session_id="s1")
    exec_result = await manager.exec_code("print('ok')", event="evt", kernel="ipython")
    uploaded = await manager.upload_file("demo.txt", "x", event="evt")
    downloaded = await manager.download_file("demo.txt", event="evt")
    files = await manager.list_sandbox_files("demo", event="evt")
    packages = await manager.list_packages("evt")
    variables = await manager.show_variables("evt")
    from_url = await manager.download_from_url("https://x", "demo.bin", event="evt")

    assert sandbox == "sandbox-instance"
    assert exec_result.text == "ok"
    assert uploaded.path == "demo.txt"
    assert downloaded.path == "demo.txt"
    assert files[0].path == "demo"
    assert packages == ["pytest"]
    assert variables == {"k": "v"}
    assert from_url.path == "demo.bin"
    assert fake_runtime.get_sandbox_calls == [("evt", "local", "s1")]
    assert fake_api.exec_calls == [("print('ok')", "ipython", False)]


@pytest.mark.asyncio
async def test_execution_manager_delegates_legacy_facade_calls() -> None:
    """旧兼容接口应全部转发到 facade。"""

    manager = ExecutionManager(context=FakeContext(), config={"show_thinking_process": False})
    fake_legacy = FakeLegacyFacade()
    manager.legacy_facade = fake_legacy  # type: ignore[assignment]

    assert await manager.execute("ls", "evt") == "execute-result"
    assert await manager.execute_local("pwd", "evt") == "execute-local-result"
    assert await manager.execute_sandbox("pwd", "evt") == "execute-sandbox-result"
    assert await manager.execute_python("print(1)", "evt", force_mode="local") == "execute-python-result"
    assert await manager.auto_execute("ls", "evt", code_type="shell") == "auto-execute-result"
    assert await manager.write_file("a.txt", "x", "evt", skip_auth=True) == "write-file-result"
    assert await manager.read_file("a.txt", "evt") == "read-file-result"
    assert await manager.list_files(".", "evt") == "list-files-result"
    assert await manager.start_web_server("/tmp/demo", 8000, "evt", framework="fastapi") == "start-server-result"
    assert await manager.healthcheck("evt") == "healthcheck-result"
    assert await manager.restart_sandbox("evt") == "restart-result"
    assert await manager.check_port(8000, "evt") == "check-port-result"

    assert fake_legacy.calls[0][0] == "execute"
    assert fake_legacy.calls[3] == ("execute_python", ("print(1)", "evt"), {"force_mode": "local"})
    assert fake_legacy.calls[8] == (
        "start_web_server",
        ("/tmp/demo", 8000, "evt"),
        {"framework": "fastapi"},
    )


@pytest.mark.asyncio
async def test_execution_manager_mode_info_and_stop_use_runtime() -> None:
    """mode info 与 stop 应读取并委托给 runtime。"""

    manager = ExecutionManager(context=FakeContext(), config={"show_thinking_process": False})
    fake_runtime = FakeRuntime()
    manager.sandbox_runtime = fake_runtime  # type: ignore[assignment]

    info = manager.get_current_mode_info()
    await manager.astop()

    assert "运行模式: 🐳 Shipyard 沙盒（Docker 隔离）" in info
    assert "在沙盒内: ✅ 是" in info
    assert "缓存沙盒数: 3" in info
    assert fake_runtime.stopped is True
