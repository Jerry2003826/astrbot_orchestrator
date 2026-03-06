"""AgentTemplateLibrary 单元测试。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from astrbot_orchestrator_v5.orchestrator.agent_templates import (
    AgentSpec,
    AgentTemplate,
    AgentTemplateLibrary,
)

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


def test_agent_spec_to_config_renders_expected_runtime_fields() -> None:
    """AgentSpec 应导出运行时所需配置字段。"""

    spec = AgentSpec(
        agent_id="agent-1",
        name="code_agent",
        role="code",
        instructions="你是代码助手",
        tools=["sandbox"],
        public_description="生成代码",
        provider_id="provider-x",
        persona_id="persona-x",
        enabled=False,
        metadata={"ignored": True},
    )

    config = spec.to_config()

    assert config == {
        "name": "code_agent",
        "enabled": False,
        "persona_id": "persona-x",
        "system_prompt": "你是代码助手",
        "public_description": "生成代码",
        "provider_id": "provider-x",
        "tools": ["sandbox"],
    }


def test_agent_template_to_spec_supports_suffix_and_copies_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模板转 spec 时应支持名称后缀并复制工具列表。"""

    monkeypatch.setattr(
        "astrbot_orchestrator_v5.orchestrator.agent_templates.uuid.uuid4",
        lambda: "uuid-fixed",
    )
    template = AgentTemplate(
        role="review",
        name="review_agent",
        system_prompt="你是审查助手",
        public_description="审查代码",
        tools=["sandbox"],
    )

    spec = template.to_spec(name_suffix="a")
    spec.tools.append("extra")

    assert spec.agent_id == "uuid-fixed"
    assert spec.name == "review_agent_a"
    assert spec.role == "review"
    assert spec.instructions == "你是审查助手"
    assert spec.public_description == "审查代码"
    assert template.tools == ["sandbox"]


def test_agent_template_library_updates_existing_templates_ignores_invalid_entries_and_exports() -> (
    None
):
    """模板库应支持更新内置模板、忽略非法 override 并导出配置。"""

    library = AgentTemplateLibrary(
        overrides={
            "code": {
                "name": "custom_code_agent",
                "system_prompt": "自定义代码助手",
                "public_description": "自定义代码描述",
                "tools": ["sandbox", "skill_gen", "browser"],
            },
            "invalid": "skip-me",
        }
    )

    roles = library.list_roles()
    code_template = library.get("code")
    exported = library.export_templates()

    assert "code" in roles
    assert code_template is not None
    assert code_template.name == "custom_code_agent"
    assert code_template.system_prompt == "自定义代码助手"
    assert code_template.public_description == "自定义代码描述"
    assert code_template.tools == ["sandbox", "skill_gen", "browser"]
    assert "invalid" not in exported
    assert exported["code"] == {
        "name": "custom_code_agent",
        "system_prompt": "自定义代码助手",
        "public_description": "自定义代码描述",
        "tools": ["sandbox", "skill_gen", "browser"],
    }


def test_agent_template_library_keeps_existing_tools_when_override_tools_is_not_list() -> None:
    """更新已有模板时，非列表 tools 不应覆盖原始工具集。"""

    library = AgentTemplateLibrary(
        overrides={
            "debug": {
                "name": "debug_agent_v2",
                "tools": "not-a-list",
            }
        }
    )

    debug_template = library.get("debug")

    assert debug_template is not None
    assert debug_template.name == "debug_agent_v2"
    assert debug_template.tools == ["sandbox"]


def test_agent_template_library_adds_new_override_role_with_non_list_tools_default() -> None:
    """新增 override 角色时，非列表 tools 应回退为空列表。"""

    library = AgentTemplateLibrary(
        overrides={
            "review": {
                "name": "review_agent",
                "system_prompt": "你是审查助手",
                "public_description": "负责代码审查",
                "tools": "not-a-list",
            }
        }
    )

    review_template = library.get("review")

    assert review_template is not None
    assert review_template.name == "review_agent"
    assert review_template.system_prompt == "你是审查助手"
    assert review_template.public_description == "负责代码审查"
    assert review_template.tools == []


def test_agent_template_library_adds_new_override_role_with_list_tools() -> None:
    """新增 override 角色时，应保留合法的 tools 列表。"""

    library = AgentTemplateLibrary(
        overrides={
            "planner": {
                "name": "planner_agent",
                "system_prompt": "你是规划助手",
                "public_description": "负责任务规划",
                "tools": ["sandbox", "browser"],
            }
        }
    )

    planner_template = library.get("planner")

    assert planner_template is not None
    assert planner_template.tools == ["sandbox", "browser"]


def test_agent_template_library_build_spec_uses_template_customizations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """build_spec 应能基于模板覆盖名称、指令、工具与 provider 信息。"""

    monkeypatch.setattr(
        "astrbot_orchestrator_v5.orchestrator.agent_templates.uuid.uuid4",
        lambda: "uuid-build",
    )
    library = AgentTemplateLibrary()

    spec = library.build_spec(
        role="code",
        name="named_code_agent",
        instructions="覆盖后的系统提示",
        tools=["shell"],
        public_description="覆盖后的公开描述",
        provider_id="provider-y",
        persona_id="persona-y",
    )

    assert spec.agent_id == "uuid-build"
    assert spec.name == "named_code_agent"
    assert spec.role == "code"
    assert spec.instructions == "覆盖后的系统提示"
    assert spec.tools == ["shell"]
    assert spec.public_description == "覆盖后的公开描述"
    assert spec.provider_id == "provider-y"
    assert spec.persona_id == "persona-y"


def test_agent_template_library_build_spec_uses_template_defaults_when_optional_values_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """build_spec 在未传可选参数时应保留模板默认值。"""

    monkeypatch.setattr(
        "astrbot_orchestrator_v5.orchestrator.agent_templates.uuid.uuid4",
        lambda: "uuid-default",
    )
    library = AgentTemplateLibrary()

    spec = library.build_spec(role="test")

    assert spec.agent_id == "uuid-default"
    assert spec.name == "test_agent"
    assert spec.role == "test"
    assert "测试与质量专家" in spec.instructions
    assert spec.tools == ["sandbox"]
    assert spec.public_description == "验证实现并输出测试建议的子代理"
    assert spec.provider_id is None
    assert spec.persona_id is None


def test_agent_template_library_build_spec_falls_back_for_unknown_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未知角色应走通用 fallback spec 构建分支。"""

    monkeypatch.setattr(
        "astrbot_orchestrator_v5.orchestrator.agent_templates.uuid.uuid4",
        lambda: "uuid-fallback",
    )
    library = AgentTemplateLibrary()

    spec = library.build_spec(
        role="planner",
        provider_id="provider-z",
        persona_id="persona-z",
    )

    assert spec.agent_id == "uuid-fallback"
    assert spec.name == "planner_agent"
    assert spec.role == "planner"
    assert spec.instructions == "你是一个通用助手。"
    assert spec.tools == []
    assert spec.public_description == "动态生成的子代理"
    assert spec.provider_id == "provider-z"
    assert spec.persona_id == "persona-z"
