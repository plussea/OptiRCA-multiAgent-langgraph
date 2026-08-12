"""
Demo script for OptiRCAgent — runs without mock LLM.
Enable LangSmith tracing by setting LANGSMITH_TRACING=true in .env.
"""

import asyncio
import json
import os

from optirc.core.config import settings

if settings.langsmith_tracing and settings.langsmith_api_key:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
    print(f"[LangSmith] Tracing ENABLED — project: {settings.langsmith_project}")
else:
    print("[LangSmith] Tracing DISABLED (set LANGSMITH_TRACING=true in .env to enable)")

from optirc.core.state import OverallState
from optirc.graphs.parent import build_optigraph


async def run_demo():
    print("=" * 60)
    print("OptiRCAgent Demo — Local Mode (MemorySaver)")
    print("=" * 60)
    print()

    test_csv = "demo_test.csv"
    with open(test_csv, "w", encoding="utf-8") as f:
        f.write("alarm_type,device_id,description,topology_id\n")
        f.write("power_loss,node_01,sudden power drop,topo_1\n")

    graph = build_optigraph()
    print(f"[Graph] Checkpointer : {type(graph.checkpointer).__name__}")
    print(f"[Graph] Nodes       : {', '.join(n for n in graph.nodes.keys() if not n.startswith('__'))}")
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
        "retry_count": 0,
        "messages": [],
    }

    config = {"configurable": {"thread_id": session_id, "recursion_limit": 200}}

    print("Running pipeline...")
    print("-" * 60)

    try:
        result = await graph.ainvoke(initial_state, config=config)
    except Exception as e:
        print(f"[Error] {e}")
        return

    print(f"[Status] {result.get('status')}")
    for key, label in [
        ("perception_result", "Perception"),
        ("diagnosis_result", "Diagnosis"),
        ("diagnosis_validation_result", "DiagValidation"),
        ("planning_result", "Planning"),
        ("solution_validation_result", "SolutionValidation"),
        ("human_review_result", "HumanReview"),
        ("closure_result", "Closure"),
    ]:
        v = result.get(key)
        if v:
            print(f"[{label}] {json.dumps(v, ensure_ascii=False, indent=2)}")

    if result.get("status") == "human_reviewed":
        from langgraph.types import Command
        result = await graph.ainvoke(
            Command(resume={"decision": "approved", "notes": "Demo approval"}),
            config=config,
        )
        print(f"\n[Status after HumanReview] {result.get('status')}")
        print(f"[Closure] {json.dumps(result.get('closure_result'), ensure_ascii=False, indent=2)}")

    print()
    print("-" * 60)
    print("Demo completed!")

    if os.path.exists(test_csv):
        os.remove(test_csv)


if __name__ == "__main__":
    asyncio.run(run_demo())