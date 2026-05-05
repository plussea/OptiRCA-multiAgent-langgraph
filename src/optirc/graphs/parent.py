import logging
from typing import Any, Dict

from langgraph.graph import END, StateGraph
from langgraph.checkpoint.memory import MemorySaver

try:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

from optirc.core.config import settings
from optirc.core.state import (
    ClosureInternalState,
    DiagnosisInternalState,
    DiagnosisValidationInternalState,
    HumanReviewInternalState,
    OverallState,
    PerceptionInternalState,
    PlanningInternalState,
    SolutionValidationInternalState,
)
from optirc.graphs.subgraphs.closure import build_closure_subgraph
from optirc.graphs.subgraphs.diagnosis import build_diagnosis_subgraph
from optirc.graphs.subgraphs.diagnosis_validation import build_diagnosis_validation_subgraph
from optirc.graphs.subgraphs.human_review import build_human_review_subgraph
from optirc.graphs.subgraphs.perception import build_perception_subgraph
from optirc.graphs.subgraphs.planning import build_planning_subgraph
from optirc.graphs.subgraphs.solution_validation import build_solution_validation_subgraph
from optirc.memory.db_store import db_store
from optirc.memory.redis_store import redis_store

logger = logging.getLogger(__name__)

# Subgraph instances
perception_subgraph = build_perception_subgraph()
diagnosis_subgraph = build_diagnosis_subgraph()
diagnosis_validation_subgraph = build_diagnosis_validation_subgraph()
planning_subgraph = build_planning_subgraph()
solution_validation_subgraph = build_solution_validation_subgraph()
human_review_subgraph = build_human_review_subgraph()
closure_subgraph = build_closure_subgraph()


async def perception_node(state: OverallState) -> Dict[str, Any]:
    """Wrapper for perception subgraph."""
    sub_input: PerceptionInternalState = {
        "raw_input": state["raw_input"],
        "detected_encoding": None,
        "raw_rows": None,
        "normalized_headers": None,
        "topology_ids": None,
        "ocr_text": None,
        "perception_summary": None,
    }
    result = await perception_subgraph.ainvoke(sub_input)
    return {
        "perception_result": result.get("perception_summary"),
        "status": "perceived",
    }


async def diagnosis_node(state: OverallState) -> Dict[str, Any]:
    """Wrapper for diagnosis subgraph."""
    sub_input: DiagnosisInternalState = {
        "perception_summary": state["perception_result"] or {},
        "query_text": None,
        "query_embedding": None,
        "retrieved_docs": None,
        "kg_subgraph": None,
        "candidate_causes": None,
        "reasoning_chain": None,
        "llm_raw_output": None,
        "root_cause": None,
        "confidence": None,
        "evidence": None,
        "recommended_action": None,
    }
    result = await diagnosis_subgraph.ainvoke(sub_input)
    return {
        "diagnosis_result": {
            "root_cause": result.get("root_cause"),
            "confidence": result.get("confidence"),
            "evidence": result.get("evidence"),
            "recommended_action": result.get("recommended_action"),
        },
        "status": "diagnosed",
    }


async def diagnosis_validation_node(state: OverallState) -> Dict[str, Any]:
    """Wrapper for diagnosis validation subgraph."""
    sub_input: DiagnosisValidationInternalState = {
        "diagnosis_result": state["diagnosis_result"] or {},
        "confidence_threshold": 0.6,
        "evidence_completeness_score": None,
        "llm_revalidation_output": None,
        "validation_passed": None,
        "validation_notes": None,
        "suggested_action": None,
    }
    result = await diagnosis_validation_subgraph.ainvoke(sub_input)
    return {
        "diagnosis_validation_result": {
            "validation_passed": result.get("validation_passed"),
            "validation_notes": result.get("validation_notes"),
            "suggested_action": result.get("suggested_action"),
        },
        "status": "diagnosis_validated",
    }


async def planning_node(state: OverallState) -> Dict[str, Any]:
    """Wrapper for planning subgraph."""
    sub_input: PlanningInternalState = {
        "diagnosis_result": state["diagnosis_result"] or {},
        "diagnosis_validation": state["diagnosis_validation_result"] or {},
        "retrieved_sops": None,
        "candidate_plans": None,
        "risk_assessment": None,
        "final_plan": None,
        "rollback_procedure": None,
    }
    result = await planning_subgraph.ainvoke(sub_input)
    return {
        "planning_result": {
            "final_plan": result.get("final_plan"),
            "rollback_procedure": result.get("rollback_procedure"),
        },
        "status": "planned",
    }


async def solution_validation_node(state: OverallState) -> Dict[str, Any]:
    """Wrapper for solution validation subgraph."""
    sub_input: SolutionValidationInternalState = {
        "planning_result": state["planning_result"] or {},
        "diagnosis_result": state["diagnosis_result"] or {},
        "consistency_matrix": None,
        "feasibility_score": None,
        "resource_match_check": None,
        "llm_evaluation_output": None,
        "solution_valid": None,
        "risk_level": None,
        "validation_notes": None,
        "needs_replan": None,
    }
    result = await solution_validation_subgraph.ainvoke(sub_input)
    return {
        "solution_validation_result": {
            "solution_valid": result.get("solution_valid"),
            "risk_level": result.get("risk_level"),
            "validation_notes": result.get("validation_notes"),
            "needs_replan": result.get("needs_replan"),
        },
        "status": "solution_validated",
    }


async def human_review_node(state: OverallState) -> Dict[str, Any]:
    """Wrapper for human review subgraph."""
    sub_input: HumanReviewInternalState = {
        "session_id": state["session_id"],
        "planning_result": state["planning_result"] or {},
        "solution_validation": state["solution_validation_result"] or {},
        "diagnosis_result": state["diagnosis_result"] or {},
        "review_package": None,
        "decision": None,
        "reviewer_notes": None,
        "approved_at": None,
    }
    result = await human_review_subgraph.ainvoke(sub_input)
    return {
        "human_review_result": {
            "decision": result.get("decision"),
            "reviewer_notes": result.get("reviewer_notes"),
            "approved_at": result.get("approved_at"),
        },
        "status": "human_reviewed",
        "pending_human": False,
        "human_decision": result.get("decision"),
    }


async def closure_node(state: OverallState) -> Dict[str, Any]:
    """Wrapper for closure subgraph."""
    sub_input: ClosureInternalState = {
        "session_id": state["session_id"],
        "full_case": {
            "perception": state.get("perception_result") or {},
            "diagnosis": state.get("diagnosis_result") or {},
            "diagnosis_validation": state.get("diagnosis_validation_result") or {},
            "planning": state.get("planning_result") or {},
            "solution_validation": state.get("solution_validation_result") or {},
            "human_review": state.get("human_review_result") or {},
        },
        "extracted_knowledge": None,
        "stored_to_vector_db": None,
        "stored_to_graph_db": None,
        "closure_summary": None,
    }
    result = await closure_subgraph.ainvoke(sub_input)
    return {
        "closure_result": {
            "closure_summary": result.get("closure_summary"),
            "stored_to_vector_db": result.get("stored_to_vector_db"),
            "stored_to_graph_db": result.get("stored_to_graph_db"),
        },
        "status": "closed",
    }


# Conditional edge routing functions
def route_diagnosis_validation(state: OverallState) -> str:
    """Route after diagnosis validation."""
    result = state.get("diagnosis_validation_result") or {}
    action = result.get("suggested_action", "retry_diagnosis")
    if action == "proceed":
        return "planning"
    elif action == "retry_diagnosis":
        return "diagnosis"
    return "human_review"


def route_solution_validation(state: OverallState) -> str:
    """Route after solution validation."""
    result = state.get("solution_validation_result") or {}
    if result.get("needs_replan"):
        return "planning"
    return "human_review"


def route_human_review(state: OverallState) -> str:
    """Route after human review."""
    decision = state.get("human_decision", "escalated")
    if decision == "approved":
        return "closure"
    elif decision == "rejected":
        return "planning"
    return END


def build_optigraph(checkpointer=None) -> StateGraph:
    """Build the parent OptiGraph with all subgraphs."""
    builder = StateGraph(OverallState)

    builder.add_node("perception", perception_node)
    builder.add_node("diagnosis", diagnosis_node)
    builder.add_node("diagnosis_validation", diagnosis_validation_node)
    builder.add_node("planning", planning_node)
    builder.add_node("solution_validation", solution_validation_node)
    builder.add_node("human_review", human_review_node)
    builder.add_node("closure", closure_node)

    builder.set_entry_point("perception")
    builder.add_edge("perception", "diagnosis")
    builder.add_edge("diagnosis", "diagnosis_validation")
    builder.add_conditional_edges(
        "diagnosis_validation",
        route_diagnosis_validation,
        {
            "planning": "planning",
            "diagnosis": "diagnosis",
            "human_review": "human_review",
        },
    )
    builder.add_edge("planning", "solution_validation")
    builder.add_conditional_edges(
        "solution_validation",
        route_solution_validation,
        {
            "planning": "planning",
            "human_review": "human_review",
        },
    )
    builder.add_conditional_edges(
        "human_review",
        route_human_review,
        {
            "closure": "closure",
            "planning": "planning",
            END: END,
        },
    )
    builder.add_edge("closure", END)

    if checkpointer is None:
        checkpointer = MemorySaver()
        logger.info("Using MemorySaver for checkpoints")

    return builder.compile(checkpointer=checkpointer)


async def create_checkpointer():
    """Create checkpointer with Postgres fallback to MemorySaver."""
    if HAS_POSTGRES:
        try:
            db_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
            checkpointer = AsyncPostgresSaver.from_conn_string(db_url)
            await checkpointer.setup()
            logger.info("Using AsyncPostgresSaver for checkpoints")
            return checkpointer
        except Exception as e:
            logger.warning("Postgres checkpointer failed (%s), falling back to MemorySaver", e)
    return MemorySaver()
