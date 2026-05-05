from typing import Any, Dict, List, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import Annotated
from typing_extensions import TypedDict


# Parent graph global state
class OverallState(TypedDict):
    session_id: str
    raw_input: str
    status: str
    perception_result: Optional[Dict[str, Any]]
    diagnosis_result: Optional[Dict[str, Any]]
    diagnosis_validation_result: Optional[Dict[str, Any]]
    planning_result: Optional[Dict[str, Any]]
    solution_validation_result: Optional[Dict[str, Any]]
    human_review_result: Optional[Dict[str, Any]]
    closure_result: Optional[Dict[str, Any]]
    pending_human: bool
    human_decision: Optional[str]
    error_message: Optional[str]
    messages: Annotated[List[BaseMessage], add_messages]


# Perception subgraph
class PerceptionInternalState(TypedDict):
    raw_input: str
    detected_encoding: Optional[str]
    raw_rows: Optional[List[Dict[str, Any]]]
    normalized_headers: Optional[List[str]]
    topology_ids: Optional[List[str]]
    ocr_text: Optional[str]
    perception_summary: Optional[Dict[str, Any]]


# Diagnosis subgraph
class DiagnosisInternalState(TypedDict):
    perception_summary: Dict[str, Any]
    query_text: Optional[str]
    query_embedding: Optional[List[float]]
    retrieved_docs: Optional[List[Dict[str, Any]]]
    kg_subgraph: Optional[Dict[str, Any]]
    candidate_causes: Optional[List[Dict[str, Any]]]
    reasoning_chain: Optional[str]
    llm_raw_output: Optional[str]
    root_cause: Optional[str]
    confidence: Optional[float]
    evidence: Optional[List[str]]
    recommended_action: Optional[str]


# Diagnosis validation subgraph
class DiagnosisValidationInternalState(TypedDict):
    diagnosis_result: Dict[str, Any]
    confidence_threshold: float
    evidence_completeness_score: Optional[float]
    llm_revalidation_output: Optional[str]
    validation_passed: Optional[bool]
    validation_notes: Optional[str]
    suggested_action: Optional[str]


# Planning subgraph
class PlanningInternalState(TypedDict):
    diagnosis_result: Dict[str, Any]
    diagnosis_validation: Dict[str, Any]
    retrieved_sops: Optional[List[Dict[str, Any]]]
    candidate_plans: Optional[List[Dict[str, Any]]]
    risk_assessment: Optional[str]
    final_plan: Optional[Dict[str, Any]]
    rollback_procedure: Optional[str]


# Solution validation subgraph
class SolutionValidationInternalState(TypedDict):
    planning_result: Dict[str, Any]
    diagnosis_result: Dict[str, Any]
    consistency_matrix: Optional[Dict[str, Any]]
    feasibility_score: Optional[float]
    resource_match_check: Optional[bool]
    llm_evaluation_output: Optional[str]
    solution_valid: Optional[bool]
    risk_level: Optional[str]
    validation_notes: Optional[str]
    needs_replan: Optional[bool]


# Human review subgraph
class HumanReviewInternalState(TypedDict):
    session_id: str
    planning_result: Dict[str, Any]
    solution_validation: Dict[str, Any]
    diagnosis_result: Dict[str, Any]
    review_package: Optional[Dict[str, Any]]
    decision: Optional[str]
    reviewer_notes: Optional[str]
    approved_at: Optional[str]


# Closure subgraph
class ClosureInternalState(TypedDict):
    session_id: str
    full_case: Dict[str, Any]
    extracted_knowledge: Optional[List[Dict[str, Any]]]
    stored_to_vector_db: Optional[bool]
    stored_to_graph_db: Optional[bool]
    closure_summary: Optional[str]
