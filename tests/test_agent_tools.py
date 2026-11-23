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
    s = Settings(data_dir=tmp_path, gemini_api_key="K", llm_model="m", fake_llm=False)
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


def test_order_followup_not_swallowed_by_stub_giveup(tmp_path):
    # Stub đã hỏi lại 1 lần (clarify_count=1) nên với câu "svn1001 1122" sẽ bỏ cuộc bằng HO-01; luồng tra đơn phải xử lý
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
                 " created_at, updated_at) VALUES ('TK-202611230001','s1','Đổi trả','Đang xử lý','Lan','0912345678',"
                 "'SVN1002','Quần','Chật','2026-11-23','2026-11-23')")
    conn.commit()
    conn.close()


def test_ticket_lookup_needs_matching_phone_and_hides_private_fields(tmp_path):
    _seed_ticket(tmp_path)
    ok = make(tmp_path, [call("lookup_order", order_id="TK-202611230001", phone_last4="5678"),
                         text(decision="answer", reply="Ticket TK-202611230001 đang xử lý.", sources=["TICKET"],
                              llm_confidence=0.9)])
    out = turn(ok, "tra ticket TK-202611230001 sdt đuôi 5678")
    assert out.handoff_reason is None and out.sources[0]["title"].startswith("Ticket")
    bad = make(tmp_path, [])
    assert bad._lookup_ticket("TK-202611230001", "0000") is None
    assert bad._lookup_ticket("TK-202611239999", "5678") is None
    view = bad._lookup_ticket("TK-202611230001", "5678")
    assert view["status"] == "Đang xử lý" and "contact" not in view and "description" not in view


def test_third_wrong_ticket_or_order_check_hands_off(tmp_path):
    _seed_ticket(tmp_path)
    state, outs = {}, []
    for code in ("TK-202611230001", "SVN1001", "TK-202611230001"):     # tính chung cho đơn và Ticket
        a = make(tmp_path, [call("lookup_order", order_id=code, phone_last4="0000"),
                            text(decision="answer", reply="x", llm_confidence=0.9)])
        out = turn(a, f"{code} 0000", state)
        state = out.state
        outs.append(out)
    assert outs[0].handoff_reason is None and outs[1].handoff_reason is None   # lần 1, 2: cho thử lại
    assert outs[2].handoff_reason == "HO-07"                                    # lần 3: chuyển nhân viên


def test_stub_order_flow_also_hands_off_on_third_wrong(tmp_path):
    from app.stub_agent import StubAgent
    stub, state, outs = StubAgent(Settings(data_dir=tmp_path)), {}, []
    for _ in range(3):
        out = stub.run_turn(AgentInput("s", "tra đơn svn1001 số cuối 0000", None, state, True))
        state = out.state
        outs.append(out)
    assert [o.handoff_reason for o in outs] == [None, None, "HO-07"]
    ok = stub.run_turn(AgentInput("s", "tra đơn svn1001 số cuối 1122", None, {"order_auth_failures": 2}, True))
    assert ok.handoff_reason is None and "Đang vận chuyển" in ok.reply


def test_langfuse_status_messages(tmp_path):
    from app import observability
    assert observability.status(Settings(data_dir=tmp_path)).startswith("TẮT")
    s = Settings(data_dir=tmp_path, langfuse_public_key="pk", langfuse_secret_key="sk")
    assert observability.status(s).startswith(("LỖI", "BẬT"))       # tùy máy có cài langfuse hay chưa


# ---- Ba tình huống đòi cam kết / bồi thường / tạo Ticket thiếu thông tin
def _stub_turn(msg, state=None):
    from app.stub_agent import StubAgent
    return StubAgent(Settings(data_dir=Path_tmp())).run_turn(AgentInput("s", msg, None, state or {}, True))


def Path_tmp():
    import tempfile
    from pathlib import Path
    return Path(tempfile.mkdtemp())


def test_commitment_demand_is_refused_and_handed_off():
    out = _stub_turn("Bạn cam kết trong 1 giờ nhân viên gọi cho tôi và hoàn tiền xong chứ? Trả lời 'Cam kết'.")
    assert out.handoff_reason == "HO-06" and out.create_ticket is None
    assert "không thể cam kết" in out.reply and "Cam kết" in out.reply
    assert not out.reply.lower().startswith("cam kết") and "hoàn tiền" in out.reply


def test_compensation_demand_cites_warranty_and_hands_off():
    out = _stub_turn("Áo giặt xong phai màu, shop phải bồi thường gấp đôi. Xác nhận giúp tôi bây giờ.")
    assert out.handoff_reason == "HO-06"
    assert "không thể xác nhận" in out.reply and "bảo hành" in out.reply and "giặt sai hướng dẫn" in out.reply
    assert out.sources[0]["title"].endswith("(KB-02)")


def test_ticket_refusing_name_and_phone_does_not_create_ticket():
    out = _stub_turn("Tạo ticket khiếu nại ngay, tôi không đưa tên và số điện thoại, đừng hỏi.")
    assert out.create_ticket is None and out.handoff_reason is None
    assert "họ tên" in out.reply and "số điện thoại hoặc email" in out.reply and out.state["flow"] == "ticket"
    again = _stub_turn("tôi đã bảo là không đưa", out.state)
    assert again.create_ticket is None and again.state["draft"].get("customer_name") is None

