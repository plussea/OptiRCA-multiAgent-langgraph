"""
End-to-end smoke test for alarm_log_demo.csv.

Runs the full OptiGraph pipeline (perception → diagnosis → validation →
planning → solution_validation → human_review → closure) on the bundled
demo CSV and prints what each stage produced.
"""
import asyncio
import json
import sys
import traceback
from pathlib import Path

# Make src/ importable
sys.path.insert(0, str(Path(__file__).parent / "src"))

from optirc.core.config import settings
from optirc.core.state import OverallState
from optirc.graphs.parent import build_optigraph


DEMO_CSV = Path("input/data/true_data/alarm_log_demo.csv")


async def main() -> int:
    print("=" * 70)
    print("OptiRCAgent — Demo End-to-End Smoke Test")
    print("=" * 70)
    print(f"Demo CSV: {DEMO_CSV}  ({DEMO_CSV.stat().st_size} bytes)")
    print(f"LLM:      {settings.llm_model} @ {settings.llm_base_url}")
    print("-" * 70)

    graph = build_optigraph()
    print(f"Checkpointer: {type(graph.checkpointer).__name__}")
    print(f"Nodes:        {sorted(n for n in graph.nodes if not n.startswith('__'))}")
    print()

    session_id = "smoke-demo-001"
    initial_state: OverallState = {
        "session_id": session_id,
        "raw_input": str(DEMO_CSV.absolute()),
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
    config = {"configurable": {"thread_id": session_id}, "recursion_limit": 200}

    print("Running pipeline (this may take 30-60s if the LLM is reachable)…")
    try:
        result = await graph.ainvoke(initial_state, config=config)
    except Exception as e:
        print(f"\n[FAIL] Pipeline raised: {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1

    print(f"\n[OK] Pipeline finished. Final status: {result.get('status')}")
    print("-" * 70)

    # Print each stage's output compactly
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
        if len(snippet) > 1200:
            snippet = snippet[:1200] + "…"
        print(f"[{label:<18}] {snippet}")

    # Count how many stages were driven by the LLM (vs. a graceful fallback)
    # by looking for the canonical "All LLM providers unavailable" message.
    fallback_count = 0
    try:
        with open("/tmp/smoke.log") as f:
            log_text = f.read()
        fallback_count = log_text.count("All LLM providers unavailable")
    except Exception:
        pass
    print(f"\n[LLM] Fallback invocations: {fallback_count} (0 means every LLM call succeeded)")

    # If we stopped at human_review, drive it to completion.
    if result.get("status") == "human_reviewed":
        print("\n" + "-" * 70)
        print("Resuming pipeline with synthetic human decision: approved")
        from langgraph.types import Command
        result2 = await graph.ainvoke(
            Command(resume={"decision": "approved", "notes": "Smoke-test approval"}),
            config=config,
        )
        print(f"[Status after resume] {result2.get('status')}")
        v = result2.get("closure_result")
        if v:
            print(f"[Closure after resume] {json.dumps(v, ensure_ascii=False, indent=2)}")

    print("\n" + "=" * 70)
    print("Smoke test finished.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
