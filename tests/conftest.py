"""共享测试夹具。

FakeEvent 基于 _astrbot_stub 的 AstrMessageEvent（与 v4.25.5 对齐）：
- `message_str` 是完整消息文本（含指令名），与真实宿主一致；
- `plain_result()` 返回 MessageEventResult，断言文本请用 `result_text()`。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import TYPE_CHECKING, Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

# 使 `import astrbot_orchestrator_v5` 解析到仓库根目录（目录名即包名）。
_PACKAGE_PARENT = str(_REPO_ROOT.parent)
if _PACKAGE_PARENT not in sys.path:
    sys.path.insert(0, _PACKAGE_PARENT)

# 使 `import astrbot` 解析到与 v4.25.5 对齐的测试桩。
_STUB_PATH = str(_REPO_ROOT / "_astrbot_stub")
if _STUB_PATH not in sys.path:
    sys.path.insert(0, _STUB_PATH)

from astrbot.core.config.astrbot_config import AstrBotConfig  # noqa: E402
from astrbot.core.message.message_event_result import MessageEventResult  # noqa: E402
from astrbot.core.platform.astr_message_event import AstrMessageEvent  # noqa: E402
from astrbot.core.platform.astrbot_message import (  # noqa: E402
    AstrBotMessage,
    MessageMember,
    MessageType,
)
from astrbot.core.platform.platform_metadata import PlatformMetadata  # noqa: E402
from astrbot.core.provider.func_tool_manager import FunctionToolManager  # noqa: E402
from astrbot.core.subagent_orchestrator import SubAgentOrchestrator  # noqa: E402

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
    """最小可用的 AstrBot Context 测试替身（对齐 v4.25.5 公开方法）。"""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._responses: list[str] = []
        self._config = AstrBotConfig(config or {})
        self.llm_tools = FunctionToolManager()
        self.provider_manager = type("FakeProviderManager", (), {"llm_tools": self.llm_tools})()
        self.subagent_orchestrator: Any = SubAgentOrchestrator(self.llm_tools)
        self._star_manager: Any = None
        self.tool_loop_calls: list[dict[str, Any]] = []

    def queue_response(self, text: str) -> None:
        """向响应队列中压入一条 LLM 输出。"""

        self._responses.append(text)

    def _pop_response(self) -> FakeLLMResponse:
        if not self._responses:
            raise RuntimeError("FakeContext 没有可用的 LLM 响应")
        return FakeLLMResponse(completion_text=self._responses.pop(0))

    async def llm_generate(self, **_: Any) -> FakeLLMResponse:
        """返回预先排队的响应。"""

        return self._pop_response()

    async def tool_loop_agent(self, **kwargs: Any) -> FakeLLMResponse:
        """记录调用参数并返回预先排队的响应。"""

        self.tool_loop_calls.append(kwargs)
        return self._pop_response()

    async def get_current_chat_provider_id(self, umo: str | None = None) -> str:
        return "fake-provider"

    def get_config(self, umo: str | None = None) -> AstrBotConfig:
        return self._config

    def get_llm_tool_manager(self) -> FunctionToolManager:
        return self.llm_tools

    def add_llm_tools(self, *tools: Any) -> None:
        for tool in tools:
            self.llm_tools.add_tool(tool)

    def get_registered_star(self, star_name: str) -> Any:
        return None

    def get_all_stars(self) -> list[Any]:
        return []

    def get_all_providers(self) -> list[Any]:
        return []


class FakeEvent(AstrMessageEvent):
    """基于真实宿主形态的事件替身。

    与真实宿主一致：`message_str` 含指令名本身（唤醒阶段只移除唤醒前缀）。
    """

    def __init__(
        self,
        message_str: str = "",
        role: str = "member",
        *,
        platform: str = "test",
        message_type: MessageType = MessageType.FRIEND_MESSAGE,
        session_id: str = "session-1",
        sender_id: str = "user-1",
        sender_name: str = "tester",
        group_id: str = "",
    ) -> None:
        message_obj = AstrBotMessage(
            type=message_type,
            self_id="bot-1",
            session_id=session_id,
            group_id=group_id,
            sender=MessageMember(user_id=sender_id, nickname=sender_name),
            message_str=message_str,
        )
        super().__init__(
            message_str=message_str,
            message_obj=message_obj,
            platform_meta=PlatformMetadata(name=platform, id=platform),
            session_id=session_id,
        )
        self.role = role
        self.is_wake = True


def result_text(result: Any) -> str:
    """提取一次 yield 结果中的纯文本，便于断言。"""

    if isinstance(result, MessageEventResult):
        return result.get_plain_text()
    return str(result)


async def collect_results(agen: Any) -> list[str]:
    """收集异步生成器产出的全部文本。"""

    return [result_text(item) async for item in agen]


@pytest.fixture
def fake_context() -> FakeContext:
    """提供最小可用的 Context 替身。"""

    return FakeContext()


@pytest.fixture
def fake_event() -> FakeEvent:
    """提供最小可用的事件替身。"""

    return FakeEvent()
