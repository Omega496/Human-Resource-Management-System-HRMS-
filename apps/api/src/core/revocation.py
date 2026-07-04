import asyncio
import logging
import time
from typing import Dict

from src.core.redis import redis_client

logger = logging.getLogger(__name__)


class RevocationCache:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(RevocationCache, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self) -> None:
        if not hasattr(self, "_initialized"):
            # Maps jti -> expiry timestamp (float unix epoch)
            self._revoked_jtis: Dict[str, float] = {}
            self._pubsub_task: asyncio.Task | None = None
            self._initialized = True

    async def hydrate(self) -> None:
        """
        Hydrate the in-memory cache from Redis.
        We prune expired items using ZREMRANGEBYSCORE and fetch currently active ones.
        """
        now = time.time()
        try:
            # 1. Prune expired revocations in Redis
            # We remove anything with score < now
            await redis_client.zremrangebyscore("revoked_jtis_zset", "-inf", now)

            # 2. Fetch all currently active revocations
            # Scores between now and +inf represent active revocations
            active_items = await redis_client.zrangebyscore("revoked_jtis_zset", now, "+inf", withscores=True)

            for jti, score in active_items:
                self._revoked_jtis[jti] = float(score)

            logger.info(f"Hydrated {len(active_items)} active revocations from Redis")
        except Exception as e:
            logger.error(f"Failed to hydrate revocation cache from Redis: {e}")

    async def start_listener(self) -> None:
        """
        Start the background Redis Pub/Sub listener.
        """
        if self._pubsub_task is not None:
            return

        async def listen():
            pubsub = redis_client.pubsub()
            await pubsub.subscribe("session_revocations")
            logger.info("Subscribed to Redis channel 'session_revocations'")
            try:
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        jti_msg = message["data"]
                        if ":" in jti_msg:
                            parts = jti_msg.split(":", 1)
                            jti_val = parts[0]
                            expiry = float(parts[1])
                            self._revoked_jtis[jti_val] = expiry
                            logger.info(f"Received revocation broadcast for JTI: {jti_val} (expires {expiry})")
                        else:
                            jti_val = jti_msg
                            score = await redis_client.zscore("revoked_jtis_zset", jti_val)
                            if score is not None:
                                self._revoked_jtis[jti_val] = float(score)
                                logger.info(f"Received revocation for JTI: {jti_val} with score {score}")
            except asyncio.CancelledError:
                logger.info("Pub/Sub listener cancelled")
            except Exception as e:
                logger.error(f"Error in Pub/Sub listener: {e}")
            finally:
                await pubsub.unsubscribe("session_revocations")
                await pubsub.close()

        self._pubsub_task = asyncio.create_task(listen())

    async def stop_listener(self) -> None:
        if self._pubsub_task:
            self._pubsub_task.cancel()
            try:
                await self._pubsub_task
            except asyncio.CancelledError:
                pass
            self._pubsub_task = None

    def is_revoked(self, jti: str) -> bool:
        """
        Check if a JTI is revoked. Purges expired items lazily on lookup.
        """
        now = time.time()
        expiry = self._revoked_jtis.get(jti)
        if expiry is None:
            return False
        if expiry < now:
            self._revoked_jtis.pop(jti, None)
            return False
        return True

    async def revoke(self, jti: str, expiry_timestamp: float) -> None:
        """
        Revoke a JTI:
        1. Write to Redis ZSET
        2. Publish to Pub/Sub
        3. Add to local memory
        """
        await redis_client.zadd("revoked_jtis_zset", {jti: expiry_timestamp})
        message = f"{jti}:{expiry_timestamp}"
        await redis_client.publish("session_revocations", message)
        self._revoked_jtis[jti] = expiry_timestamp

    def clear_local(self) -> None:
        """Clear local in-memory cache (mainly for testing)."""
        self._revoked_jtis.clear()


revocation_cache = RevocationCache()
