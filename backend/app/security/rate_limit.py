import time
from collections import defaultdict


class SlidingWindowRateLimiter:
    """Configurable sliding-window rate limiter for auth, uploads, and sensitive endpoints."""

    def __init__(self) -> None:
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def check_and_record(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        now = time.monotonic()
        cutoff = now - window_seconds
        history = [ts for ts in self._buckets[key] if ts > cutoff]
        if len(history) >= limit:
            self._buckets[key] = history
            retry_after = max(1, int(window_seconds - (now - history[0])))
            return False, retry_after
        history.append(now)
        self._buckets[key] = history
        return True, 0

    def reset(self) -> None:
        self._buckets.clear()
