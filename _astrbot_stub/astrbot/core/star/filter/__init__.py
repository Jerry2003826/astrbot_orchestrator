"""astrbot.core.star.filter 测试桩。"""

import abc
from typing import Any


class HandlerFilter(abc.ABC):
    @abc.abstractmethod
    def filter(self, event: Any, cfg: Any) -> bool: ...
