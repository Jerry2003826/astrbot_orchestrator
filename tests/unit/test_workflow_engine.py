"""WorkflowEngine 关键路径测试。"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

import astrbot_orchestrator_v5.workflow.engine as engine_module
from astrbot_orchestrator_v5.workflow.engine import WorkflowEngine
from astrbot_orchestrator_v5.workflow.nodes import (
    NodeStatus,
    NodeType,
    WorkflowDefinition,
    WorkflowNode,
    WorkflowState,
)

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


class FakeSkillLoader:
    """返回预设 Skill 内容的加载器替身。"""

    def __init__(self, skill_map: dict[str, str]) -> None:
        """保存 Skill 内容映射。"""

        self.skill_map = dict(skill_map)

    def get_skill_content(self, skill_name: str) -> str:
        """返回给定 Skill 的内容。"""

        return self.skill_map.get(skill_name, "")


class FakeMcpBridge:
    """记录 MCP 调用参数的桥接器替身。"""

    def __init__(self, result: Any) -> None:
        """保存固定返回值。"""

        self.result = result
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool_name: str, params: dict[str, Any]) -> Any:
        """记录工具调用并返回预设结果。"""

        self.calls.append((tool_name, dict(params)))
        return self.result


class RecordingContext:
    """记录 LLM 调用参数的上下文替身。"""

    def __init__(self, completion_text: str) -> None:
        """保存固定 LLM 返回文本。"""

        self.completion_text = completion_text
        self.calls: list[dict[str, Any]] = []

    async def llm_generate(self, **kwargs: Any) -> SimpleNamespace:
        """记录调用并返回固定响应。"""

        self.calls.append(kwargs)
        return SimpleNamespace(completion_text=self.completion_text)


class FakeWorkflowsPath:
    """用于模拟 workflows 目录路径的替身。"""

    def __init__(self, exists: bool, files: list[Path] | None = None) -> None:
        """保存目录是否存在及其中的 YAML 文件列表。"""

        self._exists = exists
        self._files = list(files or [])

    @property
    def parent(self) -> "FakeWorkflowsPath":
        """返回父路径本身，便于链式访问。"""

        return self

    def __truediv__(self, other: str) -> "FakeWorkflowsPath":
        """忽略子路径拼接并返回自身。"""

        del other
        return self

    def exists(self) -> bool:
        """返回目录是否存在。"""

        return self._exists

    def glob(self, pattern: str) -> list[Path]:
        """返回预设的 YAML 文件列表。"""

        del pattern
        return list(self._files)


def test_workflow_engine_loads_yaml_and_lists_workflows(tmp_path: Path) -> None:
    """YAML 工作流应能被加载、查询并出现在列表中。"""

    yaml_path = tmp_path / "demo.yaml"
    yaml_path.write_text(
        (
            "id: yaml_flow\n"
            "name: YAML Flow\n"
            "description: from yaml\n"
            "nodes:\n"
            "  - id: start\n"
            "    type: start\n"
        ),
        encoding="utf-8",
    )
    engine = WorkflowEngine(context=None)

    workflow_id = engine.load_from_yaml(str(yaml_path))
    workflows = engine.list_workflows()

    assert workflow_id == "yaml_flow"
    assert engine.get_workflow("yaml_flow") is not None
    assert {
        "id": "yaml_flow",
        "name": "YAML Flow",
        "description": "from yaml",
    } in workflows


def test_workflow_engine_load_workflows_handles_missing_directory(
    monkeypatch: "MonkeyPatch",
) -> None:
    """初始化时若 workflows 目录不存在，应直接跳过。"""

    fake_path = FakeWorkflowsPath(exists=False)
    monkeypatch.setattr(engine_module, "Path", lambda *_args, **_kwargs: fake_path)

    engine = WorkflowEngine(context=None)

    assert engine.list_workflows() == []


def test_workflow_engine_load_workflows_logs_yaml_failures(
    monkeypatch: "MonkeyPatch",
    caplog: "LogCaptureFixture",
) -> None:
    """自动加载单个 YAML 失败时应记录日志并继续。"""

    fake_path = FakeWorkflowsPath(exists=True, files=[Path("broken.yaml")])
    monkeypatch.setattr(engine_module, "Path", lambda *_args, **_kwargs: fake_path)

    def fail_load_from_yaml(self: WorkflowEngine, yaml_path: str) -> str:
        """模拟 YAML 加载失败。"""

        del yaml_path
        raise RuntimeError("boom")

    monkeypatch.setattr(WorkflowEngine, "load_from_yaml", fail_load_from_yaml)
    caplog.set_level(logging.ERROR)

    WorkflowEngine(context=None)

    assert "加载工作流失败 [broken.yaml]: boom" in caplog.text


def test_workflow_engine_load_from_yaml_rejects_invalid_definition(
    tmp_path: Path,
    monkeypatch: "MonkeyPatch",
) -> None:
    """非字典 YAML 内容应被拒绝。"""

    monkeypatch.setattr(WorkflowEngine, "_load_workflows", lambda self: None)
    yaml_path = tmp_path / "invalid.yaml"
    yaml_path.write_text("- item\n- item2\n", encoding="utf-8")
    engine = WorkflowEngine(context=None)

    with pytest.raises(ValueError, match="工作流 YAML 格式无效"):
        engine.load_from_yaml(str(yaml_path))


@pytest.mark.asyncio
async def test_workflow_engine_executes_agent_chain_and_persists_output(
    fake_context: "FakeContext",
) -> None:
    """Agent 工作流应串起 start、agent 与 end 节点。"""

    fake_context.queue_response("你好，AstrBot")
    engine = WorkflowEngine(context=fake_context)
    engine.workflows["agent_flow"] = WorkflowDefinition(
        id="agent_flow",
        name="agent_flow",
        nodes=[
            WorkflowNode(id="start", type=NodeType.START, next_nodes=["agent"]),
            WorkflowNode(
                id="agent",
                type=NodeType.AGENT,
                config={
                    "prompt": "你好，{name}",
                    "system_prompt": "你是一个助手",
                    "output_variable": "reply",
                },
                next_nodes=["end"],
            ),
            WorkflowNode(
                id="end",
                type=NodeType.END,
                config={"output_variable": "reply"},
            ),
        ],
    )

    state = await engine.execute(
        workflow_id="agent_flow",
        initial_input={"name": "AstrBot"},
        provider_id="provider-x",
    )

    assert state.status == NodeStatus.COMPLETED
    assert state.variables["reply"] == "你好，AstrBot"
    assert state.variables["_provider_id"] == "provider-x"
    assert state.node_results["agent"] == {"response": "你好，AstrBot"}
    assert state.node_status["start"] == NodeStatus.COMPLETED
    assert state.node_status["agent"] == NodeStatus.COMPLETED
    assert state.node_status["end"] == NodeStatus.COMPLETED


@pytest.mark.asyncio
async def test_workflow_engine_executes_skill_and_mcp_nodes() -> None:
    """Skill 与 MCP 节点应能解析变量并传递结果。"""

    mcp_bridge = FakeMcpBridge({"ok": True, "source": "mcp"})
    engine = WorkflowEngine(
        context=None,
        skill_loader=FakeSkillLoader({"weather": "晴天"}),
        mcp_bridge=mcp_bridge,
    )
    engine.workflows["tool_flow"] = WorkflowDefinition(
        id="tool_flow",
        name="tool_flow",
        nodes=[
            WorkflowNode(id="start", type=NodeType.START, next_nodes=["skill"]),
            WorkflowNode(
                id="skill",
                type=NodeType.SKILL,
                config={"skill": "weather"},
                next_nodes=["mcp"],
            ),
            WorkflowNode(
                id="mcp",
                type=NodeType.MCP,
                config={
                    "tool": "search_weather",
                    "parameters": {
                        "content": "$skill_weather",
                        "city": "{city}",
                    },
                    "output_variable": "tool_result",
                },
                next_nodes=["end"],
            ),
            WorkflowNode(
                id="end",
                type=NodeType.END,
                config={"output_variable": "tool_result"},
            ),
        ],
    )

    state = await engine.execute(
        workflow_id="tool_flow",
        initial_input={"city": "北京"},
        provider_id="provider-x",
    )

    assert state.status == NodeStatus.COMPLETED
    assert state.variables["skill_weather"] == "晴天"
    assert state.variables["tool_result"] == {"ok": True, "source": "mcp"}
    assert mcp_bridge.calls == [
        ("search_weather", {"content": "晴天", "city": "北京"})
    ]


@pytest.mark.asyncio
async def test_workflow_engine_unknown_node_and_missing_next_are_ignored(
    monkeypatch: "MonkeyPatch",
) -> None:
    """未知节点类型和不存在的 next 节点应平稳结束。"""

    monkeypatch.setattr(WorkflowEngine, "_load_workflows", lambda self: None)
    engine = WorkflowEngine(context=None)
    engine.workflows["mystery_flow"] = WorkflowDefinition(
        id="mystery_flow",
        name="mystery_flow",
        nodes=[
            WorkflowNode(id="start", type=NodeType.START, next_nodes=["mystery"]),
            WorkflowNode(
                id="mystery",
                type=cast(Any, "mystery"),
                next_nodes=["ghost"],
            ),
        ],
    )

    state = await engine.execute("mystery_flow")

    assert state.status == NodeStatus.COMPLETED
    assert state.node_results["mystery"] == {}
    assert state.node_status["mystery"] == NodeStatus.COMPLETED
    assert "ghost" not in state.node_status


@pytest.mark.asyncio
async def test_workflow_engine_executes_parallel_children_and_then_continues(
    fake_context: "FakeContext",
) -> None:
    """并行节点应执行所有子节点，并在结束后继续后续节点。"""

    fake_context.queue_response("并行响应")
    engine = WorkflowEngine(
        context=fake_context,
        skill_loader=FakeSkillLoader({"parallel_skill": "skill-content"}),
    )
    engine.workflows["parallel_flow"] = WorkflowDefinition(
        id="parallel_flow",
        name="parallel_flow",
        nodes=[
            WorkflowNode(id="start", type=NodeType.START, next_nodes=["parallel"]),
            WorkflowNode(
                id="parallel",
                type=NodeType.PARALLEL,
                config={"parallel_nodes": ["agent_branch", "skill_branch"]},
                next_nodes=["end"],
            ),
            WorkflowNode(
                id="agent_branch",
                type=NodeType.AGENT,
                config={"prompt": "hello", "output_variable": "agent_result"},
            ),
            WorkflowNode(
                id="skill_branch",
                type=NodeType.SKILL,
                config={"skill": "parallel_skill"},
            ),
            WorkflowNode(
                id="end",
                type=NodeType.END,
                config={"output_variable": "agent_result"},
            ),
        ],
    )

    state = await engine.execute("parallel_flow", provider_id="provider-x")

    assert state.status == NodeStatus.COMPLETED
    assert state.node_status["parallel"] == NodeStatus.COMPLETED
    assert state.node_status["agent_branch"] == NodeStatus.COMPLETED
    assert state.node_status["skill_branch"] == NodeStatus.COMPLETED
    assert state.node_status["end"] == NodeStatus.COMPLETED
    assert len(state.node_results["parallel"]["parallel_results"]) == 2


@pytest.mark.asyncio
async def test_workflow_engine_parallel_nodes_skip_missing_children(
    monkeypatch: "MonkeyPatch",
) -> None:
    """并行节点中不存在的子节点应被忽略。"""

    monkeypatch.setattr(WorkflowEngine, "_load_workflows", lambda self: None)
    engine = WorkflowEngine(context=None)
    workflow = WorkflowDefinition(
        id="parallel_flow",
        name="parallel_flow",
        nodes=[WorkflowNode(id="known", type=NodeType.START)],
    )
    state = WorkflowState(workflow_id="parallel_flow")
    node = WorkflowNode(
        id="parallel",
        type=NodeType.PARALLEL,
        config={"parallel_nodes": ["known", "missing"]},
    )

    result = await engine._execute_parallel_nodes(node, workflow, state)

    assert len(result["parallel_results"]) == 1
    assert state.node_status["known"] == NodeStatus.COMPLETED


@pytest.mark.asyncio
async def test_workflow_engine_condition_node_uses_false_branch() -> None:
    """条件节点为假时应走第二个 next 分支。"""

    engine = WorkflowEngine(context=None)
    engine.workflows["condition_flow"] = WorkflowDefinition(
        id="condition_flow",
        name="condition_flow",
        nodes=[
            WorkflowNode(id="start", type=NodeType.START, next_nodes=["cond"]),
            WorkflowNode(
                id="cond",
                type=NodeType.CONDITION,
                condition="enabled",
                next_nodes=["end_true", "end_false"],
            ),
            WorkflowNode(id="end_true", type=NodeType.END),
            WorkflowNode(id="end_false", type=NodeType.END),
        ],
    )

    state = await engine.execute(
        workflow_id="condition_flow",
        initial_input={"enabled": False},
    )

    assert state.status == NodeStatus.COMPLETED
    assert state.node_results["cond"] is False
    assert state.node_status["end_false"] == NodeStatus.COMPLETED
    assert "end_true" not in state.node_status


@pytest.mark.asyncio
async def test_workflow_engine_marks_failed_for_missing_skill_loader(
    monkeypatch: "MonkeyPatch",
) -> None:
    """节点执行异常时应把节点和工作流都标记为失败。"""

    monkeypatch.setattr(WorkflowEngine, "_load_workflows", lambda self: None)
    engine = WorkflowEngine(context=None)
    engine.workflows["broken_flow"] = WorkflowDefinition(
        id="broken_flow",
        name="broken_flow",
        nodes=[
            WorkflowNode(id="start", type=NodeType.START, next_nodes=["skill"]),
            WorkflowNode(id="skill", type=NodeType.SKILL, config={"skill": "calendar"}),
        ],
    )

    state = await engine.execute("broken_flow")

    assert state.status == NodeStatus.FAILED
    assert state.error == "Skill 加载器不可用"
    assert state.node_status["skill"] == NodeStatus.FAILED


@pytest.mark.asyncio
async def test_workflow_engine_marks_state_failed_when_start_node_missing() -> None:
    """缺少 start 节点时，工作流状态应标记为失败。"""

    engine = WorkflowEngine(context=None)
    engine.workflows["invalid_flow"] = WorkflowDefinition(
        id="invalid_flow",
        name="invalid_flow",
        nodes=[WorkflowNode(id="end", type=NodeType.END)],
    )

    state = await engine.execute("invalid_flow")

    assert state.status == NodeStatus.FAILED
    assert state.error == "工作流缺少起始节点"


@pytest.mark.asyncio
async def test_workflow_engine_raises_for_missing_workflow(
    monkeypatch: "MonkeyPatch",
) -> None:
    """执行不存在的工作流时应直接抛错。"""

    monkeypatch.setattr(WorkflowEngine, "_load_workflows", lambda self: None)
    engine = WorkflowEngine(context=None)

    with pytest.raises(ValueError, match="工作流不存在: missing_flow"):
        await engine.execute("missing_flow")


def test_workflow_engine_evaluates_safe_condition() -> None:
    """工作流条件应能正确处理白名单表达式。"""

    engine = WorkflowEngine(context=None)
    state = WorkflowState(variables={"enabled": True, "items": [1, 2]})
    node = WorkflowNode(id="cond", type=NodeType.CONDITION, condition="enabled and len(items) == 2")

    result = engine._evaluate_condition(node, state)

    assert result is True


def test_workflow_engine_rejects_unsafe_condition() -> None:
    """危险表达式应被拒绝并返回 False。"""

    engine = WorkflowEngine(context=None)
    state = WorkflowState(variables={})
    node = WorkflowNode(id="cond", type=NodeType.CONDITION, condition="().__class__")

    result = engine._evaluate_condition(node, state)

    assert result is False


@pytest.mark.asyncio
async def test_workflow_engine_agent_skill_mcp_helpers_cover_remaining_edges(
    monkeypatch: "MonkeyPatch",
) -> None:
    """补齐 agent/skill/mcp 辅助分支与 next 选择逻辑。"""

    monkeypatch.setattr(WorkflowEngine, "_load_workflows", lambda self: None)

    missing_context_engine = WorkflowEngine(context=None)
    agent_node = WorkflowNode(
        id="agent",
        type=NodeType.AGENT,
        config={"prompt": "hello {missing}", "output_variable": "reply"},
    )
    with pytest.raises(RuntimeError, match="Context 不可用"):
        await missing_context_engine._execute_agent_node(
            agent_node,
            WorkflowState(variables={"_provider_id": "provider-a"}),
        )

    recording_context = RecordingContext("ok")
    agent_engine = WorkflowEngine(context=recording_context)
    agent_state = WorkflowState(variables={"_provider_id": "provider-a"})
    agent_result = await agent_engine._execute_agent_node(agent_node, agent_state)
    assert agent_result == {"response": "ok"}
    assert agent_state.variables["reply"] == "ok"
    assert recording_context.calls[0]["prompt"] == "hello {missing}"

    missing_skill_loader_engine = WorkflowEngine(context=None, skill_loader=None)
    skill_node = WorkflowNode(id="skill", type=NodeType.SKILL, config={"skill": "missing"})
    with pytest.raises(RuntimeError, match="Skill 加载器不可用"):
        await missing_skill_loader_engine._execute_skill_node(skill_node, WorkflowState())

    empty_skill_engine = WorkflowEngine(context=None, skill_loader=FakeSkillLoader({}))
    skill_state = WorkflowState()
    skill_result = await empty_skill_engine._execute_skill_node(skill_node, skill_state)
    assert skill_result == {"skill": "missing", "loaded": False}
    assert "skill_missing" not in skill_state.variables

    missing_mcp_engine = WorkflowEngine(context=None, mcp_bridge=None)
    mcp_node = WorkflowNode(id="mcp", type=NodeType.MCP, config={"tool": "search"})
    with pytest.raises(RuntimeError, match="MCP 桥接器不可用"):
        await missing_mcp_engine._execute_mcp_node(mcp_node, WorkflowState())

    state = WorkflowState()
    end_node = WorkflowNode(id="end", type=NodeType.END)
    condition_node = WorkflowNode(
        id="cond",
        type=NodeType.CONDITION,
        next_nodes=["true_branch", "false_branch"],
    )
    assert agent_engine._get_next_node(end_node, {}, state) is None
    assert agent_engine._get_next_node(condition_node, True, state) == "true_branch"
