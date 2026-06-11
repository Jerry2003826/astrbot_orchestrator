"""插件市场能力的 FunctionTool 封装（复用 autonomous/plugin_manager.py）。"""

from __future__ import annotations

from typing import Any

from .base import OrchestratorTool, obj_schema, str_prop


class PluginSearchTool(OrchestratorTool):
    requires_admin = False

    def __init__(self, runtime: Any) -> None:
        super().__init__(
            runtime,
            name="plugin_search",
            description=("搜索 AstrBot 插件市场。输入关键词，返回匹配插件的名称、简介与仓库地址。"),
            parameters=obj_schema(
                {"keyword": str_prop("搜索关键词，如“翻译”“天气”")},
                required=["keyword"],
            ),
        )

    async def run(self, event: Any, keyword: str) -> str:
        return await self.runtime.plugin_tool.search_plugins(keyword)


class PluginListTool(OrchestratorTool):
    requires_admin = False

    def __init__(self, runtime: Any) -> None:
        super().__init__(
            runtime,
            name="plugin_list",
            description="列出当前 AstrBot 已安装的全部插件及其状态。",
            parameters=obj_schema({}),
        )

    async def run(self, event: Any) -> str:
        return await self.runtime.plugin_tool.list_plugins()


class PluginInstallTool(OrchestratorTool):
    def __init__(self, runtime: Any) -> None:
        super().__init__(
            runtime,
            name="plugin_install",
            description=(
                "安装 AstrBot 插件（管理员）。传入插件仓库地址（GitHub URL），"
                "自动套用 GitHub 加速配置。也可传入插件市场中的插件名。"
            ),
            parameters=obj_schema(
                {"repo_url": str_prop("插件 GitHub 仓库地址或插件市场名称")},
                required=["repo_url"],
            ),
        )

    async def run(self, event: Any, repo_url: str) -> str:
        if denied := self.check_permission(event):
            return denied
        repo_url = repo_url.strip()
        if repo_url.startswith(("http://", "https://", "git@")):
            return await self.runtime.plugin_tool.install_plugin(repo_url)
        return await self.runtime.plugin_tool.install_from_market(repo_url)


class PluginUninstallTool(OrchestratorTool):
    def __init__(self, runtime: Any) -> None:
        super().__init__(
            runtime,
            name="plugin_uninstall",
            description="卸载已安装的 AstrBot 插件（管理员）。",
            parameters=obj_schema(
                {"name": str_prop("要卸载的插件名称")},
                required=["name"],
            ),
        )

    async def run(self, event: Any, name: str) -> str:
        if denied := self.check_permission(event):
            return denied
        return await self.runtime.plugin_tool.remove_plugin(name)


class PluginUpdateTool(OrchestratorTool):
    def __init__(self, runtime: Any) -> None:
        super().__init__(
            runtime,
            name="plugin_update",
            description="更新已安装的 AstrBot 插件到最新版本（管理员）。",
            parameters=obj_schema(
                {"name": str_prop("要更新的插件名称")},
                required=["name"],
            ),
        )

    async def run(self, event: Any, name: str) -> str:
        if denied := self.check_permission(event):
            return denied
        return await self.runtime.plugin_tool.update_plugin(name)
