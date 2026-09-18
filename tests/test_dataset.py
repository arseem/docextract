"""Regression checks on the committed data/sample/ + expected.jsonl.

Guards against the generator script drifting out of sync with its own
output (missing files, broken NIP checksums, invalid JSON).
"""

from __future__ import annotations

import json
from pathlib import Path

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample"
NIP_WEIGHTS = [6, 5, 7, 2, 3, 4, 5, 6, 7]


def _nip_checksum_valid(nip: str) -> bool:
    if len(nip) != 10 or not nip.isdigit():
        return True  # not a domestic-shaped NIP (e.g. foreign VAT) - not our concern here
    s = sum(w * int(c) for w, c in zip(NIP_WEIGHTS, nip))
    return s % 11 == int(nip[9])


def _load_expected() -> list[dict]:
    path = SAMPLE_DIR / "expected.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_expected_jsonl_exists_and_parses():
    rows = _load_expected()
    assert len(rows) >= 25


def test_all_referenced_files_exist_on_disk():
    rows = _load_expected()
    for row in rows:
        assert row["files"], f"document with no files: {row}"
        for relpath in row["files"]:
            assert (SAMPLE_DIR / relpath).is_file(), f"missing file: {relpath}"


def test_no_orphan_files_outside_expected():
    rows = _load_expected()
    referenced = {f for row in rows for f in row["files"]}
    on_disk = {
        str(p.relative_to(SAMPLE_DIR))
        for p in SAMPLE_DIR.rglob("*")
        if p.is_file() and p.name != "expected.jsonl" and p.name != "big_export.txt"
    }
    assert on_disk == referenced


def test_domestic_nip_checksums_are_valid():
    rows = _load_expected()
    for row in rows:
        nip = row["counterparty_tax_id"]
        if nip:
            assert _nip_checksum_valid(nip), f"invalid NIP checksum: {nip} ({row['counterparty_name']})"


def test_corrupted_documents_have_null_doc_type():
    rows = _load_expected()
    corrupt_rows = [r for r in rows if any(f.startswith("corrupt/") for f in r["files"])]
    assert len(corrupt_rows) >= 5
    for row in corrupt_rows:
        assert row["doc_type"] is None


def test_all_five_formats_present():
    rows = _load_expected()
    exts = {Path(f).suffix for row in rows for f in row["files"]}
    assert {".eml", ".pdf", ".docx", ".html", ".txt"} <= exts


def test_dedup_groups_have_multiple_files():
    rows = _load_expected()
    multi_file_docs = [r for r in rows if len(r["files"]) > 1]
    assert len(multi_file_docs) >= 3
