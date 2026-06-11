"""FunctionTool 公共基础设施。

工具类均继承官方 FunctionTool（pydantic dataclass），实现 ``run(event, **kwargs)``；
高危工具在 run 内统一做管理员校验，非管理员直接返回拒绝文案（提供给 LLM）。
"""

from __future__ import annotations

from typing import Any

from astrbot.api import FunctionTool

PERMISSION_DENIED = "permission denied: 该操作仅限 AstrBot 管理员在会话中触发。"


class OrchestratorTool(FunctionTool):
    """本插件工具基类：携带 runtime 引用与统一的管理员门控。"""

    requires_admin: bool = True

    def __init__(
        self,
        runtime: Any,
        *,
        name: str,
        description: str,
        parameters: dict[str, Any],
    ) -> None:
        super().__init__(name=name, description=description, parameters=parameters)
        # pydantic dataclass 允许 init 后追加属性（与官方 HandoffTool 同法）
        self.runtime = runtime

    def check_permission(self, event: Any) -> str | None:
        """高危工具的管理员校验；通过返回 None，否则返回拒绝文案。"""

        if not self.requires_admin:
            return None
        if event is not None and event.is_admin():
            return None
        return PERMISSION_DENIED


def obj_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    """构造 object 类型的 JSON Schema。"""

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def str_prop(description: str) -> dict[str, str]:
    """构造 string 属性。"""

    return {"type": "string", "description": description}
