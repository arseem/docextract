from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium

from .base import CorruptFileError, EmptyTextError, EncryptedFileError


def _open(source) -> pdfium.PdfDocument:
    try:
        return pdfium.PdfDocument(source)
    except pdfium.PdfiumError as e:
        if "password" in str(e).lower():
            raise EncryptedFileError() from e
        raise CorruptFileError() from e


def _extract_from_doc(pdf: pdfium.PdfDocument) -> str:
    try:
        texts = []
        for page in pdf:  # page by page - never holds the whole document as one buffer
            textpage = page.get_textpage()
            texts.append(textpage.get_text_range())
        text = "\n".join(texts)
    except pdfium.PdfiumError as e:
        raise CorruptFileError() from e
    finally:
        pdf.close()
    if not text.strip():
        raise EmptyTextError()
    return text


def extract_pdf_bytes(raw: bytes) -> str:
    return _extract_from_doc(_open(raw))


def extract_pdf(path: Path) -> str:
    return _extract_from_doc(_open(str(path)))
