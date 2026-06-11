"""astrbot.core.config.astrbot_config 测试桩。

真实 AstrBotConfig 是绑定到磁盘配置文件的 dict 子类；
桩实现仅记录 save_config 调用次数，便于断言。
"""

from typing import Any


class AstrBotConfig(dict):
    """与真实实现一致：dict 子类 + save_config()。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.save_count = 0

    def save_config(self) -> None:
        """真实实现会把配置写回磁盘；桩只计数。"""
        self.save_count += 1
