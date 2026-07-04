import redis.asyncio as aioredis

from src.core.config import settings

# Configure async Redis client
redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
