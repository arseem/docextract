from __future__ import annotations

import pytest

from docextract.postprocess import (
    ground_date,
    ground_digits,
    normalize_amount,
    normalize_currency,
    normalize_date,
    normalize_tax_id,
    postprocess,
)
from docextract.schema import ExtractedFields


class TestNormalizeTaxId:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("PL 123-456-32-18", "1234563218"),
            ("123 456 32 18", "1234563218"),
            ("1234563218", "1234563218"),
            ("PL1234563218", "1234563218"),
        ],
    )
    def test_domestic_valid_checksum_normalizes(self, raw, expected):
        assert normalize_tax_id(raw) == expected

    def test_domestic_invalid_checksum_rejected(self):
        assert normalize_tax_id("1234567890") is None  # bad checksum

    def test_foreign_vat_keeps_prefix_strips_separators(self):
        assert normalize_tax_id("DE 123-456-789") == "DE123456789"
        assert normalize_tax_id("GB123456789") == "GB123456789"

    def test_none_and_garbage(self):
        assert normalize_tax_id(None) is None
        assert normalize_tax_id("") is None
        assert normalize_tax_id("not a nip") is None


class TestNormalizeAmount:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("1 234,56", "1234.56"),
            ("1.234,56", "1234.56"),
            ("1,234.56", "1234.56"),
            ("1234.56", "1234.56"),
            ("1234.56 zl", "1234.56"),
            ("2450,75", "2450.75"),
            ("150", "150.00"),
            ("12 300,50", "12300.50"),
            ("$8,750.00", "8750.00"),
        ],
    )
    def test_formats(self, raw, expected):
        assert normalize_amount(raw) == expected

    def test_none_and_empty(self):
        assert normalize_amount(None) is None
        assert normalize_amount("") is None
        assert normalize_amount("not a number") is None


class TestNormalizeDate:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2024-03-15", "2024-03-15"),
            ("15.03.2024", "2024-03-15"),
            ("15/03/2024", "2024-03-15"),
            ("15 marca 2024", "2024-03-15"),
            ("March 15, 2024", "2024-03-15"),
            ("March 15 2024", "2024-03-15"),
        ],
    )
    def test_formats(self, raw, expected):
        assert normalize_date(raw) == expected

    def test_invalid_date_rejected(self):
        assert normalize_date("32.13.2024") is None
        assert normalize_date("not a date") is None
        assert normalize_date(None) is None


class TestNormalizeCurrency:
    @pytest.mark.parametrize(
        "raw,expected",
        [("zł", "PLN"), ("zl", "PLN"), ("PLN", "PLN"), ("€", "EUR"), ("EUR", "EUR"), ("$", "USD"), ("USD", "USD")],
    )
    def test_known(self, raw, expected):
        assert normalize_currency(raw) == expected

    def test_unknown_three_letter_code_passthrough(self):
        assert normalize_currency("CHF") == "CHF"

    def test_none(self):
        assert normalize_currency(None) is None


class TestGrounding:
    def test_ground_digits_true_and_false(self):
        text = "NIP: 526-301-82-76, kwota 12 300,50 zl"
        assert ground_digits("5263018276", text) is True
        assert ground_digits("9999999999", text) is False

    @pytest.mark.parametrize(
        "text",
        [
            "Termin platnosci: 19.03.2024",
            "Data: 2024-03-19",
            "termin: 19 marca 2024",
            "Due date: March 19, 2024",
        ],
    )
    def test_ground_date_true_across_formats(self, text):
        assert ground_date("2024-03-19", text) is True

    def test_ground_date_false_when_absent(self):
        assert ground_date("2024-03-19", "brak jakiejkolwiek daty tutaj") is False


class TestPostprocessIntegration:
    def test_grounding_drops_hallucinated_amount(self):
        text = "Faktura od TechNova, NIP 526-301-82-76, termin 19.03.2024"
        fields = ExtractedFields(
            doc_type="invoice",
            counterparty_name="TechNova",
            counterparty_tax_id="526-301-82-76",
            issue_date=None,
            due_date="19.03.2024",
            gross_amount="999999.99",  # not present in text -> must be dropped
            currency="PLN",
            summary="Faktura od TechNova.",
        )
        result = postprocess(fields, text)
        assert result["gross_amount"] is None
        assert result["counterparty_tax_id"] == "5263018276"
        assert result["due_date"] == "2024-03-19"

    def test_full_document_roundtrip(self):
        text = (
            "FAKTURA VAT nr FV/2024/03/017\n"
            "Sprzedawca: TechNova Sp. z o.o.\n"
            "NIP: 526-301-82-76\n"
            "Data wystawienia: 05.03.2024\n"
            "Termin platnosci: 19.03.2024\n"
            "Razem do zaplaty: 12 300,50 zl\n"
        )
        fields = ExtractedFields(
            doc_type="invoice",
            counterparty_name="TechNova Sp. z o.o.",
            counterparty_tax_id="526-301-82-76",
            issue_date="05.03.2024",
            due_date="19.03.2024",
            gross_amount="12 300,50",
            currency="zl",
            summary="Faktura za uslugi od TechNova.",
        )
        result = postprocess(fields, text)
        assert result == {
            "doc_type": "invoice",
            "counterparty_name": "TechNova Sp. z o.o.",
            "counterparty_tax_id": "5263018276",
            "issue_date": "2024-03-05",
            "due_date": "2024-03-19",
            "gross_amount": "12300.50",
            "currency": "PLN",
            "summary": "Faktura za uslugi od TechNova.",
        }
