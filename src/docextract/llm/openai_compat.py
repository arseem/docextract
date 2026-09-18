"""OpenAI-compatible backend (llama.cpp llama-server, LM Studio, mlx-lm
server). Uses /chat/completions with response_format=json_schema. No
digest endpoint is standardized across these servers, so model identity
verification only checks the configured model id is what the server
reports serving, and otherwise trusts the pinned (tag, digest) from config
(e.g. HF repo + revision + GGUF sha256, per README instructions).

A fresh httpx.Client is opened per call rather than one shared across
worker threads - see llm/ollama.py's docstring and docs/DECISIONS.md.
"""

from __future__ import annotations

import httpx

from ..config import OpenAICompatConfig
from ..prompt import SYSTEM_PROMPT
from ..schema import ExtractedFields
from .base import LLMError, LLMResponse, LLMTimeoutError, LLMUnavailableError


class OpenAICompatBackend:
    def __init__(self, config: OpenAICompatConfig, client: httpx.Client | None = None) -> None:
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
                resp = client.get("/models")
                resp.raise_for_status()
            except httpx.HTTPError as e:
                raise LLMUnavailableError(
                    f"cannot reach OpenAI-compatible server at {self.config.base_url}: {e}"
                ) from e
        finally:
            self._close_if_owned(client)
        data = resp.json()
        ids = {m.get("id") for m in data.get("data", [])}
        if ids and self.config.model_tag not in ids:
            raise LLMError(
                f"model {self.config.model_tag!r} not reported by server (available: {sorted(ids)})"
            )

    def generate(self, prompt: str, *, max_tokens: int) -> LLMResponse:
        payload = {
            "model": self.config.model_tag,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "extracted_fields",
                    "schema": ExtractedFields.model_json_schema(),
                    "strict": True,
                },
            },
            "temperature": self.config.temperature,
            "seed": self.config.seed,
            "max_tokens": min(max_tokens, self.config.max_tokens),
        }
        client = self._make_client()
        try:
            try:
                resp = client.post("/chat/completions", json=payload)
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
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return LLMResponse(
            text=content,
            tokens_in=int(usage.get("prompt_tokens", 0) or 0),
            tokens_out=int(usage.get("completion_tokens", 0) or 0),
        )
