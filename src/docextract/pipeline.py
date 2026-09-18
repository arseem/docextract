"""Run orchestration.

Milestone 1: stub that only records a `runs` row so CLI/DB/report wiring is
testable end-to-end. Milestone 3+ replaces the body with scan -> extract ->
dedupe -> LLM -> postprocess, workers, resume and budget enforcement.
"""

from __future__ import annotations

import sqlite3

from . import db
from .config import Settings


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
    # TODO(milestone 3+): scan input_path, extract, dedupe, run LLM stage.
    db.end_run(
        conn,
        run_id,
        stop_reason="completed",
        tokens_in=0,
        tokens_out=0,
        estimated_cost="0.00",
    )
    return run_id
