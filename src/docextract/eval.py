"""Compares the DB against expected.jsonl and reports per-field accuracy.

Matching: expected rows are matched to actual documents by intersecting
`files` (expected) with the files table's `document_id` mapping - not by
guessing document identity any other way. Also reports dedup-quality
(whether the expected file group and the actual document's file group
agree exactly) and missing/extra documents, so a dedup mismatch is visible
even when every individual field would otherwise look "correct".
"""

from __future__ import annotations

import difflib
import json
import re
import sqlite3
import unicodedata
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .postprocess import normalize_tax_id
from .prompt import detect_language

FIELDS = (
    "doc_type", "counterparty_name", "counterparty_tax_id",
    "issue_date", "due_date", "gross_amount", "currency", "summary",
)

_LEGAL_FORMS = [
    "sp. z o.o.", "spolka z ograniczona odpowiedzialnoscia", "s.a.",
    "ltd.", "ltd", "inc.", "inc", "gmbh", "s.c.", "sp.j.",
]
NAME_SIMILARITY_THRESHOLD = 0.8


def _strip_diacritics(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _normalize_name(name: str | None) -> str:
    if not name:
        return ""
    s = _strip_diacritics(name.strip().strip("\"'")).casefold()
    for form in _LEGAL_FORMS:
        s = s.replace(form, "")
    s = re.sub(r"[^\w\s]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _names_match(expected: str | None, actual: str | None) -> bool:
    a, b = _normalize_name(expected), _normalize_name(actual)
    if not a and not b:
        return True
    if not a or not b:
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= NAME_SIMILARITY_THRESHOLD


def _tax_ids_match(expected: str | None, actual: str | None) -> bool:
    return normalize_tax_id(expected) == normalize_tax_id(actual) if (expected or actual) else True


def _amounts_match(expected: str | None, actual: str | None) -> bool:
    if expected is None and actual is None:
        return True
    if expected is None or actual is None:
        return False
    try:
        return abs(Decimal(expected) - Decimal(actual)) <= Decimal("0.01")
    except InvalidOperation:
        return False


def _exact_match(expected, actual) -> bool:
    return expected == actual


def _summary_ok(expected: str | None, actual: str | None) -> bool:
    if not actual or not actual.strip():
        return False
    if not expected:
        return True
    return detect_language(actual) == detect_language(expected)


_FIELD_MATCHERS = {
    "doc_type": _exact_match,
    "counterparty_name": _names_match,
    "counterparty_tax_id": _tax_ids_match,
    "issue_date": _exact_match,
    "due_date": _exact_match,
    "gross_amount": _amounts_match,
    "currency": _exact_match,
    "summary": _summary_ok,
}


def _load_expected(expected_path: str) -> list[dict]:
    path = Path(expected_path)
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def run_eval(conn: sqlite3.Connection, expected_path: str) -> dict:
    expected_rows = _load_expected(expected_path)

    file_rows = conn.execute("SELECT path, document_id FROM files").fetchall()
    path_to_docid = {r["path"]: r["document_id"] for r in file_rows}
    docid_to_paths: dict[str, set[str]] = {}
    for r in file_rows:
        docid_to_paths.setdefault(r["document_id"], set()).add(r["path"])

    doc_rows = conn.execute("SELECT * FROM documents").fetchall()
    docid_to_doc = {r["id"]: r for r in doc_rows}

    unmatched_doc_ids = set(docid_to_doc.keys())
    missing_documents: list[list[str]] = []
    dedup_correct = 0
    dedup_incorrect = 0
    field_correct = {f: 0 for f in FIELDS}
    field_total = {f: 0 for f in FIELDS}

    for erow in expected_rows:
        expected_files = set(erow["files"])
        candidate_doc_ids = [path_to_docid[f] for f in expected_files if f in path_to_docid]
        if not candidate_doc_ids:
            missing_documents.append(sorted(expected_files))
            continue

        doc_id = Counter(candidate_doc_ids).most_common(1)[0][0]
        unmatched_doc_ids.discard(doc_id)
        actual_files = docid_to_paths.get(doc_id, set())
        if actual_files == expected_files:
            dedup_correct += 1
        else:
            dedup_incorrect += 1

        actual_doc = docid_to_doc.get(doc_id)
        for field in FIELDS:
            field_total[field] += 1
            expected_value = erow.get(field)
            actual_value = actual_doc[field] if actual_doc else None
            if _FIELD_MATCHERS[field](expected_value, actual_value):
                field_correct[field] += 1

    extra_documents = [
        {"id": doc_id, "representative_path": docid_to_doc[doc_id]["representative_path"]}
        for doc_id in sorted(unmatched_doc_ids)
    ]

    field_accuracy = {
        f: (field_correct[f] / field_total[f] if field_total[f] else None) for f in FIELDS
    }

    return {
        "expected_documents": len(expected_rows),
        "matched_documents": len(expected_rows) - len(missing_documents),
        "missing_documents": len(missing_documents),
        "missing_documents_files": missing_documents,
        "extra_documents": len(extra_documents),
        "extra_documents_detail": extra_documents,
        "dedup_groups_correct": dedup_correct,
        "dedup_groups_incorrect": dedup_incorrect,
        "field_accuracy": field_accuracy,
    }
