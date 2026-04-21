"""统一处理代码提取与本地持久化。"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import posixpath
from typing import Any, Mapping, cast

from ..orchestrator.code_extractor import CodeExtractor, CodeWriter
from ..shared import UnsafePathError, ensure_within_base, quote_shell_path, slugify_identifier

logger = logging.getLogger(__name__)

# 扫描沙盒文件时允许的候选工作目录前缀
# 这些目录会被动态拼接到 `find` 命令，且在计算相对路径时被剥离。
_FALLBACK_SANDBOX_ROOTS: tuple[str, ...] = ("/workspace", "/home/ship_*/workspace")


@dataclass(slots=True)
class ArtifactService:
    """管理结构化结果到本地 artifact 的落盘边界。"""

    persist_dir: str

    def extract_files_from_text(self, text: str) -> dict[str, str]:
        """从文本中提取候选代码文件。"""

        if not text.strip():
            return {}

        extractor = CodeExtractor()
        return cast(dict[str, str], extractor.extract_web_project(text))

    def collect_output_text(self, result: Mapping[str, Any]) -> str:
        """合并任务输出与最终回答文本。"""

        all_outputs = result.get("_all_task_outputs", [])
        combined_text = "\n\n".join(all_outputs) if all_outputs else ""
        answer_text = str(result.get("answer", "") or "")
        if answer_text:
            combined_text = combined_text + "\n\n" + answer_text if combined_text else answer_text
        return combined_text

    def extract_files_from_result(self, result: Mapping[str, Any]) -> dict[str, str]:
        """从结果对象中提取候选代码文件。"""

        combined_text = self.collect_output_text(result)
        return self.extract_files_from_text(combined_text)

    def should_save_output_text(self, text: str) -> bool:
        """判断文本是否包含值得保存的代码。"""

        if not text.strip():
            return False

        extractor = CodeExtractor()
        return bool(extractor.should_save_code(text))

    def count_code_blocks(self, text: str) -> int:
        """返回文本中提取到的代码块数量。"""

        if not text.strip():
            return 0

        extractor = CodeExtractor()
        return len(extractor.extract_code_blocks(text))

    def persist_result(self, result: Mapping[str, Any], project_name: str) -> dict[str, Any]:
        """从结果对象中提取并持久化代码文件。"""

        combined_text = self.collect_output_text(result)
        if not combined_text:
            return {"success": False, "error": "无输出内容"}

        files = self.extract_files_from_result(result)
        if not files:
            logger.info("本地持久化: 未提取到代码文件")
            return {"success": True, "saved_files": [], "path": ""}

        return self.persist_files(files, project_name)

    def persist_files(self, files: Mapping[str, str], project_name: str) -> dict[str, Any]:
        """将提取出的文件安全写入本地持久化目录。"""

        safe_project_name = slugify_identifier(project_name)
        local_project_dir = ensure_within_base(self.persist_dir, safe_project_name)
        os.makedirs(local_project_dir, exist_ok=True)

        saved_files: list[str] = []
        for filename, content in files.items():
            try:
                file_path = ensure_within_base(local_project_dir, filename)
                os.makedirs(file_path.parent, exist_ok=True)
                with open(file_path, "w", encoding="utf-8") as file_obj:
                    file_obj.write(content)
                saved_files.append(filename)
                logger.info("✅ 本地持久化: %s (%d bytes)", file_path, len(content))
            except UnsafePathError as exc:
                logger.warning("⚠️ 跳过不安全文件路径: %s -> %s", filename, exc)
            except Exception as exc:
                logger.warning("⚠️ 本地持久化失败: %s -> %s", filename, exc)

        if saved_files:
            logger.info("✅ 本地持久化完成: %d 个文件 -> %s", len(saved_files), local_project_dir)
            return {
                "success": True,
                "path": str(local_project_dir),
                "saved_files": saved_files,
                "total": len(saved_files),
            }
        return {"success": True, "saved_files": [], "path": str(local_project_dir), "total": 0}

    async def write_files_to_workspace(
        self,
        files: Mapping[str, str],
        executor: Any,
        event: Any,
        project_name: str,
        base_path: str | None = None,
    ) -> list[str]:
        """将文件写入工作区/沙盒目录。

        ``base_path`` 为 ``None`` 时（默认），``CodeWriter`` 会解析当前会话沙盒
        实际的工作目录作为写入基点，避免所有会话挤到共享 ``/workspace``。
        """

        if not files:
            return []

        code_writer = CodeWriter(executor, base_path=base_path)
        success, written_files = await code_writer.write_files(
            files=dict(files),
            event=event,
            project_name=slugify_identifier(project_name),
        )
        return written_files if success and written_files else []

    async def write_output_to_workspace(
        self,
        output_text: str,
        executor: Any,
        event: Any,
        project_name: str,
        base_path: str | None = None,
    ) -> list[str]:
        """从文本中提取代码并写入工作区/沙盒目录。"""

        files = self.extract_files_from_text(output_text)
        return await self.write_files_to_workspace(
            files=files,
            executor=executor,
            event=event,
            project_name=project_name,
            base_path=base_path,
        )

    async def export_sandbox_files(
        self,
        executor: Any,
        event: Any,
        project_name: str,
        created_files: list[str],
    ) -> dict[str, Any]:
        """从沙盒导出文件到本地持久化目录。"""

        try:
            sandbox = await executor.get_sandbox(event=event)
        except Exception as exc:
            logger.error("获取沙盒失败: %s", exc)
            return {"success": False, "error": f"获取沙盒失败: {exc}"}

        safe_project_name = slugify_identifier(project_name)
        local_project_dir = ensure_within_base(self.persist_dir, safe_project_name)
        os.makedirs(local_project_dir, exist_ok=True)
        saved_files: list[str] = []

        scan_roots = self._scan_roots(sandbox)

        try:
            list_cmd = self._build_list_command(scan_roots)
            list_result = await sandbox.aexec(list_cmd, kernel="bash")
            all_files: list[str] = []
            if list_result.text:
                for line in list_result.text.strip().splitlines():
                    line = line.strip()
                    # 黑名单过滤：只排除明确不需要的内容，避免无后缀文件
                    # （Makefile/Dockerfile/README）被丢弃。
                    if (
                        line
                        and self._path_under_any_root(line, scan_roots)
                        and not line.endswith(".pyc")
                        and "__pycache__" not in line
                    ):
                        all_files.append(line)

            if not all_files and created_files:
                all_files = list(created_files)
                logger.info("使用 created_files 列表: %d 个文件", len(all_files))

            for remote_path in all_files:
                try:
                    rel_path = self._relative_to_roots(remote_path, scan_roots)
                    if not rel_path:
                        continue

                    quoted_path = quote_shell_path(remote_path)
                    read_result = await sandbox.aexec(
                        f"cat {quoted_path} 2>/dev/null",
                        kernel="bash",
                    )

                    if read_result.text and read_result.exit_code == 0:
                        local_path = ensure_within_base(local_project_dir, rel_path)
                        os.makedirs(local_path.parent, exist_ok=True)
                        with open(local_path, "w", encoding="utf-8") as file_obj:
                            file_obj.write(read_result.text)
                        saved_files.append(rel_path)
                        logger.info("✅ 已导出: %s -> %s", remote_path, local_path)
                    else:
                        logger.warning(
                            "⚠️ 无法读取文件: %s (exit=%d)",
                            remote_path,
                            read_result.exit_code,
                        )
                except UnsafePathError as exc:
                    logger.warning("⚠️ 跳过不安全导出路径: %s -> %s", remote_path, exc)
                except Exception as exc:
                    logger.warning("⚠️ 导出文件失败: %s -> %s", remote_path, exc)
        except Exception as exc:
            logger.error("扫描沙盒文件失败: %s", exc)

        return {
            "success": True,
            "path": str(local_project_dir),
            "saved_files": saved_files,
            "total": len(saved_files),
        }

    @staticmethod
    def _scan_roots(sandbox: Any) -> tuple[str, ...]:
        """根据沙盒实际工作目录构造搜索根列表，保留原有回退前缀。

        会话独享的 ``/workspace/sessions/<hash>`` 目录必须作为最长前缀排在前面，
        以便在计算相对路径时优先剑离它们而不是通用的 ``/workspace``。
        """

        cwd = str(getattr(sandbox, "cwd", "") or "").rstrip("/")
        roots: list[str] = []
        if cwd:
            roots.append(cwd)
        for candidate in _FALLBACK_SANDBOX_ROOTS:
            if candidate and candidate not in roots:
                roots.append(candidate)
        return tuple(roots)

    @staticmethod
    def _build_list_command(scan_roots: tuple[str, ...]) -> str:
        """根据候选根目录拼接 find 命令。

        包含通配符的根（如 ``/home/ship_*/workspace``）不转义，交由 bash 展开；
        其余根全部转义以防止空格/元字符注入。
        """

        parts: list[str] = []
        for root in scan_roots:
            if "*" in root or "?" in root:
                parts.append(root)
            else:
                parts.append(quote_shell_path(root))
        roots_str = " ".join(parts)
        return (
            f"find {roots_str} -type f "
            "-not -path '*/.git/*' -not -path '*/__pycache__/*' "
            "-not -name '*.pyc' -not -path '*/skills/*' "
            "2>/dev/null | head -200"
        )

    @staticmethod
    def _path_under_any_root(path: str, scan_roots: tuple[str, ...]) -> bool:
        """判断路径是否属于任一候选根。"""

        for root in scan_roots:
            if not root:
                continue
            # /home/ship_*/workspace 类 glob 根在本进程无法展开，回退到包含判断。
            if "*" in root:
                needle = root.split("*", 1)[0]
                if needle and needle in path:
                    return True
                continue
            prefix = root.rstrip("/") + "/"
            if path == root or path.startswith(prefix):
                return True
        return False

    @staticmethod
    def _relative_to_roots(path: str, scan_roots: tuple[str, ...]) -> str:
        """将绝对路径换算为相对于包含它的最长根目录的路径。"""

        best_match = ""
        for root in scan_roots:
            if not root or "*" in root:
                continue
            prefix = root.rstrip("/") + "/"
            if path == root or path.startswith(prefix):
                if len(prefix) > len(best_match):
                    best_match = prefix
        if best_match:
            return path[len(best_match) :]
        return posixpath.basename(path)
