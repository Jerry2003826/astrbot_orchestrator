"""AstrBotSkillLoader（官方 SkillManager 单一路径）测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from astrbot_orchestrator_v5.orchestrator.skill_loader import AstrBotSkillLoader


class FakeSkillManager:
    def __init__(self, infos: list[Any] | None = None, error: Exception | None = None) -> None:
        self.infos = infos or []
        self.error = error
        self.calls: list[bool] = []

    def list_skills(self, active_only: bool = False) -> list[Any]:
        if self.error is not None:
            raise self.error
        self.calls.append(active_only)
        return list(self.infos)


def make_loader(manager: Any) -> AstrBotSkillLoader:
    loader = AstrBotSkillLoader(context=SimpleNamespace())
    loader._skill_manager = manager
    return loader


def make_info(name: str, active: bool = True, path: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        description=f"desc-{name}",
        path=path or f"/skills/{name}",
        active=active,
    )


def test_list_skills_converts_official_infos() -> None:
    manager = FakeSkillManager([make_info("s1"), make_info("s2", active=False)])
    loader = make_loader(manager)

    skills = loader.list_skills(active_only=False)

    assert [s["name"] for s in skills] == ["s1", "s2"]
    assert skills[0]["type"] == "astrbot_skill"
    assert manager.calls == [False]

    loader.list_skills(active_only=True)
    assert manager.calls == [False, True]


def test_list_skills_handles_manager_errors() -> None:
    loader = make_loader(FakeSkillManager(error=RuntimeError("boom")))

    assert loader.list_skills() == []


def test_list_skills_handles_missing_manager() -> None:
    loader = AstrBotSkillLoader(context=SimpleNamespace())
    loader._get_skill_manager = lambda: None  # type: ignore[method-assign]

    assert loader.list_skills() == []


def test_get_skill_finds_by_name() -> None:
    loader = make_loader(FakeSkillManager([make_info("s1")]))

    assert loader.get_skill("s1")["description"] == "desc-s1"
    assert loader.get_skill("missing") is None


def test_get_skill_content_reads_skill_md(tmp_path: Path) -> None:
    skill_dir = tmp_path / "s1"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# hello", encoding="utf-8")

    loader = make_loader(FakeSkillManager([make_info("s1", path=str(skill_dir))]))

    assert loader.get_skill_content("s1") == "# hello"
    assert loader.get_skill_content("missing") is None


def test_get_skill_content_falls_back_to_lowercase(tmp_path: Path) -> None:
    skill_dir = tmp_path / "s1"
    skill_dir.mkdir()
    (skill_dir / "skill.md").write_text("# lower", encoding="utf-8")

    loader = make_loader(FakeSkillManager([make_info("s1", path=str(skill_dir))]))

    assert loader.get_skill_content("s1") == "# lower"


def test_build_skills_prompt_uses_official_builder_when_available() -> None:
    infos = [make_info("s1")]
    loader = make_loader(FakeSkillManager(infos))

    prompt = loader.build_skills_prompt()

    # stub 提供官方 build_skills_prompt 时输出官方格式，否则回退列表;
    # 两种情况都必须包含技能名。
    assert "s1" in prompt


def test_build_skills_prompt_empty_when_no_skills() -> None:
    loader = make_loader(FakeSkillManager([]))

    assert loader.build_skills_prompt() == ""


@pytest.mark.parametrize("name", ["invalidate_cache"])
def test_legacy_interface_kept(name: str) -> None:
    loader = make_loader(FakeSkillManager([]))

    getattr(loader, name)()
