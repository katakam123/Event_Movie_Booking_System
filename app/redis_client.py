
import os

import redis
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL")

if not REDIS_URL:
    raise RuntimeError("REDIS_URL is missing from .env")

redis_client = redis.Redis.from_url(
    REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=3,
    socket_timeout=3,
    health_check_interval=30,
)


def check_redis() -> bool:
    return bool(redis_client.ping())
