import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import asyncpg

from optirc.core.config import settings

logger = logging.getLogger(__name__)


class DBStore:
    """PostgreSQL async persistence layer."""

    def __init__(self) -> None:
        self._pool: Optional[asyncpg.Pool] = None
        self._initialized = False

    async def _init(self) -> None:
        if self._initialized:
            return
        try:
            dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
            self._pool = await asyncpg.create_pool(dsn, min_size=1, max_size=10)
            self._initialized = True
            logger.info("PostgreSQL pool initialized")
            await self._ensure_tables()
        except Exception as e:
            logger.warning("PostgreSQL init failed: %s", e)
            self._pool = None
            self._initialized = True

    async def _ensure_tables(self) -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS opticrc_sessions (
                    session_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'init',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    final_result JSONB
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS opticrc_conversations (
                    id SERIAL PRIMARY KEY,
                    session_id TEXT REFERENCES opticrc_sessions(session_id),
                    agent_name TEXT,
                    step TEXT,
                    input_payload JSONB,
                    output_payload JSONB,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

    async def create_session(self, session_id: str) -> None:
        await self._init()
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO opticrc_sessions (session_id, status)
                VALUES ($1, 'init')
                ON CONFLICT (session_id) DO UPDATE
                SET status = EXCLUDED.status, updated_at = NOW()
                """,
                session_id,
            )

    async def update_session(
        self,
        session_id: str,
        status: str,
        final_result: Optional[Dict[str, Any]] = None,
    ) -> None:
        await self._init()
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE opticrc_sessions
                SET status = $1, updated_at = NOW(), final_result = $2
                WHERE session_id = $3
                """,
                status,
                json.dumps(final_result) if final_result else None,
                session_id,
            )

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        await self._init()
        if self._pool is None:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM opticrc_sessions WHERE session_id = $1",
                session_id,
            )
            if row:
                return dict(row)
            return None

    async def log_conversation(
        self,
        session_id: str,
        agent_name: str,
        step: str,
        input_payload: Dict[str, Any],
        output_payload: Dict[str, Any],
    ) -> None:
        await self._init()
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO opticrc_conversations
                (session_id, agent_name, step, input_payload, output_payload)
                VALUES ($1, $2, $3, $4, $5)
                """,
                session_id,
                agent_name,
                step,
                json.dumps(input_payload),
                json.dumps(output_payload),
            )

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None


db_store = DBStore()
