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
import os
import asyncio
import typing as t
from typing import Dict, Any, Optional, List

from ..sandbox import CodeSandbox, ExecResult, ExecChunk, SandboxFile, create_sandbox, is_inside_shipyard_sandbox

logger = logging.getLogger(__name__)


class ExecutionManager:
    """
    执行环境管理器

    基于 CodeSandbox 抽象层，提供类似 CodeBox API 的统一接口。
    自动根据 AstrBot 配置选择 local 或 shipyard 模式。
    """

    def __init__(self, context, config: Dict = None):
        self.context = context
        self.config = config or {}
        self._env_fixer = None
        self._sandbox_cache: Dict[str, CodeSandbox] = {}
        # 默认超时提升到 120 秒，避免复杂任务超时
        if "task_timeout" not in self.config:
            self.config["task_timeout"] = 120

    def _get_env_fixer(self):
        if self._env_fixer is not None:
            return self._env_fixer
        try:
            from .env_fixer import EnvironmentFixer
            self._env_fixer = EnvironmentFixer()
        except Exception as e:
            logger.warning("无法加载环境修复器: %s", e)
            self._env_fixer = None
        return self._env_fixer

    async def _try_auto_fix(self, error_msg: str) -> str:
        fixer = self._get_env_fixer()
        if not fixer:
            return ""
        try:
            fixed, msg = await fixer.check_and_fix_environment(error_msg)
            return msg if fixed else ""
        except Exception as e:
            logger.warning("环境自动修复失败: %s", e)
            return ""

    # ── 沙盒管理 ──────────────────────────────────────────

    async def get_sandbox(
        self,
        event=None,
        mode: t.Optional[str] = None,
        session_id: t.Optional[str] = None,
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
        # 确定模式
        if mode is None:
            mode = self._detect_mode()

        # 缓存键
        cache_key = f"{mode}:{session_id or 'default'}"

        if cache_key in self._sandbox_cache:
            sandbox = self._sandbox_cache[cache_key]
            # 检查是否仍然可用
            try:
                health = await sandbox.ahealthcheck()
                if health == "healthy":
                    return sandbox
            except Exception:
                pass
            # 不可用，移除缓存
            del self._sandbox_cache[cache_key]

        # 创建新沙盒（带重试）
        max_retries = self.config.get("sandbox_create_retries", 2)
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                sandbox = create_sandbox(
                    mode=mode,
                    context=self.context,
                    event=event,
                    session_id=session_id,
                    cwd="/workspace",
                    timeout=self.config.get("task_timeout", 120),
                )
                await sandbox.astart()
                self._sandbox_cache[cache_key] = sandbox
                if attempt > 0:
                    logger.info("沙盒创建成功（第 %d 次重试）", attempt)
                return sandbox
            except Exception as e:
                last_error = e
                error_msg = str(e)
                logger.error("创建沙盒失败 (尝试 %d/%d): %s", attempt + 1, max_retries + 1, error_msg)

                # DNS 解析失败或连接错误时，等待后重试
                if attempt < max_retries and any(
                    keyword in error_msg.lower()
                    for keyword in ["name or service not known", "connection refused", "dns", "cannot connect"]
                ):
                    wait_time = (attempt + 1) * 3  # 3秒, 6秒 递增等待
                    logger.info("网络错误，等待 %d 秒后重试...", wait_time)
                    await asyncio.sleep(wait_time)
                    continue

                # 尝试自动修复
                if self.config.get("auto_fix_sandbox", True):
                    fix_msg = await self._try_auto_fix(error_msg)
                    if fix_msg:
                        logger.info("环境修复结果: %s", fix_msg)
                        # 修复后重试
                        try:
                            sandbox = create_sandbox(
                                mode=mode,
                                context=self.context,
                                event=event,
                                session_id=session_id,
                                cwd="/workspace",
                                timeout=self.config.get("task_timeout", 120),
                            )
                            await sandbox.astart()
                            self._sandbox_cache[cache_key] = sandbox
                            return sandbox
                        except Exception as retry_err:
                            logger.error("修复后仍无法创建沙盒: %s", retry_err)
                            last_error = retry_err

                break  # 非网络错误不重试

        # 回退到 local
        if mode != "local":
            logger.warning("回退到 local 模式 (原因: %s)", last_error)
            try:
                sandbox = create_sandbox(mode="local", timeout=self.config.get("task_timeout", 120))
                await sandbox.astart()
                self._sandbox_cache[f"local:{session_id or 'default'}"] = sandbox
                return sandbox
            except Exception as local_err:
                logger.error("local 模式也创建失败: %s", local_err)
                raise last_error from local_err

        raise last_error

    def _detect_mode(self) -> str:
        """检测应使用的沙盒模式
        
        优先级：
        1. 如果已在 Shipyard 沙盒内 → local（避免嵌套沙盒）
        2. 根据 AstrBot 配置决定
        """
        # 🔑 如果已在沙盒内，直接使用 local
        if is_inside_shipyard_sandbox():
            logger.info("[ExecutionManager] 已在 Shipyard 沙盒内，使用 local 模式")
            return "local"

        try:
            astrbot_config = self.context.get_config()
            computer_use = astrbot_config.get("computer_use", {})
            run_mode = computer_use.get("run_mode", "sandbox")

            if run_mode == "none":
                return "local"
            elif run_mode == "local":
                return "local"
            else:
                return "shipyard"
        except Exception:
            return "auto"

    # ── 代码执行（兼容旧接口）────────────────────────────

    async def execute(self, command: str, event) -> str:
        """
        执行命令（兼容旧接口）

        Args:
            command: Shell 命令
            event: 消息事件
        """
        if event.role != "admin":
            return "❌ 只有管理员可以执行命令"

        try:
            sandbox = await self.get_sandbox(event=event)
            result = await sandbox.aexec(command, kernel="bash")
            return self._format_result(result, sandbox.mode, command)
        except Exception as e:
            logger.error("执行失败: %s", e)
            return f"❌ 执行失败: {str(e)}"

    async def execute_local(self, command: str, event) -> str:
        """强制本地执行"""
        if event.role != "admin":
            return "❌ 只有管理员可以执行本地命令"

        try:
            sandbox = await self.get_sandbox(event=event, mode="local")
            result = await sandbox.aexec(command, kernel="bash")
            return self._format_result(result, "local", command)
        except Exception as e:
            return f"❌ 执行失败: {str(e)}"

    async def execute_sandbox(self, command: str, event) -> str:
        """强制沙盒执行"""
        if event.role != "admin":
            return "❌ 只有管理员可以执行命令"

        try:
            sandbox = await self.get_sandbox(event=event, mode="shipyard")
            result = await sandbox.aexec(command, kernel="bash")
            return self._format_result(result, "shipyard", command)
        except Exception as e:
            return f"❌ 沙盒执行失败: {str(e)}"

    async def execute_python(self, code: str, event, force_mode: str = None) -> str:
        """执行 Python 代码"""
        if event.role != "admin":
            return "❌ 只有管理员可以执行代码"

        try:
            mode = force_mode or None
            sandbox = await self.get_sandbox(event=event, mode=mode)
            result = await sandbox.aexec(code, kernel="ipython")
            return self._format_result(result, sandbox.mode, f"python: {code[:50]}...")
        except Exception as e:
            return f"❌ 执行失败: {str(e)}"

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
        sandbox = await self.get_sandbox(event=event)

        if stream:
            return sandbox.astream_exec(code, kernel=kernel)
        else:
            return await sandbox.aexec(code, kernel=kernel)

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
        sandbox = await self.get_sandbox(event=event)
        return await sandbox.aupload(remote_path, content)

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
        sandbox = await self.get_sandbox(event=event)
        return await sandbox.adownload(remote_path)

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
        sandbox = await self.get_sandbox(event=event)
        return await sandbox.alist_files(path)

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
        sandbox = await self.get_sandbox(event=event)
        return await sandbox.ainstall(*packages)

    async def list_packages(self, event) -> List[str]:
        """列出沙盒中已安装的包"""
        sandbox = await self.get_sandbox(event=event)
        return await sandbox.alist_packages()

    async def show_variables(self, event) -> Dict[str, str]:
        """显示沙盒中的会话变量"""
        sandbox = await self.get_sandbox(event=event)
        return await sandbox.ashow_variables()

    async def healthcheck(self, event=None) -> str:
        """沙盒健康检查"""
        try:
            sandbox = await self.get_sandbox(event=event)
            health = await sandbox.ahealthcheck()
            return f"✅ 沙盒状态: {health} (模式: {sandbox.mode})"
        except Exception as e:
            return f"❌ 沙盒不可用: {str(e)}"

    async def restart_sandbox(self, event) -> str:
        """重启沙盒"""
        try:
            sandbox = await self.get_sandbox(event=event)
            await sandbox.arestart()
            return f"✅ 沙盒已重启 (模式: {sandbox.mode})"
        except Exception as e:
            return f"❌ 重启失败: {str(e)}"

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
        sandbox = await self.get_sandbox(event=event)
        return await sandbox.afile_from_url(url, file_path)

    # ── 智能执行（兼容旧接口）────────────────────────────

    async def auto_execute(
        self,
        code: str,
        event,
        code_type: str = "shell",
        provider_id: str = None,
    ) -> str:
        """智能执行（兼容旧接口）"""
        dangerous_patterns = [
            "rm -rf /", "mkfs", "dd if=", "> /dev/",
            "sudo rm", "chmod 777 /", "curl | sh",
            "wget | sh"
        ]

        is_dangerous = any(p in code.lower() for p in dangerous_patterns)
        warning = ""

        if is_dangerous:
            warning = "⚠️ **警告**: 检测到潜在危险操作\n\n"

        kernel = "ipython" if code_type == "python" else "bash"

        try:
            sandbox = await self.get_sandbox(event=event)
            result = await sandbox.aexec(code, kernel=kernel)
            return warning + self._format_result(result, sandbox.mode, code)
        except Exception as e:
            return warning + f"❌ 执行失败: {str(e)}"

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
        if not skip_auth and hasattr(event, 'role') and event.role != "admin":
            return "❌ 只有管理员可以写入文件"

        try:
            sandbox = await self.get_sandbox(event=event)
            sf = await sandbox.aupload(file_path, content)
            # 构建绝对路径，方便用户定位和下载
            absolute_path = os.path.join(sandbox.cwd, sf.path)
            logger.info("✅ 文件写入成功: %s (%s), 绝对路径: %s", sf.path, sf.size_human, absolute_path)
            return (
                f"✅ 文件已创建: `{sf.path}` ({sf.size_human})\n"
                f"📂 绝对路径: `{absolute_path}`"
            )
        except Exception as e:
            logger.error("❌ 文件写入失败: %s -> %s", file_path, e)
            return f"❌ 创建文件失败: {str(e)}"

    async def read_file(self, file_path: str, event) -> str:
        """读取文件（兼容旧接口）"""
        try:
            sandbox = await self.get_sandbox(event=event)
            sf = await sandbox.adownload(file_path)
            if sf.content:
                text = sf.content.decode("utf-8", errors="replace")
                return f"📄 **{sf.path}** ({sf.size_human})\n\n```\n{text}\n```"
            return "❌ 文件内容为空"
        except FileNotFoundError:
            return f"❌ 文件不存在: {file_path}"
        except Exception as e:
            return f"❌ 读取失败: {str(e)}"

    async def list_files(self, dir_path: str, event) -> str:
        """列出文件（兼容旧接口）"""
        try:
            sandbox = await self.get_sandbox(event=event)
            files = await sandbox.alist_files(dir_path)
            if not files:
                return f"📁 `{dir_path}` 目录为空"
            lines = [f"📁 **{dir_path}** ({len(files)} 个文件)\n"]
            for f in files:
                lines.append(f"  • `{f.path}` ({f.size_human})")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ 列出文件失败: {str(e)}"

    async def start_web_server(
        self,
        project_path: str,
        port: int,
        event,
        framework: str = "python",
    ) -> str:
        """启动 Web 服务器"""
        if event.role != "admin":
            return "❌ 只有管理员可以启动服务"

        if framework == "flask":
            cmd = f"cd {project_path} && nohup python main.py > server.log 2>&1 &"
        elif framework == "fastapi":
            cmd = f"cd {project_path} && nohup uvicorn main:app --host 0.0.0.0 --port {port} > server.log 2>&1 &"
        elif framework == "node":
            cmd = f"cd {project_path} && nohup node server.js > server.log 2>&1 &"
        else:
            cmd = f"cd {project_path} && nohup python -m http.server {port} > server.log 2>&1 &"

        try:
            sandbox = await self.get_sandbox(event=event)
            await sandbox.aexec(cmd, kernel="bash")
            return (
                f"🚀 **服务启动中...**\n\n"
                f"项目: `{project_path}`\n"
                f"端口: {port}\n"
                f"框架: {framework}"
            )
        except Exception as e:
            return f"❌ 启动失败: {str(e)}"

    async def check_port(self, port: int, event) -> str:
        """检查端口是否被占用"""
        try:
            sandbox = await self.get_sandbox(event=event)
            result = await sandbox.aexec(
                f"netstat -tlnp 2>/dev/null | grep :{port} || echo '端口未被占用'",
                kernel="bash",
            )
            return result.text
        except Exception as e:
            return f"❌ 检查失败: {str(e)}"

    # ── 格式化 ────────────────────────────────────────────

    def get_current_mode_info(self) -> str:
        """获取当前执行模式信息"""
        mode = self._detect_mode()
        in_sandbox = is_inside_shipyard_sandbox()
        mode_names = {
            "shipyard": "🐳 Shipyard 沙盒（Docker 隔离）",
            "local": "💻 本地执行（无隔离）",
            "auto": "🔄 自动检测",
        }
        sandbox_note = ""
        if in_sandbox:
            sandbox_note = "\n⚡ **已在 Shipyard 沙盒内运行，直接本地执行（无需嵌套沙盒）**\n"
        return (
            f"🖥️ **当前执行环境配置**\n\n"
            f"运行模式: {mode_names.get(mode, mode)}\n"
            f"在沙盒内: {'✅ 是' if in_sandbox else '❌ 否'}\n"
            f"缓存沙盒数: {len(self._sandbox_cache)}\n"
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

    def _format_result(
        self,
        result: ExecResult,
        mode: str,
        command: str,
    ) -> str:
        """格式化执行结果"""
        show_process = self.config.get("show_thinking_process", True)
        lines = []

        if show_process:
            lines.append("🤖 **执行过程:**")
            lines.append(f"  📝 解析命令...")
            lines.append(f"  🔧 使用环境: {mode}")
            lines.append(f"  🚀 开始执行...")
            lines.append("")

        cmd_display = command[:50] + "..." if len(command) > 50 else command
        lines.append(f"🖥️ **{mode.upper()} 执行结果**\n")
        lines.append(f"命令: `{cmd_display}`")
        lines.append(f"退出码: {result.exit_code}\n")

        if result.text:
            output = result.text[:2000] + "..." if len(result.text) > 2000 else result.text
            lines.append(f"**输出:**\n```\n{output}\n```")

        if result.errors:
            errors = result.errors[:1000] + "..." if len(result.errors) > 1000 else result.errors
            lines.append(f"**错误:**\n```\n{errors}\n```")

        if result.images:
            lines.append(f"📷 生成了 {len(result.images)} 张图片")

        if result.success:
            lines.append("✅ 执行完成")
        else:
            lines.append("❌ 命令执行失败")

        return "\n".join(lines)
