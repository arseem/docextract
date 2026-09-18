"""LLM extraction stage: N worker threads pull pending documents and call
the backend concurrently (I/O-bound, so threads help despite the GIL); all
DB writes funnel through one lock ("single writer" - CLAUDE.md) so SQLite
never sees concurrent writers regardless of --workers. Per-document logic
is independent of thread count, so the resulting record set does not
depend on --workers (requirement 5).

Reliability layers on top of the per-document logic from milestone 4:
- budget: reserved upfront (input estimate + max output) before every call;
  a reservation that would exceed --budget stops the run immediately
  (stop_reason=budget_exhausted) without sending the request.
- retry+backoff (exponential, capped, jittered) for transport-level
  failures (timeout/connection error), bounded by config.retry.max_retries.
- circuit breaker: consecutive transport failures across ALL documents
  (shared, not per-document) trip it, so a fully-dead backend fails fast
  instead of retrying every remaining document one by one.
- invalid JSON (a successful response that doesn't parse/validate) is a
  per-document, not a backend-availability problem: exactly one retry,
  then quarantine llm_invalid_output - this never touches the circuit
  breaker or budget-driven stop.
- a document already in `extracted` status (SIGKILL between saving the
  raw response and finishing postprocessing) reuses that saved response
  instead of calling the model again (requirement 4).
"""

from __future__ import annotations

import random
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import db
from .budget import BudgetExhausted, BudgetTracker
from .config import RetryConfig, Settings
from .llm.base import LLMBackend, LLMResponse, LLMTimeoutError, LLMUnavailableError
from .postprocess import postprocess
from .progress import log
from .prompt import build_prompt, detect_language
from .schema import LLMOutputError, parse_llm_output
from .select import select_text


class BackendUnavailable(Exception):
    """The backend appears down, or the circuit breaker tripped - the run
    should stop with stop_reason=backend_unavailable, documents stay pending."""


class CircuitBreaker:
    def __init__(self, failure_threshold: int) -> None:
        self.failure_threshold = failure_threshold
        self._consecutive_failures = 0
        self._lock = threading.Lock()

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0

    def record_failure(self) -> bool:
        """Returns True if the circuit is now open."""
        with self._lock:
            self._consecutive_failures += 1
            return self._consecutive_failures >= self.failure_threshold


def _max_output_tokens(config: Settings) -> int:
    if config.backend.kind == "ollama":
        return config.backend.ollama.num_predict
    if config.backend.kind == "openai_compat":
        return config.backend.openai_compat.max_tokens
    return 512


def _sleep_backoff(retry: RetryConfig, attempt: int) -> None:
    backoff = min(retry.backoff_base_s * (2 ** (attempt - 1)), retry.backoff_max_s)
    time.sleep(backoff + backoff * random.uniform(0, 0.25))


def _resume_from_saved_response(conn: sqlite3.Connection, doc: sqlite3.Row) -> bool:
    last_call = conn.execute(
        "SELECT * FROM llm_calls WHERE document_id = ? AND status = 'ok' ORDER BY id DESC LIMIT 1",
        (doc["id"],),
    ).fetchone()
    if last_call is None:
        return False
    try:
        parsed = parse_llm_output(last_call["raw_response"])
    except LLMOutputError:
        return False
    fields = postprocess(parsed, doc["extracted_text"] or "")
    db.save_result(conn, doc["id"], fields)
    return True


def _call_with_retry(
    *,
    conn: sqlite3.Connection,
    run_id: int,
    doc_id: str,
    prompt: str,
    max_output_tokens: int,
    config: Settings,
    backend: LLMBackend,
    budget: BudgetTracker,
    breaker: CircuitBreaker,
    write_lock: threading.Lock,
    stop_event: threading.Event,
    json_attempt: int,
) -> LLMResponse:
    """One logical call (part of the outer invalid-JSON retry loop), with
    its own transport-level retry/backoff/circuit-breaker/budget handling."""
    max_sub_attempts = config.retry.max_retries + 1
    for sub_attempt in range(1, max_sub_attempts + 1):
        if stop_event.is_set():
            raise BackendUnavailable("stopping")

        reserved = budget.estimate_input_tokens(
            prompt, config.limits.bytes_per_token_estimate
        ) + max_output_tokens
        if not budget.try_reserve(reserved):
            stop_event.set()
            raise BudgetExhausted()

        started = db.now_iso()
        try:
            response = backend.generate(prompt, max_tokens=max_output_tokens)
        except LLMTimeoutError:
            budget.commit_reserved_as_used(reserved)
            with write_lock:
                db.save_llm_call(
                    conn, document_id=doc_id, run_id=run_id,
                    attempt=json_attempt * 100 + sub_attempt, status="timeout",
                    raw_response=None, parsed_json=None, tokens_in=0, tokens_out=0,
                    started_at=started, finished_at=db.now_iso(),
                )
            circuit_open = breaker.record_failure()
            if circuit_open or sub_attempt >= max_sub_attempts:
                stop_event.set()
                raise BackendUnavailable("timeout")
            _sleep_backoff(config.retry, sub_attempt)
            continue
        except LLMUnavailableError:
            budget.commit_actual(reserved, 0)
            with write_lock:
                db.save_llm_call(
                    conn, document_id=doc_id, run_id=run_id,
                    attempt=json_attempt * 100 + sub_attempt, status="unavailable",
                    raw_response=None, parsed_json=None, tokens_in=0, tokens_out=0,
                    started_at=started, finished_at=db.now_iso(),
                )
            circuit_open = breaker.record_failure()
            if circuit_open or sub_attempt >= max_sub_attempts:
                stop_event.set()
                raise BackendUnavailable("unavailable")
            _sleep_backoff(config.retry, sub_attempt)
            continue

        breaker.record_success()
        budget.commit_actual(reserved, response.tokens_in + response.tokens_out)
        return response

    raise BackendUnavailable("retries exhausted")  # pragma: no cover - loop always returns/raises above


def _process_document(
    *,
    conn: sqlite3.Connection,
    run_id: int,
    config: Settings,
    backend: LLMBackend,
    doc: sqlite3.Row,
    max_chars: int,
    max_output_tokens: int,
    budget: BudgetTracker,
    breaker: CircuitBreaker,
    write_lock: threading.Lock,
    stop_event: threading.Event,
) -> str:
    """Returns a short outcome string for progress logging."""
    if stop_event.is_set():
        return "skipped"

    if doc["status"] == "extracted":
        with write_lock:
            resumed = _resume_from_saved_response(conn, doc)
        if resumed:
            return "resumed"

    text = doc["extracted_text"] or ""
    language = detect_language(text)
    selected = select_text(text, max_chars=max_chars)
    prompt = build_prompt(
        selected_text=selected,
        language_hint=language,
        self_names=config.self_entities.names,
        self_tax_ids=config.self_entities.tax_ids,
    )

    quarantine_reason = None
    for json_attempt in (1, 2):
        if stop_event.is_set():
            return "skipped"
        response = _call_with_retry(
            conn=conn, run_id=run_id, doc_id=doc["id"], prompt=prompt,
            max_output_tokens=max_output_tokens, config=config, backend=backend,
            budget=budget, breaker=breaker, write_lock=write_lock,
            stop_event=stop_event, json_attempt=json_attempt,
        )
        finished = db.now_iso()
        try:
            parsed = parse_llm_output(response.text)
        except LLMOutputError:
            with write_lock:
                db.save_llm_call(
                    conn, document_id=doc["id"], run_id=run_id, attempt=json_attempt,
                    status="invalid_json", raw_response=response.text, parsed_json=None,
                    tokens_in=response.tokens_in, tokens_out=response.tokens_out,
                    started_at=finished, finished_at=finished,
                )
            quarantine_reason = "llm_invalid_output"
            continue

        with write_lock:
            db.save_llm_call(
                conn, document_id=doc["id"], run_id=run_id, attempt=json_attempt,
                status="ok", raw_response=response.text, parsed_json=parsed.model_dump_json(),
                tokens_in=response.tokens_in, tokens_out=response.tokens_out,
                started_at=finished, finished_at=finished,
            )
            db.mark_document_extracted(conn, doc["id"])
        fields = postprocess(parsed, text)
        with write_lock:
            db.save_result(conn, doc["id"], fields)
        quarantine_reason = None
        break

    if quarantine_reason:
        with write_lock:
            db.mark_document_quarantined(conn, doc["id"], quarantine_reason)
        return f"quarantined:{quarantine_reason}"
    return "done"


def run_llm_stage(
    conn: sqlite3.Connection,
    run_id: int,
    config: Settings,
    backend: LLMBackend,
    *,
    workers: int = 1,
    limit: int | None = None,
    budget: BudgetTracker | None = None,
) -> None:
    docs = db.pending_documents(conn, limit=limit)
    if not docs:
        log("[llm] no pending documents")
        return

    total = len(docs)
    log(f"[llm] processing {total} documents (workers={workers}, backend={config.backend.kind})")

    max_chars = int(config.limits.max_prompt_input_tokens * config.limits.bytes_per_token_estimate)
    max_output_tokens = _max_output_tokens(config)
    budget = budget if budget is not None else BudgetTracker(None)
    breaker = CircuitBreaker(config.retry.circuit_breaker_failures)
    write_lock = threading.Lock()
    stop_event = threading.Event()
    first_error: BaseException | None = None
    progress_lock = threading.Lock()
    completed = 0

    def run_one(doc: sqlite3.Row) -> None:
        nonlocal first_error, completed
        try:
            outcome = _process_document(
                conn=conn, run_id=run_id, config=config, backend=backend, doc=doc,
                max_chars=max_chars, max_output_tokens=max_output_tokens,
                budget=budget, breaker=breaker, write_lock=write_lock, stop_event=stop_event,
            )
        except (BackendUnavailable, BudgetExhausted) as e:
            stop_event.set()
            if first_error is None:
                first_error = e
            log(f"[llm] stopping: {type(e).__name__}: {e}")
            return
        with progress_lock:
            completed += 1
            n = completed
        log(f"[llm] [{n}/{total}] {outcome}: {doc['representative_path']}")

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = [executor.submit(run_one, doc) for doc in docs]
        for f in futures:
            f.result()

    if first_error is not None:
        raise first_error


def run_totals(conn: sqlite3.Connection, run_id: int) -> tuple[int, int]:
    row = conn.execute(
        "SELECT COALESCE(SUM(tokens_in), 0) ti, COALESCE(SUM(tokens_out), 0) to_ FROM llm_calls WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return int(row["ti"]), int(row["to_"])
