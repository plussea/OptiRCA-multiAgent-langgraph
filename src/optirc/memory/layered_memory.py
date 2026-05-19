"""Layered memory architecture for OptiRCAgent.

Implements a hierarchical memory system:
- Working Memory: In-process short-term state (Redis)
- Episodic Memory: Session-level context (PostgreSQL)
- Semantic Memory: Long-term knowledge (Neo4j + Vector DB)
- Procedural Memory: Tool usage patterns and learned strategies
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Protocol

from optirc.memory.db_store import db_store
from optirc.memory.redis_store import redis_store

logger = logging.getLogger(__name__)


@dataclass
class MemoryEntry:
    """A single memory entry."""
    key: str
    value: Any
    layer: str
    session_id: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now())
    ttl: Optional[int] = None  # seconds
    importance: float = 1.0  # 0.0 - 10.0
    tags: List[str] = field(default_factory=list)


class MemoryLayer(ABC):
    """Abstract base class for memory layers."""

    @abstractmethod
    async def store(self, entry: MemoryEntry) -> bool:
        """Store a memory entry."""
        pass

    @abstractmethod
    async def retrieve(self, key: str, session_id: Optional[str] = None) -> Optional[Any]:
        """Retrieve a memory entry by key."""
        pass

    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> List[MemoryEntry]:
        """Search memory entries by semantic similarity."""
        pass

    @abstractmethod
    async def clear(self, session_id: Optional[str] = None) -> None:
        """Clear memory entries."""
        pass


class WorkingMemory(MemoryLayer):
    """Fast in-memory cache using Redis.

    Stores:
    - Current session state
    - Active pipeline context
    - Temporary computation results
    TTL: minutes to hours
    """

    async def store(self, entry: MemoryEntry) -> bool:
        if entry.ttl is None:
            entry.ttl = 3600  # Default 1 hour
        try:
            data = {
                "value": entry.value,
                "timestamp": entry.timestamp.isoformat(),
                "importance": entry.importance,
                "tags": entry.tags,
            }
            key = f"wm:{entry.session_id or 'global'}:{entry.key}"
            await redis_store.set(key, str(data), ttl=entry.ttl)
            return True
        except Exception as e:
            logger.error(f"Working memory store failed: {e}")
            return False

    async def retrieve(self, key: str, session_id: Optional[str] = None) -> Optional[Any]:
        try:
            full_key = f"wm:{session_id or 'global'}:{key}"
            data = await redis_store.get(full_key)
            if data:
                import json
                parsed = json.loads(data.replace("'", '"'))
                return parsed.get("value")
            return None
        except Exception as e:
            logger.error(f"Working memory retrieve failed: {e}")
            return None

    async def search(self, query: str, limit: int = 10) -> List[MemoryEntry]:
        # Working memory doesn't support semantic search
        return []

    async def clear(self, session_id: Optional[str] = None) -> None:
        try:
            pattern = f"wm:{session_id or 'global'}:*"
            # Redis doesn't support pattern deletion directly
            # Would need KEYS + DEL or a Redis module
            logger.info(f"Working memory clear requested for {session_id}")
        except Exception as e:
            logger.error(f"Working memory clear failed: {e}")


class EpisodicMemory(MemoryLayer):
    """Session-level persistent storage using PostgreSQL.

    Stores:
    - Session history and state transitions
    - Human decisions and feedback
    - Pipeline execution traces
    TTL: days to months
    """

    async def store(self, entry: MemoryEntry) -> bool:
        try:
            await db_store.update_session(
                entry.session_id or "global",
                entry.key,
                entry.value
            )
            return True
        except Exception as e:
            logger.error(f"Episodic memory store failed: {e}")
            return False

    async def retrieve(self, key: str, session_id: Optional[str] = None) -> Optional[Any]:
        try:
            state = await db_store.get_session(session_id or "global")
            if state:
                return state.get(key)
            return None
        except Exception as e:
            logger.error(f"Episodic memory retrieve failed: {e}")
            return None

    async def search(self, query: str, limit: int = 10) -> List[MemoryEntry]:
        # Episodic memory uses SQL search
        return []

    async def clear(self, session_id: Optional[str] = None) -> None:
        logger.info(f"Episodic memory clear requested for {session_id}")


class SemanticMemory(MemoryLayer):
    """Long-term knowledge storage using Neo4j + Vector DB.

    Stores:
    - Learned patterns and correlations
    - Historical RCA solutions
    - Domain knowledge graph
    TTL: permanent
    """

    async def store(self, entry: MemoryEntry) -> bool:
        # Store in knowledge graph and vector DB
        try:
            # Placeholder for KG integration
            logger.info(f"Semantic memory store: {entry.key}")
            return True
        except Exception as e:
            logger.error(f"Semantic memory store failed: {e}")
            return False

    async def retrieve(self, key: str, session_id: Optional[str] = None) -> Optional[Any]:
        try:
            # Placeholder for KG retrieval
            return None
        except Exception as e:
            logger.error(f"Semantic memory retrieve failed: {e}")
            return None

    async def search(self, query: str, limit: int = 10) -> List[MemoryEntry]:
        try:
            # Placeholder for semantic search
            return []
        except Exception as e:
            logger.error(f"Semantic memory search failed: {e}")
            return []

    async def clear(self, session_id: Optional[str] = None) -> None:
        logger.warning("Semantic memory clear not supported")


class MemoryManager:
    """Unified interface for all memory layers."""

    def __init__(self) -> None:
        self.working = WorkingMemory()
        self.episodic = EpisodicMemory()
        self.semantic = SemanticMemory()
        self._layers = {
            "working": self.working,
            "episodic": self.episodic,
            "semantic": self.semantic,
        }

    async def store(
        self,
        key: str,
        value: Any,
        layer: str = "working",
        session_id: Optional[str] = None,
        ttl: Optional[int] = None,
        importance: float = 1.0,
        tags: Optional[List[str]] = None
    ) -> bool:
        """Store a value in the specified memory layer."""
        memory_layer = self._layers.get(layer)
        if not memory_layer:
            logger.error(f"Unknown memory layer: {layer}")
            return False

        entry = MemoryEntry(
            key=key,
            value=value,
            layer=layer,
            session_id=session_id,
            ttl=ttl,
            importance=importance,
            tags=tags or []
        )
        return await memory_layer.store(entry)

    async def retrieve(
        self,
        key: str,
        layer: str = "working",
        session_id: Optional[str] = None
    ) -> Optional[Any]:
        """Retrieve a value from the specified memory layer."""
        memory_layer = self._layers.get(layer)
        if not memory_layer:
            return None
        return await memory_layer.retrieve(key, session_id)

    async def multi_layer_retrieve(
        self,
        key: str,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Retrieve from all layers, returning the most relevant result."""
        results = {}
        for layer_name, layer in self._layers.items():
            try:
                value = await layer.retrieve(key, session_id)
                if value is not None:
                    results[layer_name] = value
            except Exception as e:
                logger.debug(f"Layer {layer_name} retrieve failed: {e}")
        return results

    async def search(
        self,
        query: str,
        layer: str = "semantic",
        limit: int = 10
    ) -> List[MemoryEntry]:
        """Search memory entries by semantic similarity."""
        memory_layer = self._layers.get(layer)
        if not memory_layer:
            return []
        return await memory_layer.search(query, limit)

    async def consolidate(
        self,
        session_id: str,
        min_importance: float = 5.0
    ) -> None:
        """Consolidate working memory to episodic/semantic memory.

        Moves high-importance entries from working to long-term storage.
        """
        logger.info(f"Memory consolidation for session {session_id}")
        # Implementation would scan working memory and promote important entries
        pass


# Global memory manager
memory_manager = MemoryManager()
