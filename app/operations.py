"""Tác vụ vận hành: sao lưu dữ liệu và áp dụng thời hạn lưu trữ.

Được chạy bởi ``scripts.backup`` trong Docker. Tách khỏi luồng chat để sao lưu
không làm chậm phản hồi khách hàng.
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from .config import Settings
from .db import Database

log = logging.getLogger("resolveai.operations")


def configure_technical_log(settings: Settings) -> None:
    """Ghi log kỹ thuật xoay vòng theo ngày, giữ tối đa số ngày đã cấu hình."""
    try:
        logs_dir = settings.data_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger("resolveai")
        target = str((logs_dir / "resolveai.log").resolve())
        if any(getattr(handler, "baseFilename", None) == target for handler in logger.handlers):
            return
        handler = TimedRotatingFileHandler(target, when="midnight", backupCount=max(1, settings.technical_log_retention_days),
                                           encoding="utf-8", utc=True)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    except OSError as exc:
        # Không chặn chat chỉ vì nơi triển khai chưa cấp quyền ghi file log.
        logging.getLogger("resolveai").warning("Không bật được log file: %s", exc)


def backup_once(settings: Settings) -> Path:
    """Sao lưu SQLite bằng SQLite backup API, đồng thời lưu Chroma và KB theo ngày."""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    destination = settings.backup_dir / day
    destination.mkdir(parents=True, exist_ok=True)
    if settings.app_db_path.exists():
        source = sqlite3.connect(settings.app_db_path)
        target = sqlite3.connect(destination / "app.db")
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
    for name, source in (("chroma", settings.chroma_dir), ("policies", settings.policies_dir)):
        if source.exists():
            shutil.copytree(source, destination / name, dirs_exist_ok=True)
    _purge_backups(settings)
    return destination


def retain_application_data(db: Database, settings: Settings) -> None:
    """Xóa phiên/tin nhắn/Ticket quá hạn và phiên nhân viên hết hạn.

    Chính sách mặc định giữ lịch sử nghiệp vụ 12 tháng; log kỹ thuật được xử lý
    riêng bằng file rotation 90 ngày.
    """
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=max(1, settings.ticket_retention_days))).isoformat(timespec="seconds")
    with db.tx() as c:
        c.execute("DELETE FROM staff_session WHERE expires_at<=?", (now.isoformat(timespec="seconds"),))
        old_ticket_ids = [r[0] for r in c.execute("SELECT id FROM ticket WHERE created_at<?", (cutoff,))]
        if old_ticket_ids:
            marks = ",".join("?" for _ in old_ticket_ids)
            c.execute(f"DELETE FROM ticket_note WHERE ticket_id IN ({marks})", old_ticket_ids)
            c.execute(f"DELETE FROM ticket WHERE id IN ({marks})", old_ticket_ids)
        old_session_ids = [r[0] for r in c.execute("SELECT id FROM chat_session WHERE created_at<?", (cutoff,))]
        if old_session_ids:
            marks = ",".join("?" for _ in old_session_ids)
            c.execute(f"DELETE FROM message WHERE session_id IN ({marks})", old_session_ids)
            c.execute(f"DELETE FROM handoff WHERE session_id IN ({marks})", old_session_ids)
            c.execute(f"DELETE FROM chat_session WHERE id IN ({marks})", old_session_ids)


def _purge_backups(settings: Settings) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, settings.backup_retention_days))).date()
    if not settings.backup_dir.exists():
        return
    for child in settings.backup_dir.iterdir():
        if not child.is_dir():
            continue
        try:
            dated = datetime.strptime(child.name, "%Y-%m-%d").date()
        except ValueError:
            continue
        if dated < cutoff:
            shutil.rmtree(child)
