"""共享测试夹具。"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

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


@dataclass
class FakeLLMResponse:
    """模拟 LLM 返回对象。"""

    completion_text: str


class FakeContext:
    """最小可用的 AstrBot Context 测试替身。"""

    def __init__(self) -> None:
        self._responses: list[str] = []
        self.provider_manager = SimpleNamespace(llm_tools=SimpleNamespace(mcp_client_dict={}))

    def queue_response(self, text: str) -> None:
        """向响应队列中压入一条 LLM 输出。"""

        self._responses.append(text)

    async def llm_generate(self, **_: Any) -> FakeLLMResponse:
        """返回预先排队的响应。"""

        if not self._responses:
            raise RuntimeError("FakeContext 没有可用的 LLM 响应")
        return FakeLLMResponse(completion_text=self._responses.pop(0))

    def get_config(self) -> dict[str, Any]:
        """返回最小配置对象。"""

        return {}


@dataclass
class FakeEvent:
    """最小可用的 AstrBot 事件替身。"""

    message_str: str = ""
    role: str = "user"
    unified_msg_origin: str = "umo-1"
    session_id: str = "session-1"
    sender_id: str = "user-1"

    def plain_result(self, text: str) -> str:
        """模拟返回纯文本消息组件。"""

        return text

    def get_sender_id(self) -> str:
        """返回发送者 ID。"""

        return self.sender_id


@pytest.fixture
def fake_context() -> FakeContext:
    """提供最小可用的 Context 替身。"""

    return FakeContext()


@pytest.fixture
def fake_event() -> FakeEvent:
    """提供最小可用的事件替身。"""

    return FakeEvent()
