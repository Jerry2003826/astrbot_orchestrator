"""
CodeSandbox - 类似 CodeBox API 的统一沙盒抽象层

提供统一的代码执行、文件管理、包管理接口，
支持 local（IPython）、docker（Shipyard）、remote 三种模式。

特殊逻辑：
当检测到当前进程已运行在 Shipyard 沙盒容器内时，
自动使用 local 模式执行，避免嵌套创建沙盒。

Usage:
    from .sandbox import CodeSandbox, ExecResult, SandboxFile

    sandbox = CodeSandbox(mode="local")
    result = await sandbox.aexec("print('Hello')")
    print(result.text)
"""

from .types import ExecResult, ExecChunk, SandboxFile
from .base import CodeSandbox
from .factory import create_sandbox, is_inside_shipyard_sandbox

__all__ = [
    "CodeSandbox",
    "ExecResult",
    "ExecChunk",
    "SandboxFile",
    "create_sandbox",
    "is_inside_shipyard_sandbox",
]
