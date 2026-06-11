"""AstrBot v4.25.5 API 测试桩根包。

仅复刻本插件用到的最小公开 API 子集，模块布局与真实 AstrBot 对齐，
便于单元测试在不安装宿主的情况下以真实签名导入。
"""

import logging

logger = logging.getLogger("astrbot")

__all__ = ["logger"]
