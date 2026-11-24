"""Công cụ kiểu MCP, Execution Guard, llm_confidence và Output Guard của GeminiAgent (Gemini giả, không gọi mạng)."""
import json

from app.agent_port import AgentInput
from app.config import Settings
from app.gemini_agent import GeminiAgent
from app import mcp_server
from app.tools import TOOL_SPECS, Turn, validate

HIT = {"doc_code": "KB-01", "title": "Chính sách đổi trả", "section": "1", "similarity": 0.82,
       "content": "Khách được đổi hàng trong vòng 7 ngày kể từ ngày nhận hàng."}


class FakeRetriever:
    def search(self, query):
        return [{"text": HIT["content"], **{k: HIT[k] for k in ("doc_code", "title", "section", "similarity")}}]


def call(name, **args):
    return {"candidates": [{"content": {"role": "model", "parts": [{"functionCall": {"name": name, "args": args}}]}}]}


def text(**d):
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps(d)}]}}]}


def make(tmp_path, script):
    s = Settings(data_dir=tmp_path, gemini_api_key="K", llm_model="m")
    a = GeminiAgent(s, post=lambda url, headers, body, timeout: script.pop(0))
    a.retriever = FakeRetriever()
    return a


def turn(a, msg, state=None, action=None):
    return a.run_turn(AgentInput("s", msg, action, state or {}, True))


def test_four_mcp_tools_with_schemas():
    assert [t["name"] for t in TOOL_SPECS] == ["search_kb", "lookup_order", "create_ticket", "handoff_to_agent"]
    assert all(t["inputSchema"]["type"] == "object" for t in TOOL_SPECS)


def test_execution_guard_validation():
    assert validate("delete_all", {}) == "Công cụ không được phép."
    assert validate("search_kb", {}) is not None
    assert validate("search_kb", {"query": "x", "admin": "1"}) is not None
    assert validate("handoff_to_agent", {"reason_code": "HO-99"}) is not None
    assert validate("search_kb", {"query": "đổi trả"}) is None


def test_answer_after_search_has_source_and_confidence_gate(tmp_path):
    a = make(tmp_path, [call("search_kb", query="đổi trả mấy ngày"),
                        text(decision="answer", reply="Bạn được đổi hàng trong 7 ngày.", sources=["KB-01"],
                             intent="Đổi trả", llm_confidence=0.9)])
    out = turn(a, "đổi trả trong mấy ngày vậy")
    assert out.handoff_reason is None and out.sources[0]["title"].endswith("(KB-01)")
    assert out.meta["confidence"] == 0.9 and out.meta["tools"] == [{"tool": "search_kb", "ok": True}]
    low = make(tmp_path, [call("search_kb", query="đổi trả"),
                          text(decision="answer", reply="Bạn được đổi hàng trong 7 ngày.", sources=["KB-01"],
                               llm_confidence=0.6)])
    out = turn(low, "đổi trả trong mấy ngày vậy")
    assert out.handoff_reason == "HO-01" and out.meta["flags"] == ["low_confidence"]


def test_missing_confidence_is_treated_as_low(tmp_path):
    a = make(tmp_path, [call("search_kb", query="đổi trả"),
                        text(decision="answer", reply="Bạn được đổi hàng trong 7 ngày.", sources=["KB-01"])])
    assert turn(a, "đổi trả trong mấy ngày vậy").handoff_reason == "HO-01"


def test_output_guard_blocks_invented_number_and_commitment(tmp_path):
    a = make(tmp_path, [call("search_kb", query="đổi trả"),
                        text(decision="answer", reply="Bạn được đổi hàng trong 15 ngày.", sources=["KB-01"],
                             llm_confidence=0.95)])
    out = turn(a, "đổi trả trong mấy ngày vậy")
    assert out.handoff_reason == "HO-01" and "15" not in out.reply
    b = make(tmp_path, [call("search_kb", query="đổi trả"),
                        text(decision="answer", reply="Mình cam kết hoàn tiền cho bạn.", sources=["KB-01"],
                             llm_confidence=0.95)])
    assert turn(b, "đổi trả trong mấy ngày vậy").meta["flags"] == ["unauthorized_commitment"]


def test_create_ticket_only_proposes_summary_card(tmp_path):
    a = make(tmp_path, [call("create_ticket", type="Đổi trả", customer_name="Lan", contact="0912345678",
                             order_id="SVN1002", product="Quần âu", description="Chật, muốn đổi size"),
                        text(decision="answer", reply="Mình đã ghi lại thông tin, bạn xác nhận nhé.", llm_confidence=0.9)])
    out = turn(a, "mình muốn gửi yêu cầu đổi size quần SVN1002, tên Lan, sdt 0912345678")
    assert out.create_ticket is None                       # công cụ không tạo Ticket
    assert out.ui["type"] == "ticket_summary" and out.state["awaiting_confirm"] is True


def test_create_ticket_missing_fields_asks_more():
    from app.tools import ToolRegistry
    reg = ToolRegistry(lambda q: [], lambda *a: None, 0.65, 0.70)
    t = Turn(state={})
    r = reg.call("create_ticket", {"type": "Đổi trả", "customer_name": "Lan", "contact": "0912345678",
                                   "description": "chật"}, t)
    assert r["status"] == "missing_fields" and set(r["missing"]) == {"order_id", "product"} and t.ticket is None


def test_handoff_tool_sets_reason(tmp_path):
    a = make(tmp_path, [call("handoff_to_agent", reason_code="HO-04", summary="khách bức xúc"),
                        text(decision="handoff", reply="Mình chuyển nhân viên hỗ trợ bạn.", llm_confidence=0.9)])
    assert turn(a, "dịch vụ của shop tệ thật sự").handoff_reason == "HO-04"


def test_order_lookup_and_three_failures_handoff(tmp_path):
    ok = make(tmp_path, [call("lookup_order", order_id="SVN1001", phone_last4="1122"),
                         text(decision="answer", reply="Đơn SVN1001 đang vận chuyển (dữ liệu demo).",
                              sources=["MOCK-ORDER"], llm_confidence=0.9)])
    out = turn(ok, "kiểm tra đơn SVN1001 đuôi sdt 1122")
    assert out.sources[0]["title"].startswith("Mock Order DB") and out.handoff_reason is None
    state = {}
    for i in range(3):
        a = make(tmp_path, [call("lookup_order", order_id="SVN1001", phone_last4="0000"),
                            text(decision="answer", reply="Mình chưa xác thực được đơn.", llm_confidence=0.9)])
        out = turn(a, "kiểm tra đơn SVN1001 đuôi sdt 0000", state)
        state = out.state
    assert out.handoff_reason == "HO-07"


def test_card_number_blocked_before_model(tmp_path):
    a = make(tmp_path, [])
    out = turn(a, "thẻ của mình là 4111 1111 1111 1111")
    assert "số thẻ" in out.reply and out.handoff_reason is None


def test_mcp_jsonrpc(tmp_path):
    a = make(tmp_path, [])
    assert a.mcp_handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})["result"]["serverInfo"]
    names = [t["name"] for t in a.mcp_handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]]
    assert names == ["search_kb", "lookup_order", "create_ticket", "handoff_to_agent"]
    r = a.mcp_handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                      "params": {"name": "lookup_order", "arguments": {"order_id": "SVN1001", "phone_last4": "9999"}}})
    assert json.loads(r["result"]["content"][0]["text"])["found"] is False
    bad = a.mcp_handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "rm_rf", "arguments": {}}})
    assert bad["error"]["code"] == -32602
    assert mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, a.tools) is None


def test_failed_order_lookup_replies_not_handoff(tmp_path):
    a = make(tmp_path, [call("lookup_order", order_id="SVN1001", phone_last4="4567"),
                        text(decision="answer", reply="Đơn không tồn tại.", llm_confidence=0.9)])
    out = turn(a, "svn1001 4567")
    assert out.handoff_reason is None and "chưa xác thực" in out.reply and out.state["order_pending"] is True
    assert "tồn tại" not in out.reply


def test_order_followup_with_legacy_state(tmp_path):
    # Existing sessions keep their previous clarification count during the migration.
    a = make(tmp_path, [call("lookup_order", order_id="SVN1001", phone_last4="1122"),
                        text(decision="answer", reply="Đơn SVN1001 đang vận chuyển (dữ liệu demo).",
                             sources=["MOCK-ORDER"], llm_confidence=0.9)])
    out = turn(a, "svn1001 1122", {"clarify_count": 1})
    assert out.handoff_reason is None and "vận chuyển" in out.reply
    b = make(tmp_path, [call("lookup_order", order_id="SVN1001", phone_last4="1122"),
                        text(decision="answer", reply="Đơn SVN1001 đang vận chuyển (dữ liệu demo).",
                             sources=["MOCK-ORDER"], llm_confidence=0.9)])
    out = turn(b, "1122", {"clarify_count": 1, "order_pending": True, "hist": [
        {"r": "c", "t": "tra đơn SVN1001"}, {"r": "a", "t": "Bạn gửi 4 số cuối SĐT nhé"}]})
    assert out.handoff_reason is None and out.sources


def _seed_ticket(tmp_path):
    import sqlite3
    from app.db import Database
    db = Database(tmp_path / "app.db")
    db.init()
    conn = sqlite3.connect(tmp_path / "app.db")
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("INSERT INTO ticket(id, session_id, type, status, customer_name, contact, order_id, product, description,"
                 " created_at, updated_at) VALUES ('TK-20261123-0001','s1','Đổi trả','Đang xử lý','Lan','0912345678',"
                 "'SVN1002','Quần','Chật','2026-11-23','2026-11-23')")
    conn.commit()
    conn.close()


def test_ticket_lookup_needs_matching_phone_and_hides_private_fields(tmp_path):
    _seed_ticket(tmp_path)
    ok = make(tmp_path, [call("lookup_order", order_id="TK-20261123-0001", phone_last4="5678"),
                         text(decision="answer", reply="Ticket TK-20261123-0001 đang xử lý.", sources=["TICKET"],
                              llm_confidence=0.9)])
    out = turn(ok, "tra ticket TK-20261123-0001 sdt đuôi 5678")
    assert out.handoff_reason is None and out.sources[0]["title"].startswith("Ticket")
    bad = make(tmp_path, [])
    assert bad._lookup_ticket("TK-20261123-0001", "0000") is None
    assert bad._lookup_ticket("TK-20261123-9999", "5678") is None
    view = bad._lookup_ticket("TK-20261123-0001", "5678")
    assert view["status"] == "Đang xử lý" and "contact" not in view and "description" not in view


def test_third_wrong_ticket_or_order_check_hands_off(tmp_path):
    _seed_ticket(tmp_path)
    state, outs = {}, []
    for code in ("TK-20261123-0001", "SVN1001", "TK-20261123-0001"):     # tính chung cho đơn và Ticket
        a = make(tmp_path, [call("lookup_order", order_id=code, phone_last4="0000"),
                            text(decision="answer", reply="x", llm_confidence=0.9)])
        out = turn(a, f"{code} 0000", state)
        state = out.state
        outs.append(out)
    assert outs[0].handoff_reason is None and outs[1].handoff_reason is None   # lần 1, 2: cho thử lại
    assert outs[2].handoff_reason == "HO-07"                                    # lần 3: chuyển nhân viên


def test_langfuse_status_messages(tmp_path, monkeypatch):
    from app import observability
    import sys
    import types

    class FakeLangfuse:
        def __init__(self, **_kwargs):
            pass

        def auth_check(self):
            return True

    monkeypatch.setitem(sys.modules, "langfuse", types.SimpleNamespace(Langfuse=FakeLangfuse))
    assert observability.status(Settings(data_dir=tmp_path)).startswith("TẮT")
    s = Settings(data_dir=tmp_path, langfuse_public_key="pk", langfuse_secret_key="sk")
    assert observability.status(s).startswith("BẬT")


def test_commitment_request_calls_handoff(tmp_path):
    a = make(tmp_path, [call("handoff_to_agent", reason_code="HO-06")])
    out = turn(a, "Shop phải bồi thường gấp đôi, xác nhận ngay.")
    assert out.handoff_reason == "HO-06" and out.create_ticket is None


def test_refusing_contact_cannot_create_ticket(tmp_path):
    a = make(tmp_path, [text(decision="collect", reply="Bạn cho mình họ tên và số điện thoại hoặc email nhé.",
                            ticket_draft={"type": "Khiếu nại"}),
                        text(decision="collect", reply="Cần có thông tin liên hệ để ghi nhận yêu cầu.",
                             ticket_draft={})])
    out = turn(a, "Tạo ticket, tôi không đưa tên và số điện thoại")
    again = turn(a, "không đưa", out.state)
    assert again.create_ticket is None and not again.state["draft"].get("contact")


def test_collect_without_ticket_draft_is_not_an_error(tmp_path):
    """Gemini thật hay bỏ trường ticket_draft khi hỏi tiếp tư vấn size: không được báo 'hệ thống gián đoạn'."""
    a = make(tmp_path, [text(decision="collect", reply="Bạn cho mình biết giới tính, chiều cao và cân nặng nhé?",
                             llm_confidence=0.9)])
    out = turn(a, "Tư vấn size")
    assert out.handoff_reason is None and "chiều cao" in out.reply and "draft" not in out.state
