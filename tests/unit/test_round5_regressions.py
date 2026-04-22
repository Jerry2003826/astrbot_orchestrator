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
from typing import Any, Dict, List

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


# ─────────────────────────────────────────────────────────────────
# Bug X: MCPBridge 空结果不应永久缓存
# ─────────────────────────────────────────────────────────────────


class _NoMcpToolManager:
    """模拟 FunctionToolManager 已存在但尚未加载任何 MCP 客户端。"""

    func_list: List[Any] = []
    mcp_client_dict: Dict[str, Any] = {}


def _make_context_with_tool_manager(manager: Any) -> Any:
    class _Ctx:
        def get_llm_tool_manager(self) -> Any:
            return manager

    return _Ctx()


def test_mcp_bridge_empty_result_not_cached() -> None:
    """FunctionToolManager 尚未就绪时,空结果不应让本会话被永久冻结。"""
    from astrbot_orchestrator_v5.orchestrator.mcp_bridge import MCPBridge

    bridge = MCPBridge(context=_make_context_with_tool_manager(_NoMcpToolManager()))

    first = bridge.list_tools()
    assert first == [], f"期望空列表,实际: {first}"
    assert bridge._cache_valid is False, "空结果不应标记缓存有效"


def test_mcp_bridge_non_empty_result_is_cached() -> None:
    """一旦获取到任何工具或服务器信息,就应正常缓存。"""
    from astrbot_orchestrator_v5.orchestrator.mcp_bridge import MCPBridge

    class _FakeMcpTool:
        name = "alpha"
        description = "desc"
        inputSchema: Dict[str, Any] = {}

    class _FakeClient:
        active = True
        tools = [_FakeMcpTool()]

    class _FakeToolManager:
        func_list: List[Any] = []
        mcp_client_dict = {"server-a": _FakeClient()}

    bridge = MCPBridge(context=_make_context_with_tool_manager(_FakeToolManager()))

    tools = bridge.list_tools()
    assert tools and tools[0]["name"] == "alpha"
    assert bridge._cache_valid is True, "非空结果应标记缓存有效"


def test_mcp_bridge_source_conditionally_caches() -> None:
    """静态检查 list_tools 只在非空时设置 cache_valid。"""
    from astrbot_orchestrator_v5.orchestrator import mcp_bridge

    src = inspect.getsource(mcp_bridge)
    idx = src.find("self._tools_cache = tools")
    assert idx != -1
    following = src[idx : idx + 400]
    assert "self._cache_valid = True" in following
    # 必须有 if 守卫,而不是无条件置 True
    assert "if tools or servers_info" in following, f"mcp_bridge 未对空结果做条件缓存:\n{following}"


# ─────────────────────────────────────────────────────────────────
# Bug Y: _extract_tools_from_mcp_clients 返回值类型注解
# ─────────────────────────────────────────────────────────────────


def test_extract_tools_signature_returns_tuple() -> None:
    """方法实际返回 (tools, servers_info) 元组,注解必须同步。"""
    from astrbot_orchestrator_v5.orchestrator.mcp_bridge import MCPBridge

    sig = inspect.signature(MCPBridge._extract_tools_from_mcp_clients)
    annotation = str(sig.return_annotation)
    assert "tuple" in annotation.lower() or "Tuple" in annotation, (
        f"返回值注解应为 tuple,实际: {annotation}"
    )
