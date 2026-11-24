"""Application DB (SQLite). Mỗi lần gọi mở một kết nối; ghi dùng BEGIN IMMEDIATE."""
from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_session(
  id TEXT PRIMARY KEY,
  token_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'AI_Handling',
  intent TEXT,
  handoff_reason TEXT,
  handoff_at TEXT,
  claimed_by INTEGER,
  state_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS message(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL REFERENCES chat_session(id),
  role TEXT NOT NULL,
  text TEXT NOT NULL,
  sources_json TEXT NOT NULL DEFAULT '[]',
  ui_json TEXT,
  client_msg_id TEXT,
  latency_ms INTEGER,
  created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_message_client
  ON message(session_id, client_msg_id) WHERE client_msg_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_message_session ON message(session_id, id);
CREATE TABLE IF NOT EXISTS ticket(
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES chat_session(id),
  type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'Mới',
  customer_name TEXT,
  contact TEXT,
  order_id TEXT,
  product TEXT,
  description TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ticket_note(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_id TEXT NOT NULL REFERENCES ticket(id),
  staff_id INTEGER,
  old_status TEXT,
  new_status TEXT NOT NULL,
  note TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS handoff(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL REFERENCES chat_session(id),
  reason_code TEXT NOT NULL,
  intent TEXT,
  in_business_hours INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS staff(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS staff_session(
  token_hash TEXT PRIMARY KEY,
  staff_id INTEGER NOT NULL REFERENCES staff(id),
  expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS policy_doc(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage_event(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL REFERENCES chat_session(id),
  model TEXT NOT NULL,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  estimated_cost_usd REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_usage_event_created ON usage_event(created_at);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)

    def init(self) -> None:
        with self.conn() as c:
            c.executescript(SCHEMA)

    @contextlib.contextmanager
    def conn(self):
        c = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        try:
            yield c
        finally:
            c.close()

    @contextlib.contextmanager
    def tx(self):
        """Giao dịch ghi: hoàn tác nếu có lỗi (NFR-REL-01)."""
        with self.conn() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
            except BaseException:
                c.execute("ROLLBACK")
                raise
            else:
                c.execute("COMMIT")
