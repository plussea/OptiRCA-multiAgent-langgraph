import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TopologyManager:
    """Topology query wrapper for loading and querying topology data."""

    def __init__(self) -> None:
        self._topologies: Dict[str, Dict[str, Any]] = {}

    def load_topology(self, topology_id: str, file_path: str) -> None:
        """Load a topology file by ID."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._topologies[topology_id] = data
            logger.info("Loaded topology %s from %s", topology_id, file_path)
        except Exception as e:
            logger.warning("Failed to load topology %s: %s", topology_id, e)

    def get_topology(self, topology_id: str) -> Optional[Dict[str, Any]]:
        """Get topology data by ID."""
        return self._topologies.get(topology_id)

    def query_neighbors(self, topology_id: str, node_id: str) -> List[Dict[str, Any]]:
        """Query neighbor nodes for a given node in a topology."""
        topology = self._topologies.get(topology_id)
        if not topology:
            return []
        links = topology.get("links", [])
        nodes = topology.get("nodes", [])
        node_map = {n.get("id"): n for n in nodes}
        neighbors = []
        for link in links:
            if link.get("source") == node_id:
                neighbor = node_map.get(link.get("target"))
                if neighbor:
                    neighbors.append(neighbor)
            elif link.get("target") == node_id:
                neighbor = node_map.get(link.get("source"))
                if neighbor:
                    neighbors.append(neighbor)
        return neighbors


topology_manager = TopologyManager()
