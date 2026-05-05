import logging
import os
from typing import Any, Dict, Optional

from optirc.core.config import settings

logger = logging.getLogger(__name__)


def configure_langsmith_tracing() -> Optional[Any]:
    """Configure LangSmith tracing for the agent.

    Sets environment variables for LangChain/LangGraph native tracing.
    Call this once at application startup.
    Returns None (environment variables handle the rest).
    """
    if not settings.langsmith_tracing or not settings.langsmith_api_key:
        logger.info("LangSmith tracing is disabled or no API key configured")
        return None

    try:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project

        logger.info(
            "LangSmith tracing enabled for project: %s",
            settings.langsmith_project,
        )
        return None
    except Exception as e:
        logger.warning("Failed to configure LangSmith tracing: %s", e)
        return None


def get_langsmith_config() -> Dict[str, Any]:
    """Return config dict to pass to graph invoke for LangSmith tracing."""
    if not settings.langsmith_tracing or not settings.langsmith_api_key:
        return {}
    return {
        "configurable": {
            "langsmith_api_key": settings.langsmith_api_key,
            "langsmith_project": settings.langsmith_project,
        },
    }