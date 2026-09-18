#!/usr/bin/env python3
"""Generates data/dupes.zip: a few thousand files, mostly duplicates of a
small set of base documents, used to test dedup performance and correctness
at scale. Not committed to git (see .gitignore).

Usage: uv run python scripts/make_dupes.py [--count N]
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "dupes.zip"

BASE_TEXTS = [
    (
        "Faktura VAT nr DUP/{n:04d}\n"
        "Sprzedawca: Hurtownia Testowa Sp. z o.o.\n"
        "NIP: 526-301-82-76\n"
        "Data wystawienia: 2024-02-01\n"
        "Termin płatności: 2024-02-15\n"
        "Razem do zapłaty: 500,00 zł\n"
    ),
    (
        "Umowa ramowa nr DUP-U/{n:04d}\n"
        "Strony: Partner Testowy Sp. z o.o.\n"
        "Data zawarcia: 2024-03-01\n"
        "Umowa na czas nieokreślony.\n"
    ),
    (
        "Wiadomość: przypomnienie {n:04d}\n"
        "Prosimy o potwierdzenie odbioru przesyłki numer {n:04d}.\n"
    ),
]

ENCODINGS = ["utf-8", "cp1250", "iso-8859-2"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=3000)
    parser.add_argument("--unique-groups", type=int, default=6)
    args = parser.parse_args()

    OUT.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for i in range(args.count):
            group = i % args.unique_groups
            base_template = BASE_TEXTS[group % len(BASE_TEXTS)]
            # A fixed n per group -> identical text within a group (real
            # dedup target); every ~50th file gets a distinct n, so a few
            # unique documents are salted in among the duplicates.
            n = group if (i % 50 != 0) else i
            text = base_template.format(n=n)
            encoding = ENCODINGS[i % len(ENCODINGS)]
            name = f"batch_{i // 500:03d}/dup_{i:05d}.txt"
            zf.writestr(name, text.encode(encoding))

    size_mb = OUT.stat().st_size / (1024 * 1024)
    print(f"Wrote {args.count} files ({size_mb:.1f} MB compressed) to {OUT}")
    print("Remember: this archive must stay out of git (see .gitignore).")


if __name__ == "__main__":
    main()
