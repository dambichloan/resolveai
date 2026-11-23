"""Đơn hàng giả định + tra cứu cho chatbot ResolveAI.

File này độc lập: không import gì từ phần còn lại của app, nên chép vào là chạy.
Dữ liệu nằm trong bộ nhớ (đủ cho demo). Muốn thêm đơn: thêm một dòng _order(...) vào DEMO_ORDERS.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

SHIP_FEE = 30000


def _order(code, phone, name, items, status, created, carrier=None, tracking=None,
           eta=None, address="", note="", ship=SHIP_FEE):
    """items: danh sách (tên sản phẩm, đơn giá, số lượng)."""
    lines = [{"name": n, "price": p, "qty": q} for n, p, q in items]
    subtotal = sum(i["price"] * i["qty"] for i in lines)
    return {
        "code": code, "phone": phone, "customer": name, "items": lines,
        "subtotal": subtotal, "ship": ship, "total": subtotal + ship,
        "status": status, "created": created, "carrier": carrier,
        "tracking": tracking, "eta": eta, "address": address, "note": note,
    }


DEMO_ORDERS = [
    _order("SVN1001", "0901234567", "Nguyễn Văn An",
           [("Áo thun nam basic size M", 150000, 2)], "Đang giao", "2026-11-21",
           "GHN", "GHN4829301", "2026-11-25", "12 Lê Lợi, Q.1, TP.HCM"),
    _order("SVN1002", "0912345678", "Trần Thị Bình",
           [("Quần jean nữ size 28", 420000, 1)], "Đã giao", "2026-11-14",
           "GHTK", "GHTK7731920", "2026-11-20", "45 Nguyễn Trãi, Thanh Xuân, Hà Nội",
           "Giao thành công ngày 2026-11-20."),
    _order("SVN1003", "0923456789", "Lê Hoàng Cường",
           [("Giày sneaker nam size 42", 890000, 1)], "Chờ xác nhận", "2026-11-23",
           eta="2026-11-28", address="88 Trần Phú, Hải Châu, Đà Nẵng"),
    _order("SVN1004", "0934567890", "Phạm Minh Dũng",
           [("Áo khoác gió nam size L", 560000, 1)], "Đang đóng gói", "2026-11-22",
           eta="2026-11-26", address="7 Hùng Vương, Ninh Kiều, Cần Thơ"),
    _order("SVN1005", "0945678901", "Võ Thu Hà",
           [("Váy liền nữ size S", 480000, 1), ("Túi tote vải canvas", 190000, 1)],
           "Đang giao", "2026-11-20", "Viettel Post", "VTP5520184", "2026-11-24",
           "23 Phan Chu Trinh, TP. Huế"),
    _order("SVN1006", "0956789012", "Đặng Quốc Huy",
           [("Áo sơ mi nam size XL", 350000, 1)], "Đã hủy", "2026-11-18",
           address="9 Lý Thường Kiệt, Hà Nội",
           note="Khách yêu cầu hủy ngày 2026-11-19. Tiền hoàn về trong 3-5 ngày làm việc."),
    _order("SVN1007", "0967890123", "Bùi Ngọc Lan",
           [("Chân váy nữ size M", 290000, 1)], "Hoàn trả", "2026-11-08",
           "GHN", "GHN4711022", "2026-11-12", "31 Hai Bà Trưng, Nha Trang",
           "Đã nhận lại hàng trả, đang xử lý hoàn tiền."),
    _order("SVN1008", "0978901234", "Ngô Thanh Phong",
           [("Áo hoodie unisex size L", 420000, 2)], "Đã giao", "2026-11-10",
           "GHTK", "GHTK7690455", "2026-11-15", "5 Võ Văn Tần, Q.3, TP.HCM"),
    _order("SVN1009", "0989012345", "Hoàng Mỹ Linh",
           [("Giày cao gót nữ size 37", 650000, 1)], "Đang giao", "2026-11-19",
           "GHN", "GHN4830777", "2026-11-25", "64 Điện Biên Phủ, Bình Thạnh, TP.HCM",
           "Giao lần 1 chưa thành công do không liên lạc được, shipper sẽ giao lại."),
    _order("SVN1010", "0390123456", "Đỗ Anh Khoa",
           [("Quần short nam size M", 180000, 3)], "Chờ xác nhận", "2026-11-23",
           eta="2026-11-27", address="102 Nguyễn Huệ, Biên Hòa, Đồng Nai"),
    _order("SVN1011", "0381234567", "Mai Phương Thảo",
           [("Áo len nữ size M", 380000, 1)], "Đã giao", "2026-11-09",
           "Viettel Post", "VTP5498801", "2026-11-13", "18 Trần Hưng Đạo, Hải Phòng"),
    _order("SVN1012", "0372345678", "Trịnh Văn Đức",
           [("Balo laptop chống sốc", 720000, 1)], "Đang đóng gói", "2026-11-22",
           eta="2026-11-27", address="56 Quang Trung, Vinh, Nghệ An"),
    _order("SVN1013", "0363456789", "Lý Bảo Châu",
           [("Áo polo nam size L", 270000, 2), ("Quần kaki nam size 32", 390000, 1)],
           "Đang giao", "2026-11-21", "GHTK", "GHTK7745310", "2026-11-25",
           "27 Lê Duẩn, Buôn Ma Thuột, Đắk Lắk"),
    _order("SVN1014", "0354567890", "Vũ Khánh Vy",
           [("Đầm công sở nữ size M", 520000, 1)], "Đã giao", "2026-11-05",
           "GHN", "GHN4688120", "2026-11-09", "14 Nguyễn Văn Cừ, Quy Nhơn, Bình Định"),
    _order("SVN1015", "0345678901", "Phan Đức Thịnh",
           [("Giày chạy bộ nam size 41", 950000, 1), ("Tất thể thao (3 đôi)", 90000, 1)],
           "Đang đóng gói", "2026-11-23", eta="2026-11-27",
           address="3 Bạch Đằng, Hạ Long, Quảng Ninh"),
]

_BY_CODE = {o["code"]: o for o in DEMO_ORDERS}


# ---------------------------------------------------------------- tiện ích văn bản
def _plain(text: str) -> str:
    """Chữ thường, bỏ dấu tiếng Việt (để so khớp từ khóa)."""
    text = text.lower().replace("đ", "d")
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def money(v: int) -> str:
    return f"{v:,}".replace(",", ".") + "đ"


ORDER_KEYWORDS = (
    "don hang", "ma don", "tra cuu don", "van don", "kiem tra don", "tinh trang don",
    "trang thai don", "don cua toi", "don cua minh", "hang cua toi", "hang cua minh",
    "bao gio nhan", "khi nao nhan", "bao gio giao", "khi nao giao", "giao chua",
    "da giao chua", "toi dat hang", "minh dat hang", "theo doi don",
)


def extract_order_code(text: str) -> Optional[str]:
    m = re.search(r"\bDH[\s\-]?(\d{3,6})\b", text, re.IGNORECASE)
    return f"DH{m.group(1)}" if m else None


def extract_phone(text: str) -> Optional[str]:
    for m in re.finditer(r"(?<!\d)(?:\+84|0)[\d\s.\-]{8,12}\d(?!\d)", text):
        digits = re.sub(r"\D", "", m.group())
        if digits.startswith("84"):
            digits = "0" + digits[2:]
        if len(digits) >= 10:
            return digits[:10]
    return None


def extract_phone_or_last4(text: str) -> Optional[str]:
    """Số điện thoại đầy đủ, hoặc 4 chữ số đứng riêng (4 số cuối) nếu không có số đầy đủ."""
    full = extract_phone(text)
    if full:
        return full
    rest = re.sub(r"\bDH[\s\-]?\d{3,6}\b", " ", text, flags=re.IGNORECASE)
    m = re.search(r"(?<!\d)(\d{4})(?!\d)", rest)
    return m.group(1) if m else None


def is_order_query(text: str) -> bool:
    p = _plain(text)
    return any(k in p for k in ORDER_KEYWORDS)


# ---------------------------------------------------------------- tra cứu
def find_order(code: str, phone: str) -> Optional[dict]:
    """Chỉ trả đơn khi mã đơn VÀ số điện thoại (đầy đủ hoặc 4 số cuối) cùng khớp."""
    order = _BY_CODE.get((code or "").upper())
    digits = re.sub(r"\D", "", phone or "")
    if order and (order["phone"] == digits or (len(digits) == 4 and order["phone"].endswith(digits))):
        return order
    return None


def format_order(o: dict) -> str:
    lines = [f"Đơn {o['code']} của {o['customer']}", f"Trạng thái: {o['status']}", "Sản phẩm:"]
    for i in o["items"]:
        lines.append(f"- {i['name']} x{i['qty']}: {money(i['price'] * i['qty'])}")
    lines.append(f"Phí vận chuyển: {money(o['ship'])}")
    lines.append(f"Tổng thanh toán: {money(o['total'])}")
    lines.append(f"Ngày đặt: {o['created']}")
    if o["carrier"]:
        lines.append(f"Đơn vị vận chuyển: {o['carrier']} (mã vận đơn {o['tracking']})")
    if o["eta"] and o["status"] in ("Chờ xác nhận", "Đang đóng gói", "Đang giao"):
        lines.append(f"Dự kiến giao: {o['eta']}")
    if o["address"]:
        lines.append(f"Địa chỉ nhận: {o['address']}")
    if o["note"]:
        lines.append(f"Ghi chú: {o['note']}")
    return "\n".join(lines)


def answer_order_query(text: str, history: Optional[list] = None) -> Optional[str]:
    """Trả lời câu hỏi tra cứu đơn hàng, hoặc None nếu đây không phải câu hỏi về đơn.

    text: tin nhắn hiện tại của khách.
    history: (tùy chọn) các tin nhắn trước đó của khách, để ghép mã đơn ở tin này
    với số điện thoại ở tin sau.
    """
    prev = list(history or [])
    code, phone = extract_order_code(text), extract_phone_or_last4(text)
    wants = is_order_query(text) or bool(code)
    if not wants and phone and any(extract_order_code(t) for t in prev):
        wants = True
    if not wants:
        return None

    for t in prev:  # lấy thông tin còn thiếu từ các tin trước
        code = code or extract_order_code(t)
        phone = phone or extract_phone_or_last4(t)

    if not code:
        return ("Để tra cứu đơn hàng, bạn vui lòng gửi giúp mình mã đơn (dạng SVN1001) "
                "và số điện thoại đặt hàng (hoặc 4 số cuối) nhé.")
    if not phone:
        return (f"Mình đã nhận mã đơn {code}. Bạn vui lòng gửi thêm số điện thoại đặt hàng (hoặc 4 số cuối) "
                "để mình xác minh và tra cứu nhé.")
    order = find_order(code, phone)
    if not order:
        return (f"Mình không tìm thấy đơn {code} khớp với số điện thoại này. "
                "Bạn kiểm tra lại mã đơn và số điện thoại giúp mình nhé.")
    return format_order(order)


def lookup_order_tool(order_code: str, phone: str) -> dict:
    """Dùng làm function/tool cho Gemini (hoặc agent khác): trả dict để model tự diễn đạt."""
    order = find_order(order_code, phone)
    if not order:
        return {"found": False, "message": "Không tìm thấy đơn khớp mã đơn và số điện thoại."}
    return {"found": True, "order": order}
