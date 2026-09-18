"""Runs a single file's extraction in its own subprocess with a hard
timeout. A malformed PDF/DOCX can hang or crash the interpreter that parses
it (CLAUDE.md), so each extraction gets process-level isolation: a timeout
becomes `extract_timeout`, a crashed/killed child becomes `extract_crash`.
"""

from __future__ import annotations

import multiprocessing as mp
import time
from dataclasses import dataclass
from pathlib import Path

from .base import ExtractError
from .dispatch import extract_text


@dataclass(frozen=True)
class ExtractOutcome:
    text: str | None
    reason: str | None  # quarantine reason, set iff text is None


def _worker(path_str: str, large_threshold_bytes: int, conn) -> None:
    try:
        text = extract_text(Path(path_str), large_threshold_bytes=large_threshold_bytes)
        conn.send({"ok": True, "text": text})
    except ExtractError as e:
        conn.send({"ok": False, "reason": e.reason})
    except Exception:  # noqa: BLE001 - untrusted file, must never propagate
        conn.send({"ok": False, "reason": "corrupt_file"})
    finally:
        conn.close()


def extract_with_timeout(path: Path, *, large_threshold_bytes: int, timeout_s: float) -> ExtractOutcome:
    return run_in_subprocess_with_timeout(
        _worker, (str(path), large_threshold_bytes), timeout_s=timeout_s
    )


def run_in_subprocess_with_timeout(target, args: tuple, *, timeout_s: float) -> ExtractOutcome:
    """Generic runner: `target(*args, conn)` must send exactly one
    `{"ok": bool, ...}` dict and then return. Split out from
    `extract_with_timeout` so the timeout/crash mechanics themselves are
    unit-testable with trivial picklable worker functions."""
    ctx = mp.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=target, args=(*args, child_conn), daemon=True)
    proc.start()
    child_conn.close()

    deadline = time.monotonic() + timeout_s
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                proc.terminate()
                proc.join(2)
                if proc.is_alive():
                    proc.kill()
                    proc.join(2)
                return ExtractOutcome(text=None, reason="extract_timeout")

            if parent_conn.poll(min(remaining, 0.5)):
                try:
                    result = parent_conn.recv()
                except EOFError:
                    result = None
                proc.join(5)
                if result is None:
                    return ExtractOutcome(text=None, reason="extract_crash")
                if result["ok"]:
                    return ExtractOutcome(text=result["text"], reason=None)
                return ExtractOutcome(text=None, reason=result["reason"])

            if not proc.is_alive():
                proc.join(1)
                return ExtractOutcome(text=None, reason="extract_crash")
    finally:
        parent_conn.close()
