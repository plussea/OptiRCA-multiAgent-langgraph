"""Hybrid Orchestration Framework: Compile-time Skeleton + Runtime Flesh.

This module implements the formal hybrid orchestration graph H = (V, E, τ)
where:
- V = V_s ∪ V_d: nodes are partitioned into static (deterministic) and dynamic (probabilistic)
- E ⊆ V × V: edges are fixed at compile time
- τ: V → {static, dynamic}: node type mapping

Key Properties:
- Lemma 1 (Path Reproducibility): For any input x, if all dynamic nodes produce
deterministic output given the same context, the execution path P(x) is predictable.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class NodeType(Enum):
    """Node type in hybrid orchestration graph."""

    STATIC = "static"      # Deterministic: rule_check, validation, routing
    DYNAMIC = "dynamic"    # Probabilistic: LLM inference, semantic generation


@dataclass
class NodeDefinition:
    """Definition of a node in the hybrid orchestration graph."""

    name: str
    node_type: NodeType
    description: str = ""
    is_subgraph_wrapper: bool = False
    internal_nodes: List[str] = field(default_factory=list)


@dataclass
class EdgeDefinition:
    """Definition of an edge in the hybrid orchestration graph."""

    source: str
    target: str
    edge_type: str = "sequential"  # sequential, conditional, interrupt
    condition: Optional[str] = None


class HybridOrchestrationGraph:
    """Formal hybrid orchestration graph H = (V, E, τ).

    This class documents and validates the compile-time structure of the graph,
    distinguishing static skeleton from dynamic flesh.
    """

    # OptiGraph node definitions
    NODES: Dict[str, NodeDefinition] = {
        # Static nodes (V_s): deterministic, compile-time fixed
        "perception": NodeDefinition(
            name="perception",
            node_type=NodeType.STATIC,
            description="Input parsing and normalization (deterministic routing)",
            is_subgraph_wrapper=True,
            internal_nodes=["detect_input_type", "parse_csv", "parse_ocr", "normalize"],
        ),
        "diagnosis_validation": NodeDefinition(
            name="diagnosis_validation",
            node_type=NodeType.STATIC,
            description="Diagnosis validation with rule checks and routing",
            is_subgraph_wrapper=True,
            internal_nodes=["rule_check", "llm_revalidate", "finalize_validation"],
        ),
        "solution_validation": NodeDefinition(
            name="solution_validation",
            node_type=NodeType.STATIC,
            description="Solution validation with consistency/feasibility checks",
            is_subgraph_wrapper=True,
            internal_nodes=["consistency_check", "feasibility_check", "risk_evaluation", "finalize"],
        ),
        "human_review": NodeDefinition(
            name="human_review",
            node_type=NodeType.STATIC,
            description="HITL checkpoint with interrupt() deterministic semantics",
            is_subgraph_wrapper=True,
            internal_nodes=["prepare_review", "wait_human_decision"],
        ),
        "closure": NodeDefinition(
            name="closure",
            node_type=NodeType.STATIC,
            description="Knowledge extraction and storage (deterministic orchestration)",
            is_subgraph_wrapper=True,
            internal_nodes=["extract_knowledge", "store_vector", "store_graph", "summarize"],
        ),
        # Dynamic nodes (V_d): probabilistic, LLM-based
        "diagnosis": NodeDefinition(
            name="diagnosis",
            node_type=NodeType.DYNAMIC,
            description="Root cause analysis with LLM reasoning (CoT hidden)",
            is_subgraph_wrapper=True,
            internal_nodes=["build_query", "retrieve_rag", "retrieve_kg", "analyze", "finalize"],
        ),
        "planning": NodeDefinition(
            name="planning",
            node_type=NodeType.DYNAMIC,
            description="Fix plan generation with LLM (probabilistic output)",
            is_subgraph_wrapper=True,
            internal_nodes=["retrieve_sops", "generate_candidates", "assess_risk", "finalize_plan"],
        ),
    }

    # OptiGraph edge definitions (compile-time fixed)
    EDGES: List[EdgeDefinition] = [
        EdgeDefinition("perception", "diagnosis", "sequential"),
        EdgeDefinition("diagnosis", "diagnosis_validation", "sequential"),
        EdgeDefinition("diagnosis_validation", "planning", "conditional", "action=proceed"),
        EdgeDefinition("diagnosis_validation", "diagnosis", "conditional", "action=retry_diagnosis"),
        EdgeDefinition("diagnosis_validation", "human_review", "conditional", "action=needs_human"),
        EdgeDefinition("planning", "solution_validation", "sequential"),
        EdgeDefinition("solution_validation", "planning", "conditional", "needs_replan=true"),
        EdgeDefinition("solution_validation", "human_review", "conditional", "needs_replan=false"),
        EdgeDefinition("human_review", "closure", "conditional", "decision=approved"),
        EdgeDefinition("human_review", "planning", "conditional", "decision=rejected"),
        EdgeDefinition("human_review", "END", "conditional", "decision=escalated"),
        EdgeDefinition("closure", "END", "sequential"),
    ]

    def __init__(self):
        self._validate_graph()

    def _validate_graph(self) -> None:
        """Validate graph structure at compile time."""
        node_names = set(self.NODES.keys())
        for edge in self.EDGES:
            if edge.source not in node_names and edge.source != "END":
                raise ValueError(f"Invalid edge source: {edge.source}")
            if edge.target not in node_names and edge.target != "END":
                raise ValueError(f"Invalid edge target: {edge.target}")
        logger.info("HybridOrchestrationGraph validated: %d nodes, %d edges",
                    len(self.NODES), len(self.EDGES))

    @property
    def static_nodes(self) -> List[str]:
        """V_s: Static (deterministic) nodes."""
        return [n.name for n in self.NODES.values() if n.node_type == NodeType.STATIC]

    @property
    def dynamic_nodes(self) -> List[str]:
        """V_d: Dynamic (probabilistic) nodes."""
        return [n.name for n in self.NODES.values() if n.node_type == NodeType.DYNAMIC]

    @property
    def all_nodes(self) -> List[str]:
        """V: All nodes."""
        return list(self.NODES.keys())

    def get_node_type(self, node_name: str) -> Optional[NodeType]:
        """τ: V → {static, dynamic}."""
        node = self.NODES.get(node_name)
        return node.node_type if node else None

    def is_static(self, node_name: str) -> bool:
        """Check if node is static (deterministic)."""
        return self.get_node_type(node_name) == NodeType.STATIC

    def is_dynamic(self, node_name: str) -> bool:
        """Check if node is dynamic (probabilistic)."""
        return self.get_node_type(node_name) == NodeType.DYNAMIC

    def get_outgoing_edges(self, node_name: str) -> List[EdgeDefinition]:
        """Get all outgoing edges from a node."""
        return [e for e in self.EDGES if e.source == node_name]

    def get_incoming_edges(self, node_name: str) -> List[EdgeDefinition]:
        """Get all incoming edges to a node."""
        return [e for e in self.EDGES if e.target == node_name]

    def get_possible_next_nodes(self, node_name: str) -> List[str]:
        """Get all possible next nodes (for path prediction)."""
        return [e.target for e in self.get_outgoing_edges(node_name)]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize graph structure."""
        return {
            "nodes": {
                name: {
                    "type": n.node_type.value,
                    "description": n.description,
                    "is_subgraph_wrapper": n.is_subgraph_wrapper,
                    "internal_nodes": n.internal_nodes,
                }
                for name, n in self.NODES.items()
            },
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "type": e.edge_type,
                    "condition": e.condition,
                }
                for e in self.EDGES
            ],
            "static_nodes": self.static_nodes,
            "dynamic_nodes": self.dynamic_nodes,
        }


# Global instance
hybrid_graph = HybridOrchestrationGraph()
