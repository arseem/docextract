"""Run orchestration.

Milestone 3: scan -> extract -> dedupe -> quarantine is wired in and
persisted; the report already balances on real data. Milestone 4+ adds the
LLM stage (workers, resume, budget enforcement) between scan and end_run.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import db
from .config import Settings
from .scan_stage import run_scan_stage


def run(
    conn: sqlite3.Connection,
    *,
    input_path: str,
    config: Settings,
    workers: int,
    limit: int | None,
    budget: int | None,
) -> int:
    """Execute (or resume) a run against the given input. Returns the run id."""
    model_tag, model_digest = config.active_model_identity()
    run_id = db.create_run(
        conn,
        input_path=input_path,
        config_hash=config.config_hash(),
        backend=config.backend.kind,
        model_tag=model_tag,
        model_digest=model_digest,
        workers=workers,
        limit_n=limit,
        budget=budget,
    )

    run_scan_stage(conn, Path(input_path), run_id, config.limits)

    # TODO(milestone 4+): LLM stage (workers, resume, budget enforcement).
    db.end_run(
        conn,
        run_id,
        stop_reason="completed",
        tokens_in=0,
        tokens_out=0,
        estimated_cost="0.00",
    )
    return run_id
