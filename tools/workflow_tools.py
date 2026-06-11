"""YAML 工作流能力的 FunctionTool 封装（复用 workflow/engine.py）。"""

from __future__ import annotations

import json
from typing import Any

from .base import OrchestratorTool, obj_schema, str_prop


class WorkflowListTool(OrchestratorTool):
    requires_admin = False

    def __init__(self, runtime: Any) -> None:
        super().__init__(
            runtime,
            name="workflow_list",
            description="列出可用的 YAML 工作流（id、名称、描述）。",
            parameters=obj_schema({}),
        )

    async def run(self, event: Any) -> str:
        workflows = self.runtime.workflow_engine.list_workflows()
        if not workflows:
            return "当前没有已加载的工作流。"
        lines = ["可用工作流："]
        for wf in workflows:
            lines.append(f"- {wf['id']}: {wf['name']} — {wf['description']}")
        return "\n".join(lines)


class WorkflowRunTool(OrchestratorTool):
    def __init__(self, runtime: Any) -> None:
        super().__init__(
            runtime,
            name="workflow_run",
            description=(
                "执行指定的 YAML 工作流（管理员）。inputs 为传给工作流的初始变量（JSON 对象）。"
            ),
            parameters=obj_schema(
                {
                    "workflow_id": str_prop("工作流 ID（可用 workflow_list 查询）"),
                    "inputs": {
                        "type": "object",
                        "description": "可选的初始变量",
                    },
                },
                required=["workflow_id"],
            ),
        )

    async def run(
        self,
        event: Any,
        workflow_id: str,
        inputs: dict[str, Any] | None = None,
    ) -> str:
        if denied := self.check_permission(event):
            return denied
        engine = self.runtime.workflow_engine
        if engine.get_workflow(workflow_id) is None:
            return f"工作流不存在: {workflow_id}"
        state = await engine.execute(workflow_id, initial_input=inputs)
        status = getattr(state.status, "value", state.status)
        summary = [f"工作流 {workflow_id} 执行完成，状态: {status}"]
        if state.error:
            summary.append(f"错误: {state.error}")
        outputs = {k: v for k, v in state.variables.items() if not str(k).startswith("_")}
        if outputs:
            try:
                summary.append(
                    "输出变量:\n" + json.dumps(outputs, ensure_ascii=False, indent=2)[:1500]
                )
            except (TypeError, ValueError):
                summary.append(f"输出变量: {outputs}")
        return "\n".join(summary)
