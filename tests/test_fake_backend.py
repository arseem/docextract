from __future__ import annotations

import pytest

from docextract.llm.base import LLMTimeoutError, LLMUnavailableError
from docextract.llm.fake import DEFAULT_JSON, FakeBackend


def test_fake_backend_returns_default_response_and_logs_call():
    backend = FakeBackend()
    resp = backend.generate("hello", max_tokens=100)
    assert resp.text == DEFAULT_JSON
    assert resp.tokens_in > 0 and resp.tokens_out > 0
    assert len(backend.calls) == 1
    assert backend.calls[0].prompt == "hello"


def test_fake_backend_scripted_sequence():
    backend = FakeBackend(responses=iter(["a", "b", "c"]))
    assert backend.generate("p", max_tokens=1).text == "a"
    assert backend.generate("p", max_tokens=1).text == "b"
    assert backend.generate("p", max_tokens=1).text == "c"
    # exhausted -> repeats last value
    assert backend.generate("p", max_tokens=1).text == "c"


def test_fake_backend_can_raise_timeout_and_unavailable():
    backend = FakeBackend(responses=iter([TimeoutError("slow"), ConnectionError("down")]))
    with pytest.raises(LLMTimeoutError):
        backend.generate("p", max_tokens=1)
    with pytest.raises(LLMUnavailableError):
        backend.generate("p", max_tokens=1)
    assert len(backend.calls) == 2


def test_fake_backend_model_identity():
    backend = FakeBackend(model_tag="t", model_digest="d")
    assert backend.model_identity() == ("t", "d")
