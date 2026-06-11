"""Skill 能力的 FunctionTool 封装（复用 autonomous/skill_creator.py）。"""

from __future__ import annotations

from typing import Any

from .base import OrchestratorTool, obj_schema, str_prop


class SkillListTool(OrchestratorTool):
    requires_admin = False

    def __init__(self, runtime: Any) -> None:
        super().__init__(
            runtime,
            name="skill_list",
            description="列出 AstrBot 中已安装的全部 Skill 及启用状态。",
            parameters=obj_schema({}),
        )

    async def run(self, event: Any) -> str:
        return self.runtime.skill_tool.list_skills()


class SkillReadTool(OrchestratorTool):
    requires_admin = False

    def __init__(self, runtime: Any) -> None:
        super().__init__(
            runtime,
            name="skill_read",
            description="读取指定 Skill 的 SKILL.md 内容。",
            parameters=obj_schema(
                {"name": str_prop("Skill 名称")},
                required=["name"],
            ),
        )

    async def run(self, event: Any, name: str) -> str:
        return self.runtime.skill_tool.read_skill(name)


class SkillCreateTool(OrchestratorTool):
    def __init__(self, runtime: Any) -> None:
        super().__init__(
            runtime,
            name="skill_create",
            description=(
                "创建一个新的 AstrBot Skill 并自动激活（管理员）。"
                "content 为 SKILL.md 正文（markdown），description 为一句话功能描述。"
            ),
            parameters=obj_schema(
                {
                    "name": str_prop("Skill 名称（英文小写下划线）"),
                    "description": str_prop("一句话功能描述，写入 frontmatter"),
                    "content": str_prop("SKILL.md 正文内容（markdown，不含 frontmatter）"),
                },
                required=["name", "description", "content"],
            ),
        )

    async def run(self, event: Any, name: str, description: str, content: str) -> str:
        if denied := self.check_permission(event):
            return denied
        return await self.runtime.skill_tool.create_skill(name, description, content)


class SkillDeleteTool(OrchestratorTool):
    def __init__(self, runtime: Any) -> None:
        super().__init__(
            runtime,
            name="skill_delete",
            description="删除指定的 AstrBot Skill（管理员）。",
            parameters=obj_schema(
                {"name": str_prop("要删除的 Skill 名称")},
                required=["name"],
            ),
        )

    async def run(self, event: Any, name: str) -> str:
        if denied := self.check_permission(event):
            return denied
        return self.runtime.skill_tool.delete_skill(name)
