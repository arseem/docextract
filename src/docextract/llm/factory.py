from __future__ import annotations

from ..config import Settings
from .fake import FakeBackend
from .ollama import OllamaBackend
from .openai_compat import OpenAICompatBackend


def build_backend(config: Settings):
    kind = config.backend.kind
    if kind == "ollama":
        return OllamaBackend(config.backend.ollama)
    if kind == "openai_compat":
        return OpenAICompatBackend(config.backend.openai_compat)
    if kind == "fake":
        return FakeBackend(
            model_tag=config.backend.fake.model_tag,
            model_digest=config.backend.fake.model_digest,
        )
    raise ValueError(f"unknown backend kind: {kind!r}")
