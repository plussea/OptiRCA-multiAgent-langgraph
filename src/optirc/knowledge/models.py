"""Knowledge Graph entity and relationship models for optical network domain."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ────────────────────────────────
# Entity Types
# ────────────────────────────────

class EntityType(str, Enum):
    """Core entity types in the optical network knowledge graph."""

    DEVICE = "Device"                    # 网络设备 (OTN, OLT, ONU, etc.)
    ALARM = "Alarm"                      # 告警
    ROOT_CAUSE = "RootCause"             # 根因
    CASE = "Case"                        # 案例/工单
    SOLUTION = "Solution"                # 解决方案
    TOPOLOGY = "Topology"                # 拓扑节点
    SERVICE = "Service"                  # 业务/服务
    FIBER = "Fiber"                      # 光纤链路
    PORT = "Port"                        # 端口
    CARD = "Card"                        # 板卡
    KNOWLEDGE_ITEM = "KnowledgeItem"     # 知识条目


# ────────────────────────────────
# Relationship Types
# ────────────────────────────────

class RelationType(str, Enum):
    """Core relationship types."""

    # Causal relations
    CAUSES = "CAUSES"                    # Alarm → RootCause
    CAUSED_BY = "CAUSED_BY"              # RootCause → Alarm
    LEADS_TO = "LEADS_TO"              # RootCause → Alarm (propagation)

    # Affection relations
    AFFECTS = "AFFECTS"                # Case/Alarm → Device
    AFFECTED_BY = "AFFECTED_BY"        # Device → Alarm

    # Topological relations
    CONNECTS = "CONNECTS"              # Device ↔ Device
    CONTAINS = "CONTAINS"              # Device → Port/Card
    PART_OF = "PART_OF"                # Port/Card → Device
    DEPENDS_ON = "DEPENDS_ON"          # Service → Device

    # Case relations
    HAS_ROOT_CAUSE = "HAS_ROOT_CAUSE"  # Case → RootCause
    HAS_SOLUTION = "HAS_SOLUTION"      # Case → Solution
    SIMILAR_TO = "SIMILAR_TO"          # Case ↔ Case

    # Knowledge relations
    DESCRIBES = "DESCRIBES"            # KnowledgeItem → Entity
    RELATED_TO = "RELATED_TO"          # Generic relation


# ────────────────────────────────
# Base Entity Model
# ────────────────────────────────

class Entity(BaseModel):
    """Base model for all KG entities."""

    id: str = Field(..., description="Unique entity identifier")
    entity_type: EntityType = Field(..., description="Entity type")
    name: str = Field(..., description="Human-readable name")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Additional properties")
    created_at: Optional[str] = Field(default=None, description="Creation timestamp")
    updated_at: Optional[str] = Field(default=None, description="Last update timestamp")

    def to_neo4j_properties(self) -> Dict[str, Any]:
        """Convert to Neo4j node properties."""
        props = {
            "id": self.id,
            "name": self.name,
            "entity_type": self.entity_type.value,
            **self.properties,
        }
        if self.created_at:
            props["created_at"] = self.created_at
        if self.updated_at:
            props["updated_at"] = self.updated_at
        return props


# ────────────────────────────────
# Specialized Entity Models
# ────────────────────────────────

class DeviceEntity(Entity):
    """Network device entity."""

    entity_type: EntityType = EntityType.DEVICE
    device_type: str = Field(default="", description="Device type: OTN, OLT, ONU, etc.")
    vendor: str = Field(default="", description="Device vendor")
    model: str = Field(default="", description="Device model")
    location: str = Field(default="", description="Physical location")
    ip_address: str = Field(default="", description="Management IP")
    status: str = Field(default="active", description="Device status")

    def __init__(self, **data):
        super().__init__(**data)
        self.properties.update({
            "device_type": self.device_type,
            "vendor": self.vendor,
            "model": self.model,
            "location": self.location,
            "ip_address": self.ip_address,
            "status": self.status,
        })


class AlarmEntity(Entity):
    """Alarm entity."""

    entity_type: EntityType = EntityType.ALARM
    alarm_code: str = Field(default="", description="Alarm code/ID")
    severity: str = Field(default="minor", description="Alarm severity")
    category: str = Field(default="", description="Alarm category")
    description: str = Field(default="", description="Alarm description")
    device_id: str = Field(default="", description="Source device ID")
    occurred_at: str = Field(default="", description="Occurrence time")

    def __init__(self, **data):
        super().__init__(**data)
        self.properties.update({
            "alarm_code": self.alarm_code,
            "severity": self.severity,
            "category": self.category,
            "description": self.description,
            "device_id": self.device_id,
            "occurred_at": self.occurred_at,
        })


class RootCauseEntity(Entity):
    """Root cause entity."""

    entity_type: EntityType = EntityType.ROOT_CAUSE
    cause_type: str = Field(default="", description="Type of root cause")
    description: str = Field(default="", description="Detailed description")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Confidence score")
    symptoms: List[str] = Field(default_factory=list, description="Associated symptoms")

    def __init__(self, **data):
        super().__init__(**data)
        self.properties.update({
            "cause_type": self.cause_type,
            "description": self.description,
            "confidence": self.confidence,
            "symptoms": self.symptoms,
        })


class CaseEntity(Entity):
    """Case/Work order entity."""

    entity_type: EntityType = EntityType.CASE
    session_id: str = Field(default="", description="Session ID")
    status: str = Field(default="open", description="Case status")
    created_by: str = Field(default="system", description="Creator")
    resolved_at: Optional[str] = Field(default=None, description="Resolution time")
    resolution_notes: str = Field(default="", description="Resolution notes")

    def __init__(self, **data):
        super().__init__(**data)
        self.properties.update({
            "session_id": self.session_id,
            "status": self.status,
            "created_by": self.created_by,
            "resolved_at": self.resolved_at,
            "resolution_notes": self.resolution_notes,
        })


class SolutionEntity(Entity):
    """Solution entity."""

    entity_type: EntityType = EntityType.SOLUTION
    solution_type: str = Field(default="", description="Type of solution")
    steps: List[str] = Field(default_factory=list, description="Solution steps")
    estimated_time: str = Field(default="", description="Estimated resolution time")
    risk_level: str = Field(default="low", description="Risk level")
    rollback_plan: str = Field(default="", description="Rollback procedure")

    def __init__(self, **data):
        super().__init__(**data)
        self.properties.update({
            "solution_type": self.solution_type,
            "steps": self.steps,
            "estimated_time": self.estimated_time,
            "risk_level": self.risk_level,
            "rollback_plan": self.rollback_plan,
        })


class TopologyEntity(Entity):
    """Topology node entity."""

    entity_type: EntityType = EntityType.TOPOLOGY
    topology_type: str = Field(default="", description="Topology node type")
    layer: str = Field(default="", description="Network layer")
    parent_id: str = Field(default="", description="Parent topology ID")

    def __init__(self, **data):
        super().__init__(**data)
        self.properties.update({
            "topology_type": self.topology_type,
            "layer": self.layer,
            "parent_id": self.parent_id,
        })


class KnowledgeItemEntity(Entity):
    """Knowledge item entity (from SOPs, manuals)."""

    entity_type: EntityType = EntityType.KNOWLEDGE_ITEM
    source: str = Field(default="", description="Knowledge source")
    content: str = Field(default="", description="Knowledge content")
    category: str = Field(default="", description="Knowledge category")
    tags: List[str] = Field(default_factory=list, description="Tags")

    def __init__(self, **data):
        super().__init__(**data)
        self.properties.update({
            "source": self.source,
            "content": self.content,
            "category": self.category,
            "tags": self.tags,
        })


# ────────────────────────────────
# Relationship Model
# ────────────────────────────────

class Relationship(BaseModel):
    """Knowledge graph relationship."""

    source_id: str = Field(..., description="Source entity ID")
    source_type: EntityType = Field(..., description="Source entity type")
    target_id: str = Field(..., description="Target entity ID")
    target_type: EntityType = Field(..., description="Target entity type")
    relation_type: RelationType = Field(..., description="Relationship type")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Relationship properties")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Relationship confidence")

    def to_neo4j_pattern(self) -> tuple:
        """Generate Neo4j Cypher pattern components.

        Returns: (match_clause, merge_clause, params)
        """
        src_label = self.source_type.value
        tgt_label = self.target_type.value
        rel_type = self.relation_type.value

        match_clause = (
            f"MATCH (src:{src_label} {{id: $source_id}}), "
            f"(tgt:{tgt_label} {{id: $target_id}})"
        )
        merge_clause = f"MERGE (src)-[r:{rel_type}]->(tgt) SET r += $rel_props"

        params = {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "rel_props": {**self.properties, "confidence": self.confidence},
        }

        return match_clause, merge_clause, params


# ────────────────────────────────
# Subgraph Model
# ────────────────────────────────

class Subgraph(BaseModel):
    """Subgraph representation for API responses."""

    nodes: List[Dict[str, Any]] = Field(default_factory=list, description="Nodes")
    relationships: List[Dict[str, Any]] = Field(default_factory=list, description="Relationships")
    statistics: Dict[str, Any] = Field(default_factory=dict, description="Query statistics")


# ────────────────────────────────
# Knowledge Extraction Result
# ────────────────────────────────

class ExtractedKnowledge(BaseModel):
    """Result of knowledge extraction from a case."""

    entities: List[Entity] = Field(default_factory=list, description="Extracted entities")
    relationships: List[Relationship] = Field(default_factory=list, description="Extracted relationships")
    confidence: float = Field(default=0.0, description="Overall extraction confidence")
    source_session_id: str = Field(default="", description="Source session ID")
    extracted_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    def to_closure_format(self) -> List[Dict[str, Any]]:
        """Convert to closure subgraph format."""
        return [
            {
                "category": "entity",
                "entity_type": e.entity_type.value,
                "id": e.id,
                "name": e.name,
                "properties": e.properties,
            }
            for e in self.entities
        ] + [
            {
                "category": "relationship",
                "relation_type": r.relation_type.value,
                "source_id": r.source_id,
                "target_id": r.target_id,
                "confidence": r.confidence,
            }
            for r in self.relationships
        ]
