"""
Demo script for OptiRCAgent.
Runs locally without external services using MemorySaver and mock LLM responses.
"""

import asyncio
import json
import os
from typing import Any, Dict, Optional

# Mock LLM responses for demo
from unittest.mock import AsyncMock, patch

from optirc.core.state import OverallState
from optirc.graphs.parent import build_optigraph


async def run_demo():
    """Run a demo session through the full pipeline."""
    print("=" * 60)
    print("OptiRCAgent Demo — Local Mode (MemorySaver)")
    print("=" * 60)

    # Create a test CSV file
    test_csv = "demo_test.csv"
    with open(test_csv, "w", encoding="utf-8") as f:
        f.write("alarm_type,device_id,description,topology_id\n")
        f.write("power_loss,node_01,sudden power drop,topo_1\n")

    # Mock LLM responses
    async def mock_generate_json(system: str, user_message: str, model: Optional[str] = None, temperature: float = 0.2) -> Dict[str, Any]:
        if "diagnosis" in system.lower():
            return {
                "reasoning_chain": "Power loss detected at node_01, likely fiber issue",
                "candidate_causes": [
                    {"cause": "fiber_cut", "confidence_score": 0.85, "evidence": ["alarm_log"]},
                ],
                "root_cause": "fiber_cut",
                "confidence": 0.85,
                "evidence": ["alarm_log"],
                "recommended_action": "Check fiber cable",
            }
        elif "validation" in system.lower():
            return {
                "evidence_completeness_score": 0.9,
                "validation_passed": True,
                "validation_notes": "Valid diagnosis",
                "suggested_action": "proceed",
            }
        elif "planning" in system.lower():
            return {
                "candidate_plans": [
                    {
                        "steps": ["Check fiber cable", "Replace damaged section"],
                        "estimated_time": "2 hours",
                        "required_resources": ["fiber_splicer"],
                    },
                ],
                "risk_assessment": "Low risk with proper equipment",
                "final_plan": {
                    "steps": ["Check fiber cable", "Replace damaged section"],
                    "estimated_time": "2 hours",
                    "required_resources": ["fiber_splicer"],
                },
                "rollback_procedure": "Revert config changes",
            }
        elif "solution" in system.lower():
            return {
                "consistency_matrix": {"root_cause_addressed": True},
                "feasibility_score": 0.9,
                "resource_match_check": True,
                "solution_valid": True,
                "risk_level": "low",
                "validation_notes": "Valid solution",
                "needs_replan": False,
            }
        return {}

    async def mock_embed(texts: list) -> list:
        return [[0.1] * 384 for _ in texts]

    async def mock_ocr(image_base64: str) -> str:
        return "Demo OCR text"

    # Patch LLM client
    from optirc.core import llm_client
    llm_client.generate_json = mock_generate_json
    llm_client.embed = mock_embed
    llm_client.ocr = mock_ocr

    # Build graph (will use MemorySaver since Postgres unavailable)
    graph = build_optigraph()
    print(f"Checkpointer: {type(graph.checkpointer).__name__}")
    print()

    session_id = "demo-session-001"
    initial_state: OverallState = {
        "session_id": session_id,
        "raw_input": test_csv,
        "status": "init",
        "perception_result": None,
        "diagnosis_result": None,
        "diagnosis_validation_result": None,
        "planning_result": None,
        "solution_validation_result": None,
        "human_review_result": None,
        "closure_result": None,
        "pending_human": False,
        "human_decision": None,
        "error_message": None,
        "messages": [],
    }

    config = {"configurable": {"thread_id": session_id}}

    print("Running pipeline...")
    print("-" * 60)

    # Run pipeline (will stop at human_review interrupt)
    result = await graph.ainvoke(initial_state, config=config)

    print(f"Final status: {result.get('status')}")
    print(f"Perception: {json.dumps(result.get('perception_result'), indent=2, ensure_ascii=False)}")
    print(f"Diagnosis: {json.dumps(result.get('diagnosis_result'), indent=2, ensure_ascii=False)}")
    print(f"Planning: {json.dumps(result.get('planning_result'), indent=2, ensure_ascii=False)}")
    print(f"Solution Validation: {json.dumps(result.get('solution_validation_result'), indent=2, ensure_ascii=False)}")

    # Resume with human decision
    from langgraph.types import Command
    result = await graph.ainvoke(
        Command(resume={"decision": "approved", "notes": "Demo approval"}),
        config=config,
    )

    print(f"After Human Review: {result.get('status')}")
    print(f"Closure: {json.dumps(result.get('closure_result'), indent=2, ensure_ascii=False)}")

    print("-" * 60)
    print("Demo completed successfully!")

    # Cleanup
    if os.path.exists(test_csv):
        os.remove(test_csv)


if __name__ == "__main__":
    asyncio.run(run_demo())
