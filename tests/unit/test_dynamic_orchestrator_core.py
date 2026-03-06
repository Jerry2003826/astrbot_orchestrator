"""DynamicOrchestrator 核心路径测试。"""

from __future__ import annotations

import builtins
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from astrbot_orchestrator_v5.orchestrator.core import DynamicOrchestrator, ExecutionStep
from astrbot_orchestrator_v5.runtime.graph_state import OrchestratorGraphState
from astrbot_orchestrator_v5.runtime.request_context import RequestContext

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture
    from _pytest.fixtures import FixtureRequest
    from _pytest.logging import LogCaptureFixture
    from _pytest.monkeypatch import MonkeyPatch
    from pytest_mock.plugin import MockerFixture

    from tests.conftest import FakeContext

    _PYTEST_TYPE_IMPORTS = (
        CaptureFixture,
        FixtureRequest,
        LogCaptureFixture,
        MonkeyPatch,
        MockerFixture,
    )


class FakeMetaOrchestrator:
    """记录调用参数的 SubAgent 编排器替身。"""

    def __init__(self, result: dict[str, Any]) -> None:
        """保存固定返回值。"""

        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def process(
        self,
        user_request: str,
        provider_id: str,
        event: Any,
        is_admin: bool,
    ) -> dict[str, Any]:
        """记录调用并返回预置结果。"""

        self.calls.append(
            {
                "user_request": user_request,
                "provider_id": provider_id,
                "event": event,
                "is_admin": is_admin,
            }
        )
        return dict(self.result)


class FakeDebugger:
    """记录错误诊断调用的调试器替身。"""

    def __init__(self, analysis: str) -> None:
        """保存固定诊断文本。"""

        self.analysis = analysis
        self.calls: list[dict[str, Any]] = []

    async def analyze_error(
        self,
        error: Exception,
        traceback_info: str,
        context: dict[str, Any],
    ) -> str:
        """记录诊断调用并返回分析内容。"""

        self.calls.append(
            {
                "error": str(error),
                "traceback_info": traceback_info,
                "context": context,
            }
        )
        return self.analysis


class FakeProblemDebugger:
    """记录问题分析调用的调试器替身。"""

    def __init__(self, analysis: str) -> None:
        """保存固定分析文本。"""

        self.analysis = analysis
        self.calls: list[tuple[str, str]] = []

    async def analyze_problem(self, request: str, provider_id: str) -> str:
        """记录问题分析调用。"""

        self.calls.append((request, provider_id))
        return self.analysis


class FailingDebugger:
    """在诊断阶段主动抛错的调试器替身。"""

    async def analyze_error(
        self,
        error: Exception,
        traceback_info: str,
        context: dict[str, Any],
    ) -> str:
        """模拟诊断器内部失败。"""

        del error
        del traceback_info
        del context
        raise RuntimeError("debugger failed")


class FakePipeline:
    """记录 ainvoke 调用并返回预设值的管道替身。"""

    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        """保存返回值与异常。"""

        self.result = result
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def ainvoke(self, provider_id: str, variables: dict[str, Any]) -> Any:
        """记录调用参数并返回预设结果。"""

        self.calls.append({"provider_id": provider_id, "variables": variables})
        if self.error is not None:
            raise self.error
        return self.result


class FakePluginTool:
    """插件工具替身。"""

    def __init__(self) -> None:
        """初始化调用记录。"""

        self.search_calls: list[str] = []
        self.install_calls: list[str] = []

    async def search_plugins(self, keyword: str) -> str:
        """记录搜索关键字并返回固定结果。"""

        self.search_calls.append(keyword)
        return f"search:{keyword}"

    async def install_plugin(self, repo_url: str) -> str:
        """记录安装地址并返回固定结果。"""

        self.install_calls.append(repo_url)
        return f"install:{repo_url}"


class FakeSkillTool:
    """Skill 工具替身。"""

    def __init__(
        self,
        generated_content: str = "skill-content",
        create_error: Exception | None = None,
    ) -> None:
        """保存生成结果与可选异常。"""

        self.generated_content = generated_content
        self.create_error = create_error
        self.generate_calls: list[tuple[str, str, str]] = []
        self.create_calls: list[tuple[str, str, str]] = []

    async def generate_skill_from_description(
        self,
        name: str,
        user_description: str,
        provider_id: str,
    ) -> str:
        """记录生成调用并返回预设内容。"""

        self.generate_calls.append((name, user_description, provider_id))
        return self.generated_content

    async def create_skill(
        self,
        name: str,
        description: str,
        content: str,
    ) -> str:
        """记录创建调用并按需抛出异常。"""

        self.create_calls.append((name, description, content))
        if self.create_error is not None:
            raise self.create_error
        return f"created:{name}"


class FakeExecutor:
    """执行器替身。"""

    def __init__(
        self,
        auto_result: str = "auto-result",
        execute_result: str = "exec-result",
    ) -> None:
        """保存预设结果。"""

        self.auto_result = auto_result
        self.execute_result = execute_result
        self.auto_calls: list[tuple[str, Any, str]] = []
        self.execute_calls: list[tuple[str, Any]] = []

    async def auto_execute(self, code: str, event: Any, code_type: str = "shell") -> str:
        """记录自动执行调用。"""

        self.auto_calls.append((code, event, code_type))
        return self.auto_result

    async def execute(self, command: str, event: Any) -> str:
        """记录命令执行调用。"""

        self.execute_calls.append((command, event))
        return self.execute_result


@pytest.mark.asyncio
async def test_dynamic_orchestrator_process_request_uses_meta_orchestrator_for_complex_intent(
    fake_context: "FakeContext",
) -> None:
    """复杂请求应走 SubAgent 编排路径，并使用配置覆盖 provider。"""

    meta_orchestrator = FakeMetaOrchestrator({"status": "success", "answer": "subagent-answer"})
    orchestrator = DynamicOrchestrator(
        context=fake_context,
        meta_orchestrator=meta_orchestrator,
        config={
            "show_thinking_process": False,
            "enable_dynamic_agents": True,
            "llm_provider": "override-provider",
        },
    )

    async def fake_analyze_intent(request: str, provider_id: str) -> dict[str, Any]:
        """返回需要 SubAgent 的复杂意图。"""

        del request
        del provider_id
        return {
            "intent": "web_app",
            "needs_planning": False,
            "complexity": "complex",
            "params": {},
            "description": "复杂项目",
        }

    orchestrator._analyze_intent_enhanced = fake_analyze_intent  # type: ignore[method-assign]

    request_context = RequestContext.from_legacy(
        user_request="帮我做一个复杂网站",
        provider_id="provider-x",
        context={"event": SimpleNamespace(role="admin")},
    )

    result = await orchestrator.process_request(request_context)

    assert result["status"] == "success"
    assert result["answer"] == "subagent-answer"
    assert meta_orchestrator.calls == [
        {
            "user_request": "帮我做一个复杂网站",
            "provider_id": "override-provider",
            "event": request_context.event,
            "is_admin": True,
        }
    ]


@pytest.mark.asyncio
async def test_dynamic_orchestrator_process_request_executes_plan_and_writes_file(
    fake_context: "FakeContext",
    tmp_path: Path,
) -> None:
    """计划执行路径应能真正创建文件并产出总结。"""

    orchestrator = DynamicOrchestrator(
        context=fake_context,
        config={"show_thinking_process": False},
    )
    orchestrator.projects_dir = str(tmp_path)

    async def fake_analyze_intent(request: str, provider_id: str) -> dict[str, Any]:
        """返回需要规划的代码项目意图。"""

        del request
        del provider_id
        return {
            "intent": "code_project",
            "needs_planning": True,
            "complexity": "medium",
            "params": {"project_name": "demo"},
            "description": "生成项目",
        }

    async def fake_generate_plan(
        request: str,
        intent: dict[str, Any],
        provider_id: str,
    ) -> list[ExecutionStep]:
        """返回单步文件创建计划。"""

        del request
        del intent
        del provider_id
        return [
            ExecutionStep(
                step_num=1,
                action="create_file",
                description="创建主程序",
                file_path="demo/main.py",
                code='print("ok")',
            )
        ]

    orchestrator._analyze_intent_enhanced = fake_analyze_intent  # type: ignore[method-assign]
    orchestrator._generate_execution_plan = fake_generate_plan  # type: ignore[method-assign]

    request_context = RequestContext.from_legacy(
        user_request="写一个 demo 程序",
        provider_id="provider-x",
        context={"event": SimpleNamespace(role="admin")},
    )

    result = await orchestrator.process_request(request_context)

    assert result["status"] == "success"
    assert (tmp_path / "demo" / "main.py").read_text(encoding="utf-8") == 'print("ok")'
    assert "✅ 步骤 1: 创建主程序" in result["answer"]
    assert "## 📊 项目创建完成" in result["answer"]


@pytest.mark.asyncio
async def test_dynamic_orchestrator_execute_create_file_rejects_unsafe_path(
    fake_context: "FakeContext",
    tmp_path: Path,
) -> None:
    """创建文件时应拒绝越界路径。"""

    projects_dir = tmp_path / "projects"
    orchestrator = DynamicOrchestrator(
        context=fake_context,
        config={"show_thinking_process": False},
    )
    orchestrator.projects_dir = str(projects_dir)

    result = await orchestrator._execute_create_file(
        step=ExecutionStep(
            step_num=1,
            action="create_file",
            description="危险写入",
            file_path="../escape.py",
            code="print('boom')",
        ),
        event=object(),
        is_admin=True,
    )

    assert result.startswith("❌ 创建文件失败")
    assert not (tmp_path / "escape.py").exists()


@pytest.mark.asyncio
async def test_dynamic_orchestrator_execute_by_intent_blocks_non_admin_side_effect(
    fake_context: "FakeContext",
) -> None:
    """声明需要管理员的意图应在入口处被拒绝。"""

    orchestrator = DynamicOrchestrator(
        context=fake_context,
        config={"show_thinking_process": False},
    )

    result = await orchestrator._execute_by_intent(
        intent={"intent": "search_plugin", "needs_admin": True, "params": {}},
        user_request="搜索插件",
        provider_id="provider-x",
        is_admin=False,
        event=object(),
    )

    assert result == {"status": "error", "answer": "❌ 此操作需要管理员权限"}


@pytest.mark.asyncio
async def test_dynamic_orchestrator_process_request_returns_debug_analysis_on_failure(
    fake_context: "FakeContext",
) -> None:
    """异常路径应返回自动诊断结果。"""

    debugger = FakeDebugger("这是诊断结果")
    orchestrator = DynamicOrchestrator(
        context=fake_context,
        debugger=debugger,
        config={"show_thinking_process": False},
    )

    async def raise_intent_error(request: str, provider_id: str) -> dict[str, Any]:
        """模拟意图分析失败。"""

        del request
        del provider_id
        raise RuntimeError("boom")

    orchestrator._analyze_intent_enhanced = raise_intent_error  # type: ignore[method-assign]

    request_context = RequestContext.from_legacy(
        user_request="这个请求会失败",
        provider_id="provider-x",
        context={"event": SimpleNamespace(role="member")},
    )

    result = await orchestrator.process_request(request_context)

    assert result["status"] == "error"
    assert "自动诊断" in result["answer"]
    assert "这是诊断结果" in result["answer"]
    assert debugger.calls[0]["context"]["request"] == "这个请求会失败"


def test_dynamic_orchestrator_parse_helpers_and_extractors(
    fake_context: "FakeContext",
) -> None:
    """解析器与文本提取辅助函数应覆盖成功与失败场景。"""

    orchestrator = DynamicOrchestrator(
        context=fake_context, config={"show_thinking_process": False}
    )

    payload = orchestrator._parse_intent_payload('{"intent": "reasoning", "params": {}}')
    plan = orchestrator._parse_execution_plan('[{"description": "写文件"}]')

    assert payload["intent"] == "reasoning"
    assert plan[0].step_num == 1
    assert plan[0].action == "create_file"
    assert plan[0].description == "写文件"
    assert plan[0].file_path is None
    assert orchestrator._extract_keyword("请 搜索 日历 插件", ["插件", "搜索"]) == "日历"
    assert orchestrator._extract_keyword("x", ["插件"]) == "x"
    assert orchestrator._extract_skill_name('创建 "Hello Skill"') == "hello_skill"
    assert orchestrator._extract_skill_name("未命名 skill") == ""
    assert orchestrator._extract_code("```python\nprint(1)\n```") == "print(1)"
    assert orchestrator._extract_code("执行 `echo hi`") == "echo hi"
    assert orchestrator._extract_code("没有代码") == ""

    with pytest.raises(ValueError, match="JSON 对象"):
        orchestrator._parse_intent_payload('["bad"]')
    with pytest.raises(ValueError, match="JSON 数组"):
        orchestrator._parse_execution_plan('{"step": 1}')
    with pytest.raises(ValueError, match="JSON 对象"):
        orchestrator._parse_execution_plan('["bad"]')


@pytest.mark.asyncio
async def test_dynamic_orchestrator_subagent_fallback_and_finalize_with_process(
    fake_context: "FakeContext",
) -> None:
    """缺少编排器时应回退，并在最终结果中附带思考过程。"""

    orchestrator = DynamicOrchestrator(
        context=fake_context,
        config={"show_thinking_process": True, "enable_dynamic_agents": True},
    )
    request_context = RequestContext.from_legacy(
        user_request="做一个复杂任务",
        provider_id="provider-x",
        context={"event": SimpleNamespace(role="admin")},
    )
    state = OrchestratorGraphState(request_context=request_context)
    state.intent = {
        "intent": "web_app",
        "needs_planning": True,
        "complexity": "complex",
        "description": "复杂任务",
    }

    used_subagents = await orchestrator._subagent_node(state)

    assert used_subagents is False
    assert "回退到单 Agent 模式" in state.thinking_steps[-1]

    state.result = {"status": "success", "answer": "完成"}
    finalized = orchestrator._finalize_state_result(state)

    assert "🤖 **思考过程:**" in finalized["answer"]
    assert finalized["thinking_steps"] == state.thinking_steps

    empty_state = OrchestratorGraphState(request_context=request_context)
    assert orchestrator._finalize_state_result(empty_state)["answer"] == "❌ 未生成结果"


@pytest.mark.asyncio
async def test_dynamic_orchestrator_build_error_result_falls_back_when_debugger_errors(
    fake_context: "FakeContext",
) -> None:
    """诊断器自身失败时应返回基础错误响应。"""

    orchestrator = DynamicOrchestrator(
        context=fake_context,
        debugger=FailingDebugger(),
        config={"show_thinking_process": False},
    )
    state = OrchestratorGraphState(
        request_context=RequestContext.from_legacy(
            user_request="会失败的请求",
            provider_id="provider-x",
            context={"event": SimpleNamespace(role="member")},
        )
    )

    result = await orchestrator._build_error_result(state, RuntimeError("boom"))

    assert result == {
        "status": "error",
        "answer": "❌ 执行出错: boom",
        "error": "boom",
    }
    assert state.error == "boom"


@pytest.mark.asyncio
async def test_dynamic_orchestrator_process_wrappers_delegate_correctly(
    fake_context: "FakeContext",
) -> None:
    """`process_autonomous` 与 `process` 应分别转发到正确入口。"""

    orchestrator = DynamicOrchestrator(
        context=fake_context, config={"show_thinking_process": False}
    )
    captured_contexts: list[RequestContext] = []

    async def fake_process_request(request_context: RequestContext) -> dict[str, Any]:
        """记录请求上下文并返回固定结果。"""

        captured_contexts.append(request_context)
        return {"status": "success", "answer": "ok"}

    orchestrator.process_request = fake_process_request  # type: ignore[method-assign]

    auto_result = await orchestrator.process_autonomous(
        user_request="hello",
        provider_id="provider-x",
        context={"event": SimpleNamespace(role="admin")},
    )

    assert auto_result == {"status": "success", "answer": "ok"}
    assert captured_contexts[0].request_text == "hello"
    assert captured_contexts[0].provider_id == "provider-x"
    assert captured_contexts[0].is_admin is True

    delegated_calls: list[tuple[str, str, dict[str, Any] | None]] = []

    async def fake_process_autonomous(
        user_request: str,
        provider_id: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """记录工作流入口调用。"""

        delegated_calls.append((user_request, provider_id, context))
        return {"status": "success", "answer": "delegated"}

    orchestrator.process_autonomous = fake_process_autonomous  # type: ignore[method-assign]

    process_result = await orchestrator.process(
        user_request="via process",
        provider_id="provider-y",
        context={"flag": True},
    )

    assert process_result == {"status": "success", "answer": "delegated"}
    assert delegated_calls == [("via process", "provider-y", {"flag": True})]


def test_dynamic_orchestrator_subagent_settings_and_selection_rules(
    fake_context: "FakeContext",
) -> None:
    """子代理配置解析与选择逻辑应覆盖关键分支。"""

    custom_settings = {"enable_dynamic_agents": True, "force_subagents_for_complex_tasks": False}
    custom_orchestrator = DynamicOrchestrator(
        context=fake_context,
        config={"subagent_settings": custom_settings},
    )
    default_orchestrator = DynamicOrchestrator(
        context=fake_context,
        config={
            "enable_dynamic_agents": True,
            "max_concurrent_agents": 7,
            "agent_timeout": 123,
            "auto_cleanup_agents": False,
            "use_llm_task_analyzer": False,
            "force_subagents_for_complex_tasks": True,
        },
    )
    disabled_orchestrator = DynamicOrchestrator(context=fake_context, config={})

    assert custom_orchestrator.subagent_settings == custom_settings
    assert default_orchestrator.subagent_settings["max_concurrent_agents"] == 7
    assert default_orchestrator.subagent_settings["agent_timeout"] == 123
    assert default_orchestrator.subagent_settings["auto_cleanup_agents"] is False
    assert default_orchestrator.subagent_settings["use_llm_task_analyzer"] is False

    assert disabled_orchestrator._should_use_subagents({}, "普通请求") is False
    assert (
        default_orchestrator._should_use_subagents(
            {"needs_planning": True},
            "需要规划",
        )
        is True
    )
    assert (
        default_orchestrator._should_use_subagents(
            {"complexity": "medium"},
            "中等复杂度",
        )
        is True
    )
    assert (
        default_orchestrator._should_use_subagents(
            {"intent": "code_project"},
            "写项目",
        )
        is True
    )
    assert (
        default_orchestrator._should_use_subagents(
            {"intent": "reasoning"},
            "普通问题",
        )
        is False
    )
    assert (
        custom_orchestrator._should_use_subagents(
            {"intent": "reasoning"},
            "请并行处理多个子代理任务",
        )
        is True
    )


@pytest.mark.asyncio
async def test_dynamic_orchestrator_intent_and_plan_pipelines_handle_success_and_failure(
    fake_context: "FakeContext",
) -> None:
    """意图与计划管道应正确处理成功调用和异常回退。"""

    orchestrator = DynamicOrchestrator(
        context=fake_context, config={"show_thinking_process": False}
    )
    intent_pipeline = FakePipeline(result={"intent": "debug"})
    plan_pipeline = FakePipeline(
        result=[
            ExecutionStep(
                step_num=2,
                action="execute",
                description="run",
                code="echo ok",
            )
        ]
    )
    orchestrator.intent_pipeline = intent_pipeline  # type: ignore[assignment]
    orchestrator.plan_pipeline = plan_pipeline  # type: ignore[assignment]

    intent = await orchestrator._analyze_intent_enhanced("分析请求", "provider-a")
    plan = await orchestrator._generate_execution_plan(
        request="创建项目",
        intent={
            "params": {"project_name": "demo", "tech_stack": ["python", "flask"], "features": []}
        },
        provider_id="provider-b",
    )

    assert intent == {"intent": "debug"}
    assert plan[0].action == "execute"
    assert intent_pipeline.calls == [
        {"provider_id": "provider-a", "variables": {"request": "分析请求"}}
    ]
    assert plan_pipeline.calls == [
        {
            "provider_id": "provider-b",
            "variables": {
                "request": "创建项目",
                "project_name": "demo",
                "tech_stack": "python, flask",
                "features": "根据需求自动识别",
            },
        }
    ]

    failing_intent_pipeline = FakePipeline(error=RuntimeError("intent boom"))
    failing_plan_pipeline = FakePipeline(error=RuntimeError("plan boom"))
    orchestrator.intent_pipeline = failing_intent_pipeline  # type: ignore[assignment]
    orchestrator.plan_pipeline = failing_plan_pipeline  # type: ignore[assignment]

    fallback_intent = await orchestrator._analyze_intent_enhanced("失败请求", "provider-c")
    fallback_plan = await orchestrator._generate_execution_plan(
        request="失败项目",
        intent={"params": {}},
        provider_id="provider-d",
    )

    assert fallback_intent["intent"] == "reasoning"
    assert fallback_intent["description"] == "失败请求"
    assert fallback_plan[0].action == "error"
    assert "plan boom" in fallback_plan[0].description


@pytest.mark.asyncio
async def test_dynamic_orchestrator_execute_plan_handles_skipped_failed_and_unknown_steps(
    fake_context: "FakeContext",
) -> None:
    """计划执行应覆盖 skipped、failed 与未知操作分支。"""

    orchestrator = DynamicOrchestrator(
        context=fake_context, config={"show_thinking_process": False}
    )
    logs: list[str] = []
    plan = [
        ExecutionStep(
            step_num=1,
            action="create_file",
            description="写文件但无权限",
            file_path="demo/main.py",
            code='print("x")',
        ),
        ExecutionStep(
            step_num=2,
            action="execute",
            description="执行但无权限",
            code="echo hi",
        ),
        ExecutionStep(
            step_num=3,
            action="error",
            description="计划生成失败",
        ),
        ExecutionStep(
            step_num=4,
            action="unknown",
            description="未知动作",
        ),
    ]

    result = await orchestrator._execute_plan(
        plan=plan,
        user_request="构建项目",
        provider_id="provider-x",
        is_admin=False,
        event=object(),
        log_step=logs.append,
    )

    assert result["status"] == "success"
    assert result["project_path"] == "demo"
    assert "⚠️ 步骤 1: 写文件但无权限" in result["answer"]
    assert "⚠️ 步骤 2: 执行但无权限" in result["answer"]
    assert "❌ 步骤 3: 计划生成失败" in result["answer"]
    assert "❌ 步骤 4: 未知动作" in result["answer"]
    assert logs[0] == "📌 步骤 1: 写文件但无权限"

    missing_path_plan = [
        ExecutionStep(step_num=5, action="create_file", description="缺少文件路径")
    ]
    missing_path_result = await orchestrator._execute_plan(
        plan=missing_path_plan,
        user_request="补充计划",
        provider_id="provider-y",
        is_admin=True,
        event=object(),
        log_step=logs.append,
    )

    assert missing_path_result["project_path"] is None
    assert "⚠️ 步骤 5: 缺少文件路径" in missing_path_result["answer"]


@pytest.mark.asyncio
async def test_dynamic_orchestrator_execute_plan_handles_execute_failures_and_auto_fix(
    fake_context: "FakeContext",
) -> None:
    """执行计划应处理缺少命令、命令失败和异常后的自动修复。"""

    orchestrator = DynamicOrchestrator(
        context=fake_context,
        debugger=FakeDebugger("分析"),
        config={"show_thinking_process": False},
    )
    logs: list[str] = []
    plan = [
        ExecutionStep(step_num=1, action="execute", description="缺少命令"),
        ExecutionStep(step_num=2, action="execute", description="命令返回失败", code="bad"),
    ]

    async def fake_execute_command(code: str, event: Any) -> str:
        """模拟命令执行返回失败文本。"""

        del event
        return "❌ failed" if code == "bad" else "ok"

    orchestrator._execute_command = fake_execute_command  # type: ignore[method-assign]

    result = await orchestrator._execute_plan(
        plan=plan,
        user_request="执行计划",
        provider_id="provider-x",
        is_admin=True,
        event=object(),
        log_step=logs.append,
    )

    assert "❌ 步骤 1: 缺少命令" in result["answer"]
    assert "❌ 步骤 2: 命令返回失败" in result["answer"]

    crashing_plan = [ExecutionStep(step_num=3, action="execute", description="抛异常", code="boom")]

    async def raising_execute_command(code: str, event: Any) -> str:
        """模拟命令执行直接抛错。"""

        del code
        del event
        raise RuntimeError("exec boom")

    async def fake_auto_fix(error: Exception, step: ExecutionStep, provider_id: str) -> str | None:
        """模拟自动修复成功。"""

        assert str(error) == "exec boom"
        assert step.description == "抛异常"
        assert provider_id == "provider-y"
        return "patched"

    orchestrator._execute_command = raising_execute_command  # type: ignore[method-assign]
    orchestrator._auto_fix_error = fake_auto_fix  # type: ignore[method-assign]

    crash_result = await orchestrator._execute_plan(
        plan=crashing_plan,
        user_request="执行崩溃计划",
        provider_id="provider-y",
        is_admin=True,
        event=object(),
        log_step=logs.append,
    )

    assert "❌ 步骤 3 失败: exec boom" in crash_result["answer"]
    assert "🔧 已修复: patched" in crash_result["answer"]
    assert "🔧 尝试自动修复..." in logs


@pytest.mark.asyncio
async def test_dynamic_orchestrator_execute_plan_ignores_auto_fix_errors(
    fake_context: "FakeContext",
) -> None:
    """自动修复本身失败时，计划执行不应再次抛错。"""

    orchestrator = DynamicOrchestrator(
        context=fake_context,
        debugger=FakeDebugger("分析"),
        config={"show_thinking_process": False},
    )
    logs: list[str] = []
    plan = [ExecutionStep(step_num=1, action="execute", description="执行异常", code="boom")]

    async def raising_execute_command(code: str, event: Any) -> str:
        """模拟执行命令直接抛错。"""

        del code
        del event
        raise RuntimeError("exec boom")

    async def failing_auto_fix(
        error: Exception, step: ExecutionStep, provider_id: str
    ) -> str | None:
        """模拟自动修复阶段再次抛错。"""

        del error
        del step
        del provider_id
        raise RuntimeError("fix boom")

    orchestrator._execute_command = raising_execute_command  # type: ignore[method-assign]
    orchestrator._auto_fix_error = failing_auto_fix  # type: ignore[method-assign]

    result = await orchestrator._execute_plan(
        plan=plan,
        user_request="执行崩溃计划",
        provider_id="provider-z",
        is_admin=True,
        event=object(),
        log_step=logs.append,
    )

    assert "❌ 步骤 1 失败: exec boom" in result["answer"]
    assert "已修复" not in result["answer"]
    assert logs[-1] == "🔧 尝试自动修复..."


@pytest.mark.asyncio
async def test_dynamic_orchestrator_execute_create_file_and_helpers_cover_error_paths(
    fake_context: "FakeContext",
    tmp_path: Path,
    monkeypatch: "MonkeyPatch",
) -> None:
    """文件创建与执行辅助函数应覆盖边界与异常路径。"""

    orchestrator = DynamicOrchestrator(
        context=fake_context, config={"show_thinking_process": False}
    )
    orchestrator.projects_dir = str(tmp_path)

    no_admin = await orchestrator._execute_create_file(
        step=ExecutionStep(step_num=1, action="create_file", description="无权限"),
        event=object(),
        is_admin=False,
    )
    missing_fields = await orchestrator._execute_create_file(
        step=ExecutionStep(step_num=2, action="create_file", description="缺字段"),
        event=object(),
        is_admin=True,
    )

    def failing_open(*args: Any, **kwargs: Any) -> Any:
        """模拟写文件时出现 IO 异常。"""

        del args
        del kwargs
        raise OSError("disk full")

    monkeypatch.setattr(builtins, "open", failing_open)
    io_error = await orchestrator._execute_create_file(
        step=ExecutionStep(
            step_num=3,
            action="create_file",
            description="磁盘已满",
            file_path="demo/app.py",
            code="print(1)",
        ),
        event=object(),
        is_admin=True,
    )

    assert no_admin == "⚠️ 跳过（需要管理员权限）"
    assert missing_fields == "❌ 缺少文件路径或代码"
    assert io_error == "❌ 创建文件失败: disk full"
    assert await orchestrator._execute_command("echo hi", object()) == "❌ 执行器不可用"
    assert (
        await orchestrator._auto_fix_error(
            RuntimeError("boom"),
            ExecutionStep(step_num=4, action="execute", description="step", code="print(1)"),
            "provider-x",
        )
        is None
    )

    executor = FakeExecutor(execute_result="shell-ok")
    debugger = FakeDebugger("fixed")
    orchestrator.executor = executor
    orchestrator.debugger = debugger

    assert await orchestrator._execute_command("echo hi", "evt") == "shell-ok"
    assert (
        await orchestrator._auto_fix_error(
            RuntimeError("boom"),
            ExecutionStep(step_num=5, action="execute", description="修复步骤", code="print(2)"),
            "provider-y",
        )
        == "fixed"
    )
    assert executor.execute_calls == [("echo hi", "evt")]
    assert debugger.calls[0]["context"]["step"] == "修复步骤"


@pytest.mark.asyncio
async def test_dynamic_orchestrator_handlers_cover_success_and_failure_paths(
    fake_context: "FakeContext",
) -> None:
    """各类 `_handle_*` 分支应覆盖成功、权限与工具缺失场景。"""

    plugin_tool = FakePluginTool()
    skill_tool = FakeSkillTool()
    executor = FakeExecutor(auto_result="auto-done")
    debugger = FakeProblemDebugger("problem-analysis")
    reasoning_pipeline = FakePipeline(result="reasoned-answer")
    orchestrator = DynamicOrchestrator(
        context=fake_context,
        plugin_tool=plugin_tool,
        skill_tool=skill_tool,
        executor=executor,
        debugger=debugger,
        config={"show_thinking_process": False},
    )
    orchestrator.reasoning_pipeline = reasoning_pipeline  # type: ignore[assignment]

    search_result = await orchestrator._handle_search_plugin({}, "请 搜索 天气 插件", "provider-x")
    unavailable_search = await DynamicOrchestrator(
        context=fake_context,
        config={"show_thinking_process": False},
    )._handle_search_plugin({}, "搜索 插件", "provider-x")
    install_denied = await orchestrator._handle_install_plugin({}, "安装插件", "provider-x", False)
    install_missing = await orchestrator._handle_install_plugin({}, "安装插件", "provider-x", True)
    install_success = await orchestrator._handle_install_plugin(
        {},
        "请安装 https://example.com/plugin.git",
        "provider-x",
        True,
    )
    unavailable_install = await DynamicOrchestrator(
        context=fake_context,
        config={"show_thinking_process": False},
    )._handle_install_plugin(
        {"repo_url": "https://example.com/plugin.git"},
        "安装插件",
        "provider-x",
        True,
    )
    create_denied = await orchestrator._handle_create_skill(
        {}, '创建 "Hello Skill"', "provider-x", False
    )
    create_success = await orchestrator._handle_create_skill(
        {}, '创建 "Hello Skill"', "provider-x", True
    )
    create_failed = await DynamicOrchestrator(
        context=fake_context,
        skill_tool=FakeSkillTool(create_error=RuntimeError("create boom")),
        config={"show_thinking_process": False},
    )._handle_create_skill({}, '创建 "Boom Skill"', "provider-x", True)
    unavailable_skill = await DynamicOrchestrator(
        context=fake_context,
        config={"show_thinking_process": False},
    )._handle_create_skill({}, "创建 skill", "provider-x", True)
    execute_denied = await orchestrator._handle_execute_code({}, "执行 `echo hi`", object(), False)
    execute_missing = await orchestrator._handle_execute_code({}, "没有代码", object(), True)
    execute_success = await orchestrator._handle_execute_code({}, "执行 `echo hi`", "evt", True)
    unavailable_execute = await DynamicOrchestrator(
        context=fake_context,
        config={"show_thinking_process": False},
    )._handle_execute_code({"code": "echo hi"}, "执行代码", object(), True)
    debug_success = await orchestrator._handle_debug({}, "帮我调试", "provider-x")
    debug_unavailable = await DynamicOrchestrator(
        context=fake_context,
        config={"show_thinking_process": False},
    )._handle_debug({}, "帮我调试", "provider-x")
    reasoning_success = await orchestrator._handle_reasoning("解释一下", "provider-x")
    explicit_search = await orchestrator._handle_search_plugin(
        {"keyword": "calendar"},
        "搜索插件",
        "provider-x",
    )

    assert search_result == {"status": "success", "answer": "search:天气"}
    assert explicit_search == {"status": "success", "answer": "search:calendar"}
    assert unavailable_search == {"status": "error", "answer": "❌ 插件管理工具不可用"}
    assert install_denied == {"status": "error", "answer": "❌ 只有管理员可以安装插件"}
    assert install_missing == {"status": "error", "answer": "❌ 请提供插件仓库地址"}
    assert install_success == {
        "status": "success",
        "answer": "install:https://example.com/plugin.git",
    }
    assert unavailable_install == {"status": "error", "answer": "❌ 插件管理工具不可用"}
    assert create_denied == {"status": "error", "answer": "❌ 只有管理员可以创建 Skill"}
    assert create_success == {"status": "success", "answer": "created:hello_skill"}
    assert create_failed == {"status": "error", "answer": "❌ 创建 Skill 失败: create boom"}
    assert unavailable_skill == {"status": "error", "answer": "❌ Skill 管理工具不可用"}
    assert execute_denied == {"status": "error", "answer": "❌ 只有管理员可以执行代码"}
    assert execute_missing == {"status": "error", "answer": "❌ 请提供要执行的代码"}
    assert execute_success == {"status": "success", "answer": "auto-done"}
    assert unavailable_execute == {"status": "error", "answer": "❌ 执行器不可用"}
    assert debug_success == {
        "status": "success",
        "answer": "🔍 **问题分析:**\n\nproblem-analysis",
    }
    assert debug_unavailable == {"status": "error", "answer": "❌ Debug 工具不可用"}
    assert reasoning_success == {"status": "success", "answer": "reasoned-answer"}
    assert plugin_tool.search_calls == ["天气", "calendar"]
    assert plugin_tool.install_calls == ["https://example.com/plugin.git"]
    assert skill_tool.generate_calls[0][0] == "hello_skill"
    assert skill_tool.create_calls[0][0] == "hello_skill"
    assert executor.auto_calls == [("echo hi", "evt", "shell")]
    assert debugger.calls == [("帮我调试", "provider-x")]


@pytest.mark.asyncio
async def test_dynamic_orchestrator_execute_by_intent_routes_to_project_execute_debug_and_reasoning(
    fake_context: "FakeContext",
) -> None:
    """按意图分发时应覆盖项目、执行、调试与默认推理路径。"""

    orchestrator = DynamicOrchestrator(
        context=fake_context, config={"show_thinking_process": False}
    )
    plan_calls: list[tuple[str, dict[str, Any], str]] = []
    execute_plan_calls: list[dict[str, Any]] = []
    execute_code_calls: list[tuple[dict[str, Any], str, Any, bool]] = []
    debug_calls: list[tuple[dict[str, Any], str, str]] = []
    reasoning_calls: list[tuple[str, str]] = []

    async def fake_generate_execution_plan(
        request: str,
        intent: dict[str, Any],
        provider_id: str,
    ) -> list[ExecutionStep]:
        """记录计划生成调用。"""

        plan_calls.append((request, intent, provider_id))
        return [ExecutionStep(step_num=1, action="error", description="plan")]

    async def fake_execute_plan(
        plan: list[ExecutionStep],
        user_request: str,
        provider_id: str,
        is_admin: bool,
        event: Any,
        log_step: Any,
    ) -> dict[str, Any]:
        """记录计划执行调用。"""

        del log_step
        execute_plan_calls.append(
            {
                "plan_len": len(plan),
                "user_request": user_request,
                "provider_id": provider_id,
                "is_admin": is_admin,
                "event": event,
            }
        )
        return {"status": "success", "answer": "planned"}

    async def fake_handle_execute_code(
        params: dict[str, Any],
        request: str,
        event: Any,
        is_admin: bool,
    ) -> dict[str, Any]:
        """记录 execute_code 分支调用。"""

        execute_code_calls.append((params, request, event, is_admin))
        return {"status": "success", "answer": "executed"}

    async def fake_handle_debug(
        params: dict[str, Any],
        request: str,
        provider_id: str,
    ) -> dict[str, Any]:
        """记录 debug 分支调用。"""

        debug_calls.append((params, request, provider_id))
        return {"status": "success", "answer": "debugged"}

    async def fake_handle_reasoning(request: str, provider_id: str) -> dict[str, Any]:
        """记录 reasoning 分支调用。"""

        reasoning_calls.append((request, provider_id))
        return {"status": "success", "answer": "reasoned"}

    orchestrator._generate_execution_plan = fake_generate_execution_plan  # type: ignore[method-assign]
    orchestrator._execute_plan = fake_execute_plan  # type: ignore[method-assign]
    orchestrator._handle_execute_code = fake_handle_execute_code  # type: ignore[method-assign]
    orchestrator._handle_debug = fake_handle_debug  # type: ignore[method-assign]
    orchestrator._handle_reasoning = fake_handle_reasoning  # type: ignore[method-assign]

    project_result = await orchestrator._execute_by_intent(
        intent={"intent": "code_project", "params": {}},
        user_request="做项目",
        provider_id="provider-x",
        is_admin=True,
        event="evt-1",
    )
    execute_result = await orchestrator._execute_by_intent(
        intent={"intent": "execute_code", "params": {"code": "echo hi"}},
        user_request="执行代码",
        provider_id="provider-y",
        is_admin=True,
        event="evt-2",
    )
    debug_result = await orchestrator._execute_by_intent(
        intent={"intent": "debug", "params": {"x": 1}},
        user_request="调试一下",
        provider_id="provider-z",
        is_admin=False,
        event="evt-3",
    )
    reasoning_result = await orchestrator._execute_by_intent(
        intent={"intent": "unknown", "params": {}},
        user_request="普通问题",
        provider_id="provider-r",
        is_admin=False,
        event="evt-4",
    )

    assert project_result == {"status": "success", "answer": "planned"}
    assert execute_result == {"status": "success", "answer": "executed"}
    assert debug_result == {"status": "success", "answer": "debugged"}
    assert reasoning_result == {"status": "success", "answer": "reasoned"}
    assert plan_calls[0][0] == "做项目"
    assert execute_plan_calls[0]["provider_id"] == "provider-x"
    assert execute_code_calls == [({"code": "echo hi"}, "执行代码", "evt-2", True)]
    assert debug_calls == [({"x": 1}, "调试一下", "provider-z")]
    assert reasoning_calls == [("普通问题", "provider-r")]


@pytest.mark.asyncio
async def test_dynamic_orchestrator_execute_by_intent_routes_plugin_install_and_skill_handlers(
    fake_context: "FakeContext",
) -> None:
    """按意图分发时应命中插件搜索、安装与 Skill 创建分支。"""

    orchestrator = DynamicOrchestrator(
        context=fake_context, config={"show_thinking_process": False}
    )
    search_calls: list[tuple[dict[str, Any], str, str]] = []
    install_calls: list[tuple[dict[str, Any], str, str, bool]] = []
    skill_calls: list[tuple[dict[str, Any], str, str, bool]] = []

    async def fake_search_plugin(
        params: dict[str, Any],
        request: str,
        provider_id: str,
    ) -> dict[str, Any]:
        """记录搜索插件分支调用。"""

        search_calls.append((params, request, provider_id))
        return {"status": "success", "answer": "searched"}

    async def fake_install_plugin(
        params: dict[str, Any],
        request: str,
        provider_id: str,
        is_admin: bool,
    ) -> dict[str, Any]:
        """记录安装插件分支调用。"""

        install_calls.append((params, request, provider_id, is_admin))
        return {"status": "success", "answer": "installed"}

    async def fake_create_skill(
        params: dict[str, Any],
        request: str,
        provider_id: str,
        is_admin: bool,
    ) -> dict[str, Any]:
        """记录 Skill 创建分支调用。"""

        skill_calls.append((params, request, provider_id, is_admin))
        return {"status": "success", "answer": "skill-created"}

    orchestrator._handle_search_plugin = fake_search_plugin  # type: ignore[method-assign]
    orchestrator._handle_install_plugin = fake_install_plugin  # type: ignore[method-assign]
    orchestrator._handle_create_skill = fake_create_skill  # type: ignore[method-assign]

    search_result = await orchestrator._execute_by_intent(
        intent={"intent": "search_plugin", "params": {"keyword": "calendar"}},
        user_request="搜索插件",
        provider_id="provider-a",
        is_admin=False,
        event=object(),
    )
    install_result = await orchestrator._execute_by_intent(
        intent={"intent": "install_plugin", "params": {"repo_url": "https://x"}},
        user_request="安装插件",
        provider_id="provider-b",
        is_admin=True,
        event=object(),
    )
    skill_result = await orchestrator._execute_by_intent(
        intent={"intent": "create_skill", "params": {"name": "demo"}},
        user_request="创建 skill",
        provider_id="provider-c",
        is_admin=True,
        event=object(),
    )

    assert search_result == {"status": "success", "answer": "searched"}
    assert install_result == {"status": "success", "answer": "installed"}
    assert skill_result == {"status": "success", "answer": "skill-created"}
    assert search_calls == [({"keyword": "calendar"}, "搜索插件", "provider-a")]
    assert install_calls == [({"repo_url": "https://x"}, "安装插件", "provider-b", True)]
    assert skill_calls == [({"name": "demo"}, "创建 skill", "provider-c", True)]


def test_dynamic_orchestrator_extract_code_handles_unclosed_or_empty_markup(
    fake_context: "FakeContext",
) -> None:
    """未闭合或空代码标记不应被误识别为可执行代码。"""

    orchestrator = DynamicOrchestrator(
        context=fake_context, config={"show_thinking_process": False}
    )

    assert orchestrator._extract_code("```broken") == ""
    assert orchestrator._extract_code("这里只有反引号 `") == ""
