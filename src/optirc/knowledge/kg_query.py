import logging
from typing import Any, Dict, List

from optirc.knowledge.neo4j_client import neo4j_client

logger = logging.getLogger(__name__)


class KGQueryService:
    """Knowledge graph query service."""

    async def get_subgraph(self, topology_ids: List[str], depth: int = 2) -> Dict[str, Any]:
        """Query Neo4j for subgraph around given topology IDs."""
        if not topology_ids:
            return {"nodes": [], "relationships": []}

        nodes = []
        relationships = []

        for topo_id in topology_ids:
            try:
                # Query nodes
                node_results = await neo4j_client.query(
                    "MATCH (n {topology_id: $topology_id}) RETURN n LIMIT 50",
                    {"topology_id": topo_id},
                )
                for r in node_results:
                    node = r.get("n", {})
                    if hasattr(node, "_properties"):
                        nodes.append(dict(node._properties))
                    elif isinstance(node, dict):
                        nodes.append(node)

                # Query relationships up to depth
                rel_results = await neo4j_client.query(
                    """
                    MATCH (n {topology_id: $topology_id})-[r*1..$depth]-(m)
                    RETURN n, r, m LIMIT 100
                    """,
                    {"topology_id": topo_id, "depth": depth},
                )
                for r in rel_results:
                    rel_list = r.get("r", [])
                    if not isinstance(rel_list, list):
                        rel_list = [rel_list]
                    for rel in rel_list:
                        if hasattr(rel, "_properties"):
                            relationships.append(dict(rel._properties))
                        elif isinstance(rel, dict):
                            relationships.append(rel)
            except Exception as e:
                logger.warning("KG subgraph query failed for %s: %s", topo_id, e)

        return {"nodes": nodes, "relationships": relationships}

    async def add_case_knowledge(
        self,
        session_id: str,
        root_cause: str,
        device_ids: List[str],
    ) -> bool:
        """Add case knowledge to graph database."""
        try:
            await neo4j_client.query(
                """
                MERGE (c:Case {session_id: $session_id})
                SET c.root_cause = $root_cause
                WITH c
                UNWIND $device_ids AS device_id
                MERGE (d:Device {id: device_id})
                MERGE (c)-[:AFFECTS]->(d)
                """,
                {"session_id": session_id, "root_cause": root_cause, "device_ids": device_ids},
            )
            return True
        except Exception as e:
            logger.warning("Failed to add case knowledge: %s", e)
            return False


kg_query_service = KGQueryService()
