"""
LocalSandbox - 本地代码执行实现

在 AstrBot 进程内通过 subprocess 执行代码。
支持 bash 和 python（ipython）两种内核。

注意：LocalSandbox 直接在宿主机上执行，没有隔离。
生产环境建议使用 DockerSandbox 或 ShipyardSandbox。
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
import re
import tempfile
import typing as t

from ..shared import UnsafePathError, resolve_path_within_base
from .base import CodeSandbox
from .types import ExecChunk, ExecResult, SandboxFile

logger = logging.getLogger(__name__)

# 默认 cwd：优先使用 ``/workspace``，若当前进程无权限则退到用户级别的
# 用户数据目录，避免代码生成器在非 root 运行时直接崩溃。
_DEFAULT_CWD_SENTINEL = "/workspace"


def _resolve_default_cwd() -> str:
    """选择一个当前进程可写的默认工作目录。"""

    env_cwd = os.environ.get("ASTRBOT_LOCAL_SANDBOX_CWD")
    candidates = []
    if env_cwd:
        candidates.append(env_cwd)
    candidates.extend(
        [
            _DEFAULT_CWD_SENTINEL,
            os.path.expanduser("~/.astrbot_local_sandbox"),
            os.path.join(tempfile.gettempdir(), "astrbot_local_sandbox"),
        ]
    )
    for path in candidates:
        try:
            os.makedirs(path, exist_ok=True)
        except (PermissionError, OSError) as exc:
            logger.debug("LocalSandbox 候选 cwd %s 不可用: %s", path, exc)
            continue
        # 再确认确实可写
        if os.access(path, os.W_OK):
            return path
    # 运行到这里说明连 tempdir 都无法使用，回退到 tempdir 自身
    return tempfile.gettempdir()


# 匹配 matplotlib 等生成的图片标签
IMAGE_PATTERN = re.compile(r"<image>(.*?)</image>", re.DOTALL)


class LocalSandbox(CodeSandbox):
    """
    本地沙盒实现

    通过 asyncio.subprocess 在本地执行代码。
    IPython 内核使用 python3 -c 执行。
    Bash 内核使用 /bin/bash -c 执行。
    """

    def __init__(
        self,
        session_id: t.Optional[str] = None,
        cwd: t.Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        """初始化本地沙盒。

        Args:
            cwd: 工作目录。``None`` 时自动选择可写目录，默认
                先试 ``/workspace``，失败时依次退到 ``~/.astrbot_local_sandbox``
                和 系统临时目录，避免在非 root 下因不可写而出错。
                可通过环境变量 ``ASTRBOT_LOCAL_SANDBOX_CWD`` 覆写。
        """

        resolved_cwd = cwd if cwd else _resolve_default_cwd()
        super().__init__(session_id=session_id, cwd=resolved_cwd, timeout=timeout)
        # 即便用户显式传入，也尽量创建但容忍权限异常，避免构造时立即崩溃。
        try:
            os.makedirs(self.cwd, exist_ok=True)
        except (PermissionError, OSError) as exc:
            logger.warning("LocalSandbox 创建 cwd=%s 失败: %s", self.cwd, exc)

    @property
    def mode(self) -> str:
        return "local"

    async def astart(self) -> None:
        """启动本地沙盒"""
        try:
            os.makedirs(self.cwd, exist_ok=True)
        except (PermissionError, OSError) as exc:
            logger.warning("[LocalSandbox] 创建 cwd=%s 失败: %s", self.cwd, exc)
        self._started = True
        logger.info("[LocalSandbox] 已启动, cwd=%s", self.cwd)

    async def astop(self) -> None:
        """停止本地沙盒"""
        self._started = False
        logger.info("[LocalSandbox] 已停止")

    # ── 代码执行 ──────────────────────────────────────────

    async def aexec(
        self,
        code: str,
        kernel: t.Literal["ipython", "bash"] = "ipython",
        timeout: t.Optional[float] = None,
        cwd: t.Optional[str] = None,
    ) -> ExecResult:
        """本地执行代码"""
        timeout = timeout or self.timeout
        work_dir = cwd or self.cwd

        if kernel == "bash":
            cmd = ["bash", "-c", code]
        else:
            # ipython 模式：写入临时文件执行
            cmd = ["python3", "-c", code]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)

            stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
            stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
            exit_code = proc.returncode or 0

            # 提取图片（如果有 matplotlib 等输出）
            images = []
            for match in IMAGE_PATTERN.finditer(stdout):
                images.append(match.group(1))
            # 清理图片标签
            stdout = IMAGE_PATTERN.sub("", stdout).strip()

            return ExecResult(
                text=stdout,
                errors=stderr,
                images=images,
                exit_code=exit_code,
                kernel=kernel,
            )

        except asyncio.TimeoutError:
            return ExecResult(
                text="",
                errors=f"执行超时（{timeout}秒）",
                exit_code=-1,
                kernel=kernel,
            )
        except Exception as e:
            logger.error("[LocalSandbox] 执行失败: %s", e, exc_info=True)
            return ExecResult(
                text="",
                errors=str(e),
                exit_code=-1,
                kernel=kernel,
            )

    async def astream_exec(
        self,
        code: str,
        kernel: t.Literal["ipython", "bash"] = "ipython",
        timeout: t.Optional[float] = None,
        cwd: t.Optional[str] = None,
    ) -> t.AsyncGenerator[ExecChunk, None]:
        """本地流式执行代码"""
        timeout = timeout or self.timeout
        work_dir = cwd or self.cwd

        if kernel == "bash":
            cmd = ["bash", "-c", code]
        else:
            cmd = ["python3", "-c", code]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
            )

            async def read_stream(
                stream: asyncio.StreamReader,
                chunk_type: t.Literal["stdout", "stderr"],
            ) -> t.AsyncGenerator[ExecChunk, None]:
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace")
                    yield ExecChunk(type=chunk_type, content=text)

            # 交替读取 stdout 和 stderr
            if proc.stdout:
                async for chunk in read_stream(proc.stdout, "stdout"):
                    yield chunk

            if proc.stderr:
                async for chunk in read_stream(proc.stderr, "stderr"):
                    yield chunk

            await proc.wait()
            yield ExecChunk(
                type="status",
                content=f"exit_code={proc.returncode}",
            )

        except asyncio.TimeoutError:
            yield ExecChunk(type="stderr", content=f"执行超时（{timeout}秒）")
        except Exception as e:
            yield ExecChunk(type="stderr", content=str(e))

    # ── 文件操作 ──────────────────────────────────────────

    async def aupload(
        self,
        remote_path: str,
        content: t.Union[bytes, str],
        timeout: t.Optional[float] = None,
    ) -> SandboxFile:
        """上传文件到本地工作目录"""
        full_path = resolve_path_within_base(self.cwd, remote_path)
        dir_path = full_path.parent
        os.makedirs(dir_path, exist_ok=True)

        if isinstance(content, str):
            content = content.encode("utf-8")

        with open(full_path, "wb") as f:
            f.write(content)

        size = os.path.getsize(full_path)
        logger.info("[LocalSandbox] 文件已上传: %s (%d bytes)", remote_path, size)

        return SandboxFile(path=remote_path, size=size)

    async def adownload(
        self,
        remote_path: str,
        timeout: t.Optional[float] = None,
    ) -> SandboxFile:
        """从本地工作目录下载文件"""
        full_path = resolve_path_within_base(self.cwd, remote_path)

        if not os.path.exists(full_path):
            raise FileNotFoundError(f"文件不存在: {remote_path}")

        with open(full_path, "rb") as f:
            content = f.read()

        return SandboxFile(
            path=remote_path,
            size=len(content),
            content=content,
        )

    async def alist_files(
        self,
        path: str = ".",
    ) -> t.List[SandboxFile]:
        """列出本地工作目录中的文件"""
        try:
            target_dir = Path(self.cwd) if path == "." else resolve_path_within_base(self.cwd, path)
        except UnsafePathError:
            return []

        if not os.path.isdir(target_dir):
            return []

        files = []
        for entry in os.scandir(target_dir):
            if entry.is_file():
                rel_path = os.path.relpath(entry.path, self.cwd)
                files.append(
                    SandboxFile(
                        path=rel_path,
                        size=entry.stat().st_size,
                    )
                )
        return sorted(files, key=lambda f: f.path)

    # ── 包管理 ────────────────────────────────────────────

    async def ainstall(self, *packages: str) -> str:
        """在本地安装 Python 包"""
        pkg_str = " ".join(packages)
        result = await self.aexec(f"pip install {pkg_str}", kernel="bash")
        if result.success:
            return f"{pkg_str} installed successfully"
        return f"安装失败: {result.errors}"

    async def alist_packages(self) -> t.List[str]:
        """列出本地已安装的 Python 包"""
        result = await self.aexec(
            "pip list --format=columns 2>/dev/null | tail -n +3 | awk '{print $1}'",
            kernel="bash",
        )
        return result.text.strip().splitlines() if result.text else []

    async def arestart(self) -> None:
        """重启本地沙盒。

        ``LocalSandbox`` 每次通过 ``python3 -c`` 启动新子进程，不存在 IPython
        内核的 magic 命令系统。父类的 ``%restart`` 实现在 ``python3 -c`` 运行
        时会抛出语法错误，这里重写为幂等的 start/stop 循环。
        """

        await self.astop()
        await self.astart()
