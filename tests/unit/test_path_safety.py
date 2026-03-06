"""路径与标识符安全工具测试。"""

from __future__ import annotations

from pathlib import Path
import shlex
from typing import TYPE_CHECKING

import pytest

from astrbot_orchestrator_v5.shared import path_safety
from astrbot_orchestrator_v5.shared.path_safety import (
    UnsafePathError,
    ensure_within_base,
    quote_shell_path,
    sanitize_relative_path,
    slugify_identifier,
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


def test_sanitize_relative_path_normalizes_safe_input() -> None:
    """安全路径应完成裁剪、分隔符统一和多斜杠折叠。"""

    sanitized = sanitize_relative_path("  nested\\\\folder//demo.txt  ")

    assert sanitized == "nested/folder/demo.txt"


@pytest.mark.parametrize(
    ("raw_path", "message"),
    [
        ("", "路径不能为空"),
        ("/tmp/demo.txt", "不允许绝对路径"),
        ("http://example.com/demo.txt", "不允许驱动器或协议前缀"),
        ("demo\x00.txt", "路径包含控制字符"),
        ("demo;rm.txt", "路径包含 shell 元字符"),
        (".", "路径不能为空目录"),
        ("../escape.txt", "路径不能包含 . 或 .."),
        ("nested/./file.txt", "路径不能包含 . 或 .."),
    ],
)
def test_sanitize_relative_path_rejects_unsafe_values(
    raw_path: str,
    message: str,
) -> None:
    """不安全路径应被拒绝并返回对应错误信息。"""

    with pytest.raises(UnsafePathError, match=message):
        sanitize_relative_path(raw_path)


def test_ensure_within_base_returns_resolved_safe_path(tmp_path: Path) -> None:
    """安全相对路径应被解析到基目录下。"""

    base_dir = tmp_path / "workspace"
    base_dir.mkdir()

    target_path = ensure_within_base(base_dir, "nested/demo.txt")

    assert target_path == (base_dir / "nested/demo.txt").resolve()


def test_ensure_within_base_rejects_escape_when_sanitizer_is_bypassed(
    tmp_path: Path,
    monkeypatch: "MonkeyPatch",
) -> None:
    """即使前置净化被绕过，越界路径也应被最终拦截。"""

    base_dir = tmp_path / "workspace"
    base_dir.mkdir()

    def fake_sanitize_relative_path(raw_path: str) -> str:
        """模拟净化函数被意外绕过。"""

        del raw_path
        return "../escape.txt"

    monkeypatch.setattr(path_safety, "sanitize_relative_path", fake_sanitize_relative_path)

    with pytest.raises(UnsafePathError, match="路径超出允许目录"):
        ensure_within_base(base_dir, "ignored.txt")


def test_sanitize_relative_path_rejects_dot_parts_from_path_object(
    monkeypatch: "MonkeyPatch",
) -> None:
    """即使 `Path.parts` 暴露点段，最终校验也应兜底拒绝。"""

    class FakePath:
        """模拟返回异常 `parts` 的路径对象。"""

        def __init__(self, raw_path: str) -> None:
            """保存原始路径，便于实现 `as_posix`。"""

            self._raw_path = raw_path
            self.name = "file.txt"
            self.parts = ("nested", ".", "file.txt")

        def as_posix(self) -> str:
            """返回伪造路径的 POSIX 形式。"""

            return self._raw_path

    monkeypatch.setattr(path_safety, "Path", FakePath)

    with pytest.raises(UnsafePathError, match="路径不能包含 . 或 .."):
        sanitize_relative_path("nested/file.txt")


def test_slugify_identifier_normalizes_text_and_applies_default() -> None:
    """标识符 slug 化应规范字符并在为空时使用默认值。"""

    assert slugify_identifier("  Hello / Cursor Agent!  ") == "hello_cursor_agent"
    assert slugify_identifier("###", default="fallback") == "fallback"


def test_quote_shell_path_matches_shlex_behavior() -> None:
    """shell 路径引用应直接复用 shlex.quote 的规则。"""

    raw_path = "/tmp/demo project's file.txt"

    assert quote_shell_path(raw_path) == shlex.quote(raw_path)
