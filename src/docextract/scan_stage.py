"""Scan -> extract -> dedupe -> quarantine. Populates `files` and
`documents`. Idempotent by design (see docs/DECISIONS.md): safe to re-run
on every invocation, including after a SIGKILL mid-stage - fingerprints
already recorded for a path are reused instead of re-extracted, and
`documents` rows are inserted with INSERT OR IGNORE so an already-advanced
document (extracted/done/quarantined by a later stage) is never reset.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path

from . import db
from .config import LimitsConfig
from .extract.timeout import extract_with_timeout
from .normalize import fingerprint_of_text
from .scan import scan_files


def run_scan_stage(conn: sqlite3.Connection, input_path: Path, run_id: int, limits: LimitsConfig) -> None:
    large_threshold_bytes = int(limits.large_file_threshold_mb * 1024 * 1024)

    with scan_files(input_path, max_zip_uncompressed_mb=limits.max_zip_uncompressed_mb) as scanned:
        raw_groups: dict[str, list] = defaultdict(list)
        for sf in scanned:
            raw_groups[sf.raw_sha256].append(sf)

        existing = {row["path"]: row for row in conn.execute("SELECT * FROM files").fetchall()}

        for raw_sha, members in raw_groups.items():
            members = sorted(members, key=lambda m: m.relpath)
            fingerprint, reason = _known_outcome(members, existing)
            if fingerprint is None:
                outcome = extract_with_timeout(
                    members[0].abspath,
                    large_threshold_bytes=large_threshold_bytes,
                    timeout_s=limits.extract_timeout_s,
                )
                if outcome.text is not None:
                    fingerprint = fingerprint_of_text(outcome.text)
                    reason = None
                else:
                    fingerprint = raw_sha  # unreadable file -> fingerprint = raw bytes hash
                    reason = outcome.reason

            for m in members:
                conn.execute(
                    """
                    INSERT INTO files (
                        path, size_bytes, raw_sha256, fingerprint, error_reason,
                        status, discovered_run_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, 'scanned', ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        size_bytes = excluded.size_bytes,
                        raw_sha256 = excluded.raw_sha256,
                        fingerprint = excluded.fingerprint,
                        error_reason = excluded.error_reason
                    """,
                    (m.relpath, m.size_bytes, m.raw_sha256, fingerprint, reason, run_id, db.now_iso()),
                )

    _assign_documents(conn)


def _known_outcome(members: list, existing: dict) -> tuple[str | None, str | None]:
    for m in members:
        row = existing.get(m.relpath)
        if row is not None and row["fingerprint"]:
            return row["fingerprint"], row["error_reason"]
    return None, None


def _assign_documents(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT path, fingerprint, error_reason FROM files").fetchall()
    by_fingerprint: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_fingerprint[row["fingerprint"]].append(row)

    for fingerprint, group in by_fingerprint.items():
        paths = sorted(r["path"] for r in group)
        representative_path = paths[0]
        reason = next((r["error_reason"] for r in group if r["error_reason"]), None)
        status = "quarantined" if reason else "pending"
        now = db.now_iso()
        conn.execute(
            """
            INSERT OR IGNORE INTO documents (
                id, representative_path, status, quarantine_reason, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (fingerprint, representative_path, status, reason, now, now),
        )
        for r in group:
            new_status = "scanned" if r["path"] == representative_path else "duplicate"
            conn.execute(
                "UPDATE files SET document_id = ?, status = ? WHERE path = ?",
                (fingerprint, new_status, r["path"]),
            )
