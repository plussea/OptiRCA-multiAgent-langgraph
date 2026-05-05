import pytest
from optirc.graphs.parent import build_optigraph


@pytest.mark.asyncio
async def test_build_optigraph():
    graph = build_optigraph()
    assert graph is not None
    assert graph.checkpointer is not None
