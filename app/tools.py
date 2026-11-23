"""Lớp công cụ kiểu MCP (Mục 22): bốn công cụ có tên, mô tả và inputSchema theo chuẩn MCP.

- search_kb, lookup_order: ĐỌC dữ liệu.
- create_ticket, handoff_to_agent: chỉ ĐỀ NGHỊ. Công cụ không ghi DB; Backend kiểm tra rồi mới ghi
  (Ticket cần nút Xác nhận của khách, Handoff cần Guard của Backend).
Execution Guard nằm ở ToolRegistry.call: allowlist, kiểm tra schema, giới hạn 3 lệnh gọi mỗi lượt.
Agent gọi trực tiếp trong tiến trình; app/mcp_server.py mở cùng danh mục này qua JSON-RPC (MCP) khi MCP_ENABLED=1.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

MAX_TOOL_CALLS = 3
TICKET_TYPES = ("Đổi trả", "Bảo hành", "Khiếu nại")
NEED_ORDER = ("Đổi trả", "Bảo hành")
HANDOFF_CODES = ("HO-01", "HO-03", "HO-04")   # mã mô hình được đề nghị; mã khác do Backend/luồng cố định quyết định

TOOL_SPECS: list[dict[str, Any]] = [
    {"name": "search_kb",
     "description": "Tìm chính sách Savani liên quan tới câu hỏi và trả về trích đoạn có mã nguồn, điểm similarity và decision_zone.",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string", "maxLength": 300}},
                     "required": ["query"], "additionalProperties": False}},
    {"name": "lookup_order",
     "description": "Tra cứu đơn trên Mock Order DB. Bắt buộc có mã đơn và 4 số cuối số điện thoại hoặc email đăng ký.",
     "inputSchema": {"type": "object", "properties": {
         "order_id": {"type": "string", "maxLength": 20}, "phone_last4": {"type": "string", "maxLength": 4},
         "email": {"type": "string", "maxLength": 100}}, "required": ["order_id"], "additionalProperties": False}},
    {"name": "create_ticket",
     "description": "Đề nghị tạo Ticket khi đủ thông tin. Công cụ KHÔNG tạo Ticket: khách phải bấm Xác nhận trên thẻ tóm tắt.",
     "inputSchema": {"type": "object", "properties": {
         "type": {"type": "string", "enum": list(TICKET_TYPES)},
         "customer_name": {"type": "string", "maxLength": 100}, "contact": {"type": "string", "maxLength": 100},
         "order_id": {"type": "string", "maxLength": 20}, "product": {"type": "string", "maxLength": 200},
         "description": {"type": "string", "maxLength": 1000}},
         "required": ["type", "customer_name", "contact", "description"], "additionalProperties": False}},
    {"name": "handoff_to_agent",
     "description": "Đề nghị chuyển cuộc trò chuyện cho nhân viên CSKH (HO-01 thiếu căn cứ, HO-03 khách muốn gặp người, HO-04 bức xúc/khiếu nại).",
     "inputSchema": {"type": "object", "properties": {
         "reason_code": {"type": "string", "enum": list(HANDOFF_CODES)},
         "summary": {"type": "string", "maxLength": 300}}, "required": ["reason_code"], "additionalProperties": False}},
]
SPEC_BY_NAME = {s["name"]: s for s in TOOL_SPECS}


@dataclass
class Turn:
    """Trạng thái của MỘT lượt chat khi gọi công cụ."""
    state: dict[str, Any]
    sources: dict[str, float] = field(default_factory=dict)   # doc_code -> similarity
    texts: list[str] = field(default_factory=list)            # nội dung công cụ trả về, làm căn cứ cho Output Guard
    calls: int = 0
    ticket: dict[str, Any] | None = None                      # Ticket được đề nghị
    handoff: str | None = None                                # mã Handoff được đề nghị
    log: list[dict[str, Any]] = field(default_factory=list)   # (tên, kết quả ngắn) cho trace


def gemini_declarations() -> list[dict[str, Any]]:
    """Đổi inputSchema (JSON Schema) sang functionDeclarations của Gemini."""
    def conv(s: dict) -> dict:
        out = {"type": s["type"].upper()}
        if "enum" in s:
            out["enum"] = s["enum"]
        if "properties" in s:
            out["properties"] = {k: conv(v) for k, v in s["properties"].items()}
        if s.get("required"):
            out["required"] = s["required"]
        return out
    return [{"functionDeclarations": [
        {"name": t["name"], "description": t["description"], "parameters": conv(t["inputSchema"])} for t in TOOL_SPECS]}]


def validate(name: str, args: Any) -> str | None:
    """Trả về thông báo lỗi nếu tham số không đúng inputSchema, ngược lại None."""
    spec = SPEC_BY_NAME.get(name)
    if spec is None:
        return "Công cụ không được phép."
    if not isinstance(args, dict):
        return "arguments phải là object."
    sch = spec["inputSchema"]
    extra = set(args) - set(sch["properties"])
    if extra:
        return "Tham số lạ: " + ", ".join(sorted(extra))
    for k in sch.get("required", []):
        if args.get(k) in (None, ""):
            return f"Thiếu tham số {k}."
    for k, v in args.items():
        rule = sch["properties"][k]
        if not isinstance(v, str):
            return f"{k} phải là chuỗi."
        if len(v) > rule.get("maxLength", 500):
            return f"{k} quá dài."
        if "enum" in rule and v not in rule["enum"]:
            return f"{k} không hợp lệ."
    return None


class ToolRegistry:
    def __init__(self, search_fn: Callable[[str], list[dict]], order_fn: Callable[..., dict | None],
                 rag_handoff: float, rag_answer: float):
        self._search, self._order = search_fn, order_fn
        self.rag_handoff, self.rag_answer = rag_handoff, rag_answer

    @staticmethod
    def specs() -> list[dict[str, Any]]:
        return TOOL_SPECS

    def call(self, name: str, args: Any, turn: Turn, raw_input: str = "") -> dict[str, Any]:
        err = validate(name, args)
        if err is None and turn.calls >= MAX_TOOL_CALLS:
            err = "Vượt giới hạn số lần gọi công cụ trong một lượt."
        if err:
            turn.log.append({"tool": name, "ok": False})
            return {"error": err}
        turn.calls += 1
        result = getattr(self, "_" + name)(args, turn, raw_input)
        turn.log.append({"tool": name, "ok": "error" not in result})
        return result

    # ---- search_kb
    def _search_kb(self, args: dict, turn: Turn, raw_input: str) -> dict:
        query = args["query"].strip()
        if not query:
            return {"matches": [], "message": "Cần có từ khóa tìm kiếm."}
        matches = self._search(query)
        scores = {m["doc_code"]: float(m["similarity"]) for m in matches}
        top = max(scores.values(), default=0.0)
        turn.sources.update(scores)
        turn.texts += [m["content"] for m in matches]
        zone = "handoff" if top < self.rag_handoff else ("cautious" if top < self.rag_answer else "answer")
        return {"matches": matches, "top_similarity": top, "decision_zone": zone}

    # ---- lookup_order
    def _lookup_order(self, args: dict, turn: Turn, raw_input: str) -> dict:
        order_id = args["order_id"].strip().upper()
        phone_last4 = args.get("phone_last4", "").strip()
        email = args.get("email", "").strip()
        if not email:
            m = re.search(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", raw_input)
            email = m.group(0) if m else ""
        if not phone_last4:
            m = re.search(r"(?:số\s*cuối|đuôi|last\s*4)\D{0,20}(\d{4})", raw_input, re.I)
            phone_last4 = m.group(1) if m else ""
        if not phone_last4 and not email:
            return {"found": False, "needs_verification": True,
                    "message": "Cần 4 số cuối số điện thoại hoặc email đăng ký trước khi tra đơn."}
        order = self._order(order_id, phone_last4, email)
        if order is None:
            n = int(turn.state.get("order_auth_failures", 0)) + 1
            turn.state["order_auth_failures"] = n
            if n >= 3:                                   # BR16: sai 3 lần thì chuyển nhân viên
                turn.state["order_auth_locked"] = True
            return {"found": False, "needs_verification": True,
                    "message": "Không thể xác thực thông tin đơn. Hãy kiểm tra lại mã đơn và thông tin đối chiếu."}
        turn.state.pop("order_auth_failures", None)
        turn.sources["MOCK-ORDER"] = 1.0
        turn.texts.append(json.dumps(order, ensure_ascii=False))
        return {"found": True, "order": order}

    # ---- create_ticket (chỉ đề nghị)
    def _create_ticket(self, args: dict, turn: Turn, raw_input: str) -> dict:
        draft = {k: v.strip() for k, v in args.items() if v.strip()}
        missing = [k for k in (("customer_name", "contact", "order_id", "product", "description")
                               if draft["type"] in NEED_ORDER else ("customer_name", "contact", "description"))
                   if not draft.get(k)]
        if missing:
            return {"status": "missing_fields", "missing": missing,
                    "message": "Hãy hỏi khách các thông tin còn thiếu rồi gọi lại."}
        if not (re.search(r"\d{8,}", draft["contact"]) or "@" in draft["contact"]):
            return {"status": "missing_fields", "missing": ["contact"],
                    "message": "Thông tin liên hệ phải là số điện thoại hoặc email."}
        turn.ticket = draft
        return {"status": "awaiting_customer_confirmation",
                "message": "Đã hiển thị thẻ tóm tắt; khách cần bấm Xác nhận để Ticket được tạo."}

    # ---- handoff_to_agent (chỉ đề nghị)
    def _handoff_to_agent(self, args: dict, turn: Turn, raw_input: str) -> dict:
        turn.handoff = args["reason_code"]
        return {"status": "handoff_requested", "reason_code": turn.handoff}
