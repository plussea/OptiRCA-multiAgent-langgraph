import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from langgraph.graph import END, StateGraph

from optirc.core.llm_client import llm_client
from optirc.core.state import ClosureInternalState
from optirc.knowledge.kg_query import kg_query_service
from optirc.rag.vector_store import vector_store

logger = logging.getLogger(__name__)

KNOWLEDGE_EXTRACTION_PROMPT = """Extract structured knowledge from this case.
Output JSON with:
- knowledge_items: list of {category, content, tags}
"""


def extract_knowledge_node(state: ClosureInternalState) -> Dict[str, Any]:
    """Extract structured knowledge from case."""
    full_case = state["full_case"]
    items: List[Dict[str, Any]] = []

    diagnosis = full_case.get("diagnosis", {})
    planning = full_case.get("planning", {})

    if diagnosis.get("root_cause"):
        items.append({
            "category": "root_cause",
            "content": diagnosis["root_cause"],
            "tags": ["diagnosis"],
        })
    if planning.get("final_plan"):
        items.append({
            "category": "solution",
            "content": json.dumps(planning["final_plan"], ensure_ascii=False),
            "tags": ["planning"],
        })

    return {"extracted_knowledge": items}


async def store_vector_node(state: ClosureInternalState) -> Dict[str, Any]:
    """Store knowledge to vector database."""
    knowledge = state.get("extracted_knowledge") or []
    if not knowledge:
        return {"stored_to_vector_db": False}

    try:
        docs = [json.dumps(k, ensure_ascii=False) for k in knowledge]
        metadatas = [{"category": k.get("category", "")} for k in knowledge]
        vector_store.add_documents(docs, metadatas)
        return {"stored_to_vector_db": True}
    except Exception as e:
        logger.warning("Vector store failed: %s", e)
        return {"stored_to_vector_db": False}


async def store_graph_node(state: ClosureInternalState) -> Dict[str, Any]:
    """Store knowledge to graph database."""
    full_case = state["full_case"]
    session_id = state["session_id"]
    diagnosis = full_case.get("diagnosis", {})
    root_cause = diagnosis.get("root_cause", "")
    topology_ids = full_case.get("perception", {}).get("topology_ids", [])

    if not root_cause:
        return {"stored_to_graph_db": False}

    try:
        await kg_query_service.add_case_knowledge(
            session_id=session_id,
            root_cause=root_cause,
            device_ids=topology_ids,
        )
        return {"stored_to_graph_db": True}
    except Exception as e:
        logger.warning("Graph store failed: %s", e)
        return {"stored_to_graph_db": False}


def summarize_node(state: ClosureInternalState) -> Dict[str, Any]:
    """Generate closure summary."""
    full_case = state["full_case"]
    diagnosis = full_case.get("diagnosis", {})
    planning = full_case.get("planning", {})
    human = full_case.get("human_review", {})

    summary = (
        f"Case {state['session_id']}: "
        f"Root cause={diagnosis.get('root_cause', 'N/A')}, "
        f"Plan steps={len(planning.get('final_plan', {}).get('steps', []))}, "
        f"Decision={human.get('decision', 'N/A')}"
    )
    return {"closure_summary": summary}


def build_closure_subgraph() -> StateGraph:
    """Build closure subgraph."""
    builder = StateGraph(ClosureInternalState)
    builder.add_node("extract_knowledge", extract_knowledge_node)
    builder.add_node("store_vector", store_vector_node)
    builder.add_node("store_graph", store_graph_node)
    builder.add_node("summarize", summarize_node)

    builder.set_entry_point("extract_knowledge")
    builder.add_edge("extract_knowledge", "store_vector")
    builder.add_edge("extract_knowledge", "store_graph")
    builder.add_edge("store_vector", "summarize")
    builder.add_edge("store_graph", "summarize")
    builder.add_edge("summarize", END)

    return builder.compile()
