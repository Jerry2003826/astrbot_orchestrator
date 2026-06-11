"""代码执行能力的 FunctionTool 封装（复用 autonomous/executor.py）。

执行模式（local / sandbox）由 ExecutionManager 按插件配置与宿主
provider_settings 决定，这里只做轻薄转发与管理员门控。
"""

from __future__ import annotations

from typing import Any

from .base import OrchestratorTool, obj_schema, str_prop


class SandboxExecPythonTool(OrchestratorTool):
    def __init__(self, runtime: Any) -> None:
        super().__init__(
            runtime,
            name="sandbox_exec_python",
            description=(
                "在受控环境（沙盒或本地受限模式）中执行 Python 代码并返回输出（管理员）。"
                "适合数据处理、文件生成、计算等任务。"
            ),
            parameters=obj_schema(
                {"code": str_prop("要执行的完整 Python 代码")},
                required=["code"],
            ),
        )

    async def run(self, event: Any, code: str) -> str:
        if denied := self.check_permission(event):
            return denied
        return await self.runtime.executor.execute_python(code, event)


class SandboxExecBashTool(OrchestratorTool):
    def __init__(self, runtime: Any) -> None:
        super().__init__(
            runtime,
            name="sandbox_exec_bash",
            description="在受控环境（沙盒或本地受限模式）中执行 shell 命令并返回输出（管理员）。",
            parameters=obj_schema(
                {"command": str_prop("要执行的 shell 命令")},
                required=["command"],
            ),
        )

    async def run(self, event: Any, command: str) -> str:
        if denied := self.check_permission(event):
            return denied
        return await self.runtime.executor.execute(command, event)


class SandboxFileReadTool(OrchestratorTool):
    def __init__(self, runtime: Any) -> None:
        super().__init__(
            runtime,
            name="sandbox_file_read",
            description="读取执行环境中的文件内容（管理员）。",
            parameters=obj_schema(
                {"file_path": str_prop("文件路径（执行环境内）")},
                required=["file_path"],
            ),
        )

    async def run(self, event: Any, file_path: str) -> str:
        if denied := self.check_permission(event):
            return denied
        return await self.runtime.executor.read_file(file_path, event)


class SandboxFileWriteTool(OrchestratorTool):
    def __init__(self, runtime: Any) -> None:
        super().__init__(
            runtime,
            name="sandbox_file_write",
            description="向执行环境写入文件（管理员）。用于生成代码文件、配置等。",
            parameters=obj_schema(
                {
                    "file_path": str_prop("目标文件路径（执行环境内）"),
                    "content": str_prop("要写入的完整文件内容"),
                },
                required=["file_path", "content"],
            ),
        )

    async def run(self, event: Any, file_path: str, content: str) -> str:
        if denied := self.check_permission(event):
            return denied
        return await self.runtime.executor.write_file(file_path, content, event)


class SandboxInstallPackagesTool(OrchestratorTool):
    def __init__(self, runtime: Any) -> None:
        super().__init__(
            runtime,
            name="sandbox_install_packages",
            description="在执行环境中安装 Python 包（管理员）。",
            parameters=obj_schema(
                {
                    "packages": {
                        "type": "array",
                        "description": "要安装的 pip 包名列表",
                        "items": {"type": "string"},
                    }
                },
                required=["packages"],
            ),
        )

    async def run(self, event: Any, packages: list[str]) -> str:
        if denied := self.check_permission(event):
            return denied
        return await self.runtime.executor.install_packages(packages, event)
