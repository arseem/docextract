"""Text normalization and document fingerprinting for stage-2 dedup.

Markup is already stripped by the extractors (they return plain text), so
normalization here only has to fold case/whitespace/unicode variants -
NFKC -> casefold -> collapse whitespace.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.casefold()
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def fingerprint_of_text(text: str) -> str:
    normalized = normalize_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
