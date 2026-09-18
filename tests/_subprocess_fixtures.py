"""Top-level (picklable) worker functions for testing
extract.timeout.run_in_subprocess_with_timeout under the spawn context."""

from __future__ import annotations

import os
import time


def hang_forever(conn) -> None:
    time.sleep(60)
    conn.send({"ok": True, "text": "should never get here"})


def crash_hard(conn) -> None:
    os._exit(1)  # noqa: SLF001 - deliberately simulate a segfault-like hard crash


def succeed_fast(text: str, conn) -> None:
    conn.send({"ok": True, "text": text})
