"""Picks a bounded excerpt of a document's text for the prompt: head, tail,
and windows around keywords likely to sit next to the fields we want (NIP,
amounts, dates) - relevant content can be anywhere, including deep inside a
300-page PDF. Deterministic: fixed keyword order, no randomness.
"""

from __future__ import annotations

DEFAULT_KEYWORDS = [
    "nip", "vat", "brutto", "netto", "razem", "do zapłaty", "do zaplaty",
    "termin płatności", "termin platnosci", "total", "amount due", "due date",
    "iban", "wartość", "wartosc", "kwota", "suma", "waluta", "currency",
]

WINDOW_RADIUS = 150
OMITTED_MARKER = "\n[...]\n"


def select_text(full_text: str, *, max_chars: int, keywords: list[str] | None = None) -> str:
    if len(full_text) <= max_chars:
        return full_text

    keywords = keywords or DEFAULT_KEYWORDS
    head_budget = max_chars // 3
    tail_budget = max_chars // 3
    window_budget = max_chars - head_budget - tail_budget

    head = full_text[:head_budget]
    tail = full_text[-tail_budget:] if tail_budget else ""

    lower = full_text.casefold()
    spans: list[tuple[int, int]] = []
    used = 0
    for kw in keywords:
        kw_l = kw.casefold()
        search_from = 0
        while used < window_budget:
            idx = lower.find(kw_l, search_from)
            if idx == -1:
                break
            search_from = idx + len(kw)
            start = max(0, idx - WINDOW_RADIUS)
            end = min(len(full_text), idx + len(kw) + WINDOW_RADIUS)
            if any(s <= start < e or s < end <= e for s, e in spans):
                continue
            spans.append((start, end))
            used += end - start

    spans.sort()
    merged: list[tuple[int, int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    windows_text = OMITTED_MARKER.join(full_text[s:e] for s, e in merged)
    return f"{head}{OMITTED_MARKER}{windows_text}{OMITTED_MARKER}{tail}"
