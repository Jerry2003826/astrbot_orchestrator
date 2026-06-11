"""astrbot.core.star.context 测试桩，对齐 v4.25.5 Context 公开方法签名。

行为依赖宿主运行时的方法默认抛 NotImplementedError，测试用 Fake 覆盖。
"""

from typing import Any

from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.provider.register import llm_tools

from .star import StarMetadata, star_registry


class Context:
    def __init__(
        self,
        event_queue: Any = None,
        config: AstrBotConfig | None = None,
        db: Any = None,
        provider_manager: Any = None,
        platform_manager: Any = None,
        conversation_manager: Any = None,
        message_history_manager: Any = None,
        persona_manager: Any = None,
        astrbot_config_mgr: Any = None,
        subagent_orchestrator: Any = None,
    ) -> None:
        self._event_queue = event_queue
        self._config = config if config is not None else AstrBotConfig()
        self._db = db
        self.provider_manager = provider_manager
        self.platform_manager = platform_manager
        self.conversation_manager = conversation_manager
        self.message_history_manager = message_history_manager
        self.persona_manager = persona_manager
        self.astrbot_config_mgr = astrbot_config_mgr
        self.subagent_orchestrator = subagent_orchestrator
        # 真实宿主中由 PluginManager 注入
        self._star_manager: Any = None

    # ------------------------------------------------------------------
    # LLM / Agent
    # ------------------------------------------------------------------
    async def llm_generate(
        self,
        *,
        chat_provider_id: str,
        prompt: str | None = None,
        image_urls: list[str] | None = None,
        audio_urls: list[str] | None = None,
        tools: ToolSet | None = None,
        system_prompt: str | None = None,
        contexts: list[Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        raise NotImplementedError("stub")

    async def tool_loop_agent(
        self,
        *,
        event: AstrMessageEvent,
        chat_provider_id: str,
        prompt: str | None = None,
        image_urls: list[str] | None = None,
        audio_urls: list[str] | None = None,
        tools: ToolSet | None = None,
        system_prompt: str | None = None,
        contexts: list[Any] | None = None,
        max_steps: int = 30,
        tool_call_timeout: int = 120,
        **kwargs: Any,
    ) -> Any:
        raise NotImplementedError("stub")

    # ------------------------------------------------------------------
    # Provider
    # ------------------------------------------------------------------
    def get_provider_by_id(self, provider_id: str) -> Any:
        raise NotImplementedError("stub")

    def get_all_providers(self) -> list[Any]:
        raise NotImplementedError("stub")

    def get_using_provider(self, umo: str | None = None) -> Any:
        raise NotImplementedError("stub")

    async def get_current_chat_provider_id(self, umo: str) -> str:
        raise NotImplementedError("stub")

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    def get_llm_tool_manager(self) -> Any:
        return llm_tools

    def add_llm_tools(self, *tools: FunctionTool) -> None:
        for tool in tools:
            llm_tools.add_tool(tool)

    def activate_llm_tool(self, name: str) -> bool:
        return llm_tools.activate_llm_tool(name, {})

    def deactivate_llm_tool(self, name: str) -> bool:
        return llm_tools.deactivate_llm_tool(name)

    def register_llm_tool(self, name: str, func_args: list, desc: str, func_obj: Any) -> None:
        llm_tools.add_func(name, func_args, desc, func_obj)

    def unregister_llm_tool(self, name: str) -> None:
        llm_tools.remove_func(name)

    # ------------------------------------------------------------------
    # 插件与配置
    # ------------------------------------------------------------------
    def get_registered_star(self, star_name: str) -> StarMetadata | None:
        for star in star_registry:
            if star.name == star_name:
                return star
        return None

    def get_all_stars(self) -> list[StarMetadata]:
        return star_registry

    def get_config(self, umo: str | None = None) -> AstrBotConfig:
        return self._config

    def get_db(self) -> Any:
        return self._db

    def get_event_queue(self) -> Any:
        return self._event_queue

    def get_platform(self, platform_type: Any) -> Any:
        raise NotImplementedError("stub")

    async def send_message(self, session: Any, message_chain: Any) -> bool:
        raise NotImplementedError("stub")
