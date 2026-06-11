"""共享的安全、路径与条件求值工具。"""

from .conditions import SafeConditionError, evaluate_condition
from .path_safety import (
    UnsafePathError,
    ensure_within_base,
    quote_shell_path,
    resolve_path_within_base,
    sanitize_relative_path,
    slugify_identifier,
)
from .path_utils import get_plugin_data_dir, resolve_projects_dir

__all__ = [
    "SafeConditionError",
    "UnsafePathError",
    "ensure_within_base",
    "evaluate_condition",
    "get_plugin_data_dir",
    "quote_shell_path",
    "resolve_path_within_base",
    "resolve_projects_dir",
    "sanitize_relative_path",
    "slugify_identifier",
]
