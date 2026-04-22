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

    通过多种方式尝试获取 AstrBot 已注册的 Skills
    支持不同版本的 API 访问方式
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
        """
        获取 AstrBot 的 SkillManager

        尝试多种方式获取，确保版本兼容性：
        1. 从 context 直接获取
        2. 从 provider_manager 获取
        3. 通过导入获取
        """
        if self._skill_manager is not None:
            return self._skill_manager

        # 方法1: 从 context 直接获取
        if hasattr(self.context, "skill_manager"):
            try:
                manager = self.context.skill_manager
                if manager:
                    logger.debug("通过 context.skill_manager 获取 SkillManager")
                    self._skill_manager = manager
                    return manager
            except Exception as e:
                logger.debug(f"context.skill_manager 失败: {e}")

        # 方法2: 从 provider_manager 获取
        if hasattr(self.context, "provider_manager"):
            try:
                provider_mgr = self.context.provider_manager
                if hasattr(provider_mgr, "skill_manager"):
                    manager = provider_mgr.skill_manager
                    if manager:
                        logger.debug("通过 provider_manager.skill_manager 获取 SkillManager")
                        self._skill_manager = manager
                        return manager
            except Exception as e:
                logger.debug(f"provider_manager.skill_manager 失败: {e}")

        # 方法3: 尝试不同的导入路径
        import_paths = [
            ("astrbot.core.skills.skill_manager", "SkillManager"),
            ("astrbot.core.skills", "SkillManager"),
            ("astrbot.skills", "SkillManager"),
            ("astrbot.core.skill_manager", "SkillManager"),
        ]

        for module_path, class_name in import_paths:
            try:
                module = __import__(module_path, fromlist=[class_name])
                SkillManagerClass = getattr(module, class_name, None)

                if SkillManagerClass:
                    # 检查构造函数参数
                    import inspect

                    sig = inspect.signature(SkillManagerClass.__init__)
                    params = list(sig.parameters.keys())

                    # 根据参数决定如何实例化
                    if "context" in params:
                        manager = SkillManagerClass(self.context)
                    elif "data_dir" in params or "skills_dir" in params:
                        # 尝试获取 skills 目录
                        skills_dir = self._get_skills_directory()
                        manager = SkillManagerClass(skills_dir)
                    else:
                        manager = SkillManagerClass()

                    if manager:
                        logger.debug(f"通过 {module_path} 导入并实例化 SkillManager")
                        self._skill_manager = manager
                        return manager

            except ImportError as e:
                logger.debug(f"导入 {module_path} 失败: {e}")
            except Exception as e:
                logger.debug(f"实例化 {module_path}.{class_name} 失败: {e}")

        logger.warning("无法导入 SkillManager，Skill 功能可能不可用")
        return None

    def _get_skills_directory(self) -> Path | None:
        """
        获取 AstrBot 的 Skills 目录

        Returns:
            Skills 目录路径
        """
        # 尝试从配置获取
        if hasattr(self.context, "get_config"):
            try:
                config = self.context.get_config()
                if config and "skills_dir" in config:
                    return Path(config["skills_dir"])
            except Exception:
                pass

        # 尝试常见路径 (按优先级检查)
        import os

        possible_paths: list[Path] = []
        env_root = os.environ.get("ASTRBOT_DATA_DIR") or os.environ.get("ASTRBOT_ROOT")
        if env_root:
            possible_paths.append(Path(env_root) / "skills")
        possible_paths.extend(
            [
                Path.cwd() / "data" / "skills",
                Path("data/skills"),
                Path("skills"),
                Path("/AstrBot/data/skills"),  # 官方 Docker 镜像回退
            ]
        )

        for p in possible_paths:
            if p.exists():
                return p

        return None

    def _extract_skill_info(self, skill_obj: Any) -> dict[str, Any] | None:
        """
        从 Skill 对象提取信息

        Args:
            skill_obj: Skill 对象（可能是 dataclass、dict 或其他类型）

        Returns:
            Skill 信息字典，如果提取失败返回 None
        """
        try:
            # 尝试属性访问
            name = getattr(skill_obj, "name", None)
            if name is None:
                # 尝试 dict 方式
                if isinstance(skill_obj, dict):
                    name = skill_obj.get("name")
                else:
                    # 尝试 __dict__
                    name = getattr(skill_obj, "__dict__", {}).get("name")

            if not name:
                return None

            description = (
                getattr(skill_obj, "description", None)
                or (skill_obj.get("description") if isinstance(skill_obj, dict) else None)
                or getattr(skill_obj, "__dict__", {}).get("description", "")
            )

            path = (
                getattr(skill_obj, "path", None)
                or (skill_obj.get("path") if isinstance(skill_obj, dict) else None)
                or getattr(skill_obj, "__dict__", {}).get("path", "")
            )

            active_val = getattr(skill_obj, "active", None)
            if active_val is None and isinstance(skill_obj, dict):
                active_val = skill_obj.get("active", None)
            if active_val is None:
                active_val = getattr(skill_obj, "__dict__", {}).get("active", True)
            active = active_val if active_val is not None else True

            return {
                "name": str(name),
                "description": str(description or ""),
                "path": str(path or ""),
                "active": bool(active),
                "type": "astrbot_skill",
            }

        except Exception as e:
            logger.debug(f"提取 Skill 信息失败: {e}")
            return None

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
            # 尝试不同的方法名获取 Skills 列表
            method_names = [
                "list_skills",
                "get_skills",
                "get_all_skills",
                "get_skill_list",
                "skills",
            ]

            skill_infos = None
            for method_name in method_names:
                if hasattr(skill_manager, method_name):
                    try:
                        method = getattr(skill_manager, method_name)
                        if callable(method):
                            # 检查是否接受参数
                            import inspect

                            sig = inspect.signature(method)
                            if "active_only" in sig.parameters:
                                skill_infos = method(active_only=active_only)
                            else:
                                skill_infos = method()

                            logger.debug(f"通过 {method_name}() 获取到 Skills")
                            break
                    except Exception as e:
                        logger.error(f"读取 Skills 失败: {e}")

            # 如果方法调用成功，解析结果
            if skill_infos:
                # 可能是列表、生成器或其他可迭代对象
                if not isinstance(skill_infos, (list, tuple)):
                    try:
                        skill_infos = list(skill_infos)
                    except Exception:
                        skill_infos = []

                for info in skill_infos:
                    skill_data = self._extract_skill_info(info)
                    if skill_data:
                        skills.append(skill_data)

        # 如果通过 SkillManager 获取失败，尝试直接扫描目录
        if not skills:
            skills = self._scan_skills_directory()

        self._skills_cache = skills
        self._cache_valid = True

        logger.info(f"共发现 {len(skills)} 个 Skills")

        if active_only:
            return [s for s in skills if s.get("active", True)]
        return skills

    def _scan_skills_directory(self) -> list[dict[str, Any]]:
        """
        直接扫描 Skills 目录

        Returns:
            Skills 列表
        """
        skills: list[dict[str, Any]] = []
        skills_dir = self._get_skills_directory()

        if not skills_dir or not skills_dir.exists():
            logger.debug("Skills 目录不存在或无法访问")
            return skills

        try:
            for skill_path in skills_dir.iterdir():
                if not skill_path.is_dir():
                    continue

                skill_md = skill_path / "SKILL.md"
                if not skill_md.exists():
                    skill_md = skill_path / "skill.md"

                if skill_md.exists():
                    # 从 SKILL.md 提取基本信息
                    description = ""
                    try:
                        content = skill_md.read_text(encoding="utf-8")
                        # 尝试提取第一行作为描述
                        first_line = content.split("\n")[0] if content else ""
                        description = first_line.lstrip("#").strip()
                    except Exception:
                        pass

                    skills.append(
                        {
                            "name": skill_path.name,
                            "description": description or f"Skill: {skill_path.name}",
                            "path": str(skill_path),
                            "active": True,
                            "type": "astrbot_skill",
                        }
                    )

            logger.debug(f"通过目录扫描发现 {len(skills)} 个 Skills")

        except Exception as e:
            logger.warning(f"扫描 Skills 目录失败: {e}")

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

        # 尝试使用 AstrBot 原生的 prompt 构建
        try:
            # 尝试导入 SkillInfo 和 build_skills_prompt
            import_paths = [
                "astrbot.core.skills.skill_manager",
                "astrbot.core.skills",
            ]

            for module_path in import_paths:
                try:
                    module = __import__(module_path, fromlist=["SkillInfo", "build_skills_prompt"])
                    SkillInfo = getattr(module, "SkillInfo", None)
                    build_prompt_func = getattr(module, "build_skills_prompt", None)

                    if SkillInfo and build_prompt_func:
                        skill_infos = [
                            SkillInfo(
                                name=s["name"],
                                description=s["description"],
                                path=s["path"],
                                active=s["active"],
                            )
                            for s in skills
                        ]
                        return cast(str, build_prompt_func(skill_infos))
                except Exception:
                    continue

        except Exception:
            pass

        # 备用实现
        lines = ["## 可用技能"]
        for skill in skills:
            lines.append(f"- **{skill['name']}**: {skill['description']}")
        return "\n".join(lines)

    def invalidate_cache(self) -> None:
        """使缓存失效"""
        self._cache_valid = False
        self._skills_cache = []
