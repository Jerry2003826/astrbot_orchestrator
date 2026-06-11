"""第五轮 bug 修复回归测试。

覆盖:
    - Bug W: LocalSandbox.aexec 超时后未杀掉子进程,造成进程泄漏
    - Bug X: MCPBridge.list_tools 在未获取到任何数据时也把缓存标记为有效,
             导致 FunctionToolManager 初始化延迟场景下本会话永久空白
    - Bug Y: MCPBridge._extract_tools_from_mcp_clients 返回值类型注解
             声称是 List[Dict],实际返回 tuple[list, dict]
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Dict

import pytest

# ─────────────────────────────────────────────────────────────────
# Bug W: LocalSandbox.aexec 超时杀进程
# ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aexec_timeout_kills_subprocess() -> None:
    """aexec 超时后应返回中文错误并真正终止子进程。"""
    from astrbot_orchestrator_v5.sandbox.local_sandbox import LocalSandbox

    sandbox = LocalSandbox(cwd="/tmp", timeout=0.5)

    result = await asyncio.wait_for(
        sandbox.aexec(
            "while true; do echo x; sleep 0.01; done",
            kernel="bash",
            timeout=0.3,
        ),
        timeout=5.0,
    )

    assert "执行超时" in result.errors, f"期望超时提示,实际 errors={result.errors!r}"
    assert result.exit_code == -1


def test_aexec_timeout_branch_calls_kill() -> None:
    """静态检查:aexec 的 TimeoutError 分支必须包含 proc.kill()。"""
    from astrbot_orchestrator_v5.sandbox.local_sandbox import LocalSandbox

    src = inspect.getsource(LocalSandbox.aexec)
    # 定位 TimeoutError 处理块
    idx = src.find("except asyncio.TimeoutError")
    assert idx != -1, "未找到 asyncio.TimeoutError 处理分支"
    # 向后取 800 字符作为分支主体
    block = src[idx : idx + 800]
    assert "proc.kill()" in block, f"aexec 超时分支缺 proc.kill():\n{block}"
    assert "proc.wait()" in block, f"aexec 超时分支缺 proc.wait():\n{block}"


@pytest.mark.asyncio
async def test_aexec_timeout_cleans_up_process_handle() -> None:
    """超时回收后,proc.returncode 应被正确设置,说明进程已被 reap。"""
    import astrbot_orchestrator_v5.sandbox.local_sandbox as ls_mod

    captured: Dict[str, Any] = {}
    original_create = asyncio.create_subprocess_exec

    async def spy_create(*args: Any, **kwargs: Any):
        proc = await original_create(*args, **kwargs)
        captured["proc"] = proc
        return proc

    # 直接 monkeypatch 模块引用的 asyncio
    import asyncio as _asyncio_ref

    orig = _asyncio_ref.create_subprocess_exec
    _asyncio_ref.create_subprocess_exec = spy_create  # type: ignore[assignment]
    try:
        sandbox = ls_mod.LocalSandbox(cwd="/tmp", timeout=0.3)
        result = await asyncio.wait_for(
            sandbox.aexec(
                "while true; do echo x; sleep 0.01; done",
                kernel="bash",
                timeout=0.3,
            ),
            timeout=5.0,
        )
    finally:
        _asyncio_ref.create_subprocess_exec = orig  # type: ignore[assignment]

    assert "执行超时" in result.errors
    proc = captured.get("proc")
    assert proc is not None, "未捕获到子进程句柄"
    # 允许短暂等待进程被完全回收
    for _ in range(20):
        if proc.returncode is not None:
            break
        await asyncio.sleep(0.05)
    assert proc.returncode is not None, "超时后子进程未被回收,returncode 仍为 None"


# Bug X/Y（MCPBridge 缓存与 _extract_tools 注解）已随缓存机制删除：
# mcp_bridge 现直连官方 get_llm_tool_manager().mcp_client_dict，无缓存层。
