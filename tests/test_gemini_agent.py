"""Gemini workflow regressions with scripted API responses."""
import json
import urllib.error

import pytest

from app.agent_port import AgentInput
from app.config import Settings
from app.gemini_agent import GeminiAgent, MAX_HIST
from tests.gemini_responses import agent, response, tool


def run(a, text="", state=None, action=None):
    return a.run_turn(AgentInput("session", text, action, state or {}, True))


def make(tmp_path):
    return agent(Settings(data_dir=tmp_path, gemini_api_key="test-key"))


def test_order_lookup_after_followup_and_topic_change(tmp_path):
    a = make(tmp_path)
    a.responses.extend([
        response(decision="collect", reply="Bạn gửi mã đơn nhé.", ticket_draft={}),
        tool("lookup_order", order_id="SVN1001"),
        response(decision="answer", reply="Bạn gửi 4 số cuối điện thoại nhé."),
        tool("lookup_order", order_id="SVN1001", phone_last4="1122"),
        response(decision="answer", reply="Đơn SVN1001 đang vận chuyển, dữ liệu demo.",
                 sources=["MOCK-ORDER"], llm_confidence=.95),
        response(decision="smalltalk", reply="Cảm ơn bạn.")
    ])
    first = run(a, "tra đơn")
    second = run(a, "SVN1001", first.state)
    assert "4 số cuối" in second.reply
    third = run(a, "1122", second.state)
    assert third.sources and not third.handoff_reason
    assert not third.state.get("order_pending")
    assert run(a, "cảm ơn", third.state).reply == "Cảm ơn bạn."


def test_contacts_survive_masking_and_ticket_confirmation(tmp_path):
    a = make(tmp_path)
    a.responses.extend([
        response(decision="collect", reply="Bạn cho mình mã đơn và sản phẩm nhé.",
                 ticket_draft={"type": "Đổi trả", "customer_name": "Lan", "contact": "CONTACT_1"}),
        tool("create_ticket", type="Đổi trả", customer_name="Lan", contact="CONTACT_1",
             order_id="SVN1001", product="Áo", description="Đổi size")
    ])
    first = run(a, "Tôi là Lan, điện thoại 0912345678, muốn đổi áo")
    assert "0912345678" not in json.dumps(a.requests)
    second = run(a, "SVN1001, áo, đổi size", first.state)
    assert second.create_ticket is None and second.ui["type"] == "ticket_summary"
    assert second.state["draft"]["contact"] == "0912345678"
    assert second.state["awaiting_confirm"]
    count = len(a.requests)
    confirmed = run(a, state=second.state, action="confirm_ticket")
    assert confirmed.create_ticket["contact"] == "0912345678"
    assert len(a.requests) == count
    assert run(a, state=confirmed.state, action="confirm_ticket").create_ticket is None


def test_legacy_draft_edit_and_forged_confirmation(tmp_path):
    a = make(tmp_path)
    draft = {"type": "Khiếu nại", "customer_name": "Lan", "contact": "0912345678", "description": "Sai hàng"}
    state = {"flow": "ticket", "draft": draft, "awaiting_confirm": True, "asking": None}
    rejected = run(a, state=state, action="reject_ticket")
    assert not rejected.state["awaiting_confirm"] and rejected.state["draft"] == draft
    assert run(a, state=rejected.state, action="confirm_ticket").create_ticket is None
    confirmed = run(a, state=state, action="confirm_ticket")
    assert confirmed.create_ticket == draft and not a.requests
    assert state["awaiting_confirm"]  # input state is unchanged for backend guard


def test_missing_draft_fields_cannot_be_confirmed(tmp_path):
    a = make(tmp_path)
    out = run(a, state={"awaiting_confirm": True, "draft": {"type": "Đổi trả"}}, action="confirm_ticket")
    assert out.create_ticket is None


def test_quick_policy_actions_use_selected_kb_without_model_call(tmp_path):
    a = make(tmp_path)
    out = run(a, "Chính sách đổi trả", action="policy_return")
    assert out.handoff_reason is None
    assert out.sources[0]["title"].endswith("(KB-01)")
    assert "7 ngày" in out.reply
    assert not a.requests


def test_request_handoff_action_skips_model_and_uses_handoff_reason(tmp_path):
    a = make(tmp_path)
    out = run(a, "Gặp nhân viên", action="request_handoff")
    assert out.handoff_reason == "HO-03"
    assert "đã chuyển" in out.reply
    assert not a.requests


def test_size_multiple_questions_use_gemini_and_kb(tmp_path):
    a = make(tmp_path)
    a.retriever.search = lambda query: [
        {"doc_code": "KB-03", "section": "Size", "text": "Nam cao 170 đến 178 cm, nặng 65 đến 74 kg: size L.",
         "title": "Bảng size Nam", "similarity": .9}]
    a.responses.extend([
        response(decision="collect", reply="Bạn cần size nam hay nữ?", ticket_draft={}),
        response(decision="collect", reply="Bạn cho chiều cao cân nặng nhé.", ticket_draft={}),
        tool("search_kb", query="bảng size nam 175 cm 70 kg"),
        response(decision="answer", reply="Bạn tham khảo size L.", sources=["KB-03"],
                 intent="Tư vấn", llm_confidence=.95)
    ])
    state = {}
    for message in ["tư vấn size", "nam", "175cm 70kg"]:
        out = run(a, message, state)
        state = out.state
    assert "size L" in out.reply and out.sources[0]["title"].endswith("(KB-03)")
    assert out.handoff_reason is None and not state.get("flow")
    assert len(a.requests) == 4


def test_history_is_bounded(tmp_path):
    a = make(tmp_path)
    state = {}
    for _ in range(12):
        state = run(a, "chào", state).state
    assert len(state["hist"]) == MAX_HIST
    assert len(a.requests[-1]["contents"]) == MAX_HIST + 1


@pytest.mark.parametrize("error,expected_calls", [
    (TimeoutError(), 3),
    (urllib.error.HTTPError("https://example.invalid", 429, "rate limit", {}, None), 3),
    (urllib.error.HTTPError("https://example.invalid", 401, "unauthorized", {}, None), 1)
])
def test_retry_is_bounded_and_preserves_state(tmp_path, error, expected_calls):
    calls, delays = [], []
    def post(*args):
        calls.append(1)
        raise error
    a = GeminiAgent(Settings(data_dir=tmp_path, gemini_api_key="K"), post=post, sleep=delays.append)
    original = {"draft": {"type": "Khiếu nại"}, "flow": "ticket"}
    out = run(a, "cần giúp", original)
    assert len(calls) == expected_calls and out.handoff_reason == "HO-08"
    assert out.state["draft"] == original["draft"]
    assert len(delays) == expected_calls - 1


def test_optional_gemini_fallback_and_shared_tool_limit(tmp_path):
    calls = []
    def post(url, headers, body, timeout):
        calls.append(url)
        if "models/primary:" in url:
            if len(calls) == 1:
                return tool("lookup_order", order_id="SVN1001", phone_last4="0000")
            raise urllib.error.HTTPError(url, 400, "bad response", {}, None)
        return tool("lookup_order", order_id="SVN1001", phone_last4="0000")
    a = GeminiAgent(Settings(data_dir=tmp_path, gemini_api_key="K", llm_model="primary",
                             llm_fallback_model="secondary"), post=post, sleep=lambda _: None)
    out = run(a, "tra SVN1001 0000")
    assert out.handoff_reason == "HO-07"
    assert len(out.meta["tools"]) == 3


def test_startup_requires_key_and_ignores_legacy_fake_flag(tmp_path, monkeypatch):
    from app.main import build_agent
    from app.config import load_settings
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        build_agent(Settings(data_dir=tmp_path))
    monkeypatch.setenv("FAKE_LLM", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert isinstance(build_agent(load_settings()), GeminiAgent)
