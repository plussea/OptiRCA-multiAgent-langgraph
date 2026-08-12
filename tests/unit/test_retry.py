"""Tests for retry and circuit breaker functionality."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from optirc.core.circuit_breaker import CircuitBreaker, CircuitBreakerRegistry, CircuitState, circuit_registry
from optirc.core.exceptions import LLMCircuitOpenError, LLMRateLimitError
from optirc.core.retry import RetryConfig, QuotaLimiter, async_retry


class TestRetryConfig:
    def test_default_config(self):
        config = RetryConfig()
        assert config.max_retries == 3
        assert config.base_delay == 1.0
        assert config.max_delay == 60.0

    def test_compute_delay(self):
        config = RetryConfig(base_delay=1.0, exponential_base=2.0, jitter=0)
        assert config.compute_delay(0) == 1.0
        assert config.compute_delay(1) == 2.0
        assert config.compute_delay(2) == 4.0

    def test_compute_delay_with_jitter(self):
        config = RetryConfig(base_delay=1.0, jitter=0.1)
        delay = config.compute_delay(0)
        assert 0.9 <= delay <= 1.1

    def test_compute_delay_max_cap(self):
        config = RetryConfig(base_delay=10.0, max_delay=15.0, exponential_base=2.0, jitter=0)
        assert config.compute_delay(0) == 10.0
        assert config.compute_delay(1) == 15.0  # Capped at max_delay


class TestAsyncRetry:
    @pytest.mark.asyncio
    async def test_success_no_retry(self):
        mock_func = AsyncMock(return_value="success")

        @async_retry(RetryConfig(max_retries=2, timeout=10))
        async def test_func():
            return await mock_func()

        result = await test_func()
        assert result == "success"
        assert mock_func.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_then_success(self):
        mock_func = AsyncMock(side_effect=[LLMRateLimitError("rate limited"), "success"])

        @async_retry(RetryConfig(max_retries=2, base_delay=0.01, timeout=10))
        async def test_func():
            return await mock_func()

        result = await test_func()
        assert result == "success"
        assert mock_func.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_exhausted(self):
        mock_func = AsyncMock(side_effect=LLMRateLimitError("rate limited"))

        @async_retry(RetryConfig(max_retries=1, base_delay=0.01, timeout=10))
        async def test_func():
            return await mock_func()

        with pytest.raises(LLMRateLimitError):
            await test_func()
        assert mock_func.call_count == 2  # initial + 1 retry

    @pytest.mark.asyncio
    async def test_non_retryable_exception(self):
        mock_func = AsyncMock(side_effect=ValueError("not retryable"))

        @async_retry(RetryConfig(max_retries=2, timeout=10))
        async def test_func():
            return await mock_func()

        with pytest.raises(ValueError):
            await test_func()
        assert mock_func.call_count == 1

    @pytest.mark.asyncio
    async def test_timeout(self):
        @async_retry(RetryConfig(max_retries=1, timeout=0.01, base_delay=0.01))
        async def slow_func():
            await asyncio.sleep(1)
            return "never"

        with pytest.raises(Exception) as exc_info:
            await slow_func()
        assert "timed out" in str(exc_info.value).lower()


class TestQuotaLimiter:
    @pytest.mark.asyncio
    async def test_acquire_within_limit(self):
        limiter = QuotaLimiter(requests_per_minute=10)
        # Should not block
        await limiter.acquire()
        await limiter.acquire()
        metrics = limiter.get_metrics()
        assert metrics["requests_per_minute"] == 10
        assert metrics["available_tokens"] < 10

    @pytest.mark.asyncio
    async def test_acquire_blocks_when_exhausted(self):
        limiter = QuotaLimiter(requests_per_minute=1)
        await limiter.acquire()
        # Next acquire should wait
        start = asyncio.get_event_loop().time()
        await limiter.acquire()
        elapsed = asyncio.get_event_loop().time() - start
        assert elapsed >= 0.5  # Should have waited for token replenishment


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_initial_state_closed(self):
        breaker = CircuitBreaker("test")
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_successful_call(self):
        breaker = CircuitBreaker("test")
        result = await breaker.call(lambda: asyncio.sleep(0))
        assert result is None
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_failure_counting(self):
        breaker = CircuitBreaker("test", failure_threshold=3)

        for _ in range(2):
            with pytest.raises(ValueError):
                await breaker.call(lambda: (_ for _ in ()).throw(ValueError("fail")))

        assert breaker.state == CircuitState.CLOSED  # Not yet tripped
        metrics = breaker.get_metrics()
        assert metrics["failures_in_window"] == 2

    @pytest.mark.asyncio
    async def test_circuit_trip(self):
        breaker = CircuitBreaker("test", failure_threshold=2, recovery_timeout=0.1)

        for _ in range(2):
            with pytest.raises(ValueError):
                await breaker.call(lambda: (_ for _ in ()).throw(ValueError("fail")))

        assert breaker.state == CircuitState.OPEN

        # Should fast-fail
        with pytest.raises(LLMCircuitOpenError):
            await breaker.call(lambda: asyncio.sleep(0))

    @pytest.mark.asyncio
    async def test_circuit_recovery(self):
        breaker = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.01)

        with pytest.raises(ValueError):
            await breaker.call(lambda: (_ for _ in ()).throw(ValueError("fail")))

        assert breaker.state == CircuitState.OPEN

        # Wait for recovery
        await asyncio.sleep(0.02)

        # Should allow probe call
        result = await breaker.call(lambda: asyncio.sleep(0))
        assert result is None

    @pytest.mark.asyncio
    async def test_half_open_failure_retrip(self):
        breaker = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.01)

        with pytest.raises(ValueError):
            await breaker.call(lambda: (_ for _ in ()).throw(ValueError("fail")))

        await asyncio.sleep(0.02)

        # Probe fails
        with pytest.raises(ValueError):
            await breaker.call(lambda: (_ for _ in ()).throw(ValueError("fail")))

        assert breaker.state == CircuitState.OPEN

    def test_metrics(self):
        breaker = CircuitBreaker("test_metrics", failure_threshold=5, recovery_timeout=30.0)
        metrics = breaker.get_metrics()
        assert metrics["name"] == "test_metrics"
        assert metrics["state"] == "closed"
        assert metrics["failure_threshold"] == 5
        assert metrics["recovery_timeout"] == 30.0


class TestCircuitBreakerRegistry:
    def test_get_or_create(self):
        registry = CircuitBreakerRegistry()
        breaker1 = registry.get_or_create("test", failure_threshold=3)
        breaker2 = registry.get_or_create("test", failure_threshold=3)
        assert breaker1 is breaker2

    def test_all_metrics(self):
        registry = CircuitBreakerRegistry()
        registry.get_or_create("breaker1")
        registry.get_or_create("breaker2")
        metrics = registry.all_metrics()
        assert len(metrics) == 2

    def test_get_nonexistent(self):
        registry = CircuitBreakerRegistry()
        assert registry.get("nonexistent") is None
