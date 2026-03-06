"""DynamicAgentManager 单元测试。"""

from __future__ import annotations

import importlib
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from astrbot_orchestrator_v5.orchestrator.agent_registry import AgentRecord
from astrbot_orchestrator_v5.orchestrator.agent_templates import AgentSpec

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


LOGGER_NAME = "dynamic-agent-manager-tests"


class FakeAstrbotConfig(dict[str, Any]):
    """带保存能力的 AstrBot 配置替身。"""

    def __init__(self, *args: Any, save_error: Exception | None = None, **kwargs: Any) -> None:
        """初始化配置对象。"""

        super().__init__(*args, **kwargs)
        self.save_calls = 0
        self.save_error = save_error

    def save_config(self) -> None:
        """记录保存动作，可选抛出异常。"""

        self.save_calls += 1
        if self.save_error is not None:
            raise self.save_error


class FakeOrchestrator:
    """SubAgent orchestrator 替身。"""

    def __init__(
        self,
        handoffs: list[str] | None = None,
        reload_error: Exception | None = None,
    ) -> None:
        """初始化 orchestrator。"""

        self.handoffs = handoffs or []
        self.reload_error = reload_error
        self.reload_calls: list[dict[str, Any]] = []

    async def reload_from_config(self, config: dict[str, Any]) -> None:
        """记录重载配置调用。"""

        self.reload_calls.append(config)
        if self.reload_error is not None:
            raise self.reload_error


class FakeRegisterToolsManager:
    """支持批量注册 handoff 的工具管理器。"""

    def __init__(self, error: Exception | None = None) -> None:
        """初始化调用记录。"""

        self.error = error
        self.calls: list[list[str]] = []

    def register_tools(self, handoffs: list[str]) -> None:
        """记录批量注册调用。"""

        if self.error is not None:
            raise self.error
        self.calls.append(list(handoffs))


class FakeRegisterToolManager:
    """支持逐个注册 handoff 的工具管理器。"""

    def __init__(self) -> None:
        """初始化调用记录。"""

        self.calls: list[str] = []

    def register_tool(self, handoff: str) -> None:
        """记录逐个注册调用。"""

        self.calls.append(handoff)


def load_dynamic_agent_manager_module(monkeypatch: pytest.MonkeyPatch) -> Any:
    """为测试安装假 astrbot 依赖并导入目标模块。"""

    astrbot_module = ModuleType("astrbot")
    api_module = ModuleType("astrbot.api")
    api_module.logger = logging.getLogger(LOGGER_NAME)
    astrbot_module.api = api_module
    monkeypatch.setitem(sys.modules, "astrbot", astrbot_module)
    monkeypatch.setitem(sys.modules, "astrbot.api", api_module)
    monkeypatch.delitem(
        sys.modules,
        "astrbot_orchestrator_v5.orchestrator.dynamic_agent_manager",
        raising=False,
    )
    return importlib.import_module("astrbot_orchestrator_v5.orchestrator.dynamic_agent_manager")


def make_context(
    *,
    get_config: Any | None = None,
    astrbot_config: Any | None = None,
    tool_manager: Any | None = None,
    orchestrator: Any | None = None,
) -> Any:
    """构造带可选依赖的 context 替身。"""

    context = SimpleNamespace()
    if get_config is not None:
        context.get_config = get_config
    if astrbot_config is not None:
        context.astrbot_config = astrbot_config
    if tool_manager is not None:
        context.provider_manager = SimpleNamespace(llm_tools=tool_manager)
    if orchestrator is not None:
        context.subagent_orchestrator = orchestrator
    return context


def make_spec(
    agent_id: str,
    name: str,
    role: str = "code",
    provider_id: str | None = None,
) -> AgentSpec:
    """构造测试用 AgentSpec。"""

    return AgentSpec(
        agent_id=agent_id,
        name=name,
        role=role,
        instructions=f"{role}-instructions",
        tools=["sandbox"],
        public_description=f"{role}-description",
        provider_id=provider_id,
        metadata={"source": "test"},
    )


@pytest.mark.asyncio
async def test_dynamic_agent_manager_create_agents_sets_defaults_deduplicates_and_exposes_summaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """创建动态代理时应设置默认 provider、处理重名并更新摘要。"""

    module = load_dynamic_agent_manager_module(monkeypatch)
    fixed_now = datetime(2024, 1, 1, 12, 0, 0)
    monkeypatch.setattr(module, "_utcnow", lambda: fixed_now)

    save_calls: list[str] = []
    reload_calls: list[str] = []
    manager = module.DynamicAgentManager(
        context=make_context(),
        config={"llm_provider": "provider-default"},
    )

    async def fake_save_to_config() -> None:
        """记录保存调用。"""

        save_calls.append("save")

    async def fake_reload_subagents() -> None:
        """记录重载调用。"""

        reload_calls.append("reload")

    monkeypatch.setattr(manager, "_save_to_config", fake_save_to_config)
    monkeypatch.setattr(manager, "_reload_subagents", fake_reload_subagents)

    first = make_spec("agent-1", "coder")
    second = make_spec("agent-2", "coder", role="test", provider_id="provider-custom")

    created = await manager.create_agents([first, second])

    assert created == [first, second]
    assert first.provider_id == "provider-default"
    assert second.provider_id == "provider-custom"
    assert first.name == "coder"
    assert second.name == "coder_2"
    assert save_calls == ["save"]
    assert reload_calls == ["reload"]
    assert "当前动态 SubAgent：" in manager.list_agents()
    assert "- coder (code) [active] @ 12:00:00" in manager.list_agents()
    assert "code" in manager.get_template_config()


def test_dynamic_agent_manager_provider_and_template_overrides_cover_all_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """provider 与模板 override 应覆盖配置、文件、JSON 字符串与默认值。"""

    module = load_dynamic_agent_manager_module(monkeypatch)
    plugin_config_path = tmp_path / "astrbot_orchestrator_config.json"
    plugin_config_path.write_text(
        json.dumps({"llm_provider": "provider-from-file"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "PLUGIN_CONFIG_PATH", str(plugin_config_path))
    assert module._utcnow().tzinfo is not None

    direct_manager = module.DynamicAgentManager(
        context=make_context(),
        config={
            "llm_provider": "provider-from-config",
            "subagent_template_overrides": {"code": {"name": "custom_code"}},
        },
    )
    nested_manager = module.DynamicAgentManager(
        context=make_context(),
        config={
            "subagent_settings": {
                "subagent_template_overrides": {"review": {"name": "review_agent"}}
            }
        },
    )
    string_manager = module.DynamicAgentManager(
        context=make_context(),
        config={"subagent_template_overrides": json.dumps({"research": {"name": "researcher"}})},
    )
    bad_settings_manager = module.DynamicAgentManager(
        context=make_context(),
        config={"subagent_settings": "bad"},
    )

    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    invalid_manager = module.DynamicAgentManager(
        context=make_context(),
        config={"subagent_template_overrides": "{invalid-json"},
    )

    assert direct_manager._get_default_provider_id() == "provider-from-config"
    assert nested_manager._get_default_provider_id() == "provider-from-file"
    assert string_manager._load_template_overrides() == {"research": {"name": "researcher"}}
    assert bad_settings_manager._load_template_overrides() == {}
    assert direct_manager.template_library.get("code").name == "custom_code"
    assert nested_manager.template_library.get("review").name == "review_agent"
    assert invalid_manager._load_template_overrides() == {}
    assert "解析 subagent_template_overrides 失败" in caplog.text

    no_provider_path = tmp_path / "no_provider.json"
    no_provider_path.write_text(json.dumps({}), encoding="utf-8")
    no_provider_file_manager = module.DynamicAgentManager(
        context=make_context(),
        config={},
    )
    monkeypatch.setattr(module, "PLUGIN_CONFIG_PATH", str(no_provider_path))
    assert no_provider_file_manager._get_default_provider_id() == "openai_1/qwen-max-latest"

    default_manager = module.DynamicAgentManager(context=make_context(), config={})
    monkeypatch.setattr(module, "PLUGIN_CONFIG_PATH", str(tmp_path / "missing.json"))

    assert default_manager._get_default_provider_id() == "openai_1/qwen-max-latest"
    assert "读取 orchestrator 插件配置失败" in caplog.text


def test_dynamic_agent_manager_handles_non_dict_runtime_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """运行时传入非字典配置时，应走默认 provider 与空 override。"""

    module = load_dynamic_agent_manager_module(monkeypatch)
    monkeypatch.setattr(module, "PLUGIN_CONFIG_PATH", str(tmp_path / "missing.json"))
    manager = module.DynamicAgentManager(
        context=make_context(),
        config=cast(Any, "invalid-config"),
    )

    assert manager._load_template_overrides() == {}
    assert manager._get_default_provider_id() == "openai_1/qwen-max-latest"


def test_dynamic_agent_manager_accessors_and_get_astrbot_config_cover_success_and_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """上下文访问器应覆盖成功、属性回退与异常日志。"""

    module = load_dynamic_agent_manager_module(monkeypatch)
    tool_manager = FakeRegisterToolsManager()
    orchestrator = FakeOrchestrator()
    config_object: dict[str, dict[str, Any]] = {"subagent_orchestrator": {}}
    manager = module.DynamicAgentManager(
        context=make_context(
            get_config=lambda: config_object,
            tool_manager=tool_manager,
            orchestrator=orchestrator,
        ),
    )
    fallback_manager = module.DynamicAgentManager(
        context=make_context(astrbot_config={"subagent_orchestrator": {"agents": []}}),
    )

    assert manager._get_tool_manager() is tool_manager
    assert manager._get_subagent_orchestrator() is orchestrator
    assert manager._get_astrbot_config() is config_object
    assert fallback_manager._get_astrbot_config() == {"subagent_orchestrator": {"agents": []}}

    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    broken_manager = module.DynamicAgentManager(
        context=make_context(
            get_config=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        ),
    )
    missing_tool_manager = module.DynamicAgentManager(context=make_context())

    assert broken_manager._get_astrbot_config() is None
    assert missing_tool_manager._get_tool_manager() is None
    assert "获取 AstrBot 配置对象失败: boom" in caplog.text


def test_dynamic_agent_manager_load_base_agents_covers_memory_file_and_error_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """基础代理加载应覆盖内存配置、文件回退与异常兜底。"""

    module = load_dynamic_agent_manager_module(monkeypatch)
    file_path = tmp_path / "cmd_config.json"
    file_path.write_text(
        json.dumps(
            {
                "subagent_orchestrator": {
                    "agents": [
                        {"name": "static_file"},
                        {"name": "dynamic_file", "_dynamic_": True},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "CONFIG_PATH", str(file_path))

    memory_manager = module.DynamicAgentManager(
        context=make_context(
            get_config=lambda: {
                "subagent_orchestrator": {
                    "agents": [
                        {"name": "static_memory"},
                        {"name": "dynamic_memory", "_dynamic_": True},
                    ]
                }
            }
        ),
    )
    file_manager = module.DynamicAgentManager(context=make_context())

    assert memory_manager._load_base_agents() == [{"name": "static_memory"}]
    assert file_manager._load_base_agents() == [{"name": "static_file"}]

    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    broken_manager = module.DynamicAgentManager(context=make_context())
    monkeypatch.setattr(
        broken_manager,
        "_get_astrbot_config",
        lambda: (_ for _ in ()).throw(RuntimeError("broken config")),
    )
    invalid_agents_manager = module.DynamicAgentManager(
        context=make_context(
            get_config=lambda: {"subagent_orchestrator": {"agents": {"bad": "shape"}}}
        ),
    )

    assert broken_manager._load_base_agents() == []
    assert invalid_agents_manager._load_base_agents() == []
    assert "加载配置失败: broken config" in caplog.text


@pytest.mark.asyncio
async def test_dynamic_agent_manager_save_to_config_dispatches_and_logs_errors(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """统一保存入口应覆盖内存、文件与异常路径。"""

    module = load_dynamic_agent_manager_module(monkeypatch)
    manager = module.DynamicAgentManager(context=make_context())
    calls: list[str] = []

    async def fake_save_to_memory_config(config: Any) -> None:
        """记录内存保存。"""

        calls.append(f"memory:{bool(config)}")

    async def fake_save_to_file_config() -> None:
        """记录文件保存。"""

        calls.append("file")

    monkeypatch.setattr(manager, "_save_to_memory_config", fake_save_to_memory_config)
    monkeypatch.setattr(manager, "_save_to_file_config", fake_save_to_file_config)
    monkeypatch.setattr(manager, "_get_astrbot_config", lambda: {"in_memory": True})

    await manager._save_to_config()

    monkeypatch.setattr(manager, "_get_astrbot_config", lambda: None)
    await manager._save_to_config()

    caplog.set_level(logging.ERROR, logger=LOGGER_NAME)

    async def broken_save_to_memory_config(config: Any) -> None:
        """抛出保存异常。"""

        raise RuntimeError("cannot save")

    monkeypatch.setattr(manager, "_get_astrbot_config", lambda: {"in_memory": True})
    monkeypatch.setattr(manager, "_save_to_memory_config", broken_save_to_memory_config)

    await manager._save_to_config()

    assert calls == ["memory:True", "file"]
    assert "保存 SubAgent 配置失败: cannot save" in caplog.text


@pytest.mark.asyncio
async def test_dynamic_agent_manager_save_to_memory_and_file_configs_preserve_static_agents(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """内存与文件保存都应保留静态代理并刷新动态代理列表。"""

    module = load_dynamic_agent_manager_module(monkeypatch)
    fixed_now = datetime(2024, 1, 1, 12, 34, 56)
    monkeypatch.setattr(module, "_utcnow", lambda: fixed_now)
    file_path = tmp_path / "cmd_config.json"
    file_path.write_text(
        json.dumps(
            {
                "subagent_orchestrator": {
                    "agents": [
                        {"name": "static_agent"},
                        {"name": "old_dynamic", "_dynamic_": True},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "CONFIG_PATH", str(file_path))
    manager = module.DynamicAgentManager(context=make_context())
    manager._dynamic_agents["agent-1"] = make_spec("agent-1", "new_dynamic")

    astrbot_config = FakeAstrbotConfig(
        {
            "subagent_orchestrator": {
                "agents": [
                    {"name": "memory_static"},
                    {"name": "memory_old_dynamic", "_dynamic_": True},
                ]
            }
        }
    )
    await manager._save_to_memory_config(astrbot_config)
    await manager._save_to_file_config()

    file_config = json.loads(file_path.read_text(encoding="utf-8"))
    memory_agents = astrbot_config["subagent_orchestrator"]["agents"]
    file_agents = file_config["subagent_orchestrator"]["agents"]

    assert astrbot_config.save_calls == 1
    assert [agent["name"] for agent in memory_agents] == ["memory_static", "new_dynamic"]
    assert [agent["name"] for agent in file_agents] == ["static_agent", "new_dynamic"]
    assert memory_agents[1]["_dynamic_"] is True
    assert file_agents[1]["_created_at_"] == "2024-01-01T12:34:56"


@pytest.mark.asyncio
async def test_dynamic_agent_manager_save_to_memory_config_falls_back_when_save_method_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """内存配置对象缺少 save_config 时应回退到文件保存。"""

    module = load_dynamic_agent_manager_module(monkeypatch)
    manager = module.DynamicAgentManager(context=make_context())
    manager._dynamic_agents["agent-1"] = make_spec("agent-1", "new_dynamic")
    fallback_calls: list[str] = []

    async def fake_save_to_file_config() -> None:
        """记录文件回退。"""

        fallback_calls.append("file")

    monkeypatch.setattr(manager, "_save_to_file_config", fake_save_to_file_config)
    monkeypatch.setattr(module, "_utcnow", lambda: datetime(2024, 1, 1, 0, 0, 0))

    await manager._save_to_memory_config({})
    await manager._save_to_memory_config({"subagent_orchestrator": {}})

    assert fallback_calls == ["file", "file"]


@pytest.mark.asyncio
async def test_dynamic_agent_manager_save_to_file_config_handles_missing_sections(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """文件保存应覆盖缺失 subagent_orchestrator 和缺失 agents 键。"""

    module = load_dynamic_agent_manager_module(monkeypatch)
    fixed_now = datetime(2024, 1, 1, 8, 0, 0)
    monkeypatch.setattr(module, "_utcnow", lambda: fixed_now)
    file_path = tmp_path / "cmd_config.json"
    monkeypatch.setattr(module, "CONFIG_PATH", str(file_path))
    manager = module.DynamicAgentManager(context=make_context())
    manager._dynamic_agents["agent-1"] = make_spec("agent-1", "new_dynamic")

    file_path.write_text(json.dumps({}), encoding="utf-8")
    await manager._save_to_file_config()
    first_config = json.loads(file_path.read_text(encoding="utf-8"))

    file_path.write_text(json.dumps({"subagent_orchestrator": {}}), encoding="utf-8")
    await manager._save_to_file_config()
    second_config = json.loads(file_path.read_text(encoding="utf-8"))

    assert first_config["subagent_orchestrator"]["agents"][0]["name"] == "new_dynamic"
    assert second_config["subagent_orchestrator"]["agents"][0]["_dynamic_"] is True


@pytest.mark.asyncio
async def test_dynamic_agent_manager_cleanup_removes_agents_from_memory_config_after_pop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cleanup 应在移除运行时代理后仍能从配置里删掉对应项。"""

    module = load_dynamic_agent_manager_module(monkeypatch)
    astrbot_config = FakeAstrbotConfig(
        {
            "subagent_orchestrator": {
                "agents": [
                    {"name": "static_agent"},
                    {"name": "cleanup_me", "_dynamic_": True},
                ]
            }
        }
    )
    reload_calls: list[str] = []
    manager = module.DynamicAgentManager(
        context=make_context(get_config=lambda: astrbot_config),
    )
    spec = make_spec("agent-1", "cleanup_me")
    manager._dynamic_agents[spec.agent_id] = spec
    manager.registry.register(
        AgentRecord(
            agent_id=spec.agent_id,
            name=spec.name,
            role=spec.role,
            status="active",
            created_at=datetime(2024, 1, 1, 10, 0, 0),
            spec=spec,
            metadata=spec.metadata,
        )
    )

    async def fake_reload_subagents() -> None:
        """记录重载动作。"""

        reload_calls.append("reload")

    monkeypatch.setattr(manager, "_reload_subagents", fake_reload_subagents)

    await manager.cleanup([spec])

    assert manager._dynamic_agents == {}
    assert manager.registry.get(spec.agent_id) is None
    assert astrbot_config.save_calls == 1
    assert astrbot_config["subagent_orchestrator"]["agents"] == [{"name": "static_agent"}]
    assert reload_calls == ["reload"]


@pytest.mark.asyncio
async def test_dynamic_agent_manager_remove_from_config_covers_file_and_error_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """配置移除应覆盖无匹配、文件回退与异常日志。"""

    module = load_dynamic_agent_manager_module(monkeypatch)
    file_path = tmp_path / "cmd_config.json"
    file_path.write_text(
        json.dumps(
            {
                "subagent_orchestrator": {
                    "agents": [
                        {"name": "keep_me"},
                        {"name": "remove_me", "_dynamic_": True},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "CONFIG_PATH", str(file_path))

    manager = module.DynamicAgentManager(context=make_context())
    manager._dynamic_agents["agent-1"] = make_spec("agent-1", "remove_me")

    await manager._remove_from_config([])
    assert json.loads(file_path.read_text(encoding="utf-8"))["subagent_orchestrator"]["agents"] == [
        {"name": "keep_me"},
        {"name": "remove_me", "_dynamic_": True},
    ]

    await manager._remove_from_config(["agent-1"])
    assert json.loads(file_path.read_text(encoding="utf-8"))["subagent_orchestrator"]["agents"] == [
        {"name": "keep_me"}
    ]

    missing_section_path = tmp_path / "missing_section.json"
    missing_section_path.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(module, "CONFIG_PATH", str(missing_section_path))
    await manager._remove_from_config(["agent-1"])

    missing_agents_path = tmp_path / "missing_agents.json"
    missing_agents_path.write_text(
        json.dumps({"subagent_orchestrator": {}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "CONFIG_PATH", str(missing_agents_path))
    await manager._remove_from_config(["agent-1"])

    caplog.set_level(logging.ERROR, logger=LOGGER_NAME)
    monkeypatch.setattr(
        manager,
        "_get_astrbot_config",
        lambda: (_ for _ in ()).throw(RuntimeError("cannot remove")),
    )

    await manager._remove_from_config(["agent-1"])
    assert "移除 SubAgent 配置失败: cannot remove" in caplog.text


@pytest.mark.asyncio
async def test_dynamic_agent_manager_remove_from_config_falls_through_when_memory_config_cannot_save(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """内存配置无 save_config 时，应继续落到文件配置移除路径。"""

    module = load_dynamic_agent_manager_module(monkeypatch)
    file_path = tmp_path / "cmd_config.json"
    file_path.write_text(
        json.dumps(
            {
                "subagent_orchestrator": {
                    "agents": [
                        {"name": "keep_me"},
                        {"name": "remove_me", "_dynamic_": True},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "CONFIG_PATH", str(file_path))

    manager = module.DynamicAgentManager(
        context=make_context(
            get_config=lambda: {
                "subagent_orchestrator": {
                    "agents": [
                        {"name": "keep_me"},
                        {"name": "remove_me", "_dynamic_": True},
                    ]
                }
            }
        ),
    )
    manager._dynamic_agents["agent-1"] = make_spec("agent-1", "remove_me")

    await manager._remove_from_config(["agent-1"])

    assert json.loads(file_path.read_text(encoding="utf-8"))["subagent_orchestrator"]["agents"] == [
        {"name": "keep_me"}
    ]


@pytest.mark.asyncio
async def test_dynamic_agent_manager_remove_from_config_reads_file_when_memory_section_has_no_agents(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """内存配置缺少 agents 时，应继续读取文件配置完成删除。"""

    module = load_dynamic_agent_manager_module(monkeypatch)
    file_path = tmp_path / "cmd_config.json"
    file_path.write_text(
        json.dumps(
            {
                "subagent_orchestrator": {
                    "agents": [
                        {"name": "keep_me"},
                        {"name": "remove_me", "_dynamic_": True},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "CONFIG_PATH", str(file_path))
    manager = module.DynamicAgentManager(
        context=make_context(get_config=lambda: {"subagent_orchestrator": {}}),
    )
    manager._dynamic_agents["agent-1"] = make_spec("agent-1", "remove_me")

    await manager._remove_from_config(["agent-1"])

    assert json.loads(file_path.read_text(encoding="utf-8"))["subagent_orchestrator"]["agents"] == [
        {"name": "keep_me"}
    ]


@pytest.mark.asyncio
async def test_dynamic_agent_manager_reload_subagents_covers_warning_success_and_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """重载流程应覆盖 orchestrator 缺失、内存成功、文件失败与注册异常。"""

    module = load_dynamic_agent_manager_module(monkeypatch)
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    no_orchestrator_manager = module.DynamicAgentManager(context=make_context())
    await no_orchestrator_manager._reload_subagents()
    assert "SubAgentOrchestrator 不可用" in caplog.text

    tool_manager = FakeRegisterToolsManager()
    orchestrator = FakeOrchestrator(handoffs=["handoff-a", "handoff-b"])
    memory_manager = module.DynamicAgentManager(
        context=make_context(
            get_config=lambda: {"subagent_orchestrator": {"agents": [{"name": "alpha"}]}},
            tool_manager=tool_manager,
            orchestrator=orchestrator,
        )
    )
    await memory_manager._reload_subagents()

    assert orchestrator.reload_calls == [{"agents": [{"name": "alpha"}]}]
    assert tool_manager.calls == [["handoff-a", "handoff-b"]]

    file_path = tmp_path / "cmd_config.json"
    file_path.write_text(
        json.dumps({"subagent_orchestrator": {"agents": [{"name": "file-agent"}]}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "CONFIG_PATH", str(file_path))
    file_orchestrator = FakeOrchestrator()
    file_manager = module.DynamicAgentManager(
        context=make_context(orchestrator=file_orchestrator),
    )
    await file_manager._reload_subagents()
    assert file_orchestrator.reload_calls == [{"agents": [{"name": "file-agent"}]}]

    missing_file_path = tmp_path / "missing_cmd_config.json"
    monkeypatch.setattr(module, "CONFIG_PATH", str(missing_file_path))
    caplog.set_level(logging.ERROR, logger=LOGGER_NAME)
    broken_orchestrator = FakeOrchestrator(reload_error=RuntimeError("reload failed"))
    broken_manager = module.DynamicAgentManager(
        context=make_context(orchestrator=broken_orchestrator),
    )

    await broken_manager._reload_subagents()

    assert broken_orchestrator.reload_calls == [{}]
    assert "读取配置文件失败" in caplog.text
    assert "注册 SubAgent 失败: reload failed" in caplog.text


@pytest.mark.asyncio
async def test_dynamic_agent_manager_register_handoffs_covers_all_tool_manager_paths(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """handoff 注册应覆盖无工具、空列表、批量、逐个与异常路径。"""

    module = load_dynamic_agent_manager_module(monkeypatch)
    manager = module.DynamicAgentManager(context=make_context())

    monkeypatch.setattr(manager, "_get_tool_manager", lambda: None)
    await manager._register_handoffs(FakeOrchestrator(handoffs=["ignored"]))

    no_handoff_manager = module.DynamicAgentManager(context=make_context())
    monkeypatch.setattr(
        no_handoff_manager,
        "_get_tool_manager",
        lambda: FakeRegisterToolsManager(),
    )
    await no_handoff_manager._register_handoffs(FakeOrchestrator(handoffs=[]))

    noop_manager = module.DynamicAgentManager(context=make_context())
    monkeypatch.setattr(noop_manager, "_get_tool_manager", lambda: object())
    await noop_manager._register_handoffs(FakeOrchestrator(handoffs=["noop"]))

    batch_manager = module.DynamicAgentManager(context=make_context())
    batch_tool_manager = FakeRegisterToolsManager()
    monkeypatch.setattr(batch_manager, "_get_tool_manager", lambda: batch_tool_manager)
    await batch_manager._register_handoffs(FakeOrchestrator(handoffs=["a", "b"]))

    single_manager = module.DynamicAgentManager(context=make_context())
    single_tool_manager = FakeRegisterToolManager()
    monkeypatch.setattr(single_manager, "_get_tool_manager", lambda: single_tool_manager)
    await single_manager._register_handoffs(FakeOrchestrator(handoffs=["x", "y"]))

    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    failing_manager = module.DynamicAgentManager(context=make_context())
    monkeypatch.setattr(
        failing_manager,
        "_get_tool_manager",
        lambda: FakeRegisterToolsManager(error=RuntimeError("handoff boom")),
    )
    await failing_manager._register_handoffs(FakeOrchestrator(handoffs=["z"]))

    assert batch_tool_manager.calls == [["a", "b"]]
    assert single_tool_manager.calls == ["x", "y"]
    assert "注册 Handoff 工具失败: handoff boom" in caplog.text
