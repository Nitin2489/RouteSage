"""Small in-process sliding-window limiter for trusted local deployments."""
from __future__ import annotations

from collections import defaultdict, deque
from threading import Lock
from time import monotonic


class SlidingWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        if limit < 1 or window_seconds <= 0:
            raise ValueError("limit and window_seconds must be positive")
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = monotonic()
        with self._lock:
            window = self._requests[key]
            while window and now - window[0] >= self.window_seconds:
                window.popleft()
            if len(window) >= self.limit:
                return False
            window.append(now)
            return True
