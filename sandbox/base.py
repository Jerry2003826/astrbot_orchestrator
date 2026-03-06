"""
CodeSandbox 抽象基类

参考 CodeBox API 的设计，提供统一的沙盒接口。
所有具体实现（LocalSandbox / DockerSandbox / ShipyardSandbox）
都继承此基类。

核心方法：
- exec / aexec: 执行代码
- stream_exec / astream_exec: 流式执行代码
- upload / aupload: 上传文件
- download / adownload: 下载文件
- install / ainstall: 安装 Python 包
- list_files / alist_files: 列出文件
- list_packages / alist_packages: 列出已安装包
- show_variables / ashow_variables: 显示会话变量
- healthcheck / ahealthcheck: 健康检查
- restart / arestart: 重启内核
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import json
import logging
import typing as t

from ..shared import resolve_path_within_base
from .types import ExecChunk, ExecResult, SandboxFile, SandboxStatus

logger = logging.getLogger(__name__)


class CodeSandbox(ABC):
    """
    统一沙盒抽象基类

    类似 CodeBox API 的 CodeBox 类，提供代码执行、文件管理、
    包管理等统一接口。

    Usage::

        sandbox = LocalSandbox()
        result = await sandbox.aexec("print('hello')")
        print(result.text)  # hello
    """

    def __init__(
        self,
        session_id: t.Optional[str] = None,
        cwd: str = "/workspace",
        timeout: float = 30.0,
    ) -> None:
        self.session_id = session_id or ""
        self.cwd = cwd
        self.timeout = timeout
        self._started = False

    @property
    @abstractmethod
    def mode(self) -> str:
        """沙盒模式标识 (local / docker / shipyard)"""
        ...

    # ── 生命周期 ──────────────────────────────────────────

    async def astart(self) -> None:
        """启动沙盒（异步）"""
        self._started = True

    async def astop(self) -> None:
        """停止沙盒（异步）"""
        self._started = False

    async def __aenter__(self) -> "CodeSandbox":
        await self.astart()
        return self

    async def __aexit__(self, *args) -> None:
        await self.astop()

    # ── 代码执行 ──────────────────────────────────────────

    @abstractmethod
    async def aexec(
        self,
        code: str,
        kernel: t.Literal["ipython", "bash"] = "ipython",
        timeout: t.Optional[float] = None,
        cwd: t.Optional[str] = None,
    ) -> ExecResult:
        """
        异步执行代码

        Args:
            code: 要执行的代码
            kernel: 内核类型 (ipython 或 bash)
            timeout: 超时时间（秒）
            cwd: 工作目录

        Returns:
            ExecResult 执行结果
        """
        ...

    @abstractmethod
    async def astream_exec(
        self,
        code: str,
        kernel: t.Literal["ipython", "bash"] = "ipython",
        timeout: t.Optional[float] = None,
        cwd: t.Optional[str] = None,
    ) -> t.AsyncGenerator[ExecChunk, None]:
        """
        异步流式执行代码

        逐块返回执行结果，适合长时间运行的任务。

        Args:
            code: 要执行的代码
            kernel: 内核类型
            timeout: 超时时间
            cwd: 工作目录

        Yields:
            ExecChunk 执行数据块
        """
        ...
        # 让 Python 识别为 async generator
        yield ExecChunk()  # type: ignore  # pragma: no cover

    # ── 文件操作 ──────────────────────────────────────────

    @abstractmethod
    async def aupload(
        self,
        remote_path: str,
        content: t.Union[bytes, str],
        timeout: t.Optional[float] = None,
    ) -> SandboxFile:
        """
        上传文件到沙盒

        Args:
            remote_path: 沙盒中的目标路径
            content: 文件内容（bytes 或 str）
            timeout: 超时时间

        Returns:
            SandboxFile 上传后的文件对象
        """
        ...

    @abstractmethod
    async def adownload(
        self,
        remote_path: str,
        timeout: t.Optional[float] = None,
    ) -> SandboxFile:
        """
        从沙盒下载文件

        Args:
            remote_path: 沙盒中的文件路径
            timeout: 超时时间

        Returns:
            SandboxFile 包含内容的文件对象
        """
        ...

    @abstractmethod
    async def alist_files(
        self,
        path: str = ".",
    ) -> t.List[SandboxFile]:
        """
        列出沙盒中的文件

        Args:
            path: 目录路径（相对于工作目录）

        Returns:
            SandboxFile 列表
        """
        ...

    async def afile_from_url(
        self,
        url: str,
        file_path: str,
    ) -> SandboxFile:
        """
        从 URL 下载文件到沙盒

        Args:
            url: 文件 URL
            file_path: 沙盒中的保存路径

        Returns:
            SandboxFile 下载后的文件对象
        """
        safe_url = json.dumps(url)
        target_path = resolve_path_within_base(self.cwd, file_path)
        safe_file_path = json.dumps(str(target_path))
        code = (
            "import httpx\n"
            "async with httpx.AsyncClient() as client:\n"
            f"    async with client.stream('GET', {safe_url}) as response:\n"
            "        response.raise_for_status()\n"
            f"        with open({safe_file_path}, 'wb') as f:\n"
            "            async for chunk in response.aiter_bytes():\n"
            "                f.write(chunk)\n"
        )
        await self.aexec(code)
        return await self.adownload(file_path)

    # ── 包管理 ────────────────────────────────────────────

    async def ainstall(self, *packages: str) -> str:
        """
        在沙盒中安装 Python 包

        Args:
            packages: 要安装的包名列表

        Returns:
            安装结果文本
        """
        pkg_str = " ".join(packages)
        result = await self.aexec(
            f"pip install {pkg_str}",
            kernel="bash",
        )
        return f"{pkg_str} installed successfully" if result.success else result.errors

    async def alist_packages(self) -> t.List[str]:
        """
        列出沙盒中已安装的 Python 包

        Returns:
            包名列表
        """
        result = await self.aexec(
            "pip list --format=columns | tail -n +3 | cut -d ' ' -f 1",
            kernel="bash",
        )
        return result.text.strip().splitlines() if result.text else []

    # ── 会话管理 ──────────────────────────────────────────

    async def ashow_variables(self) -> t.Dict[str, str]:
        """
        显示当前 IPython 会话中的变量

        Returns:
            变量名 -> 值的字典
        """
        result = await self.aexec("%who")
        if not result.text.strip():
            return {}
        var_names = result.text.strip().split()
        variables = {}
        for name in var_names:
            val_result = await self.aexec(f"print({name}, end='')")
            variables[name] = val_result.text
        return variables

    async def arestart(self) -> None:
        """重启执行内核"""
        await self.aexec("%restart", kernel="ipython")

    # ── 健康检查 ──────────────────────────────────────────

    async def ahealthcheck(self) -> t.Literal["healthy", "error"]:
        """
        检查沙盒健康状态

        Returns:
            "healthy" 或 "error"
        """
        try:
            result = await self.aexec("echo ok", kernel="bash")
            return "healthy" if "ok" in result.text else "error"
        except Exception:
            return "error"

    async def astatus(self) -> SandboxStatus:
        """
        获取沙盒详细状态

        Returns:
            SandboxStatus 状态对象
        """
        health = await self.ahealthcheck()
        packages = []
        variables = {}
        try:
            packages = await self.alist_packages()
        except Exception as exc:
            logger.debug("列出沙盒包失败，使用空列表回退: %s", exc)
        try:
            variables = await self.ashow_variables()
        except Exception as exc:
            logger.debug("读取沙盒变量失败，使用空映射回退: %s", exc)
        return SandboxStatus(
            healthy=(health == "healthy"),
            mode=self.mode,
            session_id=self.session_id,
            packages=packages,
            variables=variables,
        )

    # ── 保活 ──────────────────────────────────────────────

    async def akeep_alive(self, minutes: int = 15) -> None:
        """
        保持沙盒实例存活

        Args:
            minutes: 保活时间（分钟）
        """
        import asyncio

        for _ in range(minutes):
            await self.ahealthcheck()
            await asyncio.sleep(60)
