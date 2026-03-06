"""
任务分析器 - 生成 SubAgent 计划
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, cast

from .agent_templates import AgentSpec, AgentTemplateLibrary

logger = logging.getLogger(__name__)


@dataclass
class AgentTask:
    task_id: str
    description: str
    agent_role: str
    action: str
    input: str
    depends_on: List[str] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskPlan:
    agents: List[AgentSpec]
    tasks: List[AgentTask]
    summary: str = ""


class TaskAnalyzer:
    """使用 LLM 分析任务，生成 SubAgent 与任务计划"""

    def __init__(self, context, config: Optional[Dict[str, Any]] = None):
        self.context = context
        self.config = config or {}
        self.templates = AgentTemplateLibrary(self._load_template_overrides())

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
                import json

                return cast(Dict[str, Any], json.loads(overrides))
            except Exception:
                logger.warning("解析 subagent_template_overrides 失败")
        return {}

    async def analyze(self, request: str, provider_id: str) -> TaskPlan:
        use_llm = self.config.get("use_llm_task_analyzer", True)
        logger.info("开始任务分析: use_llm=%s, provider=%s", use_llm, provider_id)
        if use_llm:
            try:
                plan = await self._analyze_with_llm(request, provider_id)
                logger.info(
                    "LLM 任务分析完成: agents=%d, tasks=%d", len(plan.agents), len(plan.tasks)
                )
                # 后处理：修正错误的 action 分配
                plan = self._postprocess_plan(plan, request)
                return plan
            except Exception as e:
                logger.warning("LLM 任务分析失败，使用回退方案: %s", e, exc_info=True)
        plan = self._fallback_plan(request)
        logger.info("使用回退计划: agents=%d, tasks=%d", len(plan.agents), len(plan.tasks))
        return plan

    async def _analyze_with_llm(self, request: str, provider_id: str) -> TaskPlan:
        prompt = f"""你是一个任务规划器，需要为用户请求设计 SubAgent 和任务步骤。

用户请求：
{request}

请输出 JSON，格式如下：
{{
  "summary": "简短任务摘要",
  "agents": [
    {{
      "role": "code",
      "name": "code_agent",
      "system_prompt": "子代理指令",
      "public_description": "对主 Agent 的描述",
      "tools": ["sandbox", "skill_gen"],
      "provider_id": null
    }}
  ],
  "tasks": [
    {{
      "id": "task_generate",
      "description": "生成完整项目代码",
      "agent_role": "code",
      "action": "llm",
      "input": "请输出完整的、可直接运行的项目代码。每个文件必须使用 markdown 代码块格式，并标注语言和文件名，例如 ```python:main.py\\n代码内容\\n```",
      "depends_on": []
    }},
    {{
      "id": "task_test",
      "description": "给出测试建议",
      "agent_role": "test",
      "action": "llm",
      "input": "请提供测试建议",
      "depends_on": ["task_generate"]
    }}
  ]
}}

约束：
1. action 可选值: llm, create_skill, config_mcp, execute_code, reasoning
2. tasks 至少包含 1 个
3. agents 至少包含 1 个
4. 【极其重要】当用户要求"写代码"、"创建项目"、"开发程序/应用/小程序/网站"时：
   - 必须使用 action="llm"（而不是 execute_code）
   - input 中必须明确要求"输出完整代码，使用 markdown 代码块格式并标注文件名"
   - execute_code 仅用于执行已有的简短 shell 命令（如 pip install、npm install、ls 等），绝不能用于"生成代码"
   - 不要把自然语言描述作为 execute_code 的 input
5. 代码生成任务的 input 必须包含具体的技术要求，不能只是笼统的描述
6. 每个代码生成任务的 input 末尾必须包含："所有代码必须使用 ```语言:文件名 格式输出"
只输出 JSON。"""

        response = await self.context.llm_generate(
            chat_provider_id=provider_id,
            prompt=prompt,
            system_prompt="你是一个擅长多代理编排的任务分析专家，只输出 JSON。",
        )

        text = response.completion_text
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        data = json.loads(text.strip())
        return self._build_plan_from_data(data)

    def _postprocess_plan(self, plan: TaskPlan, request: str) -> TaskPlan:
        """后处理任务计划：修正 LLM 可能错误分配的 action"""
        # 检测是否是代码生成类请求
        code_gen_keywords = [
            "写",
            "创建",
            "开发",
            "实现",
            "生成",
            "做一个",
            "帮我",
            "程序",
            "项目",
            "应用",
            "小程序",
            "网站",
            "网页",
            "API",
            "app",
            "write",
            "create",
            "build",
            "develop",
            "implement",
        ]
        is_code_gen_request = any(kw in request.lower() for kw in code_gen_keywords)

        if not is_code_gen_request:
            return plan

        code_format_suffix = (
            "\n\n【输出格式要求】所有代码文件必须使用标准 markdown 代码块格式输出，"
            "并在代码块开头标注语言和文件名，例如：\n"
            "```python:main.py\nprint('hello')\n```\n"
            "```html:index.html\n<html>...</html>\n```\n"
            "每个文件必须是完整的、可直接运行的代码，不要省略任何部分。"
        )

        for task in plan.tasks:
            # 修正：如果 execute_code 的 input 看起来是自然语言描述而非 shell 命令，
            # 则将其降级为 llm action
            if task.action == "execute_code" and self._is_natural_language(task.input):
                logger.warning(
                    "后处理修正: 任务 %s 的 action 从 execute_code 改为 llm（input 是自然语言）",
                    task.task_id,
                )
                task.action = "llm"
                # 补充代码格式要求
                if "代码块" not in task.input and "```" not in task.input:
                    task.input += code_format_suffix

            # 对所有 llm action 的代码生成任务，确保 input 中包含格式要求
            if task.action == "llm" and task.agent_role in ("code", "custom"):
                if "代码块" not in task.input and "```" not in task.input:
                    task.input += code_format_suffix

        return plan

    @staticmethod
    def _is_natural_language(text: str) -> bool:
        """判断文本是否是自然语言描述（而非 shell 命令）"""
        if not text or not text.strip():
            return False

        text = text.strip()

        # 典型的 shell 命令特征
        shell_patterns = [
            r"^(pip|npm|yarn|apt|brew|cargo|go|git|docker|kubectl|curl|wget|cat|ls|cd|mkdir|cp|mv|rm|echo|find|grep|sed|awk|tar|zip|unzip)\s",
            r"^(python|python3|node|java|gcc|g\+\+|make|cmake)\s",
            r"^(sudo|nohup|chmod|chown|export|source|\.\/)",
            r"^\w+=",  # 环境变量赋值
            r"^\|",  # 管道
            r"^#!",  # shebang
        ]

        for pattern in shell_patterns:
            if re.match(pattern, text):
                return False

        # 自然语言特征：包含中文字符、长度较长、包含标点
        has_chinese = bool(re.search(r"[\u4e00-\u9fff]", text))
        has_punctuation = bool(re.search(r"[，。！？；：、]", text))
        word_count = len(text.split())

        # 如果包含中文或标点，很可能是自然语言
        if has_chinese or has_punctuation:
            return True

        # 如果英文单词数超过 10 且不含典型命令字符，可能是自然语言
        if word_count > 10 and not any(c in text for c in ["|", ">", "<", "&&", "||", ";"]):
            return True

        return False

    def _build_plan_from_data(self, data: Dict[str, Any]) -> TaskPlan:
        agents_data = data.get("agents", [])
        tasks_data = data.get("tasks", [])
        agents: List[AgentSpec] = []

        for item in agents_data:
            role = item.get("role", "custom")
            agents.append(
                self.templates.build_spec(
                    role=role,
                    name=item.get("name"),
                    instructions=item.get("system_prompt"),
                    tools=item.get("tools"),
                    public_description=item.get("public_description"),
                    provider_id=item.get("provider_id"),
                )
            )

        tasks: List[AgentTask] = []
        for item in tasks_data:
            tasks.append(
                AgentTask(
                    task_id=item.get("id", f"task_{len(tasks) + 1}"),
                    description=item.get("description", ""),
                    agent_role=item.get("agent_role", "code"),
                    action=item.get("action", "llm"),
                    input=item.get("input", ""),
                    depends_on=item.get("depends_on", []),
                    params=item.get("params", {}),
                )
            )

        summary = data.get("summary", "")
        return TaskPlan(agents=agents, tasks=tasks, summary=summary)

    def _fallback_plan(self, request: str) -> TaskPlan:
        request_lower = request.lower()
        agents: List[AgentSpec] = []
        tasks: List[AgentTask] = []

        code_format_hint = (
            "\n\n【输出格式要求】所有代码文件必须使用标准 markdown 代码块格式输出，"
            "并在代码块开头标注语言和文件名，例如：\n"
            "```python:main.py\nprint('hello')\n```\n"
            "每个文件必须是完整的、可直接运行的代码，不要省略任何部分。"
        )

        def add_agent(role: str) -> None:
            agents.append(self.templates.build_spec(role=role))

        def add_task(
            task_id: str, description: str, role: str, action: str, input_text: str, deps=None
        ):
            tasks.append(
                AgentTask(
                    task_id=task_id,
                    description=description,
                    agent_role=role,
                    action=action,
                    input=input_text,
                    depends_on=deps or [],
                )
            )

        if "skill" in request_lower or "技能" in request:
            add_agent("code")
            add_task("task_skill", "创建 Skill", "code", "create_skill", request)
        elif "mcp" in request_lower or "联网" in request:
            add_agent("research")
            add_task("task_mcp", "配置 MCP 服务", "research", "config_mcp", request)
        else:
            add_agent("code")
            add_agent("test")
            add_task("task_plan", "生成完整项目代码", "code", "llm", request + code_format_hint)
            add_task("task_test", "提供测试建议", "test", "llm", "给出测试建议", deps=["task_plan"])

        return TaskPlan(agents=agents, tasks=tasks, summary="自动回退计划")
