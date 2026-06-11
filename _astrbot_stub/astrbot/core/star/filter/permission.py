"""astrbot.core.star.filter.permission 测试桩，对齐 v4.25.5。"""

import enum
from typing import Any

from . import HandlerFilter


class PermissionType(enum.Flag):
    """权限类型。当选择 MEMBER，ADMIN 也可以通过。"""

    ADMIN = enum.auto()
    MEMBER = enum.auto()


class PermissionTypeFilter(HandlerFilter):
    def __init__(self, permission_type: PermissionType, raise_error: bool = True) -> None:
        self.permission_type = permission_type
        self.raise_error = raise_error

    def filter(self, event: Any, cfg: Any) -> bool:
        if self.permission_type == PermissionType.ADMIN:
            return bool(event.is_admin())
        return True
