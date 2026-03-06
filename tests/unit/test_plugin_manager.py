"""PluginManagerTool 单元测试。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

import astrbot_orchestrator_v5.autonomous.plugin_manager as plugin_module
from astrbot_orchestrator_v5.autonomous.plugin_manager import (
    GITHUB_PROXIES,
    PLUGIN_REGISTRY_FALLBACK,
    PLUGIN_REGISTRY_URL,
    PluginManagerTool,
)

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture
    from _pytest.fixtures import FixtureRequest
    from _pytest.logging import LogCaptureFixture
    from _pytest.monkeypatch import MonkeyPatch
    from pytest_mock.plugin import MockerFixture

    _PYTEST_TYPE_IMPORTS = (
        CaptureFixture,
        FixtureRequest,
        LogCaptureFixture,
        MonkeyPatch,
        MockerFixture,
    )


class RaisingConfig:
    """用于模拟配置读取异常。"""

    def get(self, key: str, default: Any = None) -> Any:
        """始终抛出异常。"""

        del key, default
        raise RuntimeError("config broken")


class FakePluginUpdator:
    """模拟 AstrBot 插件更新器。"""

    def __init__(
        self,
        *,
        install_result: str = "plugins/demo_plugin",
        install_error: Exception | None = None,
        update_error: Exception | None = None,
    ) -> None:
        """保存安装/更新返回值与失败行为。"""

        self.install_result = install_result
        self.install_error = install_error
        self.update_error = update_error
        self.install_calls: list[dict[str, Any]] = []
        self.update_calls: list[dict[str, Any]] = []

    async def install(self, repo_url: str, *, proxy: str = "") -> str:
        """记录安装调用，必要时抛出异常。"""

        self.install_calls.append({"repo_url": repo_url, "proxy": proxy})
        if self.install_error is not None:
            raise self.install_error
        return self.install_result

    async def update(self, plugin: Any, *, proxy: str = "") -> None:
        """记录更新调用，必要时抛出异常。"""

        self.update_calls.append({"plugin": plugin, "proxy": proxy})
        if self.update_error is not None:
            raise self.update_error


class FakePluginManager:
    """模拟 AstrBot 插件管理器。"""

    def __init__(
        self,
        *,
        updator: FakePluginUpdator | None = None,
        load_error: Exception | None = None,
        uninstall_error: Exception | None = None,
        reload_error: Exception | None = None,
    ) -> None:
        """保存更新器与各方法的失败行为。"""

        self.updator = updator or FakePluginUpdator()
        self.load_error = load_error
        self.uninstall_error = uninstall_error
        self.reload_error = reload_error
        self.load_calls: list[str] = []
        self.uninstall_calls: list[str] = []
        self.reload_calls: list[str] = []

    async def load(self, *, specified_dir_name: str) -> None:
        """记录加载调用，必要时抛出异常。"""

        self.load_calls.append(specified_dir_name)
        if self.load_error is not None:
            raise self.load_error

    async def uninstall(self, name: str) -> None:
        """记录卸载调用，必要时抛出异常。"""

        self.uninstall_calls.append(name)
        if self.uninstall_error is not None:
            raise self.uninstall_error

    async def reload(self, name: str) -> None:
        """记录重载调用，必要时抛出异常。"""

        self.reload_calls.append(name)
        if self.reload_error is not None:
            raise self.reload_error


class FakeContext:
    """提供 PluginManagerTool 所需最小上下文。"""

    def __init__(
        self,
        *,
        star_manager: Any = None,
        config: Any = None,
        stars: list[Any] | None = None,
        stars_error: Exception | None = None,
        registered_stars: dict[str, Any] | None = None,
    ) -> None:
        """保存插件管理器、配置和查询结果。"""

        self._star_manager = star_manager
        self._config = config if config is not None else {}
        self._stars = list(stars or [])
        self._stars_error = stars_error
        self._registered_stars = dict(registered_stars or {})

    def get_all_stars(self) -> list[Any]:
        """返回插件列表或按需抛出异常。"""

        if self._stars_error is not None:
            raise self._stars_error
        return list(self._stars)

    def get_registered_star(self, name: str) -> Any | None:
        """返回指定名称的已注册插件。"""

        return self._registered_stars.get(name)


class FakeHttpResponse:
    """模拟 aiohttp 响应对象。"""

    def __init__(self, *, status: int = 200, json_data: Any = None) -> None:
        """保存状态码和 JSON 数据。"""

        self.status = status
        self._json_data = json_data

    async def __aenter__(self) -> FakeHttpResponse:
        """进入异步上下文并返回自身。"""

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> bool:
        """退出异步上下文，不吞异常。"""

        del exc_type, exc, tb
        return False

    async def json(self) -> Any:
        """返回预设 JSON 数据。"""

        return self._json_data


class FakeClientSession:
    """模拟 aiohttp.ClientSession。"""

    def __init__(self, *, get_results: list[Any] | None = None) -> None:
        """保存 GET 调用队列。"""

        self._get_results = list(get_results or [])
        self.get_calls: list[dict[str, Any]] = []

    async def __aenter__(self) -> FakeClientSession:
        """进入异步上下文并返回自身。"""

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> bool:
        """退出异步上下文，不吞异常。"""

        del exc_type, exc, tb
        return False

    def get(self, url: str, **kwargs: Any) -> Any:
        """返回预设响应或抛出异常。"""

        self.get_calls.append({"url": url, "kwargs": kwargs})
        result = self._get_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_plugin_manager_get_plugin_manager_and_proxy_cover_success_and_fallbacks() -> None:
    """应能读取插件管理器和 GitHub 代理，并处理异常回退。"""

    manager = FakePluginManager()
    tool = PluginManagerTool(
        context=FakeContext(
            star_manager=manager,
            config={"plugin_settings": {"github_proxy": "https://proxy.example.com"}},
        )
    )

    assert tool._get_plugin_manager() is manager
    assert tool._get_github_proxy() == "https://proxy.example.com"

    missing_tool = PluginManagerTool(context=SimpleNamespace())
    assert missing_tool._get_plugin_manager() is None

    broken_tool = PluginManagerTool(context=FakeContext(config=RaisingConfig()))
    assert broken_tool._get_github_proxy() == ""


@pytest.mark.asyncio
async def test_plugin_manager_fetch_registry_uses_cache_after_official_success(
    monkeypatch: "MonkeyPatch",
) -> None:
    """官方接口成功后应缓存结果，后续调用不再请求网络。"""

    fake_session = FakeClientSession(
        get_results=[FakeHttpResponse(status=200, json_data={"stars": [{"name": "demo"}]})]
    )
    monkeypatch.setattr(plugin_module.aiohttp, "ClientSession", lambda: fake_session)

    tool = PluginManagerTool(context=FakeContext())

    first = await tool._fetch_plugin_registry()
    second = await tool._fetch_plugin_registry()

    assert first == [{"name": "demo"}]
    assert second == [{"name": "demo"}]
    assert tool._cache_valid is True
    assert fake_session.get_calls[0]["url"] == PLUGIN_REGISTRY_URL
    assert len(fake_session.get_calls) == 1


@pytest.mark.asyncio
async def test_plugin_manager_fetch_registry_falls_back_to_proxy_source(
    monkeypatch: "MonkeyPatch",
) -> None:
    """官方接口异常时应切到带代理的备用源。"""

    fake_session = FakeClientSession(
        get_results=[
            RuntimeError("api down"),
            FakeHttpResponse(status=200, json_data={"plugins": [{"name": "calendar"}]}),
        ]
    )
    monkeypatch.setattr(plugin_module.aiohttp, "ClientSession", lambda: fake_session)
    tool = PluginManagerTool(
        context=FakeContext(
            config={"plugin_settings": {"github_proxy": "https://proxy.example.com/"}}
        )
    )

    result = await tool._fetch_plugin_registry()

    assert result == [{"name": "calendar"}]
    assert fake_session.get_calls[1]["url"] == (
        f"https://proxy.example.com/{PLUGIN_REGISTRY_FALLBACK}"
    )


@pytest.mark.asyncio
async def test_plugin_manager_fetch_registry_handles_non_200_and_total_failure(
    monkeypatch: "MonkeyPatch",
) -> None:
    """非 200 响应和备用源失败时应回退为空列表。"""

    tool = PluginManagerTool(context=FakeContext())

    non_200_session = FakeClientSession(
        get_results=[FakeHttpResponse(status=503, json_data={"stars": [{"name": "ignored"}]})]
    )
    monkeypatch.setattr(plugin_module.aiohttp, "ClientSession", lambda: non_200_session)

    empty_result = await tool._fetch_plugin_registry()

    assert empty_result == []
    assert tool._cache_valid is True
    assert len(non_200_session.get_calls) == 1

    tool.invalidate_cache()
    failing_session = FakeClientSession(
        get_results=[RuntimeError("api down"), RuntimeError("fallback down")]
    )
    monkeypatch.setattr(plugin_module.aiohttp, "ClientSession", lambda: failing_session)

    failed_result = await tool._fetch_plugin_registry()

    assert failed_result == []
    assert tool._cache_valid is True


@pytest.mark.asyncio
async def test_plugin_manager_fetch_registry_handles_non_200_fallback_response(
    monkeypatch: "MonkeyPatch",
) -> None:
    """备用源返回非 200 时也应平稳回退为空列表。"""

    fake_session = FakeClientSession(
        get_results=[RuntimeError("api down"), FakeHttpResponse(status=503, json_data=[])]
    )
    monkeypatch.setattr(plugin_module.aiohttp, "ClientSession", lambda: fake_session)

    tool = PluginManagerTool(context=FakeContext())

    result = await tool._fetch_plugin_registry()

    assert result == []
    assert len(fake_session.get_calls) == 2
    assert fake_session.get_calls[1]["url"] == PLUGIN_REGISTRY_FALLBACK


@pytest.mark.asyncio
async def test_plugin_manager_search_plugins_formats_matches_limit_and_proxy(
    monkeypatch: "MonkeyPatch",
) -> None:
    """搜索结果应按关键字匹配、截断到 10 条并显示代理。"""

    plugins = [
        {
            "name": f"tool-{idx}",
            "description": f"Tool description {idx}",
            "repo": f"https://github.com/demo/tool-{idx}",
            "author": f"author-{idx}",
            "tags": ["utility", f"tag-{idx}"],
        }
        for idx in range(11)
    ]
    plugins.append(
        {
            "name": "calendar-assistant",
            "desc": "calendar helper",
            "repo": "",
            "author": "someone",
            "tags": [],
        }
    )
    tool = PluginManagerTool(
        context=FakeContext(
            config={"plugin_settings": {"github_proxy": "https://proxy.example.com"}}
        )
    )

    async def fake_fetch() -> list[dict[str, Any]]:
        """返回预设插件列表。"""

        return plugins

    monkeypatch.setattr(tool, "_fetch_plugin_registry", fake_fetch)

    result = await tool.search_plugins("tool")

    assert "🔍 找到 11 个相关插件：" in result
    assert "**tool-0** (by author-0)" in result
    assert "**tool-9** (by author-9)" in result
    assert "**tool-10**" not in result
    assert "... 还有 1 个结果" in result
    assert "🚀 当前 GitHub 加速: https://proxy.example.com" in result
    assert "💡 安装命令: `/plugin install <repo_url>`" in result


@pytest.mark.asyncio
async def test_plugin_manager_search_plugins_handles_repo_optional_and_no_proxy(
    monkeypatch: "MonkeyPatch",
) -> None:
    """单条命中时不应显示额外数量，且 repo 可选。"""

    tool = PluginManagerTool(context=FakeContext())

    async def fake_fetch() -> list[dict[str, Any]]:
        """返回单个无仓库地址的匹配插件。"""

        return [
            {
                "name": "calendar-assistant",
                "desc": "calendar helper",
                "author": "demo",
                "tags": [],
                "repo": "",
            }
        ]

    monkeypatch.setattr(tool, "_fetch_plugin_registry", fake_fetch)

    result = await tool.search_plugins("calendar")

    assert "**calendar-assistant** (by demo)" in result
    assert "📦" not in result
    assert "... 还有" not in result
    assert "🚀 当前 GitHub 加速" not in result
    assert "💡 安装命令: `/plugin install <repo_url>`" in result


@pytest.mark.asyncio
async def test_plugin_manager_search_plugins_handles_empty_and_no_match(
    monkeypatch: "MonkeyPatch",
) -> None:
    """没有市场数据或没有命中时应返回对应提示。"""

    empty_tool = PluginManagerTool(context=FakeContext())

    async def fetch_empty() -> list[dict[str, Any]]:
        """返回空插件列表。"""

        return []

    monkeypatch.setattr(empty_tool, "_fetch_plugin_registry", fetch_empty)
    assert await empty_tool.search_plugins("calendar") == "❌ 无法获取插件市场数据，请检查网络连接"

    no_match_tool = PluginManagerTool(context=FakeContext())

    async def fetch_one() -> list[dict[str, Any]]:
        """返回单个不匹配插件。"""

        return [{"name": "weather", "description": "forecast", "author": "demo", "tags": []}]

    monkeypatch.setattr(no_match_tool, "_fetch_plugin_registry", fetch_one)
    no_match = await no_match_tool.search_plugins("calendar")
    assert '🔍 未找到与 "calendar" 相关的插件' in no_match


@pytest.mark.asyncio
async def test_plugin_manager_install_plugin_covers_unavailable_and_success_cases() -> None:
    """安装插件应覆盖管理器缺失和成功路径。"""

    unavailable_tool = PluginManagerTool(context=SimpleNamespace())
    assert (
        await unavailable_tool.install_plugin("https://github.com/demo/repo")
        == "❌ 插件管理器不可用"
    )

    proxy_manager = FakePluginManager(
        updator=FakePluginUpdator(install_result="plugins/demo_plugin")
    )
    proxy_tool = PluginManagerTool(
        context=FakeContext(
            star_manager=proxy_manager,
            config={"plugin_settings": {"github_proxy": "https://proxy.example.com"}},
        )
    )

    success_with_proxy = await proxy_tool.install_plugin("https://github.com/demo/repo")
    assert "✅ 插件安装成功！" in success_with_proxy
    assert "📁 路径: plugins/demo_plugin" in success_with_proxy
    assert "🚀 使用加速: https://proxy.example.com" in success_with_proxy
    assert proxy_manager.updator.install_calls == [
        {
            "repo_url": "https://github.com/demo/repo",
            "proxy": "https://proxy.example.com",
        }
    ]
    assert proxy_manager.load_calls == ["demo_plugin"]

    direct_manager = FakePluginManager(updator=FakePluginUpdator(install_result="demo_plugin"))
    direct_tool = PluginManagerTool(
        context=FakeContext(
            star_manager=direct_manager,
            config={"plugin_settings": {"github_proxy": "https://proxy.example.com"}},
        )
    )
    success_direct = await direct_tool.install_plugin(
        "https://github.com/demo/repo",
        use_proxy=False,
    )
    assert "🚀 使用加速" not in success_direct
    assert direct_manager.updator.install_calls[0]["proxy"] == ""
    assert direct_manager.load_calls == ["demo_plugin"]


@pytest.mark.asyncio
async def test_plugin_manager_install_plugin_covers_timeout_and_general_failures() -> None:
    """安装失败时应分别返回超时建议和一般错误。"""

    timeout_manager = FakePluginManager(
        updator=FakePluginUpdator(install_error=RuntimeError("Timeout while downloading")),
    )
    timeout_tool = PluginManagerTool(context=FakeContext(star_manager=timeout_manager))

    timeout_result = await timeout_tool.install_plugin(
        "https://github.com/demo/repo",
        use_proxy=False,
    )
    assert "💡 **网络超时，建议启用 GitHub 加速：**" in timeout_result
    assert "https://edgeone.gh-proxy.com" in timeout_result

    failure_manager = FakePluginManager(
        updator=FakePluginUpdator(install_error=RuntimeError("load failed")),
    )
    failure_tool = PluginManagerTool(
        context=FakeContext(
            star_manager=failure_manager,
            config={"plugin_settings": {"github_proxy": "https://proxy.example.com"}},
        )
    )

    failure = await failure_tool.install_plugin("https://github.com/demo/repo")
    assert failure == "❌ 安装失败: load failed"


@pytest.mark.asyncio
async def test_plugin_manager_install_from_market_covers_exact_fuzzy_missing_repo_and_not_found(
    monkeypatch: "MonkeyPatch",
) -> None:
    """从市场安装应覆盖精确匹配、模糊匹配、缺仓库和未找到。"""

    tool = PluginManagerTool(context=FakeContext())
    install_calls: list[dict[str, Any]] = []

    async def fake_install(repo_url: str, use_proxy: bool | None = None) -> str:
        """记录安装参数并返回固定结果。"""

        install_calls.append({"repo_url": repo_url, "use_proxy": use_proxy})
        return f"installed:{repo_url}"

    monkeypatch.setattr(tool, "install_plugin", fake_install)

    async def fetch_exact() -> list[dict[str, Any]]:
        """返回可精确匹配的插件列表。"""

        return [{"name": "Calendar", "repo": "https://github.com/demo/calendar"}]

    monkeypatch.setattr(tool, "_fetch_plugin_registry", fetch_exact)
    exact = await tool.install_from_market("calendar")
    assert exact == "installed:https://github.com/demo/calendar"

    async def fetch_fuzzy() -> list[dict[str, Any]]:
        """返回可模糊匹配的插件列表。"""

        return [{"name": "calendar-assistant", "repo": "https://github.com/demo/fuzzy"}]

    monkeypatch.setattr(tool, "_fetch_plugin_registry", fetch_fuzzy)
    fuzzy = await tool.install_from_market("calendar")
    assert fuzzy == "installed:https://github.com/demo/fuzzy"

    async def fetch_missing_repo() -> list[dict[str, Any]]:
        """返回缺少仓库地址的插件。"""

        return [{"name": "broken-plugin", "repo": ""}]

    monkeypatch.setattr(tool, "_fetch_plugin_registry", fetch_missing_repo)
    missing_repo = await tool.install_from_market("broken")
    assert missing_repo == "❌ 插件 broken-plugin 没有仓库地址"

    async def fetch_not_found() -> list[dict[str, Any]]:
        """返回无法匹配目标名称的插件。"""

        return [{"name": "weather", "repo": "https://github.com/demo/weather"}]

    monkeypatch.setattr(tool, "_fetch_plugin_registry", fetch_not_found)
    not_found = await tool.install_from_market("calendar")
    assert "❌ 未在插件市场找到: calendar" in not_found
    assert install_calls == [
        {
            "repo_url": "https://github.com/demo/calendar",
            "use_proxy": None,
        },
        {
            "repo_url": "https://github.com/demo/fuzzy",
            "use_proxy": None,
        },
    ]


@pytest.mark.asyncio
async def test_plugin_manager_list_plugins_covers_empty_success_proxy_and_error() -> None:
    """列出插件应覆盖空列表、正常渲染和异常回退。"""

    empty_tool = PluginManagerTool(context=FakeContext(stars=[]))
    assert await empty_tool.list_plugins() == "📦 暂无已安装的插件"

    proxy_tool = PluginManagerTool(
        context=FakeContext(
            stars=[
                SimpleNamespace(
                    activated=True,
                    name="calendar",
                    version="1.0.0",
                    desc="calendar helper plugin",
                ),
                SimpleNamespace(
                    activated=False,
                    name="weather",
                    version="2.0.0",
                    desc="weather helper plugin",
                ),
            ],
            config={"plugin_settings": {"github_proxy": "https://proxy.example.com"}},
        )
    )
    listed_with_proxy = await proxy_tool.list_plugins()
    assert "✅ **calendar** v1.0.0" in listed_with_proxy
    assert "❌ **weather** v2.0.0" in listed_with_proxy
    assert "🚀 GitHub 加速: https://proxy.example.com" in listed_with_proxy

    no_proxy_tool = PluginManagerTool(
        context=FakeContext(
            stars=[SimpleNamespace(activated=True, name="", version=None, desc="")],
        )
    )
    listed_without_proxy = await no_proxy_tool.list_plugins()
    assert "✅ **未知** vNone" in listed_without_proxy
    assert "💡 未启用 GitHub 加速" in listed_without_proxy

    broken_tool = PluginManagerTool(context=FakeContext(stars_error=RuntimeError("stars broken")))
    assert await broken_tool.list_plugins() == "❌ 获取插件列表失败: stars broken"


@pytest.mark.asyncio
async def test_plugin_manager_remove_plugin_covers_unavailable_success_and_failure() -> None:
    """卸载插件应覆盖管理器缺失、成功和失败。"""

    unavailable_tool = PluginManagerTool(context=SimpleNamespace())
    assert await unavailable_tool.remove_plugin("calendar") == "❌ 插件管理器不可用"

    success_manager = FakePluginManager()
    success_tool = PluginManagerTool(context=FakeContext(star_manager=success_manager))
    assert await success_tool.remove_plugin("calendar") == "✅ 插件 `calendar` 已卸载"
    assert success_manager.uninstall_calls == ["calendar"]

    failed_manager = FakePluginManager(uninstall_error=RuntimeError("remove failed"))
    failed_tool = PluginManagerTool(context=FakeContext(star_manager=failed_manager))
    assert await failed_tool.remove_plugin("calendar") == "❌ 卸载失败: remove failed"


@pytest.mark.asyncio
async def test_plugin_manager_update_plugin_covers_unavailable_missing_success_and_failure() -> (
    None
):
    """更新插件应覆盖所有主要结果分支。"""

    plugin = SimpleNamespace(name="calendar")

    unavailable_tool = PluginManagerTool(context=SimpleNamespace())
    assert await unavailable_tool.update_plugin("calendar") == "❌ 插件管理器不可用"

    missing_manager = FakePluginManager()
    missing_tool = PluginManagerTool(context=FakeContext(star_manager=missing_manager))
    assert await missing_tool.update_plugin("calendar") == "❌ 未找到插件: calendar"

    success_manager = FakePluginManager()
    success_tool = PluginManagerTool(
        context=FakeContext(
            star_manager=success_manager,
            config={"plugin_settings": {"github_proxy": "https://proxy.example.com"}},
            registered_stars={"calendar": plugin},
        )
    )
    success = await success_tool.update_plugin("calendar")
    assert success == "✅ 插件 `calendar` 更新成功！\n🚀 使用加速: https://proxy.example.com"
    assert success_manager.updator.update_calls == [
        {"plugin": plugin, "proxy": "https://proxy.example.com"}
    ]
    assert success_manager.reload_calls == ["calendar"]

    failed_manager = FakePluginManager(
        updator=FakePluginUpdator(update_error=RuntimeError("update failed"))
    )
    failed_tool = PluginManagerTool(
        context=FakeContext(
            star_manager=failed_manager,
            registered_stars={"calendar": plugin},
        )
    )
    assert await failed_tool.update_plugin("calendar") == "❌ 更新失败: update failed"


@pytest.mark.asyncio
async def test_plugin_manager_update_plugin_success_without_proxy() -> None:
    """未配置代理时，成功更新结果不应包含加速提示。"""

    plugin = SimpleNamespace(name="calendar")
    manager = FakePluginManager()
    tool = PluginManagerTool(
        context=FakeContext(
            star_manager=manager,
            registered_stars={"calendar": plugin},
        )
    )

    result = await tool.update_plugin("calendar")

    assert result == "✅ 插件 `calendar` 更新成功！"
    assert manager.updator.update_calls == [{"plugin": plugin, "proxy": ""}]
    assert manager.reload_calls == ["calendar"]


def test_plugin_manager_get_available_proxies_and_invalidate_cache() -> None:
    """应渲染代理列表，并在失效时清空缓存。"""

    direct_tool = PluginManagerTool(
        context=FakeContext(config={"plugin_settings": {"github_proxy": ""}})
    )
    direct_text = direct_tool.get_available_proxies()
    assert "✅ 不使用加速 (直连)" in direct_text

    proxy_tool = PluginManagerTool(
        context=FakeContext(
            config={"plugin_settings": {"github_proxy": GITHUB_PROXIES[1]}},
        )
    )
    proxy_text = proxy_tool.get_available_proxies()
    assert f"✅ {GITHUB_PROXIES[1]}" in proxy_text
    assert "💡 在 AstrBot WebUI → 插件管理 中设置加速" in proxy_text

    proxy_tool._plugin_cache = [{"name": "demo"}]
    proxy_tool._cache_valid = True
    proxy_tool.invalidate_cache()
    assert proxy_tool._plugin_cache == []
    assert proxy_tool._cache_valid is False
