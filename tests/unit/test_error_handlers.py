"""Tests for error handlers and middleware."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from optirc.core.error_handlers import (
    RateLimitMiddleware,
    TraceIdMiddleware,
    setup_exception_handlers,
)
from optirc.core.exceptions import OptiRCAError, SessionNotFoundError


class TestExceptionHandlers:
    @pytest.fixture
    def app(self):
        return FastAPI()

    def test_setup_exception_handlers(self, app):
        setup_exception_handlers(app)
        # Should not raise

    @pytest.mark.asyncio
    async def test_optirca_error_handler(self, app):
        setup_exception_handlers(app)
        # Find the handler
        handler = None
        for exc_class, h in app.exception_handlers.items():
            if exc_class == OptiRCAError:
                handler = h
                break
        assert handler is not None

    @pytest.mark.asyncio
    async def test_generic_exception_handler(self, app):
        setup_exception_handlers(app)
        handler = None
        for exc_class, h in app.exception_handlers.items():
            if exc_class == Exception:
                handler = h
                break
        assert handler is not None


class TestTraceIdMiddleware:
    @pytest.mark.asyncio
    async def test_injects_trace_id(self):
        app = FastAPI()
        middleware = TraceIdMiddleware(app)

        mock_request = MagicMock()
        mock_request.headers = {}
        mock_request.client = MagicMock(host="127.0.0.1")
        mock_request.method = "GET"
        mock_request.url.path = "/test"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}

        async def call_next(request):
            assert hasattr(request.state, "trace_id")
            assert len(request.state.trace_id) == 36  # UUID length
            return mock_response

        response = await middleware.dispatch(mock_request, call_next)
        assert "x-trace-id" in response.headers
        assert "x-response-time-ms" in response.headers

    @pytest.mark.asyncio
    async def test_preserves_existing_trace_id(self):
        app = FastAPI()
        middleware = TraceIdMiddleware(app)

        mock_request = MagicMock()
        mock_request.headers = {"x-trace-id": "existing-trace-id"}
        mock_request.client = MagicMock(host="127.0.0.1")
        mock_request.method = "GET"
        mock_request.url.path = "/test"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}

        async def call_next(request):
            assert request.state.trace_id == "existing-trace-id"
            return mock_response

        response = await middleware.dispatch(mock_request, call_next)
        assert response.headers["x-trace-id"] == "existing-trace-id"


class TestRateLimitMiddleware:
    @pytest.mark.asyncio
    async def test_allows_requests_within_limit(self):
        app = FastAPI()
        middleware = RateLimitMiddleware(app, requests_per_minute=10, burst_size=5)

        mock_request = MagicMock()
        mock_request.client = MagicMock(host="127.0.0.1")

        mock_response = MagicMock()

        async def call_next(request):
            return mock_response

        # Should allow multiple requests
        for _ in range(5):
            response = await middleware.dispatch(mock_request, call_next)
            assert response is mock_response

    @pytest.mark.asyncio
    async def test_blocks_excessive_requests(self):
        app = FastAPI()
        middleware = RateLimitMiddleware(app, requests_per_minute=1, burst_size=1)

        mock_request = MagicMock()
        mock_request.client = MagicMock(host="127.0.0.1")

        async def call_next(request):
            return MagicMock()

        # First request should pass
        response1 = await middleware.dispatch(mock_request, call_next)
        assert isinstance(response1, MagicMock)

        # Second request should be rate limited
        response2 = await middleware.dispatch(mock_request, call_next)
        assert isinstance(response2, JSONResponse)
        assert response2.status_code == status.HTTP_429_TOO_MANY_REQUESTS
