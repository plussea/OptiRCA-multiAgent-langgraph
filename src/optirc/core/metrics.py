"""Prometheus metrics collection for OptiRCAgent.

Exposes key metrics for monitoring:
- Pipeline execution latency and throughput
- LLM call latency, success rate, token usage
- Circuit breaker state changes
- Database connection pool stats
- Error rates by category
"""

import logging
import time
from contextlib import contextmanager
from typing import Any, Dict, Generator, Optional

logger = logging.getLogger(__name__)

# Try to import prometheus_client, fallback to no-op if not available
try:
    from prometheus_client import Counter, Gauge, Histogram, Info, generate_latest, CONTENT_TYPE_LATEST
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.info("prometheus_client not installed, metrics will be no-op")


class MetricsCollector:
    """Centralized metrics collector with Prometheus integration."""

    def __init__(self) -> None:
        self._enabled = PROMETHEUS_AVAILABLE
        if not self._enabled:
            return

        # Application info
        self._app_info = Info("optirc_app", "OptiRCAgent application info")
        self._app_info.info({"version": "0.1.0", "langgraph_version": "0.2.50"})

        # Pipeline metrics
        self._pipeline_latency = Histogram(
            "optirc_pipeline_duration_seconds",
            "Pipeline execution latency",
            ["status"],
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0],
        )
        self._pipeline_total = Counter(
            "optirc_pipeline_total",
            "Total pipeline executions",
            ["status"],
        )
        self._node_latency = Histogram(
            "optirc_node_duration_seconds",
            "Node execution latency",
            ["node_name", "status"],
            buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
        )

        # LLM metrics
        self._llm_latency = Histogram(
            "optirc_llm_duration_seconds",
            "LLM call latency",
            ["provider", "operation", "status"],
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
        )
        self._llm_tokens = Counter(
            "optirc_llm_tokens_total",
            "Total LLM tokens used",
            ["provider", "operation"],
        )
        self._llm_calls = Counter(
            "optirc_llm_calls_total",
            "Total LLM calls",
            ["provider", "operation", "status"],
        )

        # Circuit breaker metrics
        self._circuit_state = Gauge(
            "optirc_circuit_breaker_state",
            "Circuit breaker state (0=closed, 1=half-open, 2=open)",
            ["name"],
        )
        self._circuit_failures = Counter(
            "optirc_circuit_breaker_failures_total",
            "Circuit breaker recorded failures",
            ["name"],
        )

        # Error metrics
        self._errors = Counter(
            "optirc_errors_total",
            "Total errors by category",
            ["category", "code"],
        )

        # Concurrency metrics
        self._active_pipelines = Gauge(
            "optirc_active_pipelines",
            "Currently running pipelines",
        )
        self._pending_pipelines = Gauge(
            "optirc_pending_pipelines",
            "Pipelines waiting for semaphore",
        )

        # Database metrics
        self._db_pool_size = Gauge(
            "optirc_db_pool_size",
            "Database connection pool size",
        )
        self._db_pool_available = Gauge(
            "optirc_db_pool_available",
            "Available database connections",
        )

    @contextmanager
    def pipeline_timer(self, status: str = "success") -> Generator[None, None, None]:
        """Context manager to time pipeline execution."""
        if not self._enabled:
            yield
            return

        start = time.time()
        try:
            yield
        except Exception:
            status = "error"
            raise
        finally:
            duration = time.time() - start
            self._pipeline_latency.labels(status=status).observe(duration)
            self._pipeline_total.labels(status=status).inc()

    @contextmanager
    def node_timer(self, node_name: str) -> Generator[None, None, None]:
        """Context manager to time node execution."""
        if not self._enabled:
            yield
            return

        start = time.time()
        status = "success"
        try:
            yield
        except Exception:
            status = "error"
            raise
        finally:
            duration = time.time() - start
            self._node_latency.labels(node_name=node_name, status=status).observe(duration)

    @contextmanager
    def llm_timer(self, provider: str, operation: str) -> Generator[None, None, None]:
        """Context manager to time LLM calls."""
        if not self._enabled:
            yield
            return

        start = time.time()
        status = "success"
        try:
            yield
        except Exception:
            status = "error"
            raise
        finally:
            duration = time.time() - start
            self._llm_latency.labels(provider=provider, operation=operation, status=status).observe(duration)
            self._llm_calls.labels(provider=provider, operation=operation, status=status).inc()

    def record_llm_tokens(self, provider: str, operation: str, tokens: int) -> None:
        """Record LLM token usage."""
        if not self._enabled:
            return
        self._llm_tokens.labels(provider=provider, operation=operation).inc(tokens)

    def record_circuit_state(self, name: str, state: str) -> None:
        """Record circuit breaker state (0=closed, 1=half-open, 2=open)."""
        if not self._enabled:
            return
        state_map = {"closed": 0, "half_open": 1, "open": 2}
        self._circuit_state.labels(name=name).set(state_map.get(state, 0))

    def record_circuit_failure(self, name: str) -> None:
        """Record circuit breaker failure."""
        if not self._enabled:
            return
        self._circuit_failures.labels(name=name).inc()

    def record_error(self, category: str, code: str) -> None:
        """Record an error."""
        if not self._enabled:
            return
        self._errors.labels(category=category, code=code).inc()

    def set_active_pipelines(self, count: int) -> None:
        """Set active pipeline count."""
        if not self._enabled:
            return
        self._active_pipelines.set(count)

    def set_pending_pipelines(self, count: int) -> None:
        """Set pending pipeline count."""
        if not self._enabled:
            return
        self._pending_pipelines.set(count)

    def set_db_pool_stats(self, size: int, available: int) -> None:
        """Set database pool statistics."""
        if not self._enabled:
            return
        self._db_pool_size.set(size)
        self._db_pool_available.set(available)

    def get_prometheus_metrics(self) -> tuple[bytes, str]:
        """Get Prometheus-formatted metrics."""
        if not self._enabled:
            return b"# Prometheus metrics disabled\n", "text/plain"
        return generate_latest(), CONTENT_TYPE_LATEST  # type: ignore[possibly-unbound]


# Global metrics instance
metrics = MetricsCollector()
