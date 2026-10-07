"""Response cache (SQLite). An optimisation only — every entry keeps its original
retrieval time, so cached content can never masquerade as freshly retrieved."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from ..core.util import iso, now_iso, parse_iso, utc_now
from .db import Database, dumps, loads


@dataclass
class CacheEntry:
    key: str
    url: str
    final_url: str
    status: int
    content_type: str
    headers: dict
    body: bytes
    content_sha256: str
    retrieved_at: str
    created_at: str
    expires_at: str


class ResponseCache:
    def __init__(self, db: Database, *, max_body_bytes: int = 3_000_000):
        self.db = db
        self.max_body_bytes = max_body_bytes

    def get(self, key: str) -> CacheEntry | None:
        row = self.db.one("SELECT * FROM cache_entries WHERE key=?", (key,))
        if row is None:
            return None
        expires = parse_iso(row["expires_at"])
        if expires is None or expires <= utc_now():
            return None
        return CacheEntry(
            key=row["key"], url=row["url"], final_url=row["final_url"] or row["url"], status=int(row["status"] or 0),
            content_type=row["content_type"] or "", headers=loads(row["headers_json"], {}), body=row["body"] or b"",
            content_sha256=row["content_sha256"] or "", retrieved_at=row["retrieved_at"], created_at=row["created_at"], expires_at=row["expires_at"],
        )

    def put(self, *, key: str, source: str, url: str, final_url: str, status: int, content_type: str, headers: dict, body: bytes, content_sha256: str, retrieved_at: str, ttl_seconds: int) -> None:
        if ttl_seconds <= 0 or len(body) > self.max_body_bytes:
            return
        expires = iso(utc_now() + timedelta(seconds=ttl_seconds))
        self.db.execute(
            "INSERT OR REPLACE INTO cache_entries(key, source, url, created_at, expires_at, retrieved_at, status, final_url, content_type, content_sha256, headers_json, body) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (key, source, url, now_iso(), expires, retrieved_at, status, final_url, content_type, content_sha256, dumps(headers), body),
        )

    def purge_expired(self) -> int:
        cur = self.db.execute("DELETE FROM cache_entries WHERE expires_at <= ?", (now_iso(),))
        return cur.rowcount or 0

    def invalidate_prefix(self, url_prefix: str) -> None:
        self.db.execute("DELETE FROM cache_entries WHERE url LIKE ?", (url_prefix + "%",))
