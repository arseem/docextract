"""Run orchestration.

Milestone 4: scan -> extract -> dedupe -> quarantine -> LLM extraction ->
postprocess, single-threaded. Milestone 5 adds workers, resume-aware retry/
backoff/circuit breaker and budget enforcement without changing the
per-document logic in llm_stage.py.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import db
from .budget import BudgetExhausted, BudgetTracker
from .config import Settings
from .llm.factory import build_backend
from .llm_stage import BackendUnavailable, run_llm_stage, run_totals
from .progress import log
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
    log(f"[run] input={input_path} backend={config.backend.kind} model={model_tag} workers={workers}")
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

    backend = build_backend(config)
    if config.backend.kind != "fake":
        backend.verify_model_available()  # LLMError propagates -> caller exits non-zero
        log(f"[run] model verified: {model_tag}@{model_digest}")

    run_scan_stage(conn, Path(input_path), run_id, config.limits)

    stop_reason = "completed"
    budget_tracker = BudgetTracker(budget)
    try:
        run_llm_stage(conn, run_id, config, backend, workers=workers, limit=limit, budget=budget_tracker)
        if limit is not None:
            remaining = conn.execute(
                "SELECT COUNT(*) c FROM documents WHERE status IN ('pending', 'extracted')"
            ).fetchone()["c"]
            if remaining > 0:
                stop_reason = "limit_reached"
    except BudgetExhausted:
        stop_reason = "budget_exhausted"
    except BackendUnavailable:
        stop_reason = "backend_unavailable"

    tokens_in, tokens_out = run_totals(conn, run_id)
    estimated_cost = _estimate_cost(config, tokens_in, tokens_out)
    db.end_run(
        conn,
        run_id,
        stop_reason=stop_reason,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        estimated_cost=estimated_cost,
    )
    log(f"[run] finished: stop_reason={stop_reason} tokens_in={tokens_in} tokens_out={tokens_out}")
    return run_id


def _estimate_cost(config: Settings, tokens_in: int, tokens_out: int) -> str:
    from decimal import ROUND_HALF_UP, Decimal

    cost = (
        Decimal(tokens_in) * Decimal(str(config.pricing.input_per_million)) / Decimal(1_000_000)
        + Decimal(tokens_out) * Decimal(str(config.pricing.output_per_million)) / Decimal(1_000_000)
    )
    return str(cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))
