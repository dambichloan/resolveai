"""Dữ liệu mẫu cho trang quản trị (phiên chat, Ticket, hàng đợi). Bật bằng SEED_DEMO=1.

Dựa trên 6 đơn mẫu SVN1001-SVN1006 ở Mục 22.4 và các tham số chính sách ở Mục 6.4
(đổi trả 7 ngày, bảo hành 30 ngày, danh mục không đổi trả). Idempotent: đã có phiên "demo-*" thì bỏ qua.
Toàn bộ là dữ liệu giả, không phải khách hàng thật.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import security
from .config import Settings
from .db import Database
from .hours import in_business_hours

KB1 = {"title": "Chính sách đổi trả và hoàn tiền (KB-01)"}
KB2 = {"title": "Chính sách bảo hành (KB-02)"}
KB3 = {"title": "Bảng size Nam (KB-03)"}
KB4 = {"title": "Bảng size Nữ (KB-04)"}
KB5 = {"title": "Giờ làm việc và thời gian phản hồi của CSKH (KB-05)"}

# (id, ngày trước, giờ, phút, trạng thái, intent, mã handoff, [(role, text, nguồn, latency)])
SESSIONS = [
    ("demo-01", 0, 9, 5, "Waiting_Agent", "Khiếu nại", "HO-04", [
        ("customer", "Mình mua combo tất cổ cao đơn SVN1004, nhận 2 ngày rồi muốn trả vì không vừa.", [], None),
        ("ai", "Theo chính sách, tất/vớ thuộc danh mục không áp dụng đổi trả (trừ lỗi từ nhà sản xuất).", [KB1], 1480),
        ("customer", "Quá vô lý, các bạn làm ăn tệ hại, mình sẽ tố cáo!", [], None),
        ("ai", "Mình rất tiếc về trải nghiệm này của bạn. Mình chuyển ngay cho nhân viên CSKH để hỗ trợ bạn.\nNhân viên sẽ phản hồi bạn trong vòng 15 phút.", [], 910)]),
    ("demo-02", 0, 9, 40, "Waiting_Agent", "Tư vấn", "HO-03", [
        ("customer", "Cho mình gặp nhân viên tư vấn về đơn SVN1005 nhé.", [], None),
        ("ai", "Mình sẽ chuyển cuộc trò chuyện cho nhân viên CSKH.\nNhân viên sẽ phản hồi bạn trong vòng 15 phút.", [], 640)]),
    ("demo-03", 0, 10, 15, "Agent_Handling", "Đổi trả", "HO-01", [
        ("customer", "Mình muốn đổi size quần âu đơn SVN1002 từ L sang XL, vẫn còn tem.", [], None),
        ("ai", "Savani nhận đổi trả trong 7 ngày kể từ ngày nhận hàng, sản phẩm còn nguyên tem mác, chưa giặt. Bạn đổi size theo nhu cầu cá nhân thì phí vận chuyển 2 chiều là 30.000đ.", [KB1], 1620),
        ("customer", "Phí ship đổi mình có được giảm không?", [], None),
        ("ai", "Mình chưa có thông tin chính thức cho câu hỏi này.\nNhân viên sẽ phản hồi bạn trong vòng 15 phút.", [], 700),
        ("system", "Nhân viên CSKH đã tiếp nhận cuộc trò chuyện.", [], None),
        ("staff", "Chào anh Nam, em kiểm tra đơn SVN1002 rồi ạ. Phí đổi size theo nhu cầu cá nhân là đồng giá 30.000đ 2 chiều, em ghi nhận yêu cầu đổi size cho anh nhé.", [], None)]),
    ("demo-04", 1, 14, 20, "AI_Handling", "Đổi trả", None, [
        ("customer", "Áo đã giặt rồi có đổi được không?", [], None),
        ("ai", "Sản phẩm cần chưa qua sử dụng, chưa giặt tẩy và còn nguyên tem mác mới được đổi trả trong 7 ngày kể từ ngày nhận hàng.", [KB1], 1390),
        ("customer", "OK mình hiểu rồi, cảm ơn.", [], None),
        ("ai", "Cảm ơn bạn. Nếu cần hỗ trợ thêm, bạn cứ nhắn cho Savani nhé.", [], 520)]),
    ("demo-05", 1, 15, 2, "Closed", "Bảo hành", None, [
        ("customer", "Áo blazer đơn SVN1003 mình mới nhận bị bung chỉ, khóa kéo cũng hỏng.", [], None),
        ("ai", "Savani bảo hành lỗi kỹ thuật sản xuất (bung đường chỉ, hỏng khóa kéo, đứt cúc) trong 30 ngày kể từ ngày nhận hàng. Mình ghi nhận yêu cầu bảo hành cho bạn nhé.", [KB2], 1710),
        ("customer", "Bạn cứ ghi nhận giúp mình.", [], None),
        ("system", "Nhân viên CSKH đã tiếp nhận cuộc trò chuyện.", [], None),
        ("staff", "Chào chị Thảo, bộ phận kho đã xác nhận lỗi khóa kéo, bên em sẽ đổi sản phẩm mới và miễn phí vận chuyển 2 chiều ạ.", [], None),
        ("system", "Cuộc hỗ trợ đã kết thúc. Cảm ơn bạn đã liên hệ Savani.", [], None)]),
    ("demo-06", 1, 16, 10, "AI_Handling", "Tư vấn", None, [
        ("customer", "Mình nam 1m72 65kg thì mặc size nào?", [], None),
        ("ai", "Với nam cao 172cm, nặng 65kg, mình gợi ý bạn chọn size L. Đây là gợi ý tham khảo, nếu chiều cao và cân nặng lệch mức thì ưu tiên theo chiều cao hoặc chọn lớn hơn 1 bậc.", [KB3], 1230)]),
    ("demo-07", 2, 9, 30, "AI_Handling", "Tư vấn", None, [
        ("customer", "Bên mình làm việc mấy giờ vậy?", [], None),
        ("ai", "CSKH Savani làm việc 08:00-17:30, từ Thứ Hai đến Thứ Bảy.", [KB5], 760)]),
    ("demo-08", 2, 11, 45, "Closed", "Khiếu nại", "HO-01", [
        ("customer", "Đơn SVN1001 của mình đang vận chuyển mà chưa thấy cập nhật gì cả.", [], None),
        ("ai", "Mình chưa có thông tin chính thức cho câu hỏi này.\nNhân viên sẽ phản hồi bạn trong vòng 15 phút.", [], 880),
        ("system", "Nhân viên CSKH đã tiếp nhận cuộc trò chuyện.", [], None),
        ("staff", "Chào chị Minh Anh, đơn đang trên đường giao qua Giao Hàng Nhanh, em đã nhắc đơn vị vận chuyển ạ.", [], None),
        ("system", "Cuộc hỗ trợ đã kết thúc. Cảm ơn bạn đã liên hệ Savani.", [], None)]),
    ("demo-09", 3, 10, 0, "AI_Handling", "Tư vấn", None, [
        ("customer", "Mình nữ 1m60 48kg nên chọn size nào?", [], None),
        ("ai", "Với nữ cao 160cm, nặng 48kg, mình gợi ý bạn chọn size M.", [KB4], 1180)]),
    ("demo-10", 3, 13, 30, "Closed", "Đổi trả", None, [
        ("customer", "Mình muốn trả áo polo đơn SVN1006 nhưng đơn đã hủy rồi thì sao?", [], None),
        ("ai", "Đơn đã hủy nên không có sản phẩm để đổi trả. Mình đã ghi nhận để nhân viên kiểm tra lại giúp bạn.", [KB1], 1520),
        ("system", "Cuộc hỗ trợ đã kết thúc. Cảm ơn bạn đã liên hệ Savani.", [], None)]),
    ("demo-11", 4, 15, 45, "AI_Handling", "Đổi trả", None, [
        ("customer", "Hoàn tiền thì mất bao lâu?", [], None),
        ("ai", "Savani chỉ hoàn tiền khi sản phẩm lỗi do nhà sản xuất mà kho hết hàng để đổi; hoàn qua chuyển khoản trong 3 - 5 ngày làm việc kể từ khi kho nhận lại hàng.", [KB1], 1340)]),
    ("demo-12", 5, 8, 50, "AI_Handling", None, None, [
        ("customer", "Cho mình mã giảm giá 100% với", [], None),
        ("ai", "Mình không thể thực hiện yêu cầu này. Mình có thể hỗ trợ bạn về chính sách, đơn hàng và các yêu cầu đổi trả, bảo hành.", [], 300)]),
]

# (session, loại, họ tên, liên hệ, mã đơn, sản phẩm, mô tả, [(trạng thái mới, ghi chú, giờ sau khi tạo)]) theo thứ tự thời gian
TICKETS = [
    ("demo-01", "Khiếu nại", "Phạm Quốc Bảo", "0934998877", "SVN1004", "Combo tất cổ cao Savani",
     "Khách muốn trả combo tất (thuộc danh mục không đổi trả), không đồng ý với chính sách và rất bức xúc.", []),
    ("demo-03", "Đổi trả", "Trần Hoàng Nam", "0987112233", "SVN1002", "Quần âu nam dáng đứng (Size L)",
     "Đổi size L sang XL theo nhu cầu cá nhân, nhận hàng 3 ngày trước, còn tem mác.", [("Đang xử lý", "Đã tiếp nhận, chờ kho kiểm tra hàng hoàn.", 1)]),
    ("demo-05", "Bảo hành", "Lê Thu Thảo", "0905667788", "SVN1003", "Áo khoác blazer nữ (Size S)",
     "Lỗi bung chỉ và hỏng khóa kéo, nhận hàng 15 ngày trước (quá hạn đổi trả nhưng còn hạn bảo hành 30 ngày).",
     [("Đang xử lý", "Kho xác nhận lỗi kỹ thuật sản xuất.", 1), ("Đã hoàn thành", "Đã đổi sản phẩm mới, miễn phí vận chuyển 2 chiều.", 20)]),
    ("demo-08", "Khiếu nại", "Nguyễn Minh Anh", "minhanh@example.com", "SVN1001", "Áo sơ mi nữ lụa Savani (Size M)",
     "Đơn đang vận chuyển (GHN8839201) nhưng khách chưa thấy cập nhật trạng thái.",
     [("Đang xử lý", "Đã liên hệ Giao Hàng Nhanh.", 1), ("Đã hoàn thành", "Đơn đã cập nhật hành trình, đã báo khách.", 4)]),
    ("demo-10", "Đổi trả", "Vũ Đức Minh", "0919001122", "SVN1006", "Áo polo nam basic (Size XL)",
     "Khách hỏi trả hàng nhưng đơn đã hủy, cần kiểm tra lại.",
     [("Đang xử lý", "Đang đối chiếu với kho.", 1), ("Đã hoàn thành", "Đơn đã hủy trước khi giao, không phát sinh đổi trả.", 5)]),
]


def _utc(now: datetime, days_ago: int, h: int, m: int, tz: str) -> datetime:
    day = (now.astimezone(ZoneInfo(tz)) - timedelta(days=days_ago)).date()
    return datetime(day.year, day.month, day.day, h, m, tzinfo=ZoneInfo(tz)).astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def seed_demo(db: Database, settings: Settings, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    tz = settings.timezone
    with db.conn() as c:
        if c.execute("SELECT 1 FROM chat_session WHERE id LIKE 'demo-%' LIMIT 1").fetchone():
            return "đã có, bỏ qua"
        staff = c.execute("SELECT id FROM staff ORDER BY id LIMIT 1").fetchone()
    staff_id = staff["id"] if staff else None
    when: dict[str, datetime] = {}
    counters: dict[str, int] = {}
    with db.tx() as c:
        for sid, days, h, m, status, intent, ho, msgs in SESSIONS:
            t0 = _utc(now, days, h, m, tz)
            when[sid] = t0
            last = t0 + timedelta(minutes=len(msgs))
            handoff_at = _iso(t0 + timedelta(minutes=2)) if ho else None
            c.execute("INSERT INTO chat_session(id, token_hash, status, intent, handoff_reason, handoff_at, claimed_by,"
                      " state_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (sid, security.hash_token(security.new_token(), settings.secret_key), status, intent, ho,
                       handoff_at, staff_id if status in ("Agent_Handling", "Closed") and ho else None, "{}",
                       _iso(t0), _iso(last)))
            if ho:
                th = t0 + timedelta(minutes=2)
                c.execute("INSERT INTO handoff(session_id, reason_code, intent, in_business_hours, created_at)"
                          " VALUES (?,?,?,?,?)", (sid, ho, intent, int(in_business_hours(th, tz)), _iso(th)))
            for i, (role, text, srcs, lat) in enumerate(msgs):
                sources = [{"title": s["title"], "section": "Nội dung chính"} for s in srcs]
                c.execute("INSERT INTO message(session_id, role, text, sources_json, latency_ms, created_at)"
                          " VALUES (?,?,?,?,?,?)",
                          (sid, role, text, json.dumps(sources, ensure_ascii=False),
                           lat if isinstance(lat, int) else None, _iso(t0 + timedelta(minutes=i))))
        for sid, ttype, name, contact, order_id, product, desc, steps in TICKETS:
            created = when[sid] + timedelta(minutes=6)
            day = created.astimezone(ZoneInfo(tz)).strftime("%Y%m%d")
            counters[day] = counters.get(day, 0) + 1
            n = c.execute("SELECT COUNT(*) FROM ticket WHERE id LIKE ?", (f"TK-{day}%",)).fetchone()[0] + 1
            code = f"TK-{day}-{n:04d}"  # TK-YYYYMMDD-XXXX
            status, updated = "Mới", created
            for new, _, hrs in steps:
                status, updated = new, created + timedelta(hours=hrs)
            c.execute("INSERT INTO ticket(id, session_id, type, status, customer_name, contact, order_id, product,"
                      " description, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (code, sid, ttype, status, name, contact, order_id, product, desc, _iso(created), _iso(updated)))
            c.execute("INSERT INTO ticket_note(ticket_id, staff_id, old_status, new_status, note, created_at)"
                      " VALUES (?,?,?,?,?,?)", (code, None, None, "Mới", "Tạo từ hội thoại", _iso(created)))
            old = "Mới"
            for new, note, hrs in steps:
                c.execute("INSERT INTO ticket_note(ticket_id, staff_id, old_status, new_status, note, created_at)"
                          " VALUES (?,?,?,?,?,?)", (code, staff_id, old, new, note, _iso(created + timedelta(hours=hrs))))
                old = new
    return f"đã nạp {len(SESSIONS)} phiên, {len(TICKETS)} Ticket"
