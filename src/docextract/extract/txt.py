from __future__ import annotations

from pathlib import Path

from .base import EmptyTextError
from .encoding import decode_bytes

HEAD_BYTES = 200_000
TAIL_BYTES = 200_000
OMITTED_MARKER = "\n[...pominieto srodkowa czesc duzego pliku...]\n"


def extract_txt_bytes(raw: bytes) -> str:
    text = decode_bytes(raw)
    if not text.strip():
        raise EmptyTextError()
    return text


def extract_txt(path: Path, *, large_threshold_bytes: int) -> str:
    """Files above `large_threshold_bytes` are read as head+tail only, so a
    multi-hundred-MB .txt never gets loaded into memory in full (requirement
    9). The omitted middle means a value located only there is lost - an
    accepted, documented limitation for oversized plain-text files."""
    size = path.stat().st_size
    if size == 0:
        raise EmptyTextError()
    if size <= large_threshold_bytes:
        return extract_txt_bytes(path.read_bytes())

    with path.open("rb") as f:
        head = f.read(HEAD_BYTES)
        f.seek(max(size - TAIL_BYTES, HEAD_BYTES))
        tail = f.read(TAIL_BYTES)
    head_text = decode_bytes(head)
    tail_text = decode_bytes(tail)
    text = head_text + OMITTED_MARKER + tail_text
    if not text.strip():
        raise EmptyTextError()
    return text
