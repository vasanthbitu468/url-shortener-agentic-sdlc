"""Fixed-window rate limiter.

In-process and thread-safe, which is correct for a single instance. Running several
instances needs a shared store (e.g. Redis INCR + EXPIRE) behind the same interface.
"""

import threading
import time
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_requests < 1 or window_seconds < 1:
            raise ValueError("max_requests and window_seconds must be positive")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._windows: dict[str, tuple[int, int]] = {}  # key -> (window index, count)

    def allow(self, key: str) -> bool:
        """Record one request for ``key``; return False if it exceeds the limit."""
        window = int(self._clock() // self.window_seconds)
        with self._lock:
            current, count = self._windows.get(key, (window, 0))
            if current != window:
                current, count = window, 0
            if count >= self.max_requests:
                self._windows[key] = (current, count)
                return False
            self._windows[key] = (current, count + 1)
            if len(self._windows) > 50_000:
                self._evict(window)
            return True

    def retry_after(self) -> int:
        """Seconds until the current window ends."""
        now = self._clock()
        return max(1, int(self.window_seconds - (now % self.window_seconds)))

    def _evict(self, window: int) -> None:
        stale = [k for k, (w, _) in self._windows.items() if w != window]
        for k in stale:
            del self._windows[k]
