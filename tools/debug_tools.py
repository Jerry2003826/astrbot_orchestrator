"""自我诊断能力的 FunctionTool 封装（复用 autonomous/debugger.py）。"""

from __future__ import annotations

from typing import Any

from .base import OrchestratorTool, obj_schema


class DebugStatusTool(OrchestratorTool):
    def __init__(self, runtime: Any) -> None:
        super().__init__(
            runtime,
            name="debug_status",
            description="获取 AstrBot 系统运行状态（平台、插件数、Provider、资源占用等，管理员）。",
            parameters=obj_schema({}),
        )

    async def run(self, event: Any) -> str:
        if denied := self.check_permission(event):
            return denied
        return await self.runtime.debugger.get_system_status()


class DebugRecentErrorsTool(OrchestratorTool):
    def __init__(self, runtime: Any) -> None:
        super().__init__(
            runtime,
            name="debug_recent_errors",
            description="查看最近捕获的运行错误记录（管理员）。",
            parameters=obj_schema(
                {
                    "limit": {
                        "type": "integer",
                        "description": "返回的错误条数，默认 10",
                    }
                }
            ),
        )

    async def run(self, event: Any, limit: int = 10) -> str:
        if denied := self.check_permission(event):
            return denied
        return self.runtime.debugger.get_recent_errors(limit=limit)
