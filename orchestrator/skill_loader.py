"""AstrBot Skill 加载器。

收敛到 4.25.5 官方 API：``astrbot.core.skills.skill_manager.SkillManager``
（纯文件系统实现，默认指向 data/skills）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from astrbot.api import logger


class AstrBotSkillLoader:
    """读取 AstrBot 原生 Skill 系统（基于 SKILL.md）。"""

    def __init__(self, context: Any) -> None:
        self.context = context
        self._skill_manager: Any | None = None

    def _get_skill_manager(self) -> Any | None:
        """获取官方 SkillManager（懒加载单例）。"""

        if self._skill_manager is None:
            try:
                from astrbot.core.skills.skill_manager import SkillManager

                self._skill_manager = SkillManager()
            except ImportError:
                logger.warning("无法导入 SkillManager，Skill 功能不可用")
        return self._skill_manager

    def list_skills(self, active_only: bool = True) -> list[dict[str, Any]]:
        """列出 Skills（dict 形态，便于上层渲染）。"""

        sm = self._get_skill_manager()
        if sm is None:
            return []

        try:
            infos = sm.list_skills(active_only=active_only)
        except Exception as exc:
            logger.error("读取 Skills 失败: %s", exc)
            return []

        skills = [
            {
                "name": info.name,
                "description": info.description,
                "path": info.path,
                "active": info.active,
                "type": "astrbot_skill",
            }
            for info in infos
        ]
        logger.debug("共发现 %d 个 Skills", len(skills))
        return skills

    def get_skill(self, name: str) -> dict[str, Any] | None:
        """获取指定 Skill。"""

        for skill in self.list_skills(active_only=False):
            if skill["name"] == name:
                return skill
        return None

    def get_skill_content(self, name: str) -> str | None:
        """获取 Skill 的 SKILL.md 内容。"""

        skill = self.get_skill(name)
        if not skill:
            return None

        skill_path = Path(skill["path"])
        for filename in ("SKILL.md", "skill.md"):
            skill_md = skill_path / filename
            if skill_md.exists():
                try:
                    return skill_md.read_text(encoding="utf-8")
                except Exception as exc:
                    logger.error("读取 SKILL.md 失败: %s", exc)
                    return None
        return None

    def build_skills_prompt(self) -> str:
        """构建 Skills 提示词（优先官方实现）。"""

        sm = self._get_skill_manager()
        if sm is None:
            return ""

        try:
            from astrbot.core.skills.skill_manager import build_skills_prompt

            infos = sm.list_skills(active_only=True)
            return str(build_skills_prompt(infos)) if infos else ""
        except Exception:
            skills = self.list_skills(active_only=True)
            if not skills:
                return ""
            lines = ["## 可用技能"]
            lines.extend(f"- **{s['name']}**: {s['description']}" for s in skills)
            return "\n".join(lines)

    def invalidate_cache(self) -> None:
        """兼容旧接口：官方 SkillManager 即时读盘，无缓存可失效。"""
