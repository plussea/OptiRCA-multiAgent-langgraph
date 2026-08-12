"""Knowledge graph builder: construct and manage the Neo4j knowledge graph."""

import logging
from typing import Any, Dict, List, Optional

from optirc.knowledge.models import Entity, EntityType, RelationType, Relationship
from optirc.knowledge.neo4j_client import neo4j_client

logger = logging.getLogger(__name__)


class GraphBuilder:
    """Build and manage knowledge graph in Neo4j."""

    # ── Schema Constraints ──
    CONSTRAINTS = [
        "CREATE CONSTRAINT device_id IF NOT EXISTS FOR (d:Device) REQUIRE d.id IS UNIQUE",
        "CREATE CONSTRAINT alarm_id IF NOT EXISTS FOR (a:Alarm) REQUIRE a.id IS UNIQUE",
        "CREATE CONSTRAINT rootcause_id IF NOT EXISTS FOR (r:RootCause) REQUIRE r.id IS UNIQUE",
        "CREATE CONSTRAINT case_id IF NOT EXISTS FOR (c:Case) REQUIRE c.id IS UNIQUE",
        "CREATE CONSTRAINT solution_id IF NOT EXISTS FOR (s:Solution) REQUIRE s.id IS UNIQUE",
        "CREATE CONSTRAINT topology_id IF NOT EXISTS FOR (t:Topology) REQUIRE t.id IS UNIQUE",
        "CREATE CONSTRAINT knowledge_item_id IF NOT EXISTS FOR (k:KnowledgeItem) REQUIRE k.id IS UNIQUE",
    ]

    # ── Indexes ──
    INDEXES = [
        "CREATE INDEX device_name IF NOT EXISTS FOR (d:Device) ON (d.name)",
        "CREATE INDEX alarm_code IF NOT EXISTS FOR (a:Alarm) ON (a.alarm_code)",
        "CREATE INDEX case_session IF NOT EXISTS FOR (c:Case) ON (c.session_id)",
        "CREATE INDEX entity_type IF NOT EXISTS FOR (e:Entity) ON (e.entity_type)",
    ]

    async def init_schema(self) -> bool:
        """Initialize graph schema with constraints and indexes."""
        try:
            for constraint in self.CONSTRAINTS:
                try:
                    await neo4j_client.query(constraint)
                except Exception as e:
                    # Constraint might already exist
                    logger.debug("Constraint creation (may exist): %s", e)

            for index in self.INDEXES:
                try:
                    await neo4j_client.query(index)
                except Exception as e:
                    logger.debug("Index creation (may exist): %s", e)

            logger.info("Graph schema initialized")
            return True
        except Exception as e:
            logger.error("Schema initialization failed: %s", e)
            return False

    async def create_entity(self, entity: Entity) -> bool:
        """Create or merge a single entity."""
        label = entity.entity_type.value
        props = entity.to_neo4j_properties()

        # Build property placeholders
        prop_keys = ", ".join([f"{k}: ${k}" for k in props.keys()])

        cypher = f"""
        MERGE (n:{label} {{id: $id}})
        SET n += ${props}
        RETURN n
        """

        try:
            result = await neo4j_client.query(
                f"MERGE (n:{label} {{id: $id}}) SET n = $props RETURN n",
                {"id": entity.id, "props": props},
            )
            return len(result) > 0
        except Exception as e:
            logger.warning("Failed to create entity %s: %s", entity.id, e)
            return False

    async def create_entities_batch(self, entities: List[Entity]) -> Dict[str, Any]:
        """Batch create entities using UNWIND for efficiency."""
        if not entities:
            return {"created": 0, "failed": 0}

        # Group by entity type for efficient batching
        by_type: Dict[str, List[Dict]] = {}
        for entity in entities:
            et = entity.entity_type.value
            if et not in by_type:
                by_type[et] = []
            by_type[et].append(entity.to_neo4j_properties())

        created = 0
        failed = 0

        for entity_type, props_list in by_type.items():
            try:
                result = await neo4j_client.query(
                    f"""
                    UNWIND $props_list AS props
                    MERGE (n:{entity_type} {{id: props.id}})
                    SET n = props
                    RETURN count(n) AS count
                    """,
                    {"props_list": props_list},
                )
                if result:
                    created += result[0].get("count", 0)
            except Exception as e:
                logger.warning("Batch create failed for %s: %s", entity_type, e)
                failed += len(props_list)

        return {"created": created, "failed": failed}

    async def create_relationship(self, rel: Relationship) -> bool:
        """Create or merge a single relationship."""
        src_label = rel.source_type.value
        tgt_label = rel.target_type.value
        rel_type = rel.relation_type.value

        cypher = f"""
        MATCH (src:{src_label} {{id: $source_id}})
        MATCH (tgt:{tgt_label} {{id: $target_id}})
        MERGE (src)-[r:{rel_type}]->(tgt)
        SET r.confidence = $confidence
        SET r += $props
        RETURN r
        """

        try:
            result = await neo4j_client.query(
                cypher,
                {
                    "source_id": rel.source_id,
                    "target_id": rel.target_id,
                    "confidence": rel.confidence,
                    "props": rel.properties,
                },
            )
            return len(result) > 0
        except Exception as e:
            logger.warning(
                "Failed to create relationship %s-[%s]->%s: %s",
                rel.source_id, rel_type, rel.target_id, e,
            )
            return False

    async def create_relationships_batch(self, relationships: List[Relationship]) -> Dict[str, Any]:
        """Batch create relationships."""
        if not relationships:
            return {"created": 0, "failed": 0}

        created = 0
        failed = 0

        # Process in smaller batches to avoid large transactions
        batch_size = 50
        for i in range(0, len(relationships), batch_size):
            batch = relationships[i:i + batch_size]

            # Convert to parameter format
            rel_params = []
            for rel in batch:
                rel_params.append({
                    "source_id": rel.source_id,
                    "source_type": rel.source_type.value,
                    "target_id": rel.target_id,
                    "target_type": rel.target_type.value,
                    "relation_type": rel.relation_type.value,
                    "confidence": rel.confidence,
                    "props": rel.properties,
                })

            try:
                result = await neo4j_client.query(
                    """
                    UNWIND $rels AS rel
                    MATCH (src {id: rel.source_id})
                    MATCH (tgt {id: rel.target_id})
                    CALL apoc.merge.relationship(src, rel.relation_type,
                        {source_id: rel.source_id, target_id: rel.target_id},
                        {confidence: rel.confidence, **rel.props},
                        tgt
                    ) YIELD rel as r
                    RETURN count(r) AS count
                    """,
                    {"rels": rel_params},
                )
                if result:
                    created += result[0].get("count", 0)
            except Exception as e:
                # APOC might not be available, fallback to individual
                logger.debug("Batch relationship failed (APOC unavailable?), trying individual: %s", e)
                for rel in batch:
                    success = await self.create_relationship(rel)
                    if success:
                        created += 1
                    else:
                        failed += 1

        return {"created": created, "failed": failed}

    async def build_from_extraction(
        self,
        entities: List[Entity],
        relationships: List[Relationship],
    ) -> Dict[str, Any]:
        """Build graph from extracted knowledge."""
        # Create entities first
        entity_result = await self.create_entities_batch(entities)

        # Then create relationships
        rel_result = await self.create_relationships_batch(relationships)

        return {
            "entities": entity_result,
            "relationships": rel_result,
            "total_entities": len(entities),
            "total_relationships": len(relationships),
        }

    async def delete_entity(self, entity_id: str) -> bool:
        """Delete an entity and all its relationships."""
        try:
            await neo4j_client.query(
                "MATCH (n {id: $id}) DETACH DELETE n",
                {"id": entity_id},
            )
            return True
        except Exception as e:
            logger.warning("Failed to delete entity %s: %s", entity_id, e)
            return False

    async def delete_by_session(self, session_id: str) -> bool:
        """Delete all entities related to a session."""
        try:
            await neo4j_client.query(
                """
                MATCH (c:Case {session_id: $session_id})
                OPTIONAL MATCH (c)-[]-(n)
                DETACH DELETE c, n
                """,
                {"session_id": session_id},
            )
            return True
        except Exception as e:
            logger.warning("Failed to delete session %s: %s", session_id, e)
            return False

    async def get_entity(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Get a single entity by ID."""
        try:
            result = await neo4j_client.query(
                "MATCH (n {id: $id}) RETURN n LIMIT 1",
                {"id": entity_id},
            )
            if result:
                node = result[0].get("n", {})
                if hasattr(node, "_properties"):
                    return dict(node._properties)
                elif isinstance(node, dict):
                    return node
            return None
        except Exception as e:
            logger.warning("Failed to get entity %s: %s", entity_id, e)
            return None

    async def get_entity_neighbors(
        self,
        entity_id: str,
        relation_types: Optional[List[str]] = None,
        depth: int = 1,
    ) -> Dict[str, Any]:
        """Get neighbors of an entity."""
        rel_filter = ""
        if relation_types:
            rels = "|".join(relation_types)
            rel_filter = f"[r:{rels}]"
        else:
            rel_filter = "[r]"

        try:
            result = await neo4j_client.query(
                f"""
                MATCH (n {{id: $id}})-{rel_filter}-(m)
                RETURN n, r, m
                LIMIT 100
                """,
                {"id": entity_id},
            )

            nodes = []
            relationships = []
            seen_nodes = set()

            for record in result:
                for key in ["n", "m"]:
                    node = record.get(key, {})
                    props = dict(node._properties) if hasattr(node, "_properties") else dict(node)
                    node_id = props.get("id", "")
                    if node_id and node_id not in seen_nodes:
                        nodes.append(props)
                        seen_nodes.add(node_id)

                rel = record.get("r", {})
                if rel:
                    rel_props = dict(rel._properties) if hasattr(rel, "_properties") else dict(rel)
                    rel_type = rel.type if hasattr(rel, "type") else rel_props.get("type", "")
                    relationships.append({
                        **rel_props,
                        "type": rel_type,
                        "start_node": rel.start_node.id if hasattr(rel, "start_node") else "",
                        "end_node": rel.end_node.id if hasattr(rel, "end_node") else "",
                    })

            return {"nodes": nodes, "relationships": relationships}
        except Exception as e:
            logger.warning("Failed to get neighbors for %s: %s", entity_id, e)
            return {"nodes": [], "relationships": []}


# Global builder instance
graph_builder = GraphBuilder()
