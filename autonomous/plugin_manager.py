"""
插件市场管理工具

功能：
- 搜索 AstrBot 插件市场
- 安装/卸载插件（使用 AstrBot 原生逻辑，支持 GitHub 加速）
- 查看已安装插件
"""

import logging
from typing import Any, cast

import aiohttp

logger = logging.getLogger(__name__)

# AstrBot 插件市场 API
PLUGIN_REGISTRY_URL = "https://api.soulter.top/stars"
PLUGIN_REGISTRY_FALLBACK = (
    "https://raw.githubusercontent.com/AstrBotDevs/AstrBot-Plugins/main/plugins.json"
)

# GitHub 加速镜像列表
GITHUB_PROXIES = [
    "",  # 不使用加速
    "https://edgeone.gh-proxy.com",
    "https://hk.gh-proxy.com",
    "https://gh-proxy.com",
    "https://gh.llkk.cc",
]


class PluginManagerTool:
    """
    插件市场管理工具

    通过 AstrBot 的 PluginManager 实现插件的搜索、安装、卸载
    支持 GitHub 加速
    """

    def __init__(self, context: Any) -> None:
        self.context = context
        self._plugin_cache: list[dict[str, Any]] = []
        self._cache_valid = False

    def _get_plugin_manager(self) -> Any | None:
        """获取 AstrBot 的 PluginManager"""
        try:
            return self.context._star_manager
        except AttributeError:
            return None

    def _get_github_proxy(self) -> str:
        """从 AstrBot 配置获取 GitHub 代理"""
        try:
            config = self.context._config
            # AstrBot 配置中的 GitHub 加速设置
            proxy = config.get("plugin_settings", {}).get("github_proxy", "")
            return cast(str, proxy)
        except Exception:
            return ""

    async def _fetch_plugin_registry(self) -> list[dict[str, Any]]:
        """从插件市场获取插件列表"""
        if self._cache_valid:
            return self._plugin_cache

        plugins: list[dict[str, Any]] = []

        try:
            async with aiohttp.ClientSession() as session:
                # 尝试官方 API
                try:
                    async with session.get(
                        PLUGIN_REGISTRY_URL, timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            plugins = (
                                data
                                if isinstance(data, list)
                                else data.get("plugins", data.get("stars", []))
                            )
                except Exception:
                    # 尝试备用源
                    proxy = self._get_github_proxy()
                    fallback_url = PLUGIN_REGISTRY_FALLBACK
                    if proxy:
                        fallback_url = f"{proxy.rstrip('/')}/{fallback_url}"

                    async with session.get(
                        fallback_url, timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            plugins = data if isinstance(data, list) else data.get("plugins", [])
        except Exception as e:
            logger.error(f"获取插件列表失败: {e}")

        self._plugin_cache = plugins
        self._cache_valid = True
        return plugins

    async def search_plugins(self, keyword: str) -> str:
        """
        搜索插件市场

        Args:
            keyword: 搜索关键词

        Returns:
            搜索结果字符串
        """
        plugins = await self._fetch_plugin_registry()

        if not plugins:
            return "❌ 无法获取插件市场数据，请检查网络连接"

        keyword_lower = keyword.lower()
        matches = []

        for plugin in plugins:
            name = plugin.get("name", "")
            desc = plugin.get("desc", plugin.get("description", ""))
            tags = plugin.get("tags", [])
            author = plugin.get("author", "")

            # 搜索匹配
            if (
                keyword_lower in name.lower()
                or keyword_lower in desc.lower()
                or keyword_lower in author.lower()
                or any(keyword_lower in str(tag).lower() for tag in tags)
            ):
                matches.append(plugin)

        if not matches:
            return f'🔍 未找到与 "{keyword}" 相关的插件\n\n💡 尝试使用更通用的关键词'

        lines = [f"🔍 找到 {len(matches)} 个相关插件：\n"]

        for p in matches[:10]:
            name = p.get("name", "未知")
            desc = p.get("desc", p.get("description", "无描述"))[:60]
            repo = p.get("repo", "")
            author = p.get("author", "未知")

            lines.append(f"**{name}** (by {author})")
            lines.append(f"  {desc}...")
            if repo:
                lines.append(f"  📦 `{repo}`")
            lines.append("")

        if len(matches) > 10:
            lines.append(f"... 还有 {len(matches) - 10} 个结果")

        # 显示当前代理设置
        proxy = self._get_github_proxy()
        if proxy:
            lines.append(f"\n🚀 当前 GitHub 加速: {proxy}")

        lines.append("\n💡 安装命令: `/plugin install <repo_url>`")

        return "\n".join(lines)

    async def install_plugin(self, repo_url: str, use_proxy: bool | None = None) -> str:
        """
        安装插件

        使用 AstrBot 原生的 PluginUpdator，支持 GitHub 加速

        Args:
            repo_url: 插件仓库 URL
            use_proxy: 是否使用代理（None 表示自动检测）

        Returns:
            安装结果
        """
        pm = self._get_plugin_manager()
        if not pm:
            return "❌ 插件管理器不可用"

        # 获取代理设置
        proxy = ""
        if use_proxy is not False:
            proxy = self._get_github_proxy()

        try:
            # 使用 AstrBot 的 updator 安装（已内置代理支持）
            plugin_path = await pm.updator.install(repo_url, proxy=proxy)

            # 获取目录名
            dir_name = plugin_path.split("/")[-1] if "/" in plugin_path else plugin_path

            # 加载插件
            await pm.load(specified_dir_name=dir_name)

            result = f"✅ 插件安装成功！\n\n📁 路径: {plugin_path}"
            if proxy:
                result += f"\n🚀 使用加速: {proxy}"
            result += "\n\n💡 插件已自动加载，无需重启"

            return result

        except Exception as e:
            error_msg = str(e)
            logger.error(f"安装插件失败: {e}")

            # 如果没使用代理且失败，提示使用代理
            if not proxy and "timeout" in error_msg.lower():
                return (
                    f"❌ 安装失败: {error_msg}\n\n"
                    "💡 **网络超时，建议启用 GitHub 加速：**\n"
                    "在 AstrBot WebUI → 插件管理 → 设置 GitHub 加速\n\n"
                    "可选镜像:\n"
                    "• https://edgeone.gh-proxy.com\n"
                    "• https://hk.gh-proxy.com\n"
                    "• https://gh-proxy.com\n"
                    "• https://gh.llkk.cc"
                )

            return f"❌ 安装失败: {error_msg}"

    async def install_from_market(self, plugin_name: str) -> str:
        """
        从插件市场安装（通过名称）

        Args:
            plugin_name: 插件名称
        """
        plugins = await self._fetch_plugin_registry()

        # 查找插件
        target: dict[str, Any] | None = None
        for p in plugins:
            if p.get("name", "").lower() == plugin_name.lower():
                target = p
                break

        if not target:
            # 模糊匹配
            for p in plugins:
                if plugin_name.lower() in p.get("name", "").lower():
                    target = p
                    break

        if not target:
            return (
                f"❌ 未在插件市场找到: {plugin_name}\n\n💡 使用 `/plugin search {plugin_name}` 搜索"
            )

        repo = target.get("repo", "")
        if not repo:
            return f"❌ 插件 {target.get('name')} 没有仓库地址"

        return await self.install_plugin(repo)

    async def list_plugins(self) -> str:
        """列出已安装的插件"""
        try:
            stars = self.context.get_all_stars()

            if not stars:
                return "📦 暂无已安装的插件"

            lines = ["📦 已安装的插件：\n"]

            for star in stars:
                status = "✅" if star.activated else "❌"
                name = star.name or "未知"
                version = getattr(star, "version", "?")
                desc = getattr(star, "desc", "")[:40]

                lines.append(f"{status} **{name}** v{version}")
                if desc:
                    lines.append(f"   {desc}")

            # 显示代理状态
            proxy = self._get_github_proxy()
            if proxy:
                lines.append(f"\n🚀 GitHub 加速: {proxy}")
            else:
                lines.append("\n💡 未启用 GitHub 加速")

            return "\n".join(lines)

        except Exception as e:
            return f"❌ 获取插件列表失败: {str(e)}"

    async def remove_plugin(self, name: str) -> str:
        """卸载插件"""
        pm = self._get_plugin_manager()
        if not pm:
            return "❌ 插件管理器不可用"

        try:
            await pm.uninstall(name)
            return f"✅ 插件 `{name}` 已卸载"
        except Exception as e:
            return f"❌ 卸载失败: {str(e)}"

    async def update_plugin(self, name: str) -> str:
        """更新插件"""
        pm = self._get_plugin_manager()
        if not pm:
            return "❌ 插件管理器不可用"

        proxy = self._get_github_proxy()

        try:
            # 查找插件
            plugin = self.context.get_registered_star(name)
            if not plugin:
                return f"❌ 未找到插件: {name}"

            # 使用 AstrBot 的更新方法
            await pm.updator.update(plugin, proxy=proxy)

            # 重载插件
            await pm.reload(name)

            result = f"✅ 插件 `{name}` 更新成功！"
            if proxy:
                result += f"\n🚀 使用加速: {proxy}"

            return result

        except Exception as e:
            return f"❌ 更新失败: {str(e)}"

    def get_available_proxies(self) -> str:
        """获取可用的 GitHub 加速列表"""
        lines = ["🚀 **GitHub 加速镜像列表**\n"]

        current = self._get_github_proxy()

        for proxy in GITHUB_PROXIES:
            if not proxy:
                status = "✅" if not current else ""
                lines.append(f"{status} 不使用加速 (直连)")
            else:
                status = "✅" if proxy == current else ""
                lines.append(f"{status} {proxy}")

        lines.append("\n💡 在 AstrBot WebUI → 插件管理 中设置加速")

        return "\n".join(lines)

    def invalidate_cache(self) -> None:
        """使缓存失效"""
        self._cache_valid = False
        self._plugin_cache = []
