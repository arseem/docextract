from __future__ import annotations

from docextract.normalize import fingerprint_of_text, normalize_text


def test_normalize_collapses_whitespace_and_case():
    a = normalize_text("Hello   World\n\n")
    b = normalize_text("hello world")
    assert a == b


def test_normalize_nfkc_folds_compatibility_forms():
    # full-width "A" (U+FF21) is NFKC-equivalent to ascii "A"
    assert normalize_text("Ａ") == normalize_text("A").casefold()


def test_fingerprint_stable_across_whitespace_variants():
    fp1 = fingerprint_of_text("Dziękujemy za współpracę.")
    fp2 = fingerprint_of_text("  Dziękujemy   za\n\nwspółpracę.  ")
    assert fp1 == fp2


def test_fingerprint_differs_for_different_content():
    fp1 = fingerprint_of_text("Kwota: 100 zł")
    fp2 = fingerprint_of_text("Kwota: 200 zł")
    assert fp1 != fp2
