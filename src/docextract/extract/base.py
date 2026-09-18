"""Exceptions extractors raise, mapped 1:1 to quarantine reasons."""

from __future__ import annotations


class ExtractError(Exception):
    reason: str = "corrupt_file"


class UnsupportedFormatError(ExtractError):
    reason = "unsupported_format"


class CorruptFileError(ExtractError):
    reason = "corrupt_file"


class EncryptedFileError(ExtractError):
    reason = "encrypted"


class EmptyTextError(ExtractError):
    reason = "empty_text"
