#!/usr/bin/env python3
"""Generates one multi-hundred-MB text file into data/sample/.

Not committed to git (see .gitignore) - too large. Exercises streaming
hashing/extraction (requirement 9): the tool must never load this file
fully into memory. Written in a streaming fashion itself, so generation
uses constant memory regardless of target size.

Real invoice fields sit at the very end, after a large amount of filler
text, mirroring "content can be anywhere, including deep in a huge file".

Usage: uv run python scripts/make_big.py [--size-mb N]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _gen_common import group_nip, make_valid_nip  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = ROOT / "data" / "sample"
OUT = SAMPLE_DIR / "big_export.txt"
EXPECTED_PATH = SAMPLE_DIR / "expected.jsonl"
RELPATH = "big_export.txt"
BIG_NIP = make_valid_nip("112233445")

EXPECTED_ROW = {
    "doc_type": "invoice",
    "counterparty_name": "Archiwum Danych Testowych Sp. z o.o.",
    "counterparty_tax_id": BIG_NIP,
    "issue_date": "2024-01-15",
    "due_date": "2024-01-29",
    "gross_amount": "999.99",
    "currency": "PLN",
    "summary": "Bardzo duzy plik eksportu logow zakonczony podsumowaniem faktury testowej.",
    "files": [RELPATH],
}


def upsert_expected_row() -> None:
    rows = []
    if EXPECTED_PATH.exists():
        rows = [json.loads(line) for line in EXPECTED_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [r for r in rows if RELPATH not in r.get("files", [])]
    rows.append(EXPECTED_ROW)
    with EXPECTED_PATH.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

FILLER = (
    "Log eksportu archiwum dokumentow - wpis systemowy. Ten wiersz jest "
    "powtarzany wielokrotnie w celu wygenerowania pliku o duzym rozmiarze, "
    "tak aby przetestowac strumieniowe hashowanie i odczyt bez wczytywania "
    "calego pliku do pamieci. Linia zawiera przykladowy tekst wypelniajacy.\n"
)

TAIL = (
    "\n----- KONIEC LOGU: PODSUMOWANIE DOKUMENTU -----\n"
    "FAKTURA VAT nr BIG/2024/0001\n"
    "Sprzedawca: Archiwum Danych Testowych Sp. z o.o.\n"
    f"NIP: {group_nip(BIG_NIP)}\n"
    "Data wystawienia: 2024-01-15\n"
    "Termin platnosci: 2024-01-29\n"
    "Razem do zaplaty: 999,99 zl\n"
    "Waluta: PLN\n"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--size-mb", type=int, default=300)
    args = parser.parse_args()

    target_bytes = args.size_mb * 1024 * 1024
    OUT.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    chunk = FILLER * 1000
    chunk_bytes = chunk.encode("utf-8")
    with OUT.open("wb") as f:
        while written < target_bytes - len(TAIL.encode("utf-8")):
            f.write(chunk_bytes)
            written += len(chunk_bytes)
        f.write(TAIL.encode("utf-8"))
        written += len(TAIL.encode("utf-8"))

    upsert_expected_row()

    print(f"Wrote {written / (1024 * 1024):.1f} MB to {OUT}")
    print(f"Updated {EXPECTED_PATH} with the expected row for {RELPATH}")
    print("Remember: this file must stay out of git (see .gitignore).")


if __name__ == "__main__":
    main()
