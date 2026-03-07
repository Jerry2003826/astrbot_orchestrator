"""`ExecutionManager` 的纯逻辑支持组件。"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Sequence

from ..sandbox import ExecResult, SandboxFile
from ..shared import quote_shell_path

DEFAULT_DANGEROUS_PATTERNS: tuple[str, ...] = (
    "rm -rf /",
    "mkfs",
    "dd if=",
    "> /dev/",
    "sudo rm",
    "chmod 777 /",
    "curl | sh",
    "wget | sh",
)


@dataclass(frozen=True, slots=True)
class ExecutionCommandPolicy:
    """封装执行命令的策略判断与构造。"""

    dangerous_patterns: tuple[str, ...] = DEFAULT_DANGEROUS_PATTERNS

    def is_dangerous(self, code: str) -> bool:
        """判断命令是否命中危险模式。"""

        lowered = code.lower()
        return any(pattern in lowered for pattern in self.dangerous_patterns)

    def build_web_server_command(self, project_path: str, port: int, framework: str) -> str:
        """生成启动 Web 服务的 shell 命令。"""

        quoted_path = quote_shell_path(project_path)
        normalized_framework = framework.lower()

        if normalized_framework == "flask":
            run_command = "python main.py"
        elif normalized_framework == "fastapi":
            run_command = f"uvicorn main:app --host 0.0.0.0 --port {port}"
        elif normalized_framework == "node":
            run_command = "node server.js"
        else:
            run_command = f"python -m http.server {port}"

        return f"cd {quoted_path} && nohup {run_command} > server.log 2>&1 &"


@dataclass(slots=True)
class ExecutionFormatter:
    """负责执行结果与文件信息的文本格式化。"""

    show_process: bool = True
    max_command_chars: int = 50
    max_output_chars: int = 2000
    max_error_chars: int = 1000
    mode_names: dict[str, str] = field(
        default_factory=lambda: {
            "shipyard": "🐳 Shipyard 沙盒（Docker 隔离）",
            "local": "💻 本地执行（无隔离）",
            "auto": "🔄 自动检测",
        }
    )

    def format_result(self, result: ExecResult, mode: str, command: str) -> str:
        """格式化执行结果。"""

        lines: list[str] = []

        if self.show_process:
            lines.extend(
                [
                    "🤖 **执行过程:**",
                    "  📝 解析命令...",
                    f"  🔧 使用环境: {mode}",
                    "  🚀 开始执行...",
                    "",
                ]
            )

        cmd_display = self._truncate(command, self.max_command_chars)
        lines.append(f"🖥️ **{mode.upper()} 执行结果**\n")
        lines.append(f"命令: `{cmd_display}`")
        lines.append(f"退出码: {result.exit_code}\n")

        if result.text:
            lines.append(
                f"**输出:**\n```\n{self._truncate(result.text, self.max_output_chars)}\n```"
            )

        if result.errors:
            lines.append(
                f"**错误:**\n```\n{self._truncate(result.errors, self.max_error_chars)}\n```"
            )

        if result.images:
            lines.append(f"📷 生成了 {len(result.images)} 张图片")

        lines.append("✅ 执行完成" if result.success else "❌ 命令执行失败")
        return "\n".join(lines)

    def format_mode_info(self, mode: str, in_sandbox: bool, cache_size: int) -> str:
        """格式化当前执行模式信息。"""

        sandbox_note = ""
        if in_sandbox:
            sandbox_note = "\n⚡ **已在 Shipyard 沙盒内运行，直接本地执行（无需嵌套沙盒）**\n"

        return (
            f"🖥️ **当前执行环境配置**\n\n"
            f"运行模式: {self.mode_names.get(mode, mode)}\n"
            f"在沙盒内: {'✅ 是' if in_sandbox else '❌ 否'}\n"
            f"缓存沙盒数: {cache_size}\n"
            f"{sandbox_note}\n"
            f"💡 支持的命令:\n"
            f"  `/exec <命令>` - 执行 Shell 命令\n"
            f"  `/exec python <代码>` - 执行 Python\n"
            f"  `/sandbox status` - 沙盒状态\n"
            f"  `/sandbox files [路径]` - 列出文件\n"
            f"  `/sandbox upload <路径>` - 上传文件\n"
            f"  `/sandbox install <包名>` - 安装包\n"
            f"  `/sandbox packages` - 已安装包\n"
            f"  `/sandbox restart` - 重启沙盒"
        )

    def format_written_file(self, sandbox_cwd: str, sandbox_file: SandboxFile) -> str:
        """格式化文件写入成功提示。"""

        absolute_path = os.path.join(sandbox_cwd, sandbox_file.path)
        return (
            f"✅ 文件已创建: `{sandbox_file.path}` ({sandbox_file.size_human})\n"
            f"📂 绝对路径: `{absolute_path}`"
        )

    def format_read_file(self, sandbox_file: SandboxFile) -> str:
        """格式化文件读取结果。"""

        if sandbox_file.content:
            text = sandbox_file.content.decode("utf-8", errors="replace")
            return f"📄 **{sandbox_file.path}** ({sandbox_file.size_human})\n\n```\n{text}\n```"
        return "❌ 文件内容为空"

    def format_file_list(self, dir_path: str, files: Sequence[SandboxFile]) -> str:
        """格式化目录文件列表。"""

        if not files:
            return f"📁 `{dir_path}` 目录为空"

        lines = [f"📁 **{dir_path}** ({len(files)} 个文件)\n"]
        for file_obj in files:
            lines.append(f"  • `{file_obj.path}` ({file_obj.size_human})")
        return "\n".join(lines)

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        """按上限截断文本。"""

        return text[:limit] + "..." if len(text) > limit else text
