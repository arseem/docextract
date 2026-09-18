"""Ollama backend (native macOS/Metal, no API key). Uses /api/chat with a
JSON-schema `format` (structured outputs) and explicit num_ctx/num_predict/
temperature/seed - Ollama silently truncates the prompt if num_ctx is left
at its (small) default, so it is always set explicitly here from config.

A fresh httpx.Client is opened per call rather than one shared across
worker threads - see docs/DECISIONS.md ("timeout nie odpala się pod dużym
--workers"): a client shared across many concurrent threads was observed
to make configured read timeouts fire tens of minutes late instead of at
the configured 90s under --workers 16, which a fresh-client-per-call setup
does not reproduce.
"""

from __future__ import annotations

import httpx

from ..config import OllamaConfig
from ..prompt import SYSTEM_PROMPT
from ..schema import ExtractedFields
from .base import LLMError, LLMResponse, LLMTimeoutError, LLMUnavailableError


class OllamaBackend:
    def __init__(self, config: OllamaConfig, client: httpx.Client | None = None) -> None:
        self.config = config
        self._injected_client = client  # tests inject a respx-mocked client

    def _make_client(self) -> httpx.Client:
        if self._injected_client is not None:
            return self._injected_client
        return httpx.Client(
            base_url=self.config.base_url,
            timeout=httpx.Timeout(self.config.request_timeout_s, connect=self.config.connect_timeout_s),
        )

    def _close_if_owned(self, client: httpx.Client) -> None:
        if self._injected_client is None:
            client.close()

    def model_identity(self) -> tuple[str, str]:
        return self.config.model_tag, self.config.model_digest

    def verify_model_available(self) -> None:
        client = self._make_client()
        try:
            try:
                resp = client.get("/api/tags")
                resp.raise_for_status()
            except httpx.HTTPError as e:
                raise LLMUnavailableError(
                    f"cannot reach Ollama at {self.config.base_url}: {e}"
                ) from e
        finally:
            self._close_if_owned(client)
        data = resp.json()
        digests = {m["name"]: m.get("digest", "") for m in data.get("models", [])}
        if self.config.model_tag not in digests:
            raise LLMError(
                f"model {self.config.model_tag!r} not found in Ollama "
                f"(available: {sorted(digests)}). Run: ollama pull {self.config.model_tag}"
            )
        actual = digests[self.config.model_tag].split(":")[-1]
        expected = self.config.model_digest.split(":")[-1]
        if actual != expected:
            raise LLMError(
                f"model {self.config.model_tag!r} digest mismatch: "
                f"config expects {expected}, Ollama has {actual}. "
                "Pin the actual digest in config/default.toml (from `ollama list` / GET /api/tags)."
            )

    def generate(self, prompt: str, *, max_tokens: int) -> LLMResponse:
        payload = {
            "model": self.config.model_tag,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "format": ExtractedFields.model_json_schema(),
            "options": {
                "num_ctx": self.config.num_ctx,
                "num_predict": min(max_tokens, self.config.num_predict),
                "temperature": self.config.temperature,
                "seed": self.config.seed,
            },
            "stream": False,
        }
        client = self._make_client()
        try:
            try:
                resp = client.post("/api/chat", json=payload)
                resp.raise_for_status()
            except httpx.TimeoutException as e:
                raise LLMTimeoutError(str(e)) from e
            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500:
                    raise LLMUnavailableError(str(e)) from e
                raise LLMError(str(e)) from e
            except httpx.HTTPError as e:
                raise LLMUnavailableError(str(e)) from e
        finally:
            self._close_if_owned(client)

        data = resp.json()
        content = data.get("message", {}).get("content", "")
        return LLMResponse(
            text=content,
            tokens_in=int(data.get("prompt_eval_count", 0) or 0),
            tokens_out=int(data.get("eval_count", 0) or 0),
        )
