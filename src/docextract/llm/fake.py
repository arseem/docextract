"""Deterministic, in-process backend used by the test suite (no network).

Supports scripting canned responses/failures per call, and always logs every
call it receives so tests can assert that resumed runs do not repeat calls
for documents already completed.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from .base import LLMResponse, LLMTimeoutError, LLMUnavailableError

DEFAULT_JSON = (
    '{"doc_type": "other", "counterparty_name": null, '
    '"counterparty_tax_id": null, "issue_date": null, "due_date": null, '
    '"gross_amount": null, "currency": null, "summary": "Fake summary."}'
)


@dataclass
class FakeCallRecord:
    prompt: str
    max_tokens: int


@dataclass
class FakeBackend:
    """`responses` may be a fixed string, an iterator of strings/Exceptions
    consumed one per call (last value repeats once exhausted), or a callable
    `(prompt, max_tokens) -> str` for fully custom behaviour."""

    responses: str | Iterator[object] | Callable[[str, int], str] = DEFAULT_JSON
    model_tag: str = "fake-v1"
    model_digest: str = "fake"
    tokens_per_call_in: int = 100
    tokens_per_call_out: int = 20
    sleep_s: float = 0.0
    calls: list[FakeCallRecord] = field(default_factory=list)
    _last: object = field(default=None, repr=False)

    def generate(self, prompt: str, *, max_tokens: int) -> LLMResponse:
        if self.sleep_s:
            time.sleep(self.sleep_s)
        self.calls.append(FakeCallRecord(prompt=prompt, max_tokens=max_tokens))

        if callable(self.responses) and not isinstance(self.responses, str):
            text = self.responses(prompt, max_tokens)  # type: ignore[misc]
        elif isinstance(self.responses, str):
            text = self.responses
        else:
            try:
                self._last = next(self.responses)  # type: ignore[arg-type]
            except StopIteration:
                pass
            text = self._last

        if isinstance(text, TimeoutError):
            raise LLMTimeoutError(str(text))
        if isinstance(text, ConnectionError):
            raise LLMUnavailableError(str(text))
        if isinstance(text, Exception):
            raise text
        assert isinstance(text, str)
        return LLMResponse(
            text=text,
            tokens_in=self.tokens_per_call_in,
            tokens_out=self.tokens_per_call_out,
        )

    def model_identity(self) -> tuple[str, str]:
        return self.model_tag, self.model_digest

    def verify_model_available(self) -> None:
        return None
