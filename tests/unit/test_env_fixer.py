"""EnvironmentFixer 单元测试。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

from astrbot_orchestrator_v5.autonomous.env_fixer import EnvironmentFixer

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


class FakeProcess:
    """模拟异步子进程对象。"""

    def __init__(self, stdout: bytes = b"", stderr: bytes = b"") -> None:
        """保存标准输出和错误输出。"""

        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        """返回预设的输出字节。"""

        return self._stdout, self._stderr


@pytest.mark.asyncio
async def test_environment_fixer_check_and_fix_environment_aggregates_actions(
    monkeypatch: "MonkeyPatch",
) -> None:
    """应收集所有可修复动作，并忽略返回 False 的分支。"""

    fixer = EnvironmentFixer()
    calls: list[tuple[str, str]] = []

    async def fake_fix_missing_images(error_msg: str) -> tuple[bool, str]:
        """模拟缺失镜像已修复。"""

        calls.append(("images", error_msg))
        return True, "镜像已修复"

    async def fake_ensure_shipyard_network() -> tuple[bool, str]:
        """模拟网络检测到但无需追加动作。"""

        calls.append(("network", ""))
        return False, "网络无需处理"

    async def fake_wait_ship_ready() -> tuple[bool, str]:
        """模拟等待容器成功。"""

        calls.append(("ready", ""))
        return True, "已等待就绪"

    monkeypatch.setattr(fixer, "_fix_missing_images", fake_fix_missing_images)
    monkeypatch.setattr(fixer, "_ensure_shipyard_network", fake_ensure_shipyard_network)
    monkeypatch.setattr(fixer, "_wait_ship_ready", fake_wait_ship_ready)

    fixed, message = await fixer.check_and_fix_environment(
        "No such image; network shipyard not found; Ship failed to become ready",
    )

    assert fixed is True
    assert message == "镜像已修复; 已等待就绪"
    assert calls == [
        ("images", "No such image; network shipyard not found; Ship failed to become ready"),
        ("network", ""),
        ("ready", ""),
    ]


@pytest.mark.asyncio
async def test_environment_fixer_check_and_fix_environment_returns_no_match() -> None:
    """没有匹配错误时应返回无法自动修复。"""

    fixer = EnvironmentFixer()

    fixed, message = await fixer.check_and_fix_environment("permission denied")

    assert fixed is False
    assert message == "未检测到可自动修复的问题"


@pytest.mark.asyncio
async def test_environment_fixer_check_and_fix_environment_keeps_only_successful_actions(
    monkeypatch: "MonkeyPatch",
) -> None:
    """命中关键词但部分修复失败时，应仅保留成功动作。"""

    fixer = EnvironmentFixer()

    async def fake_fix_missing_images(error_msg: str) -> tuple[bool, str]:
        """模拟镜像修复失败。"""

        del error_msg
        return False, "镜像修复失败"

    async def fake_ensure_shipyard_network() -> tuple[bool, str]:
        """模拟网络修复成功。"""

        return True, "已创建 shipyard 网络"

    async def fake_wait_ship_ready() -> tuple[bool, str]:
        """模拟等待就绪失败。"""

        return False, "等待失败"

    monkeypatch.setattr(fixer, "_fix_missing_images", fake_fix_missing_images)
    monkeypatch.setattr(fixer, "_ensure_shipyard_network", fake_ensure_shipyard_network)
    monkeypatch.setattr(fixer, "_wait_ship_ready", fake_wait_ship_ready)

    fixed, message = await fixer.check_and_fix_environment(
        "no such image; network shipyard not found; Ship failed to become ready",
    )

    assert fixed is True
    assert message == "已创建 shipyard 网络"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_msg", "remote_tag", "local_tag"),
    [
        (
            "No such image: ship:latest",
            "soulter/shipyard-ship:latest",
            "ship:latest",
        ),
        (
            "no such image: shipyard-bay:latest",
            "soulter/shipyard-bay:latest",
            "shipyard-bay:latest",
        ),
    ],
)
async def test_environment_fixer_fix_missing_images_runs_pull_and_tag(
    error_msg: str,
    remote_tag: str,
    local_tag: str,
    monkeypatch: "MonkeyPatch",
) -> None:
    """命中缺失镜像时应拉取并重新打 tag。"""

    fixer = EnvironmentFixer()
    commands: list[list[str]] = []

    async def fake_run_cmd(cmd: list[str]) -> str:
        """记录命令并返回空输出。"""

        commands.append(cmd)
        return ""

    monkeypatch.setattr(fixer, "_run_cmd", fake_run_cmd)

    fixed, message = await fixer._fix_missing_images(error_msg)

    assert fixed is True
    assert message == f"已拉取镜像 {remote_tag} 并标记为 {local_tag}"
    assert commands == [
        ["docker", "pull", remote_tag],
        ["docker", "tag", remote_tag, local_tag],
    ]


@pytest.mark.asyncio
async def test_environment_fixer_fix_missing_images_returns_no_match(
    monkeypatch: "MonkeyPatch",
) -> None:
    """未命中镜像映射时不应执行任何命令。"""

    fixer = EnvironmentFixer()
    calls: list[list[str]] = []

    async def fake_run_cmd(cmd: list[str]) -> str:
        """记录命令但不会被调用。"""

        calls.append(cmd)
        return ""

    monkeypatch.setattr(fixer, "_run_cmd", fake_run_cmd)

    fixed, message = await fixer._fix_missing_images("No such image: unknown:latest")

    assert fixed is False
    assert message == "未匹配到缺失镜像"
    assert calls == []


@pytest.mark.asyncio
async def test_environment_fixer_ensure_shipyard_network_handles_existing_and_create(
    monkeypatch: "MonkeyPatch",
) -> None:
    """网络已存在时直接返回，否则应创建新网络。"""

    fixer = EnvironmentFixer()
    commands: list[list[str]] = []
    outputs = iter(["shipyard bridge\n", "", "created"])

    async def fake_run_cmd(cmd: list[str]) -> str:
        """按顺序返回预设命令输出。"""

        commands.append(cmd)
        return next(outputs)

    monkeypatch.setattr(fixer, "_run_cmd", fake_run_cmd)

    existing_fixed, existing_message = await fixer._ensure_shipyard_network()
    created_fixed, created_message = await fixer._ensure_shipyard_network()

    assert existing_fixed is True
    assert existing_message == "shipyard 网络已存在"
    assert created_fixed is True
    assert created_message == "已创建 shipyard 网络"
    assert commands == [
        ["docker", "network", "ls"],
        ["docker", "network", "ls"],
        ["docker", "network", "create", "shipyard"],
    ]


@pytest.mark.asyncio
async def test_environment_fixer_wait_ship_ready_sleeps_before_return(
    monkeypatch: "MonkeyPatch",
) -> None:
    """等待 ship ready 时应睡眠 5 秒。"""

    fixer = EnvironmentFixer()
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        """记录睡眠时长。"""

        sleep_calls.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    fixed, message = await fixer._wait_ship_ready()

    assert fixed is True
    assert message == "已等待 ship 容器启动"
    assert sleep_calls == [5]


@pytest.mark.asyncio
async def test_environment_fixer_run_cmd_merges_stdout_and_stderr(
    monkeypatch: "MonkeyPatch",
) -> None:
    """命令输出应合并 stdout 和 stderr 并去除首尾空白。"""

    recorded_cmds: list[tuple[str, ...]] = []

    async def fake_create_subprocess_exec(
        *cmd: str,
        stdout: Any = None,
        stderr: Any = None,
    ) -> FakeProcess:
        """返回预设进程对象。"""

        del stdout, stderr
        recorded_cmds.append(cmd)
        return FakeProcess(stdout=b" hello ", stderr=b"\nwarn ")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    fixer = EnvironmentFixer()

    output = await fixer._run_cmd(["docker", "ps"])

    assert output == "hello \nwarn"
    assert recorded_cmds == [("docker", "ps")]


@pytest.mark.asyncio
async def test_environment_fixer_run_cmd_returns_empty_on_exception(
    monkeypatch: "MonkeyPatch",
) -> None:
    """底层命令异常时应记录 warning 并返回空字符串。"""

    async def fail_create_subprocess_exec(
        *cmd: str,
        stdout: Any = None,
        stderr: Any = None,
    ) -> FakeProcess:
        """模拟命令启动失败。"""

        del cmd, stdout, stderr
        raise OSError("spawn failed")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fail_create_subprocess_exec)
    fixer = EnvironmentFixer()

    output = await fixer._run_cmd(["docker", "ps"])

    assert output == ""
