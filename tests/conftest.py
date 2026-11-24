import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="resolveai-test-"))
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ["GEMINI_API_KEY"] = "test-only-no-network"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.config import Settings
from app.db import Database
from app.service import ChatService
from tests.gemini_responses import agent as test_agent

# 2026-11-18 là Thứ Tư; 10:00 giờ Việt Nam = 03:00 UTC
IN_HOURS = datetime(2026, 11, 18, 3, 0, tzinfo=timezone.utc)
OUT_HOURS = datetime(2026, 11, 18, 14, 0, tzinfo=timezone.utc)  # 21:00 VN


class Clock:
    def __init__(self, t=IN_HOURS):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def make(tmp_path, clock):
    def _make(agent=None, **kw):
        s = Settings(data_dir=tmp_path, secret_key="k", admin_user="admin", admin_password="pw12345",
                     hotline="1900-TEST", gemini_api_key="test-key", **kw)
        db = Database(s.app_db_path)
        db.init()
        svc = ChatService(db, s, agent or test_agent(s), now_fn=clock, sleep_fn=lambda _: None)
        svc.ensure_bootstrap_admin()
        return svc
    return _make


@pytest.fixture
def svc(make):
    return make()
