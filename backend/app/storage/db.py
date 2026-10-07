"""SQLite storage with tracked, additive migrations.

One file (``data/app.sqlite``), WAL mode, a single shared connection guarded by
a re-entrant lock. Migrations are numbered, recorded in ``schema_migrations``
and only ever add structure — nothing is dropped silently.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..core.util import now_iso

MIGRATIONS: list[tuple[int, str, str]] = [
    (
        1,
        "core research schema",
        """
        CREATE TABLE IF NOT EXISTS companies (
            org_number TEXT PRIMARY KEY,
            legal_name TEXT,
            legal_form TEXT,
            status TEXT,
            municipality TEXT,
            municipality_number TEXT,
            industry_code TEXT,
            industry_label TEXT,
            website TEXT,
            employees INTEGER,
            registry_json TEXT,
            first_seen_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_researched_at TEXT,
            research_state TEXT NOT NULL DEFAULT 'not_researched'
        );
        CREATE INDEX IF NOT EXISTS ix_companies_name ON companies(legal_name);

        CREATE TABLE IF NOT EXISTS source_snapshots (
            id TEXT PRIMARY KEY,
            org_number TEXT,
            source_name TEXT NOT NULL,
            source_class TEXT NOT NULL,
            url TEXT NOT NULL,
            canonical_url TEXT,
            final_url TEXT,
            retrieved_at TEXT NOT NULL,
            published_at TEXT,
            http_status INTEGER,
            content_type TEXT,
            content_sha256 TEXT,
            normalized_sha256 TEXT,
            title TEXT,
            bytes INTEGER,
            identity_json TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_snapshots_org ON source_snapshots(org_number, source_name);

        CREATE TABLE IF NOT EXISTS evidence (
            id TEXT PRIMARY KEY,
            org_number TEXT NOT NULL,
            snapshot_id TEXT,
            field TEXT,
            source_name TEXT NOT NULL,
            source_class TEXT NOT NULL,
            source_url TEXT,
            retrieved_at TEXT NOT NULL,
            content_sha256 TEXT,
            claim_span TEXT,
            extraction_method TEXT,
            identity_score REAL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_evidence_org ON evidence(org_number);

        CREATE TABLE IF NOT EXISTS facts (
            claim_key TEXT PRIMARY KEY,
            org_number TEXT NOT NULL,
            field TEXT NOT NULL,
            value_json TEXT,
            value_sha TEXT,
            availability TEXT NOT NULL,
            reporting_period TEXT,
            effective_from TEXT,
            effective_to TEXT,
            source_class TEXT,
            confidence REAL,
            evidence_ids_json TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            current INTEGER NOT NULL DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS ix_facts_org ON facts(org_number, field);

        CREATE TABLE IF NOT EXISTS fact_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_key TEXT NOT NULL,
            version INTEGER NOT NULL,
            value_json TEXT,
            observed_at TEXT NOT NULL,
            evidence_ids_json TEXT,
            UNIQUE(claim_key, version)
        );

        CREATE TABLE IF NOT EXISTS changes (
            id TEXT PRIMARY KEY,
            org_number TEXT NOT NULL,
            field TEXT NOT NULL,
            category TEXT,
            kind TEXT,
            old_value_json TEXT,
            new_value_json TEXT,
            detected_at TEXT NOT NULL,
            effective_at TEXT,
            source_url TEXT,
            source_class TEXT,
            old_content_sha256 TEXT,
            new_content_sha256 TEXT,
            material INTEGER NOT NULL DEFAULT 1,
            headline TEXT,
            payload_json TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_changes_org ON changes(org_number, detected_at);

        CREATE TABLE IF NOT EXISTS profile_versions (
            id TEXT PRIMARY KEY,
            org_number TEXT NOT NULL,
            created_at TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            research_json TEXT NOT NULL,
            label TEXT,
            run_id TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_profile_versions_org ON profile_versions(org_number, created_at);

        CREATE TABLE IF NOT EXISTS research_runs (
            run_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            input_count INTEGER,
            completed_count INTEGER,
            requests INTEGER,
            cost_usd REAL,
            llm_calls INTEGER,
            report_json TEXT
        );

        CREATE TABLE IF NOT EXISTS company_runs (
            run_id TEXT NOT NULL,
            org_number TEXT NOT NULL,
            status TEXT NOT NULL,
            terminal_state TEXT,
            started_at TEXT,
            finished_at TEXT,
            requests INTEGER,
            llm_calls INTEGER,
            facts_found INTEGER,
            facts_published INTEGER,
            facts_rejected INTEGER,
            error_summary TEXT,
            PRIMARY KEY (run_id, org_number)
        );

        CREATE TABLE IF NOT EXISTS tool_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            org_number TEXT,
            connector TEXT NOT NULL,
            operation TEXT,
            url TEXT,
            classification TEXT,
            http_status INTEGER,
            duration_ms INTEGER,
            retries INTEGER,
            from_cache INTEGER,
            at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_tool_calls_org ON tool_calls(org_number);

        CREATE TABLE IF NOT EXISTS cache_entries (
            key TEXT PRIMARY KEY,
            source TEXT,
            url TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            status INTEGER,
            final_url TEXT,
            content_type TEXT,
            content_sha256 TEXT,
            headers_json TEXT,
            body BLOB
        );
        """,
    ),
    (
        2,
        "workspace schema (library, sheets, watchlist, exports)",
        """
        CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            org_number TEXT,
            target_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            viewed_at TEXT,
            tags_json TEXT NOT NULL DEFAULT '[]',
            pinned INTEGER NOT NULL DEFAULT 0,
            archived INTEGER NOT NULL DEFAULT 0,
            data_json TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_artifacts_org ON artifacts(org_number);

        CREATE TABLE IF NOT EXISTS artifact_versions (
            id TEXT PRIMARY KEY,
            artifact_id TEXT NOT NULL,
            profile_version_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            label TEXT NOT NULL,
            note TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_artifact_versions ON artifact_versions(artifact_id, created_at);

        CREATE TABLE IF NOT EXISTS sheets (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            criteria_json TEXT NOT NULL DEFAULT '[]',
            columns_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sheet_rows (
            sheet_id TEXT NOT NULL,
            row_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            org_number TEXT NOT NULL,
            company_json TEXT NOT NULL,
            cells_json TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY (sheet_id, row_id)
        );

        CREATE TABLE IF NOT EXISTS watchlist (
            org_number TEXT PRIMARY KEY,
            added_at TEXT NOT NULL,
            last_checked_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS signals (
            id TEXT PRIMARY KEY,
            org_number TEXT NOT NULL,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            evidence_json TEXT NOT NULL DEFAULT '[]',
            seen INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS exports (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            path TEXT NOT NULL,
            content_type TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS recent_companies (
            org_number TEXT PRIMARY KEY,
            viewed_at TEXT NOT NULL
        );
        """,
    ),
]


class Database:
    """Thread-safe SQLite wrapper. Use ``Database.open(path)``; tests may pass ':memory:'."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
        self.migrate()

    # ---------------------------------------------------------------- core --
    def migrate(self) -> list[int]:
        applied: list[int] = []
        with self._lock:
            self.conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)")
            done = {row[0] for row in self.conn.execute("SELECT version FROM schema_migrations")}
            for version, name, sql in MIGRATIONS:
                if version in done:
                    continue
                self.conn.execute("BEGIN")
                try:
                    for statement in [s.strip() for s in sql.split(";") if s.strip()]:
                        self.conn.execute(statement)
                    self.conn.execute("INSERT INTO schema_migrations(version, name, applied_at) VALUES (?,?,?)", (version, name, now_iso()))
                    self.conn.execute("COMMIT")
                except Exception:
                    self.conn.execute("ROLLBACK")
                    raise
                applied.append(version)
        return applied

    def schema_version(self) -> int:
        with self._lock:
            row = self.conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
            return int(row[0] or 0)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self.conn.execute("BEGIN")
            try:
                yield self.conn
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.execute(sql, tuple(params))

    def executemany(self, sql: str, rows: Iterable[Iterable[Any]]) -> None:
        with self._lock:
            self.conn.executemany(sql, [tuple(r) for r in rows])

    def one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(sql, tuple(params)).fetchone()

    def all(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.conn.execute(sql, tuple(params)).fetchall())

    def close(self) -> None:
        with self._lock:
            self.conn.close()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def loads(value: str | bytes | None, default: Any = None) -> Any:
    if value in (None, "", b""):
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


_db: Database | None = None
_db_lock = threading.Lock()


def get_db() -> Database:
    from ..config import get_settings

    global _db
    with _db_lock:
        if _db is None:
            _db = Database(get_settings().db_path)
        return _db


def set_db(db: Database | None) -> None:
    """Test/CLI hook to swap the process database."""
    global _db
    with _db_lock:
        _db = db
