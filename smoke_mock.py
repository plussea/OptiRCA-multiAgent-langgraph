"""
End-to-end demo smoke test with a stub LLM.

The real LLM endpoints (ModelScope/OpenRouter) are rate-limited in this
environment, so we monkey-patch the LLM client to return deterministic
JSON and prove the rest of the pipeline executes correctly. This exercises
every feature: perception, diagnosis, validation, planning, solution
validation, human_review (interrupt + resume), and closure.
"""
import asyncio
import json
import sys
import traceback
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent / "src"))

DEMO_CSV = Path("input/data/true_data/alarm_log_demo.csv").absolute()


# ── Fake LLM responses ────────────────────────────────────────────────────────

DIAGNOSIS_FAKE = {
    "reasoning_chain": "6×MUT_LOS at the same instant across multiple NEs suggests a common upstream optical fiber break. 1×R_LOS on NE2 is consistent with the receive direction of the same link. 1×ODU_SNCP_STA_INDI on NE3 is a downstream effect of the optical-layer fault.",
    "candidate_causes": [
        {
            "cause": "Optical fiber break on the upstream OTS link between OA1 and NE1/NE2",
            "confidence_score": 0.92,
            "evidence": [
                "6×MUT_LOS clustered at 2025/10/23 11:06",
                "Spans OA1↔NE1 and OA1↔NE2",
                "1×R_LOS on NE2 is correlated"
            ],
            "recommended_action": "Dispatch fiber crew to inspect OA1-NE1 and OA1-NE2 spans"
        }
    ],
    "root_cause": "Optical fiber break on the upstream OTS link between OA1 and NE1/NE2",
    "confidence": 0.92,
    "evidence": [
        "6×MUT_LOS clustered at 2025/10/23 11:06",
        "Spans OA1↔NE1 and OA1↔NE2",
        "1×R_LOS on NE2 is correlated"
    ],
    "recommended_action": "Dispatch fiber crew to inspect OA1-NE1 and OA1-NE2 spans"
}

REVALIDATION_FAKE = {
    "evidence_completeness_score": 0.85,
    "validation_passed": True,
    "validation_notes": "Diagnosis is well-supported by the alarm cluster pattern",
    "suggested_action": "proceed"
}

PLANNING_FAKE = {
    "candidate_plans": [
        {
            "steps": [
                "Repair optical fiber break on the upstream OTS link between OA1 and NE1/NE2 — dispatch fiber crew to locate and splice the break",
                "Inspect physical fiber path between OA1 and NE1",
                "Replace damaged fiber section",
                "Verify alarm clearance on all affected NEs",
            ],
            "estimated_time": "2 hours",
            "required_resources": ["fiber crew", "OTDR", "spare fiber cable"],
        }
    ],
    "risk_assessment": "low - field work, no service impact expected with redundant path",
    "final_plan": {
        "steps": [
            "Repair optical fiber break on the upstream OTS link between OA1 and NE1/NE2 — dispatch fiber crew to locate and splice the break",
            "Inspect physical fiber path between OA1 and NE1",
            "Replace damaged fiber section",
            "Verify alarm clearance on all affected NEs",
        ],
        "estimated_time": "2 hours",
        "required_resources": ["fiber crew", "OTDR", "spare fiber cable"],
    },
    "rollback_procedure": "1. Revert any fiber splices 2. Restore previous patch panel routing 3. Contact senior engineer if unresolved"
}

SOLUTION_VALIDATION_FAKE = {
    "consistency_matrix": {"root_cause_addressed": True, "plan_steps_count": 4},
    "feasibility_score": 0.9,
    "resource_match_check": True,
    "solution_valid": True,
    "risk_level": "low",
    "validation_notes": "Plan directly addresses the fiber break root cause with appropriate resources",
    "needs_replan": False
}


# ── Stub the LLM client before importing the graph ────────────────────────────

import optirc.core.llm_client as llm_module

# Build a mock whose .generate_json / .embed / .ocr methods return the right
# fake for each call site.
mock = MagicMock()
async def _generate_json_dispatcher(*args, **kwargs):
    """Return a different fake JSON depending on the system prompt of the
    caller. This way, no matter which subgraph calls us, we get the right
    shape of response — and it works for retries too (side_effect can be
    called many times)."""
    system = kwargs.get("system", "")
    if not system and args:
        system = args[0]
    sys = system.lower() if isinstance(system, str) else ""
    if "diagnostic validation" in sys:
        return REVALIDATION_FAKE
    if "operations planning" in sys:
        return PLANNING_FAKE
    if "solution validation" in sys:
        return SOLUTION_VALIDATION_FAKE
    # Default: diagnosis
    return DIAGNOSIS_FAKE

mock.generate_json = _generate_json_dispatcher
mock.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])
mock.ocr = AsyncMock(return_value="")
mock.get_health_metrics = MagicMock(return_value={
    "primary": {"circuit": {"state": "closed"}},
    "backup": {"circuit": {"state": "closed"}},
})

llm_module.llm_client = mock
# Also patch the import in each subgraph that did `from optirc.core.llm_client import llm_client`
import optirc.graphs.subgraphs.diagnosis as dx_mod
import optirc.graphs.subgraphs.diagnosis_validation as dv_mod
import optirc.graphs.subgraphs.planning as pl_mod
import optirc.graphs.subgraphs.solution_validation as sv_mod
import optirc.graphs.subgraphs.perception as pe_mod
import optirc.graphs.subgraphs.closure as cl_mod
import optirc.graphs.parent as parent_mod
import optirc.rag.vector_store as vs_mod

for mod in (dx_mod, dv_mod, pl_mod, sv_mod, pe_mod, cl_mod, parent_mod, vs_mod):
    if hasattr(mod, "llm_client"):
        mod.llm_client = mock

# Stub the knowledge graph services so they don't try to hit external Neo4j.
import optirc.knowledge.kg_query as kg_mod
import optirc.knowledge.builder as kg_builder_mod
import optirc.knowledge.extractor as kg_extractor_mod

# The rag/__init__.py shadow bug means `optirc.rag.vector_store` resolves
# to the VectorStore *instance*, not the module. Patch the search method
# directly on the instance.
try:
    from optirc.rag.vector_store import vector_store as _vs_instance
    _vs_instance.search = AsyncMock(return_value=[])
    _vs_instance.add_documents = MagicMock(return_value=None)
    # Short-circuit _init so it doesn't try to talk to ChromaDB
    _vs_instance._init = lambda: None
    _vs_instance._collection = None
except Exception as e:
    print(f"(vector_store patch skipped: {e})")

kg_mod.kg_query_service.get_subgraph = AsyncMock(return_value={"nodes": [], "relationships": []})
kg_mod.kg_query_service.add_case_knowledge = AsyncMock(return_value=None)
kg_builder_mod.graph_builder.build_from_extraction = AsyncMock(
    return_value={"entities": {"created": 0}, "relationships": {"created": 0}}
)

# Mock knowledge extractor: bypass the LLM
class FakeExtraction:
    entities = []
    relationships = []

fake_extract_result = FakeExtraction()
kg_extractor_mod.knowledge_extractor.extract_from_case = AsyncMock(return_value=fake_extract_result)


# ── Run the pipeline ──────────────────────────────────────────────────────────

from optirc.core.state import OverallState
from optirc.graphs.parent import build_optigraph


async def main() -> int:
    print("=" * 70)
    print("OptiRCAgent — Demo End-to-End Smoke Test (LLM stubbed)")
    print("=" * 70)
    print(f"Demo CSV: {DEMO_CSV}  ({DEMO_CSV.stat().st_size} bytes)")
    print("-" * 70)

    graph = build_optigraph()
    print(f"Checkpointer: {type(graph.checkpointer).__name__}")
    print(f"Nodes:        {sorted(n for n in graph.nodes if not n.startswith('__'))}")
    print()

    session_id = "smoke-mock-001"
    initial_state: OverallState = {
        "session_id": session_id,
        "raw_input": str(DEMO_CSV),
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
        "retry_count": 0,
        "messages": [],
    }
    config = {"configurable": {"thread_id": session_id, "recursion_limit": 200}}

    print("Running pipeline…")
    try:
        result = await graph.ainvoke(initial_state, config=config)
    except Exception as e:
        print(f"\n[FAIL] Pipeline raised: {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1

    print(f"\n[OK] Pipeline finished. Final status: {result.get('status')}")
    print(f"     pending_human: {result.get('pending_human')}")
    print("-" * 70)

    stage_keys = [
        ("perception_result", "Perception"),
        ("diagnosis_result", "Diagnosis"),
        ("diagnosis_validation_result", "DiagValidation"),
        ("planning_result", "Planning"),
        ("solution_validation_result", "SolutionValidation"),
        ("human_review_result", "HumanReview"),
        ("closure_result", "Closure"),
    ]
    for key, label in stage_keys:
        v = result.get(key)
        if v is None:
            print(f"[{label:<18}] (none)")
            continue
        snippet = json.dumps(v, ensure_ascii=False)
        if len(snippet) > 600:
            snippet = snippet[:600] + "…"
        print(f"[{label:<18}] {snippet}")

    # If we stopped at human_review, drive it to completion.
    # The graph pauses at `wait_human_decision_node` via `interrupt()`. We
    # can detect this by checking the state — `pending_human` will be set
    # to False by the wrapper, but the graph itself is paused. We need to
    # send a Command(resume=...) to continue.
    from langgraph.types import Command
    try:
        print("\n" + "-" * 70)
        print("Resuming pipeline with synthetic human decision: approved")
        result2 = await graph.ainvoke(
            Command(resume={"decision": "approved", "notes": "Smoke-test approval"}),
            config=config,
        )
        print(f"[Status after resume] {result2.get('status')}")
        v = result2.get("closure_result")
        if v:
            print(f"[Closure after resume] {json.dumps(v, ensure_ascii=False, indent=2)}")
        # Print final summary
        print("\n" + "=" * 70)
        print("FINAL STATE SUMMARY")
        print("=" * 70)
        for key, label in [
            ("perception_result", "Perception"),
            ("diagnosis_result", "Diagnosis"),
            ("diagnosis_validation_result", "DiagValidation"),
            ("planning_result", "Planning"),
            ("solution_validation_result", "SolutionValidation"),
            ("human_review_result", "HumanReview"),
            ("closure_result", "Closure"),
        ]:
            v = result2.get(key)
            if v is None:
                print(f"  [{label}] (none)")
            else:
                print(f"  [{label}] {json.dumps(v, ensure_ascii=False)[:300]}")
    except Exception as e:
        # Graph may already be at the end if no interrupt was triggered
        if "No pending interrupts" in str(e) or "GRAPH_RECURSION" in str(e):
            print(f"  (no resume needed or already at end: {e})")
        else:
            print(f"  (resume failed: {e})")

    # Print trace
    print("\n" + "-" * 70)
    print("Execution trace (from aget_state_history):")
    try:
        history = [h async for h in graph.aget_state_history(config)]
        for i, item in enumerate(history[:20]):
            v = item.values if hasattr(item, "values") else {}
            print(f"  {i+1:2d}. status={v.get('status','?'):<22} retry={v.get('retry_count', 0)}")
    except Exception as e:
        print(f"  (history fetch failed: {e})")

    print("\n" + "=" * 70)
    return 0 if result.get("status") in ("human_reviewed", "closed") else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
