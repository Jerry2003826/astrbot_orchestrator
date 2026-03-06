"""main.py 入口层单元测试。"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import sys
from types import ModuleType
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

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
class MainTestHarness:
    """打包 main 模块测试所需桩对象。"""

    module: Any
    config_cls: type[Any]
    context_cls: type[Any]
    event_cls: type[Any]
    runtime_cls: type[Any]
    runtime_container_cls: type[Any]
    request_context_cls: type[Any]
    command_handlers_cls: type[Any]


def install_stub_module(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    **attributes: Any,
) -> ModuleType:
    """向 `sys.modules` 安装测试用桩模块。"""

    module = ModuleType(module_name)
    for attr_name, attr_value in attributes.items():
        setattr(module, attr_name, attr_value)
    monkeypatch.setitem(sys.modules, module_name, module)
    return module


def load_main_module(monkeypatch: pytest.MonkeyPatch) -> MainTestHarness:
    """安装依赖桩并导入 `astrbot_orchestrator_v5.main`。"""

    class FakeAstrBotConfig(dict[str, Any]):
        """AstrBotConfig 替身。"""

    class FakeContext:
        """Context 替身。"""

    class FakeAstrMessageEvent:
        """消息事件替身。"""

        def __init__(self, label: str = "event") -> None:
            """保存事件标签。"""

            self.label = label

    class FakeStar:
        """Star 基类替身。"""

        def __init__(self, context: Any) -> None:
            """保存上下文。"""

            self.context = context

    class FakeFilter:
        """命令装饰器替身。"""

        def command(self, command_name: str) -> Any:
            """为命令处理函数打标记。"""

            def decorator(func: Any) -> Any:
                func._command_name = command_name
                return func

            return decorator

    class FakeRuntime:
        """运行时容器实例替身。"""

        def __init__(self, exports: dict[str, Any] | None = None) -> None:
            """保存导出属性。"""

            self.exports = exports or {}
            self.stop_calls = 0

        def export_attributes(self) -> dict[str, Any]:
            """返回运行时导出组件。"""

            return dict(self.exports)

        async def astop(self) -> None:
            """记录停止调用。"""

            self.stop_calls += 1

    class FakeRuntimeContainer:
        """RuntimeContainer 替身。"""

        build_calls: list[tuple[Any, Any]] = []
        runtime_to_return: FakeRuntime = FakeRuntime()

        @classmethod
        def build(cls, context: Any, config: Any) -> FakeRuntime:
            """记录构建调用并返回预设运行时。"""

            cls.build_calls.append((context, config))
            return cls.runtime_to_return

    class FakeRequestContext:
        """RequestContext 替身。"""

        calls: list[dict[str, Any]] = []

        @classmethod
        def from_event(
            cls,
            *,
            user_request: str,
            provider_id: str,
            event: Any,
            metadata: dict[str, Any],
        ) -> dict[str, Any]:
            """记录请求上下文构建参数。"""

            payload = {
                "user_request": user_request,
                "provider_id": provider_id,
                "event": event,
                "metadata": metadata,
            }
            cls.calls.append(payload)
            return payload

    class FakeCommandHandlers:
        """CommandHandlers 替身。"""

        instances: list["FakeCommandHandlers"] = []

        def __init__(
            self,
            *,
            context: Any,
            runtime: Any,
            build_request_context: Any,
        ) -> None:
            """保存初始化参数。"""

            self.context = context
            self.runtime = runtime
            self.build_request_context = build_request_context
            self.calls: list[tuple[str, Any]] = []
            self.__class__.instances.append(self)

        async def _dispatch(
            self,
            command_name: str,
            event: Any,
        ) -> AsyncIterator[str]:
            """统一生成命令处理结果。"""

            self.calls.append((command_name, event))
            yield f"{command_name}:{event.label}"

        async def handle_agent(self, event: Any) -> AsyncIterator[str]:
            """处理 `/agent`。"""

            async for result in self._dispatch("agent", event):
                yield result

        async def handle_plugin(self, event: Any) -> AsyncIterator[str]:
            """处理 `/plugin`。"""

            async for result in self._dispatch("plugin", event):
                yield result

        async def handle_skill(self, event: Any) -> AsyncIterator[str]:
            """处理 `/skill`。"""

            async for result in self._dispatch("skill", event):
                yield result

        async def handle_mcp(self, event: Any) -> AsyncIterator[str]:
            """处理 `/mcp`。"""

            async for result in self._dispatch("mcp", event):
                yield result

        async def handle_exec(self, event: Any) -> AsyncIterator[str]:
            """处理 `/exec`。"""

            async for result in self._dispatch("exec", event):
                yield result

        async def handle_debug(self, event: Any) -> AsyncIterator[str]:
            """处理 `/debug`。"""

            async for result in self._dispatch("debug", event):
                yield result

        async def handle_sandbox(self, event: Any) -> AsyncIterator[str]:
            """处理 `/sandbox`。"""

            async for result in self._dispatch("sandbox", event):
                yield result

    def register(**kwargs: Any) -> Any:
        """模拟 AstrBot `register` 装饰器。"""

        def decorator(cls: Any) -> Any:
            cls._register_kwargs = kwargs
            return cls

        return decorator

    astrbot_api_module = install_stub_module(
        monkeypatch,
        "astrbot.api",
        AstrBotConfig=FakeAstrBotConfig,
    )
    astrbot_event_module = install_stub_module(
        monkeypatch,
        "astrbot.api.event",
        AstrMessageEvent=FakeAstrMessageEvent,
        filter=FakeFilter(),
    )
    astrbot_star_module = install_stub_module(
        monkeypatch,
        "astrbot.api.star",
        Context=FakeContext,
        Star=FakeStar,
        register=register,
    )
    astrbot_module = install_stub_module(monkeypatch, "astrbot")
    astrbot_module.api = astrbot_api_module
    astrbot_api_module.event = astrbot_event_module
    astrbot_api_module.star = astrbot_star_module

    install_stub_module(
        monkeypatch,
        "astrbot_orchestrator_v5.autonomous.debugger",
        SelfDebugger=type("SelfDebugger", (), {}),
    )
    install_stub_module(
        monkeypatch,
        "astrbot_orchestrator_v5.autonomous.executor",
        ExecutionManager=type("ExecutionManager", (), {}),
    )
    install_stub_module(
        monkeypatch,
        "astrbot_orchestrator_v5.autonomous.mcp_configurator",
        MCPConfiguratorTool=type("MCPConfiguratorTool", (), {}),
    )
    install_stub_module(
        monkeypatch,
        "astrbot_orchestrator_v5.autonomous.plugin_manager",
        PluginManagerTool=type("PluginManagerTool", (), {}),
    )
    install_stub_module(
        monkeypatch,
        "astrbot_orchestrator_v5.autonomous.skill_creator",
        SkillCreatorTool=type("SkillCreatorTool", (), {}),
    )
    install_stub_module(
        monkeypatch,
        "astrbot_orchestrator_v5.entrypoints",
        CommandHandlers=FakeCommandHandlers,
    )
    install_stub_module(
        monkeypatch,
        "astrbot_orchestrator_v5.orchestrator.agent_coordinator",
        AgentCoordinator=type("AgentCoordinator", (), {}),
    )
    install_stub_module(
        monkeypatch,
        "astrbot_orchestrator_v5.orchestrator.capability_builder",
        AgentCapabilityBuilder=type("AgentCapabilityBuilder", (), {}),
    )
    install_stub_module(
        monkeypatch,
        "astrbot_orchestrator_v5.orchestrator.core",
        DynamicOrchestrator=type("DynamicOrchestrator", (), {}),
    )
    install_stub_module(
        monkeypatch,
        "astrbot_orchestrator_v5.orchestrator.dynamic_agent_manager",
        DynamicAgentManager=type("DynamicAgentManager", (), {}),
    )
    install_stub_module(
        monkeypatch,
        "astrbot_orchestrator_v5.orchestrator.mcp_bridge",
        MCPBridge=type("MCPBridge", (), {}),
    )
    install_stub_module(
        monkeypatch,
        "astrbot_orchestrator_v5.orchestrator.meta_orchestrator",
        MetaOrchestrator=type("MetaOrchestrator", (), {}),
    )
    install_stub_module(
        monkeypatch,
        "astrbot_orchestrator_v5.orchestrator.skill_loader",
        AstrBotSkillLoader=type("AstrBotSkillLoader", (), {}),
    )
    install_stub_module(
        monkeypatch,
        "astrbot_orchestrator_v5.orchestrator.task_analyzer",
        TaskAnalyzer=type("TaskAnalyzer", (), {}),
    )
    install_stub_module(
        monkeypatch,
        "astrbot_orchestrator_v5.runtime.container",
        RuntimeContainer=FakeRuntimeContainer,
    )
    install_stub_module(
        monkeypatch,
        "astrbot_orchestrator_v5.runtime.request_context",
        RequestContext=FakeRequestContext,
    )
    install_stub_module(
        monkeypatch,
        "astrbot_orchestrator_v5.workflow.engine",
        WorkflowEngine=type("WorkflowEngine", (), {}),
    )

    monkeypatch.delitem(sys.modules, "astrbot_orchestrator_v5.main", raising=False)
    module = importlib.import_module("astrbot_orchestrator_v5.main")

    return MainTestHarness(
        module=module,
        config_cls=FakeAstrBotConfig,
        context_cls=FakeContext,
        event_cls=FakeAstrMessageEvent,
        runtime_cls=FakeRuntime,
        runtime_container_cls=FakeRuntimeContainer,
        request_context_cls=FakeRequestContext,
        command_handlers_cls=FakeCommandHandlers,
    )


async def collect_results(iterator: AsyncIterator[Any]) -> list[Any]:
    """收集异步生成器的所有结果。"""

    return [item async for item in iterator]


@pytest.mark.asyncio
async def test_main_plugin_initialize_binds_runtime_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """初始化应构建运行时、回绑组件，并保持幂等。"""

    harness = load_main_module(monkeypatch)
    runtime = harness.runtime_cls(
        exports={"debugger": "dbg", "mcp_bridge": "bridge", "orchestrator": "orch"}
    )
    harness.runtime_container_cls.runtime_to_return = runtime
    harness.runtime_container_cls.build_calls.clear()
    harness.command_handlers_cls.instances.clear()
    context = harness.context_cls()
    config = harness.config_cls(
        {
            "enable_dynamic_agents": True,
            "force_subagents_for_complex_tasks": False,
        }
    )
    plugin = harness.module.OrchestratorPlugin(context, config)

    await plugin.initialize()
    await plugin.initialize()

    assert plugin.config is config
    assert plugin.runtime is runtime
    assert plugin.debugger == "dbg"
    assert plugin.mcp_bridge == "bridge"
    assert plugin.orchestrator == "orch"
    assert plugin._initialized is True
    assert harness.runtime_container_cls.build_calls == [(context, config)]
    assert len(harness.command_handlers_cls.instances) == 1
    assert plugin.command_handlers is harness.command_handlers_cls.instances[0]
    assert plugin.command_handlers.context is context
    assert plugin.command_handlers.runtime is runtime
    assert harness.module.OrchestratorPlugin._register_kwargs["name"] == "astrbot_orchestrator"


def test_main_plugin_build_request_context_uses_default_config_and_command_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """请求上下文构建应透传参数，且默认配置和命令装饰器应生效。"""

    harness = load_main_module(monkeypatch)
    harness.request_context_cls.calls.clear()
    event = harness.event_cls("evt")
    plugin = harness.module.OrchestratorPlugin(harness.context_cls())

    request_context = plugin._build_request_context(
        event=event,
        user_request="solve task",
        provider_id="provider-x",
        entrypoint="agent",
    )

    assert isinstance(plugin.config, harness.config_cls)
    assert request_context == {
        "user_request": "solve task",
        "provider_id": "provider-x",
        "event": event,
        "metadata": {"entrypoint": "agent"},
    }
    assert harness.request_context_cls.calls == [request_context]
    assert harness.module.OrchestratorPlugin.handle_agent._command_name == "agent"
    assert harness.module.OrchestratorPlugin.handle_sandbox._command_name == "sandbox"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "expected_command"),
    [
        ("handle_agent", "agent"),
        ("handle_plugin", "plugin"),
        ("handle_skill", "skill"),
        ("handle_mcp", "mcp"),
        ("handle_exec", "exec"),
        ("handle_debug", "debug"),
        ("handle_sandbox", "sandbox"),
    ],
)
async def test_main_plugin_command_methods_delegate_to_command_handlers(
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
    expected_command: str,
) -> None:
    """所有命令入口都应委托给 `CommandHandlers`。"""

    harness = load_main_module(monkeypatch)
    harness.runtime_container_cls.runtime_to_return = harness.runtime_cls()
    harness.runtime_container_cls.build_calls.clear()
    harness.command_handlers_cls.instances.clear()
    plugin = harness.module.OrchestratorPlugin(
        harness.context_cls(),
        harness.config_cls({"enabled": True}),
    )
    event = harness.event_cls("evt")

    results = await collect_results(getattr(plugin, method_name)(event))

    assert results == [f"{expected_command}:evt"]
    assert harness.command_handlers_cls.instances[0].calls == [(expected_command, event)]
    assert harness.runtime_container_cls.build_calls == [(plugin.context, plugin.config)]


@pytest.mark.asyncio
async def test_main_plugin_handle_agent_raises_when_command_handlers_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """若初始化后仍无命令处理器，入口应抛出显式错误。"""

    harness = load_main_module(monkeypatch)
    plugin = harness.module.OrchestratorPlugin(harness.context_cls())

    async def fake_initialize() -> None:
        """模拟初始化完成但未绑定命令处理器。"""

        plugin._initialized = True

    monkeypatch.setattr(plugin, "initialize", fake_initialize)

    with pytest.raises(RuntimeError, match="命令处理器未初始化"):
        await collect_results(plugin.handle_agent(harness.event_cls("evt")))


@pytest.mark.asyncio
async def test_main_plugin_terminate_stops_runtime_only_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """终止插件时，仅在存在运行时时调用 `astop()`。"""

    harness = load_main_module(monkeypatch)
    plugin = harness.module.OrchestratorPlugin(harness.context_cls())

    await plugin.terminate()

    runtime = harness.runtime_cls()
    plugin.runtime = runtime
    await plugin.terminate()

    assert runtime.stop_calls == 1
