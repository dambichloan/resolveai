"""Nghiệp vụ của Backend API, KHÔNG phụ thuộc framework web (FastAPI chỉ gọi vào đây).

Các điểm kiểm soát chính (Mục 25):
- phiên khách xác thực bằng session_id (UUIDv4) + session_token, DB chỉ lưu bản băm (NFR-SEC-04)
- giới hạn 15 tin/phút/phiên -> HTTP 429, không gọi Agent (NFR-SEC-05)
- client_msg_id chống xử lý trùng; khóa theo phiên xử lý tuần tự (NFR-PER-03)
- chỉ báo "đã tạo Ticket / đã chuyển" SAU khi ghi DB thành công (NFR-REL-01)
- tạo Ticket chỉ khi khách bấm Xác nhận (hành động có cấu trúc) và đủ trường (BR4, NFR-SEC-03)
"""
from __future__ import annotations

import json
import unicodedata
import re
import logging
import math
import threading
import time
import uuid
from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from . import security
from .agent_port import AgentInput, AgentOutput, AgentPort
from .config import Settings
from .db import Database
from .guardrails import guard_output, mask_card
from . import kb
from .hours import in_business_hours
from .ratelimit import SlidingWindowLimiter

log = logging.getLogger("resolveai")

CUSTOMER_ACTIONS = {"confirm_ticket", "reject_ticket", "request_handoff", "policy_return", "policy_warranty"}
ACTION_LABELS = {
    "confirm_ticket": "Xác nhận yêu cầu",
    "reject_ticket": "Chỉnh sửa yêu cầu",
    "request_handoff": "Gặp nhân viên",
    "policy_return": "Chính sách đổi trả",
    "policy_warranty": "Chính sách bảo hành",
}
TICKET_FLOW = ["Mới", "Đang xử lý", "Đã hoàn thành"]
TICKET_CODE_RE = r"^TK-\d{8}-\d{4}$"  # BR5: TK-YYYYMMDD-XXXX
TICKETS_NEED_ORDER = {"Đổi trả", "Bảo hành"}
SLA_IN_HOURS = "Nhân viên sẽ phản hồi bạn trong vòng 15 phút."
SLA_OUT_HOURS = ("Hiện đang ngoài giờ làm việc (08:00-17:30, Thứ Hai đến Thứ Bảy). "
                 "Nhân viên sẽ liên hệ trong 2 giờ đầu ca làm việc tiếp theo.")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str,
                 headers: dict[str, str] | None = None, extra: dict[str, Any] | None = None):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.headers = headers or {}
        self.extra = extra or {}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _slug(title: str) -> str:
    t = unicodedata.normalize("NFD", title.replace("đ", "d").replace("Đ", "D"))
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn").lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:60] or "tai-lieu"


class ChatService:
    def __init__(self, db: Database, settings: Settings, agent: AgentPort, *,
                 limiter: SlidingWindowLimiter | None = None,
                 now_fn: Callable[[], datetime] = utcnow,
                 sleep_fn: Callable[[float], None] = time.sleep):
        self.db, self.s, self.agent = db, settings, agent
        self.limiter = limiter or SlidingWindowLimiter(settings.rate_limit_per_min, 60.0)
        self.create_limiter = SlidingWindowLimiter(settings.session_create_limit_per_min, 60.0)
        self.now, self.sleep = now_fn, sleep_fn
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._kb_lock = threading.Lock()

    # ================================================================ tiện ích
    def _lock_for(self, session_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(session_id, threading.Lock())

    def _hours(self) -> bool:
        return in_business_hours(self.now(), self.s.timezone)

    @staticmethod
    def _msg(r) -> dict:
        return {"id": r["id"], "role": r["role"], "text": r["text"],
                "sources": json.loads(r["sources_json"]),
                "ui": json.loads(r["ui_json"]) if r["ui_json"] else None,
                "created_at": r["created_at"]}

    def _add_message(self, c, session_id: str, role: str, text: str, *, sources=None, ui=None,
                     client_msg_id: str | None = None, latency_ms: int | None = None) -> int:
        cur = c.execute(
            "INSERT INTO message(session_id, role, text, sources_json, ui_json, client_msg_id, latency_ms,"
            " created_at) VALUES (?,?,?,?,?,?,?,?)",
            (session_id, role, text, json.dumps(sources or [], ensure_ascii=False),
             json.dumps(ui, ensure_ascii=False) if ui else None, client_msg_id, latency_ms,
             _iso(self.now())))
        c.execute("UPDATE chat_session SET updated_at=? WHERE id=?", (_iso(self.now()), session_id))
        return cur.lastrowid

    def _auth_session(self, c, session_id: str | None, token: str | None):
        row = c.execute("SELECT * FROM chat_session WHERE id=?", (session_id or "",)).fetchone()
        if not row or not security.verify_token(token, row["token_hash"], self.s.secret_key):
            raise ApiError(403, "invalid_session", "Phiên không hợp lệ hoặc đã hết hạn.")
        return row

    def _payload(self, session_id: str, from_id: int, new_token: str | None = None) -> dict:
        with self.db.conn() as c:
            st = c.execute("SELECT status FROM chat_session WHERE id=?", (session_id,)).fetchone()["status"]
            rows = c.execute("SELECT * FROM message WHERE session_id=? AND id>=? ORDER BY id",
                             (session_id, from_id)).fetchall()
        out = {"session_id": session_id, "status": st, "messages": [self._msg(r) for r in rows]}
        if new_token:
            out["session_token"] = new_token
        return out

    # ================================================================ khách hàng
    def post_message(self, session_id: str | None, token: str | None, text: str | None,
                     client_msg_id: str | None = None, action: str | None = None,
                     client_ip: str | None = None) -> dict:
        text = (text or "").strip()
        if action is not None and action not in CUSTOMER_ACTIONS:
            raise ApiError(422, "invalid_action", "Hành động không hợp lệ.")
        if action is None and not text:
            raise ApiError(422, "empty_message", "Tin nhắn không được để trống.")
        if len(text) > self.s.max_message_len:
            raise ApiError(422, "message_too_long",
                           f"Tin nhắn tối đa {self.s.max_message_len} ký tự.")
        if client_msg_id is not None and len(client_msg_id) > 64:
            raise ApiError(422, "invalid_client_msg_id", "client_msg_id quá dài.")

        new_token = None
        if not session_id:
            wait = self.create_limiter.hit(client_ip or "unknown")
            if wait is not None:
                self._raise_429(wait)
            session_id, new_token = str(uuid.uuid4()), security.new_token()
            now = _iso(self.now())
            with self.db.tx() as c:
                c.execute("INSERT INTO chat_session(id, token_hash, created_at, updated_at) VALUES (?,?,?,?)",
                          (session_id, security.hash_token(new_token, self.s.secret_key), now, now))
        else:
            with self.db.conn() as c:
                row = self._auth_session(c, session_id, token)
            if row["status"] == "Closed":
                raise ApiError(409, "session_closed", "Cuộc hỗ trợ đã kết thúc. Bạn có thể bắt đầu cuộc mới.")

        if client_msg_id:  # gửi lại cùng một tin (mạng chập chờn, bấm nhiều lần): trả kết quả cũ
            with self.db.conn() as c:
                dup = c.execute("SELECT id FROM message WHERE session_id=? AND client_msg_id=?",
                                (session_id, client_msg_id)).fetchone()
            if dup:
                return self._payload(session_id, dup["id"], new_token)

        wait = self.limiter.hit(session_id)
        if wait is not None:
            self._raise_429(wait)

        with self._lock_for(session_id):
            return self._process(session_id, new_token, text, client_msg_id, action)

    @staticmethod
    def _raise_429(wait: float):
        secs = max(1, math.ceil(wait))
        raise ApiError(429, "rate_limited", f"Bạn gửi quá nhanh, vui lòng đợi khoảng {secs} giây.",
                       headers={"Retry-After": str(secs)}, extra={"retry_after": secs})

    def get_messages(self, session_id: str, token: str | None, after: int = 0) -> dict:
        with self.db.conn() as c:
            row = self._auth_session(c, session_id, token)
            rows = c.execute("SELECT * FROM message WHERE session_id=? AND id>? ORDER BY id",
                             (session_id, after)).fetchall()
        return {"session_id": session_id, "status": row["status"], "messages": [self._msg(r) for r in rows]}

    def close_customer(self, session_id: str, token: str | None) -> dict:
        """Let a customer close only an AI-resolved conversation.

        A conversation waiting for or handled by staff remains staff-owned; a customer
        must not be able to remove it from the support queue.
        """
        with self._lock_for(session_id):
            with self.db.tx() as c:
                row = self._auth_session(c, session_id, token)
                if row["status"] == "Closed":
                    return {"session_id": session_id, "status": "Closed"}
                if row["status"] != "AI_Handling" or row["handoff_reason"]:
                    raise ApiError(409, "session_not_closable",
                                   "Chỉ có thể kết thúc cuộc trò chuyện khi trợ lý AI đang hỗ trợ.")
                c.execute("UPDATE chat_session SET status='Closed', updated_at=? WHERE id=?",
                          (_iso(self.now()), session_id))
        return {"session_id": session_id, "status": "Closed"}

    # ---------------------------------------------------------------- một lượt
    def _process(self, session_id: str, new_token: str | None, text: str, client_msg_id: str | None,
                 action: str | None) -> dict:
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM chat_session WHERE id=?", (session_id,)).fetchone()
            if row["status"] == "Closed":
                raise ApiError(409, "session_closed", "Cuộc hỗ trợ đã kết thúc. Bạn có thể bắt đầu cuộc mới.")
            if client_msg_id:
                dup = c.execute("SELECT id FROM message WHERE session_id=? AND client_msg_id=?",
                                (session_id, client_msg_id)).fetchone()
                if dup:
                    cust_id, duplicate = dup["id"], True
                else:
                    duplicate = False
            else:
                duplicate = False
            if not duplicate:
                cust_id = self._add_message(c, session_id, "customer", mask_card(text) or ACTION_LABELS.get(action, ""),
                                            client_msg_id=client_msg_id)
            status, state = row["status"], json.loads(row["state_json"])
        if duplicate or status != "AI_Handling":
            # Waiting_Agent / Agent_Handling: lưu tin cho nhân viên, Agent không chạy (Mục 20.2.1)
            return self._payload(session_id, cust_id, new_token)

        inp = AgentInput(session_id, text, action, state, self._hours())
        started = time.perf_counter()
        out, err = self._run_agent(inp)
        latency = int((time.perf_counter() - started) * 1000)
        if out is not None:
            out.reply = guard_output(out.reply)

        if err is not None:  # NFR-REC-01: hết lần thử, bảo toàn lịch sử và chuyển hàng đợi
            self._handoff(session_id, state.get("intent"), "HO-08", state,
                          lead="Hệ thống đang gián đoạn tạm thời.", sources=[], latency=latency)
        elif out.create_ticket is not None:
            self._ticket(session_id, inp, out, latency)
        elif out.handoff_reason:
            self._handoff(session_id, out.intent or state.get("intent"), out.handoff_reason, out.state,
                          lead=out.reply, sources=out.sources, latency=latency, meta=out.meta)
        else:
            self._finish(session_id, out.state, out.intent, out.reply, out.sources, out.ui, latency, meta=out.meta)
        return self._payload(session_id, cust_id, new_token)

    def _run_agent(self, inp: AgentInput) -> tuple[AgentOutput | None, Exception | None]:
        last: Exception | None = None
        for attempt in range(3):  # 1 lần đầu + tối đa 2 lần thử lại (NFR-REC-01)
            try:
                return self.agent.run_turn(inp), None
            except Exception as e:  # noqa: BLE001
                last = e
                log.warning("agent lỗi (lần %d): %s", attempt + 1, type(e).__name__)
                if attempt < 2:
                    self.sleep(0.5 * (2 ** attempt))
        return None, last

    def _with_retries(self, fn: Callable[[], Any]) -> Any:
        last: Exception | None = None
        for attempt in range(3):
            try:
                return fn()
            except Exception as e:  # noqa: BLE001
                last = e
                log.warning("ghi DB lỗi (lần %d): %s", attempt + 1, type(e).__name__)
                if attempt < 2:
                    self.sleep(0.3 * (2 ** attempt))
        raise last  # type: ignore[misc]

    def _finish(self, session_id: str, state: dict, intent: str | None, reply: str, sources, ui,
                latency: int | None, role: str = "ai", meta: dict | None = None) -> None:
        with self.db.tx() as c:
            c.execute("UPDATE chat_session SET state_json=?, intent=COALESCE(?, intent) WHERE id=?",
                      (json.dumps(state, ensure_ascii=False), intent, session_id))
            self._add_message(c, session_id, role, reply, sources=sources, ui=ui, latency_ms=latency)
            self._record_usage(c, session_id, meta or {})

    def _record_usage(self, c, session_id: str, meta: dict) -> None:
        usage = meta.get("usage") if isinstance(meta, dict) else None
        if not isinstance(usage, dict):
            return
        try:
            input_tokens = max(0, int(usage.get("input_tokens") or 0))
            output_tokens = max(0, int(usage.get("output_tokens") or 0))
        except (TypeError, ValueError):
            return
        if not input_tokens and not output_tokens:
            return
        model = str(meta.get("model") or self.s.llm_model)[:120]
        cost = ((input_tokens * self.s.llm_input_cost_per_million_usd) +
                (output_tokens * self.s.llm_output_cost_per_million_usd)) / 1_000_000
        now = _iso(self.now())
        c.execute("INSERT INTO usage_event(session_id, model, input_tokens, output_tokens, estimated_cost_usd, created_at) "
                  "VALUES (?,?,?,?,?,?)", (session_id, model, input_tokens, output_tokens, cost, now))
        if cost >= self.s.cost_alert_per_conversation_usd > 0:
            log.warning("Cảnh báo chi phí hội thoại: session=%s estimated_usd=%.4f", session_id[:8], cost)
        day = now[:10]
        daily = c.execute("SELECT COALESCE(SUM(estimated_cost_usd),0) FROM usage_event WHERE created_at>=?",
                          (day,)).fetchone()[0]
        if daily >= self.s.cost_alert_daily_usd > 0 and daily - cost < self.s.cost_alert_daily_usd:
            log.warning("Cảnh báo chi phí ngày: estimated_usd=%.4f threshold=%.4f", daily, self.s.cost_alert_daily_usd)

    def _fail_message(self, session_id: str, ui=None, latency: int | None = None) -> None:
        text = ("Xin lỗi, hệ thống chưa thể hoàn tất thao tác này. Vui lòng thử lại sau ít phút hoặc liên hệ "
                f"hotline {self.s.hotline}.")
        with self.db.tx() as c:
            self._add_message(c, session_id, "ai", text, ui=ui, latency_ms=latency)

    # ---------------------------------------------------------------- Handoff
    def _handoff_write(self, session_id: str, intent: str | None, reason: str, hours: bool) -> None:
        now = _iso(self.now())
        with self.db.tx() as c:
            cur = c.execute("UPDATE chat_session SET status='Waiting_Agent', handoff_reason=?, handoff_at=?,"
                            " intent=COALESCE(?, intent), updated_at=? WHERE id=? AND status='AI_Handling'",
                            (reason, now, intent, now, session_id))
            if cur.rowcount != 1:
                raise RuntimeError("phiên không còn ở AI_Handling")
            c.execute("INSERT INTO handoff(session_id, reason_code, intent, in_business_hours, created_at)"
                      " VALUES (?,?,?,?,?)", (session_id, reason, intent, int(hours), now))

    def _handoff(self, session_id: str, intent: str | None, reason: str, state: dict, *, lead: str,
                 sources, latency: int | None, meta: dict | None = None) -> None:
        hours = self._hours()
        try:
            self._with_retries(lambda: self._handoff_write(session_id, intent, reason, hours))
        except Exception:  # noqa: BLE001  (EX-COM-05: không báo thành công giả)
            log.exception("handoff thất bại")
            self._fail_message(session_id, latency=latency)
            return
        # Chỉ thông báo SAU khi ghi hàng đợi thành công (FR-COM-10, NFR-REL-01)
        notice = (lead.strip() + "\n" if lead.strip() else "") + (SLA_IN_HOURS if hours else SLA_OUT_HOURS)
        self._finish(session_id, state, None, notice, sources,
                     {"type": "handoff_notice", "in_business_hours": hours}, latency, meta=meta)

    # ---------------------------------------------------------------- Ticket
    def _ticket(self, session_id: str, inp: AgentInput, out: AgentOutput, latency: int) -> None:
        req = out.create_ticket or {}
        needed = ["type", "customer_name", "contact", "description"]
        if req.get("type") in TICKETS_NEED_ORDER:
            needed += ["order_id", "product"]
        # Execution/Handoff Guard (BR4): phải có hành động xác nhận của khách VÀ đã có cờ chờ xác nhận
        # trong trạng thái TRƯỚC lượt này, VÀ đủ trường. Không tin Agent tự báo "đã xác nhận".
        allowed = (inp.action == "confirm_ticket" and inp.state.get("awaiting_confirm") is True
                   and all(str(req.get(k, "")).strip() for k in needed))
        if not allowed:
            self._finish(session_id, inp.state, None,
                         "Mình chưa thể tạo yêu cầu vì còn thiếu thông tin hoặc chưa được bạn xác nhận.",
                         [], None, latency)
            return
        try:
            code, deduped = self._with_retries(lambda: self._ticket_write(session_id, req))
        except Exception:  # noqa: BLE001
            log.exception("tạo Ticket thất bại")
            # giữ nguyên bản nháp, gửi lại thẻ tóm tắt để khách bấm xác nhận lại
            ui = {"type": "ticket_summary", "ticket_type": req.get("type"),
                  "fields": [{"label": k, "value": req[k]} for k in
                             ("customer_name", "contact", "order_id", "product", "description") if req.get(k)]}
            self._fail_message(session_id, ui=ui, latency=latency)
            return
        if deduped:
            msg = f"Mình đã bổ sung thông tin vào yêu cầu {code} đang mở của bạn."
        else:
            msg = (f"Mình đã ghi nhận yêu cầu của bạn với mã {code}. Nhân viên CSKH sẽ xem xét và liên hệ "
                   "với bạn. Lưu ý: mình chỉ ghi nhận, không xác nhận đổi hàng, bảo hành hay hoàn tiền.")
        self._finish(session_id, out.state, out.intent, msg, [],
                     {"type": "ticket_created", "code": code, "deduplicated": deduped}, latency, meta=out.meta)

    def _ticket_write(self, session_id: str, req: dict) -> tuple[str, bool]:
        now_dt = self.now()
        now = _iso(now_dt)
        with self.db.tx() as c:
            if req.get("order_id"):  # chống trùng: cùng phiên + mã đơn + loại + đang ở trạng thái Mới (OPEN-08)
                dup = c.execute("SELECT id, description FROM ticket WHERE session_id=? AND type=? AND order_id=?"
                                " AND status='Mới'", (session_id, req["type"], req["order_id"])).fetchone()
                if dup:
                    c.execute("UPDATE ticket SET description=?, updated_at=? WHERE id=?",
                              (dup["description"] + "\n[Bổ sung] " + req["description"], now, dup["id"]))
                    return dup["id"], True
            day = now_dt.astimezone(ZoneInfo(self.s.timezone)).strftime("%Y%m%d")
            n = c.execute("SELECT COUNT(*) FROM ticket WHERE id LIKE ?", (f"TK-{day}%",)).fetchone()[0] + 1
            code = f"TK-{day}-{n:04d}"  # TK-YYYYMMDD-XXXX
            c.execute("INSERT INTO ticket(id, session_id, type, customer_name, contact, order_id, product,"
                      " description, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (code, session_id, req["type"], req["customer_name"], req["contact"], req.get("order_id"),
                       req.get("product"), req["description"], now, now))
            c.execute("INSERT INTO ticket_note(ticket_id, staff_id, old_status, new_status, note, created_at)"
                      " VALUES (?,?,?,?,?,?)", (code, None, None, "Mới", "Tạo từ hội thoại", now))
            return code, False

    # ================================================================ nhân viên
    def ensure_bootstrap_admin(self) -> None:
        """Tạo hoặc đồng bộ tài khoản quản trị từ biến môi trường."""
        username = (self.s.admin_user or "").strip()
        password = self.s.admin_password or ""
        if not username or not password:
            return
        with self.db.tx() as c:
            row = c.execute("SELECT id, password_hash FROM staff WHERE username=?", (username,)).fetchone()
            if row is None:
                c.execute("INSERT INTO staff(username, password_hash, created_at) VALUES (?,?,?)",
                          (username, security.hash_password(password), _iso(self.now())))
            elif not security.check_password(password, row["password_hash"]):
                # Giữ tài khoản bootstrap đồng bộ với ADMIN_BOOTSTRAP_PASSWORD.
                # Nhờ đó đổi biến môi trường trên Render cũng đặt lại được mật khẩu.
                c.execute("UPDATE staff SET password_hash=? WHERE id=?",
                          (security.hash_password(password), row["id"]))

    def login_staff(self, username: str | None, password: str | None) -> dict:
        username = (username or "").strip()
        password = password or ""
        if not username or not password:
            raise ApiError(422, "missing_credentials", "Cần nhập tên đăng nhập và mật khẩu.")
        now = self.now()
        with self.db.tx() as c:
            c.execute("DELETE FROM staff_session WHERE expires_at<=?", (_iso(now),))
            row = c.execute("SELECT id, username, password_hash FROM staff WHERE username=?", (username,)).fetchone()
            if row is None or not security.check_password(password, row["password_hash"]):
                raise ApiError(401, "invalid_credentials", "Tên đăng nhập hoặc mật khẩu không đúng.")
            token = security.new_token()
            expires = now + timedelta(hours=max(1, self.s.staff_session_hours))
            c.execute("INSERT INTO staff_session(token_hash, staff_id, expires_at) VALUES (?,?,?)",
                      (security.hash_token(token, self.s.secret_key), row["id"], _iso(expires)))
        return {"id": row["id"], "username": row["username"], "token": token, "expires_at": _iso(expires)}

    def logout_staff(self, token: str | None) -> None:
        if not token:
            return
        with self.db.tx() as c:
            c.execute("DELETE FROM staff_session WHERE token_hash=?", (security.hash_token(token, self.s.secret_key),))

    def require_staff(self, token: str | None = None) -> dict:
        if not token:
            raise ApiError(401, "staff_auth_required", "Bạn cần đăng nhập trang quản trị.")
        now = self.now()
        token_hash = security.hash_token(token, self.s.secret_key)
        with self.db.tx() as c:
            c.execute("DELETE FROM staff_session WHERE expires_at<=?", (_iso(now),))
            row = c.execute("SELECT s.id, s.username, ss.expires_at FROM staff_session ss "
                            "JOIN staff s ON s.id=ss.staff_id WHERE ss.token_hash=?", (token_hash,)).fetchone()
        if row is None:
            raise ApiError(401, "staff_auth_required", "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.")
        return {"id": row["id"], "username": row["username"], "expires_at": row["expires_at"]}

    def queue(self) -> list[dict]:
        with self.db.conn() as c:
            rows = c.execute("SELECT * FROM chat_session WHERE status='Waiting_Agent' ORDER BY handoff_at").fetchall()
            out = []
            for r in rows:
                last = c.execute("SELECT text FROM message WHERE session_id=? AND role='customer'"
                                 " ORDER BY id DESC LIMIT 1", (r["id"],)).fetchone()
                tickets = [t["id"] for t in c.execute("SELECT id FROM ticket WHERE session_id=?", (r["id"],))]
                out.append({"session_id": r["id"], "intent": r["intent"], "handoff_reason": r["handoff_reason"],
                            "handoff_at": r["handoff_at"], "last_customer_message": (last["text"] if last else "")[:120],
                            "tickets": tickets})
        return out

    def claim(self, staff: dict, session_id: str) -> dict:
        now = _iso(self.now())
        with self.db.tx() as c:
            exists = c.execute("SELECT 1 FROM chat_session WHERE id=?", (session_id,)).fetchone()
            if not exists:
                raise ApiError(404, "not_found", "Không tìm thấy phiên.")
            cur = c.execute("UPDATE chat_session SET status='Agent_Handling', claimed_by=?, updated_at=?"
                            " WHERE id=? AND status='Waiting_Agent'", (staff["id"], now, session_id))
            if cur.rowcount != 1:  # người khác đã tiếp nhận (hoặc phiên không còn chờ)
                raise ApiError(409, "already_claimed", "Phiên này đã được tiếp nhận hoặc không còn trong hàng đợi.")
            self._add_message(c, session_id, "system", "Nhân viên CSKH đã tiếp nhận cuộc trò chuyện.")
        return self.session_detail(session_id)

    def staff_message(self, staff: dict, session_id: str, text: str) -> dict:
        text = (text or "").strip()
        if not text:
            raise ApiError(422, "empty_message", "Tin nhắn không được để trống.")
        if len(text) > self.s.max_message_len:
            raise ApiError(422, "message_too_long", f"Tin nhắn tối đa {self.s.max_message_len} ký tự.")
        with self.db.tx() as c:
            row = c.execute("SELECT status FROM chat_session WHERE id=?", (session_id,)).fetchone()
            if not row:
                raise ApiError(404, "not_found", "Không tìm thấy phiên.")
            if row["status"] != "Agent_Handling":
                raise ApiError(409, "not_handling", "Cần tiếp nhận phiên trước khi nhắn tin.")
            self._add_message(c, session_id, "staff", text)
        return self.session_detail(session_id)

    def close(self, staff: dict, session_id: str) -> dict:
        now = _iso(self.now())
        with self.db.tx() as c:
            if not c.execute("SELECT 1 FROM chat_session WHERE id=?", (session_id,)).fetchone():
                raise ApiError(404, "not_found", "Không tìm thấy phiên.")
            cur = c.execute("UPDATE chat_session SET status='Closed', updated_at=? WHERE id=?"
                            " AND status='Agent_Handling'", (now, session_id))
            if cur.rowcount != 1:
                raise ApiError(409, "not_handling", "Chỉ kết thúc được phiên đang được nhân viên hỗ trợ.")
            self._add_message(c, session_id, "system", "Cuộc hỗ trợ đã kết thúc. Cảm ơn bạn đã liên hệ Savani.")
        return self.session_detail(session_id)

    def list_sessions(self, status: str | None = None, intent: str | None = None, limit: int = 100) -> list[dict]:
        q, args = "SELECT * FROM chat_session WHERE 1=1", []
        if status:
            q += " AND status=?"; args.append(status)
        if intent:
            q += " AND intent=?"; args.append(intent)
        q += " ORDER BY updated_at DESC LIMIT ?"; args.append(max(1, min(limit, 500)))
        with self.db.conn() as c:
            return [{"session_id": r["id"], "status": r["status"], "intent": r["intent"],
                     "handoff_reason": r["handoff_reason"], "created_at": r["created_at"],
                     "updated_at": r["updated_at"]} for r in c.execute(q, args)]

    def session_detail(self, session_id: str, after: int = 0) -> dict:
        with self.db.conn() as c:
            r = c.execute("SELECT * FROM chat_session WHERE id=?", (session_id,)).fetchone()
            if not r:
                raise ApiError(404, "not_found", "Không tìm thấy phiên.")
            msgs = [self._msg(m) for m in c.execute(
                "SELECT * FROM message WHERE session_id=? AND id>? ORDER BY id", (session_id, after))]
            tickets = [{"id": t["id"], "type": t["type"], "status": t["status"]}
                       for t in c.execute("SELECT * FROM ticket WHERE session_id=?", (session_id,))]
        sources, seen = [], set()
        for m in msgs:
            for s in m["sources"]:
                key = (s.get("title"), s.get("section"))
                if key not in seen:
                    seen.add(key); sources.append(s)
        return {"session_id": r["id"], "status": r["status"], "intent": r["intent"],
                "handoff_reason": r["handoff_reason"], "created_at": r["created_at"],
                "messages": msgs, "sources": sources, "tickets": tickets}

    # ---- Ticket
    def list_tickets(self, status: str | None = None, ttype: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM ticket WHERE 1=1", []
        if status:
            q += " AND status=?"; args.append(status)
        if ttype:
            q += " AND type=?"; args.append(ttype)
        q += " ORDER BY created_at DESC, id DESC LIMIT 500"
        with self.db.conn() as c:
            return [dict(r) for r in c.execute(q, args)]

    def ticket_detail(self, ticket_id: str) -> dict:
        with self.db.conn() as c:
            t = c.execute("SELECT * FROM ticket WHERE id=?", (ticket_id,)).fetchone()
            if not t:
                raise ApiError(404, "not_found", "Không tìm thấy Ticket.")
            notes = [dict(n) for n in c.execute("SELECT * FROM ticket_note WHERE ticket_id=? ORDER BY id",
                                                (ticket_id,))]
        return {**dict(t), "history": notes}

    def update_ticket_status(self, staff: dict, ticket_id: str, new_status: str, note: str | None) -> dict:
        if new_status not in TICKET_FLOW:
            raise ApiError(422, "invalid_status", "Trạng thái không hợp lệ.")
        note = (note or "").strip()
        now = _iso(self.now())
        with self.db.tx() as c:
            t = c.execute("SELECT status FROM ticket WHERE id=?", (ticket_id,)).fetchone()
            if not t:
                raise ApiError(404, "not_found", "Không tìm thấy Ticket.")
            if TICKET_FLOW.index(new_status) != TICKET_FLOW.index(t["status"]) + 1:
                raise ApiError(409, "invalid_transition",
                               "Chỉ được chuyển tuần tự: Mới, Đang xử lý, Đã hoàn thành.")
            if new_status == "Đã hoàn thành" and not note:  # FR-COM-11
                raise ApiError(422, "note_required", "Cần nhập ghi chú kết quả xử lý trước khi hoàn thành.")
            c.execute("UPDATE ticket SET status=?, updated_at=? WHERE id=?", (new_status, now, ticket_id))
            c.execute("INSERT INTO ticket_note(ticket_id, staff_id, old_status, new_status, note, created_at)"
                      " VALUES (?,?,?,?,?,?)", (ticket_id, staff["id"], t["status"], new_status, note, now))
        return self.ticket_detail(ticket_id)

    # ---- Dashboard (FR-ADM-05)
    def dashboard(self, date_from: str | None = None, date_to: str | None = None) -> dict:
        lo = date_from or "0000-01-01"
        hi = (date_to + "T23:59:59") if date_to else "9999-12-31"
        with self.db.conn() as c:
            total = c.execute("SELECT COUNT(*) FROM chat_session WHERE created_at>=? AND created_at<=?",
                              (lo, hi)).fetchone()[0]
            ai_only = c.execute("SELECT COUNT(*) FROM chat_session WHERE created_at>=? AND created_at<=?"
                                " AND status='Closed' AND handoff_reason IS NULL", (lo, hi)).fetchone()[0]
            intents = {(r["i"] or "Chưa phân loại"): r["n"] for r in c.execute(
                "SELECT intent AS i, COUNT(*) AS n FROM chat_session WHERE created_at>=? AND created_at<=?"
                " GROUP BY intent", (lo, hi))}
            tickets = {r["status"]: r["n"] for r in c.execute(
                "SELECT status, COUNT(*) AS n FROM ticket WHERE created_at>=? AND created_at<=? GROUP BY status",
                (lo, hi))}
            lat = c.execute("SELECT AVG(latency_ms) FROM message WHERE role='ai' AND latency_ms IS NOT NULL"
                            " AND created_at>=? AND created_at<=?", (lo, hi)).fetchone()[0]
            cost = c.execute("SELECT COALESCE(SUM(estimated_cost_usd),0) FROM usage_event WHERE created_at>=? "
                             "AND created_at<=?", (lo, hi)).fetchone()[0]
        return {"total_sessions": total, "ai_self_resolved_rate": round(ai_only / total, 3) if total else None,
                "intent_distribution": intents,
                "tickets_by_status": {s: tickets.get(s, 0) for s in TICKET_FLOW},
                "avg_latency_ms": round(lat) if lat is not None else None,
                "estimated_cost_usd": round(float(cost), 6)}

    # ---- Kho tài liệu KB: phiên bản hiện hành ở policies/, lịch sử ở .history/
    def kb_list(self) -> list[dict]:
        return [{k: v for k, v in d.items() if k != "content"} for d in kb.load_docs(self.s.policies_dir)]

    def kb_get(self, doc_code: str) -> dict:
        for d in kb.load_docs(self.s.policies_dir):
            if d["doc_code"] == doc_code:
                return d
        raise ApiError(404, "not_found", "Không tìm thấy tài liệu.")

    # ---- Quản lý KB (FR-ADM-02): Markdown hiện hành có front matter; bản cũ được lưu lịch sử.
    KB_TYPES = ("policy", "faq")
    KB_MAX_TITLE, KB_MAX_CONTENT = 200, 20000

    def _kb_validate(self, title: str | None, content: str | None, doc_type: str | None,
                     effective_date: str | None) -> tuple[str, str, str, str]:
        title = " ".join((title or "").split())
        content = (content or "").replace("\r\n", "\n").strip()
        doc_type = (doc_type or "policy").strip()
        if not title or not content:
            raise ApiError(422, "empty_doc", "Cần nhập cả tiêu đề và nội dung tài liệu.")
        if len(title) > self.KB_MAX_TITLE or len(content) > self.KB_MAX_CONTENT:
            raise ApiError(422, "doc_too_long", f"Tiêu đề tối đa {self.KB_MAX_TITLE} ký tự, "
                                                f"nội dung tối đa {self.KB_MAX_CONTENT} ký tự.")
        if doc_type not in self.KB_TYPES:
            raise ApiError(422, "bad_doc_type", "Loại tài liệu không hợp lệ.")
        today = self.now().astimezone(ZoneInfo(self.s.timezone)).date()
        try:
            eff = datetime.strptime(effective_date, "%Y-%m-%d").date() if effective_date else today
        except ValueError:
            raise ApiError(422, "bad_date", "Ngày hiệu lực phải có dạng YYYY-MM-DD.") from None
        return title, content, doc_type, eff.isoformat()

    @staticmethod
    def _next_version(value: object) -> str:
        try:
            return f"{float(str(value or '1.0')) + 0.1:.1f}"
        except ValueError:
            return "1.1"

    @staticmethod
    def _doc_text(code: str, title: str, content: str, doc_type: str, version: str,
                  effective_date: str, active: bool, source_file: str) -> str:
        return (f"---\ndoc_code: {code}\ntitle: {title}\ndoc_type: {doc_type}\nversion: {version}\n"
                f"effective_date: {effective_date}\nis_active: {'true' if active else 'false'}\n"
                f"source_file: {source_file}\n---\n\n{content}\n")

    def _kb_path(self, doc: dict) -> Any:
        filename = str(doc.get("source_file") or "")
        path = (self.s.policies_dir / filename).resolve()
        if path.parent != self.s.policies_dir.resolve() or path.suffix.lower() != ".md":
            raise ApiError(409, "invalid_doc_source", "Tệp nguồn của tài liệu không hợp lệ.")
        return path

    def _kb_reload(self, code: str) -> None:
        reload_kb = getattr(self.agent, "reload_kb", None)
        if reload_kb:
            try:
                reload_kb()
            except Exception:  # noqa: BLE001
                log.warning("Agent chưa nạp lại được kho tài liệu: %s", code)

    def kb_create(self, title: str | None, content: str | None, doc_type: str | None = None,
                  effective_date: str | None = None) -> dict:
        title, content, doc_type, eff = self._kb_validate(title, content, doc_type, effective_date)
        with self._kb_lock:                                # tránh hai người thêm cùng lúc trùng mã
            pdir = self.s.policies_dir
            pdir.mkdir(parents=True, exist_ok=True)
            docs = kb.load_docs(pdir)
            if any(d["title"].strip().lower() == title.lower() and d["is_active"] for d in docs):
                raise ApiError(409, "duplicate_title", "Đã có tài liệu đang hiệu lực với tiêu đề này.")
            nums = [int(m.group(1)) for d in docs if (m := re.fullmatch(r"KB-(\d+)", d["doc_code"] or ""))]
            code = f"KB-{max(nums, default=0) + 1:02d}"
            fname = f"{_slug(title)}.md"
            n = 2
            while (pdir / fname).exists():
                fname = f"{_slug(title)}-{n}.md"; n += 1
            text = self._doc_text(code, title, content, doc_type, "1.0", eff, True, fname)
            tmp = pdir / (fname + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(pdir / fname)                      # ghi nguyên tử, không để lại file dở
        self._kb_reload(code)
        return self.kb_get(code)

    def kb_upload(self, filename: str | None, payload: bytes, title: str | None = None,
                  doc_type: str | None = None, effective_date: str | None = None) -> dict:
        """Nhận PDF/TXT/Markdown, trích phần chữ rồi lưu thành tài liệu KB có thể versioning."""
        name = (filename or "").strip().replace("\\", "/").split("/")[-1]
        suffix = name[name.rfind("."):].lower() if "." in name else ""
        if suffix not in {".pdf", ".txt", ".md", ".markdown"}:
            raise ApiError(422, "unsupported_file", "Chỉ hỗ trợ tệp PDF, TXT hoặc Markdown.")
        if not payload or len(payload) > 2_000_000:
            raise ApiError(422, "invalid_file_size", "Tệp phải có nội dung và không vượt quá 2 MB.")
        if suffix == ".pdf":
            try:
                from pypdf import PdfReader
                text = "\n\n".join((page.extract_text() or "") for page in PdfReader(BytesIO(payload)).pages)
            except ImportError:
                raise ApiError(503, "pdf_parser_unavailable", "Máy chủ chưa cài bộ đọc PDF.") from None
            except Exception:
                raise ApiError(422, "unreadable_pdf", "Không đọc được phần chữ trong tệp PDF này.") from None
        else:
            try:
                text = payload.decode("utf-8-sig")
            except UnicodeDecodeError:
                raise ApiError(422, "invalid_text_encoding", "Tệp TXT/Markdown cần mã hóa UTF-8.") from None
            # Không để front matter của tệp tải lên lồng vào front matter hệ thống.
            _, text = kb.parse_doc(text)
        text = text.strip()
        if not text:
            raise ApiError(422, "empty_file", "Không tìm thấy nội dung chữ có thể dùng trong tệp.")
        inferred_title = Path(name).stem.replace("_", " ").replace("-", " ").strip()
        return self.kb_create(title or inferred_title, text, doc_type, effective_date)

    def kb_update(self, doc_code: str, title: str | None, content: str | None, doc_type: str | None = None,
                  effective_date: str | None = None) -> dict:
        current = self.kb_get(doc_code)
        title = current["title"] if title is None else title
        content = current["content"] if content is None else content
        doc_type = current["doc_type"] if doc_type is None else doc_type
        effective_date = current["effective_date"] if effective_date is None else effective_date
        title, content, doc_type, eff = self._kb_validate(title, content, doc_type, effective_date)
        with self._kb_lock:
            docs = self.kb_list()
            if any(d["doc_code"] != doc_code and d["is_active"] and d["title"].strip().lower() == title.lower()
                   for d in docs):
                raise ApiError(409, "duplicate_title", "Đã có tài liệu đang hiệu lực với tiêu đề này.")
            path = self._kb_path(current)
            history = self.s.policies_dir / ".history"
            history.mkdir(parents=True, exist_ok=True)
            archive = history / f"{doc_code}-v{current.get('version') or '1.0'}.md"
            archive.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            version = self._next_version(current.get("version"))
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(self._doc_text(doc_code, title, content, doc_type, version, eff, True, path.name), encoding="utf-8")
            tmp.replace(path)
        self._kb_reload(doc_code)
        return self.kb_get(doc_code)

    def kb_deactivate(self, doc_code: str) -> dict:
        current = self.kb_get(doc_code)
        if not current["is_active"]:
            return current
        with self._kb_lock:
            path = self._kb_path(current)
            history = self.s.policies_dir / ".history"
            history.mkdir(parents=True, exist_ok=True)
            (history / f"{doc_code}-v{current.get('version') or '1.0'}.md").write_text(
                path.read_text(encoding="utf-8"), encoding="utf-8")
            version = self._next_version(current.get("version"))
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(self._doc_text(doc_code, current["title"], current["content"], current["doc_type"],
                                          version, str(current["effective_date"]), False, path.name), encoding="utf-8")
            tmp.replace(path)
        self._kb_reload(doc_code)
        return self.kb_get(doc_code)
