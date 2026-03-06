"""
ShipyardSandbox - 通过 AstrBot Shipyard/Docker 沙盒执行代码

利用 AstrBot 内置的 ComputerBooter（Shipyard Bay）来执行代码，
提供与 CodeBox API DockerBox 类似的隔离执行环境。

这是生产环境推荐的沙盒模式。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import shlex
import typing as t

from ..shared import ensure_within_base, quote_shell_path
from .base import CodeSandbox
from .types import ExecChunk, ExecResult, SandboxFile

logger = logging.getLogger(__name__)


class ShipyardSandbox(CodeSandbox):
    """
    Shipyard 沙盒实现

    通过 AstrBot 的 computer_client 获取 booter，
    使用 Shipyard Bay 提供的 Docker 容器执行代码。
    """

    def __init__(
        self,
        context=None,
        event=None,
        session_id: t.Optional[str] = None,
        cwd: str = "/workspace",
        timeout: float = 120.0,
    ) -> None:
        super().__init__(session_id=session_id, cwd=cwd, timeout=timeout)
        self._context = context
        self._event = event
        self._booter = None

    @property
    def mode(self) -> str:
        return "shipyard"

    async def _get_booter(self):
        """获取 AstrBot 的 Shipyard booter"""
        if self._booter is not None:
            return self._booter

        try:
            from astrbot.core.computer.computer_client import get_booter

            umo = self._event.unified_msg_origin if self._event else None
            self._booter = await get_booter(self._context, umo)
            return self._booter
        except ImportError as exc:
            logger.error("[ShipyardSandbox] 无法导入 computer_client")
            raise RuntimeError("AstrBot computer_client 不可用") from exc
        except Exception as e:
            logger.error("[ShipyardSandbox] 获取 booter 失败: %s", e)
            raise

    async def astart(self) -> None:
        """启动 Shipyard 沙盒"""
        await self._get_booter()
        # 确保工作目录存在
        await self._shell_exec(f"mkdir -p {quote_shell_path(self.cwd)}")
        self._started = True
        logger.info("[ShipyardSandbox] 已启动")

    async def astop(self) -> None:
        """停止 Shipyard 沙盒"""
        self._booter = None
        self._started = False
        logger.info("[ShipyardSandbox] 已停止")

    async def _shell_exec(
        self,
        command: str,
        timeout: t.Optional[float] = None,
    ) -> dict[str, t.Any]:
        """通过 booter 执行 shell 命令

        Args:
            command: 要执行的命令
            timeout: 超时时间（秒），None 则使用实例默认值
        """
        booter = await self._get_booter()
        exec_timeout = int(timeout or self.timeout)
        try:
            result = await booter.shell.exec(command, timeout=exec_timeout)
        except TypeError:
            # 兼容不支持 timeout 参数的旧版 booter
            result = await booter.shell.exec(command)
        if isinstance(result, str):
            try:
                return t.cast(dict[str, t.Any], json.loads(result))
            except (json.JSONDecodeError, TypeError):
                return {"stdout": result, "stderr": "", "exit_code": 0}
        return (
            t.cast(dict[str, t.Any], result)
            if isinstance(result, dict)
            else {"stdout": str(result), "stderr": "", "exit_code": 0}
        )

    # ── 代码执行 ──────────────────────────────────────────

    async def aexec(
        self,
        code: str,
        kernel: t.Literal["ipython", "bash"] = "ipython",
        timeout: t.Optional[float] = None,
        cwd: t.Optional[str] = None,
    ) -> ExecResult:
        """通过 Shipyard 执行代码"""
        timeout = timeout or self.timeout
        work_dir = cwd or self.cwd
        quoted_work_dir = quote_shell_path(work_dir)

        try:
            if kernel == "bash":
                command = f"cd {quoted_work_dir} && {code}"
            else:
                # Python 代码：写入临时文件执行
                # 转义单引号
                escaped = code.replace("'", "'\\''")
                command = f"cd {quoted_work_dir} && python3 -c '{escaped}'"

            result = await asyncio.wait_for(
                self._shell_exec(command, timeout=timeout),
                timeout=timeout + 5,  # 外层超时略大于内层，优先让内层超时返回有意义的错误
            )

            stdout = result.get("stdout", "") or result.get("output", "") or ""
            stderr = result.get("stderr", "") or result.get("error", "") or ""
            exit_code = result.get("exit_code", result.get("returncode", 0)) or 0

            return ExecResult(
                text=stdout.strip() if isinstance(stdout, str) else str(stdout),
                errors=stderr.strip() if isinstance(stderr, str) else str(stderr),
                exit_code=int(exit_code),
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
            logger.error("[ShipyardSandbox] 执行失败: %s", e, exc_info=True)
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
        """
        Shipyard 流式执行

        注意：Shipyard 的 shell.exec 不原生支持流式，
        这里通过分行输出模拟流式效果。
        """
        yield ExecChunk(type="status", content="开始执行...")

        result = await self.aexec(code, kernel=kernel, timeout=timeout, cwd=cwd)

        # 逐行输出 stdout
        if result.text:
            for line in result.text.splitlines():
                yield ExecChunk(type="stdout", content=line + "\n")

        # 输出 stderr
        if result.errors:
            for line in result.errors.splitlines():
                yield ExecChunk(type="stderr", content=line + "\n")

        # 输出图片
        for img in result.images:
            yield ExecChunk(type="image", content=img)

        yield ExecChunk(
            type="status",
            content=f"exit_code={result.exit_code}",
        )

    # ── 文件操作 ──────────────────────────────────────────

    async def aupload(
        self,
        remote_path: str,
        content: t.Union[bytes, str],
        timeout: t.Optional[float] = None,
    ) -> SandboxFile:
        """上传文件到 Shipyard 沙盒"""
        full_path = ensure_within_base(self.cwd, remote_path)
        quoted_path = quote_shell_path(full_path)

        # 确保目录存在
        dir_path = full_path.parent
        await self._shell_exec(f"mkdir -p {quote_shell_path(dir_path)}")

        payload = content.encode("utf-8") if isinstance(content, str) else content
        b64 = base64.b64encode(payload).decode("ascii")
        await self._shell_exec(f"printf %s {shlex.quote(b64)} | base64 -d > {quoted_path}")

        # 获取文件大小
        size_result = await self._shell_exec(f"stat -c %s {quoted_path} 2>/dev/null || echo -1")
        try:
            size = int(size_result.get("stdout", "-1").strip())
        except (ValueError, AttributeError):
            size = -1

        logger.info("[ShipyardSandbox] 文件已上传: %s", remote_path)
        return SandboxFile(path=remote_path, size=size)

    async def adownload(
        self,
        remote_path: str,
        timeout: t.Optional[float] = None,
    ) -> SandboxFile:
        """从 Shipyard 沙盒下载文件"""
        full_path = ensure_within_base(self.cwd, remote_path)
        quoted_path = quote_shell_path(full_path)

        # 检查文件是否存在
        check = await self._shell_exec(f"test -f {quoted_path} && echo exists || echo missing")
        if "missing" in check.get("stdout", ""):
            raise FileNotFoundError(f"文件不存在: {remote_path}")

        # 使用 base64 编码读取（支持二进制）
        result = await self._shell_exec(f"base64 {quoted_path}")
        b64_content = result.get("stdout", "").strip()

        try:
            content = base64.b64decode(b64_content)
        except Exception:
            # 回退到文本读取
            text_result = await self._shell_exec(f"cat {quoted_path}")
            content = text_result.get("stdout", "").encode("utf-8")

        return SandboxFile(
            path=remote_path,
            size=len(content),
            content=content,
        )

    async def alist_files(
        self,
        path: str = ".",
    ) -> t.List[SandboxFile]:
        """列出 Shipyard 沙盒中的文件"""
        target_dir = self.cwd if path == "." else ensure_within_base(self.cwd, path)
        quoted_dir = quote_shell_path(target_dir)

        result = await self._shell_exec(
            f"find {quoted_dir} -maxdepth 1 -type f "
            f"-exec du -h {{}} + 2>/dev/null | awk '{{print $2, $1}}' | sort"
        )

        files = []
        stdout = result.get("stdout", "")
        if stdout:
            for line in stdout.strip().splitlines():
                parts = line.split(None, 1)
                if len(parts) == 2:
                    file_path, size_str = parts
                    rel_path = file_path.replace(self.cwd + "/", "").replace(self.cwd, "")
                    if rel_path:
                        files.append(
                            SandboxFile(
                                path=rel_path,
                                size=self._parse_size(size_str),
                            )
                        )
        return files

    @staticmethod
    def _parse_size(size_str: str) -> int:
        """解析人类可读的文件大小为字节数"""
        units = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
        try:
            number = float(size_str[:-1])
            unit = size_str[-1].upper()
            return int(number * units.get(unit, 1))
        except (ValueError, IndexError):
            return -1

    # ── 包管理 ────────────────────────────────────────────

    async def ainstall(self, *packages: str) -> str:
        """在 Shipyard 沙盒中安装 Python 包"""
        pkg_str = " ".join(packages)
        result = await self.aexec(f"pip install {pkg_str}", kernel="bash")
        if result.success:
            return f"{pkg_str} installed successfully"
        return f"安装失败: {result.errors}"

    async def alist_packages(self) -> t.List[str]:
        """列出 Shipyard 沙盒中已安装的 Python 包"""
        result = await self.aexec(
            "pip list --format=columns 2>/dev/null | tail -n +3 | awk '{print $1}'",
            kernel="bash",
        )
        return result.text.strip().splitlines() if result.text else []

    # ── 会话管理 ──────────────────────────────────────────

    async def ashow_variables(self) -> t.Dict[str, str]:
        """Shipyard 不支持 IPython 会话变量，返回空"""
        return {}

    async def arestart(self) -> None:
        """重启 Shipyard 沙盒（重新获取 booter）"""
        self._booter = None
        await self._get_booter()
        logger.info("[ShipyardSandbox] 已重启")
