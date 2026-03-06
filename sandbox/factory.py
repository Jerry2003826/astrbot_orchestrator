"""
沙盒工厂 - 根据配置创建合适的沙盒实例

支持三种模式：
- local: 本地 subprocess 执行（无隔离）
- shipyard: 通过 AstrBot Shipyard Bay 执行（Docker 隔离）
- auto: 自动检测，优先使用 Shipyard，回退到 local

特殊逻辑：
- 当检测到当前进程已运行在 Shipyard 沙盒容器内时，
  自动使用 local 模式，避免嵌套创建沙盒。
"""

from __future__ import annotations

import logging
import os
import socket
import typing as t
from importlib.util import find_spec

from .base import CodeSandbox

logger = logging.getLogger(__name__)

# 缓存检测结果，避免重复检测
_inside_sandbox_cache: t.Optional[bool] = None


def is_inside_shipyard_sandbox() -> bool:
    """
    检测当前进程是否运行在 Shipyard 沙盒容器内。

    检测方法（满足任一即判定为在沙盒内）：
    1. 环境变量 SHIPYARD_SANDBOX=1（由 Shipyard Bay 注入）
    2. hostname 以 "ship-" 开头（Shipyard 容器命名规则）
    3. 存在 /.shipyard 标记文件

    Returns:
        True 表示当前在 Shipyard 沙盒内
    """
    global _inside_sandbox_cache
    if _inside_sandbox_cache is not None:
        return _inside_sandbox_cache

    result = False

    # 方法1: 检查环境变量
    if os.environ.get("SHIPYARD_SANDBOX", "").strip() == "1":
        result = True

    # 方法2: 检查 hostname 是否以 ship- 开头
    if not result:
        try:
            hostname = socket.gethostname()
            if hostname.startswith("ship-"):
                result = True
        except Exception as exc:
            logger.debug("读取 hostname 失败，跳过 Shipyard hostname 检测: %s", exc)

    # 方法3: 检查标记文件
    if not result:
        if os.path.exists("/.shipyard"):
            result = True

    _inside_sandbox_cache = result
    if result:
        logger.info("[SandboxFactory] ✅ 检测到当前运行在 Shipyard 沙盒内，将使用 local 模式执行")
    return result


def create_sandbox(
    mode: t.Literal["local", "shipyard", "auto"] = "auto",
    context=None,
    event=None,
    session_id: t.Optional[str] = None,
    cwd: str = "/workspace",
    timeout: float = 30.0,
) -> CodeSandbox:
    """
    创建沙盒实例

    Args:
        mode: 沙盒模式
            - "local": 本地执行（无隔离）
            - "shipyard": Shipyard Docker 沙盒
            - "auto": 自动检测
        context: AstrBot Context 对象（shipyard 模式需要）
        event: AstrBot 消息事件（shipyard 模式需要）
        session_id: 会话 ID
        cwd: 工作目录
        timeout: 默认超时时间

    Returns:
        CodeSandbox 实例

    Note:
        当检测到已在 Shipyard 沙盒内运行时，即使指定 shipyard 模式，
        也会自动降级为 local 模式，避免嵌套创建沙盒容器。
    """
    # 🔑 核心逻辑：如果已在沙盒内，强制使用 local 模式
    if mode in ("shipyard", "auto") and is_inside_shipyard_sandbox():
        logger.info("[SandboxFactory] 已在 Shipyard 沙盒内，跳过嵌套沙盒创建，使用 local 模式")
        return _create_local(session_id=session_id, cwd=cwd, timeout=timeout)

    if mode == "local":
        return _create_local(session_id=session_id, cwd=cwd, timeout=timeout)

    if mode == "shipyard":
        return _create_shipyard(
            context=context,
            event=event,
            session_id=session_id,
            cwd=cwd,
            timeout=timeout,
        )

    # auto 模式：尝试 shipyard，回退到 local
    if mode == "auto":
        if context and event:
            try:
                return _create_shipyard(
                    context=context,
                    event=event,
                    session_id=session_id,
                    cwd=cwd,
                    timeout=timeout,
                )
            except Exception as e:
                logger.warning("[SandboxFactory] Shipyard 不可用，回退到 local: %s", e)

        return _create_local(session_id=session_id, cwd=cwd, timeout=timeout)

    raise ValueError(f"未知的沙盒模式: {mode}")


def _create_local(
    session_id: t.Optional[str] = None,
    cwd: str = "/workspace",
    timeout: float = 30.0,
) -> CodeSandbox:
    """创建本地沙盒"""
    from .local_sandbox import LocalSandbox

    logger.info("[SandboxFactory] 创建 LocalSandbox")
    return LocalSandbox(session_id=session_id, cwd=cwd, timeout=timeout)


def _create_shipyard(
    context=None,
    event=None,
    session_id: t.Optional[str] = None,
    cwd: str = "/workspace",
    timeout: float = 30.0,
) -> CodeSandbox:
    """创建 Shipyard 沙盒"""
    from .shipyard_sandbox import ShipyardSandbox

    logger.info("[SandboxFactory] 创建 ShipyardSandbox")
    return ShipyardSandbox(
        context=context,
        event=event,
        session_id=session_id,
        cwd=cwd,
        timeout=timeout,
    )


async def detect_available_mode(context=None) -> str:
    """
    检测可用的沙盒模式

    Returns:
        "shipyard" 或 "local"
    """
    # 如果已在沙盒内，直接返回 local
    if is_inside_shipyard_sandbox():
        logger.info("[SandboxFactory] 已在 Shipyard 沙盒内，返回 local 模式")
        return "local"

    # 检查 Shipyard 是否可用
    try:
        if find_spec("astrbot.core.computer.computer_client") is None:
            return "local"
        logger.info("[SandboxFactory] Shipyard computer_client 可用")
        return "shipyard"
    except ImportError:
        pass

    return "local"
