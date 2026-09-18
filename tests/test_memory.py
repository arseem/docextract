"""Requirement 9: peak RSS of the whole process tree at --workers 4 stays
under 2GB regardless of a single input file's size. Marked `slow` (creates
a real multi-hundred-MB file and is not part of the default `make test`
run) - CLAUDE.md's own memory-test description says as much.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

pytestmark = pytest.mark.slow

REPO_ROOT = Path(__file__).resolve().parents[1]
BIG_FILE_MB = 300
MEMORY_LIMIT_MB = 2048


def _write_big_file(path: Path, target_mb: int) -> None:
    chunk = ("Log eksportu - wiersz wypelniajacy plik testowy pamieci. " * 20 + "\n").encode("utf-8")
    target_bytes = target_mb * 1024 * 1024
    written = 0
    with path.open("wb") as f:
        while written < target_bytes:
            f.write(chunk)
            written += len(chunk)


def _peak_tree_rss_mb(proc: subprocess.Popen) -> float:
    p = psutil.Process(proc.pid)
    peak = 0
    while proc.poll() is None:
        try:
            rss = p.memory_info().rss
            for child in p.children(recursive=True):
                try:
                    rss += child.memory_info().rss
                except psutil.NoSuchProcess:
                    pass
        except psutil.NoSuchProcess:
            break
        peak = max(peak, rss)
        time.sleep(0.05)
    return peak / (1024 * 1024)


def test_peak_memory_under_2gb_with_workers_4_and_a_huge_file(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_big_file(input_dir / "big.txt", BIG_FILE_MB)
    for i in range(8):
        (input_dir / f"small_{i}.txt").write_text(f"Maly dokument numer {i}.")

    config_path = tmp_path / "fake.toml"
    config_path.write_text(
        '[backend]\nkind = "fake"\n[pricing]\ninput_per_million = 0.0\n'
        "output_per_million = 0.0\n"
    )
    db_path = tmp_path / "out.sqlite"

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "docextract.cli", "run",
            "--input", str(input_dir), "--db", str(db_path),
            "--workers", "4", "--config", str(config_path),
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    peak_mb = _peak_tree_rss_mb(proc)
    proc.wait(timeout=180)

    assert proc.returncode == 0
    assert peak_mb < MEMORY_LIMIT_MB, f"peak RSS {peak_mb:.0f} MB exceeds {MEMORY_LIMIT_MB} MB"
