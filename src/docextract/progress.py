"""Minimal progress logging to stderr, so a `run` that takes a minute or
more prints *something* while it works (distinguishes "still going" from
"hung" - CLAUDE.md doesn't require this, but reasoning about a silent
multi-minute subprocess purely by re-querying SQLite is painful, as this
project's own debugging sessions showed). Deliberately not the stdlib
`logging` module - there is nothing else in this project that needs
levels/handlers/formatters, and a flushed print is easier to read live.
"""

from __future__ import annotations

import sys
import threading

_lock = threading.Lock()


def log(msg: str) -> None:
    with _lock:
        print(msg, file=sys.stderr, flush=True)
