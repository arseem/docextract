from __future__ import annotations

import json
from pathlib import Path

from docextract import db
from docextract.config import Settings
from docextract.eval import _amounts_match, _names_match, _tax_ids_match, run_eval
from docextract.llm.fake import FakeBackend
from docextract.llm_stage import run_llm_stage
from docextract.scan_stage import run_scan_stage

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample"


class TestFieldMatchers:
    def test_names_match_ignores_legal_form_and_case(self):
        assert _names_match("TechNova Sp. z o.o.", "TECHNOVA sp. z o.o.") is True

    def test_names_match_both_none(self):
        assert _names_match(None, None) is True

    def test_names_match_one_none(self):
        assert _names_match("Acme", None) is False

    def test_names_match_rejects_very_different_names(self):
        assert _names_match("TechNova Sp. z o.o.", "Completely Different Corp") is False

    def test_tax_ids_match_after_normalization(self):
        assert _tax_ids_match("PL 526-301-82-76", "5263018276") is True

    def test_amounts_match_within_tolerance(self):
        assert _amounts_match("100.00", "100.00") is True
        assert _amounts_match("100.00", "100.005") is True  # within 0.01
        assert _amounts_match("100.00", "100.02") is False  # exceeds 0.01

    def test_amounts_match_both_none(self):
        assert _amounts_match(None, None) is True


class TestRunEvalBasics:
    def test_perfect_match(self, tmp_path):
        expected_path = tmp_path / "expected.jsonl"
        expected_path.write_text(
            json.dumps(
                {
                    "doc_type": "invoice", "counterparty_name": "Acme", "counterparty_tax_id": "5263018276",
                    "issue_date": "2024-01-01", "due_date": "2024-01-15", "gross_amount": "100.00",
                    "currency": "PLN", "summary": "Faktura.", "files": ["a.txt"],
                }
            )
            + "\n"
        )
        with db.open_db(tmp_path / "t.sqlite") as conn:
            now = db.now_iso()
            run_id = db.create_run(
                conn, input_path="in", config_hash="h", backend="fake", model_tag="t",
                model_digest="d", workers=1, limit_n=None, budget=None,
            )
            conn.execute(
                "INSERT INTO files (path, size_bytes, raw_sha256, document_id, status, "
                "discovered_run_id, created_at) VALUES ('a.txt', 1, 'h', 'doc1', 'scanned', ?, ?)",
                (run_id, now),
            )
            conn.execute(
                "INSERT INTO documents (id, representative_path, status, doc_type, "
                "counterparty_name, counterparty_tax_id, issue_date, due_date, gross_amount, "
                "currency, summary, created_at, updated_at) VALUES "
                "('doc1', 'a.txt', 'done', 'invoice', 'Acme', '5263018276', '2024-01-01', "
                "'2024-01-15', '100.00', 'PLN', 'Faktura za cos tam.', ?, ?)",
                (now, now),
            )
            result = run_eval(conn, str(expected_path))
        assert result["missing_documents"] == 0
        assert result["extra_documents"] == 0
        assert result["dedup_groups_correct"] == 1
        for field, acc in result["field_accuracy"].items():
            assert acc == 1.0, field

    def test_missing_and_extra_documents_detected(self, tmp_path):
        expected_path = tmp_path / "expected.jsonl"
        expected_path.write_text(
            json.dumps({"doc_type": "other", "summary": "x", "files": ["nowhere.txt"],
                        "counterparty_name": None, "counterparty_tax_id": None,
                        "issue_date": None, "due_date": None, "gross_amount": None, "currency": None})
            + "\n"
        )
        with db.open_db(tmp_path / "t.sqlite") as conn:
            now = db.now_iso()
            conn.execute(
                "INSERT INTO documents (id, representative_path, status, doc_type, summary, created_at, updated_at) "
                "VALUES ('doc_extra', 'somewhere.txt', 'done', 'other', 'x', ?, ?)",
                (now, now),
            )
            result = run_eval(conn, str(expected_path))
        assert result["missing_documents"] == 1
        assert result["extra_documents"] == 1


def test_eval_against_real_dataset_with_oracle_backend(tmp_path):
    """End-to-end sanity check of the whole extraction pipeline (scan ->
    LLM stage -> postprocess/grounding -> eval) using a FakeBackend that
    answers with the *correct* fields from expected.jsonl for each
    document. If postprocess/grounding had a systematic bug, this would
    fail even though the "model" is perfect - it isolates pipeline bugs
    from model quality, which is what eval on our own data is for."""
    expected_rows = [
        json.loads(line) for line in (SAMPLE_DIR / "expected.jsonl").read_text().splitlines()
    ]
    files_to_row = {f: row for row in expected_rows for f in row["files"]}

    with db.open_db(tmp_path / "t.sqlite") as conn:
        run_id = db.create_run(
            conn, input_path=str(SAMPLE_DIR), config_hash="h", backend="fake",
            model_tag="t", model_digest="d", workers=4, limit_n=None, budget=None,
        )
        run_scan_stage(conn, SAMPLE_DIR, run_id, Settings().limits)

        oracle: dict[str, dict] = {}
        for row in conn.execute("SELECT id, representative_path, extracted_text FROM documents"):
            erow = files_to_row.get(row["representative_path"])
            if erow is not None and row["extracted_text"]:
                oracle[row["extracted_text"][:80]] = erow

        def answer(prompt: str, max_tokens: int) -> str:
            for key, erow in oracle.items():
                if key and key in prompt:
                    payload = {f: erow[f] for f in
                               ("doc_type", "counterparty_name", "counterparty_tax_id",
                                "issue_date", "due_date", "gross_amount", "currency", "summary")}
                    if payload["doc_type"] is None:
                        payload["doc_type"] = "other"  # schema requires a valid enum
                    return json.dumps(payload)
            return '{"doc_type": "other", "counterparty_name": null, "counterparty_tax_id": null, ' \
                   '"issue_date": null, "due_date": null, "gross_amount": null, "currency": null, ' \
                   '"summary": "unmatched"}'

        backend = FakeBackend(responses=answer)
        run_llm_stage(conn, run_id, Settings(), backend, workers=4)

        result = run_eval(conn, str(SAMPLE_DIR / "expected.jsonl"))

    assert result["missing_documents"] == 0
    assert result["extra_documents"] == 0
    assert result["dedup_groups_correct"] == result["expected_documents"]
    # Field accuracy should be very high (not necessarily 1.0: e.g. the
    # self_entities counterparty-resolution instruction isn't exercised by
    # this oracle, and a couple of quarantined docs feed doc_type="other"
    # into a field that expects null in that specific edge case).
    for field, acc in result["field_accuracy"].items():
        assert acc >= 0.8, f"{field}: {acc}"
