"""AgentRunner（tool_loop_agent 薄层）测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from astrbot_orchestrator_v5.artifacts import ArtifactService
from astrbot_orchestrator_v5.orchestrator.agent_runner import (
    ORCHESTRATOR_SYSTEM_PROMPT,
    AgentRunner,
)
from astrbot_orchestrator_v5.tools.base import OrchestratorTool, obj_schema
from tests.conftest import FakeContext, FakeEvent


class _EchoTool(OrchestratorTool):
    requires_admin = False

    def __init__(self) -> None:
        super().__init__(None, name="echo", description="echo", parameters=obj_schema({}))

    async def run(self, event: Any) -> str:
        return "ok"


@pytest.mark.asyncio
async def test_run_invokes_tool_loop_agent_with_expected_args(
    fake_context: FakeContext, fake_event: FakeEvent
) -> None:
    runner = AgentRunner(
        context=fake_context,
        config={"max_iterations": 7, "task_timeout": 30},
        tools=[_EchoTool()],
    )
    fake_context.queue_response("任务完成")

    answer = await runner.run(fake_event, "帮我做点事")

    assert answer == "任务完成"
    assert len(fake_context.tool_loop_calls) == 1
    call = fake_context.tool_loop_calls[0]
    assert call["event"] is fake_event
    assert call["chat_provider_id"] == "fake-provider"
    assert call["prompt"] == "帮我做点事"
    assert call["system_prompt"] == ORCHESTRATOR_SYSTEM_PROMPT
    assert call["max_steps"] == 7
    assert "echo" in call["tools"].names()


@pytest.mark.asyncio
async def test_run_prefers_configured_provider(
    fake_context: FakeContext, fake_event: FakeEvent
) -> None:
    runner = AgentRunner(
        context=fake_context,
        config={"llm_provider": "my-provider"},
        tools=[],
    )
    fake_context.queue_response("done")

    await runner.run(fake_event, "task")

    assert fake_context.tool_loop_calls[0]["chat_provider_id"] == "my-provider"


@pytest.mark.asyncio
async def test_toolset_includes_official_handoffs(
    fake_context: FakeContext, fake_event: FakeEvent
) -> None:
    await fake_context.subagent_orchestrator.reload_from_config(
        {"agents": [{"name": "coder", "system_prompt": "x"}]}
    )
    runner = AgentRunner(context=fake_context, config={}, tools=[_EchoTool()])

    toolset = runner.build_toolset()

    assert "transfer_to_coder" in toolset.names()
    assert "echo" in toolset.names()


@pytest.mark.asyncio
async def test_run_persists_artifacts_from_response(
    fake_context: FakeContext, fake_event: FakeEvent, tmp_path: Path
) -> None:
    service = ArtifactService(str(tmp_path))
    runner = AgentRunner(
        context=fake_context,
        config={},
        tools=[],
        artifact_service=service,
    )
    fake_context.queue_response("生成如下：\n```python:hello.py\nprint('hi')\n```")

    answer = await runner.run(fake_event, "写个脚本")

    assert "hello.py" in answer
    saved = tmp_path / "agent_task" / "hello.py"
    assert saved.exists()
    assert "print('hi')" in saved.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_run_times_out(fake_context: FakeContext, fake_event: FakeEvent) -> None:
    import asyncio

    async def slow_tool_loop_agent(**_: Any) -> Any:
        await asyncio.sleep(5)

    fake_context.tool_loop_agent = slow_tool_loop_agent  # type: ignore[method-assign]
    runner = AgentRunner(
        context=fake_context,
        config={"task_timeout": 1},
        tools=[],
    )

    answer = await runner.run(fake_event, "task")

    assert "超时" in answer


@pytest.mark.asyncio
async def test_run_reports_missing_provider(fake_event: FakeEvent) -> None:
    class NoProviderContext(FakeContext):
        async def get_current_chat_provider_id(self, umo: str | None = None) -> str:
            raise RuntimeError("no provider")

    runner = AgentRunner(context=NoProviderContext(), config={}, tools=[])

    answer = await runner.run(fake_event, "task")

    assert "未找到可用的 LLM 提供商" in answer
