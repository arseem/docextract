from __future__ import annotations

from pathlib import Path

from docextract import db
from docextract.config import LimitsConfig
from docextract.scan_stage import run_scan_stage


def _make_input(tmp_path: Path) -> Path:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.txt").write_text("Hello world, invoice amount 100 zl")
    (input_dir / "a_copy.txt").write_bytes((input_dir / "a.txt").read_bytes())
    (input_dir / "b.txt").write_text("  Hello   world,  invoice amount 100 zl  ")
    (input_dir / "corrupt.pdf").write_bytes(b"not a real pdf")
    (input_dir / "empty.txt").write_bytes(b"")
    return input_dir


def test_scan_stage_populates_files_and_documents_and_balances(tmp_path):
    input_dir = _make_input(tmp_path)
    with db.open_db(tmp_path / "t.sqlite") as conn:
        run_id = db.create_run(
            conn, input_path=str(input_dir), config_hash="h", backend="fake",
            model_tag="t", model_digest="d", workers=1, limit_n=None, budget=None,
        )
        run_scan_stage(conn, input_dir, run_id, LimitsConfig())

        files = conn.execute("SELECT * FROM files").fetchall()
        docs = conn.execute("SELECT * FROM documents").fetchall()

        assert len(files) == 5
        # a.txt, a_copy.txt (byte-identical), b.txt (same normalized text) -> one document
        # corrupt.pdf -> one quarantined document; empty.txt -> one quarantined document
        assert len(docs) == 3

        duplicate_paths = {f["path"] for f in files if f["status"] == "duplicate"}
        assert duplicate_paths == {"a_copy.txt", "b.txt"}

        quarantined = {d["representative_path"]: d["quarantine_reason"] for d in docs if d["status"] == "quarantined"}
        assert quarantined == {"corrupt.pdf": "corrupt_file", "empty.txt": "empty_text"}


def test_scan_stage_is_idempotent_and_preserves_advanced_status(tmp_path):
    input_dir = _make_input(tmp_path)
    with db.open_db(tmp_path / "t.sqlite") as conn:
        run_id = db.create_run(
            conn, input_path=str(input_dir), config_hash="h", backend="fake",
            model_tag="t", model_digest="d", workers=1, limit_n=None, budget=None,
        )
        run_scan_stage(conn, input_dir, run_id, LimitsConfig())

        # simulate the LLM stage having already finished one document
        doc_id = conn.execute(
            "SELECT id FROM documents WHERE status = 'pending' LIMIT 1"
        ).fetchone()["id"]
        conn.execute(
            "UPDATE documents SET status = 'done', doc_type = 'other' WHERE id = ?", (doc_id,)
        )

        # re-run the scan stage (as a resumed invocation would)
        run_scan_stage(conn, input_dir, run_id, LimitsConfig())

        row = conn.execute("SELECT status, doc_type FROM documents WHERE id = ?", (doc_id,)).fetchone()
        assert row["status"] == "done"
        assert row["doc_type"] == "other"

        # counts unchanged, no duplicate rows created
        assert conn.execute("SELECT COUNT(*) c FROM files").fetchone()["c"] == 5
        assert conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"] == 3
