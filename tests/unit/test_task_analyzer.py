"""TaskAnalyzer 单元测试。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

import pytest

from astrbot_orchestrator_v5.orchestrator.task_analyzer import AgentTask, TaskAnalyzer, TaskPlan

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture
    from _pytest.fixtures import FixtureRequest
    from _pytest.logging import LogCaptureFixture
    from _pytest.monkeypatch import MonkeyPatch
    from pytest_mock.plugin import MockerFixture

    from tests.conftest import FakeContext

    _PYTEST_TYPE_IMPORTS = (
        CaptureFixture,
        FixtureRequest,
        LogCaptureFixture,
        MonkeyPatch,
        MockerFixture,
    )


@pytest.mark.asyncio
async def test_task_analyzer_analyze_postprocesses_execute_code_for_code_request(
    fake_context: "FakeContext",
) -> None:
    """代码生成请求应将误分配的 execute_code 后处理为 llm。"""

    fake_context.queue_response(
        """```json
{
  "summary": "生成网站",
  "agents": [
    {
      "role": "code",
      "name": "code_agent",
      "system_prompt": "你是代码助手",
      "public_description": "生成代码",
      "tools": ["sandbox"],
      "provider_id": null
    }
  ],
  "tasks": [
    {
      "id": "task_generate",
      "description": "生成完整项目代码",
      "agent_role": "code",
      "action": "execute_code",
      "input": "帮我写一个网站",
      "depends_on": []
    }
  ]
}
```"""
    )
    analyzer = TaskAnalyzer(fake_context)

    plan = await analyzer.analyze("帮我写一个网站", "provider-x")

    assert plan.summary == "生成网站"
    assert len(plan.agents) == 1
    assert plan.tasks[0].action == "llm"
    assert "代码块" in plan.tasks[0].input


@pytest.mark.asyncio
async def test_task_analyzer_analyze_falls_back_when_llm_payload_invalid(
    fake_context: "FakeContext",
) -> None:
    """LLM 输出非法 JSON 时应回退到内置计划。"""

    fake_context.queue_response("not-a-json-payload")
    analyzer = TaskAnalyzer(fake_context)

    plan = await analyzer.analyze("帮我写一个程序", "provider-x")

    assert plan.summary == "自动回退计划"
    assert len(plan.agents) == 2
    assert plan.tasks[0].action == "llm"
    assert "代码块" in plan.tasks[0].input
    assert plan.tasks[1].depends_on == ["task_plan"]


@pytest.mark.asyncio
async def test_task_analyzer_analyze_without_llm_builds_skill_fallback_plan(
    fake_context: "FakeContext",
) -> None:
    """禁用 LLM 分析时应直接生成 Skill 回退计划。"""

    analyzer = TaskAnalyzer(fake_context, config={"use_llm_task_analyzer": False})

    plan = await analyzer.analyze("帮我创建一个天气 skill", "provider-x")

    assert plan.summary == "自动回退计划"
    assert len(plan.agents) == 1
    assert plan.agents[0].role == "code"
    assert len(plan.tasks) == 1
    assert plan.tasks[0].action == "create_skill"


def test_task_analyzer_loads_template_overrides_from_settings_json_string(
    fake_context: "FakeContext",
) -> None:
    """应能从 settings 内的 JSON 字符串解析模板 override。"""

    analyzer = TaskAnalyzer(
        fake_context,
        config={
            "subagent_settings": {
                "subagent_template_overrides": (
                    '{"review":{"name":"review_agent","system_prompt":"你是审查者。",'
                    '"public_description":"代码审查子代理","tools":["sandbox"]}}'
                )
            }
        },
    )

    review_template = analyzer.templates.get("review")

    assert review_template is not None
    assert review_template.name == "review_agent"
    assert review_template.public_description == "代码审查子代理"
    assert review_template.tools == ["sandbox"]


def test_task_analyzer_load_template_overrides_cover_direct_dict_invalid_json_and_non_dict_configs(
    fake_context: "FakeContext",
    caplog: "LogCaptureFixture",
) -> None:
    """模板覆盖应覆盖直接字典、坏 JSON、无效 settings 与非字典配置。"""

    direct_override_analyzer = TaskAnalyzer(
        fake_context,
        config={
            "subagent_template_overrides": {
                "custom": {
                    "name": "custom_agent",
                    "system_prompt": "你是自定义代理。",
                    "public_description": "自定义描述",
                    "tools": ["sandbox"],
                }
            }
        },
    )
    settings_invalid_analyzer = TaskAnalyzer(fake_context, config={"subagent_settings": "oops"})
    nondict_config_analyzer = TaskAnalyzer(fake_context, config=cast(Any, "not-a-dict"))

    with caplog.at_level(logging.WARNING):
        invalid_json_analyzer = TaskAnalyzer(
            fake_context,
            config={"subagent_template_overrides": "{bad-json"},
        )

    custom_template = direct_override_analyzer.templates.get("custom")

    assert custom_template is not None
    assert custom_template.name == "custom_agent"
    assert custom_template.public_description == "自定义描述"
    assert custom_template.tools == ["sandbox"]
    assert settings_invalid_analyzer.templates.get("code") is not None
    assert nondict_config_analyzer.templates.get("code") is not None
    assert invalid_json_analyzer.templates.get("code") is not None
    assert "解析 subagent_template_overrides 失败" in caplog.text


@pytest.mark.asyncio
async def test_task_analyzer_analyze_with_llm_supports_generic_fence_and_task_defaults(
    fake_context: "FakeContext",
) -> None:
    """通用代码围栏 JSON 也应被解析，并补齐任务默认值。"""

    fake_context.queue_response(
        """```
{
  "summary": "研究任务",
  "agents": [
    {
      "role": "research"
    }
  ],
  "tasks": [
    {
      "description": "收集资料"
    }
  ]
}
```"""
    )
    analyzer = TaskAnalyzer(fake_context)

    plan = await analyzer._analyze_with_llm("请研究这个主题", "provider-x")

    assert plan.summary == "研究任务"
    assert len(plan.agents) == 1
    assert plan.agents[0].role == "research"
    assert len(plan.tasks) == 1
    assert plan.tasks[0].task_id == "task_1"
    assert plan.tasks[0].agent_role == "code"
    assert plan.tasks[0].action == "llm"
    assert plan.tasks[0].depends_on == []
    assert plan.tasks[0].params == {}


def test_task_analyzer_postprocess_plan_covers_return_and_suffix_branches(
    fake_context: "FakeContext",
) -> None:
    """后处理应覆盖非代码请求直返、降级与格式后缀补齐分支。"""

    analyzer = TaskAnalyzer(fake_context)
    unchanged_plan = TaskPlan(
        agents=[analyzer.templates.build_spec(role="code")],
        tasks=[
            AgentTask(
                task_id="task_shell",
                description="列出目录",
                agent_role="code",
                action="execute_code",
                input="ls -la",
            )
        ],
        summary="",
    )
    code_plan = TaskPlan(
        agents=[analyzer.templates.build_spec(role="code")],
        tasks=[
            AgentTask(
                task_id="task_downgrade",
                description="生成代码",
                agent_role="code",
                action="execute_code",
                input="帮我写一个网站，并使用```python:main.py格式输出",
            ),
            AgentTask(
                task_id="task_llm_code",
                description="补全代码",
                agent_role="code",
                action="llm",
                input="请生成完整项目",
            ),
            AgentTask(
                task_id="task_llm_test",
                description="测试建议",
                agent_role="test",
                action="llm",
                input="给出测试建议",
            ),
            AgentTask(
                task_id="task_exec_shell",
                description="安装依赖",
                agent_role="code",
                action="execute_code",
                input="npm install",
            ),
        ],
        summary="",
    )

    returned_plan = analyzer._postprocess_plan(unchanged_plan, "列出当前目录")
    processed_plan = analyzer._postprocess_plan(code_plan, "帮我创建一个应用")

    assert returned_plan is unchanged_plan
    assert processed_plan.tasks[0].action == "llm"
    assert processed_plan.tasks[0].input.count("【输出格式要求】") == 0
    assert "【输出格式要求】" in processed_plan.tasks[1].input
    assert "【输出格式要求】" not in processed_plan.tasks[2].input
    assert processed_plan.tasks[3].action == "execute_code"
    assert "【输出格式要求】" not in processed_plan.tasks[3].input


def test_task_analyzer_is_natural_language_covers_empty_shell_english_and_plain_text() -> None:
    """自然语言判断应覆盖空串、shell、英文长句与普通短文本。"""

    assert TaskAnalyzer._is_natural_language("") is False
    assert TaskAnalyzer._is_natural_language("pip install astrbot") is False
    assert (
        TaskAnalyzer._is_natural_language(
            "Please build a complete website with login dashboard settings profile notifications and help center"
        )
        is True
    )
    assert TaskAnalyzer._is_natural_language("build website") is False


def test_task_analyzer_fallback_plan_builds_mcp_task(
    fake_context: "FakeContext",
) -> None:
    """MCP 请求应命中 research/config_mcp 回退计划。"""

    analyzer = TaskAnalyzer(fake_context, config={"use_llm_task_analyzer": False})

    plan = analyzer._fallback_plan("请帮我配置 MCP 服务")

    assert plan.summary == "自动回退计划"
    assert len(plan.agents) == 1
    assert plan.agents[0].role == "research"
    assert len(plan.tasks) == 1
    assert plan.tasks[0].task_id == "task_mcp"
    assert plan.tasks[0].action == "config_mcp"
