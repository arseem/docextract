from __future__ import annotations

import pytest

from docextract import db
from docextract.config import Settings
from docextract.llm.fake import FakeBackend
from docextract.llm_stage import BackendUnavailable, run_llm_stage


def _seed_document(conn, doc_id: str, text: str, status: str = "pending") -> None:
    now = db.now_iso()
    conn.execute(
        "INSERT INTO documents (id, representative_path, status, extracted_text, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (doc_id, f"{doc_id}.txt", status, text, now, now),
    )


@pytest.fixture
def conn_with_run(tmp_path):
    with db.open_db(tmp_path / "t.sqlite") as conn:
        run_id = db.create_run(
            conn, input_path="in", config_hash="h", backend="fake", model_tag="t",
            model_digest="d", workers=1, limit_n=None, budget=None,
        )
        yield conn, run_id


def test_successful_extraction_saves_result(conn_with_run):
    conn, run_id = conn_with_run
    _seed_document(conn, "doc1", "Faktura od TechNova, NIP 526-301-82-76")
    backend = FakeBackend(
        responses='{"doc_type": "invoice", "counterparty_name": "TechNova", '
        '"counterparty_tax_id": "526-301-82-76", "issue_date": null, "due_date": null, '
        '"gross_amount": null, "currency": null, "summary": "Faktura od TechNova."}'
    )
    run_llm_stage(conn, run_id, Settings(), backend, limit=None)

    row = conn.execute("SELECT * FROM documents WHERE id = 'doc1'").fetchone()
    assert row["status"] == "done"
    assert row["counterparty_tax_id"] == "5263018276"
    assert len(backend.calls) == 1


def test_invalid_json_retries_once_then_quarantines(conn_with_run):
    conn, run_id = conn_with_run
    _seed_document(conn, "doc1", "some text")
    backend = FakeBackend(responses="not json at all")

    run_llm_stage(conn, run_id, Settings(), backend, limit=None)

    row = conn.execute("SELECT * FROM documents WHERE id = 'doc1'").fetchone()
    assert row["status"] == "quarantined"
    assert row["quarantine_reason"] == "llm_invalid_output"
    assert len(backend.calls) == 2  # one retry

    calls = conn.execute("SELECT status FROM llm_calls WHERE document_id = 'doc1'").fetchall()
    assert [c["status"] for c in calls] == ["invalid_json", "invalid_json"]


def test_retry_succeeds_on_second_attempt(conn_with_run):
    conn, run_id = conn_with_run
    _seed_document(conn, "doc1", "text")
    backend = FakeBackend(
        responses=iter(
            [
                "not json",
                '{"doc_type": "other", "counterparty_name": null, "counterparty_tax_id": null, '
                '"issue_date": null, "due_date": null, "gross_amount": null, "currency": null, '
                '"summary": "ok"}',
            ]
        )
    )
    run_llm_stage(conn, run_id, Settings(), backend, limit=None)
    row = conn.execute("SELECT status FROM documents WHERE id = 'doc1'").fetchone()
    assert row["status"] == "done"
    assert len(backend.calls) == 2


def test_timeout_raises_backend_unavailable_and_leaves_document_pending(conn_with_run):
    conn, run_id = conn_with_run
    _seed_document(conn, "doc1", "text")
    backend = FakeBackend(responses=iter([TimeoutError("slow")]))

    with pytest.raises(BackendUnavailable):
        run_llm_stage(conn, run_id, Settings(), backend, limit=None)

    row = conn.execute("SELECT status FROM documents WHERE id = 'doc1'").fetchone()
    assert row["status"] == "pending"  # not quarantined, not lost


def test_resume_from_extracted_status_does_not_call_backend_again(conn_with_run):
    conn, run_id = conn_with_run
    text = "Faktura od TechNova, NIP 526-301-82-76"
    _seed_document(conn, "doc1", text, status="extracted")
    ok_response = (
        '{"doc_type": "invoice", "counterparty_name": "TechNova", '
        '"counterparty_tax_id": "526-301-82-76", "issue_date": null, "due_date": null, '
        '"gross_amount": null, "currency": null, "summary": "Faktura od TechNova."}'
    )
    conn.execute(
        "INSERT INTO llm_calls (document_id, run_id, attempt, status, raw_response, parsed_json, "
        "tokens_in, tokens_out, started_at, finished_at) VALUES (?, ?, 1, 'ok', ?, NULL, 10, 5, ?, ?)",
        ("doc1", run_id, ok_response, db.now_iso(), db.now_iso()),
    )

    backend = FakeBackend()  # would answer, but must never be called
    run_llm_stage(conn, run_id, Settings(), backend, limit=None)

    assert len(backend.calls) == 0
    row = conn.execute("SELECT status, counterparty_tax_id FROM documents WHERE id = 'doc1'").fetchone()
    assert row["status"] == "done"
    assert row["counterparty_tax_id"] == "5263018276"


def test_unknown_json_keys_rejected_and_quarantined(conn_with_run):
    conn, run_id = conn_with_run
    _seed_document(conn, "doc1", "text")
    backend = FakeBackend(
        responses='{"doc_type": "other", "summary": "ok", "sql": "DROP TABLE documents"}'
    )
    run_llm_stage(conn, run_id, Settings(), backend, limit=None)
    row = conn.execute("SELECT status, quarantine_reason FROM documents WHERE id = 'doc1'").fetchone()
    assert row["status"] == "quarantined"
    assert row["quarantine_reason"] == "llm_invalid_output"
