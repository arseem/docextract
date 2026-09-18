"""Builds the report described in ZADANIE.md #7 from the current DB state.

Token/cost/stop_reason/backend/model/wall_time_s reflect the most recent run
row (budget is scoped per invocation, see docs/DECISIONS.md); file and
document counts reflect the whole database, since dedup/processing state
spans resumed invocations.
"""

from __future__ import annotations

import sqlite3
from typing import Any


class ReportImbalanceError(AssertionError):
    pass


def compute_report(conn: sqlite3.Connection) -> dict[str, Any]:
    run = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()

    input_files = conn.execute("SELECT COUNT(*) c FROM files").fetchone()["c"]
    duplicate_files = conn.execute(
        "SELECT COUNT(*) c FROM files WHERE status = 'duplicate'"
    ).fetchone()["c"]
    unique_documents = conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"]
    processed_ok = conn.execute(
        "SELECT COUNT(*) c FROM documents WHERE status = 'done'"
    ).fetchone()["c"]
    quarantined = conn.execute(
        "SELECT COUNT(*) c FROM documents WHERE status = 'quarantined'"
    ).fetchone()["c"]
    not_started = conn.execute(
        "SELECT COUNT(*) c FROM documents WHERE status IN ('pending', 'extracted')"
    ).fetchone()["c"]

    reason_rows = conn.execute(
        """
        SELECT quarantine_reason AS reason, COUNT(*) AS c
        FROM documents WHERE status = 'quarantined'
        GROUP BY quarantine_reason
        """
    ).fetchall()
    quarantine_by_reason = {row["reason"]: row["c"] for row in reason_rows}

    wall_time_s = None
    backend = model = stop_reason = None
    tokens_in = tokens_out = 0
    estimated_cost = "0.00"
    if run is not None:
        backend = run["backend"]
        model = f"{run['model_tag']}@{run['model_digest']}"
        stop_reason = run["stop_reason"]
        tokens_in = run["tokens_in"]
        tokens_out = run["tokens_out"]
        estimated_cost = run["estimated_cost"]
        if run["ended_at"] is not None:
            from datetime import datetime

            started = datetime.fromisoformat(run["started_at"])
            ended = datetime.fromisoformat(run["ended_at"])
            wall_time_s = (ended - started).total_seconds()

    report = {
        "input_files": input_files,
        "duplicate_files": duplicate_files,
        "unique_documents": unique_documents,
        "processed_ok": processed_ok,
        "quarantined": quarantined,
        "quarantine_by_reason": quarantine_by_reason,
        "not_started": not_started,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "estimated_cost": estimated_cost,
        "wall_time_s": wall_time_s,
        "backend": backend,
        "model": model,
        "stop_reason": stop_reason,
    }
    check_invariants(report)
    return report


def check_invariants(report: dict[str, Any]) -> None:
    if report["input_files"] != report["duplicate_files"] + report["unique_documents"]:
        raise ReportImbalanceError(
            "input_files != duplicate_files + unique_documents: "
            f"{report['input_files']} != {report['duplicate_files']} + {report['unique_documents']}"
        )
    total = report["processed_ok"] + report["quarantined"] + report["not_started"]
    if report["unique_documents"] != total:
        raise ReportImbalanceError(
            "unique_documents != processed_ok + quarantined + not_started: "
            f"{report['unique_documents']} != {total}"
        )
