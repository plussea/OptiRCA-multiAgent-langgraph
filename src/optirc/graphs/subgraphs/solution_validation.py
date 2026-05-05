import json
import logging
from typing import Any, Dict

from langgraph.graph import END, StateGraph

from optirc.core.llm_client import llm_client
from optirc.core.state import SolutionValidationInternalState

logger = logging.getLogger(__name__)

SOLUTION_VALIDATION_SYSTEM_PROMPT = """You are a solution validation expert for optical network operations.
Given a plan and diagnosis, evaluate and output JSON with:
- consistency_matrix: object showing plan-diagnosis alignment
- feasibility_score: float 0-1
- resource_match_check: bool
- solution_valid: bool
- risk_level: one of "low", "medium", "high"
- validation_notes: string
- needs_replan: bool
"""


def consistency_check_node(state: SolutionValidationInternalState) -> Dict[str, Any]:
    """Check plan-diagnosis consistency."""
    plan = state["planning_result"]
    diagnosis = state["diagnosis_result"]
    root_cause = diagnosis.get("root_cause", "")
    plan_steps = plan.get("final_plan", {}).get("steps", [])

    # Simple heuristic: plan steps should mention root cause or related terms
    related = any(root_cause.lower() in str(step).lower() for step in plan_steps)
    return {
        "consistency_matrix": {
            "root_cause_addressed": related,
            "plan_steps_count": len(plan_steps),
        },
    }


def feasibility_check_node(state: SolutionValidationInternalState) -> Dict[str, Any]:
    """Check plan feasibility."""
    plan = state["planning_result"]
    final_plan = plan.get("final_plan", {})
    resources = final_plan.get("required_resources", [])
    estimated_time = final_plan.get("estimated_time", "")

    # Simple heuristic
    has_resources = len(resources) > 0
    reasonable_time = estimated_time != "unknown" and "manual" not in str(estimated_time).lower()

    return {
        "feasibility_score": 0.8 if (has_resources and reasonable_time) else 0.4,
        "resource_match_check": has_resources,
    }


async def risk_evaluation_node(state: SolutionValidationInternalState) -> Dict[str, Any]:
    """Evaluate execution risk via LLM."""
    plan = state["planning_result"]
    diagnosis = state["diagnosis_result"]
    user_message = f"""Plan:
{json.dumps(plan, ensure_ascii=False, indent=2)}

Diagnosis:
{json.dumps(diagnosis, ensure_ascii=False, indent=2)}
"""
    try:
        result = await llm_client.generate_json(
            system=SOLUTION_VALIDATION_SYSTEM_PROMPT,
            user_message=user_message,
            temperature=0.1,
        )
        return {
            "solution_valid": result.get("solution_valid", False),
            "risk_level": result.get("risk_level", "high"),
            "validation_notes": result.get("validation_notes", ""),
            "needs_replan": result.get("needs_replan", True),
            "llm_evaluation_output": json.dumps(result, ensure_ascii=False),
        }
    except Exception as e:
        logger.warning("LLM risk evaluation failed: %s", e)
        return {
            "solution_valid": False,
            "risk_level": "high",
            "validation_notes": "evaluation failed",
            "needs_replan": True,
            "llm_evaluation_output": "",
        }


def finalize_solution_validation_node(state: SolutionValidationInternalState) -> Dict[str, Any]:
    """Finalize solution validation."""
    consistency = state.get("consistency_matrix", {})
    feasibility = state.get("feasibility_score", 0)
    resources = state.get("resource_match_check", False)
    llm_valid = state.get("solution_valid", False)
    risk = state.get("risk_level", "high")
    notes = state.get("validation_notes", "")

    valid = (
        consistency.get("root_cause_addressed", False)
        and feasibility >= 0.5
        and resources
        and llm_valid
    )

    return {
        "solution_valid": valid,
        "risk_level": risk if valid else "high",
        "validation_notes": notes,
        "needs_replan": not valid,
    }


def build_solution_validation_subgraph() -> StateGraph:
    """Build solution validation subgraph."""
    builder = StateGraph(SolutionValidationInternalState)
    builder.add_node("consistency_check", consistency_check_node)
    builder.add_node("feasibility_check", feasibility_check_node)
    builder.add_node("risk_evaluation", risk_evaluation_node)
    builder.add_node("finalize_solution_validation", finalize_solution_validation_node)

    builder.set_entry_point("consistency_check")
    builder.add_edge("consistency_check", "feasibility_check")
    builder.add_edge("feasibility_check", "risk_evaluation")
    builder.add_edge("risk_evaluation", "finalize_solution_validation")
    builder.add_edge("finalize_solution_validation", END)

    return builder.compile()
