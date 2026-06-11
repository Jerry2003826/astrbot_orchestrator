"""插件数据目录解析。

统一使用官方 StarTools.get_data_dir()，所有持久化产物
（审计日志、agent_projects 等）都落在 data/plugin_data/astrbot_plugin_orchestrator/。
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile

from astrbot.api import logger

PLUGIN_NAME = "astrbot_plugin_orchestrator"


def get_plugin_data_dir() -> Path:
    """返回本插件的数据目录（data/plugin_data/astrbot_plugin_orchestrator）。"""

    from astrbot.api.star import StarTools

    return StarTools.get_data_dir(PLUGIN_NAME)


def resolve_projects_dir(
    prefer_dir: str | None = None,
    plugin_root: Path | None = None,
) -> str:
    """解析 Agent 项目持久化目录。

    Args:
        prefer_dir: 最高优先级的已有目录（如 ``artifact_service.persist_dir``）。
        plugin_root: 兼容旧签名，已不参与解析。

    Returns:
        可用的项目目录绝对路径（必要时自动创建）。
    """

    if prefer_dir:
        try:
            os.makedirs(prefer_dir, exist_ok=True)
            return prefer_dir
        except OSError:
            logger.debug("优先目录不可写，回退: %s", prefer_dir)

    try:
        path = get_plugin_data_dir() / "agent_projects"
        path.mkdir(parents=True, exist_ok=True)
        return str(path)
    except Exception:
        logger.debug("插件数据目录不可用，回退临时目录", exc_info=True)

    fallback = tempfile.mkdtemp(prefix="astrbot_orchestrator_projects_")
    logger.warning("插件数据目录不可写，使用临时目录: %s", fallback)
    return fallback
