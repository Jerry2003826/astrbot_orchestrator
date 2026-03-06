"""
执行环境管理工具 - 基于 CodeSandbox 抽象层

功能：
- 统一的代码执行接口（类似 CodeBox API）
- 支持 local / shipyard 模式自动切换
- 执行 Shell 命令和 Python 代码
- 文件上传/下载（支持二进制）
- 包管理（install / list_packages）
- 流式执行结果返回
- 会话变量查看
- 健康检查和自动修复
"""

import logging
import typing as t
from typing import Any, Dict, List

from ..sandbox import (
    CodeSandbox,
    ExecChunk,
    ExecResult,
    SandboxFile,
)
from .execution_facades import ExecutionAccessPolicy, LegacyExecutionFacade, SandboxApiClient
from .execution_support import ExecutionCommandPolicy, ExecutionFormatter
from .sandbox_runtime import SandboxRuntime

logger = logging.getLogger(__name__)


class ExecutionManager:
    """
    执行环境管理器

    基于 CodeSandbox 抽象层，提供类似 CodeBox API 的统一接口。
    自动根据 AstrBot 配置选择 local 或 shipyard 模式。
    """

    def __init__(self, context, config: Dict[str, Any] | None = None) -> None:
        self.context = context
        self.config = config or {}
        if "task_timeout" not in self.config:
            self.config["task_timeout"] = 120
        self.sandbox_runtime = SandboxRuntime(context=self.context, config=self.config)
        self.command_policy = ExecutionCommandPolicy()
        self.formatter = ExecutionFormatter(
            show_process=self.config.get("show_thinking_process", True)
        )
        self.access_policy = ExecutionAccessPolicy()
        self.api_client = SandboxApiClient(runtime=self.sandbox_runtime)
        self.legacy_facade = LegacyExecutionFacade(
            api_client=self.api_client,
            formatter=self.formatter,
            command_policy=self.command_policy,
            access_policy=self.access_policy,
        )

    async def astop(self) -> None:
        """停止执行器内部缓存的所有沙盒。"""

        await self.sandbox_runtime.astop()

    # ── 沙盒管理 ──────────────────────────────────────────

    async def get_sandbox(
        self,
        event=None,
        mode: str | None = None,
        session_id: str | None = None,
    ) -> CodeSandbox:
        """
        获取或创建沙盒实例

        Args:
            event: AstrBot 消息事件
            mode: 强制指定模式 (local / shipyard / auto)
            session_id: 会话 ID（用于缓存）

        Returns:
            CodeSandbox 实例
        """
        return await self.sandbox_runtime.get_sandbox(
            event=event,
            mode=mode,
            session_id=session_id,
        )

    def _detect_mode(self) -> str:
        """检测应使用的沙盒模式

        优先级：
        1. 如果已在 Shipyard 沙盒内 → local（避免嵌套沙盒）
        2. 根据 AstrBot 配置决定
        """
        return self.sandbox_runtime.detect_mode()

    # ── 代码执行（兼容旧接口）────────────────────────────

    async def execute(self, command: str, event) -> str:
        """
        执行命令（兼容旧接口）

        Args:
            command: Shell 命令
            event: 消息事件
        """
        return await self.legacy_facade.execute(command, event)

    async def execute_local(self, command: str, event) -> str:
        """强制本地执行"""
        return await self.legacy_facade.execute_local(command, event)

    async def execute_sandbox(self, command: str, event) -> str:
        """强制沙盒执行"""
        return await self.legacy_facade.execute_sandbox(command, event)

    async def execute_python(self, code: str, event, force_mode: str | None = None) -> str:
        """执行 Python 代码"""
        return await self.legacy_facade.execute_python(code, event, force_mode=force_mode)

    # ── CodeBox 风格的新接口 ──────────────────────────────

    async def exec_code(
        self,
        code: str,
        event,
        kernel: str = "ipython",
        stream: bool = False,
    ) -> t.Union[ExecResult, t.AsyncGenerator[ExecChunk, None]]:
        """
        执行代码（CodeBox 风格接口）

        Args:
            code: 代码内容
            event: 消息事件
            kernel: 内核类型 (ipython / bash)
            stream: 是否流式返回

        Returns:
            ExecResult 或 ExecChunk 异步生成器
        """
        return await self.api_client.exec_code(code=code, event=event, kernel=kernel, stream=stream)

    async def upload_file(
        self,
        remote_path: str,
        content: t.Union[bytes, str],
        event,
    ) -> SandboxFile:
        """
        上传文件到沙盒

        Args:
            remote_path: 目标路径
            content: 文件内容
            event: 消息事件

        Returns:
            SandboxFile 对象
        """
        _, sandbox_file = await self.api_client.upload_file(remote_path, content, event)
        return sandbox_file

    async def download_file(
        self,
        remote_path: str,
        event,
    ) -> SandboxFile:
        """
        从沙盒下载文件

        Args:
            remote_path: 文件路径
            event: 消息事件

        Returns:
            SandboxFile 对象（包含 content）
        """
        return await self.api_client.download_file(remote_path, event)

    async def list_sandbox_files(
        self,
        path: str = ".",
        event=None,
    ) -> List[SandboxFile]:
        """
        列出沙盒中的文件

        Args:
            path: 目录路径
            event: 消息事件

        Returns:
            SandboxFile 列表
        """
        return await self.api_client.list_sandbox_files(path, event)

    async def install_packages(
        self,
        packages: List[str],
        event,
    ) -> str:
        """
        在沙盒中安装 Python 包

        Args:
            packages: 包名列表
            event: 消息事件

        Returns:
            安装结果
        """
        return await self.api_client.install_packages(packages, event)

    async def list_packages(self, event) -> List[str]:
        """列出沙盒中已安装的包"""
        return await self.api_client.list_packages(event)

    async def show_variables(self, event) -> Dict[str, str]:
        """显示沙盒中的会话变量"""
        return await self.api_client.show_variables(event)

    async def healthcheck(self, event=None) -> str:
        """沙盒健康检查"""
        return await self.legacy_facade.healthcheck(event)

    async def restart_sandbox(self, event) -> str:
        """重启沙盒"""
        return await self.legacy_facade.restart_sandbox(event)

    async def download_from_url(
        self,
        url: str,
        file_path: str,
        event,
    ) -> SandboxFile:
        """
        从 URL 下载文件到沙盒

        Args:
            url: 文件 URL
            file_path: 沙盒中的保存路径
            event: 消息事件

        Returns:
            SandboxFile 对象
        """
        return await self.api_client.download_from_url(url, file_path, event)

    # ── 智能执行（兼容旧接口）────────────────────────────

    async def auto_execute(
        self,
        code: str,
        event,
        code_type: str = "shell",
        provider_id: str | None = None,
    ) -> str:
        """智能执行（兼容旧接口）"""
        del provider_id
        return await self.legacy_facade.auto_execute(code=code, event=event, code_type=code_type)

    # ── 文件操作（兼容旧接口）────────────────────────────

    async def write_file(self, file_path: str, content: str, event, skip_auth: bool = False) -> str:
        """
        写入文件（兼容旧接口）

        Args:
            file_path: 文件路径
            content: 文件内容
            event: 消息事件
            skip_auth: 是否跳过权限检查（内部 SubAgent 调用时为 True）
        """
        return await self.legacy_facade.write_file(
            file_path=file_path,
            content=content,
            event=event,
            skip_auth=skip_auth,
        )

    async def read_file(self, file_path: str, event) -> str:
        """读取文件（兼容旧接口）"""
        return await self.legacy_facade.read_file(file_path, event)

    async def list_files(self, dir_path: str, event) -> str:
        """列出文件（兼容旧接口）"""
        return await self.legacy_facade.list_files(dir_path, event)

    async def start_web_server(
        self,
        project_path: str,
        port: int,
        event,
        framework: str = "python",
    ) -> str:
        """启动 Web 服务器"""
        return await self.legacy_facade.start_web_server(
            project_path=project_path,
            port=port,
            event=event,
            framework=framework,
        )

    async def check_port(self, port: int, event) -> str:
        """检查端口是否被占用"""
        return await self.legacy_facade.check_port(port, event)

    # ── 格式化 ────────────────────────────────────────────

    def get_current_mode_info(self) -> str:
        """获取当前执行模式信息"""
        mode = self._detect_mode()
        in_sandbox = self.sandbox_runtime.is_inside_sandbox()
        return self.formatter.format_mode_info(
            mode=mode,
            in_sandbox=in_sandbox,
            cache_size=self.sandbox_runtime.cache_size,
        )

    def _format_result(
        self,
        result: ExecResult,
        mode: str,
        command: str,
    ) -> str:
        """格式化执行结果"""
        return self.formatter.format_result(result, mode, command)
