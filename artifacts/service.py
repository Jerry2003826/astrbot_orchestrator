"""统一处理代码提取与本地持久化。"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Mapping, cast

from ..orchestrator.code_extractor import CodeExtractor, CodeWriter
from ..shared import UnsafePathError, ensure_within_base, quote_shell_path, slugify_identifier

logger = logging.getLogger(__name__)


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
        base_path: str = "/workspace",
    ) -> list[str]:
        """将文件写入工作区/沙盒目录。"""

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
        base_path: str = "/workspace",
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

        try:
            list_result = await sandbox.aexec(
                "find /home/ship_*/workspace /workspace -type f "
                "-not -path '*/\\.git/*' -not -path '*/__pycache__/*' "
                "-not -name '*.pyc' -not -path '*/skills/*' "
                "2>/dev/null | head -200",
                kernel="bash",
            )
            all_files: list[str] = []
            if list_result.text:
                for line in list_result.text.strip().splitlines():
                    line = line.strip()
                    if line and "/workspace/" in line and (
                        "project_" in line or "." in os.path.basename(line)
                    ):
                        all_files.append(line)

            if not all_files and created_files:
                all_files = list(created_files)
                logger.info("使用 created_files 列表: %d 个文件", len(all_files))

            for remote_path in all_files:
                try:
                    if "/workspace/" in remote_path:
                        rel_path = remote_path.split("/workspace/", 1)[1]
                    else:
                        rel_path = os.path.basename(remote_path)

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
