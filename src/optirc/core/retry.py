"""Retry decorator with exponential backoff, jitter, and timeout.

Supports configurable retry strategies for async functions.
"""

import asyncio
import logging
import random
from functools import wraps
from typing import Any, Callable, Optional, Type, Union

from optirc.core.exceptions import (
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMProviderUnavailableError,
)

logger = logging.getLogger(__name__)


class RetryConfig:
    """Configuration for retry behavior.

    Args:
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay between retries (seconds).
        max_delay: Maximum delay cap (seconds).
        exponential_base: Multiplier for exponential backoff.
        jitter: Random jitter factor (0-1) to avoid thundering herd.
        timeout: Per-attempt timeout in seconds (None = no timeout).
        retryable_exceptions: Exception types that trigger retry.
        on_retry: Optional callback(exc, attempt) for logging/metrics.
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: float = 0.1,
        timeout: Optional[float] = 30.0,
        retryable_exceptions: Optional[tuple[Type[BaseException], ...]] = None,
        on_retry: Optional[Callable[[BaseException, int], None]] = None,
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.timeout = timeout
        self.retryable_exceptions = retryable_exceptions or (
            LLMRateLimitError,
            LLMTimeoutError,
            LLMProviderUnavailableError,
            TimeoutError,
            ConnectionError,
            asyncio.TimeoutError,
        )
        self.on_retry = on_retry

    def compute_delay(self, attempt: int) -> float:
        """Compute delay for a given attempt with exponential backoff + jitter."""
        delay = self.base_delay * (self.exponential_base ** attempt)
        delay = min(delay, self.max_delay)
        if self.jitter > 0:
            jitter_amount = delay * self.jitter * random.uniform(-1, 1)
            delay = max(0, delay + jitter_amount)
        return delay


def async_retry(config: Optional[RetryConfig] = None):
    """Decorator that adds retry logic to an async function.

    Usage:
        @async_retry(RetryConfig(max_retries=3, timeout=10))
        async def fetch_data():
            ...
    """
    cfg = config or RetryConfig()

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Optional[BaseException] = None

            for attempt in range(cfg.max_retries + 1):
                try:
                    if cfg.timeout is not None:
                        return await asyncio.wait_for(
                            func(*args, **kwargs),
                            timeout=cfg.timeout,
                        )
                    return await func(*args, **kwargs)

                except asyncio.TimeoutError as e:
                    last_exception = LLMTimeoutError(
                        f"Operation timed out after {cfg.timeout}s (attempt {attempt + 1}/{cfg.max_retries + 1})"
                    )
                    if attempt == cfg.max_retries:
                        raise last_exception
                    if cfg.on_retry:
                        cfg.on_retry(last_exception, attempt)

                except Exception as e:
                    last_exception = e
                    if not isinstance(e, cfg.retryable_exceptions):
                        raise

                    if attempt == cfg.max_retries:
                        logger.warning(
                            "Function %s failed after %d attempts: %s",
                            func.__name__,
                            cfg.max_retries + 1,
                            e,
                        )
                        raise

                    if cfg.on_retry:
                        cfg.on_retry(e, attempt)

                    delay = cfg.compute_delay(attempt)
                    logger.info(
                        "Retrying %s in %.2fs (attempt %d/%d): %s",
                        func.__name__,
                        delay,
                        attempt + 1,
                        cfg.max_retries,
                        e,
                    )
                    await asyncio.sleep(delay)

            # Should never reach here
            raise last_exception or RuntimeError("Unexpected retry exhaustion")

        return wrapper

    return decorator


class QuotaLimiter:
    """Simple token-bucket quota limiter for LLM API calls.

    Prevents runaway costs by limiting requests per minute.
    """

    def __init__(
        self,
        requests_per_minute: int = 60,
        tokens_per_minute: Optional[int] = None,
    ) -> None:
        self.requests_per_minute = requests_per_minute
        self.tokens_per_minute = tokens_per_minute
        self._request_tokens: float = requests_per_minute
        self._last_update = asyncio.get_event_loop().time()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> None:
        """Acquire permission to make a request. Blocks if quota exceeded."""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            elapsed = now - self._last_update
            self._last_update = now

            # Replenish tokens
            self._request_tokens = min(
                self.requests_per_minute,
                self._request_tokens + elapsed * (self.requests_per_minute / 60.0),
            )

            if self._request_tokens < tokens:
                wait_time = (tokens - self._request_tokens) * (60.0 / self.requests_per_minute)
                logger.warning("Quota limiter: waiting %.2fs for token replenishment", wait_time)
                await asyncio.sleep(wait_time)
                self._request_tokens = 0
            else:
                self._request_tokens -= tokens

    def get_metrics(self) -> dict:
        return {
            "requests_per_minute": self.requests_per_minute,
            "available_tokens": self._request_tokens,
        }
