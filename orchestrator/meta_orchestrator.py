"""
Meta Orchestrator - 基于动态 SubAgent 的任务编排
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional, cast

from ..artifacts import ArtifactService
from .task_analyzer import TaskPlan

logger = logging.getLogger(__name__)


class MetaOrchestrator:
    """元编排器：分析任务 -> 动态创建 SubAgent -> 协调执行"""

    PERSIST_DIR: str = ""

    def __init__(
        self,
        context,
        task_analyzer,
        agent_manager,
        coordinator,
        config: Optional[Dict[str, Any]] = None,
        artifact_service: ArtifactService | None = None,
    ) -> None:
        self.context = context
        self.task_analyzer = task_analyzer
        self.agent_manager = agent_manager
        self.coordinator = coordinator
        self.config = config or {}

        # 使用传入的 artifact_service，或者动态获取插件目录
        if artifact_service:
            self.artifact_service = artifact_service
        else:
            # 动态获取插件目录下的 projects 文件夹
            persist_dir = self._get_plugin_projects_dir()
            self.artifact_service = ArtifactService(persist_dir)

        # 确保持久化目录存在
        _persist_dir = getattr(self.artifact_service, "persist_dir", None)
        if _persist_dir:
            os.makedirs(_persist_dir, exist_ok=True)

    def _get_plugin_projects_dir(self) -> str:
        """获取插件的项目存储目录。"""
        if self.PERSIST_DIR:
            return self.PERSIST_DIR

        from pathlib import Path

        # 从当前文件位置推断插件目录
        current_file = Path(__file__).resolve()
        plugin_root = current_file.parent.parent  # astrbot_orchestrator_v5 目录
        projects_dir = plugin_root / "projects"

        return str(projects_dir)

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
        result = cast(
            dict[str, Any],
            await self.coordinator.execute(
                plan=plan,
                agents=agents,
                event=event,
                is_admin=is_admin,
                provider_id=provider_id,
            ),
        )
        logger.info("步骤3完成: status=%s", result.get("status"))

        if not is_admin:
            logger.info("非管理员请求，跳过代码文件持久化与沙盒导出")
            result["answer"] += "\n\n⚠️ 非管理员请求不会自动写入或持久化文件。"
            if self.config.get("auto_cleanup_agents", True):
                logger.info("步骤4: 清理 SubAgents...")
                await self.agent_manager.cleanup(agents)
            if plan.summary:
                result["answer"] = f"{plan.summary}\n\n{result['answer']}"
            logger.info("MetaOrchestrator 处理完成（只读模式）")
            return result

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
        persist_result = self.artifact_service.persist_result(
            result=result,
            project_name=project_name,
        )

        if persist_result.get("success") and persist_result.get("saved_files"):
            saved_files = persist_result["saved_files"]
            export_path = persist_result["path"]
            result["export_path"] = export_path
            file_list = "\n".join(
                [f"  - `{f}` → `{os.path.join(export_path, f)}`" for f in saved_files]
            )
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
                created_files=created_files, event=event, project_name=project_name
            )
            if export_result.get("success") and export_result.get("saved_files"):
                saved_files = export_result["saved_files"]
                export_path = export_result["path"]
                result["export_path"] = export_path
                file_list = "\n".join(
                    [f"  - `{f}` → `{os.path.join(export_path, f)}`" for f in saved_files]
                )
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
        created_files: list[str] = []
        combined_text = self.artifact_service.collect_output_text(result)

        # 策略1: 合并所有任务输出，统一提取
        all_outputs = cast(list[str], result.get("_all_task_outputs", []))

        if combined_text:
            should_save = self.artifact_service.should_save_output_text(combined_text)
            code_block_count = self.artifact_service.count_code_blocks(combined_text)
            logger.info(
                "兜底代码检测（合并输出）: should_save=%s, code_blocks=%d, combined_len=%d",
                should_save,
                code_block_count,
                len(combined_text),
            )

            if (should_save or code_block_count > 0) and event:
                executor = self.coordinator.capability_builder.executor
                if executor:
                    project_name = f"project_{int(time.time())}"
                    written_files = cast(
                        list[str],
                        await self.artifact_service.write_output_to_workspace(
                            output_text=combined_text,
                            executor=executor,
                            event=event,
                            project_name=project_name,
                            base_path="/workspace",
                        ),
                    )
                    if written_files:
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

            if self.artifact_service.should_save_output_text(output_text):
                executor = self.coordinator.capability_builder.executor
                if executor:
                    project_name = f"project_{int(time.time())}"
                    written_files = cast(
                        list[str],
                        await self.artifact_service.write_output_to_workspace(
                            output_text=output_text,
                            executor=executor,
                            event=event,
                            project_name=project_name,
                            base_path="/workspace",
                        ),
                    )
                    if written_files:
                        logger.info("兜底策略2成功: 重新生成并写入 %d 个文件", len(written_files))
                        return written_files

        except Exception as e:
            logger.warning("重新生成代码失败: %s", e)

        return []

    async def _export_from_sandbox(
        self, created_files: List[str], event, project_name: str
    ) -> Dict[str, Any]:
        """
        从沙盒导出文件到插件持久化目录（备用方案）

        策略：
        1. 搜索 /home/ship_*/workspace/ 下的文件（Shipyard 实际路径）
        2. 也搜索 /workspace/ 下的文件
        3. 将文件保存到 {插件目录}/projects/{project_name}/
        """
        try:
            executor = self.coordinator.capability_builder.executor
            if not executor:
                return {"success": False, "error": "执行器不可用"}
            return cast(
                dict[str, Any],
                await self.artifact_service.export_sandbox_files(
                    executor=executor,
                    event=event,
                    project_name=project_name,
                    created_files=created_files,
                ),
            )

        except Exception as e:
            logger.error("导出文件失败: %s", e, exc_info=True)
            return {"success": False, "error": str(e)}

    def status(self) -> str:
        return str(self.agent_manager.list_agents())
