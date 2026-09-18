"""LLM extraction stage: for each pending document, build a prompt from its
persisted text, call the backend, validate+parse the JSON, postprocess with
grounding, and save. A document already in `extracted` state (SIGKILL hit
between saving the raw response and finishing postprocessing) reuses that
saved response instead of calling the model again (requirement 4).

Milestone 4 scope: single-threaded, one retry on invalid JSON. Workers,
budget enforcement, backoff and the circuit breaker are layered on in
milestone 5 without changing this module's per-document logic.
"""

from __future__ import annotations

import sqlite3

from . import db
from .config import Settings
from .llm.base import LLMBackend, LLMTimeoutError, LLMUnavailableError
from .postprocess import postprocess
from .prompt import build_prompt, detect_language
from .schema import LLMOutputError, parse_llm_output
from .select import select_text


class BackendUnavailable(Exception):
    """The backend appears down (timeout/connection error) - the run should
    stop with stop_reason=backend_unavailable, leaving documents pending."""


def _max_output_tokens(config: Settings) -> int:
    if config.backend.kind == "ollama":
        return config.backend.ollama.num_predict
    if config.backend.kind == "openai_compat":
        return config.backend.openai_compat.max_tokens
    return 512


def _resume_from_saved_response(conn: sqlite3.Connection, doc: sqlite3.Row) -> bool:
    """Returns True if the document was resolved from an already-saved LLM
    response (no new model call made)."""
    last_call = conn.execute(
        "SELECT * FROM llm_calls WHERE document_id = ? AND status = 'ok' ORDER BY id DESC LIMIT 1",
        (doc["id"],),
    ).fetchone()
    if last_call is None:
        return False
    try:
        parsed = parse_llm_output(last_call["raw_response"])
    except LLMOutputError:
        # Saved response somehow fails re-validation - fall through to a
        # fresh attempt rather than getting stuck.
        return False
    fields = postprocess(parsed, doc["extracted_text"] or "")
    db.save_result(conn, doc["id"], fields)
    return True


def run_llm_stage(
    conn: sqlite3.Connection,
    run_id: int,
    config: Settings,
    backend: LLMBackend,
    *,
    limit: int | None,
) -> None:
    docs = db.pending_documents(conn, limit=limit)
    max_chars = int(config.limits.max_prompt_input_tokens * config.limits.bytes_per_token_estimate)
    max_output_tokens = _max_output_tokens(config)

    for doc in docs:
        if doc["status"] == "extracted" and _resume_from_saved_response(conn, doc):
            continue

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
        for attempt in (1, 2):
            started = db.now_iso()
            try:
                response = backend.generate(prompt, max_tokens=max_output_tokens)
            except LLMTimeoutError as e:
                db.save_llm_call(
                    conn, document_id=doc["id"], run_id=run_id, attempt=attempt,
                    status="timeout", raw_response=None, parsed_json=None,
                    tokens_in=0, tokens_out=0, started_at=started, finished_at=db.now_iso(),
                )
                raise BackendUnavailable(str(e)) from e
            except LLMUnavailableError as e:
                db.save_llm_call(
                    conn, document_id=doc["id"], run_id=run_id, attempt=attempt,
                    status="unavailable", raw_response=None, parsed_json=None,
                    tokens_in=0, tokens_out=0, started_at=started, finished_at=db.now_iso(),
                )
                raise BackendUnavailable(str(e)) from e

            finished = db.now_iso()
            try:
                parsed = parse_llm_output(response.text)
            except LLMOutputError:
                db.save_llm_call(
                    conn, document_id=doc["id"], run_id=run_id, attempt=attempt,
                    status="invalid_json", raw_response=response.text, parsed_json=None,
                    tokens_in=response.tokens_in, tokens_out=response.tokens_out,
                    started_at=started, finished_at=finished,
                )
                quarantine_reason = "llm_invalid_output"
                continue

            db.save_llm_call(
                conn, document_id=doc["id"], run_id=run_id, attempt=attempt,
                status="ok", raw_response=response.text, parsed_json=parsed.model_dump_json(),
                tokens_in=response.tokens_in, tokens_out=response.tokens_out,
                started_at=started, finished_at=finished,
            )
            db.mark_document_extracted(conn, doc["id"])
            fields = postprocess(parsed, text)
            db.save_result(conn, doc["id"], fields)
            quarantine_reason = None
            break

        if quarantine_reason:
            db.mark_document_quarantined(conn, doc["id"], quarantine_reason)


def run_totals(conn: sqlite3.Connection, run_id: int) -> tuple[int, int]:
    row = conn.execute(
        "SELECT COALESCE(SUM(tokens_in), 0) ti, COALESCE(SUM(tokens_out), 0) to_ FROM llm_calls WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return int(row["ti"]), int(row["to_"])
