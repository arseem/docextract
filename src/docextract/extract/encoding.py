"""Byte -> text decoding for single-byte/UTF encodings.

We deliberately restrict charset-normalizer's candidate list instead of
letting it search every known codec: on our Polish cp1250 test file it
otherwise "confidently" mis-detects cp1252 (both map the same byte range,
just to different letters) and silently produces mojibake
("Us\xb3ugi" instead of "Usługi") rather than an error. Restricting to
the encodings we actually expect (see CLAUDE.md "Dane") fixes it - see
docs/DECISIONS.md. Trade-off: a document in some other single-byte
encoding outside this list may be mis-decoded instead of rejected.
"""

from __future__ import annotations

from charset_normalizer import from_bytes

from .base import EmptyTextError

CANDIDATE_ENCODINGS = ["utf-8", "cp1250", "iso-8859-2"]


def decode_bytes(raw: bytes) -> str:
    if not raw:
        raise EmptyTextError()
    result = from_bytes(raw, cp_isolation=CANDIDATE_ENCODINGS).best()
    if result is None:
        return raw.decode("utf-8", errors="replace")
    return str(result)
