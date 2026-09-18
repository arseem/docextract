from __future__ import annotations

import pytest

from docextract.extract.base import (
    CorruptFileError,
    EmptyTextError,
    EncryptedFileError,
    ExtractError,
    UnsupportedFormatError,
)
from docextract.extract.dispatch import extract_text
from docextract.extract.docx import extract_docx_bytes
from docextract.extract.encoding import decode_bytes
from docextract.extract.eml import extract_eml_bytes
from docextract.extract.html import extract_html_bytes
from docextract.extract.pdf import extract_pdf_bytes
from docextract.extract.txt import extract_txt_bytes

LARGE_THRESHOLD = 50 * 1024 * 1024


def test_txt_extracts_polish_text():
    text = extract_txt_bytes("Usługi księgowe, zapłata: 100 zł".encode("utf-8"))
    assert "Usługi" in text


def test_txt_empty_raises():
    with pytest.raises(EmptyTextError):
        extract_txt_bytes(b"")
    with pytest.raises(EmptyTextError):
        extract_txt_bytes(b"   \n\t  ")


def test_html_strips_markup_and_ignores_declared_charset():
    # declares utf-8 but is actually iso-8859-2 - decode must go by content
    raw = "<html><head><meta charset=\"utf-8\"></head><body><p>Zapłata: 100 zł</p></body></html>".encode(
        "iso-8859-2"
    )
    text = extract_html_bytes(raw)
    assert "Zapłata" in text
    assert "<p>" not in text


def test_docx_bad_zip_raises_corrupt():
    with pytest.raises(CorruptFileError):
        extract_docx_bytes(b"not a docx at all")


def test_pdf_password_protected_raises_encrypted():
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.cell(0, 10, "secret content")
    pdf.set_encryption(owner_password="owner-pw", user_password="user-pw")
    raw = bytes(pdf.output())

    with pytest.raises(EncryptedFileError):
        extract_pdf_bytes(raw)


def test_pdf_garbage_raises_corrupt():
    with pytest.raises(CorruptFileError):
        extract_pdf_bytes(b"definitely not a pdf")


def test_eml_body_and_headers_present():
    raw = (
        b"From: a@example.com\r\nTo: b@example.com\r\nSubject: Test\r\n"
        b"Date: Mon, 01 Jan 2024 00:00:00 +0000\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\nHello world\r\n"
    )
    text = extract_eml_bytes(raw)
    assert "Subject: Test" in text
    assert "Hello world" in text


def test_dispatch_unsupported_extension(tmp_path):
    p = tmp_path / "file.xyz"
    p.write_bytes(b"whatever")
    with pytest.raises(UnsupportedFormatError):
        extract_text(p, large_threshold_bytes=LARGE_THRESHOLD)


def test_decode_bytes_prefers_cp1250_over_cp1252_for_polish_text(tmp_path):
    raw = "Usługi, złoty, część".encode("cp1250")
    text = decode_bytes(raw)
    assert text == "Usługi, złoty, część"


def test_large_txt_file_uses_head_tail_streaming(tmp_path):
    path = tmp_path / "big.txt"
    head_marker = "HEAD_MARKER "
    tail_marker = " TAIL_MARKER"
    filler = "x" * 1000
    with path.open("w", encoding="utf-8") as f:
        f.write(head_marker)
        for _ in range(2000):
            f.write(filler)
        f.write(tail_marker)
    text = extract_text(path, large_threshold_bytes=10_000)
    assert "HEAD_MARKER" in text
    assert "TAIL_MARKER" in text
    assert len(text) < path.stat().st_size


def test_extract_error_reason_attrs():
    assert UnsupportedFormatError().reason == "unsupported_format"
    assert CorruptFileError().reason == "corrupt_file"
    assert EncryptedFileError().reason == "encrypted"
    assert EmptyTextError().reason == "empty_text"
    assert issubclass(EmptyTextError, ExtractError)
