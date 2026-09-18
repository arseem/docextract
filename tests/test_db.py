from __future__ import annotations

from docextract import db


def test_init_db_creates_expected_tables(tmp_path):
    with db.open_db(tmp_path / "test.sqlite") as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert {"runs", "files", "documents", "llm_calls"} <= tables


def test_wal_mode_enabled(tmp_path):
    with db.open_db(tmp_path / "test.sqlite") as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_create_and_end_run_roundtrip(tmp_path):
    with db.open_db(tmp_path / "test.sqlite") as conn:
        run_id = db.create_run(
            conn,
            input_path="data/sample",
            config_hash="abc",
            backend="fake",
            model_tag="fake-v1",
            model_digest="fake",
            workers=4,
            limit_n=None,
            budget=None,
        )
        assert db.latest_unfinished_run(conn)["id"] == run_id

        db.end_run(
            conn,
            run_id,
            stop_reason="completed",
            tokens_in=10,
            tokens_out=5,
            estimated_cost="0.00",
        )
        assert db.latest_unfinished_run(conn) is None

        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        assert row["stop_reason"] == "completed"
        assert row["tokens_in"] == 10
