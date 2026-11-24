"""Mã Ticket TK-YYYYMMDD-XXXX, dữ liệu mẫu cho admin và chính sách KB."""
import re

from app.demo_seed import seed_demo
from app.service import TICKET_CODE_RE


def test_ticket_code_format(svc):
    assert re.match(TICKET_CODE_RE, "TK-20261118-0001")
    assert not re.match(TICKET_CODE_RE, "TK-202611180001")


def test_seed_demo_populates_admin_and_is_idempotent(svc):
    assert "đã nạp" in seed_demo(svc.db, svc.s)
    assert "bỏ qua" in seed_demo(svc.db, svc.s)
    tickets = svc.list_tickets()
    assert len(tickets) == 5 and all(re.match(TICKET_CODE_RE, t["id"]) for t in tickets)
    assert len(svc.queue()) == 2
    d = svc.dashboard()
    assert d["total_sessions"] == 12 and sum(d["tickets_by_status"].values()) == 5
    assert len({t["id"] for t in tickets}) == 5


def test_kb_policies_follow_doc(svc):
    docs = {d["doc_code"]: d for d in svc.kb_list()}
    assert set(docs) == {f"KB-0{i}" for i in range(1, 7)}
    assert "7 ngày" in svc.kb_get("KB-01")["content"]
    assert "30 ngày" in svc.kb_get("KB-02")["content"]
    assert "08:00 đến 17:30" in svc.kb_get("KB-05")["content"]
