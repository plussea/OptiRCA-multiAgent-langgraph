"""Unified exception hierarchy for OptiRCAgent.

All domain-specific exceptions inherit from OptiRCAError.
This enables centralized error handling, structured logging, and client-friendly responses.
"""

from typing import Any, Dict, Optional


class OptiRCAError(Exception):
    """Base exception for all OptiRCA domain errors.

    Attributes:
        code: Machine-readable error code (e.g. "LLM_TIMEOUT").
        status_code: HTTP status code to return from API layer.
        detail: Human-readable error message.
        context: Arbitrary structured data for debugging / tracing.
    """

    code: str = "INTERNAL_ERROR"
    status_code: int = 500

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        status_code: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.detail = message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.context = context or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_code": self.code,
            "detail": self.detail,
            "context": self.context,
        }


# ── LLM / Model errors ──────────────────────────────────────────────


class LLMError(OptiRCAError):
    """Base class for LLM-related failures."""

    code = "LLM_ERROR"
    status_code = 502


class LLMTimeoutError(LLMError):
    """LLM request exceeded configured timeout."""

    code = "LLM_TIMEOUT"
    status_code = 504


class LLMRateLimitError(LLMError):
    """LLM provider returned 429 or quota exhausted."""

    code = "LLM_RATE_LIMIT"
    status_code = 429


class LLMContentFilterError(LLMError):
    """LLM output blocked by content filter."""

    code = "LLM_CONTENT_FILTER"
    status_code = 422


class LLMInvalidResponseError(LLMError):
    """LLM returned malformed JSON or unexpected schema."""

    code = "LLM_INVALID_RESPONSE"
    status_code = 502


class LLMProviderUnavailableError(LLMError):
    """All configured LLM providers failed (primary + backup)."""

    code = "LLM_PROVIDER_UNAVAILABLE"
    status_code = 503


class LLMCircuitOpenError(LLMError):
    """Circuit breaker is OPEN — LLM calls are fast-failing."""

    code = "LLM_CIRCUIT_OPEN"
    status_code = 503


# ── Knowledge / RAG errors ─────────────────────────────────────────


class KnowledgeBaseError(OptiRCAError):
    """Neo4j or vector store failure."""

    code = "KNOWLEDGE_BASE_ERROR"
    status_code = 503


class VectorStoreError(KnowledgeBaseError):
    """ChromaDB query or indexing failure."""

    code = "VECTOR_STORE_ERROR"
    status_code = 503


class KnowledgeGraphError(KnowledgeBaseError):
    """Neo4j query or connection failure."""

    code = "KNOWLEDGE_GRAPH_ERROR"
    status_code = 503


# ── Data / Ingestion errors ────────────────────────────────────────


class IngestionError(OptiRCAError):
    """CSV / file parsing failure."""

    code = "INGESTION_ERROR"
    status_code = 400


class FileValidationError(IngestionError):
    """Uploaded file failed security or format validation."""

    code = "FILE_VALIDATION_ERROR"
    status_code = 400


# ── Session / State errors ─────────────────────────────────────────


class SessionError(OptiRCAError):
    """Session lifecycle or state access failure."""

    code = "SESSION_ERROR"
    status_code = 404


class SessionNotFoundError(SessionError):
    """Requested session_id does not exist."""

    code = "SESSION_NOT_FOUND"
    status_code = 404


class InvalidStateTransitionError(SessionError):
    """Graph attempted an illegal state transition."""

    code = "INVALID_STATE_TRANSITION"
    status_code = 409


# ── Human-in-the-loop errors ───────────────────────────────────────


class HITLError(OptiRCAError):
    """Human review workflow failure."""

    code = "HITL_ERROR"
    status_code = 400


class HITLTimeoutError(HITLError):
    """Human decision not received within SLA."""

    code = "HITL_TIMEOUT"
    status_code = 408


class NoActiveInterruptError(HITLError):
    """Attempted to submit decision when no interrupt is active."""

    code = "NO_ACTIVE_INTERRUPT"
    status_code = 409
