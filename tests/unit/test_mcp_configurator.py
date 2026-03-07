"""MCPConfiguratorTool 单元测试。"""

from __future__ import annotations

import asyncio
import builtins
import json
from pathlib import Path
import socket
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

import astrbot_orchestrator_v5.autonomous.mcp_configurator as mcp_module
from astrbot_orchestrator_v5.autonomous.mcp_configurator import MCPConfiguratorTool

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


class FakeMcpClient:
    """模拟 AstrBot 中的 MCP 客户端对象。"""

    def __init__(
        self,
        *,
        active: bool = True,
        tools: list[Any] | None = None,
        cleanup_error: Exception | None = None,
    ) -> None:
        """保存客户端状态、工具列表与清理行为。"""

        self.active = active
        self.tools = list(tools or [])
        self.cleanup_error = cleanup_error
        self.cleanup_calls = 0

    async def cleanup(self) -> None:
        """记录清理调用，必要时抛出异常。"""

        self.cleanup_calls += 1
        if self.cleanup_error is not None:
            raise self.cleanup_error


class FakeToolManager:
    """模拟 MCP 工具管理器。"""

    def __init__(
        self,
        *,
        mcp_clients: dict[str, FakeMcpClient] | None = None,
        enable_error: Exception | None = None,
    ) -> None:
        """保存客户端字典与启用失败行为。"""

        self.mcp_client_dict = dict(mcp_clients or {})
        self.enable_error = enable_error
        self.enable_calls: list[dict[str, Any]] = []

    async def enable_mcp_server(self, *, name: str, config: dict[str, Any]) -> None:
        """记录启用参数，必要时抛出异常。"""

        self.enable_calls.append({"name": name, "config": config})
        if self.enable_error is not None:
            raise self.enable_error


class FakeContext:
    """为 MCPConfiguratorTool 提供最小上下文依赖。"""

    def __init__(
        self,
        *,
        tool_manager: FakeToolManager | None = None,
        llm_responses: list[str] | None = None,
        llm_error: Exception | None = None,
    ) -> None:
        """保存工具管理器与 LLM 预设行为。"""

        self.provider_manager = SimpleNamespace(llm_tools=tool_manager)
        self._llm_responses = list(llm_responses or [])
        self._llm_error = llm_error
        self.llm_calls: list[dict[str, Any]] = []

    async def llm_generate(self, **kwargs: Any) -> SimpleNamespace:
        """记录调用并返回预设完成文本。"""

        self.llm_calls.append(kwargs)
        if self._llm_error is not None:
            raise self._llm_error
        text = self._llm_responses.pop(0) if self._llm_responses else ""
        return SimpleNamespace(completion_text=text)


class FakeHttpResponse:
    """模拟 aiohttp 响应对象。"""

    def __init__(
        self,
        *,
        status: int = 200,
        json_data: Any = None,
    ) -> None:
        """保存状态码与 JSON 数据。"""

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
        """离开异步上下文，不吞掉异常。"""

        del exc_type, exc, tb
        return False

    async def json(self) -> Any:
        """返回预设 JSON 结果。"""

        return self._json_data


class FakeClientSession:
    """模拟 aiohttp.ClientSession。"""

    def __init__(
        self,
        *,
        get_results: list[Any] | None = None,
        post_results: list[Any] | None = None,
    ) -> None:
        """保存 GET/POST 请求结果队列。"""

        self._get_results = list(get_results or [])
        self._post_results = list(post_results or [])
        self.get_calls: list[dict[str, Any]] = []
        self.post_calls: list[dict[str, Any]] = []

    async def __aenter__(self) -> FakeClientSession:
        """进入异步上下文并返回自身。"""

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> bool:
        """离开异步上下文，不吞掉异常。"""

        del exc_type, exc, tb
        return False

    def get(self, url: str, **kwargs: Any) -> Any:
        """返回下一个 GET 结果或抛出预设异常。"""

        self.get_calls.append({"url": url, "kwargs": kwargs})
        result = self._get_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def post(self, url: str, **kwargs: Any) -> Any:
        """返回下一个 POST 结果或抛出预设异常。"""

        self.post_calls.append({"url": url, "kwargs": kwargs})
        result = self._post_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    """提供隔离的 MCP 配置文件路径。"""

    return tmp_path / "data" / "mcp_config.json"


def test_mcp_configurator_get_tool_manager_handles_missing_provider_manager() -> None:
    """缺少 provider_manager 时应返回 None。"""

    tool = MCPConfiguratorTool(context=SimpleNamespace())

    assert tool._get_tool_manager() is None


def test_mcp_configurator_get_mcp_config_path_supports_import_and_fallback(
    monkeypatch: "MonkeyPatch",
) -> None:
    """配置路径应优先使用 AstrBot 数据目录，并在导入失败时回退。"""

    tool = MCPConfiguratorTool(context=FakeContext())
    original_import = builtins.__import__
    fake_module = ModuleType("astrbot.core.utils.astrbot_path")
    fake_module.get_astrbot_data_path = lambda: "/tmp/astrbot-data"  # type: ignore[attr-defined]

    def import_success(
        name: str,
        globals_dict: dict[str, Any] | None = None,
        locals_dict: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        """为 AstrBot 路径模块返回假实现。"""

        if name == "astrbot.core.utils.astrbot_path":
            return fake_module
        return original_import(name, globals_dict, locals_dict, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_success)
    assert tool._get_mcp_config_path() == "/tmp/astrbot-data/mcp_config.json"

    def import_failure(
        name: str,
        globals_dict: dict[str, Any] | None = None,
        locals_dict: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        """对 AstrBot 路径模块模拟 ImportError。"""

        if name == "astrbot.core.utils.astrbot_path":
            raise ImportError("missing")
        return original_import(name, globals_dict, locals_dict, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_failure)
    monkeypatch.setattr(
        mcp_module.os.path, "expanduser", lambda path: "/tmp/fallback/mcp_config.json"
    )

    assert tool._get_mcp_config_path() == "/tmp/fallback/mcp_config.json"


@pytest.mark.parametrize(
    ("url", "resolved_hosts"),
    [
        ("https://example.com/sse", ["93.184.216.34"]),
        ("https://mcp.example.org/api", ["8.8.4.4"]),
        ("https://8.8.8.8/mcp", ["8.8.8.8"]),
    ],
)
def test_mcp_configurator_validate_server_url_accepts_public_https(
    url: str,
    resolved_hosts: list[str],
    monkeypatch: "MonkeyPatch",
) -> None:
    """公共 HTTPS 地址应通过校验。"""

    monkeypatch.setattr(
        mcp_module.socket,
        "getaddrinfo",
        lambda host, port, type=socket.SOCK_STREAM: [
            (socket.AF_INET, type, 6, "", (ip, port)) for ip in resolved_hosts
        ],
    )
    MCPConfiguratorTool._validate_server_url(url)


@pytest.mark.parametrize(
    ("url", "message", "resolved_hosts"),
    [
        ("http://example.com", "仅允许使用 HTTPS", ["93.184.216.34"]),
        ("https://", "缺少主机名", ["93.184.216.34"]),
        ("https://localhost:8080", "拒绝本地或局域网主机", ["127.0.0.1"]),
        ("https://demo.local/service", "拒绝本地或局域网主机", ["127.0.0.1"]),
        ("https://127.0.0.1/api", "拒绝私网、环回或保留地址", ["127.0.0.1"]),
        ("https://10.0.0.5/api", "拒绝私网、环回或保留地址", ["10.0.0.5"]),
        ("https://internal.example/api", "拒绝私网、环回或保留地址", ["127.0.0.1"]),
    ],
)
def test_mcp_configurator_validate_server_url_rejects_unsafe_targets(
    url: str,
    message: str,
    resolved_hosts: list[str],
    monkeypatch: "MonkeyPatch",
) -> None:
    """非 HTTPS 或局域网地址应被安全校验拦截。"""

    monkeypatch.setattr(
        mcp_module.socket,
        "getaddrinfo",
        lambda host, port, type=socket.SOCK_STREAM: [
            (socket.AF_INET, type, 6, "", (ip, port)) for ip in resolved_hosts
        ],
    )
    with pytest.raises(ValueError, match=message):
        MCPConfiguratorTool._validate_server_url(url)


def test_mcp_configurator_validate_server_url_rejects_unresolvable_hostname(
    monkeypatch: "MonkeyPatch",
) -> None:
    """无法解析的主机名应被视为不安全目标。"""

    def fail_lookup(host: str, port: int, type: int = socket.SOCK_STREAM) -> list[Any]:
        del host, port, type
        raise socket.gaierror("dns failed")

    monkeypatch.setattr(mcp_module.socket, "getaddrinfo", fail_lookup)

    with pytest.raises(ValueError, match="主机名无法解析"):
        MCPConfiguratorTool._validate_server_url("https://missing.example/api")


def test_mcp_configurator_load_and_save_config_handles_missing_and_invalid_json(
    config_path: Path,
    monkeypatch: "MonkeyPatch",
) -> None:
    """配置读写应支持首次创建，并在损坏 JSON 时回退默认值。"""

    tool = MCPConfiguratorTool(context=FakeContext())
    monkeypatch.setattr(tool, "_get_mcp_config_path", lambda: str(config_path))

    assert tool._load_mcp_config() == {"mcpServers": {}}

    config = {
        "mcpServers": {
            "demo": {
                "url": "https://example.com/sse",
                "transport": "sse",
                "active": True,
            }
        }
    }
    tool._save_mcp_config(config)

    assert json.loads(config_path.read_text(encoding="utf-8")) == config
    assert tool._load_mcp_config() == config

    config_path.write_text("{broken json", encoding="utf-8")

    assert tool._load_mcp_config() == {"mcpServers": {}}


def test_mcp_configurator_list_servers_renders_active_clients_and_configured_servers(
    config_path: Path,
    monkeypatch: "MonkeyPatch",
) -> None:
    """服务器列表应同时展示活动客户端和配置文件内容。"""

    tool_manager = FakeToolManager(
        mcp_clients={
            "search": FakeMcpClient(active=True, tools=[object(), object()]),
            "memory": FakeMcpClient(active=False, tools=[object()]),
        }
    )
    context = FakeContext(tool_manager=tool_manager)
    tool = MCPConfiguratorTool(context=context)
    monkeypatch.setattr(tool, "_get_mcp_config_path", lambda: str(config_path))
    tool._save_mcp_config(
        {
            "mcpServers": {
                "search": {"url": "https://example.com/search", "active": True},
                "memory": {"url": "https://example.com/memory", "active": False},
            }
        }
    )

    result = tool.list_servers()

    assert "✅ **search** (2 工具)" in result
    assert "❌ **memory** (1 工具)" in result
    assert "✅ search: https://example.com/search..." in result
    assert "❌ memory: https://example.com/memory..." in result
    assert "/mcp add <名称> <url>" in result


def test_mcp_configurator_list_servers_handles_empty_tool_manager(
    config_path: Path,
    monkeypatch: "MonkeyPatch",
) -> None:
    """没有活动客户端时应显示空提示。"""

    tool = MCPConfiguratorTool(context=FakeContext(tool_manager=FakeToolManager()))
    monkeypatch.setattr(tool, "_get_mcp_config_path", lambda: str(config_path))

    result = tool.list_servers()

    assert "暂无活跃的 MCP 服务器" in result


def test_mcp_configurator_list_servers_still_renders_config_without_tool_manager(
    config_path: Path,
    monkeypatch: "MonkeyPatch",
) -> None:
    """没有工具管理器时仍应显示配置文件中的服务器。"""

    tool = MCPConfiguratorTool(context=FakeContext(tool_manager=None))
    monkeypatch.setattr(tool, "_get_mcp_config_path", lambda: str(config_path))
    tool._save_mcp_config(
        {"mcpServers": {"search": {"url": "https://example.com/sse", "active": True}}}
    )

    result = tool.list_servers()

    assert "✅ search: https://example.com/sse..." in result
    assert "/mcp add <名称> <url>" in result


@pytest.mark.asyncio
async def test_mcp_configurator_add_server_success_persists_and_enables(
    config_path: Path,
    monkeypatch: "MonkeyPatch",
) -> None:
    """添加服务器成功时应写入配置并调用启用逻辑。"""

    tool_manager = FakeToolManager()
    tool = MCPConfiguratorTool(context=FakeContext(tool_manager=tool_manager))
    monkeypatch.setattr(tool, "_get_mcp_config_path", lambda: str(config_path))
    monkeypatch.setenv("MCP_AUTH_TOKEN", "Bearer demo")
    monkeypatch.setattr(
        mcp_module.socket,
        "getaddrinfo",
        lambda host, port, type=socket.SOCK_STREAM: [
            (socket.AF_INET, type, 6, "", ("93.184.216.34", port))
        ],
    )

    result = await tool.add_server(
        name="search",
        url="https://example.com/sse",
        transport="streamable_http",
        headers={"Authorization": "env:MCP_AUTH_TOKEN"},
    )

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert "✅ MCP 服务器 `search` 添加成功！" in result
    assert "传输: streamable_http" in result
    assert saved["mcpServers"]["search"]["headers"] == {"Authorization": "env:MCP_AUTH_TOKEN"}
    assert tool_manager.enable_calls == [
        {
            "name": "search",
            "config": {
                "url": "https://example.com/sse",
                "transport": "streamable_http",
                "active": True,
                "headers": {"Authorization": "Bearer demo"},
            },
        }
    ]


@pytest.mark.asyncio
async def test_mcp_configurator_add_server_rejects_raw_sensitive_headers(
    config_path: Path,
    monkeypatch: "MonkeyPatch",
) -> None:
    """敏感请求头不能以明文形式写入配置。"""

    tool = MCPConfiguratorTool(context=FakeContext(tool_manager=FakeToolManager()))
    monkeypatch.setattr(tool, "_get_mcp_config_path", lambda: str(config_path))
    monkeypatch.setattr(
        mcp_module.socket,
        "getaddrinfo",
        lambda host, port, type=socket.SOCK_STREAM: [
            (socket.AF_INET, type, 6, "", ("93.184.216.34", port))
        ],
    )

    result = await tool.add_server(
        name="search",
        url="https://example.com/sse",
        headers={"Authorization": "Bearer secret"},
    )

    assert result == "❌ 添加失败: 敏感请求头 `Authorization` 必须使用环境变量引用"
    assert not config_path.exists()


@pytest.mark.asyncio
async def test_mcp_configurator_add_server_handles_duplicate_enable_failure_and_validation(
    config_path: Path,
    monkeypatch: "MonkeyPatch",
) -> None:
    """重复名称、启用失败和非法地址都应返回对应结果。"""

    tool_manager = FakeToolManager(enable_error=RuntimeError("enable failed"))
    tool = MCPConfiguratorTool(context=FakeContext(tool_manager=tool_manager))
    monkeypatch.setattr(tool, "_get_mcp_config_path", lambda: str(config_path))
    monkeypatch.setattr(
        mcp_module.socket,
        "getaddrinfo",
        lambda host, port, type=socket.SOCK_STREAM: [
            (socket.AF_INET, type, 6, "", ("93.184.216.34", port))
        ],
    )

    tool._save_mcp_config(
        {"mcpServers": {"existing": {"url": "https://example.com", "active": True}}}
    )

    duplicate = await tool.add_server("existing", "https://another.example.com")
    assert "已存在" in duplicate

    enable_failed = await tool.add_server("new", "https://public.example.com")
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert "已添加到配置，但启用失败: enable failed" in enable_failed
    assert saved["mcpServers"]["new"]["url"] == "https://public.example.com"

    invalid = await tool.add_server("bad", "http://unsafe.example.com")
    assert invalid == "❌ 添加失败: MCP 服务仅允许使用 HTTPS 地址"


@pytest.mark.asyncio
async def test_mcp_configurator_add_server_skips_enable_when_tool_manager_unavailable(
    config_path: Path,
    monkeypatch: "MonkeyPatch",
) -> None:
    """没有工具管理器时仍应保存配置。"""

    tool = MCPConfiguratorTool(context=FakeContext(tool_manager=None))
    monkeypatch.setattr(tool, "_get_mcp_config_path", lambda: str(config_path))
    monkeypatch.setattr(
        mcp_module.socket,
        "getaddrinfo",
        lambda host, port, type=socket.SOCK_STREAM: [
            (socket.AF_INET, type, 6, "", ("93.184.216.34", port))
        ],
    )

    result = await tool.add_server("search", "https://example.com/sse")

    assert "✅ MCP 服务器 `search` 添加成功！" in result
    assert (
        json.loads(config_path.read_text(encoding="utf-8"))["mcpServers"]["search"]["active"]
        is True
    )


@pytest.mark.asyncio
async def test_mcp_configurator_remove_server_handles_missing_cleanup_and_failure(
    config_path: Path,
    monkeypatch: "MonkeyPatch",
) -> None:
    """移除服务器应覆盖不存在、清理失败和保存失败分支。"""

    tool_manager = FakeToolManager(
        mcp_clients={
            "search": FakeMcpClient(cleanup_error=RuntimeError("cleanup failed")),
        }
    )
    tool = MCPConfiguratorTool(context=FakeContext(tool_manager=tool_manager))
    monkeypatch.setattr(tool, "_get_mcp_config_path", lambda: str(config_path))

    missing = await tool.remove_server("search")
    assert missing == "❌ MCP 服务器 `search` 不存在"

    tool._save_mcp_config(
        {"mcpServers": {"search": {"url": "https://example.com/sse", "active": True}}}
    )

    removed = await tool.remove_server("search")
    assert removed == "✅ MCP 服务器 `search` 已移除"
    assert tool_manager.mcp_client_dict["search"].cleanup_calls == 1
    assert "search" in tool_manager.mcp_client_dict

    tool._save_mcp_config(
        {"mcpServers": {"broken": {"url": "https://example.com/sse", "active": True}}}
    )

    def fail_save(config: dict[str, Any]) -> None:
        """模拟配置写入失败。"""

        del config
        raise OSError("disk full")

    monkeypatch.setattr(tool, "_save_mcp_config", fail_save)
    failed = await tool.remove_server("broken")
    assert failed == "❌ 移除失败: disk full"


@pytest.mark.asyncio
async def test_mcp_configurator_remove_server_deletes_client_after_successful_cleanup(
    config_path: Path,
    monkeypatch: "MonkeyPatch",
) -> None:
    """客户端清理成功后应从活动字典中删除。"""

    tool_manager = FakeToolManager(mcp_clients={"search": FakeMcpClient()})
    tool = MCPConfiguratorTool(context=FakeContext(tool_manager=tool_manager))
    monkeypatch.setattr(tool, "_get_mcp_config_path", lambda: str(config_path))
    tool._save_mcp_config(
        {"mcpServers": {"search": {"url": "https://example.com/sse", "active": True}}}
    )

    result = await tool.remove_server("search")

    assert result == "✅ MCP 服务器 `search` 已移除"
    assert "search" not in tool_manager.mcp_client_dict


@pytest.mark.asyncio
async def test_mcp_configurator_remove_server_skips_cleanup_without_tool_manager(
    config_path: Path,
    monkeypatch: "MonkeyPatch",
) -> None:
    """没有工具管理器时，移除服务器仍应成功。"""

    tool = MCPConfiguratorTool(context=FakeContext(tool_manager=None))
    monkeypatch.setattr(tool, "_get_mcp_config_path", lambda: str(config_path))
    tool._save_mcp_config(
        {"mcpServers": {"search": {"url": "https://example.com/sse", "active": True}}}
    )

    result = await tool.remove_server("search")

    assert result == "✅ MCP 服务器 `search` 已移除"


@pytest.mark.asyncio
async def test_mcp_configurator_remove_server_handles_missing_loaded_client(
    config_path: Path,
    monkeypatch: "MonkeyPatch",
) -> None:
    """配置存在但客户端未连接时，移除仍应成功。"""

    tool = MCPConfiguratorTool(context=FakeContext(tool_manager=FakeToolManager()))
    monkeypatch.setattr(tool, "_get_mcp_config_path", lambda: str(config_path))
    tool._save_mcp_config(
        {"mcpServers": {"search": {"url": "https://example.com/sse", "active": True}}}
    )

    result = await tool.remove_server("search")

    assert result == "✅ MCP 服务器 `search` 已移除"


@pytest.mark.asyncio
async def test_mcp_configurator_test_server_covers_streamable_http_and_sse_paths(
    config_path: Path,
    monkeypatch: "MonkeyPatch",
) -> None:
    """连接测试应覆盖 POST 初始化和 SSE 检查。"""

    tool = MCPConfiguratorTool(context=FakeContext())
    monkeypatch.setattr(tool, "_get_mcp_config_path", lambda: str(config_path))
    monkeypatch.setenv("MCP_TEST_TOKEN", "Bearer test")
    monkeypatch.setattr(
        mcp_module.socket,
        "getaddrinfo",
        lambda host, port, type=socket.SOCK_STREAM: [
            (socket.AF_INET, type, 6, "", ("93.184.216.34", port))
        ],
    )
    tool._save_mcp_config(
        {
            "mcpServers": {
                "http-server": {
                    "url": "https://example.com/http",
                    "transport": "streamable_http",
                    "headers": {"Authorization": "env:MCP_TEST_TOKEN"},
                },
                "sse-server": {
                    "url": "https://example.com/sse",
                    "transport": "sse",
                    "headers": {"X-Test": "1"},
                },
            }
        }
    )

    fake_session = FakeClientSession(
        post_results=[FakeHttpResponse(status=200)],
        get_results=[FakeHttpResponse(status=503)],
    )
    monkeypatch.setattr(mcp_module.aiohttp, "ClientSession", lambda: fake_session)

    http_result = await tool.test_server("http-server")
    sse_result = await tool.test_server("sse-server")

    assert "连接正常" in http_result
    assert "HTTP 200" in http_result
    post_call = fake_session.post_calls[0]
    assert post_call["url"] == "https://example.com/http"
    assert post_call["kwargs"]["headers"]["Authorization"] == "Bearer test"
    assert post_call["kwargs"]["headers"]["Content-Type"] == "application/json"
    assert post_call["kwargs"]["json"]["method"] == "initialize"

    assert sse_result == "❌ 连接失败: HTTP 503"
    get_call = fake_session.get_calls[0]
    assert get_call["url"] == "https://example.com/sse"
    assert get_call["kwargs"]["headers"]["Accept"] == "text/event-stream"


@pytest.mark.asyncio
async def test_mcp_configurator_test_server_covers_remaining_status_branches(
    config_path: Path,
    monkeypatch: "MonkeyPatch",
) -> None:
    """连接测试应覆盖 HTTP 非 200 与 SSE 成功分支。"""

    tool = MCPConfiguratorTool(context=FakeContext())
    monkeypatch.setattr(tool, "_get_mcp_config_path", lambda: str(config_path))
    monkeypatch.setattr(
        mcp_module.socket,
        "getaddrinfo",
        lambda host, port, type=socket.SOCK_STREAM: [
            (socket.AF_INET, type, 6, "", ("93.184.216.34", port))
        ],
    )
    tool._save_mcp_config(
        {
            "mcpServers": {
                "http-fail": {
                    "url": "https://example.com/http-fail",
                    "transport": "streamable_http",
                },
                "sse-ok": {
                    "url": "https://example.com/sse-ok",
                    "transport": "sse",
                },
            }
        }
    )
    fake_session = FakeClientSession(
        post_results=[FakeHttpResponse(status=500)],
        get_results=[FakeHttpResponse(status=200)],
    )
    monkeypatch.setattr(mcp_module.aiohttp, "ClientSession", lambda: fake_session)

    http_failed = await tool.test_server("http-fail")
    sse_ok = await tool.test_server("sse-ok")

    assert http_failed == "❌ 连接失败: HTTP 500"
    assert "连接正常" in sse_ok
    assert "HTTP 200" in sse_ok


@pytest.mark.asyncio
async def test_mcp_configurator_test_server_handles_missing_timeout_and_generic_errors(
    config_path: Path,
    monkeypatch: "MonkeyPatch",
) -> None:
    """连接测试应处理不存在、超时和一般异常。"""

    tool = MCPConfiguratorTool(context=FakeContext())
    monkeypatch.setattr(tool, "_get_mcp_config_path", lambda: str(config_path))

    missing = await tool.test_server("missing")
    assert missing == "❌ MCP 服务器 `missing` 不存在"

    tool._save_mcp_config(
        {
            "mcpServers": {
                "timeout-server": {"url": "https://example.com/timeout", "transport": "sse"},
                "error-server": {"url": "https://example.com/error", "transport": "sse"},
            }
        }
    )
    fake_session = FakeClientSession(
        get_results=[asyncio.TimeoutError(), RuntimeError("network down")],
    )
    monkeypatch.setattr(mcp_module.aiohttp, "ClientSession", lambda: fake_session)

    timeout_result = await tool.test_server("timeout-server")
    error_result = await tool.test_server("error-server")

    assert timeout_result == "❌ 连接超时: https://example.com/timeout"
    assert error_result == "❌ 连接失败: network down"


@pytest.mark.asyncio
async def test_mcp_configurator_test_server_rejects_unsafe_configured_url(
    config_path: Path,
    monkeypatch: "MonkeyPatch",
) -> None:
    """测试连接前应再次校验配置中的 URL 安全性。"""

    tool = MCPConfiguratorTool(context=FakeContext())
    monkeypatch.setattr(tool, "_get_mcp_config_path", lambda: str(config_path))
    tool._save_mcp_config(
        {"mcpServers": {"unsafe": {"url": "https://127.0.0.1/api", "transport": "sse"}}}
    )

    with pytest.raises(ValueError, match="拒绝私网、环回或保留地址"):
        await tool.test_server("unsafe")


def test_mcp_configurator_list_tools_covers_unavailable_missing_empty_and_success() -> None:
    """工具列表应覆盖管理器缺失、客户端缺失、空工具和正常输出。"""

    no_manager_tool = MCPConfiguratorTool(context=FakeContext(tool_manager=None))
    assert no_manager_tool.list_tools("search") == "❌ 工具管理器不可用"

    empty_manager_tool = MCPConfiguratorTool(context=FakeContext(tool_manager=FakeToolManager()))
    assert empty_manager_tool.list_tools("search") == "❌ MCP 服务器 `search` 未连接或不存在"

    tool_manager = FakeToolManager(
        mcp_clients={
            "search": FakeMcpClient(active=True, tools=[]),
            "memory": FakeMcpClient(
                active=True,
                tools=[
                    SimpleNamespace(
                        name="lookup",
                        description="用于检索公开网页与知识库的工具描述",
                    )
                ],
            ),
        }
    )
    tool = MCPConfiguratorTool(context=FakeContext(tool_manager=tool_manager))

    assert tool.list_tools("search") == "🔌 MCP 服务器 `search` 暂无工具"

    rendered = tool.list_tools("memory")
    assert "🔌 **memory** 的工具列表 (1 个)：" in rendered
    assert "• **lookup**" in rendered
    assert "用于检索公开网页与知识库的工具描述" in rendered


@pytest.mark.asyncio
async def test_mcp_configurator_create_mcp_from_description_success_and_failure() -> None:
    """根据描述生成配置建议时应覆盖成功和失败返回。"""

    success_context = FakeContext(llm_responses=["use tavily"])
    success_tool = MCPConfiguratorTool(context=success_context)

    success = await success_tool.create_mcp_from_description(
        name="search",
        user_description="我想要一个网页搜索 MCP",
        provider_id="provider-a",
    )

    assert success == "use tavily"
    llm_call = success_context.llm_calls[0]
    assert llm_call["chat_provider_id"] == "provider-a"
    assert "网页搜索 MCP" in llm_call["prompt"]
    assert llm_call["system_prompt"] == "你是一个 MCP 协议专家，熟悉各种 MCP 服务的配置。"

    failed_tool = MCPConfiguratorTool(context=FakeContext(llm_error=RuntimeError("llm down")))
    failed = await failed_tool.create_mcp_from_description(
        name="search",
        user_description="我想要一个网页搜索 MCP",
        provider_id="provider-a",
    )

    assert failed == "❌ 分析失败: llm down"
