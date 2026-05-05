import json
import logging
import os
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from optirc.core.config import settings

logger = logging.getLogger(__name__)


def _get_langsmith_callbacks() -> List[Any]:
    """Get LangSmith callbacks if tracing is configured."""
    if not settings.langsmith_tracing or not settings.langsmith_api_key:
        return []
    try:
        from langsmith.traceable import traceable
        from langchain_core.callbacks import CallbackManager
        return []
    except Exception:
        return []


class LLMClient:
    """Unified LLM client: OpenAI API format, supports primary/backup dual-backend auto-failover."""

    def __init__(self) -> None:
        callbacks = _get_langsmith_callbacks()
        self._callback_kwargs = {"callbacks": callbacks} if callbacks else {}

        # Primary client: OpenRouter
        self.primary = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.openrouter_api_key,
        )
        self.primary_model = settings.llm_model

        # Backup client: ModelScope
        self.backup = AsyncOpenAI(
            base_url=settings.llm_backup_base_url,
            api_key=settings.llm_backup_api_key,
        )
        self.backup_model = settings.llm_backup_model

    async def generate_json(
        self,
        system: str,
        user_message: str,
        model: Optional[str] = None,
        temperature: float = 0.2,
    ) -> Dict[str, Any]:
        """Primary model first, auto-failover to backup on exception."""

        async def _call(client: AsyncOpenAI, model_name: str) -> Dict[str, Any]:
            response = await client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message},
                ],
                temperature=temperature,
                response_format={"type": "json_object"},
                **self._callback_kwargs,
            )
            content = response.choices[0].message.content
            if content is None:
                raise ValueError("LLM returned empty content")
            return json.loads(content)

        try:
            return await _call(self.primary, model or self.primary_model)
        except Exception as e:
            logger.warning("Primary LLM failed (%s), falling back to backup", e)
            return await _call(self.backup, self.backup_model)

    async def generate_text(
        self,
        system: str,
        user_message: str,
        model: Optional[str] = None,
        temperature: float = 0.2,
    ) -> str:
        """Generate plain text response with failover."""

        async def _call(client: AsyncOpenAI, model_name: str) -> str:
            response = await client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message},
                ],
                temperature=temperature,
                **self._callback_kwargs,
            )
            content = response.choices[0].message.content
            if content is None:
                raise ValueError("LLM returned empty content")
            return content

        try:
            return await _call(self.primary, model or self.primary_model)
        except Exception as e:
            logger.warning("Primary LLM failed (%s), falling back to backup", e)
            return await _call(self.backup, self.backup_model)

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """Embedding interface using configured EMBEDDING_MODEL."""
        response = await self.primary.embeddings.create(
            model=settings.embedding_model,
            input=texts,
            **self._callback_kwargs,
        )
        return [item.embedding for item in response.data]

    async def ocr(self, image_base64: str) -> str:
        """OCR interface using configured OCR_MODEL (via vision API)."""
        response = await self.primary.chat.completions.create(
            model=settings.ocr_model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract all text and table content from the image"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                ],
            }],
            **self._callback_kwargs,
        )
        content = response.choices[0].message.content
        if content is None:
            return ""
        return content


llm_client = LLMClient()