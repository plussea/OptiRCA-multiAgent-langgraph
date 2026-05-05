import json
import logging
from typing import Any, Dict

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from optirc.core.state import HumanReviewInternalState

logger = logging.getLogger(__name__)


def prepare_review_node(state: HumanReviewInternalState) -> Dict[str, Any]:
    """Assemble review package."""
    package = {
        "session_id": state["session_id"],
        "diagnosis": state["diagnosis_result"],
        "planning": state["planning_result"],
        "solution_validation": state["solution_validation"],
        "timeout_seconds": 600,
    }
    return {"review_package": package}


def wait_human_decision_node(state: HumanReviewInternalState) -> Dict[str, Any]:
    """Wait for human decision via interrupt."""
    review_package = state.get("review_package", {})
    # Use langgraph.interrupt to pause execution
    result = interrupt(review_package)
    decision = result.get("decision", "escalated")
    notes = result.get("notes", "")
    from datetime import datetime, timezone
    approved_at = datetime.now(timezone.utc).isoformat() if decision == "approved" else None
    return {
        "decision": decision,
        "reviewer_notes": notes,
        "approved_at": approved_at,
    }


def build_human_review_subgraph() -> StateGraph:
    """Build human review subgraph."""
    builder = StateGraph(HumanReviewInternalState)
    builder.add_node("prepare_review", prepare_review_node)
    builder.add_node("wait_human_decision", wait_human_decision_node)

    builder.set_entry_point("prepare_review")
    builder.add_edge("prepare_review", "wait_human_decision")
    builder.add_edge("wait_human_decision", END)

    return builder.compile()
