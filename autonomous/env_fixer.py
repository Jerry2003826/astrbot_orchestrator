"""
环境自动检测与修复模块
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

logger = logging.getLogger(__name__)


class EnvironmentFixer:
    """根据常见 Shipyard 错误自动修复本地环境。"""

    IMAGE_MAPPING = {
        "ship:latest": "soulter/shipyard-ship:latest",
        "shipyard-bay:latest": "soulter/shipyard-bay:latest",
    }

    async def check_and_fix_environment(self, error_msg: str) -> tuple[bool, str]:
        """根据错误信息尝试自动修复沙盒环境"""
        actions: list[str] = []

        if "No such image" in error_msg or "no such image" in error_msg:
            fixed, msg = await self._fix_missing_images(error_msg)
            if fixed:
                actions.append(msg)

        if "network shipyard not found" in error_msg:
            fixed, msg = await self._ensure_shipyard_network()
            if fixed:
                actions.append(msg)

        if "Ship failed to become ready" in error_msg:
            fixed, msg = await self._wait_ship_ready()
            if fixed:
                actions.append(msg)

        if actions:
            return True, "; ".join(actions)
        return False, "未检测到可自动修复的问题"

    async def _fix_missing_images(self, error_msg: str) -> tuple[bool, str]:
        """拉取并重新标记缺失的 Docker 镜像。"""

        for local_tag, remote_tag in self.IMAGE_MAPPING.items():
            if local_tag in error_msg:
                await self._run_cmd(["docker", "pull", remote_tag])
                await self._run_cmd(["docker", "tag", remote_tag, local_tag])
                return True, f"已拉取镜像 {remote_tag} 并标记为 {local_tag}"
        return False, "未匹配到缺失镜像"

    async def _ensure_shipyard_network(self) -> tuple[bool, str]:
        """确认 shipyard Docker 网络存在，不存在时创建。"""

        result = await self._run_cmd(["docker", "network", "ls"])
        if any("shipyard" in line for line in result.splitlines()):
            return True, "shipyard 网络已存在"
        await self._run_cmd(["docker", "network", "create", "shipyard"])
        return True, "已创建 shipyard 网络"

    async def _wait_ship_ready(self) -> tuple[bool, str]:
        """等待 ship 容器在短时间内完成启动。"""

        # 简单等待 ship 容器就绪
        await asyncio.sleep(5)
        return True, "已等待 ship 容器启动"

    async def _run_cmd(self, cmd: Sequence[str]) -> str:
        """执行命令并返回合并后的标准输出/错误输出。"""

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            output = (stdout.decode() if stdout else "") + (stderr.decode() if stderr else "")
            return output.strip()
        except Exception as e:
            logger.warning("执行命令失败: %s", e)
            return ""
