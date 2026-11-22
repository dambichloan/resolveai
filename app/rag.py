"""Chroma-backed policy RAG: 768-d Gemini Embedding 2, cosine, Top-3."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Callable


def _section_at(text: str, position: int) -> str:
    headings = list(re.finditer(r"^#{1,4}\s+(.+)$", text, re.MULTILINE))
    before = [h.group(1).strip() for h in headings if h.start() <= position]
    return before[-1] if before else "Nội dung chính sách"


def chunks_for(docs: list[dict], chunk_tokens: int = 400, overlap_tokens: int = 50) -> list[dict]:
    """Chunk by whitespace tokens; each chunk retains its document metadata and section."""
    out: list[dict] = []
    for doc in docs:
        text = doc["content"].strip()
        words = list(re.finditer(r"\S+", text))
        start = number = 0
        while start < len(words):
            end = min(len(words), start + chunk_tokens)
            char_start, char_end = words[start].start(), words[end - 1].end()
            content = text[char_start:char_end].strip()
            if content:
                number += 1
                out.append({
                    "chunk_id": f"{doc['doc_code']}:{number:03d}", "doc_code": doc["doc_code"],
                    "title": doc["title"], "version": str(doc.get("version") or ""),
                    "source_file": str(doc.get("source_file") or ""),
                    "effective_date": int(str(doc.get("effective_date") or "0").replace("-", "") or 0),
                    "is_active": bool(doc.get("is_active")), "section": _section_at(text, char_start),
                    "text": content,
                })
            if end == len(words):
                break
            start = max(start + 1, end - overlap_tokens)
    return out


class PolicyRetriever:
    """Persistent Chroma collection. It rebuilds only when the KB/model changes."""
    collection_name = "savani_kb"

    def __init__(self, docs: list[dict], persist_dir: Path, embed_model: str,
                 embedding_dimensions: int, embed: Callable[[str, str], list[float]], *, top_k: int = 3):
        self.docs, self.persist_dir = docs, persist_dir
        self.embed_model, self.embedding_dimensions, self.embed, self.top_k = (
            embed_model, embedding_dimensions, embed, top_k)
        self.chunks = chunks_for(docs)
        source = "\n".join(f"{d['doc_code']}|{d.get('version')}|{d['content']}" for d in docs)
        self.fingerprint = hashlib.sha256((embed_model + source).encode()).hexdigest()
        self._client = None
        self._collection = None

    @property
    def manifest_path(self) -> Path:
        return self.persist_dir / "manifest.json"

    def _open(self):
        if self._collection is not None:
            return self._collection
        import chromadb
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self.persist_dir))
        self._collection = self._client.get_or_create_collection(
            self.collection_name, metadata={"hnsw:space": "cosine"})
        return self._collection

    def _is_current(self) -> bool:
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))["fingerprint"] == self.fingerprint
        except (OSError, ValueError, KeyError):
            return False

    def _rebuild(self):
        """Embed and write all active KB chunks before exposing them to retrieval."""
        collection = self._open()
        if not self._is_current():
            try:
                self._client.delete_collection(self.collection_name)
            except Exception:
                pass
            self._collection = self._client.get_or_create_collection(
                self.collection_name, metadata={"hnsw:space": "cosine"})
            collection = self._collection
            if self.chunks:
                vectors = [self.embed(c["title"] + "\n" + c["section"] + "\n" + c["text"],
                                      "RETRIEVAL_DOCUMENT") for c in self.chunks]
                if any(len(vector) != self.embedding_dimensions for vector in vectors):
                    raise ValueError("Embedding không trả đúng 768 chiều theo cấu hình")
                collection.upsert(
                    ids=[c["chunk_id"] for c in self.chunks], embeddings=vectors,
                    documents=[c["text"] for c in self.chunks],
                    metadatas=[{k: c[k] for k in ("chunk_id", "doc_code", "title", "version", "source_file",
                                                   "effective_date", "is_active", "section")} for c in self.chunks],
                )
            self.manifest_path.write_text(json.dumps({"fingerprint": self.fingerprint}), encoding="utf-8")
        return collection

    def search(self, query: str) -> list[dict]:
        collection = self._rebuild()
        vector = self.embed(query, "RETRIEVAL_QUERY")
        if len(vector) != self.embedding_dimensions:
            raise ValueError("Embedding truy vấn không đúng 768 chiều theo cấu hình")
        today = int(datetime.now().strftime("%Y%m%d"))
        result = collection.query(
            query_embeddings=[vector], n_results=self.top_k,
            where={"$and": [{"is_active": {"$eq": True}}, {"effective_date": {"$lte": today}}]},
            include=["documents", "metadatas", "distances"],
        )
        docs = result.get("documents", [[]])[0] or []
        metas = result.get("metadatas", [[]])[0] or []
        distances = result.get("distances", [[]])[0] or []
        return [{"text": text, **meta, "similarity": round(1 - float(distance), 4)}
                for text, meta, distance in zip(docs, metas, distances)]
