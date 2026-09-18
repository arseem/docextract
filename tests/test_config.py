from __future__ import annotations

import pytest
from pydantic import ValidationError

from docextract.config import DEFAULT_CONFIG_PATH, Settings, load_config


def test_default_config_loads_and_validates():
    config = load_config(DEFAULT_CONFIG_PATH)
    assert config.backend.kind in ("ollama", "openai_compat", "fake")


def test_config_rejects_unknown_keys():
    with pytest.raises(ValidationError):
        Settings.model_validate({"backend": {"kind": "fake"}, "bogus_section": {}})


def test_config_rejects_unknown_backend_kind():
    with pytest.raises(ValidationError):
        Settings.model_validate({"backend": {"kind": "openai"}})


def test_config_hash_is_stable_and_sensitive_to_changes():
    a = Settings()
    b = Settings()
    assert a.config_hash() == b.config_hash()

    c = Settings(backend={"kind": "fake"})
    assert a.config_hash() != c.config_hash()
