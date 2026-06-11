"""astrbot.core.agent.tool 测试桩，对齐 v4.25.5 字段与方法签名。

真实实现基于 pydantic dataclass 并校验 JSON Schema；
桩用标准 dataclass 复刻字段名、默认值与方法语义。
"""

from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Generic

from .run_context import ContextWrapper, TContext

ParametersType = dict[str, Any]
ToolExecResult = Any


@dataclass
class ToolSchema:
    name: str
    description: str
    parameters: ParametersType


@dataclass
class FunctionTool(ToolSchema, Generic[TContext]):
    handler: Callable[..., Awaitable[str | None] | AsyncGenerator[Any, None]] | None = None
    handler_module_path: str | None = None
    active: bool = True
    is_background_task: bool = False

    def __repr__(self) -> str:
        return (
            f"FuncTool(name={self.name}, parameters={self.parameters}, "
            f"description={self.description})"
        )

    async def call(self, context: ContextWrapper[TContext], **kwargs: Any) -> ToolExecResult:
        raise NotImplementedError(
            "FunctionTool.call() must be implemented by subclasses or set a handler."
        )


@dataclass
class ToolSet:
    tools: list[FunctionTool] = field(default_factory=list)

    def empty(self) -> bool:
        return len(self.tools) == 0

    def add_tool(self, tool: FunctionTool) -> None:
        for i, existing_tool in enumerate(self.tools):
            if existing_tool.name == tool.name:
                existing_active = bool(getattr(existing_tool, "active", True))
                new_active = bool(getattr(tool, "active", True))
                if new_active or not existing_active:
                    self.tools[i] = tool
                return
        self.tools.append(tool)

    def remove_tool(self, name: str) -> None:
        self.tools = [tool for tool in self.tools if tool.name != name]

    def get_tool(self, name: str) -> FunctionTool | None:
        for tool in self.tools:
            if tool.name == name:
                return tool
        return None

    def names(self) -> list[str]:
        return [tool.name for tool in self.tools]

    def add_func(
        self,
        name: str,
        func_args: list,
        desc: str,
        handler: Callable[..., Awaitable[Any]],
    ) -> None:
        """[Deprecated in 4.x] 兼容旧接口。"""
        params: dict[str, Any] = {"type": "object", "properties": {}}
        for param in func_args:
            params["properties"][param["name"]] = {
                "type": param["type"],
                "description": param["description"],
            }
        self.add_tool(FunctionTool(name=name, parameters=params, description=desc, handler=handler))

    def remove_func(self, name: str) -> None:
        """[Deprecated in 4.x] 兼容旧接口。"""
        self.remove_tool(name)

    def get_func(self, name: str) -> FunctionTool | None:
        """[Deprecated in 4.x] 兼容旧接口。"""
        return self.get_tool(name)

    @property
    def func_list(self) -> list[FunctionTool]:
        return self.tools

    def __len__(self) -> int:
        return len(self.tools)

    def __iter__(self):
        return iter(self.tools)
