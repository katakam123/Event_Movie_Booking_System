
import json
import logging

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from app.redis_client import redis_client

logger = logging.getLogger(__name__)

EVENT_CACHE_TTL = 300

RATE_LIMIT_SCRIPT = """
local current = redis.call("INCR", KEYS[1])

if current == 1 then
    redis.call("EXPIRE", KEYS[1], ARGV[1])
end

local ttl = redis.call("TTL", KEYS[1])

return {current, ttl}
"""


def get_cached_json(key: str):

    try:
        cached_value = redis_client.get(key)

        if cached_value is None:
            return None

        return json.loads(cached_value)

    except Exception:
        logger.exception("Redis cache read failed: %s", key)
        return None


def set_cached_json(
    key: str,
    value,
    ttl: int = EVENT_CACHE_TTL
):

    try:
        encoded_value = jsonable_encoder(value)

        redis_client.setex(
            key,
            ttl,
            json.dumps(encoded_value, default=str)
        )

    except Exception:
        logger.exception("Redis cache write failed: %s", key)


def invalidate_event_cache(event_id: int | None = None):

    keys = ["events:list"]

    if event_id is not None:
        keys.append(f"events:detail:{event_id}")

    try:
        redis_client.delete(*keys)

    except Exception:
        logger.exception("Redis event cache invalidation failed")


def enforce_rate_limit(
    key: str,
    limit: int = 5,
    window_seconds: int = 60
):

    try:
        result = redis_client.eval(
            RATE_LIMIT_SCRIPT,
            1,
            key,
            window_seconds
        )

        request_count = int(result[0])
        remaining_seconds = max(
            1,
            int(result[1])
        )

        if request_count > limit:

            raise HTTPException(
                status_code=429,
                detail={
                    "message": "Too many requests. Please try again later.",
                    "retry_after_seconds": remaining_seconds
                },
                headers={
                    "Retry-After": str(remaining_seconds)
                }
            )

    except HTTPException:
        raise

    except Exception:
        logger.exception("Redis rate limiter failed")

        raise HTTPException(
            status_code=503,
            detail="Rate limiting service is temporarily unavailable."
        )
