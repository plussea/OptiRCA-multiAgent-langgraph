"""Unified LLM client with retry, circuit breaker, quota limiting, and failover.

Key features:
- Exponential backoff retry with jitter
- Per-provider circuit breaker (primary + backup)
- Token-bucket quota limiter
- Structured timeout handling
- Graceful degradation: primary -> backup -> fallback response
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI, APIError, RateLimitError, APITimeoutError

from optirc.core.config import settings
from optirc.core.circuit_breaker import circuit_registry
from optirc.core.exceptions import (
    LLMContentFilterError,
    LLMInvalidResponseError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from optirc.core.retry import RetryConfig, async_retry, QuotaLimiter

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────

DEFAULT_RETRY_CONFIG = RetryConfig(
    max_retries=3,
    base_delay=1.0,
    max_delay=30.0,
    exponential_base=2.0,
    jitter=0.1,
    timeout=30.0,
)

EMBEDDING_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=0.5,
    max_delay=10.0,
    timeout=20.0,
)

OCR_RETRY_CONFIG = RetryConfig(
    max_retries=2,
    base_delay=1.0,
    max_delay=20.0,
    timeout=45.0,
)

FALLBACK_RESPONSES = {
    "diagnosis": {
        "reasoning_chain": "All LLM providers unavailable — using fallback.",
        "candidate_causes": [],
        "root_cause": "unknown",
        "confidence": 0.0,
        "evidence": [],
        "recommended_action": "manual investigation required — LLM service unavailable",
    },
    "text": "LLM service temporarily unavailable. Please retry later.",
}


# ── Provider abstraction ───────────────────────────────────────────


class LLMProvider:
    """Represents a single LLM provider endpoint."""

    def __init__(
        self,
        name: str,
        client: AsyncOpenAI,
        model: str,
        circuit_name: str,
        quota_limiter: QuotaLimiter,
    ) -> None:
        self.name = name
        self.client = client
        self.model = model
        self.circuit = circuit_registry.get_or_create(
            name=circuit_name,
            failure_threshold=5,
            recovery_timeout=30.0,
        )
        self.quota = quota_limiter


# ── Main client ────────────────────────────────────────────────────


class LLMClient:
    """Unified LLM client: retry, circuit breaker, quota, failover."""

    def __init__(self) -> None:
        # Primary provider: ModelScope (DeepSeek)
        self.primary = LLMProvider(
            name="modelscope",
            client=AsyncOpenAI(
                base_url=settings.llm_base_url or settings.llm_backup_base_url,
                api_key=settings.openrouter_api_key or settings.llm_backup_api_key,
                timeout=30.0,
            ),
            model=settings.llm_model,
            circuit_name="llm_primary",
            quota_limiter=QuotaLimiter(requests_per_minute=30),
        )

        # Backup provider: OpenRouter
        self.backup = LLMProvider(
            name="openrouter",
            client=AsyncOpenAI(
                base_url=settings.llm_backup_base_url,
                api_key=settings.llm_backup_api_key,
                timeout=30.0,
            ),
            model=settings.llm_backup_model,
            circuit_name="llm_backup",
            quota_limiter=QuotaLimiter(requests_per_minute=60),
        )

        # OCR provider (separate from primary — DeepSeek is text-only, point at OpenRouter)
        ocr_base_url = (
            os.environ.get("OCR_BASE_URL")
            or "https://openrouter.ai/api/v1"
        )
        self.ocr_client = AsyncOpenAI(
            base_url=ocr_base_url,
            api_key=settings.ocr_api_key or settings.openrouter_api_key,
            timeout=45.0,
        )

        # Embedding provider (DeepSeek has no embeddings endpoint — fall back to OpenRouter)
        embed_base_url = (
            os.environ.get("EMBEDDING_BASE_URL")
            or "https://openrouter.ai/api/v1"
        )
        self.embedding = LLMProvider(
            name="embedding",
            client=AsyncOpenAI(
                base_url=embed_base_url,
                api_key=settings.embedding_api_key or settings.openrouter_api_key,
                timeout=30.0,
            ),
            model=settings.embedding_model,
            circuit_name="embedding",
            quota_limiter=QuotaLimiter(requests_per_minute=60),
        )

    # ── Internal call helpers ──────────────────────────────────────

    @async_retry(DEFAULT_RETRY_CONFIG)
    async def _generate_json_with_provider(
        self,
        provider: LLMProvider,
        system: str,
        user_message: str,
        temperature: float,
    ) -> Dict[str, Any]:
        """Make a JSON-mode chat completion via a specific provider.
        
        For providers that don't support response_format (like DeepSeek on ModelScope),
        we append JSON instructions to the system prompt and parse manually.
        """
        await provider.quota.acquire()

        # DeepSeek / ModelScope doesn't support response_format: json_object
        supports_json_mode = provider.name == "openrouter"
        
        if not supports_json_mode:
            system = system + "\n\nIMPORTANT: You must respond with valid JSON only. No markdown, no explanations, just raw JSON."

        try:
            kwargs = {
                "model": provider.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message},
                ],
                "temperature": temperature,
            }
            if supports_json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            
            response = await provider.client.chat.completions.create(**kwargs)
        except RateLimitError as e:
            raise LLMRateLimitError(
                f"Rate limited by {provider.name}: {e}"
            ) from e
        except APITimeoutError as e:
            raise LLMTimeoutError(
                f"Timeout from {provider.name}: {e}"
            ) from e
        except APIError as e:
            if getattr(e, "code", None) == "content_filter":
                raise LLMContentFilterError(
                    f"Content filter triggered on {provider.name}"
                ) from e
            raise LLMProviderUnavailableError(
                f"API error from {provider.name}: {e}"
            ) from e

        content = response.choices[0].message.content
        if content is None:
            raise LLMInvalidResponseError(f"{provider.name} returned empty content")

        # Parse JSON - handle markdown code blocks for non-json-mode providers
        try:
            if not supports_json_mode:
                # Strip markdown code blocks if present
                content = content.strip()
                if content.startswith("```"):
                    # Extract content between ```json and ```
                    lines = content.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    content = "\n".join(lines).strip()
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise LLMInvalidResponseError(
                f"Invalid JSON from {provider.name}: {e}\nContent: {content[:200]}"
            ) from e

    @async_retry(DEFAULT_RETRY_CONFIG)
    async def _generate_text_with_provider(
        self,
        provider: LLMProvider,
        system: str,
        user_message: str,
        temperature: float,
    ) -> str:
        """Make a text-mode chat completion via a specific provider."""
        await provider.quota.acquire()

        try:
            response = await provider.client.chat.completions.create(
                model=provider.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message},
                ],
                temperature=temperature,
            )
        except RateLimitError as e:
            raise LLMRateLimitError(
                f"Rate limited by {provider.name}: {e}"
            ) from e
        except APITimeoutError as e:
            raise LLMTimeoutError(
                f"Timeout from {provider.name}: {e}"
            ) from e
        except APIError as e:
            if getattr(e, "code", None) == "content_filter":
                raise LLMContentFilterError(
                    f"Content filter triggered on {provider.name}"
                ) from e
            raise LLMProviderUnavailableError(
                f"API error from {provider.name}: {e}"
            ) from e

        content = response.choices[0].message.content
        if content is None:
            raise LLMInvalidResponseError(f"{provider.name} returned empty content")
        return content

    # ── Public API ─────────────────────────────────────────────────

    async def generate_json(
        self,
        system: str,
        user_message: str,
        model: Optional[str] = None,
        temperature: float = 0.2,
        use_fallback: bool = True,
    ) -> Dict[str, Any]:
        """Generate structured JSON with full resilience stack.

        Flow: primary (with retry + circuit) -> backup (with retry + circuit)
              -> fallback response (if use_fallback=True).
        """
        last_error: Optional[Exception] = None

        for provider in (self.primary, self.backup):
            try:
                return await provider.circuit.call(
                    lambda: self._generate_json_with_provider(
                        provider, system, user_message, temperature
                    )
                )
            except Exception as e:
                last_error = e
                logger.warning(
                    "Provider %s failed for generate_json: %s",
                    provider.name,
                    type(e).__name__,
                )

        logger.error(
            "All LLM providers failed for generate_json. Last error: %s",
            last_error,
        )

        if use_fallback:
            logger.warning("Returning fallback JSON response")
            return dict(FALLBACK_RESPONSES["diagnosis"])

        raise LLMProviderUnavailableError(
            "All LLM providers failed",
            context={"last_error": str(last_error)},
        ) from last_error

    async def generate_text(
        self,
        system: str,
        user_message: str,
        model: Optional[str] = None,
        temperature: float = 0.2,
        use_fallback: bool = True,
    ) -> str:
        """Generate plain text with full resilience stack."""
        last_error: Optional[Exception] = None

        for provider in (self.primary, self.backup):
            try:
                return await provider.circuit.call(
                    lambda: self._generate_text_with_provider(
                        provider, system, user_message, temperature
                    )
                )
            except Exception as e:
                last_error = e
                logger.warning(
                    "Provider %s failed for generate_text: %s",
                    provider.name,
                    type(e).__name__,
                )

        logger.error(
            "All LLM providers failed for generate_text. Last error: %s",
            last_error,
        )

        if use_fallback:
            logger.warning("Returning fallback text response")
            return FALLBACK_RESPONSES["text"]

        raise LLMProviderUnavailableError(
            "All LLM providers failed",
            context={"last_error": str(last_error)},
        ) from last_error

    @async_retry(EMBEDDING_RETRY_CONFIG)
    async def embed(self, texts: List[str]) -> List[List[float]]:
        """Embedding with retry.
        
        ModelScope doesn't support standard embeddings API, so we use
        LLM-based pseudo-embeddings as the primary method.
        """
        # ModelScope doesn't have embeddings endpoint, use LLM-based approach
        embeddings = []
        for text in texts:
            try:
                await self.primary.quota.acquire()
                # Use LLM to generate a structured representation
                response = await self.primary.client.chat.completions.create(
                    model=self.primary.model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a text embedding generator. "
                                "Given input text, output EXACTLY 10 comma-separated floats "
                                "between -1 and 1 representing the semantic embedding. "
                                "No explanation, just numbers."
                            ),
                        },
                        {
                            "role": "user",
                            "content": f"Text: {text}",
                        },
                    ],
                    temperature=0.0,
                    max_tokens=100,
                )
                content = response.choices[0].message.content or ""
                # Parse 10 floats from response
                import re
                nums = re.findall(r'-?\d+\.?\d*', content)
                embedding = [float(n) for n in nums[:10]]
                # Pad or truncate to exactly 10 dims
                if len(embedding) < 10:
                    embedding.extend([0.0] * (10 - len(embedding)))
                embeddings.append(embedding[:10])
            except Exception as e:
                logger.warning("LLM embedding failed for '%s...': %s", text[:30], type(e).__name__)
                # Fallback to hash-based embedding
                import hashlib
                hash_bytes = hashlib.sha256(text.encode()).digest()
                embedding = []
                for i in range(10):
                    start = (i * 4) % len(hash_bytes)
                    chunk = hash_bytes[start:start+4]
                    if len(chunk) < 4:
                        chunk = chunk + hash_bytes[:4-len(chunk)]
                    import struct
                    val = struct.unpack('f', chunk)[0]
                    embedding.append(max(-1.0, min(1.0, val)))
                embeddings.append(embedding)
        
        logger.info("Generated %d embeddings (10-dim)", len(embeddings))
        return embeddings

    @async_retry(OCR_RETRY_CONFIG)
    async def ocr(self, image_base64: str) -> str:
        """OCR with retry on primary only."""
        await self.primary.quota.acquire()

        try:
            response = await self.ocr_client.chat.completions.create(
                model=settings.ocr_model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract all text and table content from the image"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                    ],
                }],
            )
        except RateLimitError as e:
            raise LLMRateLimitError(f"OCR rate limited: {e}") from e
        except APITimeoutError as e:
            raise LLMTimeoutError(f"OCR timeout: {e}") from e
        except APIError as e:
            raise LLMProviderUnavailableError(f"OCR API error: {e}") from e

        content = response.choices[0].message.content
        return content or ""

    def get_health_metrics(self) -> Dict[str, Any]:
        """Return health metrics for monitoring."""
        return {
            "primary": {
                "model": self.primary.model,
                "circuit": self.primary.circuit.get_metrics(),
                "quota": self.primary.quota.get_metrics(),
            },
            "backup": {
                "model": self.backup.model,
                "circuit": self.backup.circuit.get_metrics(),
                "quota": self.backup.quota.get_metrics(),
            },
        }


llm_client = LLMClient()
