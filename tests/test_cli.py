from __future__ import annotations

import json
from pathlib import Path

import pytest

from docextract import cli

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample"


@pytest.fixture
def fake_config_file(tmp_path):
    path = tmp_path / "fake.toml"
    path.write_text(
        '[backend]\nkind = "fake"\n[pricing]\ninput_per_million = 0.0\n'
        "output_per_million = 0.0\n"
    )
    return path


def test_run_then_report_json_balances(tmp_path, fake_config_file, capsys):
    db_path = tmp_path / "out.sqlite"
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    rc = cli.main(
        [
            "run",
            "--input",
            str(input_dir),
            "--db",
            str(db_path),
            "--config",
            str(fake_config_file),
        ]
    )
    assert rc == 0

    rc = cli.main(["report", "--db", str(db_path), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["input_files"] == out["duplicate_files"] + out["unique_documents"]
    assert out["backend"] == "fake"
    assert out["stop_reason"] == "completed"


def test_run_rejects_zero_workers(tmp_path, fake_config_file, capsys):
    db_path = tmp_path / "out.sqlite"
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    rc = cli.main(
        [
            "run",
            "--input",
            str(input_dir),
            "--db",
            str(db_path),
            "--workers",
            "0",
            "--config",
            str(fake_config_file),
        ]
    )
    assert rc != 0


def test_run_with_low_budget_stops_and_reports_budget_exhausted(tmp_path, capsys):
    config_path = tmp_path / "fake_low_budget.toml"
    config_path.write_text(
        '[backend]\nkind = "fake"\n[pricing]\ninput_per_million = 0.0\n'
        "output_per_million = 0.0\n[retry]\nmax_retries = 1\nbackoff_base_s = 0.001\n"
        "backoff_max_s = 0.01\n"
    )
    db_path = tmp_path / "out.sqlite"
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    for i in range(5):
        (input_dir / f"d{i}.txt").write_text(f"Dokument {i} z jakas tresca.")

    rc = cli.main(
        [
            "run", "--input", str(input_dir), "--db", str(db_path),
            "--config", str(config_path), "--budget", "1",
        ]
    )
    assert rc == 0

    rc = cli.main(["report", "--db", str(db_path), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["stop_reason"] == "budget_exhausted"
    assert out["tokens_in"] + out["tokens_out"] <= 1
    assert out["not_started"] >= 1  # budget of 1 token can't cover any real call


def test_run_on_sample_dataset_matches_expected_counts(tmp_path, fake_config_file, capsys):
    db_path = tmp_path / "out.sqlite"
    rc = cli.main(
        ["run", "--input", str(SAMPLE_DIR), "--db", str(db_path), "--config", str(fake_config_file)]
    )
    assert rc == 0

    rc = cli.main(["report", "--db", str(db_path), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)

    expected_rows = [
        json.loads(line) for line in (SAMPLE_DIR / "expected.jsonl").read_text().splitlines()
    ]
    assert out["unique_documents"] == len(expected_rows)
    expected_quarantined = sum(1 for r in expected_rows if r["doc_type"] is None)
    assert out["quarantined"] == expected_quarantined
    assert out["input_files"] == out["duplicate_files"] + out["unique_documents"]
    assert out["unique_documents"] == out["processed_ok"] + out["quarantined"] + out["not_started"]
