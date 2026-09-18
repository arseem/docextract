from __future__ import annotations

from docextract.prompt import DOC_END, DOC_START, build_prompt, detect_language
from docextract.select import select_text


def test_select_text_returns_full_text_when_under_budget():
    text = "short document"
    assert select_text(text, max_chars=1000) == text


def test_select_text_keeps_head_tail_and_keyword_windows():
    filler = "x" * 5000
    text = f"HEAD_MARKER {filler} NIP: 526-301-82-76 {filler} TAIL_MARKER"
    result = select_text(text, max_chars=500)
    assert "HEAD_MARKER" in result
    assert "TAIL_MARKER" in result
    assert "526-301-82-76" in result
    assert len(result) < len(text)


def test_select_text_deterministic():
    text = "NIP 111 " + "y" * 3000 + " VAT 222 " + "z" * 3000 + " total 333"
    assert select_text(text, max_chars=400) == select_text(text, max_chars=400)


def test_detect_language_polish_diacritics():
    assert detect_language("Faktura za usługi, kwota do zapłaty") == "pl"


def test_detect_language_polish_stopwords_without_diacritics():
    assert detect_language("Faktura nr 1 dnia termin oraz kwota") == "pl"


def test_detect_language_english():
    assert detect_language("Invoice number one, total amount due next month") == "en"


def test_build_prompt_wraps_text_in_delimiters():
    prompt = build_prompt(
        selected_text="some document text",
        language_hint="pl",
        self_names=[], self_tax_ids=[],
    )
    assert DOC_START in prompt
    assert DOC_END in prompt
    start = prompt.index(DOC_START)
    end = prompt.index(DOC_END)
    assert "some document text" in prompt[start:end]


def test_build_prompt_includes_self_entity_instruction():
    prompt = build_prompt(
        selected_text="text",
        language_hint="pl",
        self_names=["Acme Sp. z o.o."],
        self_tax_ids=["1234567802"],
    )
    assert "Acme Sp. z o.o." in prompt
    assert "1234567802" in prompt
    assert "DRUGIEJ strony" in prompt
