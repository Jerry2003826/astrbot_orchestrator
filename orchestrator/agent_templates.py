"""
SubAgent 模板库与配置定义
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import uuid


@dataclass
class AgentSpec:
    agent_id: str
    name: str
    role: str
    instructions: str
    tools: List[str] = field(default_factory=list)
    public_description: str = ""
    provider_id: Optional[str] = None
    persona_id: Optional[str] = None
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_config(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "persona_id": self.persona_id,
            "system_prompt": self.instructions,
            "public_description": self.public_description,
            "provider_id": self.provider_id,
            "tools": self.tools,
        }


@dataclass
class AgentTemplate:
    role: str
    name: str
    system_prompt: str
    public_description: str
    tools: List[str] = field(default_factory=list)

    def to_spec(self, name_suffix: Optional[str] = None) -> AgentSpec:
        agent_id = str(uuid.uuid4())
        name = self.name if not name_suffix else f"{self.name}_{name_suffix}"
        return AgentSpec(
            agent_id=agent_id,
            name=name,
            role=self.role,
            instructions=self.system_prompt,
            tools=list(self.tools),
            public_description=self.public_description,
        )


class AgentTemplateLibrary:
    """内置 SubAgent 模板库"""

    def __init__(self, overrides: Optional[Dict[str, Any]] = None):
        self._templates: Dict[str, AgentTemplate] = {
            "code": AgentTemplate(
                role="code",
                name="code_agent",
                system_prompt=(
                    "你是资深代码工程师，负责生成完整、可运行的代码实现。\n"
                    "【核心规则】你输出的每一个代码文件都必须使用标准 markdown 代码块格式，"
                    "并在代码块开头标注语言和文件名，格式为 ```语言:文件名\n"
                    "例如：```python:main.py\n```html:index.html\n```css:styles.css\n"
                    "每个文件必须是完整的、可直接运行的代码，绝对不要省略任何部分。\n"
                    "不要用 '...' 或注释代替实际代码。"
                ),
                public_description="生成或修改代码实现的子代理",
                tools=["sandbox", "skill_gen"],
            ),
            "test": AgentTemplate(
                role="test",
                name="test_agent",
                system_prompt=(
                    "你是测试与质量专家，负责检查实现的正确性并给出测试建议。"
                    "如果需要输出测试代码，请使用 ```语言:文件名 格式的 markdown 代码块。"
                ),
                public_description="验证实现并输出测试建议的子代理",
                tools=["sandbox"],
            ),
            "research": AgentTemplate(
                role="research",
                name="research_agent",
                system_prompt=(
                    "你是信息分析专家，擅长梳理需求、总结方案和关键风险。"
                ),
                public_description="分析需求和风险的子代理",
            ),
            "deploy": AgentTemplate(
                role="deploy",
                name="deploy_agent",
                system_prompt=(
                    "你是部署与运维专家，负责给出部署流程、配置和运行建议。"
                    "如果需要输出配置文件或脚本，请使用 ```语言:文件名 格式的 markdown 代码块。"
                ),
                public_description="部署配置和运行建议的子代理",
            ),
            "debug": AgentTemplate(
                role="debug",
                name="debug_agent",
                system_prompt=(
                    "你是调试专家，负责定位问题原因并给出修复建议。"
                ),
                public_description="排查问题并提出修复方案的子代理",
                tools=["sandbox"],
            ),
        }

        if overrides:
            self._apply_overrides(overrides)

    def get(self, role: str) -> Optional[AgentTemplate]:
        return self._templates.get(role)

    def list_roles(self) -> List[str]:
        return list(self._templates.keys())

    def _apply_overrides(self, overrides: Dict[str, Any]) -> None:
        for role, cfg in overrides.items():
            if not isinstance(cfg, dict):
                continue
            template = self._templates.get(role)
            if template:
                template.name = cfg.get("name", template.name)
                template.system_prompt = cfg.get("system_prompt", template.system_prompt)
                template.public_description = cfg.get(
                    "public_description", template.public_description
                )
                tools = cfg.get("tools")
                if isinstance(tools, list):
                    template.tools = tools
            else:
                name = cfg.get("name", f"{role}_agent")
                system_prompt = cfg.get("system_prompt", "你是一个通用助手。")
                public_description = cfg.get("public_description", "动态生成的子代理")
                tools = cfg.get("tools", [])
                if not isinstance(tools, list):
                    tools = []
                self._templates[role] = AgentTemplate(
                    role=role,
                    name=name,
                    system_prompt=system_prompt,
                    public_description=public_description,
                    tools=tools,
                )

    def export_templates(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        for role, template in self._templates.items():
            data[role] = {
                "name": template.name,
                "system_prompt": template.system_prompt,
                "public_description": template.public_description,
                "tools": template.tools,
            }
        return data

    def build_spec(
        self,
        role: str,
        name: Optional[str] = None,
        instructions: Optional[str] = None,
        tools: Optional[List[str]] = None,
        public_description: Optional[str] = None,
        provider_id: Optional[str] = None,
        persona_id: Optional[str] = None,
    ) -> AgentSpec:
        template = self.get(role)
        if template:
            spec = template.to_spec()
            if name:
                spec.name = name
            if instructions:
                spec.instructions = instructions
            if tools is not None:
                spec.tools = tools
            if public_description:
                spec.public_description = public_description
            spec.provider_id = provider_id
            spec.persona_id = persona_id
            return spec

        return AgentSpec(
            agent_id=str(uuid.uuid4()),
            name=name or f"{role}_agent",
            role=role,
            instructions=instructions or "你是一个通用助手。",
            tools=tools or [],
            public_description=public_description or "动态生成的子代理",
            provider_id=provider_id,
            persona_id=persona_id,
        )
