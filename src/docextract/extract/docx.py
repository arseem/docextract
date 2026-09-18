from __future__ import annotations

import io
from pathlib import Path

from docx import Document

from .base import CorruptFileError, EmptyTextError


def extract_docx_bytes(raw: bytes) -> str:
    try:
        doc = Document(io.BytesIO(raw))
        paragraphs = [p.text for p in doc.paragraphs]
    except Exception as e:  # noqa: BLE001 - untrusted input, any parse failure -> quarantine
        raise CorruptFileError() from e
    text = "\n".join(paragraphs)
    if not text.strip():
        raise EmptyTextError()
    return text


def extract_docx(path: Path) -> str:
    return extract_docx_bytes(path.read_bytes())
