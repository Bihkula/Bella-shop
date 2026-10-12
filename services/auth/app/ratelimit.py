"""Tiny in-process login throttle (per email). Per-pod only: for a fleet-wide
limit, back this with Redis or put rate limiting on the Ingress."""

from __future__ import annotations

import threading
import time


class LoginThrottle:
    def __init__(self, max_failures: int = 5, window_seconds: int = 300) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> list[float]:
        hits = [t for t in self._failures.get(key, []) if now - t < self.window]
        self._failures[key] = hits
        return hits

    def is_blocked(self, key: str, now: float | None = None) -> bool:
        now = now or time.monotonic()
        with self._lock:
            return len(self._recent(key, now)) >= self.max_failures

    def record_failure(self, key: str, now: float | None = None) -> None:
        now = now or time.monotonic()
        with self._lock:
            self._recent(key, now).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
