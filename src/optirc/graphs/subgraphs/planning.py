import json
import logging
from typing import Any, Dict

from langgraph.graph import END, StateGraph

from optirc.core.llm_client import llm_client
from optirc.core.state import PlanningInternalState
from optirc.rag.vector_store import vector_store

logger = logging.getLogger(__name__)

PLANNING_SYSTEM_PROMPT = """You are an optical network operations planning expert.
Given a diagnosis result, generate repair plans and output JSON with:
- candidate_plans: list of plan objects {steps, estimated_time, required_resources}
- risk_assessment: string describing overall risk
- final_plan: the recommended plan object
- rollback_procedure: string describing rollback steps
"""


async def retrieve_sops_node(state: PlanningInternalState) -> Dict[str, Any]:
    """Retrieve standard operating procedures."""
    diagnosis = state["diagnosis_result"]
    root_cause = diagnosis.get("root_cause", "")
    try:
        sops = await vector_store.search(root_cause, top_k=3, filter_type="sop")
        return {"retrieved_sops": sops}
    except Exception as e:
        logger.warning("SOP retrieval failed: %s", e)
        return {"retrieved_sops": []}


async def generate_candidates_node(state: PlanningInternalState) -> Dict[str, Any]:
    """Generate candidate repair plans via LLM."""
    diagnosis = state["diagnosis_result"]
    sops = state.get("retrieved_sops") or []

    sops_text = "\n".join([s.get("content", "") for s in sops])
    user_message = f"""Diagnosis:
{json.dumps(diagnosis, ensure_ascii=False, indent=2)}

Retrieved SOPs:
{sops_text}
"""
    try:
        result = await llm_client.generate_json(
            system=PLANNING_SYSTEM_PROMPT,
            user_message=user_message,
            temperature=0.2,
        )
        return {
            "candidate_plans": result.get("candidate_plans", []),
            "risk_assessment": result.get("risk_assessment", ""),
        }
    except Exception as e:
        logger.warning("Plan generation failed: %s", e)
        return {
            "candidate_plans": [],
            "risk_assessment": "unable to assess risk",
        }


def finalize_plan_node(state: PlanningInternalState) -> Dict[str, Any]:
    """Finalize the repair plan."""
    candidate_plans = state.get("candidate_plans") or []
    risk = state.get("risk_assessment", "")

    if not candidate_plans:
        return {
            "final_plan": {
                "steps": ["manual intervention required"],
                "estimated_time": "unknown",
                "required_resources": [],
            },
            "rollback_procedure": "no rollback available",
        }

    best = candidate_plans[0]
    return {
        "final_plan": best,
        "rollback_procedure": "; ".join([
            "1. Revert config changes",
            "2. Restore backup if available",
            "3. Contact senior engineer if unresolved",
        ]),
    }


def build_planning_subgraph() -> StateGraph:
    """Build planning subgraph."""
    builder = StateGraph(PlanningInternalState)
    builder.add_node("retrieve_sops", retrieve_sops_node)
    builder.add_node("generate_candidates", generate_candidates_node)
    builder.add_node("finalize_plan", finalize_plan_node)

    builder.set_entry_point("retrieve_sops")
    builder.add_edge("retrieve_sops", "generate_candidates")
    builder.add_edge("generate_candidates", "finalize_plan")
    builder.add_edge("finalize_plan", END)

    return builder.compile()
