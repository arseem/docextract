"""SQLite schema and low-level access.

Single writer, short transactions, WAL mode so a SIGKILL mid-write leaves the
database in a consistent, resumable state. The only place that writes an
LLM-derived result is `save_llm_result` / `save_document_fields` below, both
parametrized and keyed by `document_id` supplied by the pipeline (never by
the model) — see requirement 8 (integrity) in CLAUDE.md.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    input_path TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    backend TEXT NOT NULL,
    model_tag TEXT NOT NULL,
    model_digest TEXT NOT NULL,
    workers INTEGER NOT NULL,
    limit_n INTEGER,
    budget INTEGER,
    stop_reason TEXT,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    estimated_cost TEXT NOT NULL DEFAULT '0'
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    size_bytes INTEGER NOT NULL,
    raw_sha256 TEXT NOT NULL,
    fingerprint TEXT,
    document_id TEXT,
    status TEXT NOT NULL DEFAULT 'scanned',
    error_reason TEXT,
    discovered_run_id INTEGER NOT NULL REFERENCES runs(id),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_files_document_id ON files(document_id);
CREATE INDEX IF NOT EXISTS idx_files_fingerprint ON files(fingerprint);
CREATE INDEX IF NOT EXISTS idx_files_raw_sha256 ON files(raw_sha256);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    representative_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    quarantine_reason TEXT,
    -- Persisted (not re-read from the input path) so the LLM/postprocess
    -- stages work uniformly for zip inputs (temp-extracted, gone once the
    -- scan stage's context exits) and for resumed runs, and so grounding
    -- checks always have text available regardless of when they run.
    extracted_text TEXT,
    doc_type TEXT,
    counterparty_name TEXT,
    counterparty_tax_id TEXT,
    issue_date TEXT,
    due_date TEXT,
    gross_amount TEXT,
    currency TEXT,
    summary TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);

CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL REFERENCES documents(id),
    run_id INTEGER NOT NULL REFERENCES runs(id),
    attempt INTEGER NOT NULL,
    status TEXT NOT NULL,
    raw_response TEXT,
    parsed_json TEXT,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_document_id ON llm_calls(document_id);
CREATE INDEX IF NOT EXISTS idx_llm_calls_run_id ON llm_calls(run_id);
"""

DOCUMENT_STATUSES = ("pending", "extracted", "done", "quarantined")
QUARANTINE_REASONS = (
    "unsupported_format",
    "corrupt_file",
    "encrypted",
    "empty_text",
    "extract_timeout",
    "extract_crash",
    "llm_invalid_output",
    "too_large",
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


@contextmanager
def open_db(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        init_db(conn)
        yield conn
    finally:
        conn.close()


def create_run(
    conn: sqlite3.Connection,
    *,
    input_path: str,
    config_hash: str,
    backend: str,
    model_tag: str,
    model_digest: str,
    workers: int,
    limit_n: int | None,
    budget: int | None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO runs (
            started_at, input_path, config_hash, backend, model_tag,
            model_digest, workers, limit_n, budget
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            now_iso(),
            input_path,
            config_hash,
            backend,
            model_tag,
            model_digest,
            workers,
            limit_n,
            budget,
        ),
    )
    return int(cur.lastrowid)


def end_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    stop_reason: str,
    tokens_in: int,
    tokens_out: int,
    estimated_cost: str,
) -> None:
    conn.execute(
        """
        UPDATE runs SET ended_at = ?, stop_reason = ?, tokens_in = ?,
            tokens_out = ?, estimated_cost = ?
        WHERE id = ?
        """,
        (now_iso(), stop_reason, tokens_in, tokens_out, estimated_cost, run_id),
    )


def latest_unfinished_run(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """A run with no ended_at means a prior invocation was interrupted (SIGKILL)."""
    return conn.execute(
        "SELECT * FROM runs WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()


def pending_documents(conn: sqlite3.Connection, limit: int | None = None) -> list[sqlite3.Row]:
    """Documents not yet finished, in deterministic order (requirement 4/5:
    processing order, and therefore what `--limit N` picks, must not depend
    on `--workers` or on scan/filesystem iteration order)."""
    rows = conn.execute(
        "SELECT * FROM documents WHERE status IN ('pending', 'extracted') "
        "ORDER BY representative_path"
    ).fetchall()
    return rows[:limit] if limit is not None else rows


def save_llm_call(
    conn: sqlite3.Connection,
    *,
    document_id: str,
    run_id: int,
    attempt: int,
    status: str,
    raw_response: str | None,
    parsed_json: str | None,
    tokens_in: int,
    tokens_out: int,
    started_at: str,
    finished_at: str,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO llm_calls (
            document_id, run_id, attempt, status, raw_response, parsed_json,
            tokens_in, tokens_out, started_at, finished_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document_id, run_id, attempt, status, raw_response, parsed_json,
            tokens_in, tokens_out, started_at, finished_at,
        ),
    )
    return int(cur.lastrowid)


def mark_document_extracted(conn: sqlite3.Connection, document_id: str) -> None:
    conn.execute(
        "UPDATE documents SET status = 'extracted', updated_at = ? WHERE id = ?",
        (now_iso(), document_id),
    )


def save_result(conn: sqlite3.Connection, document_id: str, fields: dict) -> None:
    """The only place that writes LLM-derived fields to `documents`.
    `document_id` always comes from the pipeline (the fingerprint computed
    during scanning), never from model output - parametrized SQL, no
    dynamic SQL, no executescript on document-derived data (requirement 8)."""
    conn.execute(
        """
        UPDATE documents SET
            status = 'done', doc_type = ?, counterparty_name = ?,
            counterparty_tax_id = ?, issue_date = ?, due_date = ?,
            gross_amount = ?, currency = ?, summary = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            fields["doc_type"], fields["counterparty_name"], fields["counterparty_tax_id"],
            fields["issue_date"], fields["due_date"], fields["gross_amount"],
            fields["currency"], fields["summary"], now_iso(), document_id,
        ),
    )


def mark_document_quarantined(conn: sqlite3.Connection, document_id: str, reason: str) -> None:
    conn.execute(
        "UPDATE documents SET status = 'quarantined', quarantine_reason = ?, updated_at = ? WHERE id = ?",
        (reason, now_iso(), document_id),
    )
