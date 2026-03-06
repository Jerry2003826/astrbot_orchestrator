"""沙盒工厂测试。"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import TYPE_CHECKING, Any

import pytest

from astrbot_orchestrator_v5.sandbox import factory

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


def make_module(name: str, **attributes: Any) -> ModuleType:
    """构造带指定属性的假模块。"""

    module = ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def build_recording_class(class_name: str) -> type[Any]:
    """创建记录构造参数的替身类。"""

    class RecordingClass:
        """记录初始化参数。"""

        instances: list[Any] = []

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            """保存构造参数。"""

            self.args = args
            self.kwargs = kwargs
            self.__class__.instances.append(self)

    RecordingClass.__name__ = class_name
    return RecordingClass


@pytest.fixture(autouse=True)
def reset_inside_sandbox_cache() -> None:
    """每个测试前重置沙盒内检测缓存。"""

    factory._inside_sandbox_cache = None


def test_is_inside_shipyard_sandbox_detects_env_and_uses_cache(
    monkeypatch: "MonkeyPatch",
) -> None:
    """环境变量命中后应返回 True，并复用缓存结果。"""

    monkeypatch.setenv("SHIPYARD_SANDBOX", "1")

    def forbidden_hostname() -> str:
        """若被调用则说明没有命中缓存分支。"""

        raise AssertionError("hostname 不应被调用")

    monkeypatch.setattr(factory.socket, "gethostname", forbidden_hostname)

    assert factory.is_inside_shipyard_sandbox() is True

    monkeypatch.delenv("SHIPYARD_SANDBOX", raising=False)
    assert factory.is_inside_shipyard_sandbox() is True


def test_is_inside_shipyard_sandbox_falls_back_to_marker_file(
    monkeypatch: "MonkeyPatch",
) -> None:
    """hostname 检测失败时应继续检查 shipyard 标记文件。"""

    monkeypatch.delenv("SHIPYARD_SANDBOX", raising=False)

    def raise_hostname_error() -> str:
        """模拟 hostname 读取失败。"""

        raise RuntimeError("hostname failed")

    monkeypatch.setattr(factory.socket, "gethostname", raise_hostname_error)
    monkeypatch.setattr(factory.os.path, "exists", lambda path: path == "/.shipyard")

    assert factory.is_inside_shipyard_sandbox() is True


def test_is_inside_shipyard_sandbox_detects_hostname_prefix(
    monkeypatch: "MonkeyPatch",
) -> None:
    """hostname 以 ship- 开头时应识别为沙盒内运行。"""

    monkeypatch.delenv("SHIPYARD_SANDBOX", raising=False)
    monkeypatch.setattr(factory.socket, "gethostname", lambda: "ship-demo")
    monkeypatch.setattr(factory.os.path, "exists", lambda _path: False)

    assert factory.is_inside_shipyard_sandbox() is True


def test_is_inside_shipyard_sandbox_returns_false_without_any_markers(
    monkeypatch: "MonkeyPatch",
) -> None:
    """无环境变量、无特殊 hostname、无标记文件时应返回 False。"""

    monkeypatch.delenv("SHIPYARD_SANDBOX", raising=False)
    monkeypatch.setattr(factory.socket, "gethostname", lambda: "devbox")
    monkeypatch.setattr(factory.os.path, "exists", lambda _path: False)

    assert factory.is_inside_shipyard_sandbox() is False


def test_create_sandbox_uses_local_when_already_inside_shipyard(
    monkeypatch: "MonkeyPatch",
) -> None:
    """已在 Shipyard 内时，应强制回退到 local 模式。"""

    local_sandbox = object()
    monkeypatch.setattr(factory, "is_inside_shipyard_sandbox", lambda: True)
    monkeypatch.setattr(factory, "_create_local", lambda **kwargs: (local_sandbox, kwargs))

    result = factory.create_sandbox(
        mode="shipyard",
        context="ctx",
        event="evt",
        session_id="session-x",
        cwd="/workspace/demo",
        timeout=9.0,
    )

    assert result == (
        local_sandbox,
        {"session_id": "session-x", "cwd": "/workspace/demo", "timeout": 9.0},
    )


def test_create_sandbox_routes_local_and_shipyard_modes(
    monkeypatch: "MonkeyPatch",
) -> None:
    """显式模式应路由到对应创建函数。"""

    monkeypatch.setattr(factory, "is_inside_shipyard_sandbox", lambda: False)
    monkeypatch.setattr(factory, "_create_local", lambda **kwargs: ("local", kwargs))
    monkeypatch.setattr(factory, "_create_shipyard", lambda **kwargs: ("shipyard", kwargs))

    local_result = factory.create_sandbox(mode="local", session_id="s1", cwd="/tmp/a", timeout=1.0)
    shipyard_result = factory.create_sandbox(
        mode="shipyard",
        context="ctx",
        event="evt",
        session_id="s2",
        cwd="/tmp/b",
        timeout=2.0,
    )

    assert local_result == (
        "local",
        {"session_id": "s1", "cwd": "/tmp/a", "timeout": 1.0},
    )
    assert shipyard_result == (
        "shipyard",
        {
            "context": "ctx",
            "event": "evt",
            "session_id": "s2",
            "cwd": "/tmp/b",
            "timeout": 2.0,
        },
    )


def test_create_sandbox_auto_prefers_shipyard_and_falls_back_to_local(
    monkeypatch: "MonkeyPatch",
) -> None:
    """auto 模式应优先 shipyard，失败时回退到 local。"""

    monkeypatch.setattr(factory, "is_inside_shipyard_sandbox", lambda: False)
    monkeypatch.setattr(factory, "_create_local", lambda **kwargs: ("local", kwargs))

    def fake_create_shipyard(**kwargs: Any) -> tuple[str, dict[str, Any]]:
        """第一次成功，第二次失败。"""

        if kwargs["session_id"] == "ok":
            return ("shipyard", kwargs)
        raise RuntimeError("shipyard unavailable")

    monkeypatch.setattr(factory, "_create_shipyard", fake_create_shipyard)

    preferred = factory.create_sandbox(
        mode="auto",
        context="ctx",
        event="evt",
        session_id="ok",
        cwd="/workspace",
        timeout=3.0,
    )
    fallback = factory.create_sandbox(
        mode="auto",
        context="ctx",
        event="evt",
        session_id="fallback",
        cwd="/workspace",
        timeout=4.0,
    )

    assert preferred == (
        "shipyard",
        {
            "context": "ctx",
            "event": "evt",
            "session_id": "ok",
            "cwd": "/workspace",
            "timeout": 3.0,
        },
    )
    assert fallback == (
        "local",
        {"session_id": "fallback", "cwd": "/workspace", "timeout": 4.0},
    )


def test_create_sandbox_auto_without_context_returns_local(
    monkeypatch: "MonkeyPatch",
) -> None:
    """缺少 context 或 event 时，auto 模式应直接使用 local。"""

    monkeypatch.setattr(factory, "is_inside_shipyard_sandbox", lambda: False)
    monkeypatch.setattr(factory, "_create_local", lambda **kwargs: ("local", kwargs))

    result = factory.create_sandbox(mode="auto", session_id="solo", cwd="/tmp/demo", timeout=5.0)

    assert result == (
        "local",
        {"session_id": "solo", "cwd": "/tmp/demo", "timeout": 5.0},
    )


def test_create_sandbox_rejects_unknown_mode(monkeypatch: "MonkeyPatch") -> None:
    """未知模式应抛出 ValueError。"""

    monkeypatch.setattr(factory, "is_inside_shipyard_sandbox", lambda: False)

    with pytest.raises(ValueError, match="未知的沙盒模式"):
        factory.create_sandbox(mode="unknown")  # type: ignore[arg-type]


def test_create_local_and_shipyard_helpers_build_expected_instances(
    monkeypatch: "MonkeyPatch",
) -> None:
    """底层 helper 应按参数构造 LocalSandbox 与 ShipyardSandbox。"""

    LocalSandbox = build_recording_class("LocalSandbox")
    ShipyardSandbox = build_recording_class("ShipyardSandbox")
    monkeypatch.setitem(
        sys.modules,
        "astrbot_orchestrator_v5.sandbox.local_sandbox",
        make_module("astrbot_orchestrator_v5.sandbox.local_sandbox", LocalSandbox=LocalSandbox),
    )
    monkeypatch.setitem(
        sys.modules,
        "astrbot_orchestrator_v5.sandbox.shipyard_sandbox",
        make_module(
            "astrbot_orchestrator_v5.sandbox.shipyard_sandbox",
            ShipyardSandbox=ShipyardSandbox,
        ),
    )

    local_instance = factory._create_local(session_id="s1", cwd="/tmp/local", timeout=1.5)
    shipyard_instance = factory._create_shipyard(
        context="ctx",
        event="evt",
        session_id="s2",
        cwd="/tmp/shipyard",
        timeout=2.5,
    )

    assert local_instance.kwargs == {
        "session_id": "s1",
        "cwd": "/tmp/local",
        "timeout": 1.5,
    }
    assert shipyard_instance.kwargs == {
        "context": "ctx",
        "event": "evt",
        "session_id": "s2",
        "cwd": "/tmp/shipyard",
        "timeout": 2.5,
    }


@pytest.mark.asyncio
async def test_detect_available_mode_checks_sandbox_and_import_availability(
    monkeypatch: "MonkeyPatch",
) -> None:
    """模式检测应优先已在沙盒，其次检查 shipyard 依赖是否可导入。"""

    monkeypatch.setattr(factory, "is_inside_shipyard_sandbox", lambda: True)
    assert await factory.detect_available_mode() == "local"

    monkeypatch.setattr(factory, "is_inside_shipyard_sandbox", lambda: False)
    monkeypatch.setattr(factory, "find_spec", lambda _name: object())
    assert await factory.detect_available_mode() == "shipyard"

    monkeypatch.setattr(factory, "find_spec", lambda _name: None)
    assert await factory.detect_available_mode() == "local"


@pytest.mark.asyncio
async def test_detect_available_mode_returns_local_when_import_check_errors(
    monkeypatch: "MonkeyPatch",
) -> None:
    """依赖可用性检查抛 ImportError 时应回退到 local。"""

    monkeypatch.setattr(factory, "is_inside_shipyard_sandbox", lambda: False)

    def raise_import_error(_name: str) -> object:
        """模拟 import 检查失败。"""

        raise ImportError("missing")

    monkeypatch.setattr(factory, "find_spec", raise_import_error)

    assert await factory.detect_available_mode() == "local"
