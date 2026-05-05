import pytest
from optirc.core.state import PerceptionInternalState


@pytest.mark.asyncio
async def test_perception_csv(perception_subgraph):
    state: PerceptionInternalState = {
        "raw_input": "tests/data/test.csv",
        "detected_encoding": None,
        "raw_rows": None,
        "normalized_headers": None,
        "topology_ids": None,
        "ocr_text": None,
        "perception_summary": None,
    }
    result = await perception_subgraph.ainvoke(state)
    assert "perception_summary" in result
