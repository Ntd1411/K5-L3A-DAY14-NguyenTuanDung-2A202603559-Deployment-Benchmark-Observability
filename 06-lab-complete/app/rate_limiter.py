"""
Sliding-window rate limiter backed by Redis sorted sets with RedisError fallback.
"""
from collections import defaultdict, deque
import logging
import math
import threading
import time
import uuid

from fastapi import HTTPException
import redis

from app.config import settings
from app.redis_client import r

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60

_memory_lock = threading.Lock()
_memory_windows: dict[str, deque[float]] = defaultdict(deque)


def _check_rate_limit_memory(key: str, limit: int, now: float) -> None:
    window_start = now - WINDOW_SECONDS
    with _memory_lock:
        timestamps = _memory_windows[key]
        while timestamps and timestamps[0] <= window_start:
            timestamps.popleft()
        if len(timestamps) >= limit:
            retry_after = max(1, int(math.ceil(timestamps[0] + WINDOW_SECONDS - now)))
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )
        timestamps.append(now)


def check_rate_limit(key: str) -> None:
    """Enforce per-key sliding-window rate limit in Redis, falling back only on RedisError."""
    limit = settings.rate_limit_per_minute
    now = time.time()
    window_start = now - WINDOW_SECONDS

    if r is None:
        logger.warning(
            "Redis client not configured; using in-memory rate limit fallback",
            extra={"event": "rate_limit_fallback"},
        )
        _check_rate_limit_memory(key, limit, now)
        return

    redis_key = f"rate_limit:{key}"
    try:
        pipe = r.pipeline()
        pipe.zremrangebyscore(redis_key, 0, window_start)
        pipe.zcard(redis_key)
        _, count = pipe.execute()

        if count >= limit:
            oldest = r.zrange(redis_key, 0, 0, withscores=True)
            if oldest:
                retry_after = max(1, int(math.ceil(oldest[0][1] + WINDOW_SECONDS - now)))
            else:
                retry_after = WINDOW_SECONDS
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )

        member = f"{now}:{uuid.uuid4().hex}"
        pipe = r.pipeline()
        pipe.zadd(redis_key, {member: now})
        pipe.expire(redis_key, WINDOW_SECONDS + 1)
        pipe.execute()
    except redis.RedisError as exc:
        logger.warning(
            "Redis unavailable for rate limiting; falling back to in-memory window",
            extra={"event": "rate_limit_fallback", "error": str(exc)},
        )
        _check_rate_limit_memory(key, limit, now)
