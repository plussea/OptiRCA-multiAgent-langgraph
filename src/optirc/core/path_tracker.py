"""Path Tracker: Execution path tracing and reproducibility validation.

Implements:
- Path recording during graph execution
- Path reproducibility rate calculation (Lemma 1)
- Path comparison and prediction
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from optirc.core.orchestration import NodeType, hybrid_graph

logger = logging.getLogger(__name__)


@dataclass
class PathStep:
    """A single step in an execution path."""

    node_name: str
    node_type: str
    timestamp: str
    input_hash: Optional[str] = None
    output_summary: Optional[str] = None
    routing_decision: Optional[str] = None


@dataclass
class ExecutionPath:
    """Complete execution path for a single case."""

    session_id: str
    path_id: str
    steps: List[PathStep] = field(default_factory=list)
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    input_hash: Optional[str] = None
    status: str = "in_progress"  # in_progress, completed, failed

    def add_step(self, node_name: str, node_type: str, routing_decision: Optional[str] = None) -> None:
        """Add a step to the path."""
        step = PathStep(
            node_name=node_name,
            node_type=node_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            routing_decision=routing_decision,
        )
        self.steps.append(step)

    def get_node_sequence(self) -> List[str]:
        """Get the sequence of node names."""
        return [step.node_name for step in self.steps]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "path_id": self.path_id,
            "steps": [
                {
                    "node_name": s.node_name,
                    "node_type": s.node_type,
                    "timestamp": s.timestamp,
                    "routing_decision": s.routing_decision,
                }
                for s in self.steps
            ],
            "start_time": self.start_time,
            "end_time": self.end_time,
            "input_hash": self.input_hash,
            "status": self.status,
        }


class PathTracker:
    """Track execution paths and validate reproducibility."""

    def __init__(self):
        self._active_paths: Dict[str, ExecutionPath] = {}
        self._completed_paths: List[ExecutionPath] = []

    def start_path(self, session_id: str, input_hash: Optional[str] = None) -> ExecutionPath:
        """Start tracking a new execution path."""
        path_id = f"{session_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        path = ExecutionPath(
            session_id=session_id,
            path_id=path_id,
            start_time=datetime.now(timezone.utc).isoformat(),
            input_hash=input_hash,
        )
        self._active_paths[session_id] = path
        logger.info("Started path tracking for session %s", session_id)
        return path

    def record_step(self, session_id: str, node_name: str, routing_decision: Optional[str] = None) -> None:
        """Record a step in the active path."""
        path = self._active_paths.get(session_id)
        if not path:
            logger.warning("No active path for session %s", session_id)
            return

        node_type = hybrid_graph.get_node_type(node_name)
        type_str = node_type.value if node_type else "unknown"
        path.add_step(node_name, type_str, routing_decision)
        logger.debug("Recorded step: %s (%s)", node_name, type_str)

    def complete_path(self, session_id: str, status: str = "completed") -> Optional[ExecutionPath]:
        """Complete the active path."""
        path = self._active_paths.pop(session_id, None)
        if path:
            path.end_time = datetime.now(timezone.utc).isoformat()
            path.status = status
            self._completed_paths.append(path)
            logger.info("Completed path for session %s: %d steps", session_id, len(path.steps))
        return path

    def get_active_path(self, session_id: str) -> Optional[ExecutionPath]:
        """Get the active path for a session."""
        return self._active_paths.get(session_id)

    def get_completed_paths(self) -> List[ExecutionPath]:
        """Get all completed paths."""
        return self._completed_paths.copy()

    def predict_path(self, input_hash: str) -> Optional[List[str]]:
        """Predict path based on historical data with same input."""
        matching_paths = [
            p for p in self._completed_paths
            if p.input_hash == input_hash and p.status == "completed"
        ]
        if not matching_paths:
            return None

        # Return the most common path
        path_sequences = [tuple(p.get_node_sequence()) for p in matching_paths]
        from collections import Counter
        most_common = Counter(path_sequences).most_common(1)[0][0]
        return list(most_common)

    def calculate_reproducibility_rate(self, input_hash: Optional[str] = None) -> float:
        """Calculate path reproducibility rate (Lemma 1 metric).

        For a given input, run N times and measure how many produce identical paths.
        If input_hash is None, calculate across all inputs.
        """
        paths = self._completed_paths
        if input_hash:
            paths = [p for p in paths if p.input_hash == input_hash]

        if len(paths) < 2:
            return 1.0  # Single path is trivially reproducible

        # Group by input hash
        from collections import defaultdict, Counter
        by_input: Dict[str, List[ExecutionPath]] = defaultdict(list)
        for p in paths:
            by_input[p.input_hash or "unknown"].append(p)

        total_groups = 0
        reproducible_groups = 0

        for input_key, group in by_input.items():
            if len(group) < 2:
                continue
            total_groups += 1
            sequences = [tuple(p.get_node_sequence()) for p in group]
            most_common_count = Counter(sequences).most_common(1)[0][1]
            if most_common_count == len(group):
                reproducible_groups += 1

        if total_groups == 0:
            return 1.0

        return reproducible_groups / total_groups

    def get_path_statistics(self) -> Dict[str, Any]:
        """Get statistics about tracked paths."""
        all_paths = self._completed_paths + list(self._active_paths.values())
        if not all_paths:
            return {"total_paths": 0}

        path_lengths = [len(p.steps) for p in all_paths]
        static_steps = sum(
            1 for p in all_paths for s in p.steps if s.node_type == "static"
        )
        dynamic_steps = sum(
            1 for p in all_paths for s in p.steps if s.node_type == "dynamic"
        )

        return {
            "total_paths": len(all_paths),
            "completed_paths": len(self._completed_paths),
            "active_paths": len(self._active_paths),
            "avg_path_length": sum(path_lengths) / len(path_lengths),
            "min_path_length": min(path_lengths),
            "max_path_length": max(path_lengths),
            "total_static_steps": static_steps,
            "total_dynamic_steps": dynamic_steps,
            "reproducibility_rate": self.calculate_reproducibility_rate(),
        }

    def export_paths(self, filepath: str) -> None:
        """Export all paths to JSON."""
        data = {
            "paths": [p.to_dict() for p in self._completed_paths],
            "statistics": self.get_path_statistics(),
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("Exported %d paths to %s", len(self._completed_paths), filepath)


# Global instance
path_tracker = PathTracker()
