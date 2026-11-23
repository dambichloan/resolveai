"""Agent MẪU theo từ khóa (tương đương FAKE_LLM=1), chỉ để chạy được giao diện đầu-cuối.

KHÔNG phải Agent thật. Câu trả lời chính sách lấy theo tham số đã chốt ở Mục 6.4 (data/policies, KB-01..KB-05).
Thay bằng Agent LangGraph (Mục 20) bằng cách hiện thực AgentPort.run_turn.
"""
from __future__ import annotations

import re
import unicodedata

from .agent_port import AgentInput, AgentOutput
from .config import Settings
from .mock_orders import MockOrderStore

TICKET_TYPES_NEED_ORDER = {"Đổi trả", "Bảo hành"}
FIELD_PROMPTS = {
    "customer_name": "Bạn vui lòng cho mình biết họ tên?",
    "contact": "Số điện thoại hoặc email để nhân viên liên hệ với bạn là gì?",
    "order_id": "Mã đơn hàng của bạn là gì?",
    "product": "Tên hoặc mã sản phẩm liên quan là gì?",
    "description": "Bạn mô tả giúp mình vấn đề gặp phải (lý do đổi trả, lỗi cần bảo hành, nội dung khiếu nại)?",
}
CONFIRM_WORDS = {"dong y", "xac nhan", "ok", "oke", "co", "vang", "duoc"}


def norm(text: str) -> str:
    t = unicodedata.normalize("NFD", text.lower())
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    return t.replace("đ", "d").strip()

# ---- Tư vấn size theo bảng size phổ thông (KB-03, KB-04), Savani cần xác nhận số đo riêng
SIZE_SOURCE = [{"title": "Bảng size (KB-03, KB-04)", "section": "Gợi ý theo chiều cao, cân nặng"}]
_SIZES = ["S", "M", "L", "XL", "2XL"]
_WEIGHT_CUTS = {"nam": [58, 65, 72, 80], "nu": [47, 53, 59, 65]}


def parse_body(raw: str) -> dict:
    """Rút giới tính, chiều cao (cm), cân nặng (kg) từ một câu tự do."""
    t = norm(raw)
    out: dict = {}
    if re.search(r"\b(nam|dan ong|con trai|ban trai|chong)\b", t):
        out["gender"] = "nam"
    elif re.search(r"\b(nu|phu nu|con gai|ban gai|vo)\b", t):
        out["gender"] = "nu"
    m = re.search(r"\b([12])\s*m\s*(\d{1,2})\b", t) or re.search(r"\b([12])[,.](\d{1,2})\s*m\b", t)
    if m:
        frac = m.group(2)
        out["height"] = int(m.group(1)) * 100 + (int(frac) * (10 if len(frac) == 1 else 1))
    else:
        m = re.search(r"\b(1[3-9]\d|20\d)\s*(?:cm)?\b", t)
        if m:
            out["height"] = int(m.group(1))
    m = re.search(r"\b(\d{2,3})\s*(?:kg|ky|kí|can)\b", t) or re.search(r"\b(?:nang|can nang)\s*(\d{2,3})\b", t)
    if m and 30 <= int(m.group(1)) <= 150:
        out["weight"] = int(m.group(1))
    return out


def recommend_size(gender: str, height: int, weight: int) -> tuple[str, str | None]:
    idx = sum(weight >= c for c in _WEIGHT_CUTS[gender])
    tall = 178 if gender == "nam" else 165
    if height >= tall and idx < len(_SIZES) - 1:
        idx += 1
    alt = _SIZES[idx + 1] if idx + 1 < len(_SIZES) else None
    return _SIZES[idx], alt


def _has(t: str, words) -> bool:
    return any(w in t for w in words)


def _fields_for(ticket_type: str) -> list[str]:
    base = ["customer_name", "contact"]
    if ticket_type in TICKET_TYPES_NEED_ORDER:
        base += ["order_id", "product"]
    return base + ["description"]


class StubAgent:
    def __init__(self, settings: Settings | None = None):
        self.s = settings or Settings()
        self.orders = MockOrderStore(self.s.mock_orders_db_path)

    def run_turn(self, inp: AgentInput) -> AgentOutput:
        state = dict(inp.state)
        t = norm(inp.text)

        # ---- Hành động có cấu trúc từ nút trên thẻ tóm tắt Ticket
        if inp.action == "confirm_ticket":
            if state.get("awaiting_confirm") and state.get("draft"):
                draft = dict(state["draft"])
                new_state = {"clarify_count": 0}
                return AgentOutput("", new_state, intent=draft["type"], create_ticket=draft)
            return AgentOutput("Hiện chưa có yêu cầu nào đang chờ xác nhận.", state)
        if inp.action == "reject_ticket":
            state["awaiting_confirm"] = False
            state["asking"] = "description"
            return AgentOutput(
                "Bạn muốn chỉnh sửa điểm nào? Hãy gõ lại mô tả mới, mình sẽ cập nhật bản tóm tắt.", state)

        # ---- Guardrails mẫu (thay bằng Mục 23): chặn thao túng, không Handoff
        if _has(t, ["bo qua huong dan", "ignore previous", "system prompt", "ma giam gia 100", "tiet lo prompt"]):
            return AgentOutput("Mình không thể thực hiện yêu cầu này. Mình có thể hỗ trợ bạn về chính sách, "
                               "đơn hàng và các yêu cầu đổi trả, bảo hành.", state)

        # ---- Handoff sớm (BR6): đòi gặp người, bức xúc
        if _has(t, ["gap nhan vien", "gap nguoi", "noi chuyen voi nguoi", "chuyen nhan vien", "tu van vien"]):
            return AgentOutput("Mình sẽ chuyển cuộc trò chuyện cho nhân viên CSKH.", state,
                               intent=state.get("intent"), handoff_reason="HO-03")
        if _has(t, ["buc xuc", "qua te", "lua dao", "te hai", "khong chap nhan", "to cao"]):
            return AgentOutput("Mình rất tiếc về trải nghiệm này của bạn. Mình chuyển ngay cho nhân viên "
                               "CSKH để hỗ trợ bạn.", state, intent="Khiếu nại", handoff_reason="HO-04")

        # ---- Đang tư vấn size: nếu câu mới không cung cấp thông tin nào thì thoát luồng, xử lý như bình thường
        if state.get("flow") == "size":
            found = parse_body(inp.text)
            if found:
                return self._size_step(state, found)
            state.pop("flow", None)
            state.pop("size", None)

        # ---- Đang thu thập thông tin Ticket
        if state.get("flow") == "ticket":
            return self._ticket_step(inp, state, t)

        # ---- Tra cứu đơn: phải đi trước trigger đổi/trả để khách chỉ hỏi trạng thái không bị mở Ticket
        if _has(t, ["don hang", "ma don", "tra don", "giao hang"]):
            return self._order_step(state, t)

        # ---- Bắt đầu luồng tạo Ticket
        ttype = self._ticket_trigger(t)
        if ttype:
            state.update(flow="ticket", draft={"type": ttype}, asking=None, awaiting_confirm=False)
            return self._ask_next(state, "Mình sẽ ghi nhận yêu cầu " + ttype.lower() + " của bạn. ", ttype)

        # ---- Tư vấn size
        if "size" in t and not _has(t, ["doi size", "doi hang", "doi tra", "bao hanh"]) or _has(
                t, ["mac vua", "chon co", "co ao", "nen mac"]):
            state.update(flow="size", size={})
            return self._size_step(state, parse_body(inp.text), intro=True)

        # ---- Tư vấn theo dữ liệu mẫu
        if _has(t, ["hoan tien"]):
            return AgentOutput(
                "Savani chỉ hoàn tiền khi sản phẩm lỗi do nhà sản xuất mà kho hết hàng để đổi. Tiền được hoàn qua "
                "chuyển khoản ngân hàng trong 3 - 5 ngày làm việc kể từ khi kho nhận lại hàng hoàn. "
                "Việc hoàn tiền do nhân viên CSKH xác nhận.",
                state, sources=[{"title": "Chính sách đổi trả và hoàn tiền (KB-01)", "section": "Chính sách hoàn tiền"}],
                intent="Đổi trả")
        if _has(t, ["doi tra", "doi hang", "tra hang", "doi size"]):
            return AgentOutput(
                "Savani nhận đổi trả trong 7 ngày kể từ ngày bạn nhận hàng thành công, với sản phẩm còn nguyên tem "
                "mác, chưa qua sử dụng, chưa giặt tẩy, không bám bẩn/mùi lạ. Chính sách không áp dụng cho đồ lót, "
                "tất/vớ, phụ kiện (thắt lưng, ví, mũ) và hàng giảm giá từ 50% trở lên (trừ lỗi nhà sản xuất). "
                "Lỗi sản xuất hoặc giao sai thì Savani chịu phí vận chuyển 2 chiều; đổi size/màu theo nhu cầu "
                "cá nhân thì phí 2 chiều đồng giá 30.000đ.",
                state, sources=[{"title": "Chính sách đổi trả và hoàn tiền (KB-01)", "section": "Điều kiện đổi trả"}],
                intent="Đổi trả")
        if "bao hanh" in t:
            return AgentOutput(
                "Savani bảo hành 30 ngày kể từ ngày nhận hàng đối với lỗi kỹ thuật sản xuất (bung đường chỉ, hỏng "
                "khóa kéo, đứt cúc). Savani từ chối bảo hành khi hư hỏng do ngoại lực (rách do vật sắc nhọn, cháy, "
                "xước), phai màu do giặt sai hướng dẫn trên nhãn, hoặc quá 30 ngày.",
                state, sources=[{"title": "Chính sách bảo hành (KB-02)", "section": "Thời hạn bảo hành"}],
                intent="Bảo hành")
        if _has(t, ["gio lam viec", "mo cua", "may gio"]):
            return AgentOutput("CSKH Savani làm việc 08:00-17:30, từ Thứ Hai đến Thứ Bảy.", state,
                               sources=[{"title": "Giờ làm việc và thời gian phản hồi của CSKH (KB-05)", "section": "Giờ làm việc"}],
                               intent="Tư vấn")
        if _has(t, ["don hang", "ma don", "tra don", "giao hang"]):
            return self._order_step(state, t)
        if _has(t, ["xin chao", "chao", "hello", "hi"]) and len(t) < 20:
            return AgentOutput("Xin chào, mình là trợ lý CSKH của Savani. Mình có thể giải đáp chính sách đổi "
                               "trả, bảo hành, và ghi nhận yêu cầu của bạn.", state, intent="Tư vấn")

        # ---- Không hiểu: làm rõ tối đa 1 lượt rồi Handoff (BR1, BR6)
        if state.get("clarify_count", 0) < 1:
            state["clarify_count"] = state.get("clarify_count", 0) + 1
            return AgentOutput("Bạn có thể nói rõ hơn bạn cần hỗ trợ về đổi trả, bảo hành, đơn hàng hay vấn đề khác?",
                               state)
        return AgentOutput("Mình chưa có thông tin chính thức cho câu hỏi này.", state,
                           intent=state.get("intent"), handoff_reason="HO-01")

    # ------------------------------------------------------------------ Size
    def _order_step(self, state: dict, text: str) -> AgentOutput:
        match = re.search(r"\bsvn\d{4}\b", text)
        verifier = re.search(r"(?:so\s*cuoi|last\s*4)\D{0,20}(\d{4})", text)
        email = re.search(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", text)
        order = self.orders.lookup(match.group(0), verifier.group(1) if verifier else "",
                                   email.group(0) if email else "") if match else None
        if order:
            state.pop("order_auth_failures", None)
            return AgentOutput(
                f"[Dữ liệu demo] Đơn {order['order_id']}: {order['status']}. "
                f"{order['product']}. Cập nhật: {order['updated_at']}. {order['detail']}", state,
                sources=[{"title": "Mock Order DB (MOCK-ORDER)", "section": "Dữ liệu giả chỉ dùng để trình diễn"}],
                intent="Tư vấn")
        if match and (verifier or email):                 # đã gửi mã đơn và thông tin đối chiếu nhưng sai (BR16)
            fails = int(state.get("order_auth_failures", 0)) + 1
            state["order_auth_failures"] = fails
            if fails >= 3:                                # sai lần thứ 3 mới chuyển nhân viên
                state.pop("order_auth_failures", None)
                return AgentOutput("Mình chưa xác thực được đơn hàng sau nhiều lần thử, nên mình chuyển bạn cho "
                                   "nhân viên CSKH hỗ trợ trực tiếp.", state, intent="Tư vấn", handoff_reason="HO-07")
            return AgentOutput("Mình chưa xác thực được thông tin này. Bạn kiểm tra lại mã đơn và 4 số cuối số điện "
                               "thoại (hoặc email) đã đăng ký, rồi gửi lại giúp mình nhé.", state, intent="Tư vấn")
        return AgentOutput("Để tra đơn demo, bạn cho mình mã đơn và 4 số cuối số điện thoại hoặc email "
                           "đăng ký. Ví dụ: SVN1001, 4 số cuối 1122.", state, intent="Tư vấn")

    @staticmethod
    def _size_step(state: dict, found: dict, intro: bool = False) -> AgentOutput:
        info = {**state.get("size", {}), **found}
        state["size"] = info
        lead = "Mình sẽ tư vấn size giúp bạn. " if intro else ""
        if "gender" not in info:
            return AgentOutput(lead + "Bạn chọn size cho nam hay nữ? (Bạn có thể gửi luôn chiều cao và cân nặng, "
                               "ví dụ: nam 1m72 65kg)", state, intent="Tư vấn")
        if "height" not in info or "weight" not in info:
            need = "chiều cao và cân nặng" if "height" not in info and "weight" not in info else (
                "chiều cao" if "height" not in info else "cân nặng")
            return AgentOutput(lead + f"Bạn cho mình biết {need} nhé (ví dụ: 1m70, 62kg).", state, intent="Tư vấn")
        size, alt = recommend_size(info["gender"], info["height"], info["weight"])
        who = "nam" if info["gender"] == "nam" else "nữ"
        txt = (f"Với {who} cao {info['height']}cm, nặng {info['weight']}kg, mình gợi ý bạn chọn size {size}.")
        if alt:
            txt += f" Nếu bạn thích mặc rộng thoải mái thì chọn size {alt}."
        txt += " Đây là gợi ý tham khảo; nếu không vừa, Savani hỗ trợ đổi size trong 7 ngày kể từ ngày nhận hàng (sản phẩm còn nguyên tem mác, chưa giặt)."
        state.pop("flow", None)
        state.pop("size", None)
        return AgentOutput(txt, state, sources=SIZE_SOURCE, intent="Tư vấn")

    # ------------------------------------------------------------------ Ticket
    @staticmethod
    def _ticket_trigger(t: str) -> str | None:
        if "khieu nai" in t:
            return "Khiếu nại"
        wants = _has(t, ["tao yeu cau", "gui yeu cau", "yeu cau", "muon doi", "muon tra", "can bao hanh",
                         "muon bao hanh"])
        if "bao hanh" in t and wants:
            return "Bảo hành"
        if _has(t, ["doi tra", "doi hang", "tra hang"]) and wants:
            return "Đổi trả"
        return None

    def _ticket_step(self, inp: AgentInput, state: dict, t: str) -> AgentOutput:
        draft = dict(state.get("draft", {}))
        ttype = draft.get("type", "Khiếu nại")
        if state.get("awaiting_confirm"):
            hint = "Để bảo đảm chính xác, bạn vui lòng bấm nút “Xác nhận” hoặc “Chỉnh sửa” trên thẻ tóm tắt nhé."
            return AgentOutput(hint, state, ui=self._summary_ui(draft), intent=ttype)
        asking = state.get("asking")
        value = inp.text.strip()
        if asking == "contact" and not (re.search(r"\d{8,}", value) or "@" in value):
            return AgentOutput("Thông tin liên hệ chưa hợp lệ, bạn nhập số điện thoại hoặc email giúp mình nhé.",
                               state, intent=ttype)
        if asking:
            draft[asking] = value
        state["draft"] = draft
        return self._ask_next(state, "", ttype)

    def _ask_next(self, state: dict, lead: str, ttype: str) -> AgentOutput:
        draft = state["draft"]
        for f in _fields_for(ttype):
            if not draft.get(f):
                state["asking"] = f
                return AgentOutput(lead + FIELD_PROMPTS[f], state, intent=ttype)
        state["asking"] = None
        state["awaiting_confirm"] = True
        return AgentOutput("Mình đã ghi lại thông tin như dưới đây. Bạn kiểm tra và xác nhận giúp mình nhé.",
                           state, ui=self._summary_ui(draft), intent=ttype)

    @staticmethod
    def _summary_ui(draft: dict) -> dict:
        labels = {"customer_name": "Họ tên", "contact": "Liên hệ", "order_id": "Mã đơn",
                  "product": "Sản phẩm", "description": "Mô tả"}
        fields = [{"label": labels[k], "value": draft[k]} for k in labels if draft.get(k)]
        return {"type": "ticket_summary", "ticket_type": draft.get("type"), "fields": fields}
