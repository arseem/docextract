"""Token budget enforcement with upfront reservation.

Before every LLM call we reserve an upper bound on input tokens (conservative
byte-based estimate - see config.limits.bytes_per_token_estimate) plus
max_output_tokens. If used + in-flight-reservations + this reservation would
exceed --budget, we never send the request: the run stops with
stop_reason=budget_exhausted and the document stays pending. A timeout
commits the full reservation as used (we don't know how much the server
actually processed); a normal response commits the real counters instead.
"""

from __future__ import annotations

import threading


class BudgetExhausted(Exception):
    pass


class BudgetTracker:
    def __init__(self, budget: int | None) -> None:
        self.budget = budget
        self.used = 0
        self._reserved = 0
        self._lock = threading.Lock()

    def try_reserve(self, amount: int) -> bool:
        if self.budget is None:
            return True
        with self._lock:
            if self.used + self._reserved + amount > self.budget:
                return False
            self._reserved += amount
            return True

    def commit_actual(self, reserved_amount: int, actual_amount: int) -> None:
        with self._lock:
            self._reserved -= reserved_amount
            self.used += actual_amount

    def commit_reserved_as_used(self, reserved_amount: int) -> None:
        """Timeout path: we don't know how much the server actually consumed,
        so the whole reservation counts as spent (never under-count)."""
        with self._lock:
            self._reserved -= reserved_amount
            self.used += reserved_amount

    def estimate_input_tokens(self, prompt: str, bytes_per_token: float) -> int:
        byte_len = len(prompt.encode("utf-8"))
        return max(1, int(byte_len / max(bytes_per_token, 0.1)) + 1)
