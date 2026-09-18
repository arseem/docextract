"""Directory/zip -> flat list of files with streaming raw sha256.

Zip handling: members are streamed to a temp directory (never fully
buffered in memory), with two checks applied before any bytes are written:
a per-entry path-traversal guard (no zip-slip: reject ".." components and
absolute paths) and a cumulative uncompressed-size cap (no zip bombs -
`limits.max_zip_uncompressed_mb`). The temp directory is removed when the
caller's context exits.
"""

from __future__ import annotations

import hashlib
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

HASH_CHUNK_SIZE = 1024 * 1024

# Sidecar/metadata files that live alongside a document archive but are not
# themselves documents: the eval ground-truth file, and OS/editor litter.
# Excluded by convention (not a document format decision), not because our
# own dataset happens to contain them - a grading archive could too.
_SKIP_NAMES = {"expected.jsonl"}


class ZipSafetyError(Exception):
    pass


@dataclass(frozen=True)
class ScannedFile:
    relpath: str  # posix-style, relative to the input root
    abspath: Path
    size_bytes: int
    raw_sha256: str


def _hash_file(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        while chunk := f.read(HASH_CHUNK_SIZE):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def _safe_member_path(name: str) -> PurePosixPath:
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts:
        raise ZipSafetyError(f"unsafe path in zip entry: {name!r}")
    return p


def _extract_zip_safely(zip_path: Path, dest: Path, max_uncompressed_bytes: int) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        total = 0
        infos = zf.infolist()
        for info in infos:
            if info.is_dir():
                continue
            _safe_member_path(info.filename)
            total += info.file_size
            if total > max_uncompressed_bytes:
                raise ZipSafetyError(
                    f"zip uncompressed size exceeds limit ({max_uncompressed_bytes} bytes)"
                )
        for info in infos:
            if info.is_dir():
                continue
            member_path = _safe_member_path(info.filename)
            out_path = dest / member_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, out_path.open("wb") as dst:
                while chunk := src.read(HASH_CHUNK_SIZE):
                    dst.write(chunk)


@contextmanager
def _resolve_input_root(input_path: Path, max_zip_uncompressed_mb: float) -> Iterator[Path]:
    if input_path.is_dir():
        yield input_path
        return
    if zipfile.is_zipfile(input_path):
        with tempfile.TemporaryDirectory(prefix="docextract_zip_") as tmp:
            _extract_zip_safely(
                input_path, Path(tmp), int(max_zip_uncompressed_mb * 1024 * 1024)
            )
            yield Path(tmp)
        return
    raise ValueError(f"input path is neither a directory nor a zip archive: {input_path}")


@contextmanager
def scan_files(
    input_path: Path, *, max_zip_uncompressed_mb: float = 2048
) -> Iterator[list[ScannedFile]]:
    """Deterministic order (sorted by relative path), so `--limit N` and
    processing order don't depend on filesystem iteration order.

    Context manager because a zip input is extracted to a temp directory
    that must stay alive for as long as callers read file contents (e.g.
    the extraction stage) - it is removed on exit."""
    results: list[ScannedFile] = []
    with _resolve_input_root(input_path, max_zip_uncompressed_mb) as root:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.name.startswith(".") or path.name in _SKIP_NAMES:
                continue
            relpath = path.relative_to(root).as_posix()
            sha256, size = _hash_file(path)
            results.append(
                ScannedFile(relpath=relpath, abspath=path, size_bytes=size, raw_sha256=sha256)
            )
        yield results
