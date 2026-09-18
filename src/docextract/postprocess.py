"""Deterministic normalization + grounding of model output.

Grounding: NIP/amount/date values the model returns must be findable in the
document's own text (in *some* written form) or they are dropped to null.
counterparty_name is free text and is not grounding-checked (CLAUDE.md's
grounding requirement is scoped to NIP/kwota/data).
"""

from __future__ import annotations

import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .schema import ExtractedFields

NIP_WEIGHTS = [6, 5, 7, 2, 3, 4, 5, 6, 7]

PL_MONTHS = {
    "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4, "maja": 5, "czerwca": 6,
    "lipca": 7, "sierpnia": 8, "wrzesnia": 9, "pazdziernika": 10, "listopada": 11,
    "grudnia": 12,
}
EN_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}
_MONTH_TO_PL = {v: k for k, v in PL_MONTHS.items()}
_MONTH_TO_EN = {v: k.capitalize() for k, v in EN_MONTHS.items()}

CURRENCY_MAP = {
    "zl": "PLN", "zloty": "PLN", "zlotych": "PLN", "pln": "PLN",
    "eur": "EUR", "euro": "EUR",
    "usd": "USD", "dolar": "USD", "dolary": "USD",
    "gbp": "GBP", "funt": "GBP",
}
_CURRENCY_SYMBOLS = {"zł": "PLN", "€": "EUR", "$": "USD", "£": "GBP"}


def _strip_diacritics(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _nip_checksum_valid(nip: str) -> bool:
    s = sum(w * int(c) for w, c in zip(NIP_WEIGHTS, nip))
    return s % 11 == int(nip[9])


def normalize_tax_id(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = re.sub(r"[\s\-.]", "", raw.strip())
    m = re.match(r"^([A-Za-z]{2})?(\d+)$", cleaned)
    if not m:
        return None
    prefix, digits = m.groups()
    if prefix and prefix.upper() != "PL":
        return f"{prefix.upper()}{digits}"
    if len(digits) != 10 or not _nip_checksum_valid(digits):
        return None
    return digits


def normalize_amount(raw: str | None) -> str | None:
    if not raw:
        return None
    s = re.sub(r"[^\d,.\s-]", "", raw.strip()).strip()
    if not s:
        return None
    negative = s.startswith("-")
    s = s.lstrip("-")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        s = s.replace(",", ".") if len(parts) == 2 and len(parts[1]) <= 2 else s.replace(",", "")
    s = s.replace(" ", "")
    if negative:
        s = "-" + s
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    return str(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def normalize_currency(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip()
    if s in _CURRENCY_SYMBOLS:
        return _CURRENCY_SYMBOLS[s]
    key = _strip_diacritics(s).lower()
    if key in CURRENCY_MAP:
        return CURRENCY_MAP[key]
    if re.fullmatch(r"[A-Za-z]{3}", s):
        return s.upper()
    return None


def normalize_date(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip()

    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if m:
        return _safe_iso(int(m[1]), int(m[2]), int(m[3]))

    m = re.match(r"^(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})$", s)
    if m:
        return _safe_iso(int(m[3]), int(m[2]), int(m[1]))

    m = re.match(r"^(\d{1,2})\s+([A-Za-ząćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)\s+(\d{4})$", s)
    if m:
        month = PL_MONTHS.get(_strip_diacritics(m[2]).lower())
        if month:
            return _safe_iso(int(m[3]), month, int(m[1]))

    m = re.match(r"^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$", s)
    if m:
        month = EN_MONTHS.get(m[1].lower())
        if month:
            return _safe_iso(int(m[3]), month, int(m[2]))

    return None


def _safe_iso(year: int, month: int, day: int) -> str | None:
    from datetime import date

    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _digits_only(text: str) -> str:
    return re.sub(r"\D", "", text)


def ground_digits(value_digits: str, document_text: str) -> bool:
    if not value_digits:
        return False
    return value_digits in _digits_only(document_text)


def ground_date(iso_date: str, document_text: str) -> bool:
    year, month, day = (int(p) for p in iso_date.split("-"))
    candidates = [
        f"{day:02d}.{month:02d}.{year}",
        f"{day:02d}-{month:02d}-{year}",
        f"{day:02d}/{month:02d}/{year}",
        f"{year}-{month:02d}-{day:02d}",
    ]
    lower_text = _strip_diacritics(document_text).casefold()
    if _MONTH_TO_PL.get(month):
        candidates.append(f"{day} {_MONTH_TO_PL[month]} {year}")
    if _MONTH_TO_EN.get(month):
        candidates.append(f"{_MONTH_TO_EN[month]} {day}, {year}")
        candidates.append(f"{_MONTH_TO_EN[month]} {day} {year}")
    return any(_strip_diacritics(c).casefold() in lower_text for c in candidates)


def postprocess(fields: ExtractedFields, document_text: str) -> dict:
    tax_id = normalize_tax_id(fields.counterparty_tax_id)
    if tax_id and not ground_digits(_digits_only(tax_id), document_text):
        tax_id = None

    issue_date = normalize_date(fields.issue_date)
    if issue_date and not ground_date(issue_date, document_text):
        issue_date = None

    due_date = normalize_date(fields.due_date)
    if due_date and not ground_date(due_date, document_text):
        due_date = None

    amount = normalize_amount(fields.gross_amount)
    if amount and not ground_digits(_digits_only(amount), document_text):
        amount = None

    name = (fields.counterparty_name or "").strip() or None

    return {
        "doc_type": fields.doc_type,
        "counterparty_name": name,
        "counterparty_tax_id": tax_id,
        "issue_date": issue_date,
        "due_date": due_date,
        "gross_amount": amount,
        "currency": normalize_currency(fields.currency),
        "summary": fields.summary.strip(),
    }
