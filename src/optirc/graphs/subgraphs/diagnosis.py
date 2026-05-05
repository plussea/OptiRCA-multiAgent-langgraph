import json
import logging
from typing import Any, Dict, List, Optional

from langgraph.graph import END, StateGraph

from optirc.core.llm_client import llm_client
from optirc.core.state import DiagnosisInternalState
from optirc.knowledge.kg_query import kg_query_service
from optirc.rag.vector_store import vector_store

logger = logging.getLogger(__name__)

DIAGNOSIS_SYSTEM_PROMPT = """You are an optical network fault diagnosis expert.
Given alarm data, retrieved knowledge documents, and knowledge graph subgraph,
reason step by step and output a JSON object with these keys:
- reasoning_chain: string explaining your thinking
- candidate_causes: list of objects, each with {cause, confidence_score, evidence}
- root_cause: the most likely root cause string
- confidence: float 0-1
- evidence: list of evidence strings
- recommended_action: brief recommended action string
"""


def build_query_node(state: DiagnosisInternalState) -> Dict[str, Any]:
    """Build query from perception summary."""
    summary = state["perception_summary"]
    alarm_type = summary.get("alarm_type", "unknown")
    device_id = summary.get("device_id", "")
    description = summary.get("description", "")
    query_text = f"Alarm: {alarm_type}, Device: {device_id}, Description: {description}"
    return {"query_text": query_text, "query_embedding": None}


async def retrieve_rag_node(state: DiagnosisInternalState) -> Dict[str, Any]:
    """Retrieve relevant documents from vector store."""
    query_text = state.get("query_text", "")
    if not query_text:
        return {"retrieved_docs": []}
    try:
        docs = await vector_store.search(query_text, top_k=5)
        return {"retrieved_docs": docs}
    except Exception as e:
        logger.warning("RAG retrieval failed: %s", e)
        return {"retrieved_docs": []}


async def retrieve_kg_node(state: DiagnosisInternalState) -> Dict[str, Any]:
    """Retrieve subgraph from knowledge graph."""
    summary = state["perception_summary"]
    topology_ids = summary.get("topology_ids", [])
    try:
        subgraph = await kg_query_service.get_subgraph(topology_ids, depth=2)
        return {"kg_subgraph": subgraph}
    except Exception as e:
        logger.warning("KG retrieval failed: %s", e)
        return {"kg_subgraph": {"nodes": [], "relationships": []}}


async def analyze_node(state: DiagnosisInternalState) -> Dict[str, Any]:
    """Use LLM to analyze and generate candidate causes."""
    summary = state["perception_summary"]
    retrieved_docs = state.get("retrieved_docs") or []
    kg_subgraph = state.get("kg_subgraph") or {}

    docs_text = "\n".join([d.get("content", "") for d in retrieved_docs])
    kg_text = json.dumps(kg_subgraph, ensure_ascii=False, indent=2)

    user_message = f"""Perception Summary:
{json.dumps(summary, ensure_ascii=False, indent=2)}

Retrieved Documents:
{docs_text}

Knowledge Graph Subgraph:
{kg_text}
"""
    try:
        result = await llm_client.generate_json(
            system=DIAGNOSIS_SYSTEM_PROMPT,
            user_message=user_message,
            temperature=0.2,
        )
        return {
            "candidate_causes": result.get("candidate_causes", []),
            "reasoning_chain": result.get("reasoning_chain", ""),
            "llm_raw_output": json.dumps(result, ensure_ascii=False),
        }
    except Exception as e:
        logger.warning("LLM diagnosis analysis failed: %s", e)
        return {
            "candidate_causes": [],
            "reasoning_chain": "",
            "llm_raw_output": "",
        }


def finalize_node(state: DiagnosisInternalState) -> Dict[str, Any]:
    """Finalize diagnosis result."""
    candidate_causes = state.get("candidate_causes") or []
    if not candidate_causes:
        return {
            "root_cause": "unknown",
            "confidence": 0.0,
            "evidence": [],
            "recommended_action": "manual investigation required",
        }

    # Pick best candidate
    best = max(candidate_causes, key=lambda x: x.get("confidence_score", 0))
    return {
        "root_cause": best.get("cause", "unknown"),
        "confidence": best.get("confidence_score", 0.0),
        "evidence": best.get("evidence", []),
        "recommended_action": best.get("recommended_action", ""),
    }


def build_diagnosis_subgraph() -> StateGraph:
    """Build diagnosis subgraph."""
    builder = StateGraph(DiagnosisInternalState)
    builder.add_node("build_query", build_query_node)
    builder.add_node("retrieve_rag", retrieve_rag_node)
    builder.add_node("retrieve_kg", retrieve_kg_node)
    builder.add_node("analyze", analyze_node)
    builder.add_node("finalize", finalize_node)

    builder.set_entry_point("build_query")
    builder.add_edge("build_query", "retrieve_rag")
    builder.add_edge("build_query", "retrieve_kg")
    builder.add_edge("retrieve_rag", "analyze")
    builder.add_edge("retrieve_kg", "analyze")
    builder.add_edge("analyze", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile()
