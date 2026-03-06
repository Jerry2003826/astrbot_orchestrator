"""ExecutionManager 支持组件测试。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from astrbot_orchestrator_v5.autonomous.execution_support import (
    ExecutionCommandPolicy,
    ExecutionFormatter,
)
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


def test_execution_command_policy_detects_dangerous_commands() -> None:
    """应识别危险命令并放行普通命令。"""

    policy = ExecutionCommandPolicy()

    assert policy.is_dangerous("echo ok && rm -rf /") is True
    assert policy.is_dangerous("ls -la /workspace") is False


def test_execution_command_policy_quotes_web_server_path() -> None:
    """启动服务命令应正确转义项目路径。"""

    policy = ExecutionCommandPolicy()

    command = policy.build_web_server_command(
        project_path="/tmp/demo project",
        port=8000,
        framework="fastapi",
    )

    assert "cd '/tmp/demo project'" in command
    assert "uvicorn main:app --host 0.0.0.0 --port 8000" in command


def test_execution_command_policy_builds_framework_specific_commands() -> None:
    """不同框架应生成各自的启动命令。"""

    policy = ExecutionCommandPolicy()

    flask_command = policy.build_web_server_command("/tmp/app", 5000, "flask")
    node_command = policy.build_web_server_command("/tmp/app", 3000, "node")
    default_command = policy.build_web_server_command("/tmp/app", 8080, "unknown")

    assert "nohup python main.py > server.log 2>&1 &" in flask_command
    assert "nohup node server.js > server.log 2>&1 &" in node_command
    assert "nohup python -m http.server 8080 > server.log 2>&1 &" in default_command


def test_execution_formatter_formats_result_and_files() -> None:
    """格式化器应统一渲染执行结果与文件信息。"""

    formatter = ExecutionFormatter(show_process=False)
    result = ExecResult(text="hello", exit_code=0)
    file_obj = SandboxFile(path="app/main.py", size=5, content=b"print")

    rendered_result = formatter.format_result(result, "local", "echo hello")
    rendered_file = formatter.format_written_file("/workspace", file_obj)
    rendered_list = formatter.format_file_list("app", [file_obj])

    assert "命令: `echo hello`" in rendered_result
    assert "✅ 执行完成" in rendered_result
    assert "📂 绝对路径: `/workspace/app/main.py`" in rendered_file
    assert "📁 **app** (1 个文件)" in rendered_list


def test_execution_formatter_formats_failure_process_mode_and_images() -> None:
    """失败结果应展示执行过程、错误、图片和失败状态。"""

    formatter = ExecutionFormatter(
        show_process=True,
        max_command_chars=8,
        max_output_chars=5,
        max_error_chars=4,
    )
    result = ExecResult(
        text="hello world",
        errors="traceback",
        images=["img-1", "img-2"],
        exit_code=1,
    )

    rendered = formatter.format_result(result, "shipyard", "python -c 'print(123456)'")

    assert "🤖 **执行过程:**" in rendered
    assert "🔧 使用环境: shipyard" in rendered
    assert "命令: `python -...`" in rendered
    assert "hello..." in rendered
    assert "trac..." in rendered
    assert "📷 生成了 2 张图片" in rendered
    assert "❌ 命令执行失败" in rendered


def test_execution_formatter_formats_mode_info_and_read_file_variants() -> None:
    """模式信息和文件读取结果应覆盖沙盒提示与空文件分支。"""

    formatter = ExecutionFormatter()
    info = formatter.format_mode_info("unknown", in_sandbox=True, cache_size=3)
    info_without_sandbox = formatter.format_mode_info("local", in_sandbox=False, cache_size=0)
    file_with_content = SandboxFile(path="app.py", size=5, content=b"print")
    empty_file = SandboxFile(path="empty.txt", size=0, content=b"")

    assert "运行模式: unknown" in info
    assert "在沙盒内: ✅ 是" in info
    assert "⚡ **已在 Shipyard 沙盒内运行" in info
    assert "缓存沙盒数: 3" in info
    assert "在沙盒内: ❌ 否" in info_without_sandbox
    assert "⚡ **已在 Shipyard 沙盒内运行" not in info_without_sandbox
    assert "📄 **app.py** (5.0 B)" in formatter.format_read_file(file_with_content)
    assert formatter.format_read_file(empty_file) == "❌ 文件内容为空"


def test_execution_formatter_formats_empty_list_and_truncate_boundary() -> None:
    """空目录和截断边界应返回预期文本。"""

    formatter = ExecutionFormatter()

    assert formatter.format_file_list("empty", []) == "📁 `empty` 目录为空"
    assert formatter._truncate("hello", 5) == "hello"
    assert formatter._truncate("hello world", 5) == "hello..."


def test_execution_formatter_formats_error_only_result() -> None:
    """仅有错误输出时也应渲染错误区块。"""

    formatter = ExecutionFormatter(show_process=False)
    result = ExecResult(text="", errors="boom", exit_code=1)

    rendered = formatter.format_result(result, "local", "echo fail")

    assert "**输出:**" not in rendered
    assert "**错误:**" in rendered
