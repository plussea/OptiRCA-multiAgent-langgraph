import logging
import os
from typing import Any, Dict, List, Optional

from optirc.core.config import settings
from optirc.core.llm_client import llm_client

logger = logging.getLogger(__name__)


class VectorStore:
    """ChromaDB vector store wrapper."""

    def __init__(self) -> None:
        self._client: Optional[Any] = None
        self._collection: Optional[Any] = None
        self._initialized = False

    def _init(self) -> None:
        if self._initialized:
            return
        try:
            import chromadb
            self._client = chromadb.PersistentClient(path=settings.chroma_persistent_path)
            self._collection = self._client.get_or_create_collection(
                name=settings.chroma_collection
            )
            self._initialized = True
            logger.info("ChromaDB initialized at %s", settings.chroma_persistent_path)
        except Exception as e:
            logger.warning("ChromaDB init failed: %s", e)
            self._client = None
            self._collection = None
            self._initialized = True

    async def search(
        self,
        query: str,
        top_k: int = 5,
        filter_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search vector store by query text."""
        self._init()
        if self._collection is None:
            return []
        try:
            embeddings = await llm_client.embed([query])
            where = {"type": filter_type} if filter_type else None
            results = self._collection.query(
                query_embeddings=embeddings,
                n_results=top_k,
                where=where,
            )
            docs = []
            for i, doc_list in enumerate(results.get("documents", [])):
                for j, doc in enumerate(doc_list):
                    meta = results.get("metadatas", [[{}] * len(doc_list)])[i][j]
                    docs.append({
                        "content": doc,
                        "metadata": meta,
                    })
            return docs
        except Exception as e:
            logger.warning("Vector search failed: %s", e)
            return []

    def add_documents(
        self,
        documents: List[str],
        metadatas: List[Dict[str, Any]],
        ids: Optional[List[str]] = None,
    ) -> None:
        """Add documents to vector store."""
        self._init()
        if self._collection is None:
            return
        try:
            if ids is None:
                ids = [str(i) for i in range(len(documents))]
            self._collection.add(
                documents=documents,
                metadatas=metadatas,
                ids=ids,
            )
            logger.info("Added %d documents to vector store", len(documents))
        except Exception as e:
            logger.warning("Failed to add documents: %s", e)


vector_store = VectorStore()
