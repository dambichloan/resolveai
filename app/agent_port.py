"""Hợp đồng giữa Backend và Agent Workflow (Mục 20).

Backend KHÔNG tin Agent trong các thao tác ghi: Agent chỉ *đề nghị* tạo Ticket hoặc Handoff,
Backend kiểm tra điều kiện (Execution/Handoff Guard) rồi mới ghi DB. GeminiAgent hiện thực
`run_turn` theo hợp đồng này; Agent không có quyền ghi trực tiếp vào cơ sở dữ liệu.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class AgentInput:
    session_id: str
    text: str
    action: str | None            # structured customer action, if one was clicked
    state: dict[str, Any]         # trạng thái Agent của phiên (lưu ở chat_session.state_json)
    in_business_hours: bool


@dataclass
class AgentOutput:
    reply: str
    state: dict[str, Any]
    sources: list[dict[str, str]] = field(default_factory=list)
    ui: dict[str, Any] | None = None
    intent: str | None = None
    handoff_reason: str | None = None            # HO-01..HO-08: đề nghị Handoff
    create_ticket: dict[str, Any] | None = None  # đề nghị tạo Ticket (cần Guard cho phép)
    meta: dict[str, Any] = field(default_factory=dict)  # số liệu quan sát (công cụ đã gọi, độ tin cậy, cờ Guard)


class AgentPort(Protocol):
    def run_turn(self, inp: AgentInput) -> AgentOutput: ...
