"""astrbot.core.skills.skill_manager 测试桩，对齐 v4.25.5 构造与查询接口。

实现一个可工作的最小子集：扫描 skills_root 下含 SKILL.md 的目录，
启用状态保存在 data/skills.json。
"""

from dataclasses import dataclass
import json
import os
from pathlib import Path

from astrbot.core.utils.astrbot_path import (
    get_astrbot_data_path,
    get_astrbot_plugin_path,
    get_astrbot_skills_path,
)

SKILLS_CONFIG_FILENAME = "skills.json"
DEFAULT_SKILLS_CONFIG: dict[str, dict] = {"skills": {}}


@dataclass
class SkillInfo:
    name: str
    description: str
    path: str
    active: bool = True
    source: str = "local"


class SkillManager:
    def __init__(
        self,
        skills_root: str | None = None,
        plugins_root: str | None = None,
    ) -> None:
        self.skills_root = skills_root or get_astrbot_skills_path()
        self.plugins_root = plugins_root or get_astrbot_plugin_path()
        data_path = Path(get_astrbot_data_path())
        self.config_path = str(data_path / SKILLS_CONFIG_FILENAME)

    def _load_config(self) -> dict:
        if not os.path.exists(self.config_path):
            return json.loads(json.dumps(DEFAULT_SKILLS_CONFIG))
        with open(self.config_path, encoding="utf-8") as f:
            return json.load(f)

    def _save_config(self, config: dict) -> None:
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)

    @staticmethod
    def _read_description(skill_md: Path) -> str:
        try:
            for line in skill_md.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("description:"):
                    return stripped.split(":", 1)[1].strip()
            return ""
        except OSError:
            return ""

    def list_skills(
        self,
        *,
        active_only: bool = False,
        runtime: str = "local",
        show_sandbox_path: bool = True,
    ) -> list[SkillInfo]:
        skills_root = Path(self.skills_root)
        if not skills_root.exists():
            return []

        config = self._load_config()
        states = config.get("skills", {})

        skills: list[SkillInfo] = []
        for entry in sorted(skills_root.iterdir()):
            if not entry.is_dir():
                continue
            skill_md = entry / "SKILL.md"
            if not skill_md.exists():
                skill_md = entry / "skill.md"
            if not skill_md.exists():
                continue
            active = bool(states.get(entry.name, {}).get("active", True))
            if active_only and not active:
                continue
            skills.append(
                SkillInfo(
                    name=entry.name,
                    description=self._read_description(skill_md),
                    path=str(entry),
                    active=active,
                )
            )
        return skills

    def set_skill_active(self, name: str, active: bool) -> None:
        config = self._load_config()
        config.setdefault("skills", {})
        config["skills"][name] = {"active": bool(active)}
        self._save_config(config)
