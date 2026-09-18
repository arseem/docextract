from __future__ import annotations

import pytest

from docextract import db, report


def test_empty_db_report_balances(tmp_path):
    with db.open_db(tmp_path / "test.sqlite") as conn:
        rep = report.compute_report(conn)
    assert rep["input_files"] == 0
    assert rep["unique_documents"] == 0
    assert rep["stop_reason"] is None


def test_report_reflects_documents_and_balances(tmp_path):
    with db.open_db(tmp_path / "test.sqlite") as conn:
        run_id = db.create_run(
            conn,
            input_path="in",
            config_hash="h",
            backend="fake",
            model_tag="fake-v1",
            model_digest="fake",
            workers=1,
            limit_n=None,
            budget=None,
        )
        conn.execute(
            "INSERT INTO files (path, size_bytes, raw_sha256, document_id, status, "
            "discovered_run_id, created_at) VALUES (?, 1, 'h1', 'doc1', 'scanned', ?, ?)",
            ("a.txt", run_id, db.now_iso()),
        )
        conn.execute(
            "INSERT INTO files (path, size_bytes, raw_sha256, document_id, status, "
            "discovered_run_id, created_at) VALUES (?, 1, 'h1', 'doc1', 'duplicate', ?, ?)",
            ("b.txt", run_id, db.now_iso()),
        )
        conn.execute(
            "INSERT INTO documents (id, representative_path, status, created_at, updated_at) "
            "VALUES ('doc1', 'a.txt', 'done', ?, ?)",
            (db.now_iso(), db.now_iso()),
        )
        conn.execute(
            "INSERT INTO documents (id, representative_path, status, quarantine_reason, "
            "created_at, updated_at) VALUES ('doc2', 'c.pdf', 'quarantined', 'corrupt_file', ?, ?)",
            (db.now_iso(), db.now_iso()),
        )
        conn.execute(
            "INSERT INTO files (path, size_bytes, raw_sha256, document_id, status, "
            "discovered_run_id, created_at) VALUES (?, 1, 'h2', 'doc2', 'scanned', ?, ?)",
            ("c.pdf", run_id, db.now_iso()),
        )
        db.end_run(
            conn, run_id, stop_reason="completed", tokens_in=1, tokens_out=2,
            estimated_cost="0.00",
        )

        rep = report.compute_report(conn)

    assert rep["input_files"] == 3
    assert rep["duplicate_files"] == 1
    assert rep["unique_documents"] == 2
    assert rep["processed_ok"] == 1
    assert rep["quarantined"] == 1
    assert rep["not_started"] == 0
    assert rep["quarantine_by_reason"] == {"corrupt_file": 1}
    assert rep["stop_reason"] == "completed"


def test_check_invariants_raises_on_imbalance():
    bad = {
        "input_files": 5,
        "duplicate_files": 1,
        "unique_documents": 1,
        "processed_ok": 0,
        "quarantined": 0,
        "not_started": 0,
    }
    with pytest.raises(report.ReportImbalanceError):
        report.check_invariants(bad)
