"""Common interface every LLM backend implements."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class LLMError(Exception):
    """Backend call failed (network, timeout, non-2xx, ...)."""


class LLMTimeoutError(LLMError):
    pass


class LLMUnavailableError(LLMError):
    """Backend is down / connection refused / repeated failures (circuit open)."""


@dataclass(frozen=True)
class LLMResponse:
    text: str
    tokens_in: int
    tokens_out: int


class LLMBackend(Protocol):
    """Structured-output text generation. No tools, no document identity."""

    def generate(self, prompt: str, *, max_tokens: int) -> LLMResponse: ...

    def model_identity(self) -> tuple[str, str]:
        """Return (tag, digest) pinned for this backend."""
        ...

    def verify_model_available(self) -> None:
        """Raise LLMError with a clear message if the pinned digest isn't the
        one actually loaded/available on the backend. Called once at startup."""
        ...
