"""astrbot.core.agent.run_context 测试桩。"""

from dataclasses import dataclass
from typing import Generic, TypeVar

TContext = TypeVar("TContext")


@dataclass
class ContextWrapper(Generic[TContext]):
    context: TContext
    tool_call_timeout: int = 120
