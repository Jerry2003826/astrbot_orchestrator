"""路径与标识符安全工具。"""

from __future__ import annotations

from pathlib import Path
import re
import shlex

_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x1F\x7F]")
_SHELL_META_PATTERN = re.compile(r"[;&|`$<>!]")
_MULTISLASH_PATTERN = re.compile(r"/+")
_INVALID_IDENTIFIER_PATTERN = re.compile(r"[^a-z0-9_-]+")


class UnsafePathError(ValueError):
    """表示路径不安全或超出允许边界。"""


def sanitize_relative_path(raw_path: str) -> str:
    """验证并规范化相对路径。

    Args:
        raw_path: 原始路径。

    Returns:
        规范化后的相对路径。

    Raises:
        UnsafePathError: 当路径为空、包含危险字符或尝试逃逸基目录时。
    """

    candidate = raw_path.strip().replace("\\", "/")
    candidate = _MULTISLASH_PATTERN.sub("/", candidate)

    if not candidate:
        raise UnsafePathError("路径不能为空")
    if candidate.startswith("/"):
        raise UnsafePathError("不允许绝对路径")
    if ":" in candidate:
        raise UnsafePathError("不允许驱动器或协议前缀")
    if _CONTROL_CHAR_PATTERN.search(candidate):
        raise UnsafePathError("路径包含控制字符")
    if _SHELL_META_PATTERN.search(candidate):
        raise UnsafePathError("路径包含 shell 元字符")

    normalized = Path(candidate)
    if normalized.name in {"", ".", ".."}:
        raise UnsafePathError("路径不能为空目录")

    raw_parts = candidate.split("/")
    if any(part in {".", ".."} for part in raw_parts):
        raise UnsafePathError("路径不能包含 . 或 ..")

    parts = normalized.parts
    if any(part in {"", ".", ".."} for part in parts):
        raise UnsafePathError("路径不能包含 . 或 ..")

    return normalized.as_posix()


def ensure_within_base(base_dir: str | Path, relative_path: str) -> Path:
    """将相对路径解析到基目录，并确保不越界。

    Args:
        base_dir: 允许写入的基目录。
        relative_path: 相对路径。

    Returns:
        解析后的绝对路径。

    Raises:
        UnsafePathError: 当路径超出基目录时。
    """

    base_path = Path(base_dir).resolve()
    safe_relative = sanitize_relative_path(relative_path)
    target_path = (base_path / safe_relative).resolve()

    if target_path != base_path and base_path not in target_path.parents:
        raise UnsafePathError("路径超出允许目录")

    return target_path


def slugify_identifier(raw_name: str, default: str = "generated") -> str:
    """将不可信名称转换为安全标识符。

    Args:
        raw_name: 原始名称。
        default: 转换后为空时使用的默认值。

    Returns:
        适合目录名或逻辑标识的 slug。
    """

    normalized = raw_name.strip().lower().replace(" ", "_")
    normalized = normalized.replace("\\", "_").replace("/", "_")
    normalized = _INVALID_IDENTIFIER_PATTERN.sub("_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")

    return normalized or default


def quote_shell_path(path: str | Path) -> str:
    """对 shell 中使用的路径进行转义。"""

    return shlex.quote(str(path))
