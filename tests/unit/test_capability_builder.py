"""AgentCapabilityBuilder 单元测试。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from astrbot_orchestrator_v5.orchestrator.capability_builder import AgentCapabilityBuilder

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


class FakeSkillTool:
    """Skill 工具替身。"""

    def __init__(self) -> None:
        """初始化调用记录。"""

        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def generate_skill_from_description(
        self,
        *,
        name: str,
        user_description: str,
        provider_id: str,
    ) -> str:
        """记录生成 skill 调用。"""

        self.calls.append(
            (
                "generate",
                {
                    "name": name,
                    "user_description": user_description,
                    "provider_id": provider_id,
                },
            )
        )
        return "generated-content"

    async def create_skill(
        self,
        *,
        name: str,
        description: str,
        content: str,
    ) -> str:
        """记录创建 skill 调用。"""

        self.calls.append(
            (
                "create",
                {
                    "name": name,
                    "description": description,
                    "content": content,
                },
            )
        )
        return "skill-created"


class FakeMcpTool:
    """MCP 工具替身。"""

    def __init__(self) -> None:
        """初始化调用记录。"""

        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def add_server(
        self,
        *,
        name: str,
        url: str,
        transport: str,
        headers: dict[str, str] | None,
    ) -> str:
        """记录直接添加 MCP 调用。"""

        self.calls.append(
            (
                "add_server",
                {
                    "name": name,
                    "url": url,
                    "transport": transport,
                    "headers": headers,
                },
            )
        )
        return "mcp-added"

    async def create_mcp_from_description(
        self,
        *,
        name: str,
        user_description: str,
        provider_id: str,
    ) -> str:
        """记录描述生成 MCP 调用。"""

        self.calls.append(
            (
                "create_from_description",
                {
                    "name": name,
                    "user_description": user_description,
                    "provider_id": provider_id,
                },
            )
        )
        return "mcp-created"


class FakeExecutor:
    """执行器替身。"""

    def __init__(self) -> None:
        """初始化调用记录。"""

        self.calls: list[dict[str, Any]] = []

    async def auto_execute(self, *, code: str, event: object, code_type: str) -> str:
        """记录自动执行调用。"""

        self.calls.append(
            {
                "code": code,
                "event": event,
                "code_type": code_type,
            }
        )
        return f"executed:{code_type}"


@pytest.mark.asyncio
async def test_capability_builder_build_skill_returns_unavailable_without_tool() -> None:
    """缺少 skill 工具时应返回不可用提示。"""

    builder = AgentCapabilityBuilder(context=object(), skill_tool=None)

    result = await builder.build_skill("generate a skill", "provider-x")

    assert result == "❌ Skill 管理工具不可用"


@pytest.mark.asyncio
async def test_capability_builder_build_skill_generates_and_creates_skill() -> None:
    """构建 skill 时应先生成内容，再创建 skill。"""

    skill_tool = FakeSkillTool()
    builder = AgentCapabilityBuilder(context=object(), skill_tool=skill_tool)
    long_description = "a" * 120

    result = await builder.build_skill(long_description, "provider-x")

    assert result == "skill-created"
    assert skill_tool.calls == [
        (
            "generate",
            {
                "name": "auto_skill",
                "user_description": long_description,
                "provider_id": "provider-x",
            },
        ),
        (
            "create",
            {
                "name": "auto_skill",
                "description": long_description[:100],
                "content": "generated-content",
            },
        ),
    ]


@pytest.mark.asyncio
async def test_capability_builder_configure_mcp_covers_unavailable_add_and_generate_paths() -> None:
    """MCP 构建器应覆盖工具缺失、直接添加和描述生成三条路径。"""

    unavailable_builder = AgentCapabilityBuilder(context=object(), mcp_tool=None)
    mcp_tool = FakeMcpTool()
    builder = AgentCapabilityBuilder(context=object(), mcp_tool=mcp_tool)

    unavailable_result = await unavailable_builder.configure_mcp(
        "connect to search service",
        "provider-x",
    )
    add_result = await builder.configure_mcp(
        "connect to search service",
        "provider-x",
        params={
            "name": "search",
            "url": "https://example.com/mcp",
            "transport": "streamable_http",
            "headers": {"Authorization": "Bearer token"},
        },
    )
    generated_result = await builder.configure_mcp(
        "connect to docs service",
        "provider-y",
        params={},
    )

    assert unavailable_result == "❌ MCP 配置工具不可用"
    assert add_result == "mcp-added"
    assert generated_result == "mcp-created"
    assert mcp_tool.calls == [
        (
            "add_server",
            {
                "name": "search",
                "url": "https://example.com/mcp",
                "transport": "streamable_http",
                "headers": {"Authorization": "Bearer token"},
            },
        ),
        (
            "create_from_description",
            {
                "name": "auto_mcp",
                "user_description": "connect to docs service",
                "provider_id": "provider-y",
            },
        ),
    ]


@pytest.mark.asyncio
async def test_capability_builder_execute_code_covers_unavailable_default_and_custom_type() -> None:
    """代码执行应覆盖执行器缺失、默认类型与自定义类型。"""

    unavailable_builder = AgentCapabilityBuilder(context=object(), executor=None)
    executor = FakeExecutor()
    builder = AgentCapabilityBuilder(context=object(), executor=executor)
    event = object()

    unavailable_result = await unavailable_builder.execute_code("echo hi", event)
    default_result = await builder.execute_code("echo hi", event)
    python_result = await builder.execute_code(
        "print('ok')",
        event,
        params={"type": "python"},
    )

    assert unavailable_result == "❌ 执行器不可用"
    assert default_result == "executed:shell"
    assert python_result == "executed:python"
    assert executor.calls == [
        {
            "code": "echo hi",
            "event": event,
            "code_type": "shell",
        },
        {
            "code": "print('ok')",
            "event": event,
            "code_type": "python",
        },
    ]
