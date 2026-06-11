"""/agent 指令的官方化执行器。

薄封装：组装 ToolSet（本插件工具 + 宿主已注册工具 + 官方 subagent handoffs），
调用 ``context.tool_loop_agent`` 完成任务，再把 ArtifactService 提取到的
代码产物落盘并附在回复中。不再有自研规划/协调循环。
"""

from __future__ import annotations

import asyncio
from typing import Any

from astrbot.api import ToolSet, logger

ORCHESTRATOR_SYSTEM_PROMPT = (
    "你是 AstrBot 的全自主编排 Agent，可以通过工具完成以下任务：\n"
    "- 搜索/安装/卸载/更新插件（plugin_*）\n"
    "- 创建/读取/删除 Skill（skill_*）\n"
    "- 配置和测试 MCP 服务器（mcp_*）\n"
    "- 在受控环境执行 Python/Shell 代码、读写文件、安装依赖（sandbox_*）\n"
    "- 查看系统状态与最近错误（debug_*）\n"
    "- 运行 YAML 工作流（workflow_*）\n"
    "- 通过 transfer_to_<agent> 工具把子任务移交给专职子代理\n\n"
    "工作准则：\n"
    "1. 先理解任务，再选择最少且最直接的工具组合，不要重复调用同一工具做同一件事。\n"
    "2. 生成代码文件时使用 ```语言:文件名 格式的代码块，内容必须完整可运行。\n"
    "3. 工具返回 permission denied 时如实告知用户该操作需要管理员权限，不要重试。\n"
    "4. 任务完成后用简洁中文总结做了什么、产出了什么。"
)


class AgentRunner:
    """用 tool_loop_agent 执行 /agent 任务的薄层。"""

    def __init__(
        self,
        context: Any,
        config: Any,
        tools: list[Any] | None = None,
        artifact_service: Any | None = None,
    ) -> None:
        self.context = context
        self.config = config
        self.tools = list(tools or [])
        self.artifact_service = artifact_service

    async def resolve_provider_id(self, event: Any) -> str | None:
        """解析任务使用的 chat provider ID：插件配置优先，否则跟随会话。"""

        configured = str(self.config.get("llm_provider") or "").strip()
        if configured:
            return configured
        try:
            return await self.context.get_current_chat_provider_id(umo=event.unified_msg_origin)
        except Exception:
            logger.warning("无法解析会话当前的 chat provider", exc_info=True)
            return None

    def build_toolset(self) -> ToolSet:
        """本插件工具 + 官方 subagent handoff 工具。"""

        toolset = ToolSet()
        for tool in self.tools:
            toolset.add_tool(tool)

        orchestrator = getattr(self.context, "subagent_orchestrator", None)
        for handoff in getattr(orchestrator, "handoffs", None) or []:
            try:
                toolset.add_tool(handoff)
            except Exception:
                logger.debug("添加 handoff 工具失败: %s", handoff, exc_info=True)
        return toolset

    async def run(self, event: Any, task: str) -> str:
        """执行任务并返回最终回复文本。"""

        provider_id = await self.resolve_provider_id(event)
        if not provider_id:
            return "未找到可用的 LLM 提供商，请在插件配置中指定 llm_provider 或为会话配置聊天模型。"

        toolset = self.build_toolset()
        max_steps = int(self.config.get("max_iterations", 10) or 10)
        timeout = int(self.config.get("task_timeout", 120) or 120)

        try:
            llm_resp = await asyncio.wait_for(
                self.context.tool_loop_agent(
                    event=event,
                    chat_provider_id=provider_id,
                    prompt=task,
                    system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
                    tools=toolset,
                    max_steps=max_steps,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return f"任务执行超时（{timeout}s），已中止。可在插件配置中调整 task_timeout。"

        completion = (getattr(llm_resp, "completion_text", "") or "").strip()
        if not completion:
            completion = "任务已执行完成，但模型未返回文本结果。"

        artifact_note = self._persist_artifacts(completion)
        if artifact_note:
            completion = f"{completion}\n\n{artifact_note}"
        return completion

    def _persist_artifacts(self, text: str) -> str:
        """从回复中提取 ```lang:filename 代码块并落盘，返回产物摘要。"""

        service = self.artifact_service
        if service is None:
            return ""
        try:
            files = service.extract_files_from_text(text)
            if not files:
                return ""
            saved = service.persist_files(files, "agent_task")
            names = saved.get("saved_files") or []
            if not names:
                return ""
            lines = [f"已保存 {len(names)} 个产物文件到 {saved.get('path', '')}："]
            lines.extend(f"- {name}" for name in names)
            return "\n".join(lines)
        except Exception:
            logger.warning("产物落盘失败", exc_info=True)
            return ""
