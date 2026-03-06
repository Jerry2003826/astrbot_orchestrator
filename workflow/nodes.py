"""
工作流节点定义
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional


class NodeType(Enum):
    """节点类型"""
    START = "start"
    END = "end"
    AGENT = "agent"
    SKILL = "skill"
    MCP = "mcp"
    CONDITION = "condition"
    PARALLEL = "parallel"


class NodeStatus(Enum):
    """节点状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class WorkflowNode:
    """工作流节点"""
    id: str
    type: NodeType
    name: str = ""
    config: Dict[str, Any] = field(default_factory=dict)
    next_nodes: List[str] = field(default_factory=list)
    condition: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: Dict) -> "WorkflowNode":
        node_type = data.get("type", "agent")
        if isinstance(node_type, str):
            node_type = NodeType(node_type)
        
        return cls(
            id=data["id"],
            type=node_type,
            name=data.get("name", data["id"]),
            config=data.get("config", {}),
            next_nodes=data.get("next_nodes", []),
            condition=data.get("condition")
        )


@dataclass
class WorkflowState:
    """工作流状态"""
    workflow_id: str = ""
    variables: Dict[str, Any] = field(default_factory=dict)
    node_results: Dict[str, Any] = field(default_factory=dict)
    node_status: Dict[str, NodeStatus] = field(default_factory=dict)
    status: NodeStatus = NodeStatus.PENDING
    error: Optional[str] = None
    
    def set_variable(self, name: str, value: Any):
        self.variables[name] = value
    
    def get_variable(self, name: str, default: Any = None) -> Any:
        return self.variables.get(name, default)
    
    def resolve_variable(self, value: Any) -> Any:
        if isinstance(value, str):
            if value.startswith("${") and value.endswith("}"):
                return self.get_variable(value[2:-1])
            if value.startswith("$"):
                return self.get_variable(value[1:])
            if "{" in value and "}" in value:
                try:
                    return value.format(**self.variables)
                except KeyError:
                    pass
        return value


@dataclass
class WorkflowDefinition:
    """工作流定义"""
    id: str
    name: str
    description: str = ""
    nodes: List[WorkflowNode] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "WorkflowDefinition":
        nodes = [WorkflowNode.from_dict(n) for n in data.get("nodes", [])]
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            nodes=nodes,
            config=data.get("config", {})
        )
    
    def get_node(self, node_id: str) -> Optional[WorkflowNode]:
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None
    
    def get_start_node(self) -> Optional[WorkflowNode]:
        for node in self.nodes:
            if node.type == NodeType.START:
                return node
        return None
