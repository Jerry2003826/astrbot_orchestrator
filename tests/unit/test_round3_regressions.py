"""第三轮 bug 修复回归测试（sandbox 部分）。

覆盖:
    - Bug O/P: LocalSandbox.astream_exec timeout 生效 + stderr 缓冲区大时不死锁
    - Bug Q: ainstall 拒绝 shell 注入 (LocalSandbox + 基类 CodeSandbox)

注：原 Bug R/S 针对的旧 DynamicAgentManager 路径解析与 AgentCoordinator
已随官方化迁移删除，相关测试一并移除。
"""

from __future__ import annotations

import asyncio

import pytest

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
