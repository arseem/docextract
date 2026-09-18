from __future__ import annotations

import zipfile

import pytest

from docextract.scan import ZipSafetyError, scan_files


def test_scan_directory_deterministic_order_and_skips_metadata(tmp_path):
    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "expected.jsonl").write_text("{}")
    (tmp_path / ".DS_Store").write_bytes(b"junk")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.txt").write_text("c")

    with scan_files(tmp_path) as files:
        relpaths = [f.relpath for f in files]

    assert relpaths == ["a.txt", "b.txt", "sub/c.txt"]


def test_scan_computes_streaming_sha256(tmp_path):
    import hashlib

    content = b"hello world" * 100
    (tmp_path / "f.txt").write_bytes(content)
    with scan_files(tmp_path) as files:
        assert len(files) == 1
        assert files[0].raw_sha256 == hashlib.sha256(content).hexdigest()
        assert files[0].size_bytes == len(content)


def test_scan_zip_archive(tmp_path):
    zpath = tmp_path / "archive.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("docs/one.txt", "one")
        zf.writestr("docs/two.txt", "two")

    with scan_files(zpath) as files:
        relpaths = sorted(f.relpath for f in files)
        assert relpaths == ["docs/one.txt", "docs/two.txt"]


def test_scan_zip_rejects_path_traversal(tmp_path):
    zpath = tmp_path / "evil.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("../../etc/evil.txt", "pwned")

    with pytest.raises(ZipSafetyError):
        with scan_files(zpath):
            pass


def test_scan_zip_rejects_absolute_path(tmp_path):
    zpath = tmp_path / "evil_abs.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("/etc/evil.txt", "pwned")

    with pytest.raises(ZipSafetyError):
        with scan_files(zpath):
            pass


def test_scan_zip_rejects_oversized_uncompressed_content(tmp_path):
    zpath = tmp_path / "bomb.zip"
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("big.txt", b"\x00" * (5 * 1024 * 1024))

    with pytest.raises(ZipSafetyError):
        with scan_files(zpath, max_zip_uncompressed_mb=1):
            pass


def test_scan_zip_within_limit_succeeds(tmp_path):
    zpath = tmp_path / "ok.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("small.txt", b"x" * 100)

    with scan_files(zpath, max_zip_uncompressed_mb=1) as files:
        assert len(files) == 1
