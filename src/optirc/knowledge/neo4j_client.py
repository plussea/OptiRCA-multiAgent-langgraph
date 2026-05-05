import logging
from typing import Any, Dict, List, Optional

from optirc.core.config import settings

logger = logging.getLogger(__name__)


class Neo4jClient:
    """Neo4j async client wrapper."""

    def __init__(self) -> None:
        self._driver: Optional[Any] = None
        self._initialized = False

    def _init(self) -> None:
        if self._initialized:
            return
        try:
            from neo4j import AsyncGraphDatabase
            self._driver = AsyncGraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
            self._initialized = True
            logger.info("Neo4j client initialized")
        except Exception as e:
            logger.warning("Neo4j init failed: %s", e)
            self._driver = None
            self._initialized = True

    async def query(self, cypher: str, parameters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Execute a Cypher query."""
        self._init()
        if self._driver is None:
            return []
        try:
            async with self._driver.session() as session:
                result = await session.run(cypher, parameters or {})
                records = []
                async for record in result:
                    records.append(dict(record))
                return records
        except Exception as e:
            logger.warning("Neo4j query failed: %s", e)
            return []

    async def close(self) -> None:
        if self._driver:
            await self._driver.close()
            self._driver = None


neo4j_client = Neo4jClient()
