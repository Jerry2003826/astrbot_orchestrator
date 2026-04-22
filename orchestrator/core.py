"""
动态智能体编排器核心 - 增强版

支持：
- 多步骤任务规划与执行
- 真正的代码生成（不只是描述文档）
- 网页项目创建与部署
- 自主迭代改进
"""

from dataclasses import dataclass, field
from enum import Enum
import logging
import os
import re
from typing import Any, Dict, List, Optional, cast

from ..runtime.graph_state import OrchestratorGraphState
from ..runtime.pipeline import (
    CallableOutputParser,
    JsonOutputParser,
    PromptModelParserPipeline,
    PromptTemplate,
    TextOutputParser,
)
from ..runtime.request_context import RequestContext
from ..shared import UnsafePathError, ensure_within_base, quote_shell_path, slugify_identifier

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskType(Enum):
    """任务类型"""

    REASONING = "reasoning"
    SEARCH_PLUGIN = "search_plugin"
    INSTALL_PLUGIN = "install_plugin"
    CREATE_SKILL = "create_skill"
    EDIT_SKILL = "edit_skill"
    CONFIG_MCP = "config_mcp"
    EXECUTE_CODE = "execute_code"
    DEBUG = "debug"
    GENERAL = "general"
    # 新增：代码项目任务
    CODE_PROJECT = "code_project"
    WEB_APP = "web_app"
    WRITE_FILE = "write_file"
    MULTI_STEP = "multi_step"


@dataclass
class Task:
    """任务定义"""

    id: str
    description: str
    type: TaskType = TaskType.GENERAL
    priority: int = 1
    dependencies: List[str] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[str] = None


@dataclass
class ExecutionStep:
    """执行步骤"""

    step_num: int
    action: str
    description: str
    code: Optional[str] = None
    file_path: Optional[str] = None
    result: Optional[str] = None
    status: str = "pending"


class DynamicOrchestrator:
    """
    动态智能体编排器 - 增强版

    核心能力：
    - 🧠 智能任务分析和多步骤规划
    - 💻 真正的代码生成（完整可运行代码）
    - 🌐 网页应用创建与部署
    - 🔄 自主迭代和错误修复
    """

    def __init__(
        self,
        context,
        skill_loader=None,
        mcp_bridge=None,
        workflow_engine=None,
        plugin_tool=None,
        skill_tool=None,
        mcp_tool=None,
        debugger=None,
        executor=None,
        meta_orchestrator=None,
        config: Optional[Dict] = None,
    ):
        self.context = context
        self.skill_loader = skill_loader
        self.mcp_bridge = mcp_bridge
        self.workflow_engine = workflow_engine

        self.plugin_tool = plugin_tool
        self.skill_tool = skill_tool
        self.mcp_tool = mcp_tool
        self.debugger = debugger
        self.executor = executor
        self.meta_orchestrator = meta_orchestrator

        self.config = config or {}
        self.max_iterations = self.config.get("max_iterations", 10)
        self.subagent_settings = self._get_subagent_settings()
        self.intent_pipeline = self._build_intent_pipeline()
        self.plan_pipeline = self._build_plan_pipeline()
        self.reasoning_pipeline = self._build_reasoning_pipeline()

        # 项目目录 - 使用 context 传递的路径，或从 ArtifactService 获取
        self.projects_dir = self._get_projects_dir()

    def _get_projects_dir(self) -> str:
        """获取项目存储目录。"""
        import os
        from pathlib import Path

        # 优先从 meta_orchestrator 的 artifact_service 获取
        if self.meta_orchestrator and hasattr(self.meta_orchestrator, "artifact_service"):
            artifact_service = self.meta_orchestrator.artifact_service
            if artifact_service and hasattr(artifact_service, "persist_dir"):
                return artifact_service.persist_dir

        # 备选：从当前文件位置推断插件目录
        current_file = Path(__file__).resolve()
        plugin_root = current_file.parent.parent  # astrbot_orchestrator_v5 目录
        projects_dir = os.path.join(str(plugin_root), "projects")
        os.makedirs(projects_dir, exist_ok=True)

        return projects_dir

    async def _run_model_text(
        self,
        provider_id: str,
        prompt: str,
        system_prompt: str | None = None,
    ) -> str:
        """统一执行底层 LLM 调用并返回文本。"""

        response = await self.context.llm_generate(
            chat_provider_id=provider_id,
            prompt=prompt,
            system_prompt=system_prompt or "",
        )
        return str(response.completion_text)

    def _build_intent_pipeline(self) -> PromptModelParserPipeline[Dict[str, Any]]:
        """构建意图分析链。"""

        prompt_template = PromptTemplate(
            """分析用户请求，判断需要执行什么操作。

用户请求：$request

操作类型：
1. search_plugin - 搜索插件
2. install_plugin - 安装插件
3. create_skill - 创建 Skill（简单描述）
4. code_project - 创建代码项目（需要写真正的代码）
5. web_app - 创建网页应用（HTML/CSS/JS/后端）
6. execute_code - 执行代码
7. debug - 调试问题
8. reasoning - 普通问答

判断规则：
- 如果用户想要"程序"、"小程序"、"应用"、"网页"、"API"、"服务"等，选择 code_project 或 web_app
- 如果涉及多个文件、数据库、前后端，选择 web_app 并设置 needs_planning=true
- 如果只是简单的单文件脚本，选择 code_project

输出 JSON：
{
    "intent": "操作类型",
    "needs_planning": true,
    "complexity": "simple/medium/complex",
    "params": {
        "project_name": "项目名称",
        "tech_stack": ["python", "flask", "html"],
        "features": ["功能1", "功能2"],
        "other_params": "..."
    },
    "needs_admin": false,
    "description": "简短描述"
}

只输出 JSON。"""
        )
        return PromptModelParserPipeline(
            prompt_template=prompt_template,
            model_runner=self._run_model_text,
            output_parser=CallableOutputParser(self._parse_intent_payload),
            system_prompt="你是一个项目需求分析专家。只输出 JSON。",
        )

    def _build_plan_pipeline(self) -> PromptModelParserPipeline[List[ExecutionStep]]:
        """构建执行计划生成链。"""

        prompt_template = PromptTemplate(
            """你是一个高级程序员，需要规划一个项目的实现步骤。

项目需求：$request
项目名称：$project_name
技术栈：$tech_stack
功能点：$features

请输出详细的执行计划，每个步骤都要包含完整的代码。

输出 JSON 数组：
[
    {
        "step": 1,
        "action": "create_file",
        "description": "创建主程序文件",
        "file_path": "$project_name/main.py",
        "code": "完整的 Python 代码..."
    },
    {
        "step": 2,
        "action": "create_file",
        "description": "创建配置文件",
        "file_path": "$project_name/config.py",
        "code": "完整代码..."
    },
    {
        "step": 3,
        "action": "execute",
        "description": "安装依赖",
        "code": "pip install flask requests"
    },
    {
        "step": 4,
        "action": "execute",
        "description": "启动服务",
        "code": "cd $project_name && python main.py"
    }
]

要求：
1. 代码必须完整可运行，不要用省略号或注释代替代码
2. 包含所有必要的 import
3. 包含错误处理
4. 如果是 Web 应用，要包含启动服务的步骤
5. 文件路径使用相对路径

只输出 JSON 数组。"""
        )
        return PromptModelParserPipeline(
            prompt_template=prompt_template,
            model_runner=self._run_model_text,
            output_parser=CallableOutputParser(self._parse_execution_plan),
            system_prompt="你是一个资深全栈工程师。输出完整可运行的代码，不要省略任何部分。只输出 JSON。",
        )

    def _build_reasoning_pipeline(self) -> PromptModelParserPipeline[str]:
        """构建普通问答链。"""

        prompt_template = PromptTemplate("$request")
        return PromptModelParserPipeline(
            prompt_template=prompt_template,
            model_runner=self._run_model_text,
            output_parser=TextOutputParser(),
            system_prompt="""你是一个全能的智能助手，拥有以下能力：
- 搜索和安装 AstrBot 插件
- 创建代码项目和网页应用
- 执行代码（本地/沙盒）
- 诊断和调试问题

如果用户想要创建程序/应用，引导他们使用 /agent 命令。""",
        )

    def _parse_intent_payload(self, text: str) -> Dict[str, Any]:
        """解析意图分析输出。"""

        payload = JsonOutputParser[Dict[str, Any]]().parse(text)
        if not isinstance(payload, dict):
            raise ValueError("意图分析结果必须是 JSON 对象")
        return payload

    def _parse_execution_plan(self, text: str) -> List[ExecutionStep]:
        """解析执行计划输出。"""

        plan_data = JsonOutputParser[List[Dict[str, Any]] | List[Any]]().parse(text)
        if not isinstance(plan_data, list):
            raise ValueError("执行计划必须是 JSON 数组")

        steps: List[ExecutionStep] = []
        for item in plan_data:
            if not isinstance(item, dict):
                raise ValueError("执行计划中的每个步骤都必须是 JSON 对象")
            steps.append(
                ExecutionStep(
                    step_num=item.get("step", len(steps) + 1),
                    action=item.get("action", "create_file"),
                    description=item.get("description", ""),
                    code=item.get("code"),
                    file_path=item.get("file_path"),
                )
            )
        return steps

    async def _intent_node(self, state: OrchestratorGraphState) -> None:
        """图节点：分析用户意图。"""

        self._log_state_step(state, "🧠 正在分析用户意图...")
        state.intent = await self._analyze_intent_enhanced(
            state.request_text,
            state.provider_id,
        )
        self._log_state_step(
            state,
            f"💡 识别意图: {state.intent.get('intent')} - {state.intent.get('description', '')}",
        )

    async def _subagent_node(self, state: OrchestratorGraphState) -> bool:
        """图节点：如有需要，委托给 SubAgent 编排器。"""

        logger.info("SubAgent 设置: %s", self.subagent_settings)
        should_use = self._should_use_subagents(state.intent, state.request_text)
        logger.info(
            "_should_use_subagents 返回: %s (intent=%s)", should_use, state.intent.get("intent")
        )

        if not should_use:
            return False
        if not self.meta_orchestrator or not state.event:
            self._log_state_step(state, "⚠️ 未找到 SubAgent 编排器，回退到单 Agent 模式")
            return False

        self._log_state_step(state, "🤖 启用动态 SubAgent 编排...")
        state.result = await self.meta_orchestrator.process(
            user_request=state.request_text,
            provider_id=state.provider_id,
            event=state.event,
            is_admin=state.is_admin,
        )
        state.used_subagents = True
        self._log_state_step(state, "✅ SubAgent 编排完成")
        return True

    async def _plan_node(self, state: OrchestratorGraphState) -> None:
        """图节点：生成执行计划。"""

        self._log_state_step(state, "📋 任务复杂，生成执行计划...")
        state.plan = await self._generate_execution_plan(
            state.request_text,
            state.intent,
            state.provider_id,
        )
        self._log_state_step(state, f"📋 计划包含 {len(state.plan)} 个步骤")

    async def _plan_execution_node(self, state: OrchestratorGraphState) -> None:
        """图节点：执行计划。"""

        state.result = await self._execute_plan(
            plan=state.plan,
            user_request=state.request_text,
            provider_id=state.provider_id,
            is_admin=state.is_admin,
            event=state.event,
            log_step=lambda step: self._log_state_step(state, step),
        )

    async def _action_node(self, state: OrchestratorGraphState) -> None:
        """图节点：执行直接动作。"""

        self._log_state_step(state, f"⚙️ 开始执行: {state.intent.get('intent')}")
        state.result = await self._execute_by_intent(
            intent=state.intent,
            user_request=state.request_text,
            provider_id=state.provider_id,
            is_admin=state.is_admin,
            event=state.event,
        )

    def _finalize_state_result(self, state: OrchestratorGraphState) -> Dict[str, Any]:
        """将状态对象转换为最终响应。"""

        result = state.result or {"status": "error", "answer": "❌ 未生成结果"}
        show_process = self.config.get("show_thinking_process", True)
        if show_process and state.thinking_steps:
            process_text = "\n".join([f"  {step}" for step in state.thinking_steps])
            result["answer"] = (
                f"🤖 **思考过程:**\n{process_text}\n\n---\n\n{result.get('answer', '')}"
            )
            result["thinking_steps"] = list(state.thinking_steps)
        return result

    async def _build_error_result(
        self,
        state: OrchestratorGraphState,
        error: Exception,
    ) -> Dict[str, Any]:
        """构建统一错误响应。"""

        logger.error("[自主Agent] 执行失败: %s", error, exc_info=True)
        state.error = str(error)

        if self.debugger:
            try:
                import traceback

                analysis = await self.debugger.analyze_error(
                    error=error,
                    traceback_info=traceback.format_exc(),
                    context={
                        "request": state.request_text,
                        "request_id": state.request_id,
                    },
                )
                return {
                    "status": "error",
                    "answer": f"❌ 执行出错: {str(error)}\n\n🔍 **自动诊断:**\n{analysis}",
                    "error": str(error),
                }
            except Exception:
                pass

        return {
            "status": "error",
            "answer": f"❌ 执行出错: {str(error)}",
            "error": str(error),
        }

    def _log_state_step(self, state: OrchestratorGraphState, step: str) -> None:
        """记录状态轨迹。"""

        state.add_step(step)
        logger.info("[自主Agent][%s] %s", state.request_id, step)

    async def process_request(self, request_context: RequestContext) -> Dict[str, Any]:
        """使用新的请求上下文原语处理用户请求。"""

        configured_provider = self.config.get("llm_provider")
        if configured_provider:
            request_context = request_context.with_provider(str(configured_provider))
        state = OrchestratorGraphState(request_context=request_context)
        self._log_state_step(state, f"📥 收到请求: {state.request_text[:50]}...")

        try:
            await self._intent_node(state)
            if await self._subagent_node(state):
                return self._finalize_state_result(state)

            if state.intent.get("needs_planning", False):
                await self._plan_node(state)
                await self._plan_execution_node(state)
            else:
                await self._action_node(state)

            self._log_state_step(state, "✅ 执行完成")
            return self._finalize_state_result(state)

        except Exception as error:
            return await self._build_error_result(state, error)

    async def process_autonomous(
        self, user_request: str, provider_id: str, context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """全自主处理用户请求"""
        request_context = RequestContext.from_legacy(
            user_request=user_request,
            provider_id=provider_id,
            context=context,
        )
        return await self.process_request(request_context)

    def _get_subagent_settings(self) -> Dict[str, Any]:
        settings = self.config.get("subagent_settings")
        if isinstance(settings, dict):
            return settings

        return {
            "enable_dynamic_agents": self.config.get("enable_dynamic_agents", False),
            "max_concurrent_agents": self.config.get("max_concurrent_agents", 5),
            "agent_timeout": self.config.get("agent_timeout", 300),
            "auto_cleanup_agents": self.config.get("auto_cleanup_agents", True),
            "use_llm_task_analyzer": self.config.get("use_llm_task_analyzer", True),
            "force_subagents_for_complex_tasks": self.config.get(
                "force_subagents_for_complex_tasks", True
            ),
        }

    def _should_use_subagents(self, intent: Dict[str, Any], request: str) -> bool:
        if not self.subagent_settings.get("enable_dynamic_agents", False):
            return False
        complexity = intent.get("complexity", "")
        if intent.get("needs_planning", False):
            return True
        if complexity in ["medium", "complex"]:
            return True
        if self.subagent_settings.get("force_subagents_for_complex_tasks", True):
            if intent.get("intent") in ["web_app", "code_project", "multi_step"]:
                return True
        keywords = ["多步", "多个", "协作", "subagent", "子代理", "并行"]
        return any(k in request for k in keywords)

    async def _analyze_intent_enhanced(self, request: str, provider_id: str) -> Dict[str, Any]:
        """增强版意图分析 - 识别复杂项目需求"""
        try:
            return cast(
                Dict[str, Any],
                await self.intent_pipeline.ainvoke(
                    provider_id=provider_id,
                    variables={"request": request},
                ),
            )
        except Exception as e:
            logger.warning(f"意图分析失败: {e}")
            return {
                "intent": "reasoning",
                "needs_planning": False,
                "params": {},
                "needs_admin": False,
                "description": request,
            }

    async def _generate_execution_plan(
        self, request: str, intent: Dict, provider_id: str
    ) -> List[ExecutionStep]:
        """生成多步骤执行计划"""

        params = intent.get("params", {})
        project_name = params.get("project_name", "my_project")
        tech_stack = params.get("tech_stack", ["python"])
        features = params.get("features", [])

        try:
            return cast(
                List[ExecutionStep],
                await self.plan_pipeline.ainvoke(
                    provider_id=provider_id,
                    variables={
                        "request": request,
                        "project_name": project_name,
                        "tech_stack": ", ".join(tech_stack),
                        "features": ", ".join(features) if features else "根据需求自动识别",
                    },
                ),
            )
        except Exception as e:
            logger.error(f"生成执行计划失败: {e}")
            return [
                ExecutionStep(step_num=1, action="error", description=f"生成计划失败: {str(e)}")
            ]

    async def _execute_plan(
        self,
        plan: List[ExecutionStep],
        user_request: str,
        provider_id: str,
        is_admin: bool,
        event,
        log_step,
    ) -> Dict[str, Any]:
        """执行多步骤计划"""

        results = []
        project_path = None

        for step in plan:
            log_step(f"📌 步骤 {step.step_num}: {step.description}")

            try:
                if step.action == "create_file":
                    result = await self._execute_create_file(step, event, is_admin=is_admin)
                    if project_path is None and step.file_path:
                        project_path = step.file_path.split("/")[0]
                    step.status = "completed" if result.startswith("✅") else "skipped"

                elif step.action == "execute":
                    if not is_admin:
                        result = "⚠️ 跳过（需要管理员权限）"
                        step.status = "skipped"
                    elif not step.code:
                        result = "❌ 缺少执行命令"
                        step.status = "failed"
                    else:
                        result = await self._execute_command(step.code, event)
                        step.status = "completed" if not result.startswith("❌") else "failed"

                elif step.action == "error":
                    result = f"❌ {step.description}"
                    step.status = "failed"

                else:
                    result = f"未知操作: {step.action}"
                    step.status = "failed"

                step.result = result
                status_icon = (
                    "✅"
                    if step.status == "completed"
                    else "⚠️"
                    if step.status == "skipped"
                    else "❌"
                )
                results.append(f"{status_icon} 步骤 {step.step_num}: {step.description}")

            except Exception as e:
                step.status = "failed"
                step.result = str(e)
                results.append(f"❌ 步骤 {step.step_num} 失败: {str(e)}")

                # 尝试自动修复
                if self.debugger and is_admin:
                    log_step("🔧 尝试自动修复...")
                    try:
                        fix = await self._auto_fix_error(e, step, provider_id)
                        if fix:
                            results.append(f"🔧 已修复: {fix}")
                    except Exception:
                        pass

        # 生成总结
        summary = await self._generate_summary(plan, project_path, provider_id)

        output = "\n".join(results)
        output += f"\n\n---\n\n{summary}"

        return {"status": "success", "answer": output, "project_path": project_path}

    async def _execute_create_file(self, step: ExecutionStep, event, is_admin: bool) -> str:
        """执行文件创建"""
        if not is_admin:
            return "⚠️ 跳过（需要管理员权限）"
        if not step.file_path or not step.code:
            return "❌ 缺少文件路径或代码"

        try:
            full_path = ensure_within_base(self.projects_dir, step.file_path)
            os.makedirs(full_path.parent, exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as file_obj:
                file_obj.write(step.code)
            return f"✅ 已创建 `{step.file_path}`\n📂 绝对路径: `{full_path}`"
        except UnsafePathError as e:
            return f"❌ 创建文件失败: {str(e)}"
        except Exception as e:
            return f"❌ 创建文件失败: {str(e)}"

    async def _execute_command(self, code: str, event) -> str:
        """执行命令"""
        if self.executor:
            return cast(str, await self.executor.execute(code, event))
        return "❌ 执行器不可用"

    async def _auto_fix_error(
        self, error: Exception, step: ExecutionStep, provider_id: str
    ) -> Optional[str]:
        """尝试自动修复错误"""
        if not self.debugger:
            return None

        analysis = await self.debugger.analyze_error(
            error=error, traceback_info="", context={"step": step.description, "code": step.code}
        )

        return cast(Optional[str], analysis)

    async def _generate_summary(
        self, plan: List[ExecutionStep], project_path: Optional[str], provider_id: str
    ) -> str:
        """生成项目总结"""

        completed = sum(1 for s in plan if s.status == "completed")
        total = len(plan)

        files = [s.file_path for s in plan if s.action == "create_file" and s.file_path]

        # project_path 来自 LLM/用户输入，可能包含空格、中文、反引号等 shell 元字符。
        # 作为目录名先做 slugify，再用 shlex.quote 形成命令示例，以免用户直接
        # 复粘时注入危险命令。
        raw_project = project_path or "my_project"
        safe_project = slugify_identifier(raw_project) or "my_project"
        project_abs_path = f"{self.projects_dir}/{safe_project}"
        quoted_project_abs = quote_shell_path(project_abs_path)

        summary = f"""## 📊 项目创建完成

**执行进度:** {completed}/{total} 步骤完成

**📂 项目绝对路径:** `{project_abs_path}`

**创建的文件:**
"""
        for f in files:
            file_abs = os.path.join(self.projects_dir, f)
            summary += f"- `{f}` → 绝对路径: `{file_abs}`\n"

        summary += f"""
**💾 下载说明:**
文件已保存到 AstrBot 数据目录，可通过以下方式获取：
1. 查看文件: `/exec cat {quoted_project_abs}/<文件名>`
2. 打包下载: `/exec cd {quoted_project_abs} && tar czf /tmp/project.tar.gz .`
3. 运行程序: `/exec python {quoted_project_abs}/main.py`
4. 如果是 Web 应用，访问对应端口

💡 遇到问题? 发送 `/debug analyze 错误描述` 让我帮你分析
"""

        return summary

    async def _execute_by_intent(
        self, intent: Dict, user_request: str, provider_id: str, is_admin: bool, event
    ) -> Dict[str, Any]:
        """根据意图执行操作"""

        intent_type = intent.get("intent", "reasoning")
        params = intent.get("params", {})
        needs_admin = intent.get("needs_admin", False)

        if needs_admin and not is_admin:
            return {"status": "error", "answer": "❌ 此操作需要管理员权限"}

        if intent_type == "search_plugin":
            return await self._handle_search_plugin(params, user_request, provider_id)

        elif intent_type == "install_plugin":
            return await self._handle_install_plugin(params, user_request, provider_id, is_admin)

        elif intent_type == "create_skill":
            return await self._handle_create_skill(params, user_request, provider_id, is_admin)

        elif intent_type in ["code_project", "web_app"]:
            # 对于代码项目，生成计划并执行
            plan = await self._generate_execution_plan(user_request, intent, provider_id)
            return await self._execute_plan(
                plan=plan,
                user_request=user_request,
                provider_id=provider_id,
                is_admin=is_admin,
                event=event,
                log_step=lambda x: logger.info(f"[执行] {x}"),
            )

        elif intent_type == "execute_code":
            return await self._handle_execute_code(params, user_request, event, is_admin)

        elif intent_type == "debug":
            return await self._handle_debug(params, user_request, provider_id)

        else:
            return await self._handle_reasoning(user_request, provider_id)

    async def _handle_search_plugin(
        self, params: Dict, request: str, provider_id: str
    ) -> Dict[str, Any]:
        """处理插件搜索"""
        keyword = params.get("keyword", "")
        if not keyword:
            keyword = self._extract_keyword(request, ["插件", "plugin", "搜索"])

        if self.plugin_tool:
            result = await self.plugin_tool.search_plugins(keyword)
            return {"status": "success", "answer": result}

        return {"status": "error", "answer": "❌ 插件管理工具不可用"}

    async def _handle_install_plugin(
        self, params: Dict, request: str, provider_id: str, is_admin: bool
    ) -> Dict[str, Any]:
        """处理插件安装"""
        if not is_admin:
            return {"status": "error", "answer": "❌ 只有管理员可以安装插件"}

        repo_url = params.get("repo_url", "")
        if not repo_url:
            urls = re.findall(r"https?://[^\s]+", request)
            if urls:
                repo_url = urls[0]

        if not repo_url:
            return {"status": "error", "answer": "❌ 请提供插件仓库地址"}

        if self.plugin_tool:
            result = await self.plugin_tool.install_plugin(repo_url)
            return {"status": "success", "answer": result}

        return {"status": "error", "answer": "❌ 插件管理工具不可用"}

    async def _handle_create_skill(
        self, params: Dict, request: str, provider_id: str, is_admin: bool
    ) -> Dict[str, Any]:
        """处理 Skill 创建"""
        if not is_admin:
            return {"status": "error", "answer": "❌ 只有管理员可以创建 Skill"}
        skill_name = params.get("name", "") or self._extract_skill_name(request) or "my_skill"
        description = params.get("description", request)

        if self.skill_tool:
            try:
                content = await self.skill_tool.generate_skill_from_description(
                    name=skill_name, user_description=description, provider_id=provider_id
                )
                result = await self.skill_tool.create_skill(
                    name=skill_name, description=description[:100], content=content
                )
                return {"status": "success", "answer": result}
            except Exception as e:
                return {"status": "error", "answer": f"❌ 创建 Skill 失败: {str(e)}"}

        return {"status": "error", "answer": "❌ Skill 管理工具不可用"}

    async def _handle_execute_code(
        self, params: Dict, request: str, event, is_admin: bool
    ) -> Dict[str, Any]:
        """处理代码执行"""
        if not is_admin:
            return {"status": "error", "answer": "❌ 只有管理员可以执行代码"}

        code = params.get("code", "") or self._extract_code(request)
        if not code:
            return {"status": "error", "answer": "❌ 请提供要执行的代码"}

        code_type = params.get("type", "shell")

        if self.executor:
            result = await self.executor.auto_execute(code=code, event=event, code_type=code_type)
            return {"status": "success", "answer": result}

        return {"status": "error", "answer": "❌ 执行器不可用"}

    async def _handle_debug(self, params: Dict, request: str, provider_id: str) -> Dict[str, Any]:
        """处理调试请求"""
        if self.debugger:
            result = await self.debugger.analyze_problem(request, provider_id)
            return {"status": "success", "answer": f"🔍 **问题分析:**\n\n{result}"}

        return {"status": "error", "answer": "❌ Debug 工具不可用"}

    async def _handle_reasoning(self, request: str, provider_id: str) -> Dict[str, Any]:
        """处理普通推理请求"""

        answer = await self.reasoning_pipeline.ainvoke(
            provider_id=provider_id,
            variables={"request": request},
        )
        return {"status": "success", "answer": answer}

    def _extract_keyword(self, text: str, exclude: List[str]) -> str:
        words = text.replace("，", " ").replace(",", " ").split()
        for word in words:
            if word not in exclude and len(word) > 1:
                return word
        return text[:20]

    def _extract_skill_name(self, text: str) -> str:
        matches = re.findall(r'["\']([^"\']+)["\']', text)
        if matches:
            return str(matches[0]).replace(" ", "_").lower()
        return ""

    def _extract_code(self, text: str) -> str:
        if "```" in text:
            matches = re.findall(r"```(?:\w+)?\n?(.*?)```", text, re.DOTALL)
            if matches:
                return str(matches[0]).strip()
        if "`" in text:
            matches = re.findall(r"`([^`]+)`", text)
            if matches:
                return str(matches[0]).strip()
        return ""

    async def process(
        self, user_request: str, provider_id: str, context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """处理用户请求（工作流模式）"""
        return await self.process_autonomous(user_request, provider_id, context)
