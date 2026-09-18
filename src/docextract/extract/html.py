from __future__ import annotations

from pathlib import Path

from selectolax.parser import HTMLParser

from .base import EmptyTextError
from .encoding import decode_bytes


def extract_html_bytes(raw: bytes) -> str:
    """We ignore any declared <meta charset> and detect the encoding from
    the raw bytes instead - a document can (and in our test data does)
    declare one charset while actually being written in another."""
    if not raw:
        raise EmptyTextError()
    html_text = decode_bytes(raw)
    tree = HTMLParser(html_text)
    text = tree.text(separator="\n", deep=True) or ""
    if not text.strip():
        raise EmptyTextError()
    return text


def extract_html(path: Path) -> str:
    return extract_html_bytes(path.read_bytes())
