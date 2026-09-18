"""Live tests against a real running Ollama with the pinned default model.
Skipped by default (requirement 10: make test must pass with no inference
server running) - run explicitly with `-m live`.
"""

from __future__ import annotations

import pytest

from docextract.config import DEFAULT_CONFIG_PATH, load_config
from docextract.llm.factory import build_backend

pytestmark = pytest.mark.live


def test_pinned_model_digest_matches_running_ollama():
    config = load_config(DEFAULT_CONFIG_PATH)
    backend = build_backend(config)
    backend.verify_model_available()  # must not raise


def test_pinned_model_produces_valid_json_for_a_real_document():
    from docextract.prompt import build_prompt
    from docextract.schema import parse_llm_output

    config = load_config(DEFAULT_CONFIG_PATH)
    backend = build_backend(config)
    prompt = build_prompt(
        selected_text=(
            "FAKTURA VAT nr FV/2024/03/017\nSprzedawca: TechNova Sp. z o.o.\n"
            "NIP: 526-301-82-76\nData wystawienia: 05.03.2024\n"
            "Termin platnosci: 19.03.2024\nRazem do zaplaty: 12 300,50 zl"
        ),
        language_hint="pl",
        self_names=config.self_entities.names,
        self_tax_ids=config.self_entities.tax_ids,
    )
    response = backend.generate(prompt, max_tokens=512)
    fields = parse_llm_output(response.text)  # must not raise
    assert fields.doc_type == "invoice"
