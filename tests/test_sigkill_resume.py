"""Requirement 4: kill -9 the process mid-run, resume with the same
parameters, and the final record set must equal an uninterrupted reference
run - with no repeated LLM calls for documents already completed.

Uses a real subprocess (not in-process) so this exercises the actual
SIGKILL/SQLite-WAL recovery path, not just the Python-level resume logic
already covered by tests/test_llm_stage.py and tests/test_scan_stage.py.
"""

from __future__ import annotations

import json
import os
import random
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _make_input(input_dir: Path, n: int) -> None:
    input_dir.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (input_dir / f"doc_{i:02d}.txt").write_text(
            f"Dokument numer {i}. Faktura testowa, kwota {i * 10}.00 zl."
        )


def _make_config(path: Path, sleep_s: float) -> None:
    path.write_text(
        f"""
[backend]
kind = "fake"
[backend.fake]
sleep_s = {sleep_s}
[pricing]
input_per_million = 0.0
output_per_million = 0.0
[retry]
max_retries = 1
backoff_base_s = 0.01
backoff_max_s = 0.05
"""
    )


def _run(db_path: Path, input_dir: Path, config_path: Path) -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable, "-m", "docextract.cli", "run",
            "--input", str(input_dir), "--db", str(db_path),
            "--config", str(config_path),
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _document_records(db_path: Path) -> set[tuple]:
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, status, doc_type, summary FROM documents ORDER BY id"
        ).fetchall()
        return set(rows)
    finally:
        conn.close()


def _llm_call_counts(db_path: Path) -> dict[str, int]:
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT document_id, COUNT(*) FROM llm_calls WHERE status = 'ok' GROUP BY document_id"
        ).fetchall()
        return dict(rows)
    finally:
        conn.close()


def test_sigkill_mid_run_then_resume_matches_uninterrupted_run(tmp_path):
    input_dir = tmp_path / "input"
    _make_input(input_dir, n=12)
    config_path = tmp_path / "fake.toml"
    _make_config(config_path, sleep_s=0.25)

    # Reference: uninterrupted run.
    ref_db = tmp_path / "ref.sqlite"
    proc = _run(ref_db, input_dir, config_path)
    proc.wait(timeout=60)
    assert proc.returncode == 0
    reference_records = _document_records(ref_db)
    assert all(status == "done" for _id, status, _dt, _s in reference_records)

    # Interrupted run: kill -9 partway through, then resume until it finishes.
    kill_db = tmp_path / "kill.sqlite"
    random.seed(1234)
    for _ in range(3):
        proc = _run(kill_db, input_dir, config_path)
        delay = random.uniform(0.4, 1.5)
        time.sleep(delay)
        if proc.poll() is None:
            os.kill(proc.pid, signal.SIGKILL)
            proc.wait(timeout=10)
            break
        # process already finished before we could kill it - fine, just retry
        # with a shorter delay next time isn't necessary since we break below
        # if the run actually completed on its own.
        if proc.returncode == 0:
            break

    calls_before_final_resume = _llm_call_counts(kill_db)

    # Resume to completion (possibly already done above).
    for _ in range(5):
        proc = _run(kill_db, input_dir, config_path)
        proc.wait(timeout=60)
        if proc.returncode == 0:
            records = _document_records(kill_db)
            if all(status == "done" for _id, status, _dt, _s in records):
                break

    final_records = _document_records(kill_db)
    assert final_records == reference_records

    final_calls = _llm_call_counts(kill_db)
    # No document that already had a successful call before the last resume
    # got a second successful call afterwards (no repeated model calls).
    for doc_id, count_before in calls_before_final_resume.items():
        assert final_calls[doc_id] == count_before
