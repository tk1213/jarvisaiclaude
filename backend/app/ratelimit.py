"""In-process sliding-window rate limiter (spec §6).

State lives in memory, so limits are per server process. That fits the
single-container deployment; move it to Redis if Core is ever scaled out.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, status


class RateLimiter:
    def __init__(self, window_seconds: float = 60):
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int) -> None:
        """Record one hit for `key`; raise 429 if it exceeds `limit` per window."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= limit:
                retry_after = int(hits[0] + self.window - now) + 1
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    "Too many requests, please slow down",
                    {"Retry-After": str(retry_after)},
                )
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()
