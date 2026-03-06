"""动态编排器运行时原语接入测试。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from astrbot_orchestrator_v5.orchestrator.core import DynamicOrchestrator
from astrbot_orchestrator_v5.runtime.request_context import RequestContext

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
async def test_dynamic_orchestrator_process_request_uses_runtime_pipeline(
    fake_context: "FakeContext",
) -> None:
    """编排器应能消费新的 RequestContext 并通过链完成推理。"""

    fake_context.queue_response(
        """```json
{"intent": "reasoning", "needs_planning": false, "params": {}, "needs_admin": false, "description": "普通问答"}
```"""
    )
    fake_context.queue_response("LCEL 是一种用管道串联 Runnable 的声明式表达方式。")

    orchestrator = DynamicOrchestrator(
        context=fake_context,
        config={"show_thinking_process": False},
    )
    request_context = RequestContext.from_legacy(
        user_request="什么是 LCEL？",
        provider_id="provider-x",
        context={"is_admin": False},
    )

    result = await orchestrator.process_request(request_context)

    assert result["status"] == "success"
    assert "LCEL" in result["answer"]
