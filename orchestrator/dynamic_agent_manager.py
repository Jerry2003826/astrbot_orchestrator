"""官方 SubAgent 配置适配器。

把 agent_templates.py 中的预设模板写入宿主全局配置的
``subagent_orchestrator.agents``，并触发官方 ``reload_from_config``；
子代理的实际执行完全由官方 HandoffTool 体系承担。
"""

from __future__ import annotations

from typing import Any

from astrbot.api import logger

from .agent_templates import AgentTemplateLibrary

MANAGED_FLAG = "managed_by"
MANAGED_VALUE = "astrbot_orchestrator_v5"


class DynamicAgentManager:
    """将插件预设子代理同步到官方 subagent_orchestrator 配置。"""

    def __init__(self, context: Any, config: Any | None = None) -> None:
        self.context = context
        self.config = config or {}
        self.template_library = AgentTemplateLibrary()

    # ------------------------------------------------------------------
    # 模板同步
    # ------------------------------------------------------------------

    def _get_subagent_cfg(self) -> tuple[Any, dict[str, Any]]:
        """返回 (全局配置对象, subagent_orchestrator 段)。"""

        conf = self.context.get_config()
        so_cfg = conf.setdefault("subagent_orchestrator", {})
        if not isinstance(so_cfg, dict):
            so_cfg = {}
            conf["subagent_orchestrator"] = so_cfg
        return conf, so_cfg

    async def sync_templates_to_host(self) -> str:
        """把模板库中的预设写入官方配置并热重载 handoffs。

        已存在的同名 agent（无论是否本插件管理）不会被覆盖。
        """

        conf, so_cfg = self._get_subagent_cfg()
        agents: list[dict[str, Any]] = so_cfg.setdefault("agents", [])
        if not isinstance(agents, list):
            agents = []
            so_cfg["agents"] = agents

        existing_names = {
            str(item.get("name", "")).strip() for item in agents if isinstance(item, dict)
        }

        added: list[str] = []
        for role in self.template_library.list_roles():
            template = self.template_library.get(role)
            if template is None or template.name in existing_names:
                continue
            spec = template.to_spec()
            entry = spec.to_config()
            entry[MANAGED_FLAG] = MANAGED_VALUE
            agents.append(entry)
            added.append(template.name)

        # 让 handoffs 注入主 Agent（用户显式配置过则不动）
        so_cfg.setdefault("main_enable", True)

        if added:
            try:
                conf.save_config()
            except Exception:
                logger.warning("保存 subagent 配置失败", exc_info=True)

        await self._reload_host(so_cfg)
        if added:
            return f"已注册 {len(added)} 个预设子代理: {', '.join(added)}"
        return "预设子代理均已存在，无需更新。"

    async def remove_managed_agents(self) -> str:
        """移除本插件写入的子代理配置。"""

        conf, so_cfg = self._get_subagent_cfg()
        agents = so_cfg.get("agents", [])
        if not isinstance(agents, list):
            return "配置格式异常，未做修改。"

        kept = [
            item
            for item in agents
            if not (isinstance(item, dict) and item.get(MANAGED_FLAG) == MANAGED_VALUE)
        ]
        removed = len(agents) - len(kept)
        if removed:
            so_cfg["agents"] = kept
            try:
                conf.save_config()
            except Exception:
                logger.warning("保存 subagent 配置失败", exc_info=True)
            await self._reload_host(so_cfg)
        return f"已移除 {removed} 个由本插件管理的子代理。"

    async def _reload_host(self, so_cfg: dict[str, Any]) -> None:
        orchestrator = getattr(self.context, "subagent_orchestrator", None)
        if orchestrator is None:
            logger.warning("宿主未初始化 subagent_orchestrator，跳过热重载")
            return
        try:
            await orchestrator.reload_from_config(so_cfg)
        except Exception:
            logger.error("subagent_orchestrator 热重载失败", exc_info=True)

    # ------------------------------------------------------------------
    # 状态查询（读官方 handoffs）
    # ------------------------------------------------------------------

    def status_report(self) -> str:
        orchestrator = getattr(self.context, "subagent_orchestrator", None)
        handoffs = list(getattr(orchestrator, "handoffs", None) or [])
        if not handoffs:
            return (
                "当前没有已注册的子代理。\n"
                "可用 /agent sync 注册本插件预设模板，或在 WebUI 的子代理设置中添加。"
            )
        lines = [f"已注册子代理 ({len(handoffs)}):"]
        for handoff in handoffs:
            agent = getattr(handoff, "agent", None)
            name = getattr(agent, "name", None) or getattr(handoff, "name", "?")
            desc = (getattr(handoff, "description", "") or "").strip()
            provider = getattr(handoff, "provider_id", None)
            line = f"- {name}"
            if provider:
                line += f" (provider: {provider})"
            if desc:
                line += f": {desc[:80]}"
            lines.append(line)
        return "\n".join(lines)

    def templates_report(self) -> str:
        data = self.template_library.export_templates()
        lines = [f"预设子代理模板 ({len(data)}):"]
        for role, info in data.items():
            tools = ", ".join(info.get("tools") or []) or "继承全部工具"
            lines.append(f"- {role} → {info['name']}（工具: {tools}）")
            lines.append(f"  {info['public_description']}")
        lines.append("\n用 /agent sync 将模板注册为官方子代理。")
        return "\n".join(lines)
