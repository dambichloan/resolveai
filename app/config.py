"""Cấu hình đọc từ biến môi trường (xem .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("./var")
    secret_key: str = "dev-only-change-me"
    rate_limit_per_min: int = 15            # NFR-SEC-05
    session_create_limit_per_min: int = 20  # chống tạo phiên hàng loạt để né giới hạn theo phiên
    max_message_len: int = 1000
    hotline: str = "[hotline Savani - cần điền]"
    admin_user: str = ""
    admin_password: str = ""
    timezone: str = "Asia/Ho_Chi_Minh"      # giờ làm việc CSKH 08:00-17:30, T2-T7
    cookie_secure: bool = False             # đặt 1 khi chạy sau HTTPS
    staff_session_hours: int = 8
    gemini_api_key: str = field(default="", repr=False)  # khóa API Gemini (đặt qua biến môi trường GEMINI_API_KEY)
    llm_model: str = "gemini-3.5-flash-lite"
    llm_fallback_model: str = ""            # tùy chọn model Gemini dự phòng
    llm_timeout: float = 20.0               # giây cho mỗi yêu cầu Gemini
    embed_model: str = "gemini-embedding-2"
    embedding_dimensions: int = 768
    rag_top_k: int = 3
    llm_confidence_threshold: float = 0.70   # llm_confidence thấp hơn thì chuyển nhân viên (BR6)
    mcp_enabled: bool = False                # mở /mcp (JSON-RPC MCP) cho các công cụ
    rag_handoff_threshold: float = 0.65
    rag_answer_threshold: float = 0.70
    langfuse_public_key: str = field(default="", repr=False)
    langfuse_secret_key: str = field(default="", repr=False)
    langfuse_host: str = "https://cloud.langfuse.com"
    seed_demo: bool = False                 # True: nạp dữ liệu mẫu cho trang quản trị (xem app/demo_seed.py)
    policies_dir: Path = Path(__file__).resolve().parent.parent / "data" / "policies"
    backup_retention_days: int = 7
    ticket_retention_days: int = 365
    technical_log_retention_days: int = 90
    llm_input_cost_per_million_usd: float = 0.0
    llm_output_cost_per_million_usd: float = 0.0
    cost_alert_daily_usd: float = 5.0
    cost_alert_per_conversation_usd: float = 0.05

    @property
    def app_db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def mock_orders_db_path(self) -> Path:
        return self.data_dir / "mock_orders.db"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def source_policies_dir(self) -> Path:
        """Kho chính sách đóng gói cùng mã nguồn, chỉ dùng để nạp lần đầu."""
        return Path(__file__).resolve().parent.parent / "data" / "policies"


def load_settings() -> Settings:
    e = os.environ.get
    data_dir = Path(e("DATA_DIR", "./var"))
    return Settings(
        data_dir=data_dir,
        secret_key=e("SECRET_KEY", "dev-only-change-me"),
        rate_limit_per_min=int(e("RATE_LIMIT_PER_MIN", "15")),
        session_create_limit_per_min=int(e("SESSION_CREATE_LIMIT_PER_MIN", "20")),
        max_message_len=int(e("MAX_MESSAGE_LEN", "1000")),
        hotline=e("HOTLINE", "[hotline Savani - cần điền]"),
        admin_user=e("ADMIN_BOOTSTRAP_USER", ""),
        admin_password=e("ADMIN_BOOTSTRAP_PASSWORD", ""),
        timezone=e("TZ", "Asia/Ho_Chi_Minh"),
        cookie_secure=_bool(e("COOKIE_SECURE")),
        staff_session_hours=int(e("STAFF_SESSION_HOURS", "8")),
        gemini_api_key=e("GEMINI_API_KEY", "").strip(),
        llm_model=e("LLM_MODEL", "").strip() or "gemini-3.5-flash-lite",
        llm_fallback_model=e("LLM_FALLBACK_MODEL", "").strip(),
        llm_timeout=float(e("LLM_TIMEOUT", "20")),
        embed_model=e("EMBED_MODEL", "").strip() or "gemini-embedding-2",
        embedding_dimensions=int(e("EMBEDDING_DIMENSIONS", "768")),
        rag_top_k=int(e("RAG_TOP_K", "3")),
        llm_confidence_threshold=float(e("LLM_CONFIDENCE_THRESHOLD", "0.70")),
        mcp_enabled=_bool(e("MCP_ENABLED"), False),
        rag_handoff_threshold=float(e("RAG_HANDOFF_THRESHOLD", "0.65")),
        rag_answer_threshold=float(e("RAG_ANSWER_THRESHOLD", "0.70")),
        langfuse_public_key=e("LANGFUSE_PUBLIC_KEY", "").strip(),
        langfuse_secret_key=e("LANGFUSE_SECRET_KEY", "").strip(),
        langfuse_host=e("LANGFUSE_HOST", "https://cloud.langfuse.com").strip(),
        seed_demo=_bool(e("SEED_DEMO"), False),
        # Bản triển khai ghi KB vào volume DATA_DIR, không sửa trực tiếp mã nguồn trong container.
        policies_dir=Path(e("POLICIES_DIR", str(data_dir / "policies"))),
        backup_retention_days=int(e("BACKUP_RETENTION_DAYS", "7")),
        ticket_retention_days=int(e("TICKET_RETENTION_DAYS", "365")),
        technical_log_retention_days=int(e("TECHNICAL_LOG_RETENTION_DAYS", "90")),
        # Giá thay đổi theo gói Gemini; đội vận hành điền giá đang áp dụng để ước tính/cảnh báo.
        llm_input_cost_per_million_usd=float(e("LLM_INPUT_COST_PER_MILLION_USD", "0")),
        llm_output_cost_per_million_usd=float(e("LLM_OUTPUT_COST_PER_MILLION_USD", "0")),
        cost_alert_daily_usd=float(e("COST_ALERT_DAILY_USD", "5")),
        cost_alert_per_conversation_usd=float(e("COST_ALERT_PER_CONVERSATION_USD", "0.05")),
    )
