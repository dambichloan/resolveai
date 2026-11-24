"""Khởi tạo dữ liệu (idempotent): tạo schema và tài khoản admin đầu tiên.
Chạy: docker compose --profile init run --rm init"""
from app.config import load_settings
from app.db import Database
from app.service import ChatService
from app.gemini_agent import GeminiAgent

s = load_settings()
db = Database(s.app_db_path)
db.init()
ChatService(db, s, GeminiAgent(s)).ensure_bootstrap_admin()
if s.seed_demo:
    from app.demo_seed import seed_demo
    print(f"Dữ liệu mẫu: {seed_demo(db, s)}")
print(f"OK: {s.app_db_path} (admin: {'đã tạo/đã có' if s.admin_user else 'chưa cấu hình ADMIN_BOOTSTRAP_USER'})")
