"""代码提取与写入组件测试。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from astrbot_orchestrator_v5.orchestrator.code_extractor import (
    CodeExtractor,
    CodeWriter,
    ProjectExporter,
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


class FakeUploadSandbox:
    """记录备用上传写入的沙盒替身。"""

    def __init__(self) -> None:
        """初始化上传记录。"""

        self.uploads: list[tuple[str, str]] = []

    async def aupload(self, file_path: str, content: str) -> None:
        """记录上传文件调用。"""

        self.uploads.append((file_path, content))


class FakeExecutor:
    """代码提取器测试用执行器替身。"""

    def __init__(self) -> None:
        """初始化调用记录和默认返回值。"""

        self.execute_calls: list[str] = []
        self.write_calls: list[tuple[str, str, bool]] = []
        self.execute_results: dict[str, str] = {}
        self.execute_errors: dict[str, Exception] = {}
        self.write_results: dict[str, str] = {}
        self.get_sandbox_error: Exception | None = None
        self.sandbox = FakeUploadSandbox()

    async def execute(self, command: str, event: object) -> str:
        """返回命令执行结果。"""

        del event
        self.execute_calls.append(command)
        if command in self.execute_errors:
            raise self.execute_errors[command]
        return self.execute_results.get(command, "ok")

    async def write_file(
        self,
        file_path: str,
        content: str,
        event: object,
        skip_auth: bool = False,
    ) -> str:
        """记录文件写入调用。"""

        del event
        self.write_calls.append((file_path, content, skip_auth))
        return self.write_results.get(file_path, "✅ 已创建")

    async def get_sandbox(self, event: object) -> FakeUploadSandbox:
        """返回备用上传沙盒。"""

        del event
        if self.get_sandbox_error is not None:
            raise self.get_sandbox_error
        return self.sandbox


def test_code_extractor_header_helpers_cover_empty_path_and_special_tokens() -> None:
    """header 辅助解析应覆盖空值、路径文件名与特殊文件名。"""

    extractor = CodeExtractor()

    assert extractor._looks_like_filename("") is False
    assert extractor._looks_like_filename("src/main.py") is True
    assert extractor._looks_like_filename("Dockerfile") is True
    assert extractor._parse_block_header("") == ("", None)
    assert extractor._parse_block_header("Dockerfile") == ("", "Dockerfile")


def test_extract_code_blocks_skip_empty_and_cover_text_fallback_variants() -> None:
    """代码块提取应跳过空块，并覆盖 text 回退与未知扩展名分支。"""

    extractor = CodeExtractor()
    mixed_text = (
        "```python\n\n```\n```\nplain text content\n```\n``` notes.foo\nhello world content\n```"
    )

    blocks = extractor.extract_code_blocks(mixed_text)

    assert len(blocks) == 2
    assert blocks[0].language == "text"
    assert blocks[0].filename is None
    assert blocks[0].content == "plain text content"
    assert blocks[1].language == "text"
    assert blocks[1].filename == "notes.foo"
    assert blocks[1].content == "hello world content"


def test_extract_code_blocks_returns_empty_when_text_has_no_fences() -> None:
    """没有代码围栏时应直接返回空列表。"""

    extractor = CodeExtractor()

    assert extractor.extract_code_blocks("plain explanation only") == []


def test_extract_code_blocks_preserves_non_chinese_filename_and_keeps_commentless_sql_without_name() -> (
    None
):
    """无扩展名英文文件名应保留，未命中注释的 SQL 块应保持无文件名。"""

    extractor = CodeExtractor()
    text = "```python README\nprint('hello')\n```\njust description\n```sql\nselect 1;\n```"

    blocks = extractor.extract_code_blocks(text)

    assert len(blocks) == 2
    assert blocks[0].filename == "README"
    assert blocks[0].language == "python"
    assert blocks[1].filename is None
    assert blocks[1].language == "sql"


def test_extract_web_project_generates_default_txt_names_for_unknown_language_blocks() -> None:
    """未知语言且无文件名时应生成默认 txt 文件名并自动去重。"""

    extractor = CodeExtractor()
    text = "```custom\nfirst custom block content\n```\n```custom\nsecond custom block content\n```"

    files = extractor.extract_web_project(text)

    assert files == {
        "file.txt": "first custom block content",
        "file_2.txt": "second custom block content",
    }


def test_extract_code_blocks_supports_space_filename_and_strips_wrappers() -> None:
    """代码块应支持空格分隔文件名并去除包裹符号。"""

    extractor = CodeExtractor()
    text = '```python ("src/main.py")\nprint("hello")\n```'

    blocks = extractor.extract_code_blocks(text)

    assert len(blocks) == 1
    assert blocks[0].language == "python"
    assert blocks[0].filename == "src/main.py"
    assert blocks[0].content == 'print("hello")'


def test_extract_code_blocks_infers_language_from_filename_without_lang() -> None:
    """缺少语言时应根据文件扩展名推断语言。"""

    extractor = CodeExtractor()
    text = '``` config.json\n{"ok": true}\n```'

    blocks = extractor.extract_code_blocks(text)

    assert len(blocks) == 1
    assert blocks[0].language == "json"
    assert blocks[0].filename == "config.json"
    assert blocks[0].content == '{"ok": true}'


def test_extract_code_blocks_ignores_chinese_description_filename_and_uses_default() -> None:
    """中文描述性文件名应被忽略并回退到默认文件名。"""

    extractor = CodeExtractor()
    text = "```python 示例代码\nprint('hello world')\n```"

    blocks = extractor.extract_code_blocks(text)

    assert len(blocks) == 1
    assert blocks[0].filename == "main.py"
    assert blocks[0].language == "python"


def test_extract_code_blocks_loads_filename_from_previous_comment() -> None:
    """无默认文件名的代码块应能从前一行注释读取文件名。"""

    extractor = CodeExtractor()
    text = "# db/query.sql\n```sql\nselect 1;\n```"

    blocks = extractor.extract_code_blocks(text)

    assert len(blocks) == 1
    assert blocks[0].filename == "db/query.sql"
    assert blocks[0].language == "sql"


def test_extract_web_project_keeps_safe_nested_filename() -> None:
    """应保留安全的相对路径文件名。"""

    extractor = CodeExtractor()
    text = "```python:src/main.py\nprint('hello')\n```"

    files = extractor.extract_web_project(text)

    assert files == {"src/main.py": "print('hello')"}


def test_extract_web_project_drops_unsafe_filename_to_default() -> None:
    """不安全文件名应被丢弃并回退到默认文件名。"""

    extractor = CodeExtractor()
    text = "```python:../../etc/passwd\nprint('blocked')\n```"

    files = extractor.extract_web_project(text)

    assert files == {"main.py": "print('blocked')"}


def test_extract_web_project_deduplicates_default_filenames() -> None:
    """多个同类默认文件名应自动追加序号。"""

    extractor = CodeExtractor()
    text = "```javascript\nconsole.log('a')\n```\n```javascript\nconsole.log('b')\n```"

    files = extractor.extract_web_project(text)

    assert files == {
        "app.js": "console.log('a')",
        "app_2.js": "console.log('b')",
    }


def test_extract_web_project_skips_unsafe_filename_from_comment() -> None:
    """从注释中读取到不安全文件名时应直接跳过。"""

    extractor = CodeExtractor()
    text = "# ../../etc/passwd.txt\n```sql\nselect 1;\n```"

    files = extractor.extract_web_project(text)

    assert files == {}


def test_should_save_code_supports_unknown_filename_and_rejects_short_content() -> None:
    """未知语言但具备文件名的长内容应保存，短内容则不保存。"""

    extractor = CodeExtractor()
    savable_text = "```custom:notes.txt\nThis is a sufficiently long custom file.\n```"
    short_text = "```txt:notes.txt\nshort\n```"

    assert extractor.should_save_code(savable_text) is True
    assert extractor.should_save_code(short_text) is False


def test_should_save_code_covers_saveable_language_and_filename_extension_paths() -> None:
    """保存判定应覆盖可保存语言与可保存扩展名分支。"""

    extractor = CodeExtractor()
    python_text = "```python\nprint('this python output is definitely long enough')\n```"
    ext_text = "```custom:notes.py\n12345678901\n```"

    assert extractor.should_save_code(python_text) is True
    assert extractor.should_save_code(ext_text) is True
    assert extractor.should_save_code("```\nthis is plain text without filename\n```") is False


@pytest.mark.asyncio
async def test_project_exporter_runs_listing_and_tar_commands() -> None:
    """项目导出器应先列目录再打包文件。"""

    executor = FakeExecutor()
    exporter = ProjectExporter()

    success, message = await exporter.export_from_sandbox(
        executor=executor,
        event=object(),
        project_name="demo",
        sandbox_path="/workspace/demo",
    )

    assert success is True
    assert message == "项目已打包: /tmp/project.tar.gz"
    assert executor.execute_calls == [
        "ls -la /workspace/demo",
        "cd /workspace/demo && tar -czf /tmp/project.tar.gz .",
    ]
    assert exporter.get_download_path("demo") == "/www/wwwroot/downloads/demo"


@pytest.mark.asyncio
async def test_project_exporter_returns_failure_on_exception() -> None:
    """项目导出失败时应返回失败消息。"""

    executor = FakeExecutor()
    executor.execute_errors["cd /workspace/demo && tar -czf /tmp/project.tar.gz ."] = RuntimeError(
        "tar failed"
    )
    exporter = ProjectExporter()

    success, message = await exporter.export_from_sandbox(
        executor=executor,
        event=object(),
        project_name="demo",
        sandbox_path="/workspace/demo",
    )

    assert success is False
    assert message == "导出失败: tar failed"


@pytest.mark.asyncio
async def test_code_writer_writes_files_and_creates_nested_directories() -> None:
    """写入器应创建项目目录、子目录并写入文件。"""

    executor = FakeExecutor()
    writer = CodeWriter(executor, base_path="/workspace")

    success, created_files = await writer.write_files(
        files={
            "main.py": "print('main')",
            "src/app.py": "print('app')",
        },
        event=object(),
        project_name="demo",
    )

    assert success is True
    assert created_files == [
        "/workspace/demo/main.py",
        "/workspace/demo/src/app.py",
    ]
    assert executor.execute_calls == [
        "mkdir -p /workspace/demo",
        "mkdir -p /workspace/demo/src",
    ]
    assert executor.write_calls == [
        ("/workspace/demo/main.py", "print('main')", True),
        ("/workspace/demo/src/app.py", "print('app')", True),
    ]


@pytest.mark.asyncio
async def test_code_writer_falls_back_to_upload_when_write_result_unexpected() -> None:
    """写入返回异常文本时应回退到 upload 备用路径。"""

    executor = FakeExecutor()
    executor.write_results["/workspace/demo/main.py"] = "write failed"
    writer = CodeWriter(executor, base_path="/workspace")

    success, created_files = await writer.write_files(
        files={"main.py": "print('fallback')"},
        event=object(),
        project_name="demo",
    )

    assert success is True
    assert created_files == ["/workspace/demo/main.py"]
    assert executor.sandbox.uploads == [("/workspace/demo/main.py", "print('fallback')")]


@pytest.mark.asyncio
async def test_code_writer_handles_upload_fallback_failure() -> None:
    """upload 备用写入也失败时应返回失败且不记录文件。"""

    executor = FakeExecutor()
    executor.write_results["/workspace/demo/main.py"] = "write failed"
    executor.get_sandbox_error = RuntimeError("sandbox unavailable")
    writer = CodeWriter(executor, base_path="/workspace")

    success, created_files = await writer.write_files(
        files={"main.py": "print('fallback')"},
        event=object(),
        project_name="demo",
    )

    assert success is False
    assert created_files == []


@pytest.mark.asyncio
async def test_code_writer_returns_partial_failure_when_project_creation_raises() -> None:
    """项目目录创建失败时应走总异常兜底并返回空结果。"""

    executor = FakeExecutor()
    executor.execute_errors["mkdir -p /workspace/demo"] = RuntimeError("mkdir failed")
    writer = CodeWriter(executor, base_path="/workspace")

    success, created_files = await writer.write_files(
        files={"main.py": "print('x')"},
        event=object(),
        project_name="demo",
    )

    assert success is False
    assert created_files == []


@pytest.mark.asyncio
async def test_code_writer_get_project_files_filters_noise() -> None:
    """文件列表应过滤掉提示文本和无关行。"""

    executor = FakeExecutor()
    executor.execute_results["find /workspace/demo -type f"] = (
        "🖥️ shell banner\n"
        "命令执行完成\n"
        "/workspace/demo/main.py\n"
        "/workspace/demo/src/app.py\n"
        "/tmp/outside.txt\n"
    )
    writer = CodeWriter(executor, base_path="/workspace")

    files = await writer.get_project_files(event=object(), project_name="demo")

    assert files == [
        "/workspace/demo/main.py",
        "/workspace/demo/src/app.py",
    ]


@pytest.mark.asyncio
async def test_code_writer_get_project_files_returns_empty_on_failure() -> None:
    """获取文件列表失败时应返回空列表。"""

    executor = FakeExecutor()
    executor.execute_errors["find /workspace/demo -type f"] = RuntimeError("find failed")
    writer = CodeWriter(executor, base_path="/workspace")

    files = await writer.get_project_files(event=object(), project_name="demo")

    assert files == []
