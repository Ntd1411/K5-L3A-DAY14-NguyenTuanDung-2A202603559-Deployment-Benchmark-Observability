"""
Cost guard tracking cumulative daily and monthly LLM spend in Redis.
"""
from datetime import datetime, timezone
import logging
import threading

from fastapi import HTTPException
import redis

from app.config import settings
from app.redis_client import r

logger = logging.getLogger(__name__)

# Price USD / 1K tokens (reference gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

DAILY_TTL_SECONDS = 172800     # 48 hours
MONTHLY_TTL_SECONDS = 3024000  # 35 days

_memory_lock = threading.Lock()
_memory_daily: dict[str, float] = {}
_memory_monthly: dict[str, float] = {}


def _current_keys() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return (
        f"cost:daily:{now.strftime('%Y-%m-%d')}",
        f"cost:monthly:{now.strftime('%Y-%m')}",
    )


def _get_memory_spend(daily_key: str, monthly_key: str) -> tuple[float, float]:
    with _memory_lock:
        return _memory_daily.get(daily_key, 0.0), _memory_monthly.get(monthly_key, 0.0)


def _add_memory_spend(daily_key: str, monthly_key: str, cost: float) -> None:
    with _memory_lock:
        _memory_daily[daily_key] = _memory_daily.get(daily_key, 0.0) + cost
        _memory_monthly[monthly_key] = _memory_monthly.get(monthly_key, 0.0) + cost


def check_budget() -> None:
    """Check daily and monthly spend before calling LLM; raise HTTP 402 if exceeded."""
    daily_key, monthly_key = _current_keys()

    if r is None:
        logger.warning(
            "Redis client not configured; checking in-memory budget fallback",
            extra={"event": "cost_guard_fallback"},
        )
        daily_spend, monthly_spend = _get_memory_spend(daily_key, monthly_key)
    else:
        try:
            daily_raw, monthly_raw = r.mget(daily_key, monthly_key)
            daily_spend = float(daily_raw or 0.0)
            monthly_spend = float(monthly_raw or 0.0)
        except redis.RedisError as exc:
            logger.warning(
                "Redis unavailable for budget check; falling back to in-memory spend",
                extra={"event": "cost_guard_fallback", "error": str(exc)},
            )
            daily_spend, monthly_spend = _get_memory_spend(daily_key, monthly_key)

    if daily_spend >= settings.daily_budget_usd or monthly_spend >= settings.monthly_budget_usd:
        raise HTTPException(status_code=402, detail="Budget exceeded")


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Compute request cost and increment daily/monthly totals in Redis."""
    cost = (input_tokens / 1000.0) * PRICE_INPUT_PER_1K + (output_tokens / 1000.0) * PRICE_OUTPUT_PER_1K
    daily_key, monthly_key = _current_keys()

    if r is None:
        logger.warning(
            "Redis client not configured; recording cost in memory",
            extra={"event": "cost_guard_fallback"},
        )
        _add_memory_spend(daily_key, monthly_key, cost)
        return cost

    try:
        pipe = r.pipeline()
        pipe.incrbyfloat(daily_key, cost)
        pipe.expire(daily_key, DAILY_TTL_SECONDS)
        pipe.incrbyfloat(monthly_key, cost)
        pipe.expire(monthly_key, MONTHLY_TTL_SECONDS)
        pipe.execute()
    except redis.RedisError as exc:
        logger.warning(
            "Redis unavailable for recording cost; falling back to in-memory spend",
            extra={"event": "cost_guard_fallback", "error": str(exc)},
        )
        _add_memory_spend(daily_key, monthly_key, cost)

    return cost
