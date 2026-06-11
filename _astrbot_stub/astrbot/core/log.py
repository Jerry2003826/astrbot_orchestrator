"""astrbot.core.log 测试桩，对齐 v4.25.5 的 LogManager.GetLogger。"""

import logging


class LogManager:
    @classmethod
    def GetLogger(cls, log_name: str = "default") -> logging.Logger:
        return logging.getLogger(log_name)
