"""
工作流引擎

基于 AstrBot Context API 实现
"""

import asyncio
import logging
from pathlib import Path
from typing import Any, cast

import yaml

from ..shared import SafeConditionError, evaluate_condition
from .nodes import NodeStatus, NodeType, WorkflowDefinition, WorkflowNode, WorkflowState

logger = logging.getLogger(__name__)
NodeExecutionResult = dict[str, Any] | bool


class WorkflowEngine:
    """
    工作流引擎

    使用 AstrBot 的 Context API 执行工作流
    """

    def __init__(
        self,
        context: Any,
        skill_loader: Any | None = None,
        mcp_bridge: Any | None = None,
    ) -> None:
        self.context = context
        self.skill_loader = skill_loader
        self.mcp_bridge = mcp_bridge

        self.workflows: dict[str, WorkflowDefinition] = {}

        # 加载工作流
        self._load_workflows()

    def _load_workflows(self) -> None:
        """加载工作流定义"""
        workflows_dir = Path(__file__).parent.parent / "workflows"
        if workflows_dir.exists():
            for yaml_file in workflows_dir.glob("*.yaml"):
                try:
                    self.load_from_yaml(str(yaml_file))
                except Exception as exc:
                    logger.error("加载工作流失败 [%s]: %s", yaml_file, exc)

    def load_from_yaml(self, yaml_path: str) -> str:
        """从 YAML 文件加载工作流"""
        path = Path(yaml_path)
        with path.open("r", encoding="utf-8") as file_obj:
            definition = cast(dict[str, Any] | None, yaml.safe_load(file_obj))
        if not isinstance(definition, dict):
            raise ValueError(f"工作流 YAML 格式无效: {yaml_path}")

        workflow_id = str(definition.get("id", path.stem))
        workflow = WorkflowDefinition.from_dict(definition)
        workflow.id = workflow_id

        self.workflows[workflow_id] = workflow
        logger.info("已加载工作流: %s", workflow_id)
        return workflow_id

    def get_workflow(self, workflow_id: str) -> WorkflowDefinition | None:
        return self.workflows.get(workflow_id)

    def list_workflows(self) -> list[dict[str, str]]:
        return [
            {"id": w.id, "name": w.name, "description": w.description}
            for w in self.workflows.values()
        ]

    async def execute(
        self,
        workflow_id: str,
        initial_input: dict[str, Any] | None = None,
        provider_id: str | None = None,
    ) -> WorkflowState:
        """执行工作流"""
        if workflow_id not in self.workflows:
            raise ValueError(f"工作流不存在: {workflow_id}")

        workflow = self.workflows[workflow_id]

        state = WorkflowState(workflow_id=workflow_id)
        state.variables = dict(initial_input) if initial_input else {}
        state.variables["_provider_id"] = provider_id
        state.status = NodeStatus.RUNNING

        try:
            start_node = workflow.get_start_node()
            if not start_node:
                raise ValueError("工作流缺少起始节点")

            await self._execute_node(start_node, workflow, state)
            state.status = NodeStatus.COMPLETED

        except Exception as exc:
            state.status = NodeStatus.FAILED
            state.error = str(exc)
            logger.error("工作流执行失败: %s", exc)

        return state

    async def _execute_node(
        self,
        node: WorkflowNode,
        workflow: WorkflowDefinition,
        state: WorkflowState,
    ) -> None:
        """执行单个节点"""
        state.node_status[node.id] = NodeStatus.RUNNING
        result: NodeExecutionResult = {}

        try:
            if node.type == NodeType.START:
                result = {"status": "started"}

            elif node.type == NodeType.END:
                output_var = str(node.config.get("output_variable", "output"))
                result = {"output": state.get_variable(output_var)}
                state.node_status[node.id] = NodeStatus.COMPLETED
                return

            elif node.type == NodeType.AGENT:
                result = await self._execute_agent_node(node, state)

            elif node.type == NodeType.SKILL:
                result = await self._execute_skill_node(node, state)

            elif node.type == NodeType.MCP:
                result = await self._execute_mcp_node(node, state)

            elif node.type == NodeType.CONDITION:
                result = self._evaluate_condition(node, state)

            elif node.type == NodeType.PARALLEL:
                result = await self._execute_parallel_nodes(node, workflow, state)

            else:
                result = {}

            state.node_results[node.id] = result
            state.node_status[node.id] = NodeStatus.COMPLETED

            # 确定下一个节点
            next_node_id = self._get_next_node(node, result, state)
            if next_node_id:
                next_node = workflow.get_node(next_node_id)
                if next_node:
                    await self._execute_node(next_node, workflow, state)

        except Exception:
            state.node_status[node.id] = NodeStatus.FAILED
            raise

    async def _execute_agent_node(
        self,
        node: WorkflowNode,
        state: WorkflowState,
    ) -> dict[str, Any]:
        """执行 Agent 节点"""
        if self.context is None:
            raise RuntimeError("Context 不可用")

        config = node.config
        provider_id = state.get_variable("_provider_id")

        # 构建 prompt
        system_prompt = str(config.get("system_prompt", ""))
        prompt_value = state.resolve_variable(config.get("prompt", ""))
        prompt = prompt_value if isinstance(prompt_value, str) else str(prompt_value)

        # 解析变量
        try:
            prompt = prompt.format(**state.variables)
        except KeyError:
            pass

        # 调用 LLM
        response = await self.context.llm_generate(
            chat_provider_id=provider_id, prompt=prompt, system_prompt=system_prompt
        )

        result = str(response.completion_text)

        # 保存输出
        output_var = str(config.get("output_variable", "output"))
        state.set_variable(output_var, result)

        return {"response": result}

    async def _execute_skill_node(
        self,
        node: WorkflowNode,
        state: WorkflowState,
    ) -> dict[str, Any]:
        """执行 Skill 节点"""
        if not self.skill_loader:
            raise RuntimeError("Skill 加载器不可用")

        skill_name = str(node.config.get("skill", ""))
        skill_content = self.skill_loader.get_skill_content(skill_name)

        if skill_content:
            state.set_variable(f"skill_{skill_name}", skill_content)

        return {"skill": skill_name, "loaded": bool(skill_content)}

    async def _execute_mcp_node(
        self,
        node: WorkflowNode,
        state: WorkflowState,
    ) -> dict[str, Any]:
        """执行 MCP 节点"""
        if not self.mcp_bridge:
            raise RuntimeError("MCP 桥接器不可用")

        tool_name = str(node.config.get("tool", ""))
        params: dict[str, Any] = {}
        parameter_config = cast(dict[str, Any], node.config.get("parameters", {}))

        for key, value in parameter_config.items():
            params[key] = state.resolve_variable(value)

        result = await self.mcp_bridge.call_tool(tool_name, params)

        output_var = str(node.config.get("output_variable", f"mcp_{tool_name}"))
        state.set_variable(output_var, result)

        return {"tool": tool_name, "result": result}

    def _evaluate_condition(
        self,
        node: WorkflowNode,
        state: WorkflowState,
    ) -> bool:
        """评估条件"""
        condition = node.condition or node.config.get("condition", "True")
        condition_text = condition if isinstance(condition, str) else str(condition)

        try:
            return bool(evaluate_condition(condition_text, state.variables))
        except SafeConditionError as exc:
            logger.warning("工作流条件求值失败 [%s]: %s", node.id, exc)
            return False

    async def _execute_parallel_nodes(
        self,
        node: WorkflowNode,
        workflow: WorkflowDefinition,
        state: WorkflowState,
    ) -> dict[str, list[Any]]:
        """并行执行节点"""
        parallel_ids = cast(list[str], node.config.get("parallel_nodes", []))

        tasks: list[Any] = []
        for node_id in parallel_ids:
            parallel_node = workflow.get_node(node_id)
            if parallel_node:
                tasks.append(self._execute_node(parallel_node, workflow, state))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {"parallel_results": list(results)}

    def _get_next_node(
        self,
        node: WorkflowNode,
        result: NodeExecutionResult,
        state: WorkflowState,
    ) -> str | None:
        """确定下一个节点"""
        del state

        if node.type == NodeType.END:
            return None

        if node.type == NodeType.CONDITION:
            if result:
                return node.next_nodes[0] if node.next_nodes else None
            else:
                return node.next_nodes[1] if len(node.next_nodes) > 1 else None

        return node.next_nodes[0] if node.next_nodes else None
