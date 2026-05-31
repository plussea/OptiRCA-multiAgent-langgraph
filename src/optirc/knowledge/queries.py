"""Enhanced knowledge graph query service with advanced query capabilities."""

import logging
from typing import Any, Dict, List, Optional

from optirc.knowledge.neo4j_client import neo4j_client

logger = logging.getLogger(__name__)


class KGQueryService:
    """Advanced knowledge graph query service."""

    # ── Basic Queries ──

    async def get_subgraph(
        self,
        topology_ids: List[str],
        depth: int = 2,
    ) -> Dict[str, Any]:
        """Query Neo4j for subgraph around given topology IDs."""
        if not topology_ids:
            return {"nodes": [], "relationships": []}

        nodes = []
        relationships = []
        seen_nodes = set()
        seen_rels = set()

        for topo_id in topology_ids:
            try:
                # Query nodes by topology_id or name
                node_results = await neo4j_client.query(
                    """
                    MATCH (n)
                    WHERE n.topology_id = $topology_id OR n.name = $topology_id OR n.id = $topology_id
                    RETURN n LIMIT 50
                    """,
                    {"topology_id": topo_id},
                )
                for r in node_results:
                    node = r.get("n", {})
                    props = dict(node._properties) if hasattr(node, "_properties") else dict(node)
                    node_id = props.get("id", "")
                    if node_id and node_id not in seen_nodes:
                        nodes.append(props)
                        seen_nodes.add(node_id)

                # Query relationships up to depth using variable-length paths
                rel_results = await neo4j_client.query(
                    f"""
                    MATCH (n)-[r*1..{depth}]-(m)
                    WHERE n.topology_id = $topology_id OR n.name = $topology_id OR n.id = $topology_id
                    RETURN n, r, m LIMIT 100
                    """,
                    {"topology_id": topo_id},
                )
                for r in rel_results:
                    # Extract nodes
                    for key in ["n", "m"]:
                        node = r.get(key, {})
                        props = dict(node._properties) if hasattr(node, "_properties") else dict(node)
                        node_id = props.get("id", "")
                        if node_id and node_id not in seen_nodes:
                            nodes.append(props)
                            seen_nodes.add(node_id)

                    # Extract relationships (r is a list for variable-length)
                    rel_list = r.get("r", [])
                    if not isinstance(rel_list, list):
                        rel_list = [rel_list]
                    for rel in rel_list:
                        rel_id = id(rel)  # Use Python object id as unique key
                        if rel_id not in seen_rels:
                            seen_rels.add(rel_id)
                            rel_props = dict(rel._properties) if hasattr(rel, "_properties") else dict(rel)
                            rel_type = rel.type if hasattr(rel, "type") else ""
                            relationships.append({
                                **rel_props,
                                "type": rel_type,
                                "start_node": rel.start_node.id if hasattr(rel, "start_node") else "",
                                "end_node": rel.end_node.id if hasattr(rel, "end_node") else "",
                            })
            except Exception as e:
                logger.warning("KG subgraph query failed for %s: %s", topo_id, e)

        return {
            "nodes": nodes,
            "relationships": relationships,
            "statistics": {
                "node_count": len(nodes),
                "relationship_count": len(relationships),
                "query_depth": depth,
            },
        }

    # ── Case Knowledge ──

    async def add_case_knowledge(
        self,
        session_id: str,
        root_cause: str,
        device_ids: List[str],
    ) -> bool:
        """Add case knowledge to graph database (legacy method)."""
        try:
            await neo4j_client.query(
                """
                MERGE (c:Case {session_id: $session_id})
                SET c.root_cause = $root_cause, c.id = $session_id
                WITH c
                UNWIND $device_ids AS device_id
                MERGE (d:Device {id: device_id})
                SET d.name = device_id
                MERGE (c)-[:AFFECTS]->(d)
                """,
                {"session_id": session_id, "root_cause": root_cause, "device_ids": device_ids},
            )
            return True
        except Exception as e:
            logger.warning("Failed to add case knowledge: %s", e)
            return False

    # ── Advanced Queries ──

    async def find_similar_cases(
        self,
        root_cause: str,
        device_ids: List[str],
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Find similar cases based on root cause and affected devices."""
        try:
            result = await neo4j_client.query(
                """
                MATCH (c:Case)-[:HAS_ROOT_CAUSE]->(rc:RootCause)
                WHERE rc.name CONTAINS $root_cause OR c.root_cause CONTAINS $root_cause
                OPTIONAL MATCH (c)-[:AFFECTS]->(d:Device)
                WHERE d.id IN $device_ids
                WITH c, rc, count(d) AS device_matches
                ORDER BY device_matches DESC, c.created_at DESC
                RETURN c.session_id AS session_id,
                       c.root_cause AS root_cause,
                       rc.name AS rc_name,
                       rc.confidence AS confidence,
                       device_matches
                LIMIT $limit
                """,
                {"root_cause": root_cause, "device_ids": device_ids, "limit": limit},
            )
            return [dict(r) for r in result]
        except Exception as e:
            logger.warning("Similar cases query failed: %s", e)
            return []

    async def get_causal_chain(
        self,
        alarm_id: str,
        direction: str = "forward",  # "forward" (effects) or "backward" (causes)
        max_depth: int = 3,
    ) -> Dict[str, Any]:
        """Get causal chain from an alarm."""
        try:
            if direction == "forward":
                # Alarm → RootCause → affected devices/services
                result = await neo4j_client.query(
                    f"""
                    MATCH path = (a:Alarm {{id: $alarm_id}})-[:CAUSES|LEADS_TO*1..{max_depth}]->(n)
                    RETURN path
                    LIMIT 50
                    """,
                    {"alarm_id": alarm_id},
                )
            else:
                # Backward: what leads to this alarm
                result = await neo4j_client.query(
                    f"""
                    MATCH path = (n)-[:CAUSES|LEADS_TO*1..{max_depth}]->(a:Alarm {{id: $alarm_id}})
                    RETURN path
                    LIMIT 50
                    """,
                    {"alarm_id": alarm_id},
                )

            nodes = []
            relationships = []
            seen_nodes = set()
            seen_rels = set()

            for record in result:
                path = record.get("path", {})
                if hasattr(path, "nodes"):
                    for node in path.nodes:
                        props = dict(node._properties) if hasattr(node, "_properties") else {}
                        node_id = props.get("id", "")
                        if node_id and node_id not in seen_nodes:
                            nodes.append(props)
                            seen_nodes.add(node_id)

                if hasattr(path, "relationships"):
                    for rel in path.relationships:
                        rel_id = id(rel)
                        if rel_id not in seen_rels:
                            seen_rels.add(rel_id)
                            rel_props = dict(rel._properties) if hasattr(rel, "_properties") else {}
                            rel_type = rel.type if hasattr(rel, "type") else ""
                            relationships.append({
                                **rel_props,
                                "type": rel_type,
                                "start_node": rel.start_node.id if hasattr(rel, "start_node") else "",
                                "end_node": rel.end_node.id if hasattr(rel, "end_node") else "",
                            })

            return {
                "nodes": nodes,
                "relationships": relationships,
                "direction": direction,
                "max_depth": max_depth,
            }
        except Exception as e:
            logger.warning("Causal chain query failed: %s", e)
            return {"nodes": [], "relationships": [], "direction": direction, "max_depth": max_depth}

    async def get_device_impact(
        self,
        device_id: str,
        max_hops: int = 3,
    ) -> Dict[str, Any]:
        """Analyze impact radius of a device failure."""
        try:
            result = await neo4j_client.query(
                f"""
                MATCH path = (d:Device {{id: $device_id}})-[:CONNECTS|DEPENDS_ON*1..{max_hops}]-(n)
                WHERE n.id <> $device_id
                RETURN n, min(length(path)) AS distance
                ORDER BY distance
                LIMIT 50
                """,
                {"device_id": device_id},
            )

            impacted = []
            for r in result:
                node = r.get("n", {})
                props = dict(node._properties) if hasattr(node, "_properties") else dict(node)
                impacted.append({
                    **props,
                    "distance": r.get("distance", 0),
                })

            return {
                "source_device": device_id,
                "impacted_nodes": impacted,
                "total_impact": len(impacted),
                "max_hops": max_hops,
            }
        except Exception as e:
            logger.warning("Device impact query failed: %s", e)
            return {"source_device": device_id, "impacted_nodes": [], "total_impact": 0, "max_hops": max_hops}

    async def get_statistics(self) -> Dict[str, Any]:
        """Get knowledge graph statistics."""
        try:
            # Node counts by label
            node_counts = await neo4j_client.query(
                """
                MATCH (n)
                RETURN labels(n)[0] AS label, count(n) AS count
                ORDER BY count DESC
                """
            )

            # Relationship counts by type
            rel_counts = await neo4j_client.query(
                """
                MATCH ()-[r]->()
                RETURN type(r) AS type, count(r) AS count
                ORDER BY count DESC
                """
            )

            # Total counts
            totals = await neo4j_client.query(
                """
                MATCH (n) RETURN count(n) AS total_nodes
                """
            )
            total_nodes = totals[0].get("total_nodes", 0) if totals else 0

            total_rels_result = await neo4j_client.query(
                """
                MATCH ()-[r]->() RETURN count(r) AS total_rels
                """
            )
            total_rels = total_rels_result[0].get("total_rels", 0) if total_rels_result else 0

            return {
                "total_nodes": total_nodes,
                "total_relationships": total_rels,
                "node_breakdown": [dict(r) for r in node_counts],
                "relationship_breakdown": [dict(r) for r in rel_counts],
            }
        except Exception as e:
            logger.warning("Statistics query failed: %s", e)
            return {"total_nodes": 0, "total_relationships": 0, "node_breakdown": [], "relationship_breakdown": []}

    async def search_entities(
        self,
        query: str,
        entity_types: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Search entities by name or properties."""
        try:
            type_filter = ""
            if entity_types:
                labels = ":" + "|".join(entity_types)
                type_filter = f"{labels}"

            result = await neo4j_client.query(
                f"""
                MATCH (n{type_filter})
                WHERE n.name CONTAINS $query
                   OR n.id CONTAINS $query
                   OR n.description CONTAINS $query
                   OR n.alarm_code CONTAINS $query
                RETURN n
                LIMIT $limit
                """,
                {"query": query, "limit": limit},
            )

            entities = []
            for r in result:
                node = r.get("n", {})
                props = dict(node._properties) if hasattr(node, "_properties") else dict(node)
                entities.append(props)

            return entities
        except Exception as e:
            logger.warning("Entity search failed: %s", e)
            return []

    async def get_common_root_causes(
        self,
        alarm_code: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Get most common root causes, optionally filtered by alarm code."""
        try:
            if alarm_code:
                result = await neo4j_client.query(
                    """
                    MATCH (a:Alarm {alarm_code: $alarm_code})-[:CAUSES]->(rc:RootCause)
                    RETURN rc.name AS root_cause, count(*) AS frequency, avg(rc.confidence) AS avg_confidence
                    ORDER BY frequency DESC
                    LIMIT $limit
                    """,
                    {"alarm_code": alarm_code, "limit": limit},
                )
            else:
                result = await neo4j_client.query(
                    """
                    MATCH (a:Alarm)-[:CAUSES]->(rc:RootCause)
                    RETURN rc.name AS root_cause, count(*) AS frequency, avg(rc.confidence) AS avg_confidence
                    ORDER BY frequency DESC
                    LIMIT $limit
                    """,
                    {"limit": limit},
                )
            return [dict(r) for r in result]
        except Exception as e:
            logger.warning("Common root causes query failed: %s", e)
            return []


# Global query service instance
kg_query_service = KGQueryService()
