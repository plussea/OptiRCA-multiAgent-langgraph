import logging
from typing import Any, Dict

from langgraph.graph import END, StateGraph

from optirc.core.llm_client import llm_client
from optirc.core.state import DiagnosisValidationInternalState

logger = logging.getLogger(__name__)

REVALIDATION_SYSTEM_PROMPT = """You are a diagnostic validation expert.
Given a diagnosis result, evaluate its validity and output a JSON with:
- evidence_completeness_score: float 0-1
- validation_passed: bool
- validation_notes: string
- suggested_action: one of "proceed", "retry_diagnosis", "needs_human"
"""


def rule_check_node(state: DiagnosisValidationInternalState) -> Dict[str, Any]:
    """Rule-based validation of diagnosis."""
    diagnosis = state["diagnosis_result"]
    confidence = diagnosis.get("confidence", 0)
    evidence = diagnosis.get("evidence", [])
    root_cause = diagnosis.get("root_cause", "")

    notes = []
    if confidence < 0.6:
        notes.append("Confidence below threshold (0.6)")
    if not evidence:
        notes.append("No evidence provided")
    if root_cause == "unknown":
        notes.append("Root cause is unknown")

    passed = confidence >= 0.6 and len(evidence) > 0 and root_cause != "unknown"
    return {
        "validation_passed": passed,
        "validation_notes": "; ".join(notes) if notes else "Rule checks passed",
        "suggested_action": "proceed" if passed else "retry_diagnosis",
    }


async def llm_revalidate_node(state: DiagnosisValidationInternalState) -> Dict[str, Any]:
    """LLM secondary validation."""
    diagnosis = state["diagnosis_result"]
    import json
    user_message = f"Diagnosis Result:\n{json.dumps(diagnosis, ensure_ascii=False, indent=2)}"
    try:
        result = await llm_client.generate_json(
            system=REVALIDATION_SYSTEM_PROMPT,
            user_message=user_message,
            temperature=0.1,
        )
        return {
            "evidence_completeness_score": result.get("evidence_completeness_score", 0.5),
            "llm_revalidation_output": json.dumps(result, ensure_ascii=False),
        }
    except Exception as e:
        logger.warning("LLM revalidation failed: %s", e)
        return {
            "evidence_completeness_score": 0.5,
            "llm_revalidation_output": "",
        }


def finalize_validation_node(state: DiagnosisValidationInternalState) -> Dict[str, Any]:
    """Finalize validation result."""
    rule_passed = state.get("validation_passed", False)
    llm_score = state.get("evidence_completeness_score", 0.5)
    notes = state.get("validation_notes", "")
    suggested = state.get("suggested_action", "retry_diagnosis")

    # If rule check says proceed but LLM score is low, still needs review
    if rule_passed and llm_score < 0.5:
        suggested = "needs_human"
        notes += "; LLM revalidation score too low"

    return {
        "validation_passed": rule_passed and llm_score >= 0.5,
        "validation_notes": notes,
        "suggested_action": suggested,
    }


def build_diagnosis_validation_subgraph() -> StateGraph:
    """Build diagnosis validation subgraph."""
    builder = StateGraph(DiagnosisValidationInternalState)
    builder.add_node("rule_check", rule_check_node)
    builder.add_node("llm_revalidate", llm_revalidate_node)
    builder.add_node("finalize_validation", finalize_validation_node)

    builder.set_entry_point("rule_check")
    builder.add_edge("rule_check", "llm_revalidate")
    builder.add_edge("llm_revalidate", "finalize_validation")
    builder.add_edge("finalize_validation", END)

    return builder.compile()
