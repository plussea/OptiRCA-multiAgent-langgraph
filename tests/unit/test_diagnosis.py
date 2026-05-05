import pytest
from optirc.core.state import DiagnosisInternalState


@pytest.mark.asyncio
async def test_diagnosis_subgraph(diagnosis_subgraph):
    state: DiagnosisInternalState = {
        "perception_summary": {
            "alarm_type": "power_loss",
            "device_id": "node_01",
            "description": "sudden power drop",
            "topology_ids": ["topo_1"],
        },
        "query_text": None,
        "query_embedding": None,
        "retrieved_docs": None,
        "kg_subgraph": None,
        "candidate_causes": None,
        "reasoning_chain": None,
        "llm_raw_output": None,
        "root_cause": None,
        "confidence": None,
        "evidence": None,
        "recommended_action": None,
    }
    result = await diagnosis_subgraph.ainvoke(state)
    assert "root_cause" in result
    assert "confidence" in result
