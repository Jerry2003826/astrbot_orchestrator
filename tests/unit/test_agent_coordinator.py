"""AgentCoordinator 单元测试。"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from astrbot_orchestrator_v5.orchestrator.agent_coordinator import AgentCoordinator, TaskResult
from astrbot_orchestrator_v5.orchestrator.agent_templates import AgentSpec
from astrbot_orchestrator_v5.orchestrator.task_analyzer import AgentTask, TaskPlan

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


def make_agent() -> AgentSpec:
    """构造最小可用的 AgentSpec。"""

    return AgentSpec(
        agent_id="agent-1",
        name="code_agent",
        role="code",
        instructions="你是代码助手",
    )


def make_task(
    task_id: str,
    description: str,
    action: str,
    task_input: str,
    agent_role: str = "code",
) -> AgentTask:
    """构造最小可用的 AgentTask。"""

    return AgentTask(
        task_id=task_id,
        description=description,
        agent_role=agent_role,
        action=action,
        input=task_input,
    )


class FakeCapabilityBuilder:
    """记录调用的能力构建器替身。"""

    def __init__(self, executor: Any = None) -> None:
        """初始化记录容器。"""

        self.executor = executor
        self.build_skill_calls: list[dict[str, Any]] = []
        self.configure_mcp_calls: list[dict[str, Any]] = []
        self.execute_code_calls: list[dict[str, Any]] = []

    async def build_skill(self, task_description: str, provider_id: str) -> str:
        """记录创建 Skill 调用。"""

        self.build_skill_calls.append(
            {"task_description": task_description, "provider_id": provider_id}
        )
        return "skill-created"

    async def configure_mcp(
        self,
        task_description: str,
        provider_id: str,
        params: dict[str, Any],
    ) -> str:
        """记录 MCP 配置调用。"""

        self.configure_mcp_calls.append(
            {
                "task_description": task_description,
                "provider_id": provider_id,
                "params": params,
            }
        )
        return "mcp-configured"

    async def execute_code(self, code: str, event: Any, params: dict[str, Any]) -> str:
        """记录代码执行调用。"""

        self.execute_code_calls.append({"code": code, "event": event, "params": params})
        return "code-executed"


class FakeArtifactService:
    """记录写文件调用的 ArtifactService 替身。"""

    def __init__(self, written_files: list[str] | None = None) -> None:
        """初始化预置写入结果。"""

        self.written_files = written_files or []
        self.write_calls: list[dict[str, Any]] = []

    async def write_files_to_workspace(
        self,
        files: dict[str, str],
        executor: Any,
        event: Any,
        project_name: str,
        base_path: str = "/workspace",
    ) -> list[str]:
        """记录工作区写入调用。"""

        self.write_calls.append(
            {
                "files": files,
                "executor": executor,
                "event": event,
                "project_name": project_name,
                "base_path": base_path,
            }
        )
        return list(self.written_files)


class RecordingContext:
    """记录 LLM 调用参数的上下文替身。"""

    def __init__(
        self,
        responses: list[str] | None = None,
        error: Exception | None = None,
    ) -> None:
        """保存预置响应和可选异常。"""

        self.responses = responses or []
        self.error = error
        self.calls: list[dict[str, str]] = []

    def queue_response(self, text: str) -> None:
        """追加一条待消费的 LLM 输出。"""

        self.responses.append(text)

    async def llm_generate(
        self,
        *,
        chat_provider_id: str,
        prompt: str,
        system_prompt: str,
    ) -> Any:
        """记录调用并返回预置响应。"""

        self.calls.append(
            {
                "chat_provider_id": chat_provider_id,
                "prompt": prompt,
                "system_prompt": system_prompt,
            }
        )
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise RuntimeError("RecordingContext 没有可用响应")
        return SimpleNamespace(completion_text=self.responses.pop(0))


@pytest.mark.asyncio
async def test_agent_coordinator_run_task_requires_admin_for_create_skill() -> None:
    """非管理员不应执行 create_skill 任务。"""

    capability_builder = FakeCapabilityBuilder()
    coordinator = AgentCoordinator(
        context=object(),
        capability_builder=capability_builder,
        artifact_service=FakeArtifactService(),
    )
    task = make_task("task-1", "创建 Skill", "create_skill", "生成 skill")

    result = await coordinator._run_task(
        task=task,
        agent_map={"code": make_agent()},
        event=object(),
        is_admin=False,
        provider_id="provider-1",
    )

    assert result.status == "skipped"
    assert result.output == "需要管理员权限才能创建 Skill"
    assert capability_builder.build_skill_calls == []


@pytest.mark.asyncio
async def test_agent_coordinator_execute_reports_skip_reason_for_admin_only_task() -> None:
    """执行结果应保留被跳过任务的具体原因。"""

    capability_builder = FakeCapabilityBuilder()
    coordinator = AgentCoordinator(
        context=object(),
        capability_builder=capability_builder,
        artifact_service=FakeArtifactService(),
    )
    agent = make_agent()
    task = make_task("task-1", "创建 Skill", "create_skill", "生成 skill")
    plan = TaskPlan(agents=[agent], tasks=[task], summary="")

    result = await coordinator.execute(
        plan=plan,
        agents=[agent],
        event=object(),
        is_admin=False,
        provider_id="provider-1",
    )

    assert "⏭️ 创建 Skill: 需要管理员权限才能创建 Skill" in result["answer"]


@pytest.mark.asyncio
async def test_agent_coordinator_run_task_downgrades_natural_language_execute_code() -> None:
    """自然语言形式的 execute_code 应降级为 llm 任务。"""

    capability_builder = FakeCapabilityBuilder()
    coordinator = AgentCoordinator(
        context=object(),
        capability_builder=capability_builder,
        artifact_service=FakeArtifactService(),
    )

    async def fake_run_llm_task(
        task: AgentTask,
        agent: AgentSpec | None,
        provider_id: str,
        event: Any = None,
        is_admin: bool = False,
    ) -> tuple[str, list[str]]:
        """返回固定的 llm 降级结果。"""

        del task
        del agent
        del provider_id
        del event
        del is_admin
        return "llm-output", ["main.py"]

    coordinator._run_llm_task = fake_run_llm_task  # type: ignore[method-assign]
    task = make_task("task-1", "执行代码", "execute_code", "帮我写一个网站")

    result = await coordinator._run_task(
        task=task,
        agent_map={"code": make_agent()},
        event=object(),
        is_admin=True,
        provider_id="provider-1",
    )

    assert result.status == "completed"
    assert result.output == "llm-output"
    assert result.created_files == ["main.py"]
    assert capability_builder.execute_code_calls == []


@pytest.mark.asyncio
async def test_agent_coordinator_run_llm_task_warns_non_admin_when_code_detected(
    fake_context: "FakeContext",
) -> None:
    """非管理员检测到代码时应只追加提示而不写文件。"""

    fake_context.queue_response('''```python:main.py
print("ok")
```''')
    artifact_service = FakeArtifactService(written_files=["/workspace/project_1/main.py"])
    coordinator = AgentCoordinator(
        context=fake_context,
        capability_builder=FakeCapabilityBuilder(executor=object()),
        artifact_service=artifact_service,
    )

    output_text, created_files = await coordinator._run_llm_task(
        task=make_task("task-1", "生成代码", "llm", "请写一个程序"),
        agent=make_agent(),
        provider_id="provider-1",
        event=object(),
        is_admin=False,
    )

    assert created_files == []
    assert "代码不会被自动写入文件系统" in output_text
    assert artifact_service.write_calls == []


@pytest.mark.asyncio
async def test_agent_coordinator_run_llm_task_writes_files_for_admin(
    fake_context: "FakeContext",
) -> None:
    """管理员上下文检测到代码时应写入工作区并记录文件。"""

    fake_context.queue_response('''```python:main.py
print("ok")
```''')
    artifact_service = FakeArtifactService(written_files=["/workspace/project_1/main.py"])
    coordinator = AgentCoordinator(
        context=fake_context,
        capability_builder=FakeCapabilityBuilder(executor=object()),
        artifact_service=artifact_service,
    )

    output_text, created_files = await coordinator._run_llm_task(
        task=make_task("task-1", "生成代码", "llm", "请写一个程序"),
        agent=make_agent(),
        provider_id="provider-1",
        event=object(),
        is_admin=True,
    )

    assert created_files == ["/workspace/project_1/main.py"]
    assert coordinator.all_created_files == ["/workspace/project_1/main.py"]
    assert coordinator._all_task_outputs == ['''```python:main.py
print("ok")
```''']
    assert "📁 **已创建文件:**" in output_text
    assert len(artifact_service.write_calls) == 1


@pytest.mark.asyncio
async def test_agent_coordinator_execute_renders_completed_file_task(
    fake_context: "FakeContext",
) -> None:
    """端到端执行应在最终回答中包含创建文件信息。"""

    fake_context.queue_response('''```python:main.py
print("ok")
```''')
    artifact_service = FakeArtifactService(written_files=["/workspace/project_1/main.py"])
    coordinator = AgentCoordinator(
        context=fake_context,
        capability_builder=FakeCapabilityBuilder(executor=object()),
        artifact_service=artifact_service,
    )
    agent = make_agent()
    task = make_task("task-1", "生成代码", "llm", "请写一个程序")
    plan = TaskPlan(agents=[agent], tasks=[task], summary="")

    result = await coordinator.execute(
        plan=plan,
        agents=[agent],
        event=object(),
        is_admin=True,
        provider_id="provider-1",
    )

    assert result["status"] == "success"
    assert "📁 **任务文件:**" in result["answer"]
    assert "📁 **编程完成！已创建文件:**" in result["answer"]


@pytest.mark.asyncio
async def test_agent_coordinator_execute_handles_timeout_and_unmet_dependencies(
    caplog: "LogCaptureFixture",
) -> None:
    """执行流程应覆盖超时、依赖无法满足与调试日志分支。"""

    capability_builder = FakeCapabilityBuilder()
    coordinator = AgentCoordinator(
        context=object(),
        capability_builder=capability_builder,
        config={"agent_timeout": 0.01, "debug_mode": True},
        artifact_service=FakeArtifactService(),
    )
    agent = make_agent()
    slow_task = make_task("task-1", "慢任务", "llm", "slow")
    blocked_task = make_task("task-2", "依赖任务", "llm", "wait")
    blocked_task.depends_on = ["missing-task"]
    plan = TaskPlan(agents=[agent], tasks=[slow_task, blocked_task], summary="")

    async def slow_run_task(
        task: AgentTask,
        agent_map: dict[str, AgentSpec],
        event: Any,
        is_admin: bool,
        provider_id: str,
    ) -> TaskResult:
        """模拟一个会超时的任务。"""

        del task, agent_map, event, is_admin, provider_id
        await asyncio.sleep(0.05)
        return TaskResult(task_id="task-1", status="completed", output="done")

    coordinator._run_task = slow_run_task  # type: ignore[method-assign]

    with caplog.at_level(logging.INFO):
        result = await coordinator.execute(
            plan=plan,
            agents=[agent],
            event=object(),
            is_admin=True,
            provider_id="provider-1",
        )

    assert result["status"] == "partial"
    assert "❌ 慢任务: 任务执行超时" in result["answer"]
    assert "⚠️ 依赖任务: 未执行" in result["answer"]
    assert "SubAgent 任务准备执行: task-1" in caplog.text
    assert "任务依赖无法满足，终止执行" in caplog.text


@pytest.mark.asyncio
async def test_agent_coordinator_run_task_covers_admin_actions_and_failure_logging(
    monkeypatch: pytest.MonkeyPatch,
    caplog: "LogCaptureFixture",
) -> None:
    """管理员动作分支、调试日志与异常兜底都应被覆盖。"""

    capability_builder = FakeCapabilityBuilder()
    coordinator = AgentCoordinator(
        context=object(),
        capability_builder=capability_builder,
        config={"debug_mode": True},
        artifact_service=FakeArtifactService(),
    )
    agent_map = {"code": make_agent()}

    with caplog.at_level(logging.INFO):
        create_result = await coordinator._run_task(
            task=make_task("task-create", "创建 Skill", "create_skill", "生成 skill"),
            agent_map=agent_map,
            event=object(),
            is_admin=True,
            provider_id="provider-1",
        )

    config_task = make_task("task-config", "配置 MCP", "config_mcp", "配置 search")
    config_task.params = {"url": "https://example.com"}
    config_skip = await coordinator._run_task(
        task=config_task,
        agent_map=agent_map,
        event=object(),
        is_admin=False,
        provider_id="provider-1",
    )
    config_done = await coordinator._run_task(
        task=config_task,
        agent_map=agent_map,
        event=object(),
        is_admin=True,
        provider_id="provider-1",
    )

    execute_task = make_task("task-exec", "执行命令", "execute_code", "python main.py")
    execute_skip = await coordinator._run_task(
        task=execute_task,
        agent_map=agent_map,
        event=object(),
        is_admin=False,
        provider_id="provider-1",
    )
    execute_done = await coordinator._run_task(
        task=execute_task,
        agent_map=agent_map,
        event=object(),
        is_admin=True,
        provider_id="provider-1",
    )

    async def raise_build_skill(task_description: str, provider_id: str) -> str:
        """模拟能力构建器抛出异常。"""

        del task_description, provider_id
        raise RuntimeError("boom")

    monkeypatch.setattr(capability_builder, "build_skill", raise_build_skill)
    failed_result = await coordinator._run_task(
        task=make_task("task-fail", "失败任务", "create_skill", "生成 skill"),
        agent_map=agent_map,
        event=object(),
        is_admin=True,
        provider_id="provider-1",
    )

    assert create_result.status == "completed"
    assert create_result.output == "skill-created"
    assert config_skip.status == "skipped"
    assert config_skip.output == "需要管理员权限才能配置 MCP"
    assert config_done.output == "mcp-configured"
    assert execute_skip.status == "skipped"
    assert execute_skip.output == "需要管理员权限"
    assert execute_done.output == "code-executed"
    assert failed_result.status == "failed"
    assert failed_result.error == "boom"
    assert capability_builder.configure_mcp_calls[0]["params"] == {"url": "https://example.com"}
    assert capability_builder.execute_code_calls[0]["code"] == "python main.py"
    assert "执行任务 task-create" in caplog.text
    assert "任务 task-create 执行完成" in caplog.text


def test_agent_coordinator_is_natural_language_covers_shell_and_text_variants() -> None:
    """自然语言检测应正确区分 shell 命令与描述性文本。"""

    assert AgentCoordinator._is_natural_language("") is False
    assert AgentCoordinator._is_natural_language("   ") is False
    assert AgentCoordinator._is_natural_language("pip install astrbot") is False
    assert AgentCoordinator._is_natural_language("NAME=value python app.py") is False
    assert AgentCoordinator._is_natural_language("| grep hello") is False
    assert AgentCoordinator._is_natural_language("#!/bin/bash") is False
    assert AgentCoordinator._is_natural_language("帮我写一个网站") is True
    assert (
        AgentCoordinator._is_natural_language(
            "Please design a complete web application with login page dashboard settings and profile support"
        )
        is True
    )
    assert (
        AgentCoordinator._is_natural_language(
            "Please design a complete web application with login | dashboard settings and profile support"
        )
        is False
    )
    assert AgentCoordinator._is_natural_language("build website") is False


@pytest.mark.asyncio
async def test_agent_coordinator_run_llm_task_uses_shared_context_and_default_system_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM 任务应拼接共享上下文，并在缺少 agent 时使用默认系统提示。"""

    context = RecordingContext(["plain response"])
    coordinator = AgentCoordinator(
        context=context,
        capability_builder=FakeCapabilityBuilder(executor=object()),
        artifact_service=FakeArtifactService(),
    )
    coordinator.bus.publish("planner", "任务拆分完成")
    monkeypatch.setattr(coordinator.code_extractor, "should_save_code", lambda text: False)
    monkeypatch.setattr(coordinator.code_extractor, "extract_code_blocks", lambda text: [])

    output_text, created_files = await coordinator._run_llm_task(
        task=make_task("task-1", "普通问答", "llm", "请总结一下"),
        agent=None,
        provider_id="provider-1",
        event=None,
        is_admin=False,
    )

    assert output_text == "plain response"
    assert created_files == []
    assert len(context.calls) == 1
    assert context.calls[0]["prompt"].startswith("共享上下文消息：")
    assert "\n\n任务: 请总结一下" in context.calls[0]["prompt"]
    assert context.calls[0]["system_prompt"].startswith("你是一个智能助手。")


@pytest.mark.asyncio
async def test_agent_coordinator_run_llm_task_logs_write_edge_cases(
    monkeypatch: pytest.MonkeyPatch,
    caplog: "LogCaptureFixture",
) -> None:
    """LLM 写文件流程应覆盖提取为空、执行器缺失与空写入分支。"""

    extract_empty_context = RecordingContext(['''```python:main.py
print("ok")
```'''])
    extract_empty = AgentCoordinator(
        context=extract_empty_context,
        capability_builder=FakeCapabilityBuilder(executor=object()),
        artifact_service=FakeArtifactService(),
    )
    monkeypatch.setattr(extract_empty.code_extractor, "should_save_code", lambda text: True)
    monkeypatch.setattr(extract_empty.code_extractor, "extract_code_blocks", lambda text: ["block"])
    monkeypatch.setattr(extract_empty.code_extractor, "extract_web_project", lambda text: {})

    with caplog.at_level(logging.WARNING):
        output_text, created_files = await extract_empty._run_llm_task(
            task=make_task("task-empty", "生成代码", "llm", "请写一个程序"),
            agent=make_agent(),
            provider_id="provider-1",
            event=object(),
            is_admin=True,
        )

    assert output_text.startswith("```python:main.py")
    assert created_files == []
    assert "代码提取结果为空" in caplog.text

    missing_executor_context = RecordingContext(['''```python:main.py
print("ok")
```'''])
    missing_executor = AgentCoordinator(
        context=missing_executor_context,
        capability_builder=FakeCapabilityBuilder(executor=None),
        artifact_service=FakeArtifactService(),
    )
    monkeypatch.setattr(missing_executor.code_extractor, "should_save_code", lambda text: True)
    monkeypatch.setattr(
        missing_executor.code_extractor,
        "extract_code_blocks",
        lambda text: ["block"],
    )
    monkeypatch.setattr(
        missing_executor.code_extractor,
        "extract_web_project",
        lambda text: {"main.py": "print('ok')"},
    )

    with caplog.at_level(logging.WARNING):
        await missing_executor._run_llm_task(
            task=make_task("task-no-executor", "生成代码", "llm", "请写一个程序"),
            agent=make_agent(),
            provider_id="provider-1",
            event=object(),
            is_admin=True,
        )

    assert "执行器不可用，无法写入文件" in caplog.text

    empty_write_context = RecordingContext(['''```python:main.py
print("ok")
```'''])
    empty_write_artifact = FakeArtifactService(written_files=[])
    empty_write = AgentCoordinator(
        context=empty_write_context,
        capability_builder=FakeCapabilityBuilder(executor=object()),
        artifact_service=empty_write_artifact,
    )
    monkeypatch.setattr(empty_write.code_extractor, "should_save_code", lambda text: True)
    monkeypatch.setattr(empty_write.code_extractor, "extract_code_blocks", lambda text: ["block"])
    monkeypatch.setattr(
        empty_write.code_extractor,
        "extract_web_project",
        lambda text: {"main.py": "print('ok')"},
    )

    with caplog.at_level(logging.WARNING):
        await empty_write._run_llm_task(
            task=make_task("task-empty-write", "生成代码", "llm", "请写一个程序"),
            agent=make_agent(),
            provider_id="provider-1",
            event=object(),
            is_admin=True,
        )

    assert len(empty_write_artifact.write_calls) == 1
    assert "文件写入失败或无文件" in caplog.text


@pytest.mark.asyncio
async def test_agent_coordinator_run_llm_task_reraises_llm_failures(
    caplog: "LogCaptureFixture",
) -> None:
    """LLM 调用失败时应记录日志并继续向上抛出异常。"""

    coordinator = AgentCoordinator(
        context=RecordingContext(error=RuntimeError("llm down")),
        capability_builder=FakeCapabilityBuilder(executor=object()),
        artifact_service=FakeArtifactService(),
    )

    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError, match="llm down"):
        await coordinator._run_llm_task(
            task=make_task("task-error", "生成代码", "llm", "请写一个程序"),
            agent=make_agent(),
            provider_id="provider-1",
            event=object(),
            is_admin=True,
        )

    assert "LLM 调用失败: task=task-error, error=llm down" in caplog.text


def test_agent_coordinator_strip_code_blocks_covers_all_placeholder_variants() -> None:
    """代码块剥离应覆盖文件名、语言名和无元信息三种占位文本。"""

    with_filename = AgentCoordinator._strip_code_blocks(
        "```python:main.py\nprint('ok')\n```"
    )
    with_language = AgentCoordinator._strip_code_blocks("```python \n```")
    without_meta = AgentCoordinator._strip_code_blocks("```\n```")

    assert with_filename == "📄 `main.py` (代码已保存到文件)"
    assert with_language == "📄 `python` 代码块 (已保存到文件)"
    assert without_meta == "📄 代码块 (已保存到文件)"


def test_agent_coordinator_build_response_covers_non_verbose_paths() -> None:
    """非调试模式的汇总应覆盖截断、文件提示、跳过、失败和未执行分支。"""

    coordinator = AgentCoordinator(
        context=object(),
        capability_builder=FakeCapabilityBuilder(),
        artifact_service=FakeArtifactService(),
    )
    long_output = (
        "A" * 780
        + "\n```python:main.py\nprint('ok')\n```"
        + "\n\n📁 **已创建文件:**\n  - /workspace/project_1/main.py"
    )
    tasks = [
        make_task("task-1", "普通输出任务", "llm", "input"),
        make_task("task-2", "带文件输出任务", "llm", "input"),
        make_task("task-3", "空输出文件任务", "llm", "input"),
        make_task("task-4", "跳过任务", "llm", "input"),
        make_task("task-5", "失败任务", "llm", "input"),
        make_task("task-6", "未执行任务", "llm", "input"),
    ]
    results = {
        "task-1": TaskResult(task_id="task-1", status="completed", output="short output"),
        "task-2": TaskResult(
            task_id="task-2",
            status="completed",
            output=long_output,
            created_files=["/workspace/project_1/main.py"],
        ),
        "task-3": TaskResult(
            task_id="task-3",
            status="completed",
            output="",
            created_files=["/workspace/project_1/empty.py"],
        ),
        "task-4": TaskResult(task_id="task-4", status="skipped", output=""),
        "task-5": TaskResult(task_id="task-5", status="failed", output="", error=None),
    }

    response = coordinator._build_response(
        plan=TaskPlan(agents=[make_agent()], tasks=tasks, summary=""),
        results=results,
        agents=[make_agent()],
    )

    assert response["status"] == "partial"
    assert "✅ 普通输出任务" in response["answer"]
    assert "short output" in response["answer"]
    assert "```python:main.py" not in response["answer"]
    assert "\n..." in response["answer"]
    assert "📁 **已创建文件:**" in response["answer"]
    assert "📁 **任务文件:**" in response["answer"]
    assert "⏭️ 跳过任务: 已跳过" in response["answer"]
    assert "❌ 失败任务: 失败" in response["answer"]
    assert "⚠️ 未执行任务: 未执行" in response["answer"]
    assert "⚠️ 注意：本次任务未检测到需要保存的代码文件" in response["answer"]


def test_agent_coordinator_build_response_covers_verbose_output_and_file_summary() -> None:
    """调试模式汇总应直接展示原始输出并追加文件总览。"""

    coordinator = AgentCoordinator(
        context=object(),
        capability_builder=FakeCapabilityBuilder(),
        config={"debug_mode": True},
        artifact_service=FakeArtifactService(),
    )
    coordinator.all_created_files = ["/workspace/project_1/main.py"]
    response = coordinator._build_response(
        plan=TaskPlan(
            agents=[make_agent()],
            tasks=[make_task("task-1", "调试任务", "llm", "input")],
            summary="",
        ),
        results={
            "task-1": TaskResult(
                task_id="task-1",
                status="completed",
                output="full verbose output",
            )
        },
        agents=[make_agent()],
    )

    assert response["status"] == "success"
    assert "full verbose output" in response["answer"]
    assert "📁 **编程完成！已创建文件:**" in response["answer"]
    assert "💡 文件已保存到沙盒的 /workspace/ 目录" in response["answer"]
