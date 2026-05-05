import pytest
from optirc.graphs.subgraphs.closure import build_closure_subgraph
from optirc.graphs.subgraphs.diagnosis import build_diagnosis_subgraph
from optirc.graphs.subgraphs.diagnosis_validation import build_diagnosis_validation_subgraph
from optirc.graphs.subgraphs.human_review import build_human_review_subgraph
from optirc.graphs.subgraphs.perception import build_perception_subgraph
from optirc.graphs.subgraphs.planning import build_planning_subgraph
from optirc.graphs.subgraphs.solution_validation import build_solution_validation_subgraph


@pytest.fixture
def perception_subgraph():
    return build_perception_subgraph()


@pytest.fixture
def diagnosis_subgraph():
    return build_diagnosis_subgraph()


@pytest.fixture
def diagnosis_validation_subgraph():
    return build_diagnosis_validation_subgraph()


@pytest.fixture
def planning_subgraph():
    return build_planning_subgraph()


@pytest.fixture
def solution_validation_subgraph():
    return build_solution_validation_subgraph()


@pytest.fixture
def human_review_subgraph():
    return build_human_review_subgraph()


@pytest.fixture
def closure_subgraph():
    return build_closure_subgraph()
