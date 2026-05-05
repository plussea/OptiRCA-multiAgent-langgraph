import pytest
from optirc.core.state import DiagnosisValidationInternalState


@pytest.mark.asyncio
async def test_diagnosis_validation_proceed(diagnosis_validation_subgraph):
    state: DiagnosisValidationInternalState = {
        "diagnosis_result": {
            "root_cause": "fiber_cut",
            "confidence": 0.85,
            "evidence": ["alarm_log", "otdr_trace"],
        },
        "confidence_threshold": 0.6,
        "evidence_completeness_score": None,
        "llm_revalidation_output": None,
        "validation_passed": None,
        "validation_notes": None,
        "suggested_action": None,
    }
    result = await diagnosis_validation_subgraph.ainvoke(state)
    assert "validation_passed" in result
    assert "suggested_action" in result
