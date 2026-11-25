"""
Shared Redis client for rate limiting and cost guard.

Created lazily without pinging at import time so the app can start even when Redis is down.
"""
from typing import Optional

import redis

from app.config import settings


def _create_client() -> Optional[redis.Redis]:
    if not settings.redis_url:
        return None
    return redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


r: Optional[redis.Redis] = _create_client()


def redis_healthy() -> bool:
    """Ping Redis and return False on any connection or runtime error."""
    if r is None:
        return False
    try:
        return bool(r.ping())
    except Exception:
        return False


def close_redis() -> None:
    """Close the shared Redis client cleanly on shutdown."""
    if r is None:
        return
    try:
        r.close()
    except Exception:
        pass
