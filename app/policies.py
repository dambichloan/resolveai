"""Kho chính sách do nhân viên thêm/sửa/xóa ở trang quản trị. Agent đọc từ đây mỗi lượt chat."""
from __future__ import annotations

from datetime import datetime, timezone

from .db import Database
from .knowledge import DEFAULT_POLICIES
from .service import ApiError
from .guardrails import _norm as norm

MAX_TITLE, MAX_CONTENT, MAX_PROMPT_CHARS = 200, 6000, 20000
STOP = {"cho", "minh", "toi", "ban", "the", "nao", "khong", "duoc", "nay", "voi", "cua", "gia", "shop",
        "vay", "nhe", "a", "la", "co", "gi", "va", "bi", "em", "anh", "chi", "xin", "hoi", "muon", "biet"}


def _words(text: str) -> set[str]:
    return {w for w in norm(text).replace(",", " ").replace(".", " ").replace(":", " ").split()
            if len(w) >= 3 and w not in STOP}


class PolicyRepo:
    def __init__(self, db: Database):
        self.db = db

    def _check(self, title: str, content: str) -> tuple[str, str]:
        title, content = (title or "").strip(), (content or "").strip()
        if not title or not content:
            raise ApiError(422, "empty_policy", "Cần nhập cả tiêu đề và nội dung.")
        if len(title) > MAX_TITLE or len(content) > MAX_CONTENT:
            raise ApiError(422, "policy_too_long", f"Tiêu đề tối đa {MAX_TITLE}, nội dung tối đa {MAX_CONTENT} ký tự.")
        return title, content

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def seed_defaults(self) -> None:
        with self.db.tx() as c:
            if c.execute("SELECT COUNT(*) FROM policy_doc").fetchone()[0] == 0:
                for title, content in DEFAULT_POLICIES:
                    c.execute("INSERT INTO policy_doc(title, content, updated_at) VALUES (?,?,?)",
                              (title, content, self._now()))

    def list(self) -> list[dict]:
        with self.db.conn() as c:
            rows = c.execute("SELECT id, title, content, updated_at FROM policy_doc ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def create(self, title: str, content: str) -> dict:
        title, content = self._check(title, content)
        with self.db.tx() as c:
            cur = c.execute("INSERT INTO policy_doc(title, content, updated_at) VALUES (?,?,?)",
                            (title, content, self._now()))
            return {"id": cur.lastrowid, "title": title, "content": content}

    def update(self, doc_id: int, title: str, content: str) -> dict:
        title, content = self._check(title, content)
        with self.db.tx() as c:
            cur = c.execute("UPDATE policy_doc SET title=?, content=?, updated_at=? WHERE id=?",
                            (title, content, self._now(), doc_id))
            if cur.rowcount != 1:
                raise ApiError(404, "not_found", "Không tìm thấy chính sách.")
        return {"id": doc_id, "title": title, "content": content}

    def delete(self, doc_id: int) -> dict:
        with self.db.tx() as c:
            if c.execute("DELETE FROM policy_doc WHERE id=?", (doc_id,)).rowcount != 1:
                raise ApiError(404, "not_found", "Không tìm thấy chính sách.")
        return {"ok": True}

    def text(self) -> str:
        """Toàn bộ chính sách dạng văn bản để đưa vào prompt Gemini."""
        out, size = [], 0
        for d in self.list():
            block = f"### {d['title']}\n{d['content']}\n"
            if size + len(block) > MAX_PROMPT_CHARS:
                break
            out.append(block); size += len(block)
        return "\n".join(out)

    def search(self, query: str) -> dict | None:
        """Tìm chính sách khớp nhất theo từ khóa (cho Agent mẫu không dùng Gemini)."""
        q = _words(query)
        best, best_score = None, 0
        for d in self.list():
            tw, cw = _words(d["title"]), _words(d["content"])
            score = 3 * len(q & tw) + len(q & (cw - tw))
            if score > best_score:
                best, best_score = d, score
        return best if best_score >= 3 else None
