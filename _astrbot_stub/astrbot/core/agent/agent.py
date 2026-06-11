"""astrbot.core.agent.agent 测试桩，对齐 v4.25.5 Agent dataclass。"""

from dataclasses import dataclass
from typing import Any, Generic

from .hooks import BaseAgentRunHooks
from .run_context import TContext
from .tool import FunctionTool


@dataclass
class Agent(Generic[TContext]):
    name: str
    instructions: str | None = None
    tools: list[str | FunctionTool] | None = None
    run_hooks: BaseAgentRunHooks[TContext] | None = None
    begin_dialogs: list[Any] | None = None
