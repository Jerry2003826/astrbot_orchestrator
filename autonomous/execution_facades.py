"""执行器门面与低层沙盒操作客户端。"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, cast

from ..sandbox import CodeSandbox, ExecChunk, ExecResult, SandboxFile
from .execution_support import ExecutionCommandPolicy, ExecutionFormatter
from .sandbox_runtime import SandboxRuntime

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ExecutionAccessPolicy:
    """封装基于事件角色的执行权限判断。"""

    def is_admin(self, event: Any) -> bool:
        """判断当前事件是否具备管理员权限。"""

        return getattr(event, "role", None) == "admin"

    def require_admin(self, event: Any, failure_message: str) -> str | None:
        """缺少管理员权限时返回失败提示，否则返回 `None`。"""

        if self.is_admin(event):
            return None
        return failure_message


@dataclass(slots=True)
class SandboxApiClient:
    """对 `SandboxRuntime` 暴露稳定的低层操作接口。"""

    runtime: SandboxRuntime

    async def get_sandbox(
        self,
        event: Any = None,
        mode: str | None = None,
        session_id: str | None = None,
    ) -> CodeSandbox:
        """获取一个可用的沙盒实例。"""

        return await self.runtime.get_sandbox(event=event, mode=mode, session_id=session_id)

    async def run_code(
        self,
        code: str,
        event: Any,
        kernel: str = "ipython",
        mode: str | None = None,
    ) -> tuple[CodeSandbox, ExecResult]:
        """在指定沙盒中执行代码并返回原始结果。"""

        sandbox = await self.get_sandbox(event=event, mode=mode)
        result = cast(ExecResult, await sandbox.aexec(code, kernel=kernel))
        return sandbox, result

    async def exec_code(
        self,
        code: str,
        event: Any,
        kernel: str = "ipython",
        stream: bool = False,
    ) -> ExecResult | AsyncGenerator[ExecChunk, None]:
        """执行代码，支持普通与流式两种模式。"""

        sandbox = await self.get_sandbox(event=event)
        if stream:
            return cast(AsyncGenerator[ExecChunk, None], sandbox.astream_exec(code, kernel=kernel))
        return cast(ExecResult, await sandbox.aexec(code, kernel=kernel))

    async def upload_file(
        self,
        remote_path: str,
        content: bytes | str,
        event: Any,
    ) -> tuple[CodeSandbox, SandboxFile]:
        """上传文件并返回沙盒对象与文件元数据。"""

        sandbox = await self.get_sandbox(event=event)
        sandbox_file = cast(SandboxFile, await sandbox.aupload(remote_path, content))
        return sandbox, sandbox_file

    async def download_file(self, remote_path: str, event: Any) -> SandboxFile:
        """下载文件内容。"""

        sandbox = await self.get_sandbox(event=event)
        return cast(SandboxFile, await sandbox.adownload(remote_path))

    async def list_sandbox_files(self, path: str = ".", event: Any = None) -> list[SandboxFile]:
        """列出目录内文件。"""

        sandbox = await self.get_sandbox(event=event)
        return cast(list[SandboxFile], await sandbox.alist_files(path))

    async def install_packages(self, packages: list[str], event: Any) -> str:
        """在沙盒中安装 Python 包。"""

        sandbox = await self.get_sandbox(event=event)
        return cast(str, await sandbox.ainstall(*packages))

    async def list_packages(self, event: Any) -> list[str]:
        """返回当前沙盒中的包列表。"""

        sandbox = await self.get_sandbox(event=event)
        return cast(list[str], await sandbox.alist_packages())

    async def show_variables(self, event: Any) -> dict[str, str]:
        """返回当前沙盒中的会话变量。"""

        sandbox = await self.get_sandbox(event=event)
        return cast(dict[str, str], await sandbox.ashow_variables())

    async def download_from_url(self, url: str, file_path: str, event: Any) -> SandboxFile:
        """从 URL 下载文件到沙盒。"""

        sandbox = await self.get_sandbox(event=event)
        return cast(SandboxFile, await sandbox.afile_from_url(url, file_path))


@dataclass(slots=True)
class LegacyExecutionFacade:
    """兼容旧执行接口的门面，负责权限校验与文本结果拼装。"""

    api_client: SandboxApiClient
    formatter: ExecutionFormatter
    command_policy: ExecutionCommandPolicy
    access_policy: ExecutionAccessPolicy = field(default_factory=ExecutionAccessPolicy)

    async def execute(self, command: str, event: Any) -> str:
        """执行普通 shell 命令。"""

        denied = self.access_policy.require_admin(event, "❌ 只有管理员可以执行命令")
        if denied is not None:
            return denied
        return await self._execute_shell(command, event)

    async def execute_local(self, command: str, event: Any) -> str:
        """强制在本地模式执行 shell 命令。"""

        denied = self.access_policy.require_admin(event, "❌ 只有管理员可以执行本地命令")
        if denied is not None:
            return denied
        return await self._execute_shell(
            command=command,
            event=event,
            mode="local",
            mode_label="local",
        )

    async def execute_sandbox(self, command: str, event: Any) -> str:
        """强制在 shipyard 模式执行 shell 命令。"""

        denied = self.access_policy.require_admin(event, "❌ 只有管理员可以执行命令")
        if denied is not None:
            return denied
        return await self._execute_shell(
            command=command,
            event=event,
            mode="shipyard",
            mode_label="shipyard",
            failure_prefix="❌ 沙盒执行失败",
        )

    async def execute_python(
        self,
        code: str,
        event: Any,
        force_mode: str | None = None,
    ) -> str:
        """执行 Python 代码并返回格式化结果。"""

        denied = self.access_policy.require_admin(event, "❌ 只有管理员可以执行代码")
        if denied is not None:
            return denied

        try:
            sandbox, result = await self.api_client.run_code(
                code=code,
                event=event,
                kernel="ipython",
                mode=force_mode,
            )
        except Exception as exc:
            return f"❌ 执行失败: {str(exc)}"
        command_label = f"python: {code[:50]}..."
        return cast(str, self.formatter.format_result(result, sandbox.mode, command_label))

    async def auto_execute(
        self,
        code: str,
        event: Any,
        code_type: str = "shell",
    ) -> str:
        """执行自动推断出的 shell 或 Python 代码。"""

        if self.command_policy.is_dangerous(code):
            return "❌ 检测到潜在危险命令，已拒绝执行"

        kernel = "ipython" if code_type == "python" else "bash"
        try:
            sandbox, result = await self.api_client.run_code(code=code, event=event, kernel=kernel)
        except Exception as exc:
            return f"❌ 执行失败: {str(exc)}"
        return cast(str, self.formatter.format_result(result, sandbox.mode, code))

    async def write_file(
        self,
        file_path: str,
        content: str,
        event: Any,
        skip_auth: bool = False,
    ) -> str:
        """兼容旧接口地写入文件。"""

        if not skip_auth:
            denied = self.access_policy.require_admin(event, "❌ 只有管理员可以写入文件")
            if denied is not None:
                return denied

        try:
            sandbox, sandbox_file = await self.api_client.upload_file(file_path, content, event)
        except Exception as exc:
            logger.error("❌ 文件写入失败: %s -> %s", file_path, exc)
            return f"❌ 创建文件失败: {str(exc)}"

        logger.info("✅ 文件写入成功: %s (%s)", sandbox_file.path, sandbox_file.size_human)
        return cast(str, self.formatter.format_written_file(sandbox.cwd, sandbox_file))

    async def read_file(self, file_path: str, event: Any) -> str:
        """兼容旧接口地读取文件。"""

        try:
            sandbox_file = await self.api_client.download_file(file_path, event)
        except FileNotFoundError:
            return f"❌ 文件不存在: {file_path}"
        except Exception as exc:
            return f"❌ 读取失败: {str(exc)}"
        return cast(str, self.formatter.format_read_file(sandbox_file))

    async def list_files(self, dir_path: str, event: Any) -> str:
        """兼容旧接口地列出目录文件。"""

        try:
            files = await self.api_client.list_sandbox_files(dir_path, event)
        except Exception as exc:
            return f"❌ 列出文件失败: {str(exc)}"
        return cast(str, self.formatter.format_file_list(dir_path, files))

    async def start_web_server(
        self,
        project_path: str,
        port: int,
        event: Any,
        framework: str = "python",
    ) -> str:
        """启动 Web 服务并返回提示文本。"""

        denied = self.access_policy.require_admin(event, "❌ 只有管理员可以启动服务")
        if denied is not None:
            return denied

        command = self.command_policy.build_web_server_command(project_path, port, framework)
        try:
            await self.api_client.run_code(command, event=event, kernel="bash")
        except Exception as exc:
            return f"❌ 启动失败: {str(exc)}"
        return (
            f"🚀 **服务启动中...**\n\n"
            f"项目: `{project_path}`\n"
            f"端口: {port}\n"
            f"框架: {framework}"
        )

    async def healthcheck(self, event: Any = None) -> str:
        """返回当前沙盒健康状态。"""

        try:
            sandbox = await self.api_client.get_sandbox(event=event)
            health = await sandbox.ahealthcheck()
        except Exception as exc:
            return f"❌ 沙盒不可用: {str(exc)}"
        return f"✅ 沙盒状态: {health} (模式: {sandbox.mode})"

    async def restart_sandbox(self, event: Any) -> str:
        """重启当前沙盒。"""

        try:
            sandbox = await self.api_client.get_sandbox(event=event)
            await sandbox.arestart()
        except Exception as exc:
            return f"❌ 重启失败: {str(exc)}"
        return f"✅ 沙盒已重启 (模式: {sandbox.mode})"

    async def check_port(self, port: int, event: Any) -> str:
        """检查端口占用情况。"""

        command = f"netstat -tlnp 2>/dev/null | grep :{port} || echo '端口未被占用'"
        try:
            _, result = await self.api_client.run_code(command, event=event, kernel="bash")
        except Exception as exc:
            return f"❌ 检查失败: {str(exc)}"
        return str(result.text)

    async def _execute_shell(
        self,
        command: str,
        event: Any,
        mode: str | None = None,
        mode_label: str | None = None,
        failure_prefix: str = "❌ 执行失败",
    ) -> str:
        """执行 shell 命令并统一格式化结果。"""

        try:
            sandbox, result = await self.api_client.run_code(
                code=command,
                event=event,
                kernel="bash",
                mode=mode,
            )
        except Exception as exc:
            logger.error("执行失败: %s", exc)
            return f"{failure_prefix}: {str(exc)}"
        display_mode = mode_label or sandbox.mode
        return cast(str, self.formatter.format_result(result, display_mode, command))
