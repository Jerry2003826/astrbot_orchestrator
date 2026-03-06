"""Workflow 节点对象测试。"""

from __future__ import annotations

from typing import TYPE_CHECKING

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

    _PYTEST_TYPE_IMPORTS = (
        CaptureFixture,
        FixtureRequest,
        LogCaptureFixture,
        MonkeyPatch,
        MockerFixture,
    )


def test_workflow_node_from_dict_supports_string_and_enum_types() -> None:
    """节点字典应兼容字符串类型和值已是枚举的情况。"""

    start_node = WorkflowNode.from_dict({"id": "start", "type": "start"})
    end_node = WorkflowNode.from_dict(
        {
            "id": "end",
            "type": NodeType.END,
            "name": "结束节点",
            "config": {"output_variable": "result"},
            "next_nodes": ["cleanup"],
            "condition": "enabled",
        }
    )

    assert start_node.type == NodeType.START
    assert start_node.name == "start"
    assert start_node.config == {}
    assert start_node.next_nodes == []
    assert start_node.condition is None

    assert end_node.type == NodeType.END
    assert end_node.name == "结束节点"
    assert end_node.config == {"output_variable": "result"}
    assert end_node.next_nodes == ["cleanup"]
    assert end_node.condition == "enabled"


def test_workflow_state_variable_helpers_cover_all_resolution_paths() -> None:
    """状态对象应支持赋值、默认值、变量引用、模板格式化与原样返回。"""

    state = WorkflowState(status=NodeStatus.PENDING)
    raw_value: dict[str, str] = {"raw": "value"}

    state.set_variable("name", "AstrBot")
    state.set_variable("answer", 42)

    assert state.get_variable("name") == "AstrBot"
    assert state.get_variable("missing", "fallback") == "fallback"
    assert state.resolve_variable("${answer}") == 42
    assert state.resolve_variable("$answer") == 42
    assert state.resolve_variable("hello {name}") == "hello AstrBot"
    assert state.resolve_variable("hello {missing}") == "hello {missing}"
    assert state.resolve_variable(raw_value) is raw_value


def test_workflow_definition_helpers_cover_lookup_and_start_resolution() -> None:
    """工作流定义应能从字典构建并正确查找节点。"""

    definition = WorkflowDefinition.from_dict(
        {
            "id": "demo_flow",
            "name": "Demo Flow",
            "description": "workflow description",
            "config": {"parallel": True},
            "nodes": [
                {"id": "start", "type": "start", "next_nodes": ["agent"]},
                {"id": "agent", "type": "agent"},
            ],
        }
    )
    missing_start_definition = WorkflowDefinition(
        id="missing_start",
        name="Missing Start",
        nodes=[WorkflowNode(id="agent", type=NodeType.AGENT)],
    )

    assert definition.id == "demo_flow"
    assert definition.name == "Demo Flow"
    assert definition.description == "workflow description"
    assert definition.config == {"parallel": True}
    assert definition.get_node("agent") is not None
    assert definition.get_node("missing") is None
    assert definition.get_start_node() == WorkflowNode(
        id="start",
        type=NodeType.START,
        name="start",
        config={},
        next_nodes=["agent"],
        condition=None,
    )
    assert missing_start_definition.get_start_node() is None
