from __future__ import annotations

from pathlib import Path

from docextract import cli
from docextract.progress import log

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample"


def test_log_writes_to_stderr_not_stdout(capsys):
    log("[test] hello")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "[test] hello" in captured.err


def test_run_prints_progress_markers_to_stderr(tmp_path, capsys):
    config_path = tmp_path / "fake.toml"
    config_path.write_text(
        '[backend]\nkind = "fake"\n[pricing]\ninput_per_million = 0.0\n'
        "output_per_million = 0.0\n"
    )
    db_path = tmp_path / "out.sqlite"

    rc = cli.main(
        ["run", "--input", str(SAMPLE_DIR), "--db", str(db_path), "--config", str(config_path)]
    )
    assert rc == 0

    captured = capsys.readouterr()
    assert captured.out == ""  # run prints nothing to stdout, only progress to stderr
    err = captured.err
    assert "[run] input=" in err
    assert "[scan] scanning" in err
    assert "[scan] done: 32 unique documents" in err
    assert "[llm] processing 26 documents" in err
    assert "[llm] [26/26]" in err  # last document logged
    assert "[run] finished: stop_reason=completed" in err
