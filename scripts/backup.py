"""Chạy một lần hoặc theo lịch 24 giờ: backup + dọn dữ liệu quá hạn."""
from __future__ import annotations

import argparse
import logging
import time

from app.config import load_settings
from app.db import Database
from app.operations import backup_once, configure_technical_log, retain_application_data


def run_once() -> None:
    settings = load_settings()
    configure_technical_log(settings)
    db = Database(settings.app_db_path)
    db.init()
    retain_application_data(db, settings)
    path = backup_once(settings)
    logging.getLogger("resolveai.operations").warning("Đã sao lưu dữ liệu vào %s", path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="Lặp lại sau mỗi 24 giờ")
    args = parser.parse_args()
    while True:
        try:
            run_once()
        except Exception:  # noqa: BLE001
            logging.exception("Sao lưu thất bại")
        if not args.loop:
            return
        time.sleep(24 * 60 * 60)


if __name__ == "__main__":
    main()
