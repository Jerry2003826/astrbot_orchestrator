"""
SubAgent 协调器
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import re
import time
from typing import Any, Dict, List, Optional

from ..artifacts import ArtifactService
from .agent_bus import AgentMessageBus
from .agent_templates import AgentSpec
from .code_extractor import CodeExtractor
from .task_analyzer import AgentTask, TaskPlan

logger = logging.getLogger(__name__)


@dataclass
class TaskResult:
    task_id: str
    status: str
    output: str
    error: Optional[str] = None
    created_files: List[str] = field(default_factory=list)


class AgentCoordinator:
    """协调多个 SubAgent 的任务执行"""

    def __init__(
        self,
        context,
        capability_builder,
        config: Optional[Dict] = None,
        artifact_service: ArtifactService | None = None,
    ) -> None:
        self.context = context
        self.capability_builder = capability_builder
        self.config = config or {}

        # 使用传入的 artifact_service，或者动态获取插件目录
        if artifact_service:
            self.artifact_service = artifact_service
        else:
            persist_dir = self._get_plugin_projects_dir()
            self.artifact_service = ArtifactService(persist_dir)

        self.bus = AgentMessageBus()
        self.verbose_logs = self.config.get("subagent_verbose_logs", False) or self.config.get(
            "debug_mode", False
        )
        self.code_extractor = CodeExtractor()
        self.all_created_files: List[str] = []  # 记录所有创建的文件
        self._all_task_outputs: List[str] = []  # 记录所有任务的原始输出（用于兜底提取）

    def _get_plugin_projects_dir(self) -> str:
        """获取插件的项目存储目录。"""
        import os
        from pathlib import Path

        # 从当前文件位置推断插件目录
        current_file = Path(__file__).resolve()
        plugin_root = current_file.parent.parent  # astrbot_orchestrator_v5 目录
        projects_dir = plugin_root / "projects"

        # 确保目录存在
        os.makedirs(projects_dir, exist_ok=True)

        return str(projects_dir)

    async def execute(
        self,
        plan: TaskPlan,
        agents: List[AgentSpec],
        event,
        is_admin: bool,
        provider_id: str,
    ) -> dict[str, Any]:
        # 每次执行前重置状态
        self.all_created_files = []
        self._all_task_outputs = []

        agent_map = {agent.role: agent for agent in agents}
        pending = {task.task_id: task for task in plan.tasks}
        completed: Dict[str, TaskResult] = {}

        max_parallel = self.config.get("max_parallel_tasks", 3)
        task_timeout = self.config.get("agent_timeout", 300)
        semaphore = asyncio.Semaphore(max_parallel)

        async def run_task(task: AgentTask) -> TaskResult:
            async with semaphore:
                try:
                    return await asyncio.wait_for(
                        self._run_task(task, agent_map, event, is_admin, provider_id),
                        timeout=task_timeout,
                    )
                except asyncio.TimeoutError:
                    return TaskResult(
                        task_id=task.task_id,
                        status="failed",
                        output="",
                        error="任务执行超时",
                    )

        while pending:
            ready = [
                task
                for task in pending.values()
                if all(dep in completed for dep in task.depends_on)
            ]
            if not ready:
                logger.warning("任务依赖无法满足，终止执行")
                break

            if self.verbose_logs:
                ready_ids = ", ".join([task.task_id for task in ready])
                logger.info("SubAgent 任务准备执行: %s", ready_ids)

            results = await asyncio.gather(*(run_task(task) for task in ready))
            for result in results:
                completed[result.task_id] = result
                pending.pop(result.task_id, None)

        return self._build_response(plan, completed, agents)

    async def _run_task(
        self,
        task: AgentTask,
        agent_map: Dict[str, AgentSpec],
        event,
        is_admin: bool,
        provider_id: str,
    ) -> TaskResult:
        agent = agent_map.get(task.agent_role) or agent_map.get("code")
        sender = agent.name if agent else "agent"
        created_files = []

        try:
            if self.verbose_logs:
                logger.info(
                    "执行任务 %s (role=%s action=%s)",
                    task.task_id,
                    task.agent_role,
                    task.action,
                )
            if task.action == "create_skill":
                if not is_admin:
                    return TaskResult(
                        task_id=task.task_id,
                        status="skipped",
                        output="需要管理员权限才能创建 Skill",
                    )
                output = await self.capability_builder.build_skill(
                    task_description=task.input or task.description,
                    provider_id=provider_id,
                )
            elif task.action == "config_mcp":
                if not is_admin:
                    return TaskResult(
                        task_id=task.task_id,
                        status="skipped",
                        output="需要管理员权限才能配置 MCP",
                    )
                output = await self.capability_builder.configure_mcp(
                    task_description=task.input or task.description,
                    provider_id=provider_id,
                    params=task.params,
                )
            elif task.action == "execute_code":
                # 安全检查：如果 input 是自然语言而非 shell 命令，降级为 llm 任务
                if self._is_natural_language(task.input):
                    logger.warning(
                        "任务 %s 的 execute_code input 是自然语言，降级为 llm 任务: %s",
                        task.task_id,
                        (task.input or "")[:80],
                    )
                    output, created_files = await self._run_llm_task(
                        task,
                        agent,
                        provider_id,
                        event,
                        is_admin=is_admin,
                    )
                elif not is_admin:
                    return TaskResult(
                        task_id=task.task_id, status="skipped", output="需要管理员权限"
                    )
                else:
                    output = await self.capability_builder.execute_code(
                        code=task.input,
                        event=event,
                        params=task.params,
                    )
            else:
                # LLM 任务，传递 event 以便写入文件
                output, created_files = await self._run_llm_task(
                    task,
                    agent,
                    provider_id,
                    event,
                    is_admin=is_admin,
                )

            self.bus.publish(sender, f"{task.description} 完成")
            if self.verbose_logs:
                logger.info("任务 %s 执行完成", task.task_id)
            return TaskResult(
                task_id=task.task_id, status="completed", output=output, created_files=created_files
            )
        except Exception as e:
            logger.error("任务执行失败: %s", e, exc_info=True)
            return TaskResult(task_id=task.task_id, status="failed", output="", error=str(e))

    @staticmethod
    def _is_natural_language(text: str) -> bool:
        """判断文本是否是自然语言描述（而非 shell 命令）"""
        if not text or not text.strip():
            return False

        text = text.strip()

        # 典型的 shell 命令特征
        shell_patterns = [
            r"^(pip|npm|yarn|apt|brew|cargo|go|git|docker|kubectl|curl|wget|cat|ls|cd|mkdir|cp|mv|rm|echo|find|grep|sed|awk|tar|zip|unzip)\s",
            r"^(python|python3|node|java|gcc|g\+\+|make|cmake)\s",
            r"^(sudo|nohup|chmod|chown|export|source|\.\/)",
            r"^\w+=",
            r"^\|",
            r"^#!",
        ]

        for pattern in shell_patterns:
            if re.match(pattern, text):
                return False

        has_chinese = bool(re.search(r"[\u4e00-\u9fff]", text))
        has_punctuation = bool(re.search(r"[，。！？；：、]", text))
        word_count = len(text.split())

        if has_chinese or has_punctuation:
            return True

        if word_count > 10 and not any(c in text for c in ["|", ">", "<", "&&", "||", ";"]):
            return True

        return False

    async def _run_llm_task(
        self,
        task: AgentTask,
        agent: Optional[AgentSpec],
        provider_id: str,
        event=None,
        is_admin: bool = False,
    ) -> tuple:
        """
        执行 LLM 任务，并自动提取代码写入文件系统

        Returns:
            (output_text, created_files)
        """
        prompt = task.input or task.description
        system_prompt = agent.instructions if agent else "你是一个智能助手。"

        # 强制要求 LLM 输出标准 markdown 代码块格式，确保代码可被提取
        code_format_hint = (
            "\n\n【极其重要的输出格式要求】\n"
            "如果你的回答中包含任何代码，你必须严格遵守以下格式：\n"
            "1. 每个代码文件必须使用标准 markdown 代码块格式\n"
            "2. 代码块开头必须标注语言和文件名，格式为 ```语言:文件名\n"
            "3. 示例：\n"
            "```html:index.html\n<!DOCTYPE html>\n<html>...</html>\n```\n\n"
            "```css:styles.css\nbody { margin: 0; }\n```\n\n"
            "```javascript:app.js\nconsole.log('hello');\n```\n\n"
            "```python:main.py\nprint('hello')\n```\n\n"
            '```json:app.json\n{"pages": ["pages/index/index"]}\n```\n\n'
            "4. 每个文件必须是完整的、可直接运行的代码，绝对不要省略任何部分\n"
            "5. 不要用 '...' 或 '// 省略' 代替代码\n"
            "6. 如果项目包含多个文件，每个文件都必须单独用代码块输出"
        )

        # 增强 system prompt，强调代码输出格式
        enhanced_system_prompt = (
            system_prompt + "\n\n"
            "【核心规则】当你需要输出代码时，必须使用 ```语言:文件名 格式的 markdown 代码块。"
            "每个文件都必须完整输出，不得省略。这是最重要的规则。"
        )

        prompt = prompt + code_format_hint

        shared_context = self.bus.format_messages(agent.role if agent else None)
        if shared_context:
            prompt = f"{shared_context}\n\n任务: {prompt}"

        logger.info("开始 LLM 调用: task=%s, provider=%s", task.task_id, provider_id)
        created_files = []

        try:
            response = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
                system_prompt=enhanced_system_prompt,
            )
            logger.info("LLM 调用完成: task=%s", task.task_id)
            output_text = response.completion_text

            # 记录原始输出（用于后续兜底提取）
            self._all_task_outputs.append(output_text)

            # 调试：检查代码提取条件
            should_save = self.code_extractor.should_save_code(output_text)
            # 增强检测：即使 should_save 为 False，也检查是否有代码块
            code_blocks = self.code_extractor.extract_code_blocks(output_text)
            has_any_code = len(code_blocks) > 0
            logger.info(
                "代码检测: task=%s, should_save=%s, has_any_code=%s, code_blocks=%d, has_event=%s, output_len=%d",
                task.task_id,
                should_save,
                has_any_code,
                len(code_blocks),
                event is not None,
                len(output_text),
            )

            # 放宽条件：只要有代码块且有 event 就尝试保存
            if (should_save or has_any_code) and event and is_admin:
                logger.info(
                    "检测到代码，开始提取并写入文件系统: task=%s (blocks=%d)",
                    task.task_id,
                    len(code_blocks),
                )

                # 提取代码文件
                files = self.code_extractor.extract_web_project(output_text)

                if files:
                    logger.info("提取到 %d 个文件: %s", len(files), list(files.keys()))
                    # 获取执行器
                    executor = self.capability_builder.executor
                    if executor:
                        # 生成项目名称（基于时间戳）
                        project_name = f"project_{int(time.time())}"

                        written_files = await self.artifact_service.write_files_to_workspace(
                            files=files,
                            executor=executor,
                            event=event,
                            project_name=project_name,
                            base_path="/workspace",
                        )

                        if written_files:
                            created_files = written_files
                            self.all_created_files.extend(written_files)
                            logger.info(
                                "✅ 代码已写入文件系统: task=%s, files=%s",
                                task.task_id,
                                written_files,
                            )

                            # 在输出中添加文件创建信息
                            file_list = "\n".join([f"  - {f}" for f in written_files])
                            output_text += f"\n\n📁 **已创建文件:**\n{file_list}"
                        else:
                            logger.warning(
                                "⚠️ 文件写入失败或无文件: task=%s, written=%s",
                                task.task_id,
                                written_files,
                            )
                    else:
                        logger.warning("⚠️ 执行器不可用，无法写入文件: task=%s", task.task_id)
                else:
                    logger.warning("⚠️ 代码提取结果为空: task=%s", task.task_id)
            elif (should_save or has_any_code) and event and not is_admin:
                logger.info("检测到代码，但当前不是管理员请求，跳过自动写入: task=%s", task.task_id)
                output_text += "\n\n⚠️ 当前请求不是管理员上下文，代码不会被自动写入文件系统。"

            return output_text, created_files

        except Exception as e:
            logger.error("LLM 调用失败: task=%s, error=%s", task.task_id, e, exc_info=True)
            raise

    @staticmethod
    def _strip_code_blocks(text: str) -> str:
        """
        从文本中移除代码块内容，只保留说明文字和文件信息。
        用于在回复消息中避免展示过长的代码。
        """

        # 匹配 ```...``` 代码块，替换为简短的占位符
        def replace_block(match):
            lang = match.group(1) or ""
            filename = match.group(2) or ""
            lang = lang.strip()
            filename = filename.strip()
            if filename:
                return f"📄 `{filename}` (代码已保存到文件)"
            elif lang:
                return f"📄 `{lang}` 代码块 (已保存到文件)"
            else:
                return "📄 代码块 (已保存到文件)"

        pattern = r"```[ \t]*([\w+-]+)?(?:[:：\s]([^\r\n`]+?))?[ \t]*\r?\n.*?```"
        stripped = re.sub(pattern, replace_block, text, flags=re.DOTALL)
        return stripped

    def _build_response(
        self,
        plan: TaskPlan,
        results: Dict[str, TaskResult],
        agents: List[AgentSpec],
    ) -> dict[str, Any]:
        total = len(plan.tasks)
        completed = sum(1 for r in results.values() if r.status == "completed")

        agent_names = ", ".join([agent.name for agent in agents]) or "无"
        lines = [
            f"🤖 已创建 SubAgent: {agent_names}",
            f"✅ 任务完成情况: {completed}/{total}",
            "",
        ]

        for task in plan.tasks:
            result = results.get(task.task_id)
            if not result:
                lines.append(f"⚠️ {task.description}: 未执行")
                continue
            if result.status == "completed":
                lines.append(f"✅ {task.description}")
                if result.output:
                    if self.verbose_logs:
                        lines.append(result.output)
                    else:
                        output = result.output

                        # ★ 关键修复：如果有文件被创建，移除代码块内容以缩短消息
                        if result.created_files:
                            output = self._strip_code_blocks(output)

                        # 提取并保留 "已创建文件" 部分
                        file_info_marker = "📁 **已创建文件:**"
                        file_info = ""
                        if file_info_marker in output:
                            marker_idx = output.index(file_info_marker)
                            file_info = output[marker_idx:]
                            output = output[:marker_idx]

                        # 截断过长的输出
                        if len(output) > 800:
                            output = output[:800] + "\n..."

                        lines.append(output)
                        if file_info:
                            lines.append(file_info)
                # 即使 output 为空，也显示已创建的文件
                if result.created_files:
                    file_list = "\n".join([f"  - `{f}`" for f in result.created_files])
                    lines.append(f"\n📁 **任务文件:**\n{file_list}")
            elif result.status == "skipped":
                skip_reason = result.output or "已跳过"
                lines.append(f"⏭️ {task.description}: {skip_reason}")
            else:
                lines.append(f"❌ {task.description}: {result.error or '失败'}")

        # 添加创建的文件信息汇总
        if self.all_created_files:
            lines.append("")
            lines.append("📁 **编程完成！已创建文件:**")
            for f in self.all_created_files:
                lines.append(f"  - `{f}`")
            lines.append("")
            lines.append("💡 文件已保存到沙盒的 /workspace/ 目录")
            lines.append("💡 可通过宝塔面板 → 文件 → /www/wwwroot/downloads/ 下载")
        else:
            # 没有文件被创建时给出提示
            lines.append("")
            lines.append("⚠️ 注意：本次任务未检测到需要保存的代码文件")
            lines.append("💡 如需生成代码文件，请明确要求「帮我写一个xxx程序」")

        return {
            "status": "success" if completed == total else "partial",
            "answer": "\n".join(lines),
            "created_files": self.all_created_files.copy(),
            "_all_task_outputs": self._all_task_outputs.copy(),
        }
