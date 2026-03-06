"""SkillCreatorTool 单元测试。"""

from __future__ import annotations

import builtins
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

import astrbot_orchestrator_v5.autonomous.skill_creator as skill_module
from astrbot_orchestrator_v5.autonomous.skill_creator import SkillCreatorTool

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
    """模拟 AstrBot SkillManager。"""

    def __init__(
        self,
        *,
        skills: list[Any] | None = None,
        list_error: Exception | None = None,
        delete_error: Exception | None = None,
    ) -> None:
        """保存技能列表与失败行为。"""

        self.skills = list(skills or [])
        self.list_error = list_error
        self.delete_error = delete_error
        self.list_calls: list[bool] = []
        self.set_active_calls: list[tuple[str, bool]] = []
        self.delete_calls: list[str] = []

    def list_skills(self, *, active_only: bool) -> list[Any]:
        """返回预设技能列表或抛出异常。"""

        self.list_calls.append(active_only)
        if self.list_error is not None:
            raise self.list_error
        return list(self.skills)

    def set_skill_active(self, name: str, active: bool) -> None:
        """记录激活调用。"""

        self.set_active_calls.append((name, active))

    def delete_skill(self, name: str) -> None:
        """记录删除调用，必要时抛出异常。"""

        self.delete_calls.append(name)
        if self.delete_error is not None:
            raise self.delete_error


class FakeContext:
    """为 SkillCreatorTool 提供最小上下文。"""

    def __init__(
        self,
        *,
        llm_responses: list[str] | None = None,
        llm_error: Exception | None = None,
    ) -> None:
        """保存 LLM 结果与异常。"""

        self._llm_responses = list(llm_responses or [])
        self._llm_error = llm_error
        self.llm_calls: list[dict[str, Any]] = []

    async def llm_generate(self, **kwargs: Any) -> SimpleNamespace:
        """记录调用并返回预设完成文本。"""

        self.llm_calls.append(kwargs)
        if self._llm_error is not None:
            raise self._llm_error
        text = self._llm_responses.pop(0) if self._llm_responses else ""
        return SimpleNamespace(completion_text=text)


def test_skill_creator_get_skill_manager_caches_success_and_handles_import_error(
    monkeypatch: "MonkeyPatch",
) -> None:
    """SkillManager 应在首次导入后缓存，并在导入失败时回退为 None。"""

    tool = SkillCreatorTool(context=FakeContext())
    original_import = builtins.__import__
    created_managers: list[FakeSkillManager] = []

    class ImportedSkillManager:
        """用于模拟被导入的 SkillManager 类。"""

        def __init__(self) -> None:
            """构造时记录创建。"""

            created_managers.append(FakeSkillManager())

    fake_module = ModuleType("astrbot.core.skills.skill_manager")
    fake_module.SkillManager = ImportedSkillManager  # type: ignore[attr-defined]

    def import_success(
        name: str,
        globals_dict: dict[str, Any] | None = None,
        locals_dict: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        """返回假的 SkillManager 模块。"""

        if name == "astrbot.core.skills.skill_manager":
            return fake_module
        return original_import(name, globals_dict, locals_dict, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_success)

    first = tool._get_skill_manager()
    second = tool._get_skill_manager()

    assert first is second
    assert len(created_managers) == 1

    failing_tool = SkillCreatorTool(context=FakeContext())

    def import_failure(
        name: str,
        globals_dict: dict[str, Any] | None = None,
        locals_dict: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        """对 SkillManager 模块模拟导入失败。"""

        if name == "astrbot.core.skills.skill_manager":
            raise ImportError("missing")
        return original_import(name, globals_dict, locals_dict, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_failure)
    assert failing_tool._get_skill_manager() is None


def test_skill_creator_get_skills_path_supports_import_and_fallback(
    monkeypatch: "MonkeyPatch",
) -> None:
    """Skills 路径应优先使用 AstrBot 提供的方法，否则回退到默认目录。"""

    tool = SkillCreatorTool(context=FakeContext())
    original_import = builtins.__import__
    fake_module = ModuleType("astrbot.core.utils.astrbot_path")
    fake_module.get_astrbot_skills_path = lambda: "/tmp/astrbot-skills"  # type: ignore[attr-defined]

    def import_success(
        name: str,
        globals_dict: dict[str, Any] | None = None,
        locals_dict: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        """为 skills path 模块返回假实现。"""

        if name == "astrbot.core.utils.astrbot_path":
            return fake_module
        return original_import(name, globals_dict, locals_dict, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_success)
    assert tool._get_skills_path() == "/tmp/astrbot-skills"

    def import_failure(
        name: str,
        globals_dict: dict[str, Any] | None = None,
        locals_dict: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        """对 skills path 模块模拟导入失败。"""

        if name == "astrbot.core.utils.astrbot_path":
            raise ImportError("missing")
        return original_import(name, globals_dict, locals_dict, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_failure)
    monkeypatch.setattr(skill_module.os.path, "expanduser", lambda path: "/tmp/fallback-skills")
    assert tool._get_skills_path() == "/tmp/fallback-skills"


def test_skill_creator_list_skills_covers_unavailable_empty_success_and_failure(
    monkeypatch: "MonkeyPatch",
) -> None:
    """技能列表应覆盖管理器缺失、空列表、正常渲染和异常回退。"""

    unavailable_tool = SkillCreatorTool(context=FakeContext())
    monkeypatch.setattr(unavailable_tool, "_get_skill_manager", lambda: None)
    assert unavailable_tool.list_skills() == "❌ Skill 管理器不可用"

    empty_manager = FakeSkillManager(skills=[])
    empty_tool = SkillCreatorTool(context=FakeContext())
    monkeypatch.setattr(empty_tool, "_get_skill_manager", lambda: empty_manager)
    empty_result = empty_tool.list_skills()
    assert "📚 暂无 Skill" in empty_result
    assert "/skill create <名称>" in empty_result

    success_manager = FakeSkillManager(
        skills=[
            SimpleNamespace(
                active=True,
                name="calendar",
                description="calendar helper skill",
                path="/tmp/skills/calendar",
            ),
            SimpleNamespace(
                active=False,
                name="weather",
                description="",
                path="/tmp/skills/weather",
            ),
        ]
    )
    success_tool = SkillCreatorTool(context=FakeContext())
    monkeypatch.setattr(success_tool, "_get_skill_manager", lambda: success_manager)
    rendered = success_tool.list_skills()
    assert "✅ **calendar**" in rendered
    assert "❌ **weather**" in rendered
    assert "calendar helper skill..." in rendered
    assert "📁 /tmp/skills/weather" in rendered
    assert success_manager.list_calls == [False]

    failed_manager = FakeSkillManager(list_error=RuntimeError("list failed"))
    failed_tool = SkillCreatorTool(context=FakeContext())
    monkeypatch.setattr(failed_tool, "_get_skill_manager", lambda: failed_manager)
    assert failed_tool.list_skills() == "❌ 获取 Skill 列表失败: list failed"


def test_skill_creator_read_skill_covers_unavailable_missing_uppercase_and_lowercase(
    tmp_path: Path,
    monkeypatch: "MonkeyPatch",
) -> None:
    """读取技能应覆盖管理器缺失、文件不存在、大小写文件名兼容。"""

    unavailable_tool = SkillCreatorTool(context=FakeContext())
    monkeypatch.setattr(unavailable_tool, "_get_skill_manager", lambda: None)
    assert unavailable_tool.read_skill("Calendar Skill") == "❌ Skill 管理器不可用"

    tool = SkillCreatorTool(context=FakeContext())
    monkeypatch.setattr(tool, "_get_skill_manager", lambda: FakeSkillManager())
    monkeypatch.setattr(tool, "_get_skills_path", lambda: str(tmp_path))

    missing = tool.read_skill("Calendar Skill")
    assert missing == "❌ Skill `calendar_skill` 不存在"

    upper_dir = tmp_path / "calendar_skill"
    upper_dir.mkdir()
    (upper_dir / "SKILL.md").write_text("# Calendar\n", encoding="utf-8")
    upper_result = tool.read_skill("Calendar Skill")
    assert "📄 Skill: **calendar_skill**" in upper_result
    assert "# Calendar" in upper_result

    lower_dir = tmp_path / "weather_skill"
    lower_dir.mkdir()
    (lower_dir / "skill.md").write_text("# Weather\n", encoding="utf-8")
    lower_result = tool.read_skill("Weather Skill")
    assert "📄 Skill: **weather_skill**" in lower_result
    assert "# Weather" in lower_result


def test_skill_creator_read_skill_handles_read_failure(
    tmp_path: Path,
    monkeypatch: "MonkeyPatch",
) -> None:
    """读取文件异常时应返回统一错误。"""

    tool = SkillCreatorTool(context=FakeContext())
    monkeypatch.setattr(tool, "_get_skill_manager", lambda: FakeSkillManager())
    monkeypatch.setattr(tool, "_get_skills_path", lambda: str(tmp_path))
    skill_dir = tmp_path / "calendar_skill"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# Calendar\n", encoding="utf-8")

    def fail_read(self: Path, encoding: str = "utf-8") -> str:
        """对目标文件模拟读取失败。"""

        del encoding
        if self == skill_file:
            raise OSError("read failed")
        return Path.read_text(self, encoding="utf-8")

    original_read_text = skill_module.Path.read_text
    monkeypatch.setattr(
        skill_module.Path,
        "read_text",
        lambda self, encoding="utf-8": (
            (_ for _ in ()).throw(OSError("read failed"))
            if self == skill_file
            else original_read_text(self, encoding=encoding)
        ),
    )

    assert tool.read_skill("calendar skill") == "❌ 读取 Skill 失败: read failed"


@pytest.mark.asyncio
async def test_skill_creator_create_skill_covers_existing_success_scripts_and_no_manager(
    tmp_path: Path,
    monkeypatch: "MonkeyPatch",
) -> None:
    """创建技能应覆盖已存在、成功创建、脚本落盘和无管理器分支。"""

    tool = SkillCreatorTool(context=FakeContext())
    monkeypatch.setattr(tool, "_get_skills_path", lambda: str(tmp_path))
    existing_dir = tmp_path / "calendar_skill"
    existing_dir.mkdir()
    exists_result = await tool.create_skill("Calendar Skill", "desc", "# body")
    assert exists_result == "❌ Skill `calendar_skill` 已存在，请使用其他名称或先删除"

    success_manager = FakeSkillManager()
    success_tool = SkillCreatorTool(context=FakeContext())
    monkeypatch.setattr(success_tool, "_get_skills_path", lambda: str(tmp_path))
    monkeypatch.setattr(success_tool, "_get_skill_manager", lambda: success_manager)
    success_result = await success_tool.create_skill(
        "Weather Skill",
        "天气描述",
        "# Weather\n\n内容",
        scripts={"run.py": "print('ok')"},
    )
    skill_dir = tmp_path / "weather_skill"
    assert "✅ Skill `weather_skill` 创建成功！" in success_result
    assert (skill_dir / "SKILL.md").read_text(encoding="utf-8").startswith("---\ndescription: 天气描述")
    assert (skill_dir / "scripts" / "run.py").read_text(encoding="utf-8") == "print('ok')"
    assert success_manager.set_active_calls == [("weather_skill", True)]

    no_manager_tool = SkillCreatorTool(context=FakeContext())
    monkeypatch.setattr(no_manager_tool, "_get_skills_path", lambda: str(tmp_path))
    monkeypatch.setattr(no_manager_tool, "_get_skill_manager", lambda: None)
    no_manager_result = await no_manager_tool.create_skill(
        "No Manager Skill",
        "desc",
        "# No Manager",
    )
    assert "✅ Skill `no_manager_skill` 创建成功！" in no_manager_result


@pytest.mark.asyncio
async def test_skill_creator_create_skill_handles_write_failure(
    tmp_path: Path,
    monkeypatch: "MonkeyPatch",
) -> None:
    """创建文件失败时应返回统一错误。"""

    tool = SkillCreatorTool(context=FakeContext())
    monkeypatch.setattr(tool, "_get_skills_path", lambda: str(tmp_path))
    original_write_text = skill_module.Path.write_text

    def fail_write(self: Path, content: str, encoding: str = "utf-8") -> int:
        """对 SKILL.md 模拟写入失败。"""

        if self.name == "SKILL.md":
            raise OSError("disk full")
        return original_write_text(self, content, encoding=encoding)

    monkeypatch.setattr(skill_module.Path, "write_text", fail_write)

    result = await tool.create_skill("Broken Skill", "desc", "# body")

    assert result == "❌ 创建失败: disk full"


@pytest.mark.asyncio
async def test_skill_creator_edit_skill_covers_missing_uppercase_lowercase_and_failure(
    tmp_path: Path,
    monkeypatch: "MonkeyPatch",
) -> None:
    """编辑技能应覆盖缺失、大小写文件名兼容、备份和失败分支。"""

    tool = SkillCreatorTool(context=FakeContext())
    monkeypatch.setattr(tool, "_get_skills_path", lambda: str(tmp_path))

    missing = await tool.edit_skill("Calendar Skill", "# new")
    assert missing == "❌ Skill `calendar_skill` 不存在"

    upper_dir = tmp_path / "calendar_skill"
    upper_dir.mkdir()
    upper_file = upper_dir / "SKILL.md"
    upper_file.write_text("# Old\n", encoding="utf-8")
    upper_result = await tool.edit_skill("Calendar Skill", "# Updated\n")
    assert "✅ Skill `calendar_skill` 已更新" in upper_result
    assert upper_file.read_text(encoding="utf-8") == "# Updated\n"
    assert (upper_dir / "SKILL.md.bak").read_text(encoding="utf-8") == "# Old\n"

    lower_dir = tmp_path / "weather_skill"
    lower_dir.mkdir()
    lower_file = lower_dir / "skill.md"
    lower_file.write_text("# Lower\n", encoding="utf-8")
    lower_result = await tool.edit_skill("Weather Skill", "# Lower Updated\n")
    assert "✅ Skill `weather_skill` 已更新" in lower_result
    assert lower_file.read_text(encoding="utf-8") == "# Lower Updated\n"
    assert (lower_dir / "skill.md.bak").read_text(encoding="utf-8") == "# Lower\n"

    original_write_text = skill_module.Path.write_text

    def fail_backup_or_write(self: Path, content: str, encoding: str = "utf-8") -> int:
        """在写入更新内容时模拟失败。"""

        if self == upper_file:
            raise OSError("write failed")
        return original_write_text(self, content, encoding=encoding)

    monkeypatch.setattr(skill_module.Path, "write_text", fail_backup_or_write)
    failed = await tool.edit_skill("Calendar Skill", "# Broken\n")
    assert failed == "❌ 编辑失败: write failed"


def test_skill_creator_delete_skill_covers_unavailable_success_and_failure(
    monkeypatch: "MonkeyPatch",
) -> None:
    """删除技能应覆盖管理器缺失、成功和失败。"""

    unavailable_tool = SkillCreatorTool(context=FakeContext())
    monkeypatch.setattr(unavailable_tool, "_get_skill_manager", lambda: None)
    assert unavailable_tool.delete_skill("Calendar Skill") == "❌ Skill 管理器不可用"

    success_manager = FakeSkillManager()
    success_tool = SkillCreatorTool(context=FakeContext())
    monkeypatch.setattr(success_tool, "_get_skill_manager", lambda: success_manager)
    assert success_tool.delete_skill("Calendar Skill") == "✅ Skill `calendar_skill` 已删除"
    assert success_manager.delete_calls == ["calendar_skill"]

    failed_manager = FakeSkillManager(delete_error=RuntimeError("delete failed"))
    failed_tool = SkillCreatorTool(context=FakeContext())
    monkeypatch.setattr(failed_tool, "_get_skill_manager", lambda: failed_manager)
    assert failed_tool.delete_skill("Calendar Skill") == "❌ 删除失败: delete failed"


@pytest.mark.asyncio
async def test_skill_creator_generate_skill_from_description_covers_all_formats() -> None:
    """生成技能内容应正确提取 markdown fenced、普通 fenced 与纯文本。"""

    context = FakeContext(
        llm_responses=[
            "```markdown\n# Skill A\n```",
            "```text\n# Skill B\n```",
            "  # Skill C  ",
            "```\n# Skill D\n```",
            "```# Skill E```",
        ]
    )
    tool = SkillCreatorTool(context=context)

    markdown_result = await tool.generate_skill_from_description(
        "Calendar Skill",
        "做一个日历 Skill",
        "provider-a",
    )
    generic_result = await tool.generate_skill_from_description(
        "Weather Skill",
        "做一个天气 Skill",
        "provider-b",
    )
    plain_result = await tool.generate_skill_from_description(
        "Todo Skill",
        "做一个待办 Skill",
        "provider-c",
    )
    blank_first_line_result = await tool.generate_skill_from_description(
        "Blank Skill",
        "做一个空行 fenced Skill",
        "provider-d",
    )
    inline_fence_result = await tool.generate_skill_from_description(
        "Inline Skill",
        "做一个单行 fenced Skill",
        "provider-e",
    )

    assert markdown_result == "# Skill A"
    assert generic_result == "# Skill B"
    assert plain_result == "# Skill C"
    assert blank_first_line_result == "# Skill D"
    assert inline_fence_result == "# Skill E"
    assert context.llm_calls[0]["chat_provider_id"] == "provider-a"
    assert "做一个日历 Skill" in context.llm_calls[0]["prompt"]
    assert context.llm_calls[0]["system_prompt"] == "你是一个专业的 AstrBot Skill 开发者。"


@pytest.mark.asyncio
async def test_skill_creator_generate_skill_from_description_reraises_failure() -> None:
    """LLM 失败时应继续抛出异常，让上层决定如何处理。"""

    tool = SkillCreatorTool(context=FakeContext(llm_error=RuntimeError("llm down")))

    with pytest.raises(RuntimeError, match="llm down"):
        await tool.generate_skill_from_description(
            "Calendar Skill",
            "做一个日历 Skill",
            "provider-a",
        )
