"""Kiểm thử lớp HTTP (FastAPI). Bỏ qua nếu chưa cài fastapi/httpx."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from tests.gemini_responses import agent as test_agent
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture
def client(tmp_path):
    s = Settings(data_dir=tmp_path, secret_key="k", admin_user="admin", admin_password="pw12345", hotline="1900", gemini_api_key="test-key")
    return TestClient(create_app(s, agent=test_agent(s)))


def test_health(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_chat_flow_and_403(client):
    r = client.post("/api/chat/messages", json={"text": "giờ làm việc", "client_msg_id": "a"})
    assert r.status_code == 200
    sid, tok = r.json()["session_id"], r.json()["session_token"]
    assert client.get(f"/api/chat/sessions/{sid}/messages").status_code == 403
    assert client.get(f"/api/chat/sessions/{sid}/messages", headers={"X-Session-Token": tok}).status_code == 200


def test_rate_limit_429_header(client):
    r = client.post("/api/chat/messages", json={"text": "a"})
    sid, tok = r.json()["session_id"], r.json()["session_token"]
    codes = [client.post("/api/chat/messages", json={"session_id": sid, "text": "a"},
                         headers={"X-Session-Token": tok}) for _ in range(15)]
    assert codes[-1].status_code == 429 and "retry-after" in codes[-1].headers


def test_admin_open_without_login_and_static_pages(client):
    assert client.get("/api/admin/queue").status_code == 401
    assert client.get("/admin/login").status_code == 200
    assert client.post("/api/admin/login", json={"username": "admin", "password": "sai"}).status_code == 401
    assert client.post("/api/admin/login", json={"username": "admin", "password": "pw12345"}).status_code == 200
    assert client.get("/api/admin/me").json()["username"] == "admin"
    assert client.get("/api/admin/queue").status_code == 200
    docs = client.get("/api/admin/kb/docs").json()["items"]
    assert [d["doc_code"] for d in docs] == ["KB-01", "KB-02", "KB-03", "KB-04", "KB-05", "KB-06"]
    assert "7 ngày" in client.get("/api/admin/kb/docs/KB-01").json()["content"]
    assert client.get("/api/admin/kb/docs/KB-99").status_code == 404
    saved = client.put("/api/admin/kb/docs/KB-01", json={"content": "Nội dung cập nhật", "title": "Chính sách đổi trả và hoàn tiền (KB-01)", "doc_type": "policy", "effective_date": "2026-11-01"})
    assert saved.status_code == 200 and saved.json()["version"] == "1.1"
    assert client.delete("/api/admin/kb/docs/KB-01").json()["is_active"] is False
    assert "SAVANI" in client.get("/").text
    assert client.get("/chat/").status_code == 200
    assert client.get("/widget/widget.js").status_code == 200
    assert client.get("/admin/").status_code == 200
    assert client.get("/admin/login.html").status_code == 200
