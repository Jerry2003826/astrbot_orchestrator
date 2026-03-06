"""ArtifactService 测试。"""

from __future__ import annotations

import builtins
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from astrbot_orchestrator_v5.artifacts.service import ArtifactService
from astrbot_orchestrator_v5.shared import quote_shell_path

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


LIST_SANDBOX_FILES_COMMAND = (
    "find /home/ship_*/workspace /workspace -type f "
    "-not -path '*/\\.git/*' -not -path '*/__pycache__/*' "
    "-not -name '*.pyc' -not -path '*/skills/*' "
    "2>/dev/null | head -200"
)


def test_artifact_service_collects_all_outputs_and_answer(tmp_path: Path) -> None:
    """应合并所有任务输出与最终回答文本。"""

    service = ArtifactService(persist_dir=str(tmp_path))
    result = {
        "_all_task_outputs": ["第一段输出", "第二段输出"],
        "answer": "最终回答",
    }

    combined = service.collect_output_text(result)

    assert "第一段输出" in combined
    assert "第二段输出" in combined
    assert "最终回答" in combined


def test_artifact_service_text_helpers_handle_blank_and_extract_code(tmp_path: Path) -> None:
    """文本辅助函数应处理空白内容并提取代码文件。"""

    service = ArtifactService(persist_dir=str(tmp_path))
    output_text = (
        "前置说明\n"
        "```python:src/main.py\n"
        "print('artifact service coverage check')\n"
        "```\n"
        "```json:config.json\n"
        '{"mode": "safe", "enabled": true}\n'
        "```"
    )

    assert service.extract_files_from_text("   ") == {}
    assert service.should_save_output_text("   ") is False
    assert service.count_code_blocks("   ") == 0
    assert service.extract_files_from_text(output_text) == {
        "src/main.py": "print('artifact service coverage check')",
        "config.json": '{"mode": "safe", "enabled": true}',
    }
    assert service.should_save_output_text(output_text) is True
    assert service.count_code_blocks(output_text) == 2


def test_artifact_service_extracts_files_from_result_and_persists(tmp_path: Path) -> None:
    """结果对象中的代码应能被提取并持久化到安全目录。"""

    service = ArtifactService(persist_dir=str(tmp_path))
    result = {
        "_all_task_outputs": ["```python:app.py\nprint('from task output')\n```"],
        "answer": "```css:assets/site.css\nbody { color: #333; }\n```",
    }

    extracted_files = service.extract_files_from_result(result)
    persisted = service.persist_result(result, "Demo Project")

    assert extracted_files == {
        "app.py": "print('from task output')",
        "assets/site.css": "body { color: #333; }",
    }
    assert persisted["success"] is True
    assert persisted["saved_files"] == ["app.py", "assets/site.css"]
    assert (tmp_path / "demo_project" / "app.py").read_text(
        encoding="utf-8"
    ) == "print('from task output')"
    assert (tmp_path / "demo_project" / "assets" / "site.css").read_text(
        encoding="utf-8"
    ) == "body { color: #333; }"


def test_artifact_service_persist_result_handles_empty_and_plain_text(tmp_path: Path) -> None:
    """无输出或无代码时应返回明确结果而不是报错。"""

    service = ArtifactService(persist_dir=str(tmp_path))

    empty_result = service.persist_result({}, "demo")
    plain_text_result = service.persist_result({"answer": "这里只是普通说明文本"}, "demo")

    assert empty_result == {"success": False, "error": "无输出内容"}
    assert plain_text_result == {"success": True, "saved_files": [], "path": ""}


def test_artifact_service_skips_unsafe_paths_when_persisting(tmp_path: Path) -> None:
    """持久化时应跳过不安全路径。"""

    service = ArtifactService(persist_dir=str(tmp_path))
    result = service.persist_files(
        files={
            "safe/main.py": "print('ok')",
            "../escape.txt": "boom",
        },
        project_name="demo",
    )

    assert result["saved_files"] == ["safe/main.py"]
    assert not (tmp_path / "escape.txt").exists()
    assert (tmp_path / "demo" / "safe" / "main.py").read_text(encoding="utf-8") == "print('ok')"


def test_artifact_service_returns_empty_result_when_persist_write_fails(
    monkeypatch: "MonkeyPatch",
    tmp_path: Path,
) -> None:
    """写入异常时应返回空保存结果而不是中断流程。"""

    service = ArtifactService(persist_dir=str(tmp_path))
    real_open = builtins.open

    def failing_open(*args: Any, **kwargs: Any) -> Any:
        """对目标文件模拟写入失败。"""

        if args and str(args[0]).endswith("main.py"):
            raise OSError("disk full")
        return real_open(*args, **kwargs)

    monkeypatch.setattr(builtins, "open", failing_open)

    result = service.persist_files({"safe/main.py": "print('ok')"}, "demo")

    assert result == {
        "success": True,
        "saved_files": [],
        "path": str(tmp_path / "demo"),
        "total": 0,
    }


class FakeExecutor:
    """测试用执行器。"""

    def __init__(self) -> None:
        """初始化执行记录。"""

        self.commands: list[str] = []
        self.writes: dict[str, str] = {}

    async def execute(self, command: str, event: object) -> str:
        """记录命令执行。"""

        del event
        self.commands.append(command)
        return "ok"

    async def write_file(
        self,
        file_path: str,
        content: str,
        event: object,
        skip_auth: bool = False,
    ) -> str:
        """记录文件写入。"""

        del event
        del skip_auth
        self.writes[file_path] = content
        return "✅ 已创建"


@dataclass
class FakeSandboxResult:
    """模拟沙盒执行结果。"""

    text: str = ""
    exit_code: int = 0


class FakeSandbox:
    """按命令返回预设结果的沙盒替身。"""

    def __init__(
        self,
        command_results: dict[str, FakeSandboxResult | Exception],
    ) -> None:
        """保存命令到执行结果的映射。"""

        self.command_results = dict(command_results)
        self.commands: list[str] = []

    async def aexec(self, command: str, kernel: str) -> FakeSandboxResult:
        """返回命令对应的结果。"""

        assert kernel == "bash"
        self.commands.append(command)
        result = self.command_results.get(command, FakeSandboxResult(text="", exit_code=1))
        if isinstance(result, Exception):
            raise result
        return result


class FakeSandboxExecutor:
    """测试用沙盒执行器。"""

    def __init__(
        self,
        sandbox: FakeSandbox | None = None,
        error: Exception | None = None,
    ) -> None:
        """保存沙盒实例或预设异常。"""

        self.sandbox = sandbox
        self.error = error

    async def get_sandbox(self, event: object) -> FakeSandbox:
        """返回预设沙盒或抛出异常。"""

        del event
        if self.error is not None:
            raise self.error
        if self.sandbox is None:
            raise RuntimeError("sandbox unavailable")
        return self.sandbox


@pytest.mark.asyncio
async def test_artifact_service_write_files_to_workspace_returns_empty_for_no_files(
    tmp_path: Path,
) -> None:
    """没有文件时不应触发任何工作区写入。"""

    service = ArtifactService(persist_dir=str(tmp_path))
    executor = FakeExecutor()

    created_files = await service.write_files_to_workspace(
        files={},
        executor=executor,
        event=object(),
        project_name="Demo Project",
    )

    assert created_files == []
    assert executor.commands == []
    assert executor.writes == {}


@pytest.mark.asyncio
async def test_artifact_service_writes_output_to_workspace(tmp_path: Path) -> None:
    """应将提取出的代码写入工作区。"""

    service = ArtifactService(persist_dir=str(tmp_path))
    executor = FakeExecutor()

    created_files = await service.write_output_to_workspace(
        output_text="""```python:main.py
print("ok")
```""",
        executor=executor,
        event=object(),
        project_name="Demo Project",
    )

    assert created_files == ["/workspace/demo_project/main.py"]
    assert executor.commands == ["mkdir -p /workspace/demo_project"]
    assert executor.writes["/workspace/demo_project/main.py"] == 'print("ok")'


@pytest.mark.asyncio
async def test_artifact_service_export_sandbox_files_handles_get_sandbox_failure(
    tmp_path: Path,
) -> None:
    """获取沙盒失败时应返回失败结果。"""

    service = ArtifactService(persist_dir=str(tmp_path))
    executor = FakeSandboxExecutor(error=RuntimeError("no sandbox"))

    result = await service.export_sandbox_files(
        executor=executor,
        event=object(),
        project_name="Demo Project",
        created_files=[],
    )

    assert result == {"success": False, "error": "获取沙盒失败: no sandbox"}


@pytest.mark.asyncio
async def test_artifact_service_export_sandbox_files_uses_scan_results_and_skips_failed_reads(
    tmp_path: Path,
) -> None:
    """扫描到的工作区文件应被导出，读取失败的文件应被跳过。"""

    safe_remote = "/workspace/src/app.py"
    failed_remote = "/workspace/src/bad.py"
    sandbox = FakeSandbox(
        command_results={
            LIST_SANDBOX_FILES_COMMAND: FakeSandboxResult(
                text=f"{safe_remote}\n/workspace/README\n{failed_remote}\n/tmp/outside.py\n"
            ),
            f"cat {quote_shell_path(safe_remote)} 2>/dev/null": FakeSandboxResult(
                text="print('ok')",
                exit_code=0,
            ),
            f"cat {quote_shell_path(failed_remote)} 2>/dev/null": FakeSandboxResult(
                text="",
                exit_code=1,
            ),
        }
    )
    service = ArtifactService(persist_dir=str(tmp_path))
    executor = FakeSandboxExecutor(sandbox=sandbox)

    result = await service.export_sandbox_files(
        executor=executor,
        event=object(),
        project_name="Demo Project",
        created_files=[],
    )

    assert result["success"] is True
    assert result["saved_files"] == ["src/app.py"]
    assert (tmp_path / "demo_project" / "src" / "app.py").read_text(
        encoding="utf-8"
    ) == "print('ok')"


@pytest.mark.asyncio
async def test_artifact_service_export_sandbox_files_falls_back_to_created_files_and_skips_unsafe(
    tmp_path: Path,
) -> None:
    """扫描为空时应回退到 created_files，并拒绝不安全路径。"""

    safe_remote = "/tmp/main.py"
    unsafe_remote = "/workspace/../escape.py"
    empty_remote = "/tmp/empty-dir/"
    sandbox = FakeSandbox(
        command_results={
            LIST_SANDBOX_FILES_COMMAND: FakeSandboxResult(text="", exit_code=0),
            f"cat {quote_shell_path(safe_remote)} 2>/dev/null": FakeSandboxResult(
                text="print('fallback')",
                exit_code=0,
            ),
            f"cat {quote_shell_path(unsafe_remote)} 2>/dev/null": FakeSandboxResult(
                text="print('unsafe')",
                exit_code=0,
            ),
        }
    )
    service = ArtifactService(persist_dir=str(tmp_path))
    executor = FakeSandboxExecutor(sandbox=sandbox)

    result = await service.export_sandbox_files(
        executor=executor,
        event=object(),
        project_name="Demo Project",
        created_files=[safe_remote, unsafe_remote, empty_remote],
    )

    assert result["success"] is True
    assert result["saved_files"] == ["main.py"]
    assert (tmp_path / "demo_project" / "main.py").read_text(
        encoding="utf-8"
    ) == "print('fallback')"
    assert not (tmp_path / "demo_project" / "escape.py").exists()


@pytest.mark.asyncio
async def test_artifact_service_export_sandbox_files_handles_scan_failure(tmp_path: Path) -> None:
    """扫描沙盒失败时应记录错误并返回空导出结果。"""

    sandbox = FakeSandbox(command_results={LIST_SANDBOX_FILES_COMMAND: RuntimeError("scan failed")})
    service = ArtifactService(persist_dir=str(tmp_path))
    executor = FakeSandboxExecutor(sandbox=sandbox)

    result = await service.export_sandbox_files(
        executor=executor,
        event=object(),
        project_name="Demo Project",
        created_files=[],
    )

    assert result == {
        "success": True,
        "path": str(tmp_path / "demo_project"),
        "saved_files": [],
        "total": 0,
    }


@pytest.mark.asyncio
async def test_artifact_service_export_sandbox_files_skips_local_write_failure(
    monkeypatch: "MonkeyPatch",
    tmp_path: Path,
) -> None:
    """导出文件落盘失败时应跳过当前文件并继续返回结果。"""

    safe_remote = "/workspace/src/app.py"
    sandbox = FakeSandbox(
        command_results={
            LIST_SANDBOX_FILES_COMMAND: FakeSandboxResult(text=f"{safe_remote}\n", exit_code=0),
            f"cat {quote_shell_path(safe_remote)} 2>/dev/null": FakeSandboxResult(
                text="print('write failure')",
                exit_code=0,
            ),
        }
    )
    service = ArtifactService(persist_dir=str(tmp_path))
    executor = FakeSandboxExecutor(sandbox=sandbox)
    real_open = builtins.open

    def failing_open(*args: Any, **kwargs: Any) -> Any:
        """仅对导出目标文件模拟写盘失败。"""

        if args and str(args[0]).endswith("src/app.py"):
            raise OSError("permission denied")
        return real_open(*args, **kwargs)

    monkeypatch.setattr(builtins, "open", failing_open)

    result = await service.export_sandbox_files(
        executor=executor,
        event=object(),
        project_name="Demo Project",
        created_files=[],
    )

    assert result == {
        "success": True,
        "path": str(tmp_path / "demo_project"),
        "saved_files": [],
        "total": 0,
    }
