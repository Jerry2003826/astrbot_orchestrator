"""DynamicAgentManager（官方 subagent 配置适配器）测试。"""

from __future__ import annotations

import pytest

from astrbot_orchestrator_v5.orchestrator.dynamic_agent_manager import (
    MANAGED_FLAG,
    MANAGED_VALUE,
    DynamicAgentManager,
)
from tests.conftest import FakeContext


@pytest.fixture
def manager(fake_context: FakeContext) -> DynamicAgentManager:
    return DynamicAgentManager(fake_context, {})


@pytest.mark.asyncio
async def test_sync_templates_writes_official_config(
    manager: DynamicAgentManager, fake_context: FakeContext
) -> None:
    result = await manager.sync_templates_to_host()

    assert "已注册" in result
    conf = fake_context.get_config()
    so_cfg = conf["subagent_orchestrator"]
    agents = so_cfg["agents"]

    # 模板库 5 个角色全部写入
    names = {a["name"] for a in agents}
    assert {"code_agent", "test_agent", "research_agent", "deploy_agent", "debug_agent"} <= names

    # 写入项带管理标记，键名对齐官方 reload_from_config
    for entry in agents:
        assert entry[MANAGED_FLAG] == MANAGED_VALUE
        assert {"name", "enabled", "system_prompt", "public_description", "tools"} <= set(entry)

    # main_enable 默认打开，handoffs 已热重载
    assert so_cfg["main_enable"] is True
    assert conf.save_count >= 1
    handoff_names = {h.name for h in fake_context.subagent_orchestrator.handoffs}
    assert "transfer_to_code_agent" in handoff_names


@pytest.mark.asyncio
async def test_sync_templates_does_not_duplicate_existing(
    manager: DynamicAgentManager, fake_context: FakeContext
) -> None:
    conf = fake_context.get_config()
    conf["subagent_orchestrator"] = {
        "agents": [{"name": "code_agent", "enabled": False, "system_prompt": "用户自定义"}]
    }

    await manager.sync_templates_to_host()

    agents = conf["subagent_orchestrator"]["agents"]
    code_entries = [a for a in agents if a["name"] == "code_agent"]
    # 用户已有的同名 agent 不被覆盖/重复
    assert len(code_entries) == 1
    assert code_entries[0]["system_prompt"] == "用户自定义"

    # 第二次同步幂等
    result = await manager.sync_templates_to_host()
    assert "无需更新" in result
    assert len(agents) == len({a["name"] for a in agents})


@pytest.mark.asyncio
async def test_remove_managed_agents_keeps_user_entries(
    manager: DynamicAgentManager, fake_context: FakeContext
) -> None:
    await manager.sync_templates_to_host()
    conf = fake_context.get_config()
    conf["subagent_orchestrator"]["agents"].append({"name": "user_agent", "system_prompt": "x"})

    result = await manager.remove_managed_agents()

    assert "已移除 5 个" in result
    remaining = conf["subagent_orchestrator"]["agents"]
    assert [a["name"] for a in remaining] == ["user_agent"]


@pytest.mark.asyncio
async def test_status_report_reads_official_handoffs(
    manager: DynamicAgentManager, fake_context: FakeContext
) -> None:
    assert "没有已注册的子代理" in manager.status_report()

    await manager.sync_templates_to_host()
    report = manager.status_report()

    assert "code_agent" in report
    assert "5" in report


def test_templates_report_lists_roles(manager: DynamicAgentManager) -> None:
    report = manager.templates_report()

    for role in ("code", "test", "research", "deploy", "debug"):
        assert role in report
    assert "/agent sync" in report


@pytest.mark.asyncio
async def test_sync_survives_missing_host_orchestrator(
    fake_context: FakeContext,
) -> None:
    fake_context.subagent_orchestrator = None
    manager = DynamicAgentManager(fake_context, {})

    result = await manager.sync_templates_to_host()

    # 配置仍写入，热重载被跳过且不抛异常
    assert "已注册" in result
    assert fake_context.get_config()["subagent_orchestrator"]["agents"]
