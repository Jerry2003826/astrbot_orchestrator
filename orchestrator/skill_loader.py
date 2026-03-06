"""
AstrBot Skill 加载器

读取 AstrBot 原生的 Skill 系统（基于 SKILL.md）
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)


class AstrBotSkillLoader:
    """
    AstrBot Skill 加载器
    
    通过 AstrBot 的 SkillManager 读取已注册的 Skills
    """
    
    def __init__(self, context: Any) -> None:
        """
        初始化
        
        Args:
            context: AstrBot Context 对象
        """
        self.context = context
        self._skill_manager: Any | None = None
        self._skills_cache: list[dict[str, Any]] = []
        self._cache_valid = False
    
    def _get_skill_manager(self) -> Any | None:
        """获取 AstrBot 的 SkillManager"""
        if self._skill_manager is None:
            try:
                from astrbot.core.skills import SkillManager
                self._skill_manager = SkillManager()
            except ImportError:
                logger.warning("无法导入 SkillManager，Skill 功能不可用")
        return self._skill_manager
    
    def list_skills(self, active_only: bool = True) -> list[dict[str, Any]]:
        """
        列出所有可用的 Skills
        
        Args:
            active_only: 是否只返回激活的 Skills
        
        Returns:
            Skills 列表
        """
        if self._cache_valid:
            if active_only:
                return [s for s in self._skills_cache if s.get("active", True)]
            return self._skills_cache
        
        skills: list[dict[str, Any]] = []
        
        skill_manager = self._get_skill_manager()
        if skill_manager:
            try:
                skill_infos = skill_manager.list_skills(active_only=active_only)
                for info in skill_infos:
                    skills.append({
                        "name": info.name,
                        "description": info.description,
                        "path": info.path,
                        "active": info.active,
                        "type": "astrbot_skill"
                    })
            except Exception as e:
                logger.error(f"读取 Skills 失败: {e}")
        
        self._skills_cache = skills
        self._cache_valid = True
        
        return skills
    
    def get_skill(self, name: str) -> dict[str, Any] | None:
        """获取指定 Skill"""
        skills = self.list_skills(active_only=False)
        for skill in skills:
            if skill["name"] == name:
                return skill
        return None
    
    def get_skill_content(self, name: str) -> str | None:
        """
        获取 Skill 的 SKILL.md 内容
        
        Args:
            name: Skill 名称
        
        Returns:
            SKILL.md 文件内容
        """
        skill = self.get_skill(name)
        if not skill:
            return None
        
        skill_path = Path(skill["path"])
        skill_md = skill_path / "SKILL.md"
        
        if not skill_md.exists():
            # 尝试小写
            skill_md = skill_path / "skill.md"
        
        if skill_md.exists():
            try:
                return skill_md.read_text(encoding="utf-8")
            except Exception as e:
                logger.error(f"读取 SKILL.md 失败: {e}")
        
        return None
    
    def build_skills_prompt(self) -> str:
        """
        构建 Skills 提示词（供 LLM 使用）
        
        Returns:
            Skills 描述的提示词
        """
        skills = self.list_skills(active_only=True)
        
        if not skills:
            return ""
        
        # 使用 AstrBot 原生的 prompt 构建
        try:
            from astrbot.core.skills.skill_manager import SkillInfo, build_skills_prompt
            
            skill_infos = [
                SkillInfo(
                    name=s["name"],
                    description=s["description"],
                    path=s["path"],
                    active=s["active"]
                )
                for s in skills
            ]
            return cast(str, build_skills_prompt(skill_infos))
        except ImportError:
            # 备用实现
            lines = ["## 可用技能"]
            for skill in skills:
                lines.append(f"- **{skill['name']}**: {skill['description']}")
            return "\n".join(lines)
    
    def invalidate_cache(self) -> None:
        """使缓存失效"""
        self._cache_valid = False
        self._skills_cache = []
