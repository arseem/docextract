"""Shared helpers for the synthetic dataset generators.

Deterministic on purpose: no wall-clock, no real randomness (the one RNG use
is seeded). Re-running any generator script reproduces byte-identical output.
"""

from __future__ import annotations

import io
from email import charset as email_charset
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from docx import Document
from fpdf import FPDF
from fpdf.enums import XPos, YPos

ROOT = Path(__file__).resolve().parents[1]
FONT_DIR = ROOT / "data" / "fonts"
FONT_REGULAR = FONT_DIR / "DejaVuSans.ttf"
FONT_BOLD = FONT_DIR / "DejaVuSans-Bold.ttf"

NIP_WEIGHTS = [6, 5, 7, 2, 3, 4, 5, 6, 7]


def nip_checksum(first9: str) -> int:
    return sum(w * int(c) for w, c in zip(NIP_WEIGHTS, first9)) % 11


def make_valid_nip(base9: str) -> str:
    """Nudge the last digit of `base9` until the NIP-10 checksum is valid
    (checksum == 10 has no representable check digit and must be skipped)."""
    digits = list(base9)
    for _ in range(20):
        c = nip_checksum("".join(digits))
        if c != 10:
            return "".join(digits) + str(c)
        digits[-1] = str((int(digits[-1]) + 1) % 10)
    raise RuntimeError(f"could not derive a valid NIP from {base9!r}")


def group_nip(nip10: str) -> str:
    """3-3-2-2 grouping, e.g. 5263018276 -> 526-301-82-76."""
    return f"{nip10[0:3]}-{nip10[3:6]}-{nip10[6:8]}-{nip10[8:10]}"


def write_txt(out_dir: Path, relpath: str, text: str, encoding: str = "utf-8") -> Path:
    path = out_dir / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode(encoding))
    return path


def write_html(
    out_dir: Path,
    relpath: str,
    title: str,
    body_paragraphs: list[str],
    encoding: str = "utf-8",
    declared_charset: str | None = None,
) -> Path:
    declared = declared_charset or encoding
    body_html = "".join(f"<p>{p}</p>\n" for p in body_paragraphs)
    html = (
        "<!DOCTYPE html>\n<html><head>"
        f'<meta charset="{declared}">'
        f"<title>{title}</title></head>\n"
        f"<body>\n{body_html}</body></html>\n"
    )
    path = out_dir / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(html.encode(encoding))
    return path


def write_docx(out_dir: Path, relpath: str, paragraphs: list[str]) -> Path:
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    path = out_dir / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path


def docx_bytes(paragraphs: list[str]) -> bytes:
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _build_pdf(paragraphs: list[str]) -> FPDF:
    pdf = FPDF()
    pdf.add_font("DejaVu", "", str(FONT_REGULAR))
    pdf.add_font("DejaVu", "B", str(FONT_BOLD))
    pdf.set_font("DejaVu", size=11)
    pdf.add_page()
    for p in paragraphs:
        if p == "\f":
            pdf.add_page()
            continue
        pdf.multi_cell(0, 6, p, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    return pdf


def write_pdf(out_dir: Path, relpath: str, paragraphs: list[str]) -> Path:
    pdf = _build_pdf(paragraphs)
    path = out_dir / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))
    return path


def pdf_bytes(paragraphs: list[str]) -> bytes:
    pdf = _build_pdf(paragraphs)
    return bytes(pdf.output())


def write_encrypted_pdf(out_dir: Path, relpath: str, paragraphs: list[str], password: str) -> Path:
    pdf = _build_pdf(paragraphs)
    pdf.set_encryption(owner_password=password + "-owner", user_password=password)
    path = out_dir / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))
    return path


def write_eml(
    out_dir: Path,
    relpath: str,
    *,
    from_: str,
    to: str,
    subject: str,
    date_str: str,
    body: str,
    encoding: str = "utf-8",
    body_encoding: int | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> Path:
    """`body_encoding`: email.charset.QP or email.charset.BASE64, or None for
    the library's default (7bit/QP as applicable for the given charset)."""
    if body_encoding is not None:
        cs = email_charset.Charset(encoding)
        cs.body_encoding = body_encoding
        text_part = MIMEText(body, _charset=cs)
    else:
        text_part = MIMEText(body, _charset=encoding)

    if attachments:
        msg = MIMEMultipart()
        msg.attach(text_part)
        for filename, data, subtype in attachments:
            part = MIMEApplication(data, _subtype=subtype)
            part.add_header("Content-Disposition", "attachment", filename=filename)
            msg.attach(part)
    else:
        msg = text_part

    msg["From"] = from_
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = date_str

    path = out_dir / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(msg.as_bytes())
    return path


QP = email_charset.QP
BASE64 = email_charset.BASE64
