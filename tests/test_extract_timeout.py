from __future__ import annotations

from docextract.extract.timeout import run_in_subprocess_with_timeout

from tests._subprocess_fixtures import crash_hard, hang_forever, succeed_fast


def test_hang_becomes_extract_timeout():
    outcome = run_in_subprocess_with_timeout(hang_forever, (), timeout_s=0.3)
    assert outcome.text is None
    assert outcome.reason == "extract_timeout"


def test_hard_crash_becomes_extract_crash():
    outcome = run_in_subprocess_with_timeout(crash_hard, (), timeout_s=5)
    assert outcome.text is None
    assert outcome.reason == "extract_crash"


def test_successful_worker_returns_text():
    outcome = run_in_subprocess_with_timeout(succeed_fast, ("hello",), timeout_s=5)
    assert outcome.text == "hello"
    assert outcome.reason is None
