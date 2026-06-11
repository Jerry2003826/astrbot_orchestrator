"""astrbot.core.star.register 测试桩。

复刻 v4.25.5 装饰器表面：被装饰函数保持可直接调用，
注册信息记录在函数属性 ``__astrbot_handlers__`` 上供测试断言；
指令组装饰器返回 RegisteringCommandable，与真实实现一致。
"""

from collections.abc import Callable
from typing import Any

from astrbot.core.agent.agent import Agent
from astrbot.core.agent.handoff import HandoffTool
from astrbot.core.agent.hooks import BaseAgentRunHooks
from astrbot.core.agent.tool import FunctionTool
from astrbot.core.provider.register import llm_tools


def _record(fn: Callable, record: dict[str, Any]) -> Callable:
    records = getattr(fn, "__astrbot_handlers__", [])
    records.append(record)
    fn.__astrbot_handlers__ = records  # type: ignore[attr-defined]
    return fn


class CommandGroupFilter:
    def __init__(
        self,
        group_name: str,
        alias: set | None = None,
        parent_group: "CommandGroupFilter | None" = None,
    ) -> None:
        self.group_name = group_name
        self.alias = alias or set()
        self.parent_group = parent_group
        self.sub_command_filters: list[Any] = []

    def add_sub_command_filter(self, sub_filter: Any) -> None:
        self.sub_command_filters.append(sub_filter)


class RegisteringCommandable:
    """用于指令组级联注册。"""

    def __init__(self, parent_group: CommandGroupFilter) -> None:
        self.parent_group = parent_group

    def command(self, command_name: str | None = None, alias: set | None = None, **kwargs):
        def decorator(fn: Callable) -> Callable:
            return _record(
                fn,
                {
                    "type": "command",
                    "name": command_name or fn.__name__,
                    "alias": alias or set(),
                    "group": self.parent_group.group_name,
                },
            )

        return decorator

    def group(self, sub_command: str, alias: set | None = None, **kwargs):
        def decorator(fn: Callable) -> "RegisteringCommandable":
            new_group = CommandGroupFilter(
                sub_command,
                alias,
                parent_group=self.parent_group,
            )
            self.parent_group.add_sub_command_filter(new_group)
            return RegisteringCommandable(new_group)

        return decorator


def register_command(command_name: str | None = None, alias: set | None = None, **kwargs):
    def decorator(fn: Callable) -> Callable:
        return _record(
            fn,
            {
                "type": "command",
                "name": command_name if isinstance(command_name, str) else fn.__name__,
                "alias": alias or set(),
                "group": None,
            },
        )

    return decorator


def register_command_group(
    command_group_name: str | None = None,
    sub_command: str | None = None,
    alias: set | None = None,
    **kwargs,
):
    def decorator(obj: Callable) -> RegisteringCommandable:
        new_group = CommandGroupFilter(str(command_group_name), alias)
        return RegisteringCommandable(new_group)

    return decorator


def register_regex(regex: str, **kwargs):
    def decorator(fn: Callable) -> Callable:
        return _record(fn, {"type": "regex", "pattern": regex})

    return decorator


def register_permission_type(permission_type: Any, raise_error: bool = True, **kwargs):
    def decorator(fn: Callable) -> Callable:
        return _record(
            fn,
            {
                "type": "permission",
                "permission_type": permission_type,
                "raise_error": raise_error,
            },
        )

    return decorator


def register_event_message_type(event_message_type: Any, **kwargs):
    def decorator(fn: Callable) -> Callable:
        return _record(fn, {"type": "event_message_type", "value": event_message_type})

    return decorator


def register_custom_filter(custom_filter: Any, **kwargs):
    def decorator(fn: Callable) -> Callable:
        return _record(fn, {"type": "custom_filter", "filter": custom_filter})

    return decorator


def register_llm_tool(name: str | None = None, **kwargs):
    name_ = name

    def decorator(fn: Callable) -> Callable:
        return _record(fn, {"type": "llm_tool", "name": name_ or fn.__name__})

    return decorator


class RegisteringAgent:
    def __init__(self, agent: Agent) -> None:
        self.agent = agent


def register_agent(
    name: str,
    instruction: str,
    tools: list[str | FunctionTool] | None = None,
    run_hooks: BaseAgentRunHooks | None = None,
):
    tools_ = tools or []

    def decorator(awaitable: Callable) -> RegisteringAgent:
        agent = Agent(
            name=name,
            instructions=instruction,
            tools=tools_,
            run_hooks=run_hooks or BaseAgentRunHooks(),
        )
        handoff_tool = HandoffTool(agent=agent)
        handoff_tool.handler = awaitable
        llm_tools.func_list.append(handoff_tool)
        return RegisteringAgent(agent)

    return decorator


def register_star(name: str, author: str, desc: str, version: str, repo: str | None = None):
    """[DEPRECATED in 4.x] AstrBot 会自动识别继承自 Star 的类。"""

    def decorator(cls: type) -> type:
        return cls

    return decorator


def _make_event_decorator(event_name: str):
    def register_event(**kwargs):
        def decorator(fn: Callable) -> Callable:
            return _record(fn, {"type": event_name})

        return decorator

    return register_event


register_on_astrbot_loaded = _make_event_decorator("on_astrbot_loaded")
register_on_platform_loaded = _make_event_decorator("on_platform_loaded")
register_on_plugin_loaded = _make_event_decorator("on_plugin_loaded")
register_on_plugin_unloaded = _make_event_decorator("on_plugin_unloaded")
register_on_plugin_error = _make_event_decorator("on_plugin_error")
register_on_llm_request = _make_event_decorator("on_llm_request")
register_on_llm_response = _make_event_decorator("on_llm_response")
register_on_waiting_llm_request = _make_event_decorator("on_waiting_llm_request")
register_on_using_llm_tool = _make_event_decorator("on_using_llm_tool")
register_on_llm_tool_respond = _make_event_decorator("on_llm_tool_respond")
register_on_agent_begin = _make_event_decorator("on_agent_begin")
register_on_agent_done = _make_event_decorator("on_agent_done")
register_on_decorating_result = _make_event_decorator("on_decorating_result")
register_after_message_sent = _make_event_decorator("after_message_sent")
