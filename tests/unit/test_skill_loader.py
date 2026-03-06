"""AstrBotSkillLoader 单元测试。"""

from __future__ import annotations

import builtins
import logging
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from astrbot_orchestrator_v5.orchestrator.skill_loader import AstrBotSkillLoader

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture
    from _pytest.fixtures import FixtureRequest
    from _pytest.logging import LogCaptureFixture
    from _pytest.monkeypatch import MonkeyPatch
    from pytest_mock.plugin import MockerFixture

    _PYTEST_TYPE_IMPORTS = (
        CaptureFixture,
        FixtureRequest,
        LogCaptureFixture,
        MonkeyPatch,
        MockerFixture,
    )


class FakeSkillManager:
    """SkillManager 替身。"""

    def __init__(
        self,
        infos: list[SimpleNamespace] | None = None,
        error: Exception | None = None,
    ) -> None:
        """初始化技能列表与异常行为。"""

        self.infos = infos or []
        self.error = error
        self.calls: list[bool] = []

    def list_skills(self, active_only: bool = True) -> list[SimpleNamespace]:
        """返回模拟技能列表。"""

        self.calls.append(active_only)
        if self.error is not None:
            raise self.error
        if active_only:
            return [info for info in self.infos if info.active]
        return list(self.infos)


class FakeSkillInfo:
    """Prompt 构建时使用的 SkillInfo 替身。"""

    def __init__(self, name: str, description: str, path: str, active: bool) -> None:
        """保存技能信息。"""

        self.name = name
        self.description = description
        self.path = path
        self.active = active


def install_fake_skill_modules(
    monkeypatch: pytest.MonkeyPatch,
    skill_manager_class: type[FakeSkillManager],
) -> None:
    """安装伪造的 astrbot skill 模块。"""

    astrbot_module = ModuleType("astrbot")
    core_module = ModuleType("astrbot.core")
    skills_module = ModuleType("astrbot.core.skills")
    skill_manager_module = ModuleType("astrbot.core.skills.skill_manager")

    def build_skills_prompt(skill_infos: list[FakeSkillInfo]) -> str:
        """构建测试用 prompt。"""

        names = ",".join(info.name for info in skill_infos)
        return f"PROMPT:{names}"

    setattr(skills_module, "SkillManager", skill_manager_class)
    setattr(skill_manager_module, "SkillInfo", FakeSkillInfo)
    setattr(skill_manager_module, "build_skills_prompt", build_skills_prompt)
    setattr(astrbot_module, "core", core_module)
    setattr(core_module, "skills", skills_module)

    monkeypatch.setitem(sys.modules, "astrbot", astrbot_module)
    monkeypatch.setitem(sys.modules, "astrbot.core", core_module)
    monkeypatch.setitem(sys.modules, "astrbot.core.skills", skills_module)
    monkeypatch.setitem(
        sys.modules,
        "astrbot.core.skills.skill_manager",
        skill_manager_module,
    )


def test_skill_loader_get_skill_manager_caches_success_and_logs_import_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SkillManager 应支持成功缓存与导入失败告警。"""

    install_fake_skill_modules(monkeypatch, FakeSkillManager)
    loader = AstrBotSkillLoader(context=object())

    first_manager = loader._get_skill_manager()
    second_manager = loader._get_skill_manager()

    assert isinstance(first_manager, FakeSkillManager)
    assert second_manager is first_manager

    original_import = builtins.__import__

    def fake_import(
        name: str,
        globals_dict: dict[str, Any] | None = None,
        locals_dict: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        """拦截 astrbot.core.skills 导入失败场景。"""

        if name == "astrbot.core.skills":
            raise ImportError("boom")
        return original_import(name, globals_dict, locals_dict, fromlist, level)

    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    failing_loader = AstrBotSkillLoader(context=object())

    assert failing_loader._get_skill_manager() is None
    assert failing_loader.list_skills() == []
    assert "无法导入 SkillManager" in caplog.text


def test_skill_loader_list_get_and_invalidate_cache_cover_success_and_error_paths(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """技能列表应覆盖缓存、过滤、查询、失效与异常路径。"""

    infos = [
        SimpleNamespace(
            name="alpha",
            description="active skill",
            path="/tmp/alpha",
            active=True,
        ),
        SimpleNamespace(
            name="beta",
            description="inactive skill",
            path="/tmp/beta",
            active=False,
        ),
    ]
    skill_manager = FakeSkillManager(infos=infos)
    loader = AstrBotSkillLoader(context=object())
    monkeypatch.setattr(loader, "_get_skill_manager", lambda: skill_manager)

    all_skills = loader.list_skills(active_only=False)
    active_skills = loader.list_skills(active_only=True)

    assert skill_manager.calls == [False]
    assert [skill["name"] for skill in all_skills] == ["alpha", "beta"]
    assert [skill["name"] for skill in active_skills] == ["alpha"]
    assert loader.get_skill("beta") == {
        "name": "beta",
        "description": "inactive skill",
        "path": "/tmp/beta",
        "active": False,
        "type": "astrbot_skill",
    }
    assert loader.get_skill("missing") is None

    loader.invalidate_cache()
    loader.list_skills(active_only=True)
    assert skill_manager.calls == [False, True]

    caplog.set_level(logging.ERROR)
    error_loader = AstrBotSkillLoader(context=object())
    error_manager = FakeSkillManager(error=RuntimeError("broken"))
    monkeypatch.setattr(error_loader, "_get_skill_manager", lambda: error_manager)

    assert error_loader.list_skills() == []
    assert "读取 Skills 失败: broken" in caplog.text


def test_skill_loader_get_skill_content_supports_uppercase_lowercase_missing_and_read_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """读取 Skill 内容时应覆盖大小写文件名、缺失与读取失败。"""

    upper_dir = tmp_path / "upper"
    upper_dir.mkdir()
    upper_file = upper_dir / "SKILL.md"
    upper_file.write_text("UPPER", encoding="utf-8")

    lower_dir = tmp_path / "lower"
    lower_dir.mkdir()
    (lower_dir / "skill.md").write_text("LOWER", encoding="utf-8")

    missing_dir = tmp_path / "missing"
    missing_dir.mkdir()

    broken_dir = tmp_path / "broken"
    broken_dir.mkdir()
    broken_file = broken_dir / "SKILL.md"
    broken_file.write_text("BROKEN", encoding="utf-8")

    skill_paths = {
        "upper": {"path": str(upper_dir)},
        "lower": {"path": str(lower_dir)},
        "missing": {"path": str(missing_dir)},
        "broken": {"path": str(broken_dir)},
    }
    loader = AstrBotSkillLoader(context=object())
    monkeypatch.setattr(loader, "get_skill", lambda name: skill_paths.get(name))

    assert loader.get_skill_content("upper") == "UPPER"
    assert loader.get_skill_content("lower") == "LOWER"
    assert loader.get_skill_content("missing") is None
    assert loader.get_skill_content("unknown") is None

    original_read_text = Path.read_text

    def fake_read_text(self: Path, encoding: str = "utf-8") -> str:
        """针对特定文件模拟读取失败。"""

        if self == broken_file:
            raise OSError("cannot read")
        return original_read_text(self, encoding=encoding)

    caplog.set_level(logging.ERROR)
    monkeypatch.setattr(Path, "read_text", fake_read_text)

    assert loader.get_skill_content("broken") is None
    assert "读取 SKILL.md 失败: cannot read" in caplog.text


def test_skill_loader_build_skills_prompt_covers_empty_native_and_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """技能提示词应覆盖空列表、原生构建与备用实现。"""

    install_fake_skill_modules(monkeypatch, FakeSkillManager)
    loader = AstrBotSkillLoader(context=object())

    monkeypatch.setattr(loader, "list_skills", lambda active_only=True: [])
    assert loader.build_skills_prompt() == ""

    monkeypatch.setattr(
        loader,
        "list_skills",
        lambda active_only=True: [
            {
                "name": "alpha",
                "description": "first skill",
                "path": "/tmp/alpha",
                "active": True,
            }
        ],
    )
    assert loader.build_skills_prompt() == "PROMPT:alpha"

    original_import = builtins.__import__

    def fake_import(
        name: str,
        globals_dict: dict[str, Any] | None = None,
        locals_dict: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        """触发 prompt 构建器的 ImportError 备用分支。"""

        if name == "astrbot.core.skills.skill_manager":
            raise ImportError("no skill prompt builder")
        return original_import(name, globals_dict, locals_dict, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    assert loader.build_skills_prompt() == "## 可用技能\n- **alpha**: first skill"
