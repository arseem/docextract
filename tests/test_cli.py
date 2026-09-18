from __future__ import annotations

import json

import pytest

from docextract import cli


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
