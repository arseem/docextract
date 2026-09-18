"""EML extraction: headers + body + attachment text, all as one document
(attachments are not separate input_files - see CLAUDE.md "Deduplikacja")."""

from __future__ import annotations

from email import policy
from email.parser import BytesParser
from pathlib import Path

from .base import EmptyTextError, ExtractError
from .docx import extract_docx_bytes
from .html import extract_html_bytes
from .pdf import extract_pdf_bytes
from .txt import extract_txt_bytes

ATTACHMENT_EXTRACTORS = {
    ".pdf": extract_pdf_bytes,
    ".docx": extract_docx_bytes,
    ".html": extract_html_bytes,
    ".htm": extract_html_bytes,
    ".txt": extract_txt_bytes,
}


def _extract_attachment(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    extractor = ATTACHMENT_EXTRACTORS.get(ext)
    if extractor is None:
        raise ExtractError()
    return extractor(data)


def extract_eml_bytes(raw: bytes) -> str:
    if not raw:
        raise EmptyTextError()
    msg = BytesParser(policy=policy.default).parsebytes(raw)

    lines = [
        f"From: {msg.get('From', '')}",
        f"To: {msg.get('To', '')}",
        f"Subject: {msg.get('Subject', '')}",
        f"Date: {msg.get('Date', '')}",
        "",
    ]

    body_part = msg.get_body(preferencelist=("plain", "html"))
    if body_part is not None:
        content = body_part.get_content()
        if body_part.get_content_type() == "text/html":
            content = extract_html_bytes(content.encode("utf-8"))
        lines.append(content)

    for att in msg.iter_attachments():
        filename = att.get_filename() or "attachment"
        try:
            data = att.get_content()
            if isinstance(data, str):
                data = data.encode("utf-8")
            att_text = _extract_attachment(filename, data)
            lines.append(f"\n[Zalacznik: {filename}]\n{att_text}")
        except ExtractError:
            lines.append(f"\n[Zalacznik: {filename} - nie udalo sie odczytac]")

    text = "\n".join(lines)
    if not text.strip():
        raise EmptyTextError()
    return text


def extract_eml(path: Path) -> str:
    return extract_eml_bytes(path.read_bytes())
