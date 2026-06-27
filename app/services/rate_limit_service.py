from __future__ import annotations

from collections import defaultdict, deque
from time import monotonic

from fastapi import HTTPException, Request, status


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, *, limit: int, window_seconds: int) -> None:
        now = monotonic()
        bucket = self._buckets[key]
        while bucket and now - bucket[0] > window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests.")
        bucket.append(now)


rate_limiter = InMemoryRateLimiter()


def client_key(request: Request, suffix: str) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        ip_address = forwarded_for.split(",", 1)[0].strip()
    else:
        ip_address = request.client.host if request.client else "unknown"
    return f"{suffix}:{ip_address}"
