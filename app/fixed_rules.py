"""Quy tắc cố định theo văn bản của khách, chạy TRƯỚC Gemini (Backend Guard, Mục 23). Không gọi LLM.

Gemini hiểu câu hỏi và trả lời theo chính sách (RAG). Những tình huống dưới đây phải xử lý chắc chắn nên không giao
cho mô hình quyết định: khách đòi gặp người (HO-03), đòi cam kết/hoàn tiền/bồi thường/voucher/ngoại lệ (HO-06, BR3,
BR6(6), BR15), muốn bỏ qua bước xác nhận Ticket (BR4) hoặc không chịu cung cấp thông tin để tạo Ticket (BR4).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .agent_port import AgentOutput
from .guardrails import _norm

REQUIRED_NOTE = ("Mình chưa thể tạo Ticket nếu thiếu thông tin: cần họ tên, số điện thoại hoặc email và mô tả vấn đề, "
                 "sau đó bạn xác nhận trên thẻ tóm tắt. Bạn vui lòng cho mình biết họ tên trước nhé?")
CONFIRM_REQUIRED = ("Mình không thể bỏ qua bước xác nhận: Ticket chỉ được tạo sau khi bạn kiểm tra bản tóm tắt và bấm "
                    "“Xác nhận”. Bạn cho mình họ tên, số điện thoại hoặc email và mô tả vấn đề để mình soạn bản tóm tắt nhé?")
COMMIT_REFUSAL = ("Mình không thể cam kết hoàn tiền hay thời gian gọi lại ngoài khung phản hồi đã quy định, và mình không "
                  "trả lời \"Cam kết\" thay nhân viên. Việc hoàn tiền do nhân viên CSKH quyết định sau khi kiểm tra, nên "
                  "mình chuyển bạn cho nhân viên.")
POLICY_HINT = ("Khách đang đòi hoàn tiền, bồi thường, voucher, miễn phí hoặc phê duyệt ngoại lệ. Hãy gọi search_kb để lấy chính "
               "sách liên quan (bảo hành, đổi trả hoặc hoàn tiền) và nêu NGẮN GỌN điều kiện theo chính sách. Tuyệt đối không "
               "hứa, không xác nhận và không tự phê duyệt; nói rõ việc này do nhân viên CSKH quyết định và mình chuyển nhân "
               "viên. Chọn decision handoff (không gọi handoff_to_agent). Nếu tài liệu không nêu thì chỉ nói chuyển nhân viên.")

_REFUSE = ["khong dua", "khong cung cap", "khong cho biet", "khong noi", "dung hoi", "khoi hoi", "khong can hoi"]
_TICKET = ["ticket", "tao yeu cau", "gui yeu cau", "ghi nhan", "khieu nai"]
_HUMAN = re.compile(
    r"\b(gap|noi chuyen voi|lien he voi)\b.{0,12}\b(nhan vien|nguoi that|tu van vien)\b|"
    r"\bchuyen\b.{0,20}\b(sang|cho|den|qua)\b.{0,15}\b(nhan vien|nguoi that|tu van vien)\b|\bchuyen nhan vien\b|"
    r"\bket noi\b.{0,15}\b(nhan vien|tu van vien)\b|"
    r"\bkhong muon (trao doi|noi chuyen|chat|lam viec) voi (ai|bot|may|tro ly)\b|\bmuon (noi chuyen|gap) (voi )?nguoi\b")
_BENEFIT = r"(hoan tien|boi thuong|den bu|gap doi|voucher|ma giam gia|mien phi (van chuyen|ship)|ngoai le)"
_DEMAND = (r"(xac nhan|phe duyet|duyet (cho|ngay)?|cam ket|bao dam|\bhua\b|phai (boi thuong|hoan|den bu)|muon (duoc )?"
           r"(hoan|boi thuong|den bu)|yeu cau .{0,20}(hoan|boi thuong)|tang (them )?(cho toi )?(voucher|ma)|"
           r"cho toi (hoan|voucher|ma giam)|tu (phe duyet|quyet))")
_COMMIT = re.compile(r"\b(cam ket|bao dam|hua)\b")
_SKIP_CONFIRM = re.compile(r"\b(bo qua|khong can|khoi|khong cho)\b.{0,25}\b(xac nhan|dong y)\b|"
                           r"\bkhi chua (dong y|xac nhan)\b|\bchua dong y voi noi dung\b")


@dataclass
class Rule:
    output: AgentOutput                 # câu trả lời cố định (cũng dùng khi Gemini không phản hồi được)
    hint: str | None = None             # có hint: nhờ Gemini soạn câu trả lời theo chính sách, Backend ép mã Handoff
    force: str | None = None


def match_text_rule(text: str, state: dict) -> Rule | None:
    n = _norm(text)
    has = lambda words: any(w in n for w in words)  # noqa: E731
    ticket_words = has(_TICKET)

    if _HUMAN.search(n):
        return Rule(AgentOutput("Mình sẽ chuyển cuộc trò chuyện cho nhân viên CSKH.", dict(state),
                                intent=state.get("intent") or "Tư vấn", handoff_reason="HO-03"))

    if has(_REFUSE) and (ticket_words or state.get("flow") == "ticket"):     # không chịu cung cấp thông tin: không tạo Ticket
        st = dict(state)
        st["flow"] = "ticket"
        st.setdefault("draft", {})
        return Rule(AgentOutput(REQUIRED_NOTE, st, intent=(st["draft"] or {}).get("type") or "Khiếu nại"))

    if ticket_words and _SKIP_CONFIRM.search(n):                              # muốn bỏ bước xác nhận Ticket
        return Rule(AgentOutput(CONFIRM_REQUIRED, dict(state), intent="Khiếu nại"))

    if not ticket_words:
        if _COMMIT.search(n) and (has(["hoan tien", "boi thuong"]) or has(["goi cho toi", "nhan vien goi", "1 gio"])):
            return Rule(AgentOutput(COMMIT_REFUSAL, dict(state), intent=state.get("intent") or "Đổi trả",
                                    handoff_reason="HO-06"))
        if re.search(_BENEFIT, n) and re.search(_DEMAND, n):
            fixed = AgentOutput("Mình không thể xác nhận hay hứa hoàn tiền, bồi thường, voucher hoặc ngoại lệ chính sách. "
                                "Những việc này do nhân viên CSKH quyết định, nên mình chuyển bạn cho nhân viên.",
                                dict(state), intent=state.get("intent") or "Đổi trả", handoff_reason="HO-06")
            return Rule(fixed, hint=POLICY_HINT, force="HO-06")
    return None
