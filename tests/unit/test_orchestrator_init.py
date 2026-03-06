"""orchestrator 包级惰性导出测试。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

import astrbot_orchestrator_v5.orchestrator as orchestrator_pkg

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


def test_orchestrator_getattr_returns_cached_export_and_dir_lists_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """惰性导出应成功加载并缓存，__dir__ 应包含公开符号。"""

    exported_value = object()
    monkeypatch.delitem(
        orchestrator_pkg.__dict__,
        "AgentCapabilityBuilder",
        raising=False,
    )
    monkeypatch.setattr(
        orchestrator_pkg,
        "import_module",
        lambda module_name, package_name: SimpleNamespace(
            AgentCapabilityBuilder=exported_value
        ),
    )

    value = orchestrator_pkg.__getattr__("AgentCapabilityBuilder")
    names = orchestrator_pkg.__dir__()

    assert value is exported_value
    assert orchestrator_pkg.__dict__["AgentCapabilityBuilder"] is exported_value
    assert names == sorted(set(orchestrator_pkg.__dict__) | set(orchestrator_pkg.__all__))
    assert "AgentCapabilityBuilder" in names


def test_orchestrator_getattr_handles_unknown_and_missing_dependency_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """惰性导出应区分未知属性、AstrBot 缺失与其他缺失依赖。"""

    with pytest.raises(AttributeError):
        orchestrator_pkg.__getattr__("UnknownExport")

    monkeypatch.delitem(orchestrator_pkg.__dict__, "AstrBotSkillLoader", raising=False)

    def raise_astrbot_missing(module_name: str, package_name: str) -> SimpleNamespace:
        """模拟缺失 astrbot 依赖。"""

        raise ModuleNotFoundError("missing astrbot dependency", name="astrbot.core")

    monkeypatch.setattr(orchestrator_pkg, "import_module", raise_astrbot_missing)

    assert orchestrator_pkg.__getattr__("AstrBotSkillLoader") is None
    assert orchestrator_pkg.__dict__["AstrBotSkillLoader"] is None

    def raise_other_missing(module_name: str, package_name: str) -> SimpleNamespace:
        """模拟缺失非 astrbot 依赖。"""

        raise ModuleNotFoundError("missing yaml dependency", name="yaml")

    monkeypatch.setattr(orchestrator_pkg, "import_module", raise_other_missing)

    with pytest.raises(ModuleNotFoundError, match="yaml"):
        orchestrator_pkg.__getattr__("MetaOrchestrator")
