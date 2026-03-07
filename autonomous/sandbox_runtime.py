"""沙盒生命周期与缓存运行时。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import logging
from typing import Any, Callable

from ..sandbox import CodeSandbox, create_sandbox, is_inside_shipyard_sandbox

logger = logging.getLogger(__name__)

_NETWORK_ERROR_KEYWORDS: tuple[str, ...] = (
    "name or service not known",
    "connection refused",
    "dns",
    "cannot connect",
)


@dataclass(slots=True)
class SandboxRuntime:
    """管理沙盒的模式探测、缓存、重试与清理。"""

    context: Any
    config: dict[str, Any]
    sandbox_factory: Callable[..., CodeSandbox] = create_sandbox
    inside_sandbox_detector: Callable[[], bool] = is_inside_shipyard_sandbox
    env_fixer_factory: Callable[[], Any] | None = None
    default_cwd: str = "/workspace"
    _env_fixer: Any | None = field(default=None, init=False, repr=False)
    _sandbox_cache: dict[str, CodeSandbox] = field(default_factory=dict, init=False, repr=False)

    @property
    def cache_size(self) -> int:
        """返回当前缓存中的沙盒数量。"""

        return len(self._sandbox_cache)

    async def astop(self) -> None:
        """停止并清空当前缓存中的所有沙盒。"""

        for sandbox in list(self._sandbox_cache.values()):
            try:
                await sandbox.astop()
            except Exception as exc:
                logger.debug("停止沙盒失败，忽略并继续: %s", exc)
        self._sandbox_cache.clear()

    def detect_mode(self) -> str:
        """根据宿主环境与配置推断当前应使用的模式。"""

        if self.is_inside_sandbox():
            logger.info("[SandboxRuntime] 已在 Shipyard 沙盒内，使用 local 模式")
            return "local"

        try:
            astrbot_config = self.context.get_config()
            computer_use = astrbot_config.get("computer_use", {})
            run_mode = computer_use.get("run_mode", "sandbox")
        except Exception:
            return "auto"

        if run_mode in {"none", "local"}:
            return "local"
        return "shipyard"

    def is_inside_sandbox(self) -> bool:
        """判断当前进程是否已运行在 Shipyard 沙盒内。"""

        return bool(self.inside_sandbox_detector())

    async def get_sandbox(
        self,
        event: Any = None,
        mode: str | None = None,
        session_id: str | None = None,
    ) -> CodeSandbox:
        """获取健康的缓存沙盒，必要时创建新实例。"""

        resolved_session_id = self._resolve_session_id(event, session_id)
        selected_mode = mode or self.detect_mode()
        cache_key = self._cache_key(selected_mode, resolved_session_id)
        cached_sandbox = await self._get_cached_sandbox(cache_key)
        if cached_sandbox is not None:
            return cached_sandbox
        return await self._create_or_fallback(
            selected_mode,
            event,
            resolved_session_id,
            cache_key,
        )

    async def _get_cached_sandbox(self, cache_key: str) -> CodeSandbox | None:
        """返回健康的缓存沙盒，不健康时移除缓存。"""

        sandbox = self._sandbox_cache.get(cache_key)
        if sandbox is None:
            return None

        try:
            if await sandbox.ahealthcheck() == "healthy":
                return sandbox
        except Exception as exc:
            logger.debug("缓存沙盒健康检查失败，将重建: %s", exc)

        self._sandbox_cache.pop(cache_key, None)
        return None

    async def _create_or_fallback(
        self,
        mode: str,
        event: Any,
        session_id: str | None,
        cache_key: str,
    ) -> CodeSandbox:
        """优先创建目标模式沙盒，失败时按策略回退或抛错。"""

        try:
            return await self._create_primary_sandbox(mode, event, session_id, cache_key)
        except Exception as exc:
            return await self._fallback_or_raise(mode, event, session_id, exc)

    async def _create_primary_sandbox(
        self,
        mode: str,
        event: Any,
        session_id: str | None,
        cache_key: str,
    ) -> CodeSandbox:
        """按配置执行重试与自动修复，然后创建主沙盒。"""

        last_error: Exception | None = None
        for attempt in range(self.retry_count + 1):
            try:
                sandbox = await self._start_sandbox(mode, event, session_id, cache_key)
                if attempt > 0:
                    logger.info("沙盒创建成功（第 %d 次重试）", attempt)
                return sandbox
            except Exception as exc:
                last_error = exc
                self._log_creation_failure(exc, attempt)
                if await self._wait_before_retry(exc, attempt):
                    continue
                try:
                    return await self._create_after_fix(exc, mode, event, session_id, cache_key)
                except Exception as retry_err:
                    last_error = retry_err
                    if retry_err is not exc:
                        logger.error("修复后仍无法创建沙盒: %s", retry_err)
                break

        if last_error is not None:
            raise last_error
        raise RuntimeError("沙盒创建失败，但未捕获到具体异常")

    async def _start_sandbox(
        self,
        mode: str,
        event: Any,
        session_id: str | None,
        cache_key: str,
    ) -> CodeSandbox:
        """创建并启动一个新沙盒，同时写入缓存。"""

        sandbox = self.sandbox_factory(
            mode=mode,
            context=self.context,
            event=event,
            session_id=session_id,
            cwd=self._get_workspace_cwd(session_id),
            timeout=self.task_timeout,
        )
        await sandbox.astart()
        self._sandbox_cache[cache_key] = sandbox
        return sandbox

    def _log_creation_failure(self, error: Exception, attempt: int) -> None:
        """记录沙盒创建失败日志。"""

        logger.error(
            "创建沙盒失败 (尝试 %d/%d): %s",
            attempt + 1,
            self.retry_count + 1,
            error,
        )

    async def _wait_before_retry(self, error: Exception, attempt: int) -> bool:
        """当错误属于网络类问题时按配置等待并重试。"""

        if attempt >= self.retry_count:
            return False
        if not self._is_network_error(error):
            return False

        wait_time = (attempt + 1) * 3
        logger.info("网络错误，等待 %d 秒后重试...", wait_time)
        await asyncio.sleep(wait_time)
        return True

    async def _create_after_fix(
        self,
        error: Exception,
        mode: str,
        event: Any,
        session_id: str | None,
        cache_key: str,
    ) -> CodeSandbox:
        """尝试自动修复环境后再次创建沙盒。"""

        if not self.config.get("auto_fix_sandbox", True):
            raise error

        fix_message = await self._try_auto_fix(str(error))
        if not fix_message:
            raise error

        logger.info("环境修复结果: %s", fix_message)
        return await self._start_sandbox(mode, event, session_id, cache_key)

    async def _fallback_or_raise(
        self,
        mode: str,
        event: Any,
        session_id: str | None,
        last_error: Exception,
    ) -> CodeSandbox:
        """按配置决定是否回退到 local，否则抛出更明确的异常。"""

        if mode != "local" and self.config.get("allow_local_fallback", False):
            return await self._start_local_fallback(event, session_id, last_error)
        if mode != "local":
            raise RuntimeError(
                f"沙盒创建失败，已拒绝自动回退到本地执行: {last_error}"
            ) from last_error
        raise last_error

    async def _start_local_fallback(
        self,
        event: Any,
        session_id: str | None,
        last_error: Exception,
    ) -> CodeSandbox:
        """回退创建本地沙盒，并保留原始异常链。"""

        logger.warning("回退到 local 模式 (原因: %s)", last_error)
        cache_key = self._cache_key("local", session_id)
        try:
            return await self._start_sandbox("local", event, session_id, cache_key)
        except Exception as local_error:
            logger.error("local 模式也创建失败: %s", local_error)
            raise last_error from local_error

    async def _try_auto_fix(self, error_msg: str) -> str:
        """尝试调用环境修复器修复依赖环境。"""

        fixer = self._get_env_fixer()
        if fixer is None:
            return ""

        try:
            fixed, message = await fixer.check_and_fix_environment(error_msg)
        except Exception as exc:
            logger.warning("环境自动修复失败: %s", exc)
            return ""
        return str(message) if fixed else ""

    def _get_env_fixer(self) -> Any | None:
        """按需构造环境修复器实例，并在运行时缓存。"""

        if self._env_fixer is not None:
            return self._env_fixer

        try:
            self._env_fixer = self._build_env_fixer()
        except Exception as exc:
            logger.warning("无法加载环境修复器: %s", exc)
            self._env_fixer = None
        return self._env_fixer

    def _build_env_fixer(self) -> Any:
        """构造环境修复器，便于在测试中注入替身。"""

        if self.env_fixer_factory is not None:
            return self.env_fixer_factory()

        from .env_fixer import EnvironmentFixer

        return EnvironmentFixer()

    def _is_network_error(self, error: Exception) -> bool:
        """判断异常是否属于可重试的网络类失败。"""

        error_text = str(error).lower()
        return any(keyword in error_text for keyword in _NETWORK_ERROR_KEYWORDS)

    @property
    def task_timeout(self) -> float:
        """返回沙盒默认超时。"""

        return float(self.config.get("task_timeout", 120))

    @property
    def retry_count(self) -> int:
        """返回沙盒创建重试次数。"""

        return int(self.config.get("sandbox_create_retries", 2))

    @staticmethod
    def _cache_key(mode: str, session_id: str | None) -> str:
        """生成缓存键。"""

        return f"{mode}:{session_id or 'default'}"

    @staticmethod
    def _resolve_session_id(event: Any, session_id: str | None) -> str | None:
        """优先使用显式 session_id，否则从事件对象提取稳定会话标识。"""

        if session_id:
            return str(session_id)
        if event is None:
            return None

        for attr_name in ("session_id", "unified_msg_origin"):
            value = getattr(event, attr_name, None)
            if value:
                return str(value)

        get_sender_id = getattr(event, "get_sender_id", None)
        if callable(get_sender_id):
            try:
                sender_id = get_sender_id()
            except Exception:
                return None
            if sender_id:
                return str(sender_id)
        return None

    def _get_workspace_cwd(self, session_id: str | None) -> str:
        """为每个会话分配独立工作目录，避免共享 /workspace。"""

        if not session_id:
            return self.default_cwd
        digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
        return f"{self.default_cwd}/sessions/{digest}"
