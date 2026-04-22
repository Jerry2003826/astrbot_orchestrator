"""
代码提取器 - 从 LLM 输出中提取代码块并保存到文件系统
"""

from dataclasses import dataclass
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

from ..shared import UnsafePathError, quote_shell_path, sanitize_relative_path

logger = logging.getLogger(__name__)


@dataclass
class CodeBlock:
    """代码块"""

    language: str
    content: str
    filename: Optional[str] = None


class CodeExtractor:
    """从 LLM 输出中提取代码块"""

    # 语言到文件扩展名的映射
    LANG_TO_EXT = {
        "html": ".html",
        "css": ".css",
        "javascript": ".js",
        "js": ".js",
        "python": ".py",
        "py": ".py",
        "typescript": ".ts",
        "ts": ".ts",
        "json": ".json",
        "yaml": ".yaml",
        "yml": ".yml",
        "bash": ".sh",
        "shell": ".sh",
        "sh": ".sh",
        "sql": ".sql",
        "markdown": ".md",
        "md": ".md",
        "xml": ".xml",
        "java": ".java",
        "go": ".go",
        "rust": ".rs",
        "c": ".c",
        "cpp": ".cpp",
        "php": ".php",
        "ruby": ".rb",
        "swift": ".swift",
        "kotlin": ".kt",
        "wxml": ".wxml",
        "wxss": ".wxss",
        "wxs": ".wxs",
        "less": ".less",
        "scss": ".scss",
        "sass": ".sass",
        "vue": ".vue",
        "jsx": ".jsx",
        "tsx": ".tsx",
        "toml": ".toml",
        "ini": ".ini",
        "conf": ".conf",
        "dockerfile": "Dockerfile",
        "makefile": "Makefile",
    }

    # 默认文件名映射
    DEFAULT_FILENAMES = {
        "html": "index.html",
        "css": "styles.css",
        "javascript": "app.js",
        "js": "app.js",
        "python": "main.py",
        "py": "main.py",
        "json": "config.json",
        "wxml": "index.wxml",
        "wxss": "index.wxss",
    }

    def _looks_like_filename(self, token: str) -> bool:
        """判断 header token 是否更像文件名而非语言名。"""

        if not token:
            return False
        if "/" in token or "\\" in token:
            return True
        if os.path.splitext(token)[1]:
            return True
        return token.lower() in {"dockerfile", "makefile"}

    def _parse_block_header(self, header: str) -> tuple[str, Optional[str]]:
        """解析代码块 header 中的语言和文件名。"""

        normalized = header.strip()
        if not normalized:
            return "", None

        for separator in (":", "："):
            if separator in normalized:
                lang_part, filename_part = normalized.split(separator, 1)
                lang = lang_part.strip().lower()
                filename = filename_part.strip() or None
                return lang, filename

        parts = normalized.split(maxsplit=1)
        if len(parts) == 2:
            return parts[0].strip().lower(), parts[1].strip() or None

        token = parts[0].strip()
        if self._looks_like_filename(token):
            return "", token
        return token.lower(), None

    def extract_code_blocks(self, text: str) -> List[CodeBlock]:
        """
        从文本中提取所有代码块

        支持格式:
        - ```language\ncode\n```
        - ```language:filename\ncode\n```
        - ```language filename\ncode\n```  (空格分隔)
        - 文件名注释模式（代码块前一行有 // filename 或 # filename）
        """
        blocks: List[CodeBlock] = []
        # 跟随每个已保留 block 对应的原始 match，以保障后续按位置回查前一行
        # 注释时不会因中间空内容 block 被跳过而错位。
        block_matches: List[re.Match[str]] = []

        # 模式1: 捕获 header 整行，再解析语言/文件名，避免把首行代码误识别为文件名
        pattern = r"```[ \t]*([^\r\n`]*)\r?\n(.*?)```"
        match_iter = list(re.finditer(pattern, text, re.DOTALL))

        for m in match_iter:
            header, content = m.group(1), m.group(2)
            lang, filename = self._parse_block_header(header)
            content = content.strip()

            # 跳过空代码块
            if not content:
                continue

            # 清理文件名中的多余字符
            if filename:
                # 移除可能的引号和括号
                filename = filename.strip("'\"()（）")
                # 如果文件名看起来不像文件名（没有扩展名且不含路径分隔符），忽略它
                if (
                    filename
                    and not os.path.splitext(filename)[1]
                    and "/" not in filename
                    and "\\" not in filename
                ):
                    # 可能是描述文字而非文件名，检查是否包含中文
                    if re.search(r"[\u4e00-\u9fff]", filename):
                        filename = None
                if filename:
                    try:
                        filename = sanitize_relative_path(filename)
                    except UnsafePathError:
                        logger.warning("忽略不安全文件名: %s", filename)
                        filename = None

            # 如果语言缺失但有文件名，尝试从扩展名推断
            if not lang:
                if filename:
                    ext = os.path.splitext(filename)[1].lower()
                    for key, value in self.LANG_TO_EXT.items():
                        if value == ext:
                            lang = key
                            break
                if not lang:
                    lang = "text"

            # 注意：不在此处填充 DEFAULT_FILENAMES，否则模式2（前一行注释文件名）将
            # 无法覆盖伪默认值。真正的默认文件名回退转移到模式2之后统一处理。

            blocks.append(CodeBlock(language=lang, content=content, filename=filename))
            block_matches.append(m)

        # 模式2: 检查代码块前的文件名注释
        # 例如: "<!-- index.html -->" 或 "// app.js" 或 "# main.py" 后跟代码块
        # 依靠 finditer 给出的单个块真实起始位置回查，而不是按语言名再搜一遍
        # ——后者会让多个同语言代码块的注释全部滑产到第一个代码块上。
        unsafe_block_ids: set[int] = set()
        if blocks:
            fname_comment_pattern = re.compile(r"(?://|#|<!--|/\*)\s*([\w./\\-]+\.\w+)")
            for block, match in zip(blocks, block_matches, strict=True):
                if block.filename:
                    continue
                # 找到此代码块所在行前一行的原文范围
                line_start = text.rfind("\n", 0, match.start())
                if line_start == -1:
                    continue
                prev_line_end = line_start
                prev_line_start = text.rfind("\n", 0, prev_line_end)
                prev_line = text[prev_line_start + 1 : prev_line_end].strip()
                fname_match = fname_comment_pattern.search(prev_line)
                if fname_match:
                    try:
                        block.filename = sanitize_relative_path(fname_match.group(1))
                    except UnsafePathError:
                        logger.warning("忽略不安全代码块注释文件名: %s", fname_match.group(1))
                        # 注释中出现明确但不安全的文件名——视作用户意图指向危险路径，
                        # 不回退到默认文件名，避免将内容写入错误位置。
                        unsafe_block_ids.add(id(block))

        # 模式3: 给仍未确定文件名的代码块填充默认文件名
        # （跳过模式2已被判定为不安全注释的代码块）
        for block in blocks:
            if id(block) in unsafe_block_ids:
                continue
            if not block.filename:
                block.filename = self.DEFAULT_FILENAMES.get(block.language)

        # 丢弃那些被显式标记为不安全的代码块
        blocks = [b for b in blocks if id(b) not in unsafe_block_ids]

        return blocks

    def extract_web_project(self, text: str) -> Dict[str, str]:
        """
        提取 Web 项目文件 (HTML/CSS/JS)

        Returns:
            Dict[filename, content]
        """
        blocks = self.extract_code_blocks(text)
        files = {}

        # 计数器，用于处理多个同类型文件
        counters: Dict[str, int] = {}

        for block in blocks:
            # 确定文件名
            if block.filename:
                try:
                    filename = sanitize_relative_path(block.filename)
                except UnsafePathError:
                    logger.warning("跳过不安全提取文件名: %s", block.filename)
                    continue
                if filename in files:
                    counters[block.language] = counters.get(block.language, 1) + 1
                    name, ext = os.path.splitext(filename)
                    filename = f"{name}_{counters[block.language]}{ext}"
            else:
                ext = self.LANG_TO_EXT.get(block.language, ".txt")
                base = self.DEFAULT_FILENAMES.get(block.language, f"file{ext}")

                # 处理重复文件名
                if base in files:
                    counters[block.language] = counters.get(block.language, 1) + 1
                    name, ext = os.path.splitext(base)
                    filename = f"{name}_{counters[block.language]}{ext}"
                else:
                    filename = base

            files[filename] = block.content

        return files

    def should_save_code(self, text: str) -> bool:
        """判断文本是否包含应该保存的代码"""
        blocks = self.extract_code_blocks(text)

        # 检查是否有可执行的代码文件
        saveable_langs = {
            "html",
            "css",
            "javascript",
            "js",
            "python",
            "py",
            "typescript",
            "ts",
            "json",
            "yaml",
            "yml",
            "sql",
            "bash",
            "shell",
            "sh",
            "php",
            "java",
            "go",
            "rust",
            "c",
            "cpp",
            "ruby",
            "swift",
            "kotlin",
            "wxml",
            "wxss",
            "wxs",
            "vue",
            "jsx",
            "tsx",
            "less",
            "scss",
            "sass",
            "toml",
            "xml",
        }
        saveable_exts = {
            ".html",
            ".css",
            ".js",
            ".py",
            ".ts",
            ".json",
            ".yaml",
            ".yml",
            ".sql",
            ".sh",
            ".php",
            ".java",
            ".go",
            ".rs",
            ".c",
            ".cpp",
            ".rb",
            ".wxml",
            ".wxss",
            ".wxs",
            ".vue",
            ".jsx",
            ".tsx",
            ".less",
            ".scss",
            ".toml",
            ".xml",
        }

        for block in blocks:
            # 降低内容长度阈值：只要有 20 个字符以上的代码就保存
            if block.language in saveable_langs and len(block.content) > 20:
                return True
            if block.filename:
                ext = os.path.splitext(block.filename)[1].lower()
                if ext in saveable_exts and len(block.content) > 10:
                    return True
            # 即使语言未知，如果有文件名就保存
            if block.filename and len(block.content) > 20:
                return True

        return False


class ProjectExporter:
    """项目导出器 - 将代码打包导出到宿主/宝塔等下载目录。"""

    # 默认下载导出根目录。原本硬编码为宝塔的 ``/www/wwwroot/downloads``，
    # 对非宝塔部署不安全也不合理。现改为允许通过环境变量
    # ``ASTRBOT_EXPORT_BASE`` 或构造参数覆写，默认退到与所在平台无关的
    # 安全临时目录，调用方应在生产环境中显式传入所需路径。
    _BAOTA_DEFAULT_PATH: str = "/www/wwwroot/downloads"

    @staticmethod
    def _default_export_path() -> str:
        """返回默认导出路径。

        优先级：``ASTRBOT_EXPORT_BASE`` > ``/www/wwwroot/downloads``（该目录存在时）
        > ``<tempdir>/astrbot_exports``。
        """

        env_path = os.environ.get("ASTRBOT_EXPORT_BASE")
        if env_path:
            return env_path
        if os.path.isdir(ProjectExporter._BAOTA_DEFAULT_PATH):
            return ProjectExporter._BAOTA_DEFAULT_PATH
        import tempfile

        return os.path.join(tempfile.gettempdir(), "astrbot_exports")

    def __init__(self, base_export_path: Optional[str] = None):
        """初始化导出器。

        Args:
            base_export_path: 显式指定的导出根目录。``None`` 时会按 ``_default_export_path``
                逻辑构造，遇到非宝塔部署时会退到系统临时目录。
        """

        self.base_export_path = base_export_path or self._default_export_path()

    async def export_from_sandbox(
        self,
        executor,
        event,
        project_name: str,
        sandbox_path: str = "/workspace",
    ) -> Tuple[bool, str]:
        """
        从沙盒导出项目到宝塔目录

        Args:
            executor: 执行管理器
            event: 消息事件
            project_name: 项目名称
            sandbox_path: 沙盒中的项目路径。默认为 ``/workspace``——有意义的固定工
                作目录。**不**接受 glob（如 ``/home/ship_*/workspace``），因为在调用
                ``ls`` / ``cd`` 时 glob 展开完全取决于运行时环境，且同时匹配多个
                路径时 ``cd`` 会报错。

        Returns:
            (success, message)
        """
        try:
            safe_path = quote_shell_path(sandbox_path)

            # 1. 在沙盒中列出文件
            await executor.execute(f"ls -la {safe_path}", event)

            # 2. 打包文件
            tar_cmd = f"cd {safe_path} && tar -czf /tmp/project.tar.gz ."
            await executor.execute(tar_cmd, event)

            # 3. 返回打包文件路径
            return True, "项目已打包: /tmp/project.tar.gz"

        except Exception as e:
            logger.error(f"导出项目失败: {e}")
            return False, f"导出失败: {str(e)}"

    def get_download_path(self, project_name: str) -> str:
        """获取下载路径"""
        return f"{self.base_export_path}/{project_name}"


class CodeWriter:
    """代码写入器 - 将代码写入沙盒文件系统"""

    # 调用者没有显式指定基路径时使用的回退值。仅在无法从沙盒读取 cwd 时
    # 才会真正落到这个值，从而避免将明确的显式传入的 "/workspace" 与 "使用
    # 会话 cwd" 两种意图混淆在同一个值里。
    DEFAULT_FALLBACK_BASE_PATH: str = "/workspace"

    def __init__(self, executor, base_path: str | None = None):
        """初始化写入器。

        Args:
            executor: 拥有 ``get_sandbox`` / ``write_file`` 等方法的执行器。
            base_path: 显式指定的写入基路径。传 ``None``（默认）表示直接使用沙
                盒 ``cwd``，在获取失败时回退到 ``DEFAULT_FALLBACK_BASE_PATH``。
        """

        self.executor = executor
        self._explicit_base_path: Optional[str] = base_path
        # 保留 ``base_path`` 属性以兼容现有行为：其他代码可以在写入前读取当
        # 前指定的基路径。未显式指定时仍然导出回退值，避免旧调用点看到
        # ``None``。
        self.base_path = base_path or self.DEFAULT_FALLBACK_BASE_PATH

    async def _resolve_base_path(self, event) -> str:
        """解析写入基路径。

        优先级：
        1. ``__init__`` 时显式传入的 ``base_path``（即使为 ``/workspace``，也尊重
           调用方的显式选择）。
        2. 当前会话沙盒的 ``cwd``，用于会话独享的工作目录。
        3. 回退到 ``DEFAULT_FALLBACK_BASE_PATH``。
        """

        if self._explicit_base_path is not None:
            return self._explicit_base_path

        get_sandbox = getattr(self.executor, "get_sandbox", None)
        if not callable(get_sandbox):
            return self.DEFAULT_FALLBACK_BASE_PATH

        try:
            sandbox = await get_sandbox(event=event)
        except TypeError:
            try:
                sandbox = await get_sandbox(event)
            except Exception:
                return self.DEFAULT_FALLBACK_BASE_PATH
        except Exception:
            return self.DEFAULT_FALLBACK_BASE_PATH

        cwd = getattr(sandbox, "cwd", "")
        return str(cwd) if cwd else self.DEFAULT_FALLBACK_BASE_PATH

    async def write_files(
        self, files: Dict[str, str], event, project_name: str = "project"
    ) -> Tuple[bool, List[str]]:
        """
        将文件写入沙盒

        Args:
            files: {filename: content}
            event: 消息事件
            project_name: 项目名称

        Returns:
            (success, created_files)
        """
        base_path = await self._resolve_base_path(event)
        project_path = f"{base_path}/{project_name}"
        created_files = []

        try:
            # 创建项目目录（转义路径以避免含空格 / shell 元字符的 cwd 注入命令）
            logger.info("创建项目目录: %s", project_path)
            await self.executor.execute(f"mkdir -p {quote_shell_path(project_path)}", event)

            for filename, content in files.items():
                file_path = f"{project_path}/{filename}"

                # 创建子目录（如果需要）
                dir_path = os.path.dirname(file_path)
                if dir_path != project_path:
                    await self.executor.execute(f"mkdir -p {quote_shell_path(dir_path)}", event)

                # 写入文件（使用 skip_auth=True 绕过权限检查，因为这是内部调用）
                logger.info("写入文件: %s (内容长度: %d)", file_path, len(content))
                result = await self.executor.write_file(file_path, content, event, skip_auth=True)

                if "✅" in result or "已创建" in result:
                    created_files.append(file_path)
                    logger.info("✅ 文件已写入: %s", file_path)
                else:
                    logger.warning("⚠️ 文件写入可能失败: %s, result: %s", file_path, result[:200])
                    # 即使 write_file 返回非预期结果，也尝试用 upload 直接写入
                    try:
                        sandbox = await self.executor.get_sandbox(event=event)
                        await sandbox.aupload(file_path, content)
                        created_files.append(file_path)
                        logger.info("✅ 文件通过 upload 备用方式写入: %s", file_path)
                    except Exception as upload_err:
                        logger.error("❌ upload 备用写入也失败: %s -> %s", file_path, upload_err)

            logger.info("项目文件写入完成: %d/%d 成功", len(created_files), len(files))
            return len(created_files) > 0, created_files

        except Exception as e:
            logger.error("写入文件失败: %s", e, exc_info=True)
            return len(created_files) > 0, created_files

    async def get_project_files(self, event, project_name: str = "project") -> List[str]:
        """获取项目中的文件列表"""
        base_path = await self._resolve_base_path(event)
        project_path = f"{base_path}/{project_name}"

        try:
            result = await self.executor.execute(
                f"find {quote_shell_path(project_path)} -type f", event
            )

            # 解析文件列表
            files = []
            for line in result.split("\n"):
                line = line.strip()
                if (
                    line
                    and not line.startswith("🖥️")
                    and not line.startswith("命令")
                    and project_path in line
                ):
                    files.append(line)

            return files

        except Exception as e:
            logger.error(f"获取文件列表失败: {e}")
            return []
