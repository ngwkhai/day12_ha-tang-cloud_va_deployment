"""Redis-backed sliding-window rate limiter."""
import time
from collections import defaultdict, deque

from fastapi import HTTPException

from app.config import settings


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._windows: dict[str, deque[float]] = defaultdict(deque)
        self._redis = None

    def _client(self):
        if not settings.redis_url:
            return None
        if self._redis is None:
            import redis

            self._redis = redis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    def _check_redis(self, key: str) -> dict:
        now = time.time()
        bucket = f"rate:{key}"
        client = self._client()
        pipe = client.pipeline()
        pipe.zremrangebyscore(bucket, 0, now - self.window_seconds)
        pipe.zcard(bucket)
        pipe.zrange(bucket, 0, 0, withscores=True)
        _, count, oldest = pipe.execute()

        if count >= self.max_requests:
            oldest_score = oldest[0][1] if oldest else now
            retry_after = max(1, int(oldest_score + self.window_seconds - now) + 1)
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Rate limit exceeded",
                    "limit": self.max_requests,
                    "window_seconds": self.window_seconds,
                    "retry_after_seconds": retry_after,
                },
                headers={
                    "X-RateLimit-Limit": str(self.max_requests),
                    "X-RateLimit-Remaining": "0",
                    "Retry-After": str(retry_after),
                },
            )

        pipe = client.pipeline()
        pipe.zadd(bucket, {f"{now:.6f}": now})
        pipe.expire(bucket, self.window_seconds * 2)
        pipe.execute()
        return {
            "limit": self.max_requests,
            "remaining": self.max_requests - count - 1,
            "reset_at": int(now + self.window_seconds),
        }

    def _check_memory(self, key: str) -> dict:
        now = time.time()
        window = self._windows[key]
        while window and window[0] < now - self.window_seconds:
            window.popleft()

        if len(window) >= self.max_requests:
            retry_after = max(1, int(window[0] + self.window_seconds - now) + 1)
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Rate limit exceeded",
                    "limit": self.max_requests,
                    "window_seconds": self.window_seconds,
                    "retry_after_seconds": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        window.append(now)
        return {
            "limit": self.max_requests,
            "remaining": self.max_requests - len(window),
            "reset_at": int(now + self.window_seconds),
        }

    def check(self, key: str) -> dict:
        try:
            client = self._client()
            if client:
                client.ping()
                return self._check_redis(key)
        except Exception as exc:
            if isinstance(exc, HTTPException):
                raise
        return self._check_memory(key)


rate_limiter = RateLimiter(max_requests=settings.rate_limit_per_minute)


def check_rate_limit(key: str) -> dict:
    """Check and record one request for the given key."""
    return rate_limiter.check(key)
