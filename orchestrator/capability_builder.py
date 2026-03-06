"""
SubAgent 能力构建器
"""

from __future__ import annotations

import logging
from typing import Any, cast

logger = logging.getLogger(__name__)


class AgentCapabilityBuilder:
    """封装 Skill/MCP/沙盒能力"""

    def __init__(
        self,
        context: Any,
        skill_tool: Any | None = None,
        mcp_tool: Any | None = None,
        executor: Any | None = None,
    ) -> None:
        """保存能力工具实例。"""

        self.context = context
        self.skill_tool = skill_tool
        self.mcp_tool = mcp_tool
        self.executor = executor

    async def build_skill(self, task_description: str, provider_id: str) -> str:
        """根据描述自动生成并创建 Skill。"""

        if not self.skill_tool:
            return "❌ Skill 管理工具不可用"

        name = "auto_skill"
        description = task_description[:100]

        content = await self.skill_tool.generate_skill_from_description(
            name=name,
            user_description=task_description,
            provider_id=provider_id,
        )

        created_skill = await self.skill_tool.create_skill(
            name=name,
            description=description,
            content=content,
        )
        return cast(str, created_skill)

    async def configure_mcp(
        self,
        task_description: str,
        provider_id: str,
        params: dict[str, Any] | None = None,
    ) -> str:
        """根据参数或描述配置 MCP 服务。"""

        if not self.mcp_tool:
            return "❌ MCP 配置工具不可用"

        params = params or {}
        name = params.get("name")
        url = params.get("url")
        transport = params.get("transport", "sse")
        headers = params.get("headers")

        if name and url:
            added_server = await self.mcp_tool.add_server(
                name=name,
                url=url,
                transport=transport,
                headers=headers,
            )
            return cast(str, added_server)

        generated_mcp = await self.mcp_tool.create_mcp_from_description(
            name=name or "auto_mcp",
            user_description=task_description,
            provider_id=provider_id,
        )
        return cast(str, generated_mcp)

    async def execute_code(
        self,
        code: str,
        event: Any,
        params: dict[str, Any] | None = None,
    ) -> str:
        """使用执行器运行代码或命令。"""

        if not self.executor:
            return "❌ 执行器不可用"
        params = params or {}
        code_type = params.get("type", "shell")
        execution_result = await self.executor.auto_execute(
            code=code,
            event=event,
            code_type=code_type,
        )
        return cast(str, execution_result)
