"""
Agent 注册表
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class AgentRecord:
    agent_id: str
    name: str
    role: str
    status: str
    created_at: datetime
    spec: Any
    metadata: Dict[str, Any]


class AgentRegistry:
    """维护动态 SubAgent 的运行态信息"""

    def __init__(self):
        self._records: Dict[str, AgentRecord] = {}

    def register(self, record: AgentRecord) -> None:
        self._records[record.agent_id] = record

    def update_status(self, agent_id: str, status: str) -> None:
        record = self._records.get(agent_id)
        if record:
            record.status = status

    def remove(self, agent_id: str) -> Optional[AgentRecord]:
        return self._records.pop(agent_id, None)

    def get(self, agent_id: str) -> Optional[AgentRecord]:
        return self._records.get(agent_id)

    def list(self) -> List[AgentRecord]:
        return list(self._records.values())

    def summary(self) -> str:
        if not self._records:
            return "暂无动态 SubAgent"

        lines = ["当前动态 SubAgent："]
        for record in self._records.values():
            created_at = record.created_at.strftime("%H:%M:%S")
            lines.append(
                f"- {record.name} ({record.role}) [{record.status}] @ {created_at}"
            )
        return "\n".join(lines)
