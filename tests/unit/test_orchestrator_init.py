"""orchestrator 包级惰性导出测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import astrbot_orchestrator_v5.orchestrator as orchestrator_pkg


def test_orchestrator_getattr_returns_cached_export_and_dir_lists_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """惰性导出应成功加载并缓存，__dir__ 应包含公开符号。"""

    exported_value = object()
    monkeypatch.delitem(orchestrator_pkg.__dict__, "AgentRunner", raising=False)
    monkeypatch.setattr(
        orchestrator_pkg,
        "import_module",
        lambda module_name, package_name: SimpleNamespace(AgentRunner=exported_value),
    )

    value = orchestrator_pkg.__getattr__("AgentRunner")
    names = orchestrator_pkg.__dir__()

    assert value is exported_value
    assert orchestrator_pkg.__dict__["AgentRunner"] is exported_value
    assert names == sorted(set(orchestrator_pkg.__dict__) | set(orchestrator_pkg.__all__))
    assert "AgentRunner" in names


def test_orchestrator_exports_official_surface_only() -> None:
    """删除的自研编排符号不应再导出。"""

    assert set(orchestrator_pkg.__all__) == {
        "AgentRunner",
        "AstrBotSkillLoader",
        "DynamicAgentManager",
        "MCPBridge",
    }

    with pytest.raises(AttributeError):
        orchestrator_pkg.__getattr__("DynamicOrchestrator")

    with pytest.raises(AttributeError):
        orchestrator_pkg.__getattr__("MetaOrchestrator")


def test_orchestrator_real_exports_importable() -> None:
    """真实惰性导入应能解析全部公开符号。"""

    for name in orchestrator_pkg.__all__:
        orchestrator_pkg.__dict__.pop(name, None)
        assert orchestrator_pkg.__getattr__(name) is not None
