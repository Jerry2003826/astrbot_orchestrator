"""
Meta Orchestrator - 基于动态 SubAgent 的任务编排
"""

from __future__ import annotations

import logging
import os
import time
import asyncio
from typing import Any, Dict, Optional, List

from .task_analyzer import TaskPlan
from .code_extractor import CodeExtractor, CodeWriter

logger = logging.getLogger(__name__)


class MetaOrchestrator:
    """元编排器：分析任务 -> 动态创建 SubAgent -> 协调执行"""

    # 持久化目录（astrbot 容器内，会被 docker volume 持久化）
    PERSIST_DIR = "/AstrBot/data/agent_projects"

    def __init__(
        self,
        context,
        task_analyzer,
        agent_manager,
        coordinator,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.context = context
        self.task_analyzer = task_analyzer
        self.agent_manager = agent_manager
        self.coordinator = coordinator
        self.config = config or {}
        
        # 确保持久化目录存在
        os.makedirs(self.PERSIST_DIR, exist_ok=True)

    async def process(
        self,
        user_request: str,
        provider_id: str,
        event,
        is_admin: bool,
    ) -> Dict[str, Any]:
        logger.info("MetaOrchestrator 开始处理: request=%s...", user_request[:50])
        
        logger.info("步骤1: 分析任务...")
        plan: TaskPlan = await self.task_analyzer.analyze(user_request, provider_id)
        logger.info("步骤1完成: %d agents, %d tasks", len(plan.agents), len(plan.tasks))

        logger.info("步骤2: 创建 SubAgents...")
        agents = await self.agent_manager.create_agents(plan.agents)
        logger.info("步骤2完成: 创建了 %d 个 agents", len(agents))
        
        logger.info("步骤3: 执行任务...")
        result = await self.coordinator.execute(
            plan=plan,
            agents=agents,
            event=event,
            is_admin=is_admin,
            provider_id=provider_id,
        )
        logger.info("步骤3完成: status=%s", result.get("status"))

        # ★ 增强兜底：合并所有任务输出，尝试提取代码
        created_files = result.get("created_files", [])
        if not created_files:
            created_files = await self._fallback_extract_code(result, event, provider_id)
            if created_files:
                result["created_files"] = created_files
                file_list = "\n".join([f"  - {f}" for f in created_files])
                result["answer"] += f"\n\n📁 **已创建文件（兜底提取）:**\n{file_list}"

        # ★ 步骤4: 直接从 LLM 输出中提取代码并保存到 AstrBot 持久化目录
        # 不再依赖沙盒导出（沙盒文件可能随会话结束被清理）
        logger.info("步骤4: 保存文件到 AstrBot 持久化目录...")
        project_name = f"project_{int(time.time())}"
        persist_result = await self._persist_files_locally(
            result=result,
            project_name=project_name,
            event=event,
        )
        
        if persist_result.get("success") and persist_result.get("saved_files"):
            saved_files = persist_result["saved_files"]
            export_path = persist_result["path"]
            result["export_path"] = export_path
            file_list = "\n".join([f"  - `{f}` → `{os.path.join(export_path, f)}`" for f in saved_files])
            result["answer"] += (
                f"\n\n📦 **文件已持久化保存（共 {len(saved_files)} 个）:**\n{file_list}"
                f"\n\n💾 **项目绝对路径:** `{export_path}`"
                f"\n📥 **下载/查看方式:**"
                f"\n  - 查看文件: `/exec cat {export_path}/<文件名>`"
                f"\n  - 打包下载: `/exec cd {export_path} && tar czf /workspace/project.tar.gz .`"
                f"\n  - 列出文件: `/exec ls -la {export_path}/`"
                f"\n💡 文件已保存到 AstrBot 数据目录，不会因沙盒销毁而丢失"
            )
            logger.info("步骤4完成: 保存 %d 个文件到 %s", len(saved_files), export_path)
        else:
            # 回退：尝试从沙盒导出
            logger.info("步骤4: 本地保存无文件，尝试从沙盒导出...")
            export_result = await self._export_from_sandbox(
                created_files=created_files,
                event=event,
                project_name=project_name
            )
            if export_result.get("success") and export_result.get("saved_files"):
                saved_files = export_result["saved_files"]
                export_path = export_result["path"]
                result["export_path"] = export_path
                file_list = "\n".join([f"  - `{f}` → `{os.path.join(export_path, f)}`" for f in saved_files])
                result["answer"] += (
                    f"\n\n📦 **文件已持久化保存（共 {len(saved_files)} 个）:**\n{file_list}"
                    f"\n\n💾 **项目绝对路径:** `{export_path}`"
                    f"\n📥 **下载/查看方式:**"
                    f"\n  - 查看文件: `/exec cat {export_path}/<文件名>`"
                    f"\n  - 打包下载: `/exec cd {export_path} && tar czf /workspace/project.tar.gz .`"
                    f"\n  - 列出文件: `/exec ls -la {export_path}/`"
                )
                logger.info("步骤4完成（沙盒导出）: %d 个文件", len(saved_files))
            else:
                logger.warning("步骤4: 没有文件被保存")

        if self.config.get("auto_cleanup_agents", True):
            logger.info("步骤5: 清理 SubAgents...")
            await self.agent_manager.cleanup(agents)

        if plan.summary:
            result["answer"] = f"{plan.summary}\n\n{result['answer']}"

        logger.info("MetaOrchestrator 处理完成")
        return result

    async def _persist_files_locally(
        self,
        result: Dict[str, Any],
        project_name: str,
        event=None,
    ) -> Dict[str, Any]:
        """
        直接从 LLM 输出中提取代码，保存到 AstrBot 本地持久化目录。
        不依赖沙盒，直接用 Python 文件 I/O 写入。
        """
        extractor = CodeExtractor()
        saved_files = []
        
        # 合并所有任务输出
        all_outputs = result.get("_all_task_outputs", [])
        combined_text = "\n\n".join(all_outputs) if all_outputs else ""
        
        # 也检查 answer 本身
        answer_text = result.get("answer", "") or ""
        if answer_text:
            combined_text = combined_text + "\n\n" + answer_text
        
        if not combined_text:
            return {"success": False, "error": "无输出内容"}
        
        # 提取代码文件
        files = extractor.extract_web_project(combined_text)
        if not files:
            logger.info("本地持久化: 未提取到代码文件")
            return {"success": True, "saved_files": [], "path": ""}
        
        # 创建项目目录
        local_project_dir = os.path.join(self.PERSIST_DIR, project_name)
        os.makedirs(local_project_dir, exist_ok=True)
        
        # 写入文件
        for filename, content in files.items():
            try:
                file_path = os.path.join(local_project_dir, filename)
                file_dir = os.path.dirname(file_path)
                os.makedirs(file_dir, exist_ok=True)
                
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)
                
                saved_files.append(filename)
                logger.info("✅ 本地持久化: %s (%d bytes)", file_path, len(content))
            except Exception as e:
                logger.warning("⚠️ 本地持久化失败: %s -> %s", filename, e)
        
        if saved_files:
            logger.info("✅ 本地持久化完成: %d 个文件 -> %s", len(saved_files), local_project_dir)
            return {
                "success": True,
                "path": local_project_dir,
                "saved_files": saved_files,
                "total": len(saved_files),
            }
        
        return {"success": True, "saved_files": [], "path": ""}

    async def _fallback_extract_code(
        self,
        result: Dict[str, Any],
        event,
        provider_id: str,
    ) -> List[str]:
        """
        兜底代码提取：合并所有任务的原始输出，尝试提取代码块并写入文件系统。
        
        如果所有任务输出中都没有代码块，则尝试让 LLM 重新生成一次带代码的回答。
        """
        extractor = CodeExtractor()
        created_files = []

        # 策略1: 合并所有任务输出，统一提取
        all_outputs = result.get("_all_task_outputs", [])
        combined_text = "\n\n".join(all_outputs) if all_outputs else ""
        
        # 也检查 answer 本身
        answer_text = result.get("answer", "") or ""
        if answer_text and answer_text not in combined_text:
            combined_text = combined_text + "\n\n" + answer_text

        if combined_text:
            should_save = extractor.should_save_code(combined_text)
            code_blocks = extractor.extract_code_blocks(combined_text)
            logger.info(
                "兜底代码检测（合并输出）: should_save=%s, code_blocks=%d, combined_len=%d",
                should_save, len(code_blocks), len(combined_text)
            )

            if (should_save or len(code_blocks) > 0) and event:
                files = extractor.extract_web_project(combined_text)
                if files:
                    executor = self.coordinator.capability_builder.executor
                    if executor:
                        project_name = f"project_{int(time.time())}"
                        code_writer = CodeWriter(executor, base_path="/workspace")
                        success, written_files = await code_writer.write_files(
                            files=files,
                            event=event,
                            project_name=project_name
                        )
                        if success and written_files:
                            created_files = written_files
                            logger.info("兜底写入成功（合并输出）: files=%s", written_files)
                            return created_files

        # 策略2: 如果合并输出中也没有代码，尝试让 LLM 重新生成
        if not created_files and event and all_outputs:
            logger.info("兜底策略2: 尝试让 LLM 重新生成带代码块的回答...")
            try:
                created_files = await self._regenerate_code(
                    all_outputs=all_outputs,
                    event=event,
                    provider_id=provider_id,
                )
            except Exception as e:
                logger.warning("兜底策略2失败: %s", e)

        return created_files

    async def _regenerate_code(
        self,
        all_outputs: List[str],
        event,
        provider_id: str,
    ) -> List[str]:
        """
        让 LLM 根据之前的任务输出，重新生成带标准代码块格式的代码。
        """
        # 取前 3000 字符作为上下文
        context_text = "\n---\n".join(all_outputs)
        if len(context_text) > 3000:
            context_text = context_text[:3000] + "..."

        prompt = f"""以下是之前的任务输出，其中包含了项目的设计和实现描述，但代码没有使用标准格式输出。

请根据以下内容，重新输出所有代码文件。

【之前的输出】
{context_text}

【要求】
1. 每个文件必须使用 ```语言:文件名 格式的 markdown 代码块
2. 每个文件必须是完整的、可直接运行的代码
3. 不要输出任何解释文字，只输出代码块
4. 示例格式：
```python:main.py
print("hello")
```
"""

        try:
            response = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
                system_prompt="你是一个代码格式化专家。只输出标准 markdown 代码块格式的代码文件，不要输出其他内容。",
            )

            output_text = response.completion_text
            extractor = CodeExtractor()
            
            if extractor.should_save_code(output_text):
                files = extractor.extract_web_project(output_text)
                if files:
                    executor = self.coordinator.capability_builder.executor
                    if executor:
                        project_name = f"project_{int(time.time())}"
                        code_writer = CodeWriter(executor, base_path="/workspace")
                        success, written_files = await code_writer.write_files(
                            files=files,
                            event=event,
                            project_name=project_name
                        )
                        if success and written_files:
                            logger.info("兜底策略2成功: 重新生成并写入 %d 个文件", len(written_files))
                            return written_files

        except Exception as e:
            logger.warning("重新生成代码失败: %s", e)

        return []

    async def _export_from_sandbox(
        self,
        created_files: List[str],
        event,
        project_name: str
    ) -> Dict[str, Any]:
        """
        从沙盒导出文件到 astrbot 持久化目录（备用方案）
        
        策略：
        1. 搜索 /home/ship_*/workspace/ 下的文件（Shipyard 实际路径）
        2. 也搜索 /workspace/ 下的文件
        3. 将文件保存到 /AstrBot/data/agent_projects/{project_name}/
        """
        try:
            executor = self.coordinator.capability_builder.executor
            if not executor:
                return {"success": False, "error": "执行器不可用"}
            
            # 获取沙盒实例
            try:
                sandbox = await executor.get_sandbox(event=event)
            except Exception as e:
                logger.error("获取沙盒失败: %s", e)
                return {"success": False, "error": f"获取沙盒失败: {e}"}
            
            # 创建本地项目目录
            local_project_dir = os.path.join(self.PERSIST_DIR, project_name)
            os.makedirs(local_project_dir, exist_ok=True)
            
            saved_files = []
            
            try:
                # ★ 修复：搜索 Shipyard 沙盒的实际路径
                # Shipyard 的 workspace 在 /home/ship_xxx/workspace/ 下
                list_result = await sandbox.aexec(
                    "find /home/ship_*/workspace /workspace -type f "
                    "-not -path '*/\\.git/*' -not -path '*/__pycache__/*' "
                    "-not -name '*.pyc' -not -path '*/skills/*' "
                    "2>/dev/null | head -200",
                    kernel="bash"
                )
                
                all_files = []
                if list_result.text:
                    for line in list_result.text.strip().splitlines():
                        line = line.strip()
                        if line and ("/workspace/" in line) and ("project_" in line or "." in os.path.basename(line)):
                            all_files.append(line)
                
                logger.info("沙盒中发现 %d 个文件", len(all_files))
                
                if not all_files and created_files:
                    all_files = created_files
                    logger.info("使用 created_files 列表: %d 个文件", len(all_files))
                
                # 逐个下载文件
                for remote_path in all_files:
                    try:
                        # 计算相对路径
                        # 处理 /home/ship_xxx/workspace/project_xxx/file 格式
                        if "/workspace/" in remote_path:
                            rel_path = remote_path.split("/workspace/", 1)[1]
                        else:
                            rel_path = os.path.basename(remote_path)
                        
                        if not rel_path:
                            continue
                        
                        # 通过 cat 读取文件内容（比 base64 更可靠）
                        read_result = await sandbox.aexec(
                            f"cat '{remote_path}' 2>/dev/null",
                            kernel="bash"
                        )
                        
                        if read_result.text and read_result.exit_code == 0:
                            content = read_result.text
                            
                            # 保存到本地
                            local_path = os.path.join(local_project_dir, rel_path)
                            local_dir = os.path.dirname(local_path)
                            os.makedirs(local_dir, exist_ok=True)
                            
                            with open(local_path, "w", encoding="utf-8") as f:
                                f.write(content)
                            
                            saved_files.append(rel_path)
                            logger.info("✅ 已导出: %s -> %s", remote_path, local_path)
                        else:
                            logger.warning("⚠️ 无法读取文件: %s (exit=%d)", remote_path, read_result.exit_code)
                            
                    except Exception as file_err:
                        logger.warning("⚠️ 导出文件失败: %s -> %s", remote_path, file_err)
                        continue
                
            except Exception as scan_err:
                logger.error("扫描沙盒文件失败: %s", scan_err)
            
            if saved_files:
                return {
                    "success": True,
                    "path": local_project_dir,
                    "saved_files": saved_files,
                    "total": len(saved_files)
                }
            else:
                return {"success": True, "path": local_project_dir, "saved_files": [], "total": 0}
            
        except Exception as e:
            logger.error("导出文件失败: %s", e, exc_info=True)
            return {"success": False, "error": str(e)}

    def status(self) -> str:
        return self.agent_manager.list_agents()
