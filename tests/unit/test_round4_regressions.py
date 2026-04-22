"""第四轮 bug 修复回归测试。

覆盖:
    - Bug T: ShipyardSandbox.ainstall 命令注入 —— 必须对包名做 shlex.quote
    - Bug U: AutoPluginManager._fetch_plugin_registry 空结果不该被永久缓存
    - Bug V: SkillLoader 的 _skills_cache 同样不该在空结果时标记 cache_valid
"""

from __future__ import annotations

import inspect
import logging
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

LOGGER_NAME = "astrbot_orchestrator_v5.tests.round4"


# ─────────────────────────────────────────────────────────────────
# Bug T: ShipyardSandbox.ainstall 使用 shlex.quote
# ─────────────────────────────────────────────────────────────────


def test_shipyard_ainstall_source_uses_shlex_quote() -> None:
    """静态检查 sandbox/shipyard_sandbox.py 的 ainstall 实现。"""
    from astrbot_orchestrator_v5.sandbox.shipyard_sandbox import ShipyardSandbox

    src = inspect.getsource(ShipyardSandbox.ainstall)
    assert "shlex.quote" in src, f"ShipyardSandbox.ainstall 未使用 shlex.quote:\n{src}"
    # 确认不再是简单拼接
    assert "pip install {pkg_str}" not in src, (
        f"ShipyardSandbox.ainstall 仍在直接拼接未转义的包名:\n{src}"
    )


@pytest.mark.asyncio
async def test_shipyard_ainstall_escapes_malicious_package_name() -> None:
    """动态测试: 注入式包名被 shlex.quote 包裹在单引号内。"""
    from astrbot_orchestrator_v5.sandbox.shipyard_sandbox import ShipyardSandbox
    from astrbot_orchestrator_v5.sandbox.types import ExecResult

    sandbox = ShipyardSandbox.__new__(ShipyardSandbox)  # 绕开 __init__，不需要 booter
    captured: list[str] = []

    async def fake_aexec(code: str, kernel: str = "bash", **kwargs: Any) -> ExecResult:
        captured.append(code)
        return ExecResult(text="ok", errors="", exit_code=0, kernel=kernel)

    sandbox.aexec = fake_aexec  # type: ignore[method-assign]

    await sandbox.ainstall("requests; rm -rf /")
    assert captured, "aexec 未被调用"
    cmd = captured[0]
    assert "'requests; rm -rf /'" in cmd, (
        f"ShipyardSandbox.ainstall 未对恶意字符做 shell 引用: {cmd!r}"
    )


@pytest.mark.asyncio
async def test_shipyard_ainstall_handles_empty_packages() -> None:
    """空包列表不该触发 pip install 调用。"""
    from astrbot_orchestrator_v5.sandbox.shipyard_sandbox import ShipyardSandbox

    sandbox = ShipyardSandbox.__new__(ShipyardSandbox)
    calls: list[str] = []

    async def fake_aexec(code: str, **kwargs: Any) -> Any:
        calls.append(code)
        raise AssertionError("空包列表不应调用 aexec")

    sandbox.aexec = fake_aexec  # type: ignore[method-assign]

    result = await sandbox.ainstall()
    assert "未指定" in result, f"期望中文错误提示，实际: {result}"
    assert not calls, f"空包列表不应调用 aexec，但调用了: {calls}"


# ─────────────────────────────────────────────────────────────────
# Bug U: AutoPluginManager._fetch_plugin_registry 空结果不缓存
# ─────────────────────────────────────────────────────────────────


def _load_plugin_manager_module() -> ModuleType:
    """加载 autonomous.plugin_manager 所需的最小 astrbot 依赖。"""
    astrbot_module = sys.modules.get("astrbot") or ModuleType("astrbot")
    api_module = sys.modules.get("astrbot.api") or ModuleType("astrbot.api")
    api_module.logger = logging.getLogger(LOGGER_NAME)  # type: ignore[attr-defined]
    astrbot_module.api = api_module  # type: ignore[attr-defined]
    sys.modules.setdefault("astrbot", astrbot_module)
    sys.modules.setdefault("astrbot.api", api_module)
    import importlib

    return importlib.import_module("astrbot_orchestrator_v5.autonomous.plugin_manager")


@pytest.mark.asyncio
async def test_plugin_manager_empty_fetch_not_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pm_mod = _load_plugin_manager_module()

    fake_context = SimpleNamespace(_config={})
    manager = pm_mod.PluginManagerTool(fake_context)

    # 模拟网络失败 —— aiohttp.ClientSession 抛异常
    class _FakeSession:
        async def __aenter__(self) -> "_FakeSession":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        def get(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("network down")

    monkeypatch.setattr(pm_mod.aiohttp, "ClientSession", lambda: _FakeSession())

    result = await manager._fetch_plugin_registry()
    assert result == [], f"网络故障下应返回空列表，实际: {result}"
    assert manager._cache_valid is False, "空结果不应把 cache 标记为 valid"


@pytest.mark.asyncio
async def test_plugin_manager_non_empty_fetch_is_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pm_mod = _load_plugin_manager_module()

    fake_context = SimpleNamespace(_config={})
    manager = pm_mod.PluginManagerTool(fake_context)

    fake_plugins: list[dict[str, Any]] = [{"name": "demo", "desc": "d"}]

    class _FakeResp:
        status = 200

        async def json(self) -> list[dict[str, Any]]:
            return fake_plugins

        async def __aenter__(self) -> "_FakeResp":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

    class _FakeSession:
        async def __aenter__(self) -> "_FakeSession":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        def get(self, *args: Any, **kwargs: Any) -> _FakeResp:
            return _FakeResp()

    monkeypatch.setattr(pm_mod.aiohttp, "ClientSession", lambda: _FakeSession())

    result = await manager._fetch_plugin_registry()
    assert result == fake_plugins, f"应返回 fake_plugins，实际: {result}"
    assert manager._cache_valid is True, "非空结果应标记 cache valid"


# ─────────────────────────────────────────────────────────────────
# Bug V: SkillLoader 的 _skills_cache 空结果不缓存
# ─────────────────────────────────────────────────────────────────


def test_skill_loader_source_conditionally_caches() -> None:
    """静态检查 skill_loader.py 的 list_skills 只在非空时缓存。"""
    from astrbot_orchestrator_v5.orchestrator import skill_loader

    src = inspect.getsource(skill_loader)
    # 搜索 "self._skills_cache = skills" 上下文,确认紧跟的 cache_valid 赋值有条件
    assert "self._skills_cache = skills" in src
    # 确认不是无条件设置 True
    idx = src.find("self._skills_cache = skills")
    following = src[idx : idx + 400]
    assert "if skills" in following, f"skill_loader 未对空 skills 做条件缓存:\n{following}"
