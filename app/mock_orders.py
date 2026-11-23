"""SQLite Mock Order DB for the MVP. All records are fabricated demo data."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SEED_ORDERS = [
    ("SVN1001", "Áo sơ mi nữ lụa Savani (Size M)", "Đang vận chuyển", "23/11/2026 09:15", "1122", "minhanh@example.demo", "Đơn đã rời kho Hà Nội và đang được bàn giao cho đơn vị vận chuyển."),
    ("SVN1002", "Quần âu nam dáng đứng (Size L)", "Đã giao thành công", "22/10/2026 14:30", "2233", "nam@example.demo", "Đơn đã giao thành công; sản phẩm còn nguyên tem có thể tạo yêu cầu đổi size."),
    ("SVN1003", "Áo khoác blazer nữ (Size S)", "Đã giao thành công", "18/11/2026 16:05", "7788", "thao@example.demo", "Đơn đã giao thành công; lỗi kỹ thuật có thể gửi yêu cầu bảo hành."),
    ("SVN1004", "Combo tất cổ cao Savani", "Đã giao thành công", "21/11/2026 10:20", "8877", "bao@example.demo", "Đơn đã giao thành công; tất/vớ không thuộc diện đổi trả theo chính sách."),
    ("SVN1005", "Áo thun nam cổ tròn (Size XL)", "Đang xử lý tại kho", "23/11/2026 08:40", "4455", "huy@example.demo", "Kho đang đóng gói; dự kiến bàn giao đơn vị vận chuyển trong hôm nay."),
    ("SVN1006", "Áo polo nam basic (Size XL)", "Đã hủy", "23/11/2026 11:00", "1122", "minh@example.demo", "Đơn đã được hủy theo yêu cầu trước khi bàn giao đơn vị vận chuyển."),
]


class MockOrderStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        conn = self._conn()
        try:
            conn.execute("""CREATE TABLE IF NOT EXISTS mock_order(
                order_id TEXT PRIMARY KEY, product TEXT NOT NULL, status TEXT NOT NULL,
                updated_at TEXT NOT NULL, phone_last4 TEXT NOT NULL, email TEXT NOT NULL,
                detail TEXT NOT NULL
            )""")
            conn.executemany("INSERT OR IGNORE INTO mock_order VALUES (?,?,?,?,?,?,?)", SEED_ORDERS)
            conn.commit()
        finally:
            conn.close()

    def lookup(self, order_id: str, phone_last4: str = "", email: str = "") -> dict | None:
        """Return only permitted fields after order ID + verifier match; never reveal existence on failure."""
        normalized = order_id.strip().upper()
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM mock_order WHERE order_id=?", (normalized,)).fetchone()
        finally:
            conn.close()
        verifier_ok = bool(row and ((phone_last4.isdigit() and len(phone_last4) == 4 and
                                    phone_last4 == row["phone_last4"]) or
                                   (email.strip().lower() and email.strip().lower() == row["email"])))
        if not verifier_ok:
            return None
        return {"order_id": row["order_id"], "product": row["product"], "status": row["status"],
                "updated_at": row["updated_at"], "detail": row["detail"], "demo_only": True}
