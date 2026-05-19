"""Tests for database store with health checks."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from optirc.memory.db_store import DBStore


class TestDBStore:
    @pytest.mark.asyncio
    async def test_init_creates_pool(self):
        store = DBStore()

        class AsyncContextManager:
            def __init__(self, conn):
                self._conn = conn
            async def __aenter__(self):
                return self._conn
            async def __aexit__(self, *args):
                return False

        class MockConnection:
            async def execute(self, *args, **kwargs):
                return None

        class MockPool:
            def __init__(self):
                self._conn = MockConnection()

            def acquire(self):
                return AsyncContextManager(self._conn)

            def get_size(self):
                return 1

        mock_pool = MockPool()

        async def mock_create_pool(*args, **kwargs):
            return mock_pool

        with patch("asyncpg.create_pool", side_effect=mock_create_pool):
            await store._init()
            assert store._initialized
            assert store._pool is not None

    @pytest.mark.asyncio
    async def test_init_failure_graceful(self):
        store = DBStore()
        with patch("asyncpg.create_pool", side_effect=Exception("connection failed")):
            await store._init()
            assert store._initialized
            assert store._pool is None

    @pytest.mark.asyncio
    async def test_health_check_healthy(self):
        store = DBStore()
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock()
        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        store._pool = mock_pool
        store._initialized = True

        result = await store._health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_no_pool(self):
        store = DBStore()
        store._pool = None
        result = await store._health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_recent_check(self):
        store = DBStore()
        store._pool = MagicMock()
        store._initialized = True
        store._last_health_check = 9999999999  # Far future

        result = await store._health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_create_session_no_pool(self):
        store = DBStore()
        store._pool = None
        store._initialized = True
        # Should not raise
        await store.create_session("test-session")

    @pytest.mark.asyncio
    async def test_close(self):
        store = DBStore()
        mock_pool = MagicMock()
        mock_pool.close = AsyncMock()
        store._pool = mock_pool

        await store.close()
        assert store._pool is None


class TestRedisStore:
    @pytest.mark.asyncio
    async def test_get_no_client(self):
        from optirc.memory.redis_store import RedisStore
        store = RedisStore()
        store._client = None
        store._initialized = True
        result = await store.get("test-key")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_no_client(self):
        from optirc.memory.redis_store import RedisStore
        store = RedisStore()
        store._client = None
        store._initialized = True
        # Should not raise
        await store.set("test-key", "test-value")

    @pytest.mark.asyncio
    async def test_get_failure_recovery(self):
        from optirc.memory.redis_store import RedisStore
        store = RedisStore()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=Exception("connection lost"))
        store._client = mock_client
        store._initialized = True

        result = await store.get("test-key")
        assert result is None
        assert store._client is None  # Should reset for reconnection
        assert not store._initialized
