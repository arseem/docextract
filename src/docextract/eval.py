"""Compare DB results against expected.jsonl. Implemented in milestone 6."""

from __future__ import annotations

import sqlite3


def run_eval(conn: sqlite3.Connection, expected_path: str) -> dict:
    raise NotImplementedError("eval will be implemented in milestone 6")
