"""astrbot.core.subagent_orchestrator 测试桩，对齐 v4.25.5 配置键名与行为。"""

import copy
from typing import Any

from astrbot import logger
from astrbot.core.agent.agent import Agent
from astrbot.core.agent.handoff import HandoffTool


class SubAgentOrchestrator:
    """Loads subagent definitions from config and registers handoff tools."""

    def __init__(self, tool_mgr: Any, persona_mgr: Any = None) -> None:
        self._tool_mgr = tool_mgr
        self._persona_mgr = persona_mgr
        self.handoffs: list[HandoffTool] = []

    async def reload_from_config(self, cfg: dict[str, Any]) -> None:
        agents = cfg.get("agents", [])
        if not isinstance(agents, list):
            logger.warning("subagent_orchestrator.agents must be a list")
            return

        handoffs: list[HandoffTool] = []
        for item in agents:
            if not isinstance(item, dict):
                continue
            if not item.get("enabled", True):
                continue

            name = str(item.get("name", "")).strip()
            if not name:
                continue

            persona_id = item.get("persona_id")
            if persona_id is not None:
                persona_id = str(persona_id).strip() or None
            persona_data = None
            if self._persona_mgr is not None:
                persona_data = self._persona_mgr.get_persona_v3_by_id(persona_id)

            instructions = str(item.get("system_prompt", "")).strip()
            public_description = str(item.get("public_description", "")).strip()
            provider_id = item.get("provider_id")
            if provider_id is not None:
                provider_id = str(provider_id).strip() or None
            tools = item.get("tools", [])
            begin_dialogs = None

            if persona_data:
                prompt = str(persona_data.get("prompt", "")).strip()
                if prompt:
                    instructions = prompt
                begin_dialogs = copy.deepcopy(persona_data.get("_begin_dialogs_processed"))
                tools = persona_data.get("tools")
                if public_description == "" and prompt:
                    public_description = prompt[:120]
            if tools is None:
                tools = None
            elif not isinstance(tools, list):
                tools = []
            else:
                tools = [str(t).strip() for t in tools if str(t).strip()]

            agent = Agent(name=name, instructions=instructions, tools=tools)
            agent.begin_dialogs = begin_dialogs
            handoff = HandoffTool(
                agent=agent,
                tool_description=public_description or None,
            )
            handoff.provider_id = provider_id
            handoffs.append(handoff)

        self.handoffs = handoffs
