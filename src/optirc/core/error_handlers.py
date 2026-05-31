"""FastAPI exception handlers and middleware for centralized error handling.

Provides:
- Global exception handlers for all OptiRCAError subclasses
- Request validation middleware (logging, trace_id injection)
- Structured error responses
"""

import logging
import time
import uuid
from typing import Any, Callable, Dict, Optional

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from optirc.core.exceptions import OptiRCAError

logger = logging.getLogger(__name__)


# ── Exception Handlers ─────────────────────────────────────────────


def setup_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the FastAPI app."""

    @app.exception_handler(OptiRCAError)
    async def handle_optirca_error(request: Request, exc: OptiRCAError) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", "unknown")
        logger.error(
            "[%s] OptiRCAError: code=%s status=%d detail=%s context=%s",
            trace_id,
            exc.code,
            exc.status_code,
            exc.detail,
            exc.context,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "detail": exc.detail,
                    "trace_id": trace_id,
                    **({"context": exc.context} if exc.context else {}),
                }
            },
        )

    @app.exception_handler(Exception)
    async def handle_generic_exception(request: Request, exc: Exception) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", "unknown")
        logger.exception("[%s] Unhandled exception: %s", trace_id, exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "detail": "An unexpected error occurred. Please contact support.",
                    "trace_id": trace_id,
                }
            },
        )


# ── Middleware ─────────────────────────────────────────────────────


class TraceIdMiddleware(BaseHTTPMiddleware):
    """Inject trace_id into request state for distributed tracing."""

    async def dispatch(self, request: Request, call_next: Callable) -> Any:
        trace_id = request.headers.get("x-trace-id") or str(uuid.uuid4())
        request.state.trace_id = trace_id

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.exception("[%s] Unhandled exception in middleware: %s", trace_id, exc)
            raise

        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["x-trace-id"] = trace_id
        response.headers["x-response-time-ms"] = f"{duration_ms:.2f}"

        logger.info(
            "[%s] %s %s -> %d in %.2fms",
            trace_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory rate limiter (per-IP, sliding window).

    Production should use Redis-backed rate limiting.
    """

    def __init__(
        self,
        app: Any,
        requests_per_minute: int = 60,
        burst_size: int = 10,
    ) -> None:
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.burst_size = burst_size
        self._requests: Dict[str, list[float]] = {}

    async def dispatch(self, request: Request, call_next: Callable) -> Any:
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        # Clean old entries
        window = 60.0
        self._requests[client_ip] = [
            t for t in self._requests.get(client_ip, []) if now - t < window
        ]

        if len(self._requests[client_ip]) >= self.requests_per_minute:
            logger.warning("Rate limit exceeded for %s", client_ip)
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "detail": "Too many requests. Please slow down.",
                    }
                },
            )

        self._requests[client_ip].append(now)
        return await call_next(request)


# ── Graph node error wrapper ───────────────────────────────────────


def safe_node(
    node_func: Callable,
    *,
    error_status: str = "error",
    fallback_value: Optional[Dict[str, Any]] = None,
    log_level: int = logging.WARNING,
) -> Callable:
    """Decorator that wraps a LangGraph node function with error handling.

    On exception: logs the error, returns a graceful fallback state update,
    and allows the graph to continue instead of crashing.

    Works with both sync and async node functions.

    Usage:
        @safe_node(error_status="diagnosis_error")
        async def analyze_node(state):
            ...
    """
    import asyncio
    import inspect

    is_async = inspect.iscoroutinefunction(node_func)

    async def async_wrapper(state: Dict[str, Any]) -> Dict[str, Any]:
        trace_id = state.get("session_id", "unknown")
        node_name = node_func.__name__
        try:
            return await node_func(state)
        except OptiRCAError as exc:
            logger.log(
                log_level,
                "[%s] Node %s failed with OptiRCAError: %s (code=%s)",
                trace_id,
                node_name,
                exc.detail,
                exc.code,
            )
            result = {
                "status": error_status,
                "error_message": f"[{exc.code}] {exc.detail}",
            }
            if fallback_value:
                result.update(fallback_value)
            return result
        except Exception as exc:
            logger.exception(
                "[%s] Node %s crashed with unexpected error: %s",
                trace_id,
                node_name,
                exc,
            )
            result = {
                "status": error_status,
                "error_message": f"Unexpected error in {node_name}: {type(exc).__name__}",
            }
            if fallback_value:
                result.update(fallback_value)
            return result

    def sync_wrapper(state: Dict[str, Any]) -> Dict[str, Any]:
        trace_id = state.get("session_id", "unknown")
        node_name = node_func.__name__
        try:
            return node_func(state)
        except OptiRCAError as exc:
            logger.log(
                log_level,
                "[%s] Node %s failed with OptiRCAError: %s (code=%s)",
                trace_id,
                node_name,
                exc.detail,
                exc.code,
            )
            result = {
                "status": error_status,
                "error_message": f"[{exc.code}] {exc.detail}",
            }
            if fallback_value:
                result.update(fallback_value)
            return result
        except Exception as exc:
            logger.exception(
                "[%s] Node %s crashed with unexpected error: %s",
                trace_id,
                node_name,
                exc,
            )
            result = {
                "status": error_status,
                "error_message": f"Unexpected error in {node_name}: {type(exc).__name__}",
            }
            if fallback_value:
                result.update(fallback_value)
            return result

    wrapper = async_wrapper if is_async else sync_wrapper
    wrapper.__name__ = node_func.__name__
    return wrapper
