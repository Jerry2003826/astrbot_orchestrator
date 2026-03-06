"""
动态 SubAgent 管理器 - 持久化版本

创建的 SubAgents 会保存到 AstrBot 配置文件，在 UI 中可见
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from astrbot.api import logger as astrbot_logger

from .agent_registry import AgentRegistry, AgentRecord
from .agent_templates import AgentSpec, AgentTemplateLibrary

logger = astrbot_logger

CONFIG_PATH = '/AstrBot/data/cmd_config.json'


class DynamicAgentManager:
    """动态创建/销毁 SubAgent，并持久化到 AstrBot 配置"""

    def __init__(self, context, config: Optional[Dict[str, Any]] = None):
        self.context = context
        self.config = config or {}
        self.registry = AgentRegistry()
        self.template_library = AgentTemplateLibrary(self._load_template_overrides())
        self._dynamic_agents: Dict[str, AgentSpec] = {}

    def _get_default_provider_id(self) -> str:
        """获取默认的 LLM provider ID"""
        # 优先从 orchestrator 配置获取
        if isinstance(self.config, dict):
            provider = self.config.get("llm_provider")
            if provider:
                return provider
        
        # 从插件配置文件获取
        try:
            config_path = '/AstrBot/data/config/astrbot_orchestrator_config.json'
            with open(config_path, 'r', encoding='utf-8-sig') as f:
                orch_config = json.load(f)
            provider = orch_config.get("llm_provider")
            if provider:
                return provider
        except Exception:
            pass
        
        # 默认值
        return "openai_1/qwen-max-latest"

    def _load_template_overrides(self) -> Dict[str, Any]:
        overrides = None
        if isinstance(self.config, dict):
            overrides = self.config.get("subagent_template_overrides")
            if not overrides:
                settings = self.config.get("subagent_settings", {})
                if isinstance(settings, dict):
                    overrides = settings.get("subagent_template_overrides")

        if isinstance(overrides, dict):
            return overrides
        if isinstance(overrides, str) and overrides.strip():
            try:
                return json.loads(overrides)
            except Exception:
                logger.warning("解析 subagent_template_overrides 失败")
        return {}

    def _get_subagent_orchestrator(self):
        return getattr(self.context, "subagent_orchestrator", None)

    def _get_tool_manager(self):
        try:
            return self.context.provider_manager.llm_tools
        except AttributeError:
            return None

    def _load_base_agents(self) -> List[Dict[str, Any]]:
        """加载基础 agents（非动态创建的）"""
        try:
            # 优先从内存配置读取
            astrbot_config = self._get_astrbot_config()
            if astrbot_config is not None:
                subagent_cfg = astrbot_config.get("subagent_orchestrator", {})
            else:
                # 备选：从文件读取
                with open(CONFIG_PATH, 'r', encoding='utf-8-sig') as f:
                    cfg = json.load(f)
                subagent_cfg = cfg.get("subagent_orchestrator", {})
            
            agents = subagent_cfg.get("agents", [])
            if isinstance(agents, list):
                return [a for a in agents if not a.get('_dynamic_', False)]
        except Exception as e:
            logger.warning("加载配置失败: %s", e)
        return []

    async def create_agents(self, specs: List[AgentSpec]) -> List[AgentSpec]:
        """创建动态 agents 并持久化到配置"""
        created = []
        name_counts: Dict[str, int] = {}
        
        # 获取默认 provider_id
        default_provider = self._get_default_provider_id()

        for spec in specs:
            # 自动设置 provider_id
            if not spec.provider_id:
                spec.provider_id = default_provider
            
            name_counts.setdefault(spec.name, 0)
            name_counts[spec.name] += 1
            if name_counts[spec.name] > 1:
                spec.name = f"{spec.name}_{name_counts[spec.name]}"

            self._dynamic_agents[spec.agent_id] = spec
            self.registry.register(
                AgentRecord(
                    agent_id=spec.agent_id,
                    name=spec.name,
                    role=spec.role,
                    status="active",
                    created_at=datetime.utcnow(),
                    spec=spec,
                    metadata=spec.metadata,
                )
            )
            created.append(spec)

        # 持久化到配置文件并重新加载
        await self._save_to_config()
        await self._reload_subagents()
        
        logger.info("动态 SubAgent 创建完成并已保存: %s", [a.name for a in created])
        return created

    async def cleanup(self, specs: List[AgentSpec]) -> None:
        """清理动态 agents（可选，用户可以在 UI 中手动管理）"""
        agent_ids = [spec.agent_id for spec in specs]
        
        for spec in specs:
            self._dynamic_agents.pop(spec.agent_id, None)
            self.registry.remove(spec.agent_id)
        
        # 从配置文件中移除
        await self._remove_from_config(agent_ids)
        await self._reload_subagents()

    def list_agents(self) -> str:
        return self.registry.summary()

    def get_template_config(self) -> Dict[str, Any]:
        return self.template_library.export_templates()

    def _get_astrbot_config(self):
        """获取 AstrBot 内存中的配置对象"""
        try:
            # 优先通过 context.get_config() 获取
            if hasattr(self.context, 'get_config'):
                return self.context.get_config()
            # 备选：直接访问 astrbot_config 属性
            if hasattr(self.context, 'astrbot_config'):
                return self.context.astrbot_config
        except Exception as e:
            logger.warning("获取 AstrBot 配置对象失败: %s", e)
        return None

    async def _save_to_config(self) -> None:
        """将动态 agents 持久化到 AstrBot 配置（内存+文件）"""
        try:
            # 尝试获取内存中的配置对象
            astrbot_config = self._get_astrbot_config()
            
            if astrbot_config is not None:
                # 方案A: 通过内存配置对象更新（WebUI 实时可见）
                await self._save_to_memory_config(astrbot_config)
            else:
                # 方案B: 直接写文件（备选）
                await self._save_to_file_config()
                
        except Exception as e:
            logger.error("保存 SubAgent 配置失败: %s", e, exc_info=True)

    async def _save_to_memory_config(self, astrbot_config) -> None:
        """通过内存配置对象保存（WebUI 实时可见）"""
        # 获取或创建 subagent_orchestrator 配置
        if 'subagent_orchestrator' not in astrbot_config:
            astrbot_config['subagent_orchestrator'] = {'main_enable': True, 'agents': []}
        
        subagent_config = astrbot_config['subagent_orchestrator']
        if 'agents' not in subagent_config:
            subagent_config['agents'] = []
        
        existing_agents = subagent_config['agents']
        
        # 保留非动态的 agents，移除旧的动态 agents
        existing_agents = [a for a in existing_agents if not a.get('_dynamic_', False)]
        
        # 添加新的动态 agents
        for spec in self._dynamic_agents.values():
            agent_config = spec.to_config()
            agent_config['_dynamic_'] = True  # 标记为动态创建
            agent_config['enabled'] = True
            agent_config['_created_at_'] = datetime.utcnow().isoformat()
            existing_agents.append(agent_config)
        
        subagent_config['agents'] = existing_agents
        
        # 同步保存到文件
        if hasattr(astrbot_config, 'save_config'):
            astrbot_config.save_config()
            logger.info("动态 SubAgents 已保存到内存配置和文件 (共 %d 个)", len(self._dynamic_agents))
        else:
            # 如果没有 save_config 方法，手动写文件
            await self._save_to_file_config()

    async def _save_to_file_config(self) -> None:
        """直接写入配置文件（备选方案）"""
        with open(CONFIG_PATH, 'r', encoding='utf-8-sig') as f:
            config = json.load(f)
        
        if 'subagent_orchestrator' not in config:
            config['subagent_orchestrator'] = {'main_enable': True, 'agents': []}
        
        subagent_config = config['subagent_orchestrator']
        if 'agents' not in subagent_config:
            subagent_config['agents'] = []
        
        existing_agents = subagent_config['agents']
        existing_agents = [a for a in existing_agents if not a.get('_dynamic_', False)]
        
        for spec in self._dynamic_agents.values():
            agent_config = spec.to_config()
            agent_config['_dynamic_'] = True
            agent_config['enabled'] = True
            agent_config['_created_at_'] = datetime.utcnow().isoformat()
            existing_agents.append(agent_config)
        
        subagent_config['agents'] = existing_agents
        
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        
        logger.info("动态 SubAgents 已保存到配置文件 (共 %d 个)", len(self._dynamic_agents))

    async def _remove_from_config(self, agent_ids: List[str]) -> None:
        """从配置中移除指定的动态 agents（内存+文件）"""
        try:
            # 获取要移除的 agent 名称
            names_to_remove = set()
            for aid in agent_ids:
                spec = self._dynamic_agents.get(aid)
                if spec:
                    names_to_remove.add(spec.name)
            
            if not names_to_remove:
                return
            
            # 尝试通过内存配置更新
            astrbot_config = self._get_astrbot_config()
            
            if astrbot_config is not None and 'subagent_orchestrator' in astrbot_config:
                subagent_config = astrbot_config['subagent_orchestrator']
                if 'agents' in subagent_config:
                    subagent_config['agents'] = [
                        a for a in subagent_config['agents']
                        if a.get('name') not in names_to_remove
                    ]
                    if hasattr(astrbot_config, 'save_config'):
                        astrbot_config.save_config()
                        logger.info("已从内存配置和文件中移除 SubAgents: %s", names_to_remove)
                        return
            
            # 备选：直接操作文件
            with open(CONFIG_PATH, 'r', encoding='utf-8-sig') as f:
                config = json.load(f)
            
            if 'subagent_orchestrator' not in config:
                return
            
            subagent_config = config['subagent_orchestrator']
            if 'agents' not in subagent_config:
                return
            
            subagent_config['agents'] = [
                a for a in subagent_config['agents']
                if a.get('name') not in names_to_remove
            ]
            
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            
            logger.info("已从配置文件中移除 SubAgents: %s", names_to_remove)
        except Exception as e:
            logger.error("移除 SubAgent 配置失败: %s", e, exc_info=True)

    async def _reload_subagents(self) -> None:
        """重新加载 SubAgents 到内存"""
        orchestrator = self._get_subagent_orchestrator()
        if not orchestrator:
            logger.warning("SubAgentOrchestrator 不可用，无法注册动态 SubAgent")
            return

        # 优先从内存配置读取
        subagent_config = {}
        astrbot_config = self._get_astrbot_config()
        
        if astrbot_config is not None:
            subagent_config = astrbot_config.get("subagent_orchestrator", {})
        else:
            # 备选：从文件读取
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8-sig') as f:
                    config = json.load(f)
                subagent_config = config.get("subagent_orchestrator", {})
            except Exception as e:
                logger.error("读取配置文件失败: %s", e)

        try:
            await orchestrator.reload_from_config(subagent_config)
            await self._register_handoffs(orchestrator)
        except Exception as e:
            logger.error("注册 SubAgent 失败: %s", e, exc_info=True)

    async def _register_handoffs(self, orchestrator) -> None:
        """注册 handoff 工具"""
        tool_manager = self._get_tool_manager()
        if not tool_manager:
            return

        handoffs = getattr(orchestrator, "handoffs", [])
        if not handoffs:
            return

        try:
            if hasattr(tool_manager, "register_tools"):
                tool_manager.register_tools(handoffs)
            elif hasattr(tool_manager, "register_tool"):
                for handoff in handoffs:
                    tool_manager.register_tool(handoff)
        except Exception as e:
            logger.warning("注册 Handoff 工具失败: %s", e)
