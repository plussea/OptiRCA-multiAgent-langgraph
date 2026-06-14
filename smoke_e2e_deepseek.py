"""End-to-end smoke test: run demo CSV through the full OptiGraph with DeepSeek.

What this exercises:
- perception → diagnosis → diagnosis_validation → planning → solution_validation
  → human_review (auto-approved) → closure
- Confirms DeepSeek (https://api.deepseek.com) is hit at every LLM step
- Survives missing Postgres / Redis / Neo4j / ChromaDB by relying on the
  graceful-degradation paths already built into each subgraph.

NOTE: human_review uses langgraph.types.interrupt to pause for HITL. We
monkey-patch it to auto-approve so we can drive a full pipeline in one
process without standing up a separate decision API.
"""

import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path

# Make the project importable
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# ── Silence noise, but keep our own INFO logs ───────────────────────────
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
# Bump the modules we care about
for name in ("optirc.core.llm_client", "optirc.graphs", "optirc.knowledge",
             "optirc.rag", "optirc.memory", "optirc.ingestion"):
    logging.getLogger(name).setLevel(logging.INFO)


# ── Monkey-patch interrupt() so human_review auto-approves ──────────────
import langgraph.types as _lg_types

_real_interrupt = _lg_types.interrupt


def _auto_approve_interrupt(payload):
    print(f"  [HUMAN_REVIEW] interrupt() called — auto-approving. "
          f"payload keys={list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__}")
    return {"decision": "approved", "notes": "auto-approved by smoke_e2e_deepseek.py"}


_lg_types.interrupt = _auto_approve_interrupt

# Also patch the import path that human_review.py uses
import optirc.graphs.subgraphs.human_review as _hr_mod
_hr_mod.interrupt = _auto_approve_interrupt


# ── Track every LLM call to prove DeepSeek was hit ──────────────────────
from optirc.core import llm_client as _llm_mod

_orig_generate_json = _llm_mod.LLMClient.generate_json
_orig_generate_text = _llm_mod.LLMClient.generate_text
_orig_embed = _llm_mod.LLMClient.embed
_orig_ocr = _llm_mod.LLMClient.ocr

call_log: list = []


async def _wrap_json(self, system, user_message, model=None, temperature=0.2, use_fallback=True):
    primary_model = self.primary.model
    primary_url = str(self.primary.client.base_url)
    print(f"  [LLM.generate_json] model={primary_model} base_url={primary_url}")
    call_log.append({"fn": "generate_json", "model": primary_model, "base_url": primary_url})
    return await _orig_generate_json(self, system, user_message, model, temperature, use_fallback)


async def _wrap_text(self, system, user_message, model=None, temperature=0.2, use_fallback=True):
    primary_model = self.primary.model
    primary_url = str(self.primary.client.base_url)
    print(f"  [LLM.generate_text] model={primary_model} base_url={primary_url}")
    call_log.append({"fn": "generate_text", "model": primary_model, "base_url": primary_url})
    return await _orig_generate_text(self, system, user_message, model, temperature, use_fallback)


async def _wrap_embed(self, texts):
    base_url = str(self.embedding.client.base_url)
    print(f"  [LLM.embed] model={self.embedding.model} base_url={base_url} n={len(texts)}")
    call_log.append({"fn": "embed", "model": self.embedding.model, "base_url": base_url, "n": len(texts)})
    return await _orig_embed(self, texts)


async def _wrap_ocr(self, image_base64):
    base_url = str(self.ocr_client.base_url)
    print(f"  [LLM.ocr] base_url={base_url}")
    call_log.append({"fn": "ocr", "base_url": base_url})
    return await _orig_ocr(self, image_base64)


_llm_mod.LLMClient.generate_json = _wrap_json
_llm_mod.LLMClient.generate_text = _wrap_text
_llm_mod.LLMClient.embed = _wrap_embed
_llm_mod.LLMClient.ocr = _wrap_ocr


# ── Now build the graph and run ─────────────────────────────────────────
from langgraph.checkpoint.memory import MemorySaver
from optirc.core.config import settings
from optirc.core.state import OverallState
from optirc.graphs.parent import build_optigraph

DEMO_CSV = ROOT / "input" / "data" / "true_data" / "alarm_log_demo.csv"


async def main() -> int:
    print("=" * 70)
    print(" OptiGraph E2E smoke test (DeepSeek)")
    print("=" * 70)
    print(f" .env loaded: LLM_MODEL={settings.llm_model}, "
          f"LLM_BASE_URL={settings.llm_base_url}, "
          f"BACKUP_BASE_URL={settings.llm_backup_base_url}")
    print(f" demo CSV:    {DEMO_CSV} (exists={DEMO_CSV.exists()})")
    print()

    if not DEMO_CSV.exists():
        print(f"!! demo CSV not found at {DEMO_CSV}")
        return 1

    checkpointer = MemorySaver()
    graph = build_optigraph(checkpointer=checkpointer)

    session_id = str(uuid.uuid4())
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
    config = {"configurable": {"thread_id": session_id}}

    print(f"▶ Running pipeline for session {session_id}")
    print("-" * 70)
    try:
        final = await graph.ainvoke(initial_state, config=config)
    except Exception as e:
        print(f"\n!! Pipeline raised: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        # Show state at time of failure
        try:
            snap = await graph.aget_state(config)
            print(f"\n state at failure: status={snap.values.get('status')!r}, "
                  f"error={snap.values.get('error_message')!r}")
        except Exception:
            pass
        return 1
    print("-" * 70)
    print("✓ Pipeline finished")
    print()

    # ── Report final state ───────────────────────────────────────────────
    print("=" * 70)
    print(" Final state")
    print("=" * 70)
    print(f"  status                 = {final.get('status')!r}")
    print(f"  perception             = {json.dumps(final.get('perception_result'), ensure_ascii=False)[:200]}...")
    diag = final.get("diagnosis_result") or {}
    print(f"  diagnosis.root_cause   = {diag.get('root_cause')!r}")
    print(f"  diagnosis.confidence  = {diag.get('confidence')!r}")
    print(f"  diagnosis.evidence     = {(diag.get('evidence') or [])[:3]}")
    print(f"  diagnosis.action       = {diag.get('recommended_action')!r}")
    val = final.get("diagnosis_validation_result") or {}
    print(f"  validation.passed      = {val.get('validation_passed')!r}")
    print(f"  validation.suggested   = {val.get('suggested_action')!r}")
    plan = final.get("planning_result") or {}
    print(f"  plan.final_plan        = {str(plan.get('final_plan'))[:200]!r}")
    sval = final.get("solution_validation_result") or {}
    print(f"  solution.valid         = {sval.get('solution_valid')!r}")
    print(f"  solution.risk_level    = {sval.get('risk_level')!r}")
    hr = final.get("human_review_result") or {}
    print(f"  human_review.decision  = {hr.get('decision')!r}")
    cl = final.get("closure_result") or {}
    print(f"  closure.summary        = {str(cl.get('closure_summary'))[:200]!r}")
    print()

    # ── LLM call log ─────────────────────────────────────────────────────
    print("=" * 70)
    print(f" LLM call log ({len(call_log)} calls)")
    print("=" * 70)
    for i, c in enumerate(call_log, 1):
        print(f"  {i:2d}. {c}")
    print()

    # ── Verdict ──────────────────────────────────────────────────────────
    print("=" * 70)
    print(" Verdict")
    print("=" * 70)
    deepseek_calls = [c for c in call_log if "deepseek.com" in c.get("base_url", "")]
    openrouter_calls = [c for c in call_log if "openrouter" in c.get("base_url", "")]
    print(f"  DeepSeek calls    : {len(deepseek_calls)}")
    print(f"  OpenRouter calls  : {len(openrouter_calls)} (expected for embed/ocr)")
    print(f"  Final status      : {final.get('status')!r}")

    ok = (
        len(deepseek_calls) >= 1
        and final.get("status") in ("closed", "human_reviewed")
        and final.get("diagnosis_result", {}).get("root_cause")
        and final.get("diagnosis_result", {}).get("root_cause") != "unknown"
    )
    print(f"  RESULT            : {'✓ PASS' if ok else '✗ FAIL'}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
