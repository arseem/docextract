"""Configuration loading and validation (TOML -> pydantic)."""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OllamaConfig(StrictModel):
    base_url: str = "http://localhost:11434"
    model_tag: str = "TODO"
    model_digest: str = "TODO"
    num_ctx: int = 8192
    num_predict: int = 512
    temperature: float = 0.0
    seed: int = 42
    connect_timeout_s: float = 5.0
    request_timeout_s: float = 90.0


class OpenAICompatConfig(StrictModel):
    base_url: str = "http://localhost:8080/v1"
    model_tag: str = "TODO"
    model_digest: str = "TODO"
    max_tokens: int = 512
    temperature: float = 0.0
    seed: int = 42
    connect_timeout_s: float = 5.0
    request_timeout_s: float = 90.0


class FakeBackendConfig(StrictModel):
    model_tag: str = "fake-v1"
    model_digest: str = "fake"


class BackendConfig(StrictModel):
    kind: Literal["ollama", "openai_compat", "fake"] = "ollama"
    ollama: OllamaConfig = OllamaConfig()
    openai_compat: OpenAICompatConfig = OpenAICompatConfig()
    fake: FakeBackendConfig = FakeBackendConfig()


class PricingConfig(StrictModel):
    input_per_million: float = 0.0
    output_per_million: float = 0.0


class LimitsConfig(StrictModel):
    large_file_threshold_mb: float = 50
    max_zip_uncompressed_mb: float = 2048
    extract_timeout_s: float = 30
    max_prompt_input_tokens: int = 6000
    bytes_per_token_estimate: float = 3.0


class RetryConfig(StrictModel):
    max_retries: int = 2
    backoff_base_s: float = 1.0
    backoff_max_s: float = 20.0
    circuit_breaker_failures: int = 5
    circuit_breaker_reset_s: float = 30.0


class SelfEntitiesConfig(StrictModel):
    names: list[str] = []
    tax_ids: list[str] = []


class Settings(StrictModel):
    backend: BackendConfig = BackendConfig()
    pricing: PricingConfig = PricingConfig()
    limits: LimitsConfig = LimitsConfig()
    retry: RetryConfig = RetryConfig()
    self_entities: SelfEntitiesConfig = SelfEntitiesConfig()

    def active_model_identity(self) -> tuple[str, str]:
        """Return (tag, digest) for the currently selected backend."""
        if self.backend.kind == "ollama":
            return self.backend.ollama.model_tag, self.backend.ollama.model_digest
        if self.backend.kind == "openai_compat":
            return (
                self.backend.openai_compat.model_tag,
                self.backend.openai_compat.model_digest,
            )
        return self.backend.fake.model_tag, self.backend.fake.model_digest

    def config_hash(self) -> str:
        """Stable hash of the fully-resolved config, used to detect drift across resumes."""
        canonical = self.model_dump_json(by_alias=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_config(path: str | Path) -> Settings:
    path = Path(path)
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return Settings.model_validate(raw)


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "default.toml"
