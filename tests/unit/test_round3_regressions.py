"""第三轮 bug 修复回归测试。

覆盖:
    - Bug O/P: LocalSandbox.astream_exec timeout 生效 + stderr 缓冲区大时不死锁
    - Bug Q: ainstall 拒绝 shell 注入 (LocalSandbox + 基类 CodeSandbox)
    - Bug R: DynamicAgentManager 的路径 getter 每次重新解析
    - Bug S: agent_coordinator 的 projects_dir 优先级链
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from pathlib import Path
import sys
from types import ModuleType

import pytest

LOGGER_NAME = "astrbot_orchestrator_v5.tests.round3"


# ─────────────────────────────────────────────────────────────────
# Bug O: LocalSandbox.astream_exec timeout 真正生效
# ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_astream_exec_timeout_kills_runaway_process() -> None:
    from astrbot_orchestrator_v5.sandbox.local_sandbox import LocalSandbox

    sandbox = LocalSandbox(cwd="/tmp", timeout=0.5)
    chunks: list[tuple[str, str]] = []

    # 用 bash 写一个会永久循环输出的死循环
    async for chunk in sandbox.astream_exec(
        "while true; do echo x; sleep 0.01; done",
        kernel="bash",
        timeout=0.5,
    ):
        chunks.append((chunk.type, chunk.content))
        if len(chunks) > 1000:  # 安全阈值: 不能无限吐
            pytest.fail(f"超时未生效,累计收到 {len(chunks)} chunk")

    stderr_msgs = [c for t, c in chunks if t == "stderr"]
    status_msgs = [c for t, c in chunks if t == "status"]
    assert any("执行超时" in msg for msg in stderr_msgs), (
        f"期望收到超时 stderr,实际 stderr={stderr_msgs[:5]}"
    )
    assert status_msgs, "期望收到 status chunk 表示进程已终止"


# ─────────────────────────────────────────────────────────────────
# Bug P: stderr 缓冲区超过 64KB 时不死锁
# ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_astream_exec_handles_large_stderr_without_deadlock() -> None:
    from astrbot_orchestrator_v5.sandbox.local_sandbox import LocalSandbox

    sandbox = LocalSandbox(cwd="/tmp", timeout=10.0)

    # 向 stderr 输出 200KB,stdout 输出小量 'done'
    # 旧实现 (顺序读 stdout→stderr) 会在 stderr 管道被 64KB 写满时死锁
    code = "printf 'E%.0s' $(seq 1 200000) 1>&2 ; echo done"

    async def collect() -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        async for chunk in sandbox.astream_exec(code, kernel="bash", timeout=5.0):
            out.append((chunk.type, chunk.content))
        return out

    chunks = await asyncio.wait_for(collect(), timeout=8.0)

    stdout_text = "".join(c for t, c in chunks if t == "stdout")
    stderr_text = "".join(c for t, c in chunks if t == "stderr")

    assert "done" in stdout_text, f"stdout 缺 done,可能死锁: stdout={stdout_text[:200]}"
    assert len(stderr_text) >= 100000, f"stderr 被截断 / 死锁: 只收到 {len(stderr_text)} 字节"


# ─────────────────────────────────────────────────────────────────
# Bug Q: LocalSandbox.ainstall shell 注入防御
# ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_local_sandbox_ainstall_escapes_shell_metacharacters() -> None:
    from astrbot_orchestrator_v5.sandbox.local_sandbox import LocalSandbox
    from astrbot_orchestrator_v5.sandbox.types import ExecResult

    sandbox = LocalSandbox(cwd="/tmp")
    captured: list[str] = []

    async def fake_aexec(code, kernel="ipython", timeout=None, cwd=None):
        captured.append(code)
        return ExecResult(text="", errors="", exit_code=0, kernel=kernel)

    sandbox.aexec = fake_aexec  # type: ignore[method-assign]

    await sandbox.ainstall("requests; rm -rf /")
    assert captured, "aexec 未被调用"
    cmd = captured[0]
    # shlex.quote 对含空格和 ; 的字符串会用单引号包裹,并对内部单引号做转义
    assert "'requests; rm -rf /'" in cmd, (
        f"LocalSandbox.ainstall 未对恶意字符做 shell 引用: {cmd!r}"
    )


# ─────────────────────────────────────────────────────────────────
# Bug Q (part 2): 基类 CodeSandbox.ainstall 同样需要防注入
# 直接验证 shlex.quote 的行为,避免实例化抽象类的复杂性
# ─────────────────────────────────────────────────────────────────


def test_base_ainstall_source_uses_shlex_quote() -> None:
    """静态检查 sandbox/base.py 的 ainstall 实现使用了 shlex.quote。"""
    import inspect

    from astrbot_orchestrator_v5.sandbox.base import CodeSandbox

    src = inspect.getsource(CodeSandbox.ainstall)
    assert "shlex.quote" in src, f"CodeSandbox.ainstall 未使用 shlex.quote:\n{src}"
    # 确认不再是简单的 " ".join 然后拼到 shell 命令
    assert "pip install {pkg_str}" not in src, (
        f"CodeSandbox.ainstall 仍在直接拼接未转义的包名:\n{src}"
    )


# ─────────────────────────────────────────────────────────────────
# Bug R: dynamic_agent_manager 路径 getter 运行时解析
# ─────────────────────────────────────────────────────────────────


def _load_dam_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """为测试安装假 astrbot 依赖并 import 目标模块。"""
    astrbot_module = ModuleType("astrbot")
    api_module = ModuleType("astrbot.api")
    api_module.logger = logging.getLogger(LOGGER_NAME)  # type: ignore[attr-defined]
    astrbot_module.api = api_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "astrbot", astrbot_module)
    monkeypatch.setitem(sys.modules, "astrbot.api", api_module)
    monkeypatch.delitem(
        sys.modules,
        "astrbot_orchestrator_v5.orchestrator.dynamic_agent_manager",
        raising=False,
    )
    return importlib.import_module("astrbot_orchestrator_v5.orchestrator.dynamic_agent_manager")


def test_config_path_resolves_at_call_time_not_import_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dam = _load_dam_module(monkeypatch)

    new_root = tmp_path / "runtime_data"
    new_root.mkdir()

    monkeypatch.setenv("ASTRBOT_DATA_DIR", str(new_root))

    resolved_cfg = dam._config_path()
    resolved_plugin = dam._plugin_config_path()

    assert str(new_root) in resolved_cfg, f"_config_path 未响应环境变量: {resolved_cfg}"
    assert resolved_cfg.endswith("cmd_config.json")
    assert str(new_root) in resolved_plugin
    assert resolved_plugin.endswith("astrbot_orchestrator_config.json")


def test_resolve_astrbot_data_root_priority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dam = _load_dam_module(monkeypatch)

    monkeypatch.setenv("ASTRBOT_DATA_DIR", "/custom/data")
    assert str(dam._resolve_astrbot_data_root()) == "/custom/data"


# ─────────────────────────────────────────────────────────────────
# Bug S: agent_coordinator projects_dir 优先级
# ─────────────────────────────────────────────────────────────────


def test_agent_coordinator_projects_dir_prefers_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """模拟 AgentCoordinator._get_plugin_projects_dir —— 该方法不依赖 self,
    直接反射调用即可,不必完整构造协调器。"""

    import importlib

    from astrbot_orchestrator_v5.orchestrator import (
        agent_coordinator as ac_module,
    )

    importlib.reload(ac_module)  # 清缓存,避免其他测试污染
    env_root = tmp_path / "userdata"
    env_root.mkdir()

    monkeypatch.setenv("ASTRBOT_DATA_DIR", str(env_root))

    # 绕开 __init__: 用 __new__ 创建空实例,调用 bound method
    instance = ac_module.AgentCoordinator.__new__(ac_module.AgentCoordinator)
    resolved = instance._get_plugin_projects_dir()

    assert str(env_root) in resolved, f"未优先使用 ASTRBOT_DATA_DIR,实际落到: {resolved}"
    assert resolved.endswith("agent_projects")


def test_agent_coordinator_projects_dir_falls_back_to_cwd_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from astrbot_orchestrator_v5.orchestrator import (
        agent_coordinator as ac_module,
    )

    # 清除 env,cwd 有 data/ 目录时应落入其中
    monkeypatch.delenv("ASTRBOT_DATA_DIR", raising=False)
    monkeypatch.delenv("ASTRBOT_ROOT", raising=False)

    (tmp_path / "data").mkdir()
    monkeypatch.chdir(tmp_path)

    instance = ac_module.AgentCoordinator.__new__(ac_module.AgentCoordinator)
    resolved = instance._get_plugin_projects_dir()

    # 应落在 cwd/data/agent_projects 下
    assert resolved.endswith("agent_projects"), f"实际: {resolved}"
    assert str(tmp_path) in resolved, f"未落到 cwd 下的 data/agent_projects,实际: {resolved}"


# ─────────────────────────────────────────────────────────────────
# 回归: 上一轮 `/AstrBot` 硬编码已修复 —— 确认仍未回退
# ─────────────────────────────────────────────────────────────────


def test_no_more_hardcoded_astrbot_root_as_only_path(tmp_path: Path) -> None:
    """在非 Docker 环境下,任何地方都不该把 /AstrBot 作为唯一选项。"""
    import inspect

    import astrbot_orchestrator_v5.orchestrator.agent_coordinator as ac
    import astrbot_orchestrator_v5.orchestrator.core as core_mod

    src_ac = inspect.getsource(ac.AgentCoordinator._get_plugin_projects_dir)
    src_core = inspect.getsource(core_mod)

    # 如果源码中出现 /AstrBot,必须是候选之一而非唯一路径
    for src, name in [(src_ac, "agent_coordinator"), (src_core, "core")]:
        if "/AstrBot" in src:
            # 必须同时出现 ASTRBOT_DATA_DIR 或 candidates 之类的多候选标记
            assert (
                "ASTRBOT_DATA_DIR" in src or "candidates" in src.lower() or "ASTRBOT_ROOT" in src
            ), f"{name} 仍把 /AstrBot 当唯一路径"
