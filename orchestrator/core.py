"""
动态智能体编排器核心 - 增强版

支持：
- 多步骤任务规划与执行
- 真正的代码生成（不只是描述文档）
- 网页项目创建与部署
- 自主迭代改进
"""

import json
import logging
import asyncio
import re
import os
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

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
        config: Optional[Dict] = None
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
        
        # 项目目录
        self.projects_dir = "/AstrBot/data/agent_projects"
    
    async def process_autonomous(
        self,
        user_request: str,
        provider_id: str,
        context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """全自主处理用户请求"""
        context = context or {}
        is_admin = context.get("is_admin", False)
        event = context.get("event")
        show_process = self.config.get("show_thinking_process", True)
        
        configured_provider = self.config.get("llm_provider")
        if configured_provider:
            provider_id = configured_provider
        
        thinking_steps = []
        
        def log_step(step: str):
            thinking_steps.append(step)
            logger.info(f"[自主Agent] {step}")
        
        log_step(f"📥 收到请求: {user_request[:50]}...")
        
        try:
            log_step("🧠 正在分析用户意图...")
            intent = await self._analyze_intent_enhanced(user_request, provider_id)
            log_step(f"💡 识别意图: {intent.get('intent')} - {intent.get('description', '')}")

            # 调试：检查 SubAgent 设置
            logger.info("SubAgent 设置: %s", self.subagent_settings)
            should_use = self._should_use_subagents(intent, user_request)
            logger.info("_should_use_subagents 返回: %s (intent=%s)", should_use, intent.get("intent"))
            
            if should_use:
                if self.meta_orchestrator and event:
                    log_step("🤖 启用动态 SubAgent 编排...")
                    result = await self.meta_orchestrator.process(
                        user_request=user_request,
                        provider_id=provider_id,
                        event=event,
                        is_admin=is_admin,
                    )
                    log_step("✅ SubAgent 编排完成")
                    if show_process and thinking_steps:
                        process_text = "\n".join([f"  {s}" for s in thinking_steps])
                        result["answer"] = (
                            f"🤖 **思考过程:**\n{process_text}\n\n---\n\n"
                            f"{result.get('answer', '')}"
                        )
                        result["thinking_steps"] = thinking_steps
                    return result
                log_step("⚠️ 未找到 SubAgent 编排器，回退到单 Agent 模式")
            
            # 检查是否需要多步骤执行
            if intent.get("needs_planning", False):
                log_step("📋 任务复杂，生成执行计划...")
                plan = await self._generate_execution_plan(user_request, intent, provider_id)
                log_step(f"📋 计划包含 {len(plan)} 个步骤")
                
                result = await self._execute_plan(
                    plan=plan,
                    user_request=user_request,
                    provider_id=provider_id,
                    is_admin=is_admin,
                    event=event,
                    log_step=log_step
                )
            else:
                log_step(f"⚙️ 开始执行: {intent.get('intent')}")
                result = await self._execute_by_intent(
                    intent=intent,
                    user_request=user_request,
                    provider_id=provider_id,
                    is_admin=is_admin,
                    event=event
                )
            
            log_step("✅ 执行完成")
            
            if show_process and thinking_steps:
                process_text = "\n".join([f"  {s}" for s in thinking_steps])
                result["answer"] = f"🤖 **思考过程:**\n{process_text}\n\n---\n\n{result.get('answer', '')}"
                result["thinking_steps"] = thinking_steps
            
            return result
            
        except Exception as e:
            logger.error(f"[自主Agent] 执行失败: {e}", exc_info=True)
            
            if self.debugger:
                try:
                    import traceback
                    analysis = await self.debugger.analyze_error(
                        error=e,
                        traceback_info=traceback.format_exc(),
                        context={"request": user_request}
                    )
                    return {
                        "status": "error",
                        "answer": f"❌ 执行出错: {str(e)}\n\n🔍 **自动诊断:**\n{analysis}",
                        "error": str(e)
                    }
                except Exception:
                    pass
            
            return {
                "status": "error",
                "answer": f"❌ 执行出错: {str(e)}",
                "error": str(e)
            }

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
        
        prompt = f"""分析用户请求，判断需要执行什么操作。

用户请求：{request}

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
{{
    "intent": "操作类型",
    "needs_planning": true/false,  // 是否需要多步骤规划
    "complexity": "simple/medium/complex",
    "params": {{
        "project_name": "项目名称",
        "tech_stack": ["python", "flask", "html"],  // 技术栈
        "features": ["功能1", "功能2"],
        "other_params": "..."
    }},
    "needs_admin": true/false,
    "description": "简短描述"
}}

只输出 JSON。"""

        try:
            response = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
                system_prompt="你是一个项目需求分析专家。只输出 JSON。"
            )
            
            text = response.completion_text
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            
            return json.loads(text.strip())
            
        except Exception as e:
            logger.warning(f"意图分析失败: {e}")
            return {
                "intent": "reasoning",
                "needs_planning": False,
                "params": {},
                "needs_admin": False,
                "description": request
            }
    
    async def _generate_execution_plan(
        self,
        request: str,
        intent: Dict,
        provider_id: str
    ) -> List[ExecutionStep]:
        """生成多步骤执行计划"""
        
        params = intent.get("params", {})
        project_name = params.get("project_name", "my_project")
        tech_stack = params.get("tech_stack", ["python"])
        features = params.get("features", [])
        
        prompt = f"""你是一个高级程序员，需要规划一个项目的实现步骤。

项目需求：{request}
项目名称：{project_name}
技术栈：{', '.join(tech_stack)}
功能点：{', '.join(features) if features else '根据需求自动识别'}

请输出详细的执行计划，每个步骤都要包含完整的代码。

输出 JSON 数组：
[
    {{
        "step": 1,
        "action": "create_file",
        "description": "创建主程序文件",
        "file_path": "{project_name}/main.py",
        "code": "完整的 Python 代码..."
    }},
    {{
        "step": 2,
        "action": "create_file",
        "description": "创建配置文件",
        "file_path": "{project_name}/config.py",
        "code": "完整代码..."
    }},
    {{
        "step": 3,
        "action": "execute",
        "description": "安装依赖",
        "code": "pip install flask requests"
    }},
    {{
        "step": 4,
        "action": "execute",
        "description": "启动服务",
        "code": "cd {project_name} && python main.py"
    }}
]

要求：
1. 代码必须完整可运行，不要用省略号或注释代替代码
2. 包含所有必要的 import
3. 包含错误处理
4. 如果是 Web 应用，要包含启动服务的步骤
5. 文件路径使用相对路径

只输出 JSON 数组。"""

        try:
            response = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
                system_prompt="你是一个资深全栈工程师。输出完整可运行的代码，不要省略任何部分。只输出 JSON。"
            )
            
            text = response.completion_text
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            
            plan_data = json.loads(text.strip())
            
            steps = []
            for item in plan_data:
                steps.append(ExecutionStep(
                    step_num=item.get("step", len(steps) + 1),
                    action=item.get("action", "create_file"),
                    description=item.get("description", ""),
                    code=item.get("code"),
                    file_path=item.get("file_path")
                ))
            
            return steps
            
        except Exception as e:
            logger.error(f"生成执行计划失败: {e}")
            return [ExecutionStep(
                step_num=1,
                action="error",
                description=f"生成计划失败: {str(e)}"
            )]
    
    async def _execute_plan(
        self,
        plan: List[ExecutionStep],
        user_request: str,
        provider_id: str,
        is_admin: bool,
        event,
        log_step
    ) -> Dict[str, Any]:
        """执行多步骤计划"""
        
        results = []
        project_path = None
        
        for step in plan:
            log_step(f"📌 步骤 {step.step_num}: {step.description}")
            
            try:
                if step.action == "create_file":
                    result = await self._execute_create_file(step, event)
                    if project_path is None and step.file_path:
                        project_path = step.file_path.split("/")[0]
                        
                elif step.action == "execute":
                    if not is_admin:
                        result = "⚠️ 跳过（需要管理员权限）"
                    else:
                        result = await self._execute_command(step.code, event)
                        
                elif step.action == "error":
                    result = f"❌ {step.description}"
                    
                else:
                    result = f"未知操作: {step.action}"
                
                step.result = result
                step.status = "completed"
                results.append(f"✅ 步骤 {step.step_num}: {step.description}")
                
            except Exception as e:
                step.status = "failed"
                step.result = str(e)
                results.append(f"❌ 步骤 {step.step_num} 失败: {str(e)}")
                
                # 尝试自动修复
                if self.debugger and is_admin:
                    log_step(f"🔧 尝试自动修复...")
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
    
    async def _execute_create_file(self, step: ExecutionStep, event) -> str:
        """执行文件创建"""
        if not step.file_path or not step.code:
            return "❌ 缺少文件路径或代码"
        
        # 确保目录存在
        full_path = os.path.join(self.projects_dir, step.file_path)
        dir_path = os.path.dirname(full_path)
        
        # 创建目录命令
        mkdir_cmd = f"mkdir -p {dir_path}"
        
        # 写入文件命令 - 使用 cat 和 heredoc
        # 转义特殊字符
        escaped_code = step.code.replace("\\", "\\\\").replace("$", "\\$").replace("`", "\\`")
        write_cmd = f"""cat > {full_path} << 'ENDOFFILE'
{step.code}
ENDOFFILE"""
        
        if self.executor:
            try:
                # 创建目录
                await self.executor.execute(mkdir_cmd, event)
                # 写入文件
                result = await self.executor.execute(write_cmd, event)
                return f"✅ 已创建 `{step.file_path}`\n📂 绝对路径: `{full_path}`"
            except Exception as e:
                return f"❌ 创建文件失败: {str(e)}"
        
        return "❌ 执行器不可用"
    
    async def _execute_command(self, code: str, event) -> str:
        """执行命令"""
        if self.executor:
            return await self.executor.execute(code, event)
        return "❌ 执行器不可用"
    
    async def _auto_fix_error(
        self,
        error: Exception,
        step: ExecutionStep,
        provider_id: str
    ) -> Optional[str]:
        """尝试自动修复错误"""
        if not self.debugger:
            return None
        
        analysis = await self.debugger.analyze_error(
            error=error,
            traceback_info="",
            context={"step": step.description, "code": step.code}
        )
        
        return analysis
    
    async def _generate_summary(
        self,
        plan: List[ExecutionStep],
        project_path: Optional[str],
        provider_id: str
    ) -> str:
        """生成项目总结"""
        
        completed = sum(1 for s in plan if s.status == "completed")
        total = len(plan)
        
        files = [s.file_path for s in plan if s.action == "create_file" and s.file_path]
        
        project_abs_path = f"{self.projects_dir}/{project_path or 'my_project'}"
        
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
1. 查看文件: `/exec cat {project_abs_path}/<文件名>`
2. 打包下载: `/exec cd {project_abs_path} && tar czf /workspace/project.tar.gz .`
3. 运行程序: `/exec python {project_abs_path}/main.py`
4. 如果是 Web 应用，访问对应端口

💡 遇到问题? 发送 `/debug analyze 错误描述` 让我帮你分析
"""
        
        return summary
    
    async def _execute_by_intent(
        self,
        intent: Dict,
        user_request: str,
        provider_id: str,
        is_admin: bool,
        event
    ) -> Dict[str, Any]:
        """根据意图执行操作"""
        
        intent_type = intent.get("intent", "reasoning")
        params = intent.get("params", {})
        needs_admin = intent.get("needs_admin", False)
        
        if needs_admin and not is_admin:
            return {
                "status": "error",
                "answer": "❌ 此操作需要管理员权限"
            }
        
        if intent_type == "search_plugin":
            return await self._handle_search_plugin(params, user_request, provider_id)
        
        elif intent_type == "install_plugin":
            return await self._handle_install_plugin(params, user_request, provider_id, is_admin)
        
        elif intent_type == "create_skill":
            return await self._handle_create_skill(params, user_request, provider_id)
        
        elif intent_type in ["code_project", "web_app"]:
            # 对于代码项目，生成计划并执行
            plan = await self._generate_execution_plan(user_request, intent, provider_id)
            return await self._execute_plan(
                plan=plan,
                user_request=user_request,
                provider_id=provider_id,
                is_admin=is_admin,
                event=event,
                log_step=lambda x: logger.info(f"[执行] {x}")
            )
        
        elif intent_type == "execute_code":
            return await self._handle_execute_code(params, user_request, event, is_admin)
        
        elif intent_type == "debug":
            return await self._handle_debug(params, user_request, provider_id)
        
        else:
            return await self._handle_reasoning(user_request, provider_id)
    
    async def _handle_search_plugin(self, params: Dict, request: str, provider_id: str) -> Dict[str, Any]:
        """处理插件搜索"""
        keyword = params.get("keyword", "")
        if not keyword:
            keyword = self._extract_keyword(request, ["插件", "plugin", "搜索"])
        
        if self.plugin_tool:
            result = await self.plugin_tool.search_plugins(keyword)
            return {"status": "success", "answer": result}
        
        return {"status": "error", "answer": "❌ 插件管理工具不可用"}
    
    async def _handle_install_plugin(self, params: Dict, request: str, provider_id: str, is_admin: bool) -> Dict[str, Any]:
        """处理插件安装"""
        if not is_admin:
            return {"status": "error", "answer": "❌ 只有管理员可以安装插件"}
        
        repo_url = params.get("repo_url", "")
        if not repo_url:
            urls = re.findall(r'https?://[^\s]+', request)
            if urls:
                repo_url = urls[0]
        
        if not repo_url:
            return {"status": "error", "answer": "❌ 请提供插件仓库地址"}
        
        if self.plugin_tool:
            result = await self.plugin_tool.install_plugin(repo_url)
            return {"status": "success", "answer": result}
        
        return {"status": "error", "answer": "❌ 插件管理工具不可用"}
    
    async def _handle_create_skill(self, params: Dict, request: str, provider_id: str) -> Dict[str, Any]:
        """处理 Skill 创建"""
        skill_name = params.get("name", "") or self._extract_skill_name(request) or "my_skill"
        description = params.get("description", request)
        
        if self.skill_tool:
            try:
                content = await self.skill_tool.generate_skill_from_description(
                    name=skill_name,
                    user_description=description,
                    provider_id=provider_id
                )
                result = await self.skill_tool.create_skill(
                    name=skill_name,
                    description=description[:100],
                    content=content
                )
                return {"status": "success", "answer": result}
            except Exception as e:
                return {"status": "error", "answer": f"❌ 创建 Skill 失败: {str(e)}"}
        
        return {"status": "error", "answer": "❌ Skill 管理工具不可用"}
    
    async def _handle_execute_code(self, params: Dict, request: str, event, is_admin: bool) -> Dict[str, Any]:
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
        
        system_prompt = """你是一个全能的智能助手，拥有以下能力：
- 搜索和安装 AstrBot 插件
- 创建代码项目和网页应用
- 执行代码（本地/沙盒）
- 诊断和调试问题

如果用户想要创建程序/应用，引导他们使用 /agent 命令。"""

        response = await self.context.llm_generate(
            chat_provider_id=provider_id,
            prompt=request,
            system_prompt=system_prompt
        )
        
        return {"status": "success", "answer": response.completion_text}
    
    def _extract_keyword(self, text: str, exclude: List[str]) -> str:
        words = text.replace("，", " ").replace(",", " ").split()
        for word in words:
            if word not in exclude and len(word) > 1:
                return word
        return text[:20]
    
    def _extract_skill_name(self, text: str) -> str:
        matches = re.findall(r'["\']([^"\']+)["\']', text)
        if matches:
            return matches[0].replace(" ", "_").lower()
        return ""
    
    def _extract_code(self, text: str) -> str:
        if "```" in text:
            matches = re.findall(r'```(?:\w+)?\n?(.*?)```', text, re.DOTALL)
            if matches:
                return matches[0].strip()
        if "`" in text:
            matches = re.findall(r'`([^`]+)`', text)
            if matches:
                return matches[0].strip()
        return ""
    
    async def process(self, user_request: str, provider_id: str, context: Optional[Dict] = None) -> Dict[str, Any]:
        """处理用户请求（工作流模式）"""
        return await self.process_autonomous(user_request, provider_id, context)
