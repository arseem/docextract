from __future__ import annotations

import pytest

from docextract.config import Settings
from docextract.config import BackendConfig, FakeBackendConfig


@pytest.fixture
def fake_config() -> Settings:
    return Settings(backend=BackendConfig(kind="fake", fake=FakeBackendConfig()))
