"""Circuit breaker pattern for resilient external service calls.

Implements the classic three-state machine:
    CLOSED   -> calls pass through, failures are counted
    OPEN     -> calls fast-fail for a cooldown period
    HALF-OPEN -> one probe call is allowed to test recovery

Usage:
    breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30)
    async with breaker:
        result = await some_external_call()
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Async circuit breaker with sliding-window failure counting.

    Args:
        name: Identifier for logging/metrics.
        failure_threshold: Number of failures within window to trip OPEN.
        recovery_timeout: Seconds to wait before attempting HALF_OPEN.
        half_open_max_calls: Max probe calls allowed in HALF_OPEN state.
        success_threshold: Consecutive successes in HALF_OPEN to close.
        sliding_window_seconds: Time window for failure counting.
        on_state_change: Optional callback(state: CircuitState) for metrics.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 3,
        success_threshold: int = 2,
        sliding_window_seconds: float = 60.0,
        on_state_change: Optional[Callable[[CircuitState], None]] = None,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.success_threshold = success_threshold
        self.sliding_window_seconds = sliding_window_seconds
        self.on_state_change = on_state_change

        self._state = CircuitState.CLOSED
        self._lock = asyncio.Lock()
        self._failures: list[float] = []
        self._last_failure_time: Optional[float] = None
        self._half_open_calls = 0
        self._half_open_successes = 0

    @property
    def state(self) -> CircuitState:
        return self._state

    def _now(self) -> float:
        return time.monotonic()

    def _prune_failures(self) -> None:
        cutoff = self._now() - self.sliding_window_seconds
        self._failures = [t for t in self._failures if t > cutoff]

    def _trip(self) -> None:
        self._state = CircuitState.OPEN
        self._last_failure_time = self._now()
        logger.warning(
            "Circuit breaker '%s' tripped OPEN (failures=%d)",
            self.name,
            len(self._failures),
        )
        if self.on_state_change:
            try:
                self.on_state_change(self._state)
            except Exception:
                pass

    def _attempt_reset(self) -> bool:
        if self._last_failure_time is None:
            return True
        if self._now() - self._last_failure_time >= self.recovery_timeout:
            self._state = CircuitState.HALF_OPEN
            self._half_open_calls = 0
            self._half_open_successes = 0
            logger.info("Circuit breaker '%s' entering HALF_OPEN", self.name)
            if self.on_state_change:
                try:
                    self.on_state_change(self._state)
                except Exception:
                    pass
            return True
        return False

    def _close(self) -> None:
        self._state = CircuitState.CLOSED
        self._failures.clear()
        self._last_failure_time = None
        self._half_open_calls = 0
        self._half_open_successes = 0
        logger.info("Circuit breaker '%s' CLOSED", self.name)
        if self.on_state_change:
            try:
                self.on_state_change(self._state)
            except Exception:
                pass

    async def call(self, coro_factory: Callable[[], Any]) -> Any:
        """Execute a coroutine under circuit breaker protection.

        Args:
            coro_factory: Callable that returns a coroutine (not the coroutine itself).
                         This ensures fresh coroutines on retry.

        Raises:
            LLMCircuitOpenError: If circuit is OPEN and recovery timeout not elapsed.
            Exception: The original exception from the coroutine.
        """
        from optirc.core.exceptions import LLMCircuitOpenError

        async with self._lock:
            self._prune_failures()

            if self._state == CircuitState.OPEN:
                if not self._attempt_reset():
                    raise LLMCircuitOpenError(
                        f"Circuit breaker '{self.name}' is OPEN. "
                        f"Retry after {self.recovery_timeout}s."
                    )

            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    raise LLMCircuitOpenError(
                        f"Circuit breaker '{self.name}' is HALF_OPEN but max probe calls reached."
                    )
                self._half_open_calls += 1

        # Execute outside lock to allow concurrency
        try:
            result = await coro_factory()
        except Exception as exc:
            async with self._lock:
                self._failures.append(self._now())
                self._last_failure_time = self._now()

                if self._state == CircuitState.HALF_OPEN:
                    self._trip()
                elif len(self._failures) >= self.failure_threshold:
                    self._trip()

            logger.warning(
                "Circuit breaker '%s' recorded failure (%s), state=%s, failures=%d",
                self.name,
                type(exc).__name__,
                self._state.value,
                len(self._failures),
            )
            raise

        # Success path
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_successes += 1
                if self._half_open_successes >= self.success_threshold:
                    self._close()
            else:
                # In CLOSED state, clear old failures on success
                self._prune_failures()

        return result

    @asynccontextmanager
    async def context(self):
        """Async context manager wrapper.

        Usage:
            async with breaker.context():
                result = await external_call()
        """
        await self.call(lambda: self._noop())
        yield

    async def _noop(self) -> None:
        pass

    def get_metrics(self) -> dict:
        """Return current breaker metrics for health checks."""
        return {
            "name": self.name,
            "state": self._state.value,
            "failures_in_window": len(self._failures),
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "last_failure_time": self._last_failure_time,
        }


class CircuitBreakerRegistry:
    """Registry for named circuit breakers."""

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}

    def get_or_create(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        **kwargs: Any,
    ) -> CircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
                **kwargs,
            )
        return self._breakers[name]

    def get(self, name: str) -> Optional[CircuitBreaker]:
        return self._breakers.get(name)

    def all_metrics(self) -> list[dict]:
        return [b.get_metrics() for b in self._breakers.values()]


circuit_registry = CircuitBreakerRegistry()
