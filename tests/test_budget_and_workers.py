from __future__ import annotations

import pytest

from docextract import db
from docextract.budget import BudgetExhausted, BudgetTracker
from docextract.config import LimitsConfig, RetryConfig, Settings
from docextract.llm.fake import FakeBackend
from docextract.llm_stage import BackendUnavailable, CircuitBreaker, run_llm_stage

OK_JSON = (
    '{"doc_type": "other", "counterparty_name": null, "counterparty_tax_id": null, '
    '"issue_date": null, "due_date": null, "gross_amount": null, "currency": null, '
    '"summary": "ok"}'
)
FAST_RETRY = RetryConfig(max_retries=1, backoff_base_s=0.001, backoff_max_s=0.01)


def _seed_documents(conn, n: int) -> None:
    now = db.now_iso()
    for i in range(n):
        conn.execute(
            "INSERT INTO documents (id, representative_path, status, extracted_text, created_at, updated_at) "
            "VALUES (?, ?, 'pending', ?, ?, ?)",
            (f"doc{i}", f"doc{i}.txt", f"document number {i}", now, now),
        )


@pytest.fixture
def conn_with_run(tmp_path):
    with db.open_db(tmp_path / "t.sqlite") as conn:
        run_id = db.create_run(
            conn, input_path="in", config_hash="h", backend="fake", model_tag="t",
            model_digest="d", workers=1, limit_n=None, budget=None,
        )
        yield conn, run_id


class TestBudgetTracker:
    def test_reserve_within_budget_succeeds(self):
        tracker = BudgetTracker(100)
        assert tracker.try_reserve(50) is True
        assert tracker.try_reserve(50) is True
        assert tracker.try_reserve(1) is False

    def test_unlimited_when_budget_none(self):
        tracker = BudgetTracker(None)
        assert tracker.try_reserve(10**9) is True

    def test_commit_actual_frees_reservation(self):
        tracker = BudgetTracker(100)
        tracker.try_reserve(50)
        tracker.commit_actual(50, 10)
        assert tracker.used == 10
        assert tracker.try_reserve(89) is True  # 10 used + 89 = 99 <= 100


class TestBudgetEnforcement:
    def test_never_exceeds_budget_and_stops_with_documents_pending(self, conn_with_run):
        conn, run_id = conn_with_run
        _seed_documents(conn, 5)
        backend = FakeBackend(responses=OK_JSON, tokens_per_call_in=40, tokens_per_call_out=10)
        # 40+10=50 tokens actually used per call; reservation uses byte-estimate
        # input + max_output(512 default), so budget is tiny relative to a
        # normal call - only the very first document should get processed.
        budget = BudgetTracker(60)
        settings = Settings(retry=FAST_RETRY)

        with pytest.raises(BudgetExhausted):
            run_llm_stage(conn, run_id, settings, backend, workers=1, budget=budget)

        rows = conn.execute("SELECT status FROM documents").fetchall()
        statuses = [r["status"] for r in rows]
        assert statuses.count("done") <= 1
        assert "pending" in statuses  # some documents never started
        assert budget.used <= 60

    def test_zero_budget_stops_before_any_call(self, conn_with_run):
        conn, run_id = conn_with_run
        _seed_documents(conn, 3)
        backend = FakeBackend(responses=OK_JSON)
        budget = BudgetTracker(0)

        with pytest.raises(BudgetExhausted):
            run_llm_stage(conn, run_id, Settings(retry=FAST_RETRY), backend, budget=budget)

        assert len(backend.calls) == 0
        rows = conn.execute("SELECT status FROM documents").fetchall()
        assert all(r["status"] == "pending" for r in rows)


class TestWorkers:
    @pytest.mark.parametrize("workers", [1, 4, 16])
    def test_result_set_independent_of_worker_count(self, tmp_path, workers):
        with db.open_db(tmp_path / f"t_{workers}.sqlite") as conn:
            run_id = db.create_run(
                conn, input_path="in", config_hash="h", backend="fake", model_tag="t",
                model_digest="d", workers=workers, limit_n=None, budget=None,
            )
            _seed_documents(conn, 20)
            backend = FakeBackend(responses=OK_JSON)
            run_llm_stage(conn, run_id, Settings(), backend, workers=workers)

            rows = conn.execute("SELECT id, status, summary FROM documents").fetchall()
            result_set = {(r["id"], r["status"], r["summary"]) for r in rows}
            expected_set = {(f"doc{i}", "done", "ok") for i in range(20)}
            assert result_set == expected_set

    def test_workers_do_not_duplicate_llm_calls(self, tmp_path):
        with db.open_db(tmp_path / "t.sqlite") as conn:
            run_id = db.create_run(
                conn, input_path="in", config_hash="h", backend="fake", model_tag="t",
                model_digest="d", workers=8, limit_n=None, budget=None,
            )
            _seed_documents(conn, 20)
            backend = FakeBackend(responses=OK_JSON)
            run_llm_stage(conn, run_id, Settings(), backend, workers=8)
            assert len(backend.calls) == 20  # exactly one call per document, no races


class TestCircuitBreaker:
    def test_trips_after_threshold_consecutive_failures(self):
        breaker = CircuitBreaker(failure_threshold=3)
        assert breaker.record_failure() is False
        assert breaker.record_failure() is False
        assert breaker.record_failure() is True

    def test_success_resets_counter(self):
        breaker = CircuitBreaker(failure_threshold=2)
        assert breaker.record_failure() is False
        breaker.record_success()
        assert breaker.record_failure() is False

    def test_persistent_backend_failure_stops_run_quickly(self, conn_with_run):
        conn, run_id = conn_with_run
        _seed_documents(conn, 10)
        backend = FakeBackend(responses=iter([ConnectionError("down")] * 50))
        settings = Settings(
            retry=RetryConfig(max_retries=1, backoff_base_s=0.001, backoff_max_s=0.01, circuit_breaker_failures=2)
        )
        with pytest.raises(BackendUnavailable):
            run_llm_stage(conn, run_id, settings, backend, workers=4)
        # circuit should trip well before all 10 documents got a full retry budget
        assert len(backend.calls) < 10 * 2

        rows = conn.execute("SELECT status FROM documents").fetchall()
        assert all(r["status"] == "pending" for r in rows)  # no document lost or wrongly quarantined
