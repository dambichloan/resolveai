"""Small deterministic PII guard for model-bound text and AI replies."""
from __future__ import annotations

import re
import unicodedata

_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"(?<!\w)(?:\+?84|0)(?:[ .-]?\d){8,10}(?!\w)")
_INJECTION = re.compile(r"ignore\s+(all|previous)|bỏ qua\s+(hướng dẫn|chỉ dẫn|chính sách)|"
                        r"tiết lộ\s+(prompt|api key)|system prompt|(?:mã giảm giá|voucher).*(100|toàn bộ)", re.I)
_UNTRUSTED = re.compile(r"ignore previous|system prompt|bỏ qua hướng dẫn", re.I)


def mask_pii(text: str) -> str:
    text = _EMAIL.sub("[email đã ẩn]", text)
    return _PHONE.sub("[số điện thoại đã ẩn]", text)


def input_guard(text: str) -> str | None:
    """Reject prompt injection before routing it into the Agent workflow."""
    if _INJECTION.search(text):
        return "Mình không thể thực hiện yêu cầu này. Mình có thể hỗ trợ về chính sách, đơn hàng và yêu cầu CSKH."
    if sensitive_input(text):
        return SENSITIVE_REPLY
    return None


def prepare_untrusted_text(text: str) -> str | None:
    """Do not pass hostile instructions embedded in KB/tool data to the model context."""
    if _UNTRUSTED.search(text):
        return None
    return mask_pii(text)


def guard_output(text: str) -> str:
    """Prevent the assistant from echoing contact details from retrieved/user text."""
    return mask_pii(text)


# ---------------------------------------------------------------- Guard bổ sung (Mục 23)
SENSITIVE_REPLY = ("Để bảo mật, bạn đừng gửi số thẻ, mã CVV, mật khẩu hay mã OTP trong cuộc trò chuyện này; "
                   "Savani không bao giờ yêu cầu những thông tin đó. Bạn cần hỗ trợ gì thêm về chính sách hoặc "
                   "đơn hàng không?")
SAFE_FALLBACK = "Mình chưa có thông tin chính thức cho câu hỏi này."
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_SENSITIVE_WORDS = re.compile(r"\b(cvv|cvc|otp|mat khau|password|so the|the tin dung|the ngan hang)\b")
_COMMITMENT = [re.compile(p) for p in (
    r"(cam ket|dam bao|chac chan).{0,40}(hoan (lai )?tien|boi thuong|duoc doi|duoc tra|duoc bao hanh)",
    r"(se|xin) (hoan (lai )?tien|boi thuong)",
    r"hoan (lai )?tien (100|toan bo|ngay)",
    r"den bu|boi thuong (cho )?(ban|quy khach)",
    r"(chap nhan|duyet) (doi|tra|hoan tien|bao hanh) (cho ban|ngay)",
)]
_NUM = re.compile(r"\d[\d.,]*")


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")


def luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def mask_card(text: str) -> str:
    """Che số thẻ (13-19 chữ số qua kiểm Luhn) trước khi lưu tin nhắn của khách."""
    def sub(m: re.Match) -> str:
        return "[số thẻ đã ẩn]" if luhn_ok(re.sub(r"\D", "", m.group(0))) else m.group(0)
    return _CARD.sub(sub, text)


def sensitive_input(text: str) -> bool:
    """Khách lỡ gửi số thẻ hợp lệ, CVV, OTP hoặc mật khẩu."""
    if any(luhn_ok(re.sub(r"\D", "", m.group(0))) for m in _CARD.finditer(text)):
        return True
    return bool(_SENSITIVE_WORDS.search(_norm(text)))


def unauthorized_commitment(reply: str, allowed_text: str) -> bool:
    """Câu trả lời cam kết hoàn tiền/bồi thường/duyệt đổi trả mà tài liệu không nêu (BR3, BR15)."""
    n, a = _norm(reply), _norm(allowed_text)
    return any(p.search(n) for p in _COMMITMENT) and not any(p.search(a) for p in _COMMITMENT)


def ungrounded_numbers(reply: str, allowed_text: str) -> list[str]:
    """Số liệu (từ 2 chữ số, hoặc kèm đơn vị) trong câu trả lời mà không có trong tài liệu, kết quả công cụ hay câu hỏi."""
    key = lambda s: re.sub(r"\D", "", s)  # noqa: E731
    allowed = {key(m.group(0)) for m in _NUM.finditer(allowed_text)}
    bad = []
    for m in _NUM.finditer(reply):
        raw = m.group(0).rstrip(".,")
        k = key(raw)
        if not k or k in allowed:
            continue
        unit = re.match(r"\s*(%|ngay|ngày|gio|giờ|d\b|đ\b|k\b|vnd|kg|cm|tieng|tiếng|lan|lần)", reply[m.end():m.end() + 8].lower())
        if len(k) >= 2 or unit:
            bad.append(raw)
    return bad
