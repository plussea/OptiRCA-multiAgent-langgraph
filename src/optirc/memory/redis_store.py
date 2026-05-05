import json
import logging
from typing import Any, Dict, Optional

from optirc.core.config import settings

logger = logging.getLogger(__name__)


class RedisStore:
    """Redis async cache wrapper."""

    def __init__(self) -> None:
        self._client: Optional[Any] = None
        self._initialized = False

    def _init(self) -> None:
        if self._initialized:
            return
        try:
            import redis.asyncio as redis
            self._client = redis.from_url(settings.redis_url, decode_responses=True)
            self._initialized = True
            logger.info("Redis client initialized")
        except Exception as e:
            logger.warning("Redis init failed: %s", e)
            self._client = None
            self._initialized = True

    async def get(self, key: str) -> Optional[str]:
        self._init()
        if self._client is None:
            return None
        try:
            return await self._client.get(key)
        except Exception as e:
            logger.warning("Redis get failed: %s", e)
            return None

    async def set(self, key: str, value: str, ttl: int = 60) -> None:
        self._init()
        if self._client is None:
            return
        try:
            await self._client.setex(key, ttl, value)
        except Exception as e:
            logger.warning("Redis set failed: %s", e)

    async def publish(self, channel: str, message: str) -> None:
        self._init()
        if self._client is None:
            return
        try:
            await self._client.publish(channel, message)
        except Exception as e:
            logger.warning("Redis publish failed: %s", e)

    async def get_session_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        raw = await self.get(f"session:{session_id}")
        if raw:
            return json.loads(raw)
        return None

    async def set_session_state(self, session_id: str, state: Dict[str, Any]) -> None:
        await self.set(f"session:{session_id}", json.dumps(state), ttl=60)


redis_store = RedisStore()
