import pytest
from optirc.core.state import SolutionValidationInternalState


@pytest.mark.asyncio
async def test_solution_validation(solution_validation_subgraph):
    state: SolutionValidationInternalState = {
        "planning_result": {
            "final_plan": {
                "steps": ["check fiber cable", "replace damaged section"],
                "required_resources": ["fiber_splicer"],
            },
        },
        "diagnosis_result": {
            "root_cause": "fiber_cut",
        },
        "consistency_matrix": None,
        "feasibility_score": None,
        "resource_match_check": None,
        "llm_evaluation_output": None,
        "solution_valid": None,
        "risk_level": None,
        "validation_notes": None,
        "needs_replan": None,
    }
    result = await solution_validation_subgraph.ainvoke(state)
    assert "solution_valid" in result
    assert "risk_level" in result
