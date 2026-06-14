"""E2E driver: run each subgraph manually, with verbose per-stage logging.

Why not use build_optigraph().ainvoke()?
  The parent graph's diagnosis-validation routing combined with LLM retry can
  loop in subtle ways. By invoking each subgraph directly, we get a clear
  pass/fail per stage and a clean demonstration that DeepSeek drives every
  LLM-dependent node.

Stages driven:
  1. perception         (no LLM, CSV parsing)
  2. diagnosis          (LLM: deepseek-v4-flash)  <-- the key call
  3. diagnosis_validation (LLM: deepseek-v4-flash) <-- second LLM call
  4. planning           (LLM: deepseek-v4-flash)
  5. solution_validation (LLM: deepseek-v4-flash)
  6. human_review       (synthetic: approved, no LLM)
  7. closure            (no LLM)
"""

import asyncio
import json
import logging
import os
import sys
import time
import traceback
import uuid
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
for name in ("optirc.core.llm_client", "optirc.graphs", "optirc.knowledge",
             "optirc.rag", "optirc.memory", "optirc.ingestion"):
    logging.getLogger(name).setLevel(logging.INFO)

# ── Track LLM calls with stage tags ─────────────────────────────────────
from optirc.core import llm_client as _llm_mod
from optirc.core.llm_client import LLMClient as _LLMClientClass

call_log: list = []
_orig_json = _LLMClientClass.generate_json
_orig_text = _LLMClientClass.generate_text
_orig_embed = _LLMClientClass.embed


async def _wrap_json(self, system, user_message, model=None, temperature=0.2, use_fallback=True):
    info = {
        "fn": "generate_json",
        "model": self.primary.model,
        "base_url": str(self.primary.client.base_url),
        "sys_chars": len(system),
        "user_chars": len(user_message),
    }
    t0 = time.time()
    try:
        out = await _orig_json(self, system, user_message, model, temperature, use_fallback)
        info["latency_s"] = round(time.time() - t0, 2)
        info["ok"] = True
        if isinstance(out, dict):
            info["out_keys"] = sorted(out.keys())
        call_log.append(info)
        print(f"  [LLM OK   ] {info['fn']}  {info['latency_s']}s  model={info['model']}  base={info['base_url']}")
        return out
    except Exception as e:
        info["latency_s"] = round(time.time() - t0, 2)
        info["ok"] = False
        info["err"] = f"{type(e).__name__}: {e}"
        call_log.append(info)
        print(f"  [LLM FAIL ] {info['fn']}  {info['latency_s']}s  err={info['err']}")
        raise


async def _wrap_text(self, system, user_message, model=None, temperature=0.2, use_fallback=True):
    info = {"fn": "generate_text", "model": self.primary.model,
            "base_url": str(self.primary.client.base_url)}
    t0 = time.time()
    try:
        out = await _orig_text(self, system, user_message, model, temperature, use_fallback)
        info["latency_s"] = round(time.time() - t0, 2)
        info["ok"] = True
        info["out_chars"] = len(out)
        call_log.append(info)
        print(f"  [LLM OK   ] {info['fn']}  {info['latency_s']}s  chars={info['out_chars']}")
        return out
    except Exception as e:
        info["err"] = f"{type(e).__name__}: {e}"
        call_log.append(info)
        print(f"  [LLM FAIL ] {info['fn']}  err={info['err']}")
        raise


async def _wrap_embed(self, texts):
    info = {"fn": "embed", "model": self.embedding.model,
            "base_url": str(self.embedding.client.base_url), "n": len(texts)}
    t0 = time.time()
    try:
        out = await _orig_embed(self, texts)
        info["latency_s"] = round(time.time() - t0, 2)
        info["ok"] = True
        info["dim"] = len(out[0]) if out else 0
        call_log.append(info)
        print(f"  [LLM OK   ] {info['fn']}  {info['latency_s']}s  dim={info['dim']}")
        return out
    except Exception as e:
        info["err"] = f"{type(e).__name__}: {e}"
        call_log.append(info)
        print(f"  [LLM FAIL ] {info['fn']}  err={info['err']}")
        raise


_LLMClientClass.generate_json = _wrap_json
_LLMClientClass.generate_text = _wrap_text
_LLMClientClass.embed = _wrap_embed


# ── Subgraph imports ────────────────────────────────────────────────────
from optirc.core.config import settings
from optirc.core.state import (
    PerceptionInternalState, DiagnosisInternalState,
    DiagnosisValidationInternalState, PlanningInternalState,
    SolutionValidationInternalState, HumanReviewInternalState,
    ClosureInternalState,
)
from optirc.graphs import parent as _parent
from optirc.graphs.subgraphs.perception import build_perception_subgraph
from optirc.graphs.subgraphs.diagnosis import build_diagnosis_subgraph
from optirc.graphs.subgraphs.diagnosis_validation import build_diagnosis_validation_subgraph
from optirc.graphs.subgraphs.planning import build_planning_subgraph
from optirc.graphs.subgraphs.solution_validation import build_solution_validation_subgraph
from optirc.graphs.subgraphs.human_review import build_human_review_subgraph
from optirc.graphs.subgraphs.closure import build_closure_subgraph

perception_subgraph = build_perception_subgraph()
diagnosis_subgraph = build_diagnosis_subgraph()
diagnosis_validation_subgraph = build_diagnosis_validation_subgraph()
planning_subgraph = build_planning_subgraph()
solution_validation_subgraph = build_solution_validation_subgraph()
human_review_subgraph = build_human_review_subgraph()
closure_subgraph = build_closure_subgraph()


DEMO_CSV = ROOT / "input" / "data" / "true_data" / "alarm_log_demo.csv"


async def main() -> int:
    print("=" * 72)
    print(" OptiGraph E2E (per-subgraph, DeepSeek)")
    print("=" * 72)
    print(f" Demo CSV  : {DEMO_CSV} (exists={DEMO_CSV.exists()})")
    print(f" Primary   : {settings.llm_model} @ {settings.llm_base_url}")
    print(f" Backup    : {settings.llm_backup_model} @ {settings.llm_backup_base_url}")
    print(f" Embed base: openrouter  OCR base: openrouter  (via env fallback)")
    print()

    if not DEMO_CSV.exists():
        print("!! demo CSV missing"); return 1

    session_id = "smoke-e2e-" + uuid.uuid4().hex[:8]

    # ── 1. perception ────────────────────────────────────────────────────
    print(f"── [1/7] perception (session={session_id})")
    p_in: PerceptionInternalState = {
        "raw_input": str(DEMO_CSV.absolute()),
        "input_type": None, "detected_encoding": None,
        "raw_rows": None, "normalized_headers": None, "header_aliases": None,
        "topology_ids": None, "ocr_text": None, "perception_summary": None,
    }
    p_out = await perception_subgraph.ainvoke(p_in)
    summary = p_out.get("perception_summary", {})
    print(f"   rows={summary.get('raw_rows_count')}  alarm_type={summary.get('alarm_type')!r}  "
          f"device={summary.get('device_id')!r}  unique_types={summary.get('unique_alarm_types')}")
    print()

    # ── 2. diagnosis ─────────────────────────────────────────────────────
    print(f"── [2/7] diagnosis (LLM)")
    d_in: DiagnosisInternalState = {
        "perception_summary": summary,
        "query_text": None, "query_embedding": None,
        "retrieved_docs": None, "kg_subgraph": None,
        "candidate_causes": None, "reasoning_chain": None, "llm_raw_output": None,
        "root_cause": None, "confidence": None, "evidence": None, "recommended_action": None,
    }
    try:
        d_out = await diagnosis_subgraph.ainvoke(d_in)
    except Exception as e:
        print(f"   !! diagnosis failed: {e}")
        d_out = {"root_cause": "unknown", "confidence": 0.0, "evidence": [], "recommended_action": str(e)}
    print(f"   root_cause={d_out.get('root_cause')!r}  conf={d_out.get('confidence')}  "
          f"action={str(d_out.get('recommended_action'))[:100]!r}")
    print()

    # ── 3. diagnosis_validation ──────────────────────────────────────────
    print(f"── [3/7] diagnosis_validation (LLM)")
    v_in: DiagnosisValidationInternalState = {
        "diagnosis_result": {
            "root_cause": d_out.get("root_cause"),
            "confidence": d_out.get("confidence"),
            "evidence": d_out.get("evidence") or [],
            "recommended_action": d_out.get("recommended_action"),
        },
        "confidence_threshold": 0.6,
        "evidence_completeness_score": None, "llm_revalidation_output": None,
        "validation_passed": None, "validation_notes": None, "suggested_action": None,
    }
    try:
        v_out = await diagnosis_validation_subgraph.ainvoke(v_in)
    except Exception as e:
        print(f"   !! validation failed: {e}")
        v_out = {"validation_passed": False, "validation_notes": str(e), "suggested_action": "needs_human"}
    print(f"   passed={v_out.get('validation_passed')}  suggested={v_out.get('suggested_action')!r}  "
          f"notes={str(v_out.get('validation_notes'))[:120]!r}")
    print()

    # ── 4. planning ──────────────────────────────────────────────────────
    print(f"── [4/7] planning (LLM)")
    pl_in: PlanningInternalState = {
        "diagnosis_result": v_in["diagnosis_result"],
        "diagnosis_validation": v_out,
        "retrieved_sops": None, "candidate_plans": None, "risk_assessment": None,
        "final_plan": None, "rollback_procedure": None,
    }
    try:
        pl_out = await planning_subgraph.ainvoke(pl_in)
    except Exception as e:
        print(f"   !! planning failed: {e}")
        pl_out = {"final_plan": None, "rollback_procedure": None}
    print(f"   final_plan={str(pl_out.get('final_plan'))[:200]!r}")
    print()

    # ── 5. solution_validation ───────────────────────────────────────────
    print(f"── [5/7] solution_validation (LLM)")
    sv_in: SolutionValidationInternalState = {
        "planning_result": pl_out,
        "diagnosis_result": v_in["diagnosis_result"],
        "consistency_matrix": None, "feasibility_score": None,
        "resource_match_check": None, "llm_evaluation_output": None,
        "solution_valid": None, "risk_level": None, "validation_notes": None,
        "needs_replan": None,
    }
    try:
        sv_out = await solution_validation_subgraph.ainvoke(sv_in)
    except Exception as e:
        print(f"   !! solution_validation failed: {e}")
        sv_out = {"solution_valid": False, "risk_level": "unknown", "needs_replan": False,
                  "validation_notes": str(e)}
    print(f"   valid={sv_out.get('solution_valid')}  risk={sv_out.get('risk_level')!r}  "
          f"replan={sv_out.get('needs_replan')}")
    print()

    # ── 6. human_review (synthetic) ──────────────────────────────────────
    print(f"── [6/7] human_review (synthetic approved)")
    hr_in: HumanReviewInternalState = {
        "session_id": session_id,
        "planning_result": pl_out,
        "solution_validation": sv_out,
        "diagnosis_result": v_in["diagnosis_result"],
        "review_package": None, "decision": None,
        "reviewer_notes": None, "approved_at": None,
    }
    # human_review subgraph calls interrupt(). We invoke only the prepare node,
    # then synthetic-approve.
    hr_out = await human_review_subgraph.ainvoke(hr_in)  # will hit interrupt
    print(f"   decision={hr_out.get('decision')!r}  notes={hr_out.get('reviewer_notes')!r}")
    # If interrupt was hit, substitute a synthetic approved result
    if hr_out.get("decision") is None or hr_out.get("decision") == "escalated":
        print("   (interrupt paused; injecting synthetic approved decision)")
        hr_out = {"decision": "approved", "reviewer_notes": "smoke-test approved", "approved_at": "synthetic"}
    print()

    # ── 7. closure ───────────────────────────────────────────────────────
    print(f"── [7/7] closure")
    c_in: ClosureInternalState = {
        "session_id": session_id,
        "full_case": {
            "perception": summary, "diagnosis": v_in["diagnosis_result"],
            "diagnosis_validation": v_out, "planning": pl_out,
            "solution_validation": sv_out, "human_review": hr_out,
        },
        "extracted_knowledge": None, "stored_to_vector_db": None,
        "stored_to_graph_db": None, "closure_summary": None,
    }
    try:
        c_out = await closure_subgraph.ainvoke(c_in)
    except Exception as e:
        print(f"   !! closure failed: {e}")
        c_out = {"closure_summary": None, "stored_to_vector_db": False, "stored_to_graph_db": False}
    print(f"   summary={str(c_out.get('closure_summary'))[:160]!r}")
    print(f"   stored_to_vector_db={c_out.get('stored_to_vector_db')}  "
          f"stored_to_graph_db={c_out.get('stored_to_graph_db')}")
    print()

    # ── Summary ──────────────────────────────────────────────────────────
    print("=" * 72)
    print(" LLM call log")
    print("=" * 72)
    deepseek = [c for c in call_log if "deepseek.com" in c.get("base_url", "")]
    or_      = [c for c in call_log if "openrouter" in c.get("base_url", "")]
    ok       = [c for c in call_log if c.get("ok")]
    failed   = [c for c in call_log if not c.get("ok")]
    for c in call_log:
        flag = "OK  " if c.get("ok") else "FAIL"
        print(f"  [{flag}] {c['fn']:<14} model={c.get('model')!r:<28} base={c.get('base_url','?')}")
    print()
    print(f"  Total: {len(call_log)}   OK: {len(ok)}   FAIL: {len(failed)}")
    print(f"  DeepSeek: {len(deepseek)}    OpenRouter: {len(or_)}")
    print()
    print("=" * 72)
    print(" Verdict")
    print("=" * 72)
    print(f"  Diagnosis root_cause : {d_out.get('root_cause')!r}")
    print(f"  Diagnosis confidence : {d_out.get('confidence')}")
    print(f"  Validation passed    : {v_out.get('validation_passed')}")
    print(f"  Human decision       : {hr_out.get('decision')!r}")
    print(f"  Closure stored       : vec={c_out.get('stored_to_vector_db')}  kg={c_out.get('stored_to_graph_db')}")

    has_real_diagnosis = (
        d_out.get("root_cause")
        and d_out.get("root_cause") != "unknown"
        and (d_out.get("confidence") or 0) > 0
    )
    has_deepseek = len(deepseek) >= 2  # diagnosis + validation at minimum
    ok_flag = has_real_diagnosis and has_deepseek and len(failed) == 0
    print(f"\n  RESULT: {'✓ PASS' if ok_flag else '✗ FAIL'}")
    return 0 if ok_flag else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
