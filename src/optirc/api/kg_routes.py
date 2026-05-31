"""Knowledge Graph REST API routes."""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from optirc.knowledge.builder import graph_builder
from optirc.knowledge.models import EntityType, ExtractedKnowledge, Subgraph
from optirc.knowledge.neo4j_client import neo4j_client
from optirc.knowledge.queries import kg_query_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/kg", tags=["knowledge-graph"])


# ── Schema Management ──

@router.post("/schema/init")
async def init_schema():
    """Initialize knowledge graph schema (constraints and indexes)."""
    success = await graph_builder.init_schema()
    if not success:
        raise HTTPException(status_code=500, detail="Schema initialization failed")
    return {"status": "ok", "message": "Schema initialized"}


# ── Entity CRUD ──

@router.get("/entities/search")
async def search_entities(
    q: str = Query(..., description="Search query"),
    types: Optional[List[str]] = Query(None, description="Filter by entity types"),
    limit: int = Query(20, ge=1, le=100),
):
    """Search entities by name or properties."""
    results = await kg_query_service.search_entities(q, types, limit)
    return {"query": q, "results": results, "count": len(results)}


@router.get("/entities/{entity_id}")
async def get_entity(entity_id: str):
    """Get a single entity by ID."""
    entity = await graph_builder.get_entity(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found")
    return entity


@router.get("/entities/{entity_id}/neighbors")
async def get_entity_neighbors(
    entity_id: str,
    relation_types: Optional[List[str]] = Query(None),
    depth: int = Query(1, ge=1, le=3),
):
    """Get neighbors of an entity."""
    result = await graph_builder.get_entity_neighbors(entity_id, relation_types, depth)
    return result


@router.delete("/entities/{entity_id}")
async def delete_entity(entity_id: str):
    """Delete an entity and all its relationships."""
    success = await graph_builder.delete_entity(entity_id)
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to delete entity {entity_id}")
    return {"status": "ok", "message": f"Entity {entity_id} deleted"}


# ── Subgraph Queries ──

@router.get("/subgraph")
async def get_subgraph(
    topology_ids: List[str] = Query(..., description="Topology IDs to query around"),
    depth: int = Query(2, ge=1, le=4),
):
    """Get subgraph around given topology IDs."""
    result = await kg_query_service.get_subgraph(topology_ids, depth)
    return result


# ── Causal Analysis ──

@router.get("/causal-chain/{alarm_id}")
async def get_causal_chain(
    alarm_id: str,
    direction: str = Query("forward", regex="^(forward|backward)$"),
    max_depth: int = Query(3, ge=1, le=5),
):
    """Get causal chain from an alarm."""
    result = await kg_query_service.get_causal_chain(alarm_id, direction, max_depth)
    return result


@router.get("/impact-analysis/{device_id}")
async def get_device_impact(
    device_id: str,
    max_hops: int = Query(3, ge=1, le=5),
):
    """Analyze impact radius of a device failure."""
    result = await kg_query_service.get_device_impact(device_id, max_hops)
    return result


# ── Case Queries ──

@router.get("/cases/similar")
async def find_similar_cases(
    root_cause: str = Query(..., description="Root cause to match"),
    device_ids: List[str] = Query(default=[], description="Affected device IDs"),
    limit: int = Query(5, ge=1, le=20),
):
    """Find similar cases based on root cause and affected devices."""
    results = await kg_query_service.find_similar_cases(root_cause, device_ids, limit)
    return {"results": results, "count": len(results)}


@router.get("/root-causes/common")
async def get_common_root_causes(
    alarm_code: Optional[str] = Query(None, description="Filter by alarm code"),
    limit: int = Query(10, ge=1, le=50),
):
    """Get most common root causes."""
    results = await kg_query_service.get_common_root_causes(alarm_code, limit)
    return {"results": results, "count": len(results)}


# ── Statistics ──

@router.get("/statistics")
async def get_statistics():
    """Get knowledge graph statistics."""
    stats = await kg_query_service.get_statistics()
    return stats


# ── Visualization Data ──

@router.get("/visualization")
async def get_visualization_data(
    center_id: Optional[str] = Query(None, description="Center entity ID"),
    topology_ids: Optional[List[str]] = Query(None, description="Topology IDs"),
    depth: int = Query(2, ge=1, le=4),
    limit: int = Query(100, ge=10, le=500),
):
    """Get data formatted for graph visualization (D3.js, Cytoscape, etc.)."""
    nodes = []
    edges = []
    seen_nodes = set()
    seen_edges = set()

    try:
        if center_id:
            # Query from center
            result = await neo4j_client.query(
                f"""
                MATCH path = (center {{id: $center_id}})-[r*1..{depth}]-(n)
                RETURN center, nodes(path) AS path_nodes, relationships(path) AS path_rels
                LIMIT $limit
                """,
                {"center_id": center_id, "limit": limit},
            )

            for record in result:
                center = record.get("center", {})
                center_props = dict(center._properties) if hasattr(center, "_properties") else dict(center)
                center_id_val = center_props.get("id", "")
                if center_id_val and center_id_val not in seen_nodes:
                    nodes.append({
                        "id": center_id_val,
                        "label": center_props.get("name", center_id_val),
                        "type": center_props.get("entity_type", "Unknown"),
                        **center_props,
                    })
                    seen_nodes.add(center_id_val)

                for node in record.get("path_nodes", []):
                    props = dict(node._properties) if hasattr(node, "_properties") else dict(node)
                    node_id = props.get("id", "")
                    if node_id and node_id not in seen_nodes:
                        nodes.append({
                            "id": node_id,
                            "label": props.get("name", node_id),
                            "type": props.get("entity_type", "Unknown"),
                            **props,
                        })
                        seen_nodes.add(node_id)

                for rel in record.get("path_rels", []):
                    if not isinstance(rel, list):
                        rel = [rel]
                    for r in rel:
                        start = r.start_node.id if hasattr(r, "start_node") else ""
                        end = r.end_node.id if hasattr(r, "end_node") else ""
                        rel_type = r.type if hasattr(r, "type") else ""
                        edge_id = f"{start}-{rel_type}-{end}"
                        if edge_id not in seen_edges and start and end:
                            seen_edges.add(edge_id)
                            edges.append({
                                "id": edge_id,
                                "source": start,
                                "target": end,
                                "label": rel_type,
                                "properties": dict(r._properties) if hasattr(r, "_properties") else {},
                            })

        elif topology_ids:
            subgraph = await kg_query_service.get_subgraph(topology_ids, depth)
            for node in subgraph.get("nodes", []):
                node_id = node.get("id", "")
                if node_id and node_id not in seen_nodes:
                    nodes.append({
                        "id": node_id,
                        "label": node.get("name", node_id),
                        "type": node.get("entity_type", "Unknown"),
                        **node,
                    })
                    seen_nodes.add(node_id)

            for rel in subgraph.get("relationships", []):
                start = rel.get("start_node", "")
                end = rel.get("end_node", "")
                rel_type = rel.get("type", "")
                edge_id = f"{start}-{rel_type}-{end}"
                if edge_id not in seen_edges and start and end:
                    seen_edges.add(edge_id)
                    edges.append({
                        "id": edge_id,
                        "source": start,
                        "target": end,
                        "label": rel_type,
                        "properties": {k: v for k, v in rel.items() if k not in ["type", "start_node", "end_node"]},
                    })

        return {
            "nodes": nodes,
            "edges": edges,
            "layout": "force-directed",
            "node_count": len(nodes),
            "edge_count": len(edges),
        }

    except Exception as e:
        logger.warning("Visualization query failed: %s", e)
        return {"nodes": [], "edges": [], "error": str(e)}


# ── Bulk Operations ──

@router.delete("/cases/{session_id}")
async def delete_case(session_id: str):
    """Delete a case and all related entities."""
    success = await graph_builder.delete_by_session(session_id)
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to delete case {session_id}")
    return {"status": "ok", "message": f"Case {session_id} deleted"}


@router.get("/health")
async def kg_health():
    """Knowledge graph health check."""
    try:
        stats = await kg_query_service.get_statistics()
        return {
            "status": "healthy",
            "total_nodes": stats.get("total_nodes", 0),
            "total_relationships": stats.get("total_relationships", 0),
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
        }
