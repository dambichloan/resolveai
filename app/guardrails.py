"""Small deterministic PII guard for model-bound text and AI replies."""
from __future__ import annotations

import re

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
    return None


def prepare_untrusted_text(text: str) -> str | None:
    """Do not pass hostile instructions embedded in KB/tool data to the model context."""
    if _UNTRUSTED.search(text):
        return None
    return mask_pii(text)


def guard_output(text: str) -> str:
    """Prevent the assistant from echoing contact details from retrieved/user text."""
    return mask_pii(text)
