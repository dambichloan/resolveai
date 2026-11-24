"""Đọc kho tài liệu chính sách (data/policies/*.md), chỉ đọc. Mỗi file có front matter:
doc_code, title, doc_type, version, effective_date, is_active, source_file (Mục 21.3.2)."""
from __future__ import annotations

import shutil
from pathlib import Path

META_KEYS = ("doc_code", "title", "doc_type", "version", "effective_date", "is_active", "source_file")


def parse_doc(text: str) -> tuple[dict, str]:
    meta: dict = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            for line in text[3:end].strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            body = text[end + 4:].lstrip("\n")
    meta["is_active"] = str(meta.get("is_active", "true")).lower() == "true"
    return meta, body


def load_docs(policies_dir: Path) -> list[dict]:
    docs = []
    if not policies_dir.is_dir():
        return docs
    for p in sorted(policies_dir.glob("*.md")):
        meta, body = parse_doc(p.read_text(encoding="utf-8"))
        if not meta.get("doc_code"):
            continue
        meta.setdefault("title", p.stem)
        meta.setdefault("source_file", p.name)
        docs.append({**{k: meta.get(k) for k in META_KEYS}, "content": body})
    return sorted(docs, key=lambda d: d["doc_code"])


def bootstrap_policies(target_dir: Path, source_dir: Path) -> None:
    """Nạp sáu tài liệu mẫu vào kho dữ liệu bền vững ở lần chạy đầu.

    Chỉ sao chép khi kho đích chưa có tài liệu nào, vì các bản sau nhân viên đã
    có thể cập nhật/tắt hiệu lực tài liệu ở đó.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    if not any(target_dir.glob("*.md")):
        for source in source_dir.glob("*.md"):
            shutil.copy2(source, target_dir / source.name)
    source_rules = source_dir.parent / "rules.md"
    target_rules = target_dir.parent / "rules.md"
    if source_rules.exists() and not target_rules.exists():
        shutil.copy2(source_rules, target_rules)
