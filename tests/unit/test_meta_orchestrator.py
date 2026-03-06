"""MetaOrchestrator 单元测试。"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from astrbot_orchestrator_v5.orchestrator.agent_templates import AgentSpec
from astrbot_orchestrator_v5.orchestrator.meta_orchestrator import MetaOrchestrator
from astrbot_orchestrator_v5.orchestrator.task_analyzer import TaskPlan

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture
    from _pytest.fixtures import FixtureRequest
    from _pytest.logging import LogCaptureFixture
    from _pytest.monkeypatch import MonkeyPatch
    from pytest_mock.plugin import MockerFixture

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


class FakeTaskAnalyzer:
    """返回固定计划的分析器替身。"""

    def __init__(self, plan: TaskPlan) -> None:
        """保存预置计划。"""

        self.plan = plan
        self.calls: list[tuple[str, str]] = []

    async def analyze(self, request: str, provider_id: str) -> TaskPlan:
        """记录分析调用并返回固定计划。"""

        self.calls.append((request, provider_id))
        return self.plan


class FakeAgentManager:
    """记录创建与清理的 AgentManager 替身。"""

    def __init__(self, created_agents: list[AgentSpec]) -> None:
        """保存创建结果。"""

        self.created_agents = created_agents
        self.create_calls: list[list[AgentSpec]] = []
        self.cleanup_calls: list[list[AgentSpec]] = []

    async def create_agents(self, agents: list[AgentSpec]) -> list[AgentSpec]:
        """记录创建调用并返回预置列表。"""

        self.create_calls.append(agents)
        return self.created_agents

    async def cleanup(self, agents: list[AgentSpec]) -> None:
        """记录清理调用。"""

        self.cleanup_calls.append(agents)

    def list_agents(self) -> str:
        """返回固定状态文本。"""

        return "ok"


class FakeCoordinator:
    """返回固定执行结果的协调器替身。"""

    def __init__(self, result: dict[str, Any], executor: Any = None) -> None:
        """保存执行结果与执行器。"""

        self.result = result
        self.execute_calls: list[dict[str, Any]] = []
        self.capability_builder = SimpleNamespace(executor=executor)

    async def execute(
        self,
        plan: TaskPlan,
        agents: list[AgentSpec],
        event: Any,
        is_admin: bool,
        provider_id: str,
    ) -> dict[str, Any]:
        """记录调用并返回执行结果副本。"""

        self.execute_calls.append(
            {
                "plan": plan,
                "agents": agents,
                "event": event,
                "is_admin": is_admin,
                "provider_id": provider_id,
            }
        )
        return dict(self.result)


class FakeArtifactService:
    """可配置行为的 ArtifactService 替身。"""

    def __init__(self) -> None:
        """初始化默认返回值。"""

        self.persist_result_value: dict[str, Any] = {
            "success": True,
            "saved_files": [],
            "path": "",
            "total": 0,
        }
        self.export_result_value: dict[str, Any] = {
            "success": True,
            "saved_files": [],
            "path": "",
            "total": 0,
        }
        self.combined_text: str = ""
        self.should_save: bool = False
        self.code_block_count: int = 0
        self.written_files: list[str] = []
        self.persist_calls: list[tuple[dict[str, Any], str]] = []
        self.export_calls: list[dict[str, Any]] = []
        self.write_calls: list[dict[str, Any]] = []

    def collect_output_text(self, result: dict[str, Any]) -> str:
        """返回预置合并文本。"""

        del result
        return self.combined_text

    def should_save_output_text(self, text: str) -> bool:
        """返回预置保存判断。"""

        del text
        return self.should_save

    def count_code_blocks(self, text: str) -> int:
        """返回预置代码块数量。"""

        del text
        return self.code_block_count

    async def write_output_to_workspace(
        self,
        output_text: str,
        executor: Any,
        event: Any,
        project_name: str,
        base_path: str = "/workspace",
    ) -> list[str]:
        """记录工作区写入调用。"""

        self.write_calls.append(
            {
                "output_text": output_text,
                "executor": executor,
                "event": event,
                "project_name": project_name,
                "base_path": base_path,
            }
        )
        return list(self.written_files)

    def persist_result(self, result: dict[str, Any], project_name: str) -> dict[str, Any]:
        """记录持久化调用。"""

        self.persist_calls.append((result, project_name))
        return dict(self.persist_result_value)

    async def export_sandbox_files(
        self,
        executor: Any,
        event: Any,
        project_name: str,
        created_files: list[str],
    ) -> dict[str, Any]:
        """记录导出调用。"""

        self.export_calls.append(
            {
                "executor": executor,
                "event": event,
                "project_name": project_name,
                "created_files": created_files,
            }
        )
        return dict(self.export_result_value)


class FakeLlmContext:
    """记录 LLM 调用并返回预置结果。"""

    def __init__(
        self,
        completion_text: str = "",
        error: Exception | None = None,
    ) -> None:
        """保存预置返回文本或异常。"""

        self.completion_text = completion_text
        self.error = error
        self.calls: list[dict[str, str]] = []

    async def llm_generate(
        self,
        chat_provider_id: str,
        prompt: str,
        system_prompt: str,
    ) -> Any:
        """记录 LLM 调用。"""

        self.calls.append(
            {
                "chat_provider_id": chat_provider_id,
                "prompt": prompt,
                "system_prompt": system_prompt,
            }
        )
        if self.error is not None:
            raise self.error
        return SimpleNamespace(completion_text=self.completion_text)


@pytest.mark.asyncio
async def test_meta_orchestrator_non_admin_skips_persistence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """非管理员流程应跳过本地持久化并保留只读提示。"""

    agent = make_agent()
    plan = TaskPlan(agents=[agent], tasks=[], summary="任务摘要")
    analyzer = FakeTaskAnalyzer(plan)
    manager = FakeAgentManager([agent])
    coordinator = FakeCoordinator(
        {
            "status": "success",
            "answer": "执行完成",
            "created_files": [],
            "_all_task_outputs": [],
        }
    )
    artifact_service = FakeArtifactService()
    monkeypatch.setattr(MetaOrchestrator, "PERSIST_DIR", str(tmp_path))

    orchestrator = MetaOrchestrator(
        context=SimpleNamespace(),
        task_analyzer=analyzer,
        agent_manager=manager,
        coordinator=coordinator,
        artifact_service=artifact_service,
    )

    result = await orchestrator.process("做点什么", "provider-1", event=object(), is_admin=False)

    assert "任务摘要" in result["answer"]
    assert "非管理员请求不会自动写入或持久化文件" in result["answer"]
    assert artifact_service.persist_calls == []
    assert artifact_service.export_calls == []
    assert len(manager.cleanup_calls) == 1


@pytest.mark.asyncio
async def test_meta_orchestrator_admin_prefers_persist_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """管理员流程在本地持久化成功时不应再走沙盒导出。"""

    agent = make_agent()
    plan = TaskPlan(agents=[agent], tasks=[], summary="总结")
    analyzer = FakeTaskAnalyzer(plan)
    manager = FakeAgentManager([agent])
    coordinator = FakeCoordinator(
        {
            "status": "success",
            "answer": "执行完成",
            "created_files": ["/workspace/project_1/main.py"],
            "_all_task_outputs": [],
        }
    )
    artifact_service = FakeArtifactService()
    artifact_service.persist_result_value = {
        "success": True,
        "saved_files": ["main.py"],
        "path": "/tmp/export-project",
        "total": 1,
    }
    monkeypatch.setattr(MetaOrchestrator, "PERSIST_DIR", str(tmp_path))

    orchestrator = MetaOrchestrator(
        context=SimpleNamespace(),
        task_analyzer=analyzer,
        agent_manager=manager,
        coordinator=coordinator,
        artifact_service=artifact_service,
    )

    result = await orchestrator.process("生成项目", "provider-1", event=object(), is_admin=True)

    assert result["export_path"] == "/tmp/export-project"
    assert "文件已持久化保存" in result["answer"]
    assert "`main.py` → `/tmp/export-project/main.py`" in result["answer"]
    assert len(artifact_service.persist_calls) == 1
    assert artifact_service.export_calls == []


@pytest.mark.asyncio
async def test_meta_orchestrator_admin_falls_back_to_export(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """本地未持久化出文件时应回退到沙盒导出。"""

    agent = make_agent()
    plan = TaskPlan(agents=[agent], tasks=[], summary="")
    analyzer = FakeTaskAnalyzer(plan)
    manager = FakeAgentManager([agent])
    coordinator = FakeCoordinator(
        {
            "status": "success",
            "answer": "执行完成",
            "created_files": ["/workspace/project_1/main.py"],
            "_all_task_outputs": [],
        },
        executor=object(),
    )
    artifact_service = FakeArtifactService()
    artifact_service.export_result_value = {
        "success": True,
        "saved_files": ["main.py"],
        "path": "/tmp/export-fallback",
        "total": 1,
    }
    monkeypatch.setattr(MetaOrchestrator, "PERSIST_DIR", str(tmp_path))

    orchestrator = MetaOrchestrator(
        context=SimpleNamespace(),
        task_analyzer=analyzer,
        agent_manager=manager,
        coordinator=coordinator,
        artifact_service=artifact_service,
    )

    result = await orchestrator.process("生成项目", "provider-1", event=object(), is_admin=True)

    assert result["export_path"] == "/tmp/export-fallback"
    assert len(artifact_service.persist_calls) == 1
    assert len(artifact_service.export_calls) == 1
    assert "`main.py` → `/tmp/export-fallback/main.py`" in result["answer"]


@pytest.mark.asyncio
async def test_meta_orchestrator_fallback_extract_code_writes_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """兜底提取检测到代码时应委托 ArtifactService 写入工作区。"""

    agent = make_agent()
    analyzer = FakeTaskAnalyzer(TaskPlan(agents=[agent], tasks=[]))
    manager = FakeAgentManager([agent])
    coordinator = FakeCoordinator({}, executor=object())
    artifact_service = FakeArtifactService()
    artifact_service.combined_text = '```python:main.py\nprint("ok")\n```'
    artifact_service.should_save = True
    artifact_service.code_block_count = 1
    artifact_service.written_files = ["/workspace/project_1/main.py"]
    monkeypatch.setattr(MetaOrchestrator, "PERSIST_DIR", str(tmp_path))

    orchestrator = MetaOrchestrator(
        context=SimpleNamespace(),
        task_analyzer=analyzer,
        agent_manager=manager,
        coordinator=coordinator,
        artifact_service=artifact_service,
    )

    created_files = await orchestrator._fallback_extract_code(
        result={"answer": "", "_all_task_outputs": []},
        event=object(),
        provider_id="provider-1",
    )

    assert created_files == ["/workspace/project_1/main.py"]
    assert len(artifact_service.write_calls) == 1


@pytest.mark.asyncio
async def test_meta_orchestrator_non_admin_can_skip_cleanup_and_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """非管理员只读流程应覆盖无摘要且禁用清理的分支。"""

    agent = make_agent()
    analyzer = FakeTaskAnalyzer(TaskPlan(agents=[agent], tasks=[], summary=""))
    manager = FakeAgentManager([agent])
    coordinator = FakeCoordinator(
        {
            "status": "success",
            "answer": "执行完成",
            "created_files": [],
            "_all_task_outputs": [],
        }
    )
    artifact_service = FakeArtifactService()
    monkeypatch.setattr(MetaOrchestrator, "PERSIST_DIR", str(tmp_path))

    orchestrator = MetaOrchestrator(
        context=SimpleNamespace(),
        task_analyzer=analyzer,
        agent_manager=manager,
        coordinator=coordinator,
        config={"auto_cleanup_agents": False},
        artifact_service=artifact_service,
    )

    result = await orchestrator.process("只读请求", "provider-1", event=object(), is_admin=False)

    assert result["answer"] == "执行完成\n\n⚠️ 非管理员请求不会自动写入或持久化文件。"
    assert manager.cleanup_calls == []


@pytest.mark.asyncio
async def test_meta_orchestrator_admin_uses_fallback_extract_and_warns_when_export_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """管理员流程应覆盖兜底提取、导出失败警告与无清理分支。"""

    agent = make_agent()
    analyzer = FakeTaskAnalyzer(TaskPlan(agents=[agent], tasks=[], summary=""))
    manager = FakeAgentManager([agent])
    coordinator = FakeCoordinator(
        {
            "status": "success",
            "answer": "执行完成",
            "created_files": [],
            "_all_task_outputs": [],
        },
        executor=object(),
    )
    artifact_service = FakeArtifactService()
    artifact_service.persist_result_value = {
        "success": True,
        "saved_files": [],
        "path": "",
        "total": 0,
    }
    artifact_service.export_result_value = {
        "success": False,
        "saved_files": [],
        "path": "",
        "total": 0,
    }
    monkeypatch.setattr(MetaOrchestrator, "PERSIST_DIR", str(tmp_path))

    orchestrator = MetaOrchestrator(
        context=SimpleNamespace(),
        task_analyzer=analyzer,
        agent_manager=manager,
        coordinator=coordinator,
        config={"auto_cleanup_agents": False},
        artifact_service=artifact_service,
    )

    async def fake_fallback_extract(
        result: dict[str, Any],
        event: Any,
        provider_id: str,
    ) -> list[str]:
        """返回兜底提取出来的文件列表。"""

        del result, event, provider_id
        return ["/workspace/project_1/main.py"]

    monkeypatch.setattr(orchestrator, "_fallback_extract_code", fake_fallback_extract)

    with caplog.at_level(logging.WARNING):
        result = await orchestrator.process("生成项目", "provider-1", event=object(), is_admin=True)

    assert "已创建文件（兜底提取）" in result["answer"]
    assert "/workspace/project_1/main.py" in result["answer"]
    assert result["created_files"] == ["/workspace/project_1/main.py"]
    assert "没有文件被保存" in caplog.text
    assert manager.cleanup_calls == []
    assert len(artifact_service.export_calls) == 1
    assert "export_path" not in result


@pytest.mark.asyncio
async def test_meta_orchestrator_admin_can_continue_without_fallback_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """管理员流程在兜底提取失败时仍应继续后续持久化。"""

    agent = make_agent()
    analyzer = FakeTaskAnalyzer(TaskPlan(agents=[agent], tasks=[], summary=""))
    manager = FakeAgentManager([agent])
    coordinator = FakeCoordinator(
        {
            "status": "success",
            "answer": "执行完成",
            "created_files": [],
            "_all_task_outputs": [],
        }
    )
    artifact_service = FakeArtifactService()
    artifact_service.persist_result_value = {
        "success": True,
        "saved_files": ["main.py"],
        "path": "/tmp/export-project",
        "total": 1,
    }
    monkeypatch.setattr(MetaOrchestrator, "PERSIST_DIR", str(tmp_path))

    orchestrator = MetaOrchestrator(
        context=SimpleNamespace(),
        task_analyzer=analyzer,
        agent_manager=manager,
        coordinator=coordinator,
        config={"auto_cleanup_agents": False},
        artifact_service=artifact_service,
    )

    async def empty_fallback_extract(
        result: dict[str, Any],
        event: Any,
        provider_id: str,
    ) -> list[str]:
        """模拟兜底提取未找到任何文件。"""

        del result, event, provider_id
        return []

    monkeypatch.setattr(orchestrator, "_fallback_extract_code", empty_fallback_extract)

    result = await orchestrator.process("生成项目", "provider-1", event=object(), is_admin=True)

    assert "已创建文件（兜底提取）" not in result["answer"]
    assert result["export_path"] == "/tmp/export-project"


@pytest.mark.asyncio
async def test_meta_orchestrator_fallback_extract_regenerates_when_outputs_exist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """兜底提取在存在任务输出时应回退到重新生成。"""

    agent = make_agent()
    analyzer = FakeTaskAnalyzer(TaskPlan(agents=[agent], tasks=[]))
    manager = FakeAgentManager([agent])
    coordinator = FakeCoordinator({}, executor=object())
    artifact_service = FakeArtifactService()
    monkeypatch.setattr(MetaOrchestrator, "PERSIST_DIR", str(tmp_path))

    orchestrator = MetaOrchestrator(
        context=SimpleNamespace(),
        task_analyzer=analyzer,
        agent_manager=manager,
        coordinator=coordinator,
        artifact_service=artifact_service,
    )

    async def fake_regenerate(
        all_outputs: list[str],
        event: Any,
        provider_id: str,
    ) -> list[str]:
        """返回重新生成出的文件列表。"""

        del event, provider_id
        assert all_outputs == ["task output"]
        return ["main.py"]

    monkeypatch.setattr(orchestrator, "_regenerate_code", fake_regenerate)

    created_files = await orchestrator._fallback_extract_code(
        result={"answer": "", "_all_task_outputs": ["task output"]},
        event=object(),
        provider_id="provider-1",
    )

    assert created_files == ["main.py"]


@pytest.mark.asyncio
async def test_meta_orchestrator_fallback_extract_covers_strategy1_skip_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """兜底提取应覆盖不可保存、缺执行器和写空文件等分支。"""

    agent = make_agent()
    analyzer = FakeTaskAnalyzer(TaskPlan(agents=[agent], tasks=[]))
    manager = FakeAgentManager([agent])
    artifact_service = FakeArtifactService()
    monkeypatch.setattr(MetaOrchestrator, "PERSIST_DIR", str(tmp_path))

    non_savable = MetaOrchestrator(
        context=SimpleNamespace(),
        task_analyzer=analyzer,
        agent_manager=manager,
        coordinator=FakeCoordinator({}, executor=object()),
        artifact_service=artifact_service,
    )
    artifact_service.combined_text = "plain text"
    artifact_service.should_save = False
    artifact_service.code_block_count = 0
    artifact_service.written_files = []
    assert await non_savable._fallback_extract_code(
        result={"answer": "", "_all_task_outputs": []},
        event=object(),
        provider_id="provider-1",
    ) == []

    missing_executor = MetaOrchestrator(
        context=SimpleNamespace(),
        task_analyzer=analyzer,
        agent_manager=manager,
        coordinator=FakeCoordinator({}, executor=None),
        artifact_service=artifact_service,
    )
    artifact_service.combined_text = '```python:main.py\nprint("ok")\n```'
    artifact_service.should_save = True
    artifact_service.code_block_count = 1
    assert await missing_executor._fallback_extract_code(
        result={"answer": "", "_all_task_outputs": []},
        event=object(),
        provider_id="provider-1",
    ) == []

    empty_write = MetaOrchestrator(
        context=SimpleNamespace(),
        task_analyzer=analyzer,
        agent_manager=manager,
        coordinator=FakeCoordinator({}, executor=object()),
        artifact_service=artifact_service,
    )
    artifact_service.written_files = []
    assert await empty_write._fallback_extract_code(
        result={"answer": "", "_all_task_outputs": []},
        event=object(),
        provider_id="provider-1",
    ) == []
    assert len(artifact_service.write_calls) == 1


@pytest.mark.asyncio
async def test_meta_orchestrator_fallback_extract_logs_regenerate_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """重新生成失败时应记录 warning 并返回空列表。"""

    agent = make_agent()
    analyzer = FakeTaskAnalyzer(TaskPlan(agents=[agent], tasks=[]))
    manager = FakeAgentManager([agent])
    coordinator = FakeCoordinator({}, executor=object())
    artifact_service = FakeArtifactService()
    monkeypatch.setattr(MetaOrchestrator, "PERSIST_DIR", str(tmp_path))

    orchestrator = MetaOrchestrator(
        context=SimpleNamespace(),
        task_analyzer=analyzer,
        agent_manager=manager,
        coordinator=coordinator,
        artifact_service=artifact_service,
    )

    async def raise_regenerate(
        all_outputs: list[str],
        event: Any,
        provider_id: str,
    ) -> list[str]:
        """抛出重新生成异常。"""

        del all_outputs, event, provider_id
        raise RuntimeError("regen failed")

    monkeypatch.setattr(orchestrator, "_regenerate_code", raise_regenerate)

    with caplog.at_level(logging.WARNING):
        created_files = await orchestrator._fallback_extract_code(
            result={"answer": "", "_all_task_outputs": ["task output"]},
            event=object(),
            provider_id="provider-1",
        )

    assert created_files == []
    assert "兜底策略2失败: regen failed" in caplog.text


@pytest.mark.asyncio
async def test_meta_orchestrator_regenerate_code_truncates_context_and_writes_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """重新生成代码成功时应截断超长上下文并写入工作区。"""

    agent = make_agent()
    llm_context = FakeLlmContext('```python:main.py\nprint("ok")\n```')
    analyzer = FakeTaskAnalyzer(TaskPlan(agents=[agent], tasks=[]))
    manager = FakeAgentManager([agent])
    coordinator = FakeCoordinator({}, executor=object())
    artifact_service = FakeArtifactService()
    artifact_service.should_save = True
    artifact_service.written_files = ["/workspace/project_1/main.py"]
    monkeypatch.setattr(MetaOrchestrator, "PERSIST_DIR", str(tmp_path))

    orchestrator = MetaOrchestrator(
        context=llm_context,
        task_analyzer=analyzer,
        agent_manager=manager,
        coordinator=coordinator,
        artifact_service=artifact_service,
    )

    created_files = await orchestrator._regenerate_code(
        all_outputs=["x" * 3101],
        event=object(),
        provider_id="provider-1",
    )

    assert created_files == ["/workspace/project_1/main.py"]
    assert len(artifact_service.write_calls) == 1
    assert len(llm_context.calls) == 1
    assert "..." in llm_context.calls[0]["prompt"]
    assert llm_context.calls[0]["chat_provider_id"] == "provider-1"


@pytest.mark.asyncio
async def test_meta_orchestrator_regenerate_code_returns_empty_when_write_has_no_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """重新生成成功但写入为空时应返回空列表。"""

    agent = make_agent()
    analyzer = FakeTaskAnalyzer(TaskPlan(agents=[agent], tasks=[]))
    manager = FakeAgentManager([agent])
    artifact_service = FakeArtifactService()
    artifact_service.should_save = True
    artifact_service.written_files = []
    llm_context = FakeLlmContext('```python:main.py\nprint("ok")\n```')
    monkeypatch.setattr(MetaOrchestrator, "PERSIST_DIR", str(tmp_path))

    orchestrator = MetaOrchestrator(
        context=llm_context,
        task_analyzer=analyzer,
        agent_manager=manager,
        coordinator=FakeCoordinator({}, executor=object()),
        artifact_service=artifact_service,
    )

    assert await orchestrator._regenerate_code(["output"], object(), "provider-1") == []
    assert len(artifact_service.write_calls) == 1


@pytest.mark.asyncio
async def test_meta_orchestrator_regenerate_code_handles_no_save_missing_executor_and_llm_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """重新生成代码应覆盖不保存、执行器缺失与 LLM 失败分支。"""

    agent = make_agent()
    analyzer = FakeTaskAnalyzer(TaskPlan(agents=[agent], tasks=[]))
    manager = FakeAgentManager([agent])
    artifact_service = FakeArtifactService()
    monkeypatch.setattr(MetaOrchestrator, "PERSIST_DIR", str(tmp_path))

    no_save_context = FakeLlmContext('```python:main.py\nprint("ok")\n```')
    no_save_orchestrator = MetaOrchestrator(
        context=no_save_context,
        task_analyzer=analyzer,
        agent_manager=manager,
        coordinator=FakeCoordinator({}, executor=object()),
        artifact_service=artifact_service,
    )
    assert await no_save_orchestrator._regenerate_code(["output"], object(), "provider-1") == []

    artifact_service.should_save = True
    missing_executor_context = FakeLlmContext('```python:main.py\nprint("ok")\n```')
    missing_executor_orchestrator = MetaOrchestrator(
        context=missing_executor_context,
        task_analyzer=analyzer,
        agent_manager=manager,
        coordinator=FakeCoordinator({}, executor=None),
        artifact_service=artifact_service,
    )
    assert await missing_executor_orchestrator._regenerate_code(
        ["output"],
        object(),
        "provider-1",
    ) == []

    failing_context = FakeLlmContext(error=RuntimeError("llm down"))
    failing_orchestrator = MetaOrchestrator(
        context=failing_context,
        task_analyzer=analyzer,
        agent_manager=manager,
        coordinator=FakeCoordinator({}, executor=object()),
        artifact_service=artifact_service,
    )
    with caplog.at_level(logging.WARNING):
        assert await failing_orchestrator._regenerate_code(["output"], object(), "provider-1") == []

    assert "重新生成代码失败: llm down" in caplog.text
    assert artifact_service.write_calls == []


@pytest.mark.asyncio
async def test_meta_orchestrator_export_from_sandbox_and_status_cover_edges(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """沙盒导出应覆盖执行器缺失、异常回退和状态查询。"""

    agent = make_agent()
    analyzer = FakeTaskAnalyzer(TaskPlan(agents=[agent], tasks=[]))
    manager = FakeAgentManager([agent])
    coordinator = FakeCoordinator({}, executor=None)
    artifact_service = FakeArtifactService()
    monkeypatch.setattr(MetaOrchestrator, "PERSIST_DIR", str(tmp_path))

    orchestrator = MetaOrchestrator(
        context=SimpleNamespace(),
        task_analyzer=analyzer,
        agent_manager=manager,
        coordinator=coordinator,
        artifact_service=artifact_service,
    )

    missing_executor_result = await orchestrator._export_from_sandbox(
        created_files=["main.py"],
        event=object(),
        project_name="demo-project",
    )
    assert missing_executor_result == {"success": False, "error": "执行器不可用"}

    async def raise_export(
        *,
        executor: Any,
        event: Any,
        project_name: str,
        created_files: list[str],
    ) -> dict[str, Any]:
        """抛出导出异常。"""

        del executor, event, project_name, created_files
        raise RuntimeError("export failed")

    coordinator.capability_builder.executor = object()
    monkeypatch.setattr(artifact_service, "export_sandbox_files", raise_export)

    with caplog.at_level(logging.ERROR):
        error_result = await orchestrator._export_from_sandbox(
            created_files=["main.py"],
            event=object(),
            project_name="demo-project",
        )

    assert error_result == {"success": False, "error": "export failed"}
    assert "导出文件失败: export failed" in caplog.text
    assert orchestrator.status() == "ok"
