from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/omniops"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # LLM Primary (OpenRouter)
    llm_provider: str = "openrouter"
    llm_model: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
    openrouter_api_key: str = ""

    # LLM Backup (ModelScope)
    llm_backup_provider: str = "openrouter"
    llm_backup_model: str = "MiniMax/MiniMax-M2.7"
    llm_backup_api_key: str = ""
    llm_backup_base_url: str = "https://api-inference.modelscope.cn/v1"

    # OCR
    ocr_api_key: str = ""
    ocr_model: str = "baidu/qianfan-ocr-fast:free"

    # Embedding
    embedding_api_key: str = ""
    embedding_model: str = "nvidia/llama-nemotron-embed-vl-1b-v2:free"

    # Vector Database
    chroma_persistent_path: str = "./data/chroma"
    chroma_collection: str = "omniops_knowledge"

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"

    # Application
    omniops_api_host: str = "0.0.0.0"
    omniops_api_port: int = 8000
    omniops_api_debug: bool = True
    omniops_upload_dir: str = "./uploads"
    omniops_max_upload_size: int = 10485760
    log_level: str = "INFO"

    # HITL
    hitl_timeout_seconds: int = 600
    hitl_escalation_webhook_url: Optional[str] = None

    # LangSmith Tracing
    langsmith_api_key: Optional[str] = None
    langsmith_project: str = "optirc-agent"
    langsmith_tracing: bool = False


settings = Settings()
