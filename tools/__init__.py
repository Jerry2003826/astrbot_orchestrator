"""本插件的 FunctionTool 集合。

按配置开关分组构建工具实例，在 main.OrchestratorPlugin.initialize()
中通过 ``context.add_llm_tools(*tools)`` 注册给宿主默认 Agent；
/agent 指令的 tool_loop_agent 也复用同一批工具。
"""

from __future__ import annotations

from typing import Any

from .base import OrchestratorTool
from .debug_tools import DebugRecentErrorsTool, DebugStatusTool
from .mcp_tools import (
    McpAddTool,
    McpListTool,
    McpListToolsTool,
    McpRemoveTool,
    McpTestTool,
)
from .plugin_tools import (
    PluginInstallTool,
    PluginListTool,
    PluginSearchTool,
    PluginUninstallTool,
    PluginUpdateTool,
)
from .sandbox_tools import (
    SandboxExecBashTool,
    SandboxExecPythonTool,
    SandboxFileReadTool,
    SandboxFileWriteTool,
    SandboxInstallPackagesTool,
)
from .skill_tools import (
    SkillCreateTool,
    SkillDeleteTool,
    SkillListTool,
    SkillReadTool,
)
from .workflow_tools import WorkflowListTool, WorkflowRunTool

__all__ = [
    "OrchestratorTool",
    "build_orchestrator_tools",
]


def build_orchestrator_tools(runtime: Any, config: Any) -> list[OrchestratorTool]:
    """按配置开关构建本插件提供的全部 FunctionTool。"""

    def enabled(key: str) -> bool:
        try:
            return bool(config.get(key, True))
        except Exception:
            return True

    tools: list[OrchestratorTool] = []

    if enabled("enable_plugin_management"):
        tools += [
            PluginSearchTool(runtime),
            PluginListTool(runtime),
            PluginInstallTool(runtime),
            PluginUninstallTool(runtime),
            PluginUpdateTool(runtime),
        ]

    if enabled("enable_skill_creation"):
        tools += [
            SkillListTool(runtime),
            SkillReadTool(runtime),
            SkillCreateTool(runtime),
            SkillDeleteTool(runtime),
        ]

    if enabled("enable_mcp_config"):
        tools += [
            McpListTool(runtime),
            McpAddTool(runtime),
            McpRemoveTool(runtime),
            McpTestTool(runtime),
            McpListToolsTool(runtime),
        ]

    if enabled("enable_code_execution"):
        tools += [
            SandboxExecPythonTool(runtime),
            SandboxExecBashTool(runtime),
            SandboxFileReadTool(runtime),
            SandboxFileWriteTool(runtime),
            SandboxInstallPackagesTool(runtime),
        ]

    if enabled("enable_self_debug"):
        tools += [
            DebugStatusTool(runtime),
            DebugRecentErrorsTool(runtime),
        ]

    if enabled("enable_workflows"):
        tools += [
            WorkflowListTool(runtime),
            WorkflowRunTool(runtime),
        ]

    return tools
