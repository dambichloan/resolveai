"""FastAPI: lớp HTTP mỏng, mọi nghiệp vụ nằm ở app/service.py."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent_port import AgentPort
from .config import Settings, load_settings
from .db import Database
from . import kb
from .operations import configure_technical_log
from . import observability
from .service import ApiError, ChatService

logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s - %(message)s")
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def build_agent(settings: Settings) -> AgentPort:
    """Khởi tạo Gemini cho hội thoại và gọi công cụ nghiệp vụ."""
    if not settings.gemini_api_key:
        raise RuntimeError("Cần đặt GEMINI_API_KEY để chạy ResolveAI.")
    from .gemini_agent import GeminiAgent
    logging.getLogger("resolveai").info("Gemini: có khóa (%d ký tự), model=%s, dự phòng=%s, embed=%s",
                                        len(settings.gemini_api_key), settings.llm_model,
                                        settings.llm_fallback_model or "-", settings.embed_model)
    return GeminiAgent(settings)


class ChatIn(BaseModel):
    session_id: str | None = None
    text: str | None = None
    client_msg_id: str | None = None
    action: str | None = None


class TextIn(BaseModel):
    text: str


class LoginIn(BaseModel):
    username: str | None = None
    password: str | None = None


class KbIn(BaseModel):
    title: str | None = None
    content: str | None = None
    doc_type: str | None = None
    effective_date: str | None = None


class StatusIn(BaseModel):
    status: str
    note: str | None = None


def create_app(settings: Settings | None = None, agent: AgentPort | None = None) -> FastAPI:
    settings = settings or load_settings()
    kb.bootstrap_policies(settings.policies_dir, settings.source_policies_dir)
    configure_technical_log(settings)
    db = Database(settings.app_db_path)
    db.init()
    logging.getLogger("resolveai").warning("Langfuse: %s", observability.status(settings))
    svc = ChatService(db, settings, agent or build_agent(settings))
    svc.ensure_bootstrap_admin()
    if settings.seed_demo:
        from .demo_seed import seed_demo
        seed_demo(db, settings)

    app = FastAPI(title="ResolveAI", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.service = svc

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, e: ApiError):
        body = {"error": {"code": e.code, "message": e.message, **e.extra}}
        return JSONResponse(body, status_code=e.status, headers=e.headers)

    def staff(request: Request) -> dict:
        return svc.require_staff(request.cookies.get("staff_session"))

    # ---------------- khách hàng
    @app.get("/healthz")
    def healthz():
        with db.conn() as c:
            c.execute("SELECT 1")
        return {"status": "ok"}

    @app.post("/api/chat/messages")
    def post_message(body: ChatIn, request: Request, x_session_token: str | None = Header(default=None)):
        ip = request.client.host if request.client else None
        return svc.post_message(body.session_id, x_session_token, body.text, body.client_msg_id,
                                body.action, client_ip=ip)

    @app.get("/api/chat/sessions/{session_id}/messages")
    def get_messages(session_id: str, after: int = 0, x_session_token: str | None = Header(default=None)):
        return svc.get_messages(session_id, x_session_token, after)

    @app.post("/api/chat/sessions/{session_id}/close")
    def close_customer_chat(session_id: str, x_session_token: str | None = Header(default=None)):
        return svc.close_customer(session_id, x_session_token)

    # ---------------- nhân viên
    @app.post("/api/admin/login")
    def admin_login(body: LoginIn):
        result = svc.login_staff(body.username, body.password)
        token = result.pop("token")
        response = JSONResponse(result)
        response.set_cookie("staff_session", token, max_age=settings.staff_session_hours * 3600,
                            httponly=True, samesite="strict", secure=settings.cookie_secure, path="/")
        return response

    @app.post("/api/admin/logout", status_code=204)
    def admin_logout(request: Request):
        svc.logout_staff(request.cookies.get("staff_session"))
        response = Response(status_code=204)
        response.delete_cookie("staff_session", path="/")
        return response

    @app.get("/api/admin/me")
    def me(s: dict = Depends(staff)):
        return s

    @app.get("/api/admin/queue")
    def queue(_: dict = Depends(staff)):
        return {"items": svc.queue()}

    @app.post("/api/admin/sessions/{session_id}/claim")
    def claim(session_id: str, s: dict = Depends(staff)):
        return svc.claim(s, session_id)

    @app.post("/api/admin/sessions/{session_id}/messages")
    def staff_msg(session_id: str, body: TextIn, s: dict = Depends(staff)):
        return svc.staff_message(s, session_id, body.text)

    @app.post("/api/admin/sessions/{session_id}/close")
    def close(session_id: str, s: dict = Depends(staff)):
        return svc.close(s, session_id)

    @app.get("/api/admin/sessions")
    def sessions(status: str | None = None, intent: str | None = None, _: dict = Depends(staff)):
        return {"items": svc.list_sessions(status, intent)}

    @app.get("/api/admin/sessions/{session_id}")
    def session_detail(session_id: str, after: int = 0, _: dict = Depends(staff)):
        return svc.session_detail(session_id, after)

    @app.get("/api/admin/tickets")
    def tickets(status: str | None = None, type: str | None = None, _: dict = Depends(staff)):
        return {"items": svc.list_tickets(status, type)}

    @app.get("/api/admin/tickets/{ticket_id}")
    def ticket(ticket_id: str, _: dict = Depends(staff)):
        return svc.ticket_detail(ticket_id)

    @app.patch("/api/admin/tickets/{ticket_id}/status")
    def ticket_status(ticket_id: str, body: StatusIn, s: dict = Depends(staff)):
        return svc.update_ticket_status(s, ticket_id, body.status, body.note)

    @app.get("/api/admin/dashboard")
    def dashboard(date_from: str | None = None, date_to: str | None = None, _: dict = Depends(staff)):
        return svc.dashboard(date_from, date_to)

    if settings.mcp_enabled and hasattr(svc.agent, "mcp_handle"):
        @app.post("/mcp")
        async def mcp_endpoint(request: Request):
            try:
                message = await request.json()
            except ValueError:
                return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            reply = svc.agent.mcp_handle(message)
            return JSONResponse(reply) if reply is not None else JSONResponse(None, status_code=202)

    @app.get("/api/admin/kb/docs")
    def kb_list(_: dict = Depends(staff)):
        return {"items": svc.kb_list()}

    @app.get("/api/admin/kb/docs/{doc_code}")
    def kb_get(doc_code: str, _: dict = Depends(staff)):
        return svc.kb_get(doc_code)

    @app.post("/api/admin/kb/docs", status_code=201)
    def kb_create(body: KbIn, _: dict = Depends(staff)):
        return svc.kb_create(body.title, body.content, body.doc_type, body.effective_date)

    @app.put("/api/admin/kb/docs/{doc_code}")
    def kb_update(doc_code: str, body: KbIn, _: dict = Depends(staff)):
        return svc.kb_update(doc_code, body.title, body.content, body.doc_type, body.effective_date)

    @app.delete("/api/admin/kb/docs/{doc_code}")
    def kb_delete(doc_code: str, _: dict = Depends(staff)):
        return svc.kb_deactivate(doc_code)

    @app.post("/api/admin/kb/upload", status_code=201)
    async def kb_upload(request: Request, filename: str, title: str | None = None,
                        doc_type: str | None = None, effective_date: str | None = None,
                        _: dict = Depends(staff)):
        return svc.kb_upload(filename, await request.body(), title, doc_type, effective_date)

    # StaticFiles phục vụ thư mục khi URL có dấu / cuối. Hai redirect này giúp
    # các liên kết /admin và /chat không rơi nhầm vào trang bán hàng.
    @app.get("/admin", include_in_schema=False)
    def admin_root():
        return RedirectResponse("/admin/")

    @app.get("/admin/login", include_in_schema=False)
    def admin_login_page():
        return RedirectResponse("/admin/login.html")

    @app.get("/chat", include_in_schema=False)
    def chat_root():
        return RedirectResponse("/chat/")

   
    
    # ---------------- giao diện tĩnh (đặt sau cùng để không che /api)
    app.mount("/admin", StaticFiles(directory=WEB_DIR / "admin", html=True), name="admin")
    app.mount("/chat", StaticFiles(directory=WEB_DIR / "chat", html=True), name="chat")      # khung chat (iframe)
    app.mount("/widget", StaticFiles(directory=WEB_DIR / "widget"), name="widget")           # nút chatbot nhúng
    app.mount("/", StaticFiles(directory=WEB_DIR / "store", html=True), name="store")        # trang bán hàng demo
    return app


app = create_app()
