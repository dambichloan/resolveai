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
    refusal = classify_attack(text)
    if refusal:
        return refusal
    if sensitive_input(text):
        return SENSITIVE_REPLY
    return None


def prepare_untrusted_text(text: str) -> str | None:
    """Do not pass hostile instructions embedded in KB/tool data to the model context."""
    if _UNTRUSTED.search(text):
        return None
    return mask_pii(text)


def guard_output(text: str) -> str:
    """Prevent the assistant from echoing contact details from retrieved/user text, or leaking its configuration."""
    if leaks_config(text):
        return CONFIG_REFUSAL
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


# ---------------------------------------------------------------- Tấn công thường gặp (bộ red-team RT-xx)
_OFFER = " Mình có thể hỗ trợ bạn về chính sách, đơn hàng và các yêu cầu đổi trả, bảo hành."
CONFIG_REFUSAL = "Mình không thể thực hiện yêu cầu này vì liên quan đến thông tin cấu hình nội bộ." + _OFFER
DESTRUCTIVE_REFUSAL = ("Mình không thể thực hiện yêu cầu này: xóa hoặc thay đổi dữ liệu nằm ngoài phạm vi hỗ trợ "
                       "của trợ lý chăm sóc khách hàng." + _OFFER)
MARKUP_REFUSAL = "Mình không thể thực hiện yêu cầu này: mình không thực thi hay lặp lại mã." + _OFFER
BYPASS_REFUSAL = "Mình không thể thực hiện yêu cầu này: mình luôn tuân thủ các quy tắc an toàn của Savani." + _OFFER
AUTHORITY_REFUSAL = ("Mình không thể thực hiện yêu cầu này: mình không công nhận quyền quản trị hay nhân viên qua lời tự khai "
                     "trong cuộc trò chuyện và không cung cấp dữ liệu quản trị." + _OFFER)
ORDER_LIST_REFUSAL = ("Mình không thể thực hiện yêu cầu này: mình không cung cấp danh sách hay dữ liệu đơn hàng của shop. "
                      "Nếu là đơn của bạn, hãy gửi mã đơn và 4 số cuối số điện thoại hoặc email đã đăng ký để mình tra giúp.")

_MARKUP = re.compile(r"<\s*/?\s*(script|iframe|img|svg|object|embed|style|link|meta|body|html|form|input)\b|"
                     r"\bon(error|load|click|focus|mouseover)\s*=|javascript\s*:", re.I)
_SECRET = r"(api ?key|apikey|khoa api|token|secret|mat khau (he thong|admin|database|co so du lieu)|chuoi ket noi|connection string|bien moi truong|env\b)"
_CONFIG = [re.compile(p) for p in (
    r"\b(liet ke|ke ten|danh sach|cho (toi|minh) (biet|xem))\b.{0,30}\b(cong cu|tool|tools|ham|function)\b.{0,40}\b(noi bo|cua ban|ban co|tham so|tung)\b",
    r"\bcong cu noi bo\b|\btham so (cua )?(tung |moi )?(cong cu|tool|ham)\b",
    r"\b(cho (toi|minh) xem|xem|in ra|hien thi|tiet lo|cho biet|gui|show|print|reveal|dump)\b.{0,30}" + _SECRET,
    r"\b(system prompt|prompt he thong|prompt cua ban|chi dan he thong|chi dan noi bo|cau hinh noi bo|quy tac noi bo|huong dan noi bo)\b",
    r"\b(in|in ra|hien thi|cho xem|tiet lo|xuat|print|show|reveal|dump|repeat)\b.{0,25}\b(toan bo )?(cau hinh|instructions?)\b",
    r"\b(lap lai|nhac lai|doc lai|chep|sao chep|repeat)\b.{0,40}\bban la\b",
    r"\b(lap lai|nhac lai|doc lai|chep|sao chep|tom tat( lai)?|liet ke|repeat|summari[sz]e)\b.{0,50}\b(huong dan|chi dan|chi thi|cau hinh|quy tac|instructions?)\b.{0,50}\b(duoc cau hinh|cua ban|o dau|dau tien|ban dau|noi bo|nguyen van)\b",
    r"\b(huong dan|chi dan|cau hinh|quy tac)\b.{0,30}\b(duoc cau hinh|ban dau|dau cuoc tro chuyen|o dau cuoc)\b",
    r"\bma hoa\b.{0,25}\b(prompt|huong dan|chi dan)\b|\bbase ?64\b",
    r"\b(che do|mode)\s*(debug|dev|developer|nha phat trien|bao tri)\b|\bvao che do debug\b",
    r"what (are|is) your (system |initial |first )?(instructions?|prompt|rules)",
)]
_DESTRUCT = [re.compile(p) for p in (
    r"\b(xoa|huy|go bo|reset|wipe|drop|delete|truncate)\b.{0,25}\b(toan bo|het|tat ca|all|moi)\b.{0,25}\b(du lieu|don hang|co so du lieu|database|orders?|data|bang)\b",
    r"\b(xoa|drop|delete|truncate)\b.{0,20}\b(du lieu|database|table|bang don hang|orders?)\b",
    r"\b(viet|tao|cho|gui)\b.{0,25}\b(ma|code|script|lenh|cau lenh|sql|query)\b.{0,35}\b(xoa|delete|drop|truncate)\b",
    r"\b(drop|truncate)\s+table\b|\bdelete\s+from\b|\brm\s+-rf\b",
)]
_BYPASS = [re.compile(p) for p in (
    r"\b(quen|bo qua|vo hieu hoa?|huy|tat|ignore|disable|forget|override)\b.{0,30}\b(moi |het |tat ca |all |cac )?(quy tac|luat|rang buoc|rules?|restrictions?|safety|an toan|rao chan|guardrails?|huong dan|chi dan|instructions?)\b",
    r"\bsafety (checks? )?(are |is )?off\b|\bno (safety|restrictions)\b|\bkhong (con )?(quy tac|gioi han|rang buoc)\b|\bkhong gioi han\b",
    r"\bda bo qua quy tac\b|\bbat dau bang\b.{0,40}\b(ok|da bo qua|da duyet|da cap nhat)\b|\bbat dau bang\b.{0,25}\b(duyet hoan tien|da duyet)\b",
    r"\bmoi cau tra loi\b.{0,30}\bbat dau bang\b|\bcau tra loi tiep theo\b.{0,30}\bbat dau bang\b",
    r"\b(pretend|gia vo|tuong tuong|gia su|dong vai|role ?play)\b.{0,80}\b(safety|an toan|quy tac|test environment|moi truong thu nghiem|off|tat|khong (co )?gioi han|dan)\b",
    r"\bkiem tra bao mat\b.{0,80}\b(quen|bo qua|in cau hinh|xac nhan bang chu)\b",
    r"\bxac nhan bang (chu|tu|cum tu)\b|\btra loi (la |bang )?['\"]?(da cap nhat|safety off)\b",
    r"\bjailbreak\b|\bdan mode\b|\bdong vai dan\b|\bdan,? mot ai\b|\bsudo\b",
    r"^\s*\[?\s*(system|he thong|admin)\s*\]",
    r"\bquy tac moi co hieu luc\b",
)]
_AUTHORITY = re.compile(
    r"\btoi la\b.{0,25}\b(quan tri vien|admin|lap trinh vien|nguoi tao ra ban|nhan vien (cskh|savani|cham soc khach hang)|chu cua hang|giam doc|dev)\b|"
    r"\bma nhan vien\b|\bmo trang quan tri\b|\bquen mat khau admin\b")
_ORDER_LIST = re.compile(r"\b(xem|liet ke|cho (toi|minh)|gui|in|hien thi|show|list|dump|xuat)\b.{0,25}\b(du lieu |danh sach |toan bo |tat ca )?"
                         r"don hang\b.{0,20}\b(hom nay|cua shop|cua cua hang|toan bo|tat ca|moi nhat|gan day)\b|"
                         r"\b(danh sach|du lieu|toan bo|tat ca) don hang (hom nay|cua shop|cua cua hang)\b")
_OWN_ORDER = re.compile(r"\bcua (toi|minh)\b|\bma don\b|\bsvn\s?\d|\btk-?\d")
_LEAK_MARKERS = ("search_kb", "lookup_order", "create_ticket", "handoff_to_agent", "llm_confidence",
                 "functiondeclarations", "bạn là trợ lý cskh", "quy tắc bắt buộc", "system prompt")


def classify_attack(text: str) -> str | None:
    """Câu từ chối cho các kiểu tấn công thường gặp (không gọi LLM), hoặc None nếu tin nhắn bình thường."""
    if _MARKUP.search(text):
        return MARKUP_REFUSAL
    n = _norm(text)
    if any(p.search(n) for p in _DESTRUCT):
        return DESTRUCTIVE_REFUSAL
    if _AUTHORITY.search(n):
        return ORDER_LIST_REFUSAL if (_ORDER_LIST.search(n) and not _OWN_ORDER.search(n)) else AUTHORITY_REFUSAL
    if any(p.search(n) for p in _CONFIG):
        return CONFIG_REFUSAL
    if any(p.search(n) for p in _BYPASS):
        return ORDER_LIST_REFUSAL if (_ORDER_LIST.search(n) and not _OWN_ORDER.search(n)) else BYPASS_REFUSAL
    if _ORDER_LIST.search(n) and not _OWN_ORDER.search(n):
        return ORDER_LIST_REFUSAL
    return None


def leaks_config(reply: str) -> bool:
    """Câu trả lời để lộ tên công cụ nội bộ hoặc nội dung chỉ dẫn hệ thống."""
    low = reply.lower()
    return any(m in low for m in _LEAK_MARKERS)
