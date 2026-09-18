from __future__ import annotations

from pathlib import Path

from .base import UnsupportedFormatError
from .docx import extract_docx
from .eml import extract_eml
from .html import extract_html
from .pdf import extract_pdf
from .txt import extract_txt

_SIMPLE = {
    ".pdf": extract_pdf,
    ".docx": extract_docx,
    ".html": extract_html,
    ".htm": extract_html,
    ".eml": extract_eml,
}


def extract_text(path: Path, *, large_threshold_bytes: int) -> str:
    ext = path.suffix.lower()
    if ext == ".txt":
        return extract_txt(path, large_threshold_bytes=large_threshold_bytes)
    fn = _SIMPLE.get(ext)
    if fn is None:
        raise UnsupportedFormatError()
    return fn(path)
