"""
CodeSandbox 类型定义

参考 CodeBox API 的 ExecResult / ExecChunk / RemoteFile，
为 AstrBot 插件提供结构化的执行结果和文件对象。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional, List, Literal


@dataclass
class ExecResult:
    """
    代码执行结果

    类似 CodeBox API 的 ExecResult，包含标准输出、错误和图片。

    Attributes:
        text: 标准输出文本
        errors: 错误信息
        images: 生成的图片（base64 编码列表）
        exit_code: 退出码（0 表示成功）
        kernel: 使用的内核类型
    """

    text: str = ""
    errors: str = ""
    images: List[str] = field(default_factory=list)
    exit_code: int = 0
    kernel: str = "ipython"

    @property
    def success(self) -> bool:
        """执行是否成功"""
        return self.exit_code == 0 and not self.errors

    def __str__(self) -> str:
        parts = []
        if self.text:
            parts.append(self.text)
        if self.errors:
            parts.append(f"[ERROR] {self.errors}")
        if self.images:
            parts.append(f"[{len(self.images)} image(s)]")
        return "\n".join(parts) if parts else "(no output)"


@dataclass
class ExecChunk:
    """
    流式执行的单个数据块

    类似 CodeBox API 的 ExecChunk，用于流式返回执行结果。

    Attributes:
        type: 数据块类型 (stdout / stderr / image / status)
        content: 数据块内容
    """

    type: Literal["stdout", "stderr", "image", "status"] = "stdout"
    content: str = ""

    def __str__(self) -> str:
        return self.content


@dataclass
class SandboxFile:
    """
    沙盒中的文件对象

    类似 CodeBox API 的 RemoteFile，表示沙盒文件系统中的一个文件。

    Attributes:
        path: 文件路径（相对于沙盒工作目录）
        size: 文件大小（字节），-1 表示未知
        content: 文件内容（可选，仅在下载时填充）
    """

    path: str = ""
    size: int = -1
    content: Optional[bytes] = None

    @property
    def name(self) -> str:
        """文件名"""
        return os.path.basename(self.path)

    @property
    def extension(self) -> str:
        """文件扩展名"""
        _, ext = os.path.splitext(self.path)
        return ext

    @property
    def size_human(self) -> str:
        """人类可读的文件大小"""
        if self.size < 0:
            return "unknown"
        units = ["B", "KB", "MB", "GB", "TB"]
        size = float(self.size)
        for unit in units:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

    def __str__(self) -> str:
        return f"{self.path} ({self.size_human})"


@dataclass
class SandboxStatus:
    """
    沙盒状态信息

    Attributes:
        healthy: 是否健康
        mode: 运行模式 (local / docker / shipyard)
        session_id: 会话 ID
        uptime: 运行时间（秒）
        packages: 已安装的包列表
        variables: 当前会话变量
    """

    healthy: bool = False
    mode: str = "unknown"
    session_id: str = ""
    uptime: float = 0.0
    packages: List[str] = field(default_factory=list)
    variables: dict = field(default_factory=dict)

    def __str__(self) -> str:
        status = "✅ healthy" if self.healthy else "❌ unhealthy"
        return f"Sandbox({self.mode}) {status} session={self.session_id}"
