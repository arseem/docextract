"""Regression test for a real bug found during manual --workers 16
verification: a single httpx.Client shared across many worker threads made
the configured read timeout fire tens of minutes late instead of at the
configured value (5 requests observed to hang ~32 minutes against a
configured 90s timeout). Fixed by opening a fresh httpx.Client per call
(see llm/ollama.py, llm/openai_compat.py) instead of one shared client.

Uses a Unix domain socket (not a TCP port) so this stays within
--allow-unix-socket under --disable-socket - no real network needed.
"""

from __future__ import annotations

import os
import socket
import threading
import time

import httpx

from docextract.config import OllamaConfig
from docextract.llm.base import LLMTimeoutError
from docextract.llm.ollama import OllamaBackend


class _HangingUnixServer:
    """Accepts connections and never responds - simulates a backend that is
    reachable but stuck (e.g. queued behind other requests with no reply
    yet), which is exactly the scenario that exposed the bug."""

    def __init__(self, sock_path: str) -> None:
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(sock_path)
        self._sock.listen(64)
        self._sock.settimeout(0.2)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        conns = []
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
                conns.append(conn)
            except socket.timeout:
                continue
            except OSError:
                break
        for c in conns:
            try:
                c.close()
            except OSError:
                pass

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self._sock.close()


def test_concurrent_calls_each_timeout_near_configured_value():
    # AF_UNIX paths are limited to ~104 bytes on macOS - pytest's nested
    # tmp_path is often too long, so use a short name directly under /tmp.
    sock_path = f"/tmp/de_test_{os.getpid()}.sock"
    if os.path.exists(sock_path):
        os.unlink(sock_path)
    server = _HangingUnixServer(sock_path)
    try:
        timeout_s = 1.0
        transport = httpx.HTTPTransport(uds=sock_path)
        config = OllamaConfig(
            base_url="http://localhost",
            model_tag="x", model_digest="y",
            request_timeout_s=timeout_s, connect_timeout_s=timeout_s,
        )
        # No injected client: each generate() call opens (and closes) its
        # own httpx.Client via _make_client(), but they must all route
        # through the Unix socket transport - patch the client factory.
        backend = OllamaBackend(config)
        backend._make_client = lambda: httpx.Client(  # noqa: SLF001 - test hook
            base_url=config.base_url,
            transport=transport,
            timeout=httpx.Timeout(config.request_timeout_s, connect=config.connect_timeout_s),
        )

        results: list[tuple[str, float]] = []
        results_lock = threading.Lock()

        def worker() -> None:
            start = time.monotonic()
            try:
                backend.generate("prompt", max_tokens=10)
                outcome = "no_error"
            except LLMTimeoutError:
                outcome = "timeout"
            except Exception as e:  # noqa: BLE001
                outcome = f"other:{type(e).__name__}"
            with results_lock:
                results.append((outcome, time.monotonic() - start))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        t0 = time.monotonic()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        total_wall = time.monotonic() - t0

        assert all(not t.is_alive() for t in threads), "a worker thread never returned"
        assert len(results) == 8
        for outcome, elapsed in results:
            assert outcome == "timeout", f"unexpected outcome: {outcome}"
            # generous margin over the 1s configured timeout - the bug made
            # this thousands of seconds, not a handful.
            assert elapsed < 10, f"timeout fired after {elapsed:.1f}s, expected ~{timeout_s}s"
        # 8 concurrent timeouts should overlap, not serialize to 8x.
        assert total_wall < 10, f"total wall time {total_wall:.1f}s suggests timeouts serialized"
    finally:
        server.close()
        if os.path.exists(sock_path):
            os.unlink(sock_path)
