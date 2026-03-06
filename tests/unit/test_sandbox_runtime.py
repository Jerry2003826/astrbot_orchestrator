"""SandboxRuntime 单元测试。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

from astrbot_orchestrator_v5.autonomous.sandbox_runtime import SandboxRuntime

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


class FakeContext:
    """提供最小配置读取能力的测试上下文。"""

    def __init__(self, config: dict[str, Any], should_raise: bool = False) -> None:
        """保存测试配置。"""

        self._config = config
        self._should_raise = should_raise

    def get_config(self) -> dict[str, Any]:
        """返回配置或按需抛错。"""

        if self._should_raise:
            raise RuntimeError("读取配置失败")
        return self._config


class FakeSandbox:
    """最小可用的沙盒替身。"""

    def __init__(
        self,
        mode: str,
        health: str = "healthy",
        start_error: Exception | None = None,
        health_error: Exception | None = None,
        stop_error: Exception | None = None,
    ) -> None:
        """初始化沙盒状态。"""

        self.mode = mode
        self.health = health
        self.start_error = start_error
        self.health_error = health_error
        self.stop_error = stop_error
        self.started = False
        self.stopped = False
        self.healthcheck_calls = 0

    async def astart(self) -> None:
        """启动沙盒。"""

        if self.start_error is not None:
            raise self.start_error
        self.started = True

    async def ahealthcheck(self) -> str:
        """返回当前健康状态。"""

        self.healthcheck_calls += 1
        if self.health_error is not None:
            raise self.health_error
        return self.health

    async def astop(self) -> None:
        """停止沙盒。"""

        self.stopped = True
        if self.stop_error is not None:
            raise self.stop_error


class FakeSandboxFactory:
    """按模式返回预置沙盒的工厂替身。"""

    def __init__(self, sandboxes_by_mode: dict[str, list[FakeSandbox]]) -> None:
        """保存各模式的返回队列。"""

        self.sandboxes_by_mode = {
            mode: list(sandboxes) for mode, sandboxes in sandboxes_by_mode.items()
        }
        self.calls: list[str] = []
        self.invocations: list[dict[str, Any]] = []

    def __call__(
        self,
        mode: str,
        context: Any = None,
        event: Any = None,
        session_id: str | None = None,
        cwd: str = "/workspace",
        timeout: float = 30.0,
    ) -> FakeSandbox:
        """返回预置沙盒并记录调用信息。"""

        del context
        del event
        self.calls.append(mode)
        self.invocations.append(
            {
                "mode": mode,
                "session_id": session_id,
                "cwd": cwd,
                "timeout": timeout,
            }
        )

        sandboxes = self.sandboxes_by_mode.setdefault(mode, [])
        if sandboxes:
            return sandboxes.pop(0)
        return FakeSandbox(mode=mode)


class FakeFixer:
    """环境修复器替身。"""

    def __init__(self) -> None:
        """初始化记录容器。"""

        self.seen_errors: list[str] = []

    async def check_and_fix_environment(self, error_msg: str) -> tuple[bool, str]:
        """记录错误并模拟修复成功。"""

        self.seen_errors.append(error_msg)
        return True, "fixed"


class BrokenFixer:
    """始终在修复阶段抛错的替身。"""

    async def check_and_fix_environment(self, error_msg: str) -> tuple[bool, str]:
        """模拟修复器自身异常。"""

        del error_msg
        raise RuntimeError("fixer crashed")


@pytest.mark.parametrize(
    ("inside_sandbox", "run_mode", "expected"),
    [
        (True, "sandbox", "local"),
        (False, "local", "local"),
        (False, "none", "local"),
        (False, "sandbox", "shipyard"),
    ],
)
def test_sandbox_runtime_detect_mode_uses_host_and_config(
    inside_sandbox: bool,
    run_mode: str,
    expected: str,
) -> None:
    """应综合宿主环境与配置推断沙盒模式。"""

    runtime = SandboxRuntime(
        context=FakeContext({"computer_use": {"run_mode": run_mode}}),
        config={},
        inside_sandbox_detector=lambda: inside_sandbox,
    )

    assert runtime.detect_mode() == expected


def test_sandbox_runtime_detect_mode_returns_auto_when_context_errors() -> None:
    """无法读取 AstrBot 配置时应回退到 auto。"""

    runtime = SandboxRuntime(
        context=FakeContext({}, should_raise=True),
        config={},
        inside_sandbox_detector=lambda: False,
    )

    assert runtime.detect_mode() == "auto"


@pytest.mark.asyncio
async def test_sandbox_runtime_reuses_healthy_cached_sandbox() -> None:
    """健康缓存应直接复用，不重复创建沙盒。"""

    sandbox = FakeSandbox(mode="local")
    factory = FakeSandboxFactory({"local": [sandbox]})
    runtime = SandboxRuntime(
        context=FakeContext({}),
        config={},
        sandbox_factory=factory,
        inside_sandbox_detector=lambda: False,
    )

    first = await runtime.get_sandbox(mode="local", session_id="s1")
    second = await runtime.get_sandbox(mode="local", session_id="s1")

    assert first is second
    assert factory.calls == ["local"]
    assert sandbox.healthcheck_calls == 1


@pytest.mark.asyncio
async def test_sandbox_runtime_recreates_unhealthy_cached_sandbox() -> None:
    """缓存沙盒失健康时应移除并重新创建。"""

    first_sandbox = FakeSandbox(mode="local", health="unhealthy")
    second_sandbox = FakeSandbox(mode="local")
    factory = FakeSandboxFactory({"local": [first_sandbox, second_sandbox]})
    runtime = SandboxRuntime(
        context=FakeContext({}),
        config={},
        sandbox_factory=factory,
        inside_sandbox_detector=lambda: False,
    )

    first = await runtime.get_sandbox(mode="local", session_id="s1")
    second = await runtime.get_sandbox(mode="local", session_id="s1")

    assert first is first_sandbox
    assert second is second_sandbox
    assert factory.calls == ["local", "local"]


@pytest.mark.asyncio
async def test_sandbox_runtime_recreates_cached_sandbox_when_healthcheck_errors() -> None:
    """缓存沙盒健康检查抛错时也应丢弃并重建。"""

    first_sandbox = FakeSandbox(mode="local", health_error=RuntimeError("health boom"))
    second_sandbox = FakeSandbox(mode="local")
    factory = FakeSandboxFactory({"local": [first_sandbox, second_sandbox]})
    runtime = SandboxRuntime(
        context=FakeContext({}),
        config={},
        sandbox_factory=factory,
        inside_sandbox_detector=lambda: False,
    )

    first = await runtime.get_sandbox(mode="local", session_id="s1")
    second = await runtime.get_sandbox(mode="local", session_id="s1")

    assert first is first_sandbox
    assert second is second_sandbox
    assert factory.calls == ["local", "local"]


@pytest.mark.asyncio
async def test_sandbox_runtime_retries_after_auto_fix() -> None:
    """自动修复成功后应再次创建同模式沙盒。"""

    fixer = FakeFixer()
    first_sandbox = FakeSandbox(mode="shipyard", start_error=RuntimeError("boom"))
    second_sandbox = FakeSandbox(mode="shipyard")
    factory = FakeSandboxFactory({"shipyard": [first_sandbox, second_sandbox]})
    runtime = SandboxRuntime(
        context=FakeContext({}),
        config={"sandbox_create_retries": 0, "auto_fix_sandbox": True},
        sandbox_factory=factory,
        inside_sandbox_detector=lambda: False,
        env_fixer_factory=lambda: fixer,
    )

    sandbox = await runtime.get_sandbox(mode="shipyard", session_id="s1")

    assert sandbox is second_sandbox
    assert fixer.seen_errors == ["boom"]
    assert factory.calls == ["shipyard", "shipyard"]


@pytest.mark.asyncio
async def test_sandbox_runtime_retries_network_errors_before_success(
    monkeypatch: "MonkeyPatch",
) -> None:
    """网络错误应按次数等待重试，并在后续成功时返回新沙盒。"""

    first_sandbox = FakeSandbox(
        mode="shipyard",
        start_error=RuntimeError("Connection refused"),
    )
    second_sandbox = FakeSandbox(mode="shipyard")
    factory = FakeSandboxFactory({"shipyard": [first_sandbox, second_sandbox]})
    runtime = SandboxRuntime(
        context=FakeContext({}),
        config={"sandbox_create_retries": 1, "auto_fix_sandbox": False},
        sandbox_factory=factory,
        inside_sandbox_detector=lambda: False,
    )
    sleep_calls: list[int] = []

    async def fake_sleep(seconds: float) -> None:
        """记录重试等待秒数。"""

        sleep_calls.append(int(seconds))

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    sandbox = await runtime.get_sandbox(mode="shipyard", session_id="s1")

    assert sandbox is second_sandbox
    assert factory.calls == ["shipyard", "shipyard"]
    assert sleep_calls == [3]


@pytest.mark.asyncio
async def test_sandbox_runtime_wait_before_retry_skips_non_network_errors() -> None:
    """非网络错误即使未达重试上限也不应等待重试。"""

    runtime = SandboxRuntime(
        context=FakeContext({}),
        config={"sandbox_create_retries": 2},
        inside_sandbox_detector=lambda: False,
    )

    should_retry = await runtime._wait_before_retry(RuntimeError("plain boom"), attempt=0)

    assert should_retry is False


@pytest.mark.asyncio
async def test_sandbox_runtime_falls_back_to_local_when_enabled() -> None:
    """主模式失败且允许回退时，应切换到 local 模式。"""

    shipyard_sandbox = FakeSandbox(mode="shipyard", start_error=RuntimeError("connect failed"))
    local_sandbox = FakeSandbox(mode="local")
    factory = FakeSandboxFactory({"shipyard": [shipyard_sandbox], "local": [local_sandbox]})
    runtime = SandboxRuntime(
        context=FakeContext({}),
        config={
            "sandbox_create_retries": 0,
            "auto_fix_sandbox": False,
            "allow_local_fallback": True,
        },
        sandbox_factory=factory,
        inside_sandbox_detector=lambda: False,
    )

    sandbox = await runtime.get_sandbox(mode="shipyard", session_id="s1")

    assert sandbox is local_sandbox
    assert factory.calls == ["shipyard", "local"]
    assert runtime.cache_size == 1


@pytest.mark.asyncio
async def test_sandbox_runtime_fallback_or_raise_preserves_mode_specific_errors() -> None:
    """禁用回退时应区分 shipyard 包装错误与 local 原始错误。"""

    runtime = SandboxRuntime(
        context=FakeContext({}),
        config={"allow_local_fallback": False},
        inside_sandbox_detector=lambda: False,
    )
    shipyard_error = RuntimeError("ship failed")
    local_error = RuntimeError("local failed")

    with pytest.raises(RuntimeError, match="已拒绝自动回退到本地执行: ship failed"):
        await runtime._fallback_or_raise(
            "shipyard", event=None, session_id="s1", last_error=shipyard_error
        )

    with pytest.raises(RuntimeError, match="local failed"):
        await runtime._fallback_or_raise(
            "local", event=None, session_id="s1", last_error=local_error
        )


@pytest.mark.asyncio
async def test_sandbox_runtime_local_fallback_raises_original_error_when_local_fails() -> None:
    """local 回退自身失败时应重新抛出原始异常。"""

    last_error = RuntimeError("ship down")
    local_sandbox = FakeSandbox(mode="local", start_error=RuntimeError("local down"))
    factory = FakeSandboxFactory({"local": [local_sandbox]})
    runtime = SandboxRuntime(
        context=FakeContext({}),
        config={},
        sandbox_factory=factory,
        inside_sandbox_detector=lambda: False,
    )

    with pytest.raises(RuntimeError, match="ship down") as exc_info:
        await runtime._start_local_fallback(event=None, session_id="s1", last_error=last_error)

    assert exc_info.value.__cause__ is local_sandbox.start_error


@pytest.mark.asyncio
async def test_sandbox_runtime_create_primary_raises_retry_error_after_failed_fix(
    monkeypatch: "MonkeyPatch",
) -> None:
    """自动修复后仍失败时，应抛出修复阶段的最新异常。"""

    runtime = SandboxRuntime(
        context=FakeContext({}),
        config={"sandbox_create_retries": 0},
        inside_sandbox_detector=lambda: False,
    )

    async def fake_start_sandbox(
        self: SandboxRuntime,
        mode: str,
        event: Any,
        session_id: str | None,
        cache_key: str,
    ) -> FakeSandbox:
        """模拟主创建始终失败。"""

        del self
        del mode
        del event
        del session_id
        del cache_key
        raise RuntimeError("primary boom")

    async def fake_wait_before_retry(
        self: SandboxRuntime,
        error: Exception,
        attempt: int,
    ) -> bool:
        """禁止进入等待重试分支。"""

        del self
        del error
        del attempt
        return False

    async def fake_create_after_fix(
        self: SandboxRuntime,
        error: Exception,
        mode: str,
        event: Any,
        session_id: str | None,
        cache_key: str,
    ) -> FakeSandbox:
        """模拟修复后仍失败。"""

        del self
        del error
        del mode
        del event
        del session_id
        del cache_key
        raise RuntimeError("fix failed")

    monkeypatch.setattr(SandboxRuntime, "_start_sandbox", fake_start_sandbox)
    monkeypatch.setattr(SandboxRuntime, "_wait_before_retry", fake_wait_before_retry)
    monkeypatch.setattr(SandboxRuntime, "_create_after_fix", fake_create_after_fix)

    with pytest.raises(RuntimeError, match="fix failed"):
        await runtime._create_primary_sandbox(
            mode="shipyard",
            event=None,
            session_id="s1",
            cache_key="shipyard:s1",
        )


@pytest.mark.asyncio
async def test_sandbox_runtime_create_primary_raises_generic_error_when_no_attempts_run() -> None:
    """非法负重试配置导致零次尝试时，应抛出通用失败异常。"""

    runtime = SandboxRuntime(
        context=FakeContext({}),
        config={"sandbox_create_retries": -1},
        inside_sandbox_detector=lambda: False,
    )

    with pytest.raises(RuntimeError, match="未捕获到具体异常"):
        await runtime._create_primary_sandbox(
            mode="shipyard",
            event=None,
            session_id="s1",
            cache_key="shipyard:s1",
        )


@pytest.mark.asyncio
async def test_sandbox_runtime_create_after_fix_requires_non_empty_fix_message(
    monkeypatch: "MonkeyPatch",
) -> None:
    """修复器没有返回有效修复结果时，应重新抛出原始异常。"""

    runtime = SandboxRuntime(
        context=FakeContext({}),
        config={"auto_fix_sandbox": True},
        inside_sandbox_detector=lambda: False,
    )
    original_error = RuntimeError("ship failed")

    async def fake_try_auto_fix(self: SandboxRuntime, error_msg: str) -> str:
        """模拟修复器未能修复环境。"""

        del self
        del error_msg
        return ""

    monkeypatch.setattr(SandboxRuntime, "_try_auto_fix", fake_try_auto_fix)

    with pytest.raises(RuntimeError, match="ship failed"):
        await runtime._create_after_fix(
            error=original_error,
            mode="shipyard",
            event=None,
            session_id="s1",
            cache_key="shipyard:s1",
        )


@pytest.mark.asyncio
async def test_sandbox_runtime_astop_stops_cached_sandboxes() -> None:
    """停止运行时应关闭所有缓存沙盒并清空缓存。"""

    first_sandbox = FakeSandbox(mode="local")
    second_sandbox = FakeSandbox(mode="local")
    factory = FakeSandboxFactory({"local": [first_sandbox, second_sandbox]})
    runtime = SandboxRuntime(
        context=FakeContext({}),
        config={},
        sandbox_factory=factory,
        inside_sandbox_detector=lambda: False,
    )

    await runtime.get_sandbox(mode="local", session_id="s1")
    await runtime.get_sandbox(mode="local", session_id="s2")
    await runtime.astop()

    assert first_sandbox.stopped is True
    assert second_sandbox.stopped is True
    assert runtime.cache_size == 0


@pytest.mark.asyncio
async def test_sandbox_runtime_astop_ignores_stop_errors() -> None:
    """停止缓存沙盒时的异常不应阻断整体清理。"""

    first_sandbox = FakeSandbox(mode="local", stop_error=RuntimeError("stop failed"))
    second_sandbox = FakeSandbox(mode="local")
    factory = FakeSandboxFactory({"local": [first_sandbox, second_sandbox]})
    runtime = SandboxRuntime(
        context=FakeContext({}),
        config={},
        sandbox_factory=factory,
        inside_sandbox_detector=lambda: False,
    )

    await runtime.get_sandbox(mode="local", session_id="s1")
    await runtime.get_sandbox(mode="local", session_id="s2")
    await runtime.astop()

    assert first_sandbox.stopped is True
    assert second_sandbox.stopped is True
    assert runtime.cache_size == 0


@pytest.mark.asyncio
async def test_sandbox_runtime_try_auto_fix_handles_missing_and_broken_fixers(
    monkeypatch: "MonkeyPatch",
) -> None:
    """无修复器或修复器异常时都应返回空字符串。"""

    runtime_without_fixer = SandboxRuntime(
        context=FakeContext({}),
        config={},
        inside_sandbox_detector=lambda: False,
    )
    runtime_broken_fixer = SandboxRuntime(
        context=FakeContext({}),
        config={},
        inside_sandbox_detector=lambda: False,
        env_fixer_factory=BrokenFixer,
    )

    def fake_build_env_fixer(self: SandboxRuntime) -> Any:
        """模拟无法加载环境修复器。"""

        del self
        raise RuntimeError("import failed")

    with monkeypatch.context() as nested:
        nested.setattr(SandboxRuntime, "_build_env_fixer", fake_build_env_fixer)
        assert await runtime_without_fixer._try_auto_fix("boom") == ""

    assert await runtime_broken_fixer._try_auto_fix("boom") == ""


def test_sandbox_runtime_get_env_fixer_caches_instance_and_handles_build_failure(
    monkeypatch: "MonkeyPatch",
) -> None:
    """环境修复器应被缓存，构造失败时返回 None。"""

    fixer = FakeFixer()
    cached_runtime = SandboxRuntime(
        context=FakeContext({}),
        config={},
        inside_sandbox_detector=lambda: False,
        env_fixer_factory=lambda: fixer,
    )
    failed_runtime = SandboxRuntime(
        context=FakeContext({}),
        config={},
        inside_sandbox_detector=lambda: False,
    )

    first = cached_runtime._get_env_fixer()
    second = cached_runtime._get_env_fixer()

    def fake_build_env_fixer(self: SandboxRuntime) -> Any:
        """模拟构造修复器失败。"""

        del self
        raise RuntimeError("import failed")

    monkeypatch.setattr(SandboxRuntime, "_build_env_fixer", fake_build_env_fixer)

    assert first is fixer
    assert second is fixer
    assert failed_runtime._get_env_fixer() is None


def test_sandbox_runtime_build_env_fixer_and_network_error_detection() -> None:
    """默认修复器构造与网络错误识别都应正常工作。"""

    runtime = SandboxRuntime(
        context=FakeContext({}),
        config={},
        inside_sandbox_detector=lambda: False,
    )

    fixer = runtime._build_env_fixer()

    assert fixer.__class__.__name__ == "EnvironmentFixer"
    assert runtime._is_network_error(RuntimeError("Connection refused")) is True
    assert runtime._is_network_error(RuntimeError("plain failure")) is False


def test_fake_sandbox_factory_returns_default_sandbox_when_queue_empty() -> None:
    """工厂未预置实例时应回退为默认 FakeSandbox。"""

    factory = FakeSandboxFactory({})

    sandbox = factory(mode="local")

    assert isinstance(sandbox, FakeSandbox)
    assert sandbox.mode == "local"


@pytest.mark.asyncio
async def test_sandbox_runtime_derives_session_cache_key_and_workspace_from_event() -> None:
    """未显式传 session_id 时应从事件对象导出会话隔离信息。"""

    factory = FakeSandboxFactory({"local": [FakeSandbox(mode="local")]})
    runtime = SandboxRuntime(
        context=FakeContext({}),
        config={},
        sandbox_factory=factory,
        inside_sandbox_detector=lambda: False,
    )
    event = type("Evt", (), {"session_id": "chat-42"})()

    await runtime.get_sandbox(event=event, mode="local")

    assert factory.invocations[0]["session_id"] == "chat-42"
    assert factory.invocations[0]["cwd"].startswith("/workspace/sessions/")
