"""
dataiq/db.py
------------
SQLite persistence layer for DataIQ.
Stores sessions and Q&A history so they survive server restarts.

Database file: dataiq.db  (created next to server.py automatically)

Tables:
  sessions    — one row per loaded dataset
  qa_history  — one row per question/answer pair
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Default DB path (next to server.py / project root)
_DEFAULT_DB_PATH = Path(__file__).parent.parent / "dataiq.db"


class DataIQDB:
    """Thin wrapper around a SQLite connection for DataIQ persistence."""

    def __init__(self, db_path: Path | str = _DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self._init_db()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _init_db(self):
        """Create tables if they don't exist."""
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id   TEXT PRIMARY KEY,
                    filename     TEXT NOT NULL,
                    num_rows     INTEGER,
                    num_cols     INTEGER,
                    columns_json TEXT,          -- JSON array of column names
                    schema_json  TEXT,          -- full schema dict as JSON
                    llm_backend  TEXT,
                    created_at   TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS qa_history (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id   TEXT NOT NULL,
                    query        TEXT NOT NULL,
                    answer       TEXT NOT NULL,
                    query_type   TEXT,          -- 'simple' | 'complex' | 'out_of_scope' | 'error'
                    duration_ms  INTEGER,       -- execution time in ms
                    created_at   TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                );

                CREATE INDEX IF NOT EXISTS idx_qa_session
                    ON qa_history(session_id, created_at DESC);
            """)

    @contextmanager
    def _conn(self):
        """Yield a SQLite connection with auto-commit context."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")   # safe concurrent reads
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def save_session(
        self,
        session_id: str,
        filename: str,
        schema: dict,
        llm_backend: str = "",
    ) -> None:
        """Insert or replace a session record."""
        cols = schema.get("columns", [])
        shape = schema.get("shape", {})
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sessions
                    (session_id, filename, num_rows, num_cols,
                     columns_json, schema_json, llm_backend, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    filename,
                    shape.get("rows"),
                    shape.get("cols"),
                    json.dumps(cols),
                    json.dumps(schema),
                    llm_backend,
                    _now(),
                ),
            )

    def get_session(self, session_id: str) -> Optional[dict]:
        """Return session metadata dict, or None if not found."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_sessions(self, limit: int = 20) -> list[dict]:
        """Return most recent sessions."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_session(self, session_id: str) -> None:
        """Delete session and all its Q&A history."""
        with self._conn() as conn:
            conn.execute("DELETE FROM qa_history WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM sessions   WHERE session_id = ?", (session_id,))

    # ------------------------------------------------------------------
    # Q&A History
    # ------------------------------------------------------------------

    def save_qa(
        self,
        session_id: str,
        query: str,
        answer: str,
        query_type: str = "",
        duration_ms: int = 0,
    ) -> int:
        """Insert a Q&A record. Returns the new row id."""
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO qa_history
                    (session_id, query, answer, query_type, duration_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, query, answer, query_type, duration_ms, _now()),
            )
        return cur.lastrowid

    def get_history(
        self,
        session_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Return Q&A history for a session, newest first."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, query, answer, query_type, duration_ms, created_at
                FROM qa_history
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (session_id, limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_all_history(self, limit: int = 100) -> list[dict]:
        """Return Q&A history across all sessions, newest first."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT h.id, h.session_id, s.filename,
                       h.query, h.answer, h.query_type,
                       h.duration_ms, h.created_at
                FROM qa_history h
                LEFT JOIN sessions s USING (session_id)
                ORDER BY h.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def count_qa(self, session_id: str) -> int:
        """Count total Q&A entries for a session."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM qa_history WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return row["n"] if row else 0

    def search_history(self, keyword: str, session_id: str | None = None, limit: int = 20) -> list[dict]:
        """Full-text search over queries in history."""
        like = f"%{keyword}%"
        with self._conn() as conn:
            if session_id:
                rows = conn.execute(
                    """SELECT id, session_id, query, answer, created_at
                       FROM qa_history
                       WHERE session_id = ? AND query LIKE ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (session_id, like, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT id, session_id, query, answer, created_at
                       FROM qa_history
                       WHERE query LIKE ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (like, limit),
                ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """Return summary statistics about the database."""
        with self._conn() as conn:
            n_sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            n_qa       = conn.execute("SELECT COUNT(*) FROM qa_history").fetchone()[0]
            db_size_kb = round(self.db_path.stat().st_size / 1024, 1) if self.db_path.exists() else 0
        return {
            "total_sessions": n_sessions,
            "total_qa":       n_qa,
            "db_path":        str(self.db_path),
            "db_size_kb":     db_size_kb,
        }


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _now() -> str:
    """UTC timestamp string."""
    return datetime.now(timezone.utc).isoformat()


# Module-level singleton used by server.py
_db_instance: DataIQDB | None = None


def get_db(db_path: Path | str = _DEFAULT_DB_PATH) -> DataIQDB:
    """Return the module-level DB singleton, creating it if needed."""
    global _db_instance
    if _db_instance is None:
        _db_instance = DataIQDB(db_path)
    return _db_instance
