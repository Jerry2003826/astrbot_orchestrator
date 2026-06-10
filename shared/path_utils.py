"""项目目录解析 — 统一来自 RuntimeContainer / DynamicOrchestrator / MetaOrchestrator
的重复回退链，避免多份拷贝脱节。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import logging

logger = logging.getLogger(__name__)


def resolve_projects_dir(
    prefer_dir: str | None = None,
    plugin_root: Path | None = None,
) -> str:
    """按统一优先级解析 Agent 项目持久化目录。

    Args:
        prefer_dir: 最高优先级的已有目录（如 ``artifact_service.persist_dir``）。
        plugin_root: 插件包根目录，用于最后回退 ``<plugin_root>/projects``。

    Returns:
        可用的项目目录绝对路径（必要时自动创建）。
    """

    if prefer_dir:
        try:
            os.makedirs(prefer_dir, exist_ok=True)
            return prefer_dir
        except OSError:
            logger.debug("优先目录不可写，回退: %s", prefer_dir)

    env_root = os.environ.get("ASTRBOT_DATA_DIR") or os.environ.get("ASTRBOT_ROOT")
    if env_root:
        path = os.path.join(env_root, "agent_projects")
        try:
            os.makedirs(path, exist_ok=True)
            return path
        except OSError:
            logger.debug("环境变量目录不可写，回退: %s", path)

    cwd_path = Path.cwd() / "data" / "agent_projects"
    try:
        os.makedirs(cwd_path, exist_ok=True)
        return str(cwd_path)
    except OSError:
        logger.debug("当前目录不可写，回退: %s", cwd_path)

    docker_path = Path("/AstrBot/data/agent_projects")
    try:
        os.makedirs(docker_path, exist_ok=True)
        return str(docker_path)
    except OSError:
        logger.debug("Docker 标准目录不可写，回退: %s", docker_path)

    if plugin_root is not None:
        plugin_path = plugin_root / "projects"
        try:
            os.makedirs(plugin_path, exist_ok=True)
            return str(plugin_path)
        except OSError:
            logger.debug("插件目录不可写，回退: %s", plugin_path)

    fallback = tempfile.mkdtemp(prefix="astrbot_orchestrator_projects_")
    logger.warning("所有标准位置都不可写，使用临时目录: %s", fallback)
    return fallback
