"""Knowledge graph module for OptiRCAgent."""

from optirc.knowledge.builder import graph_builder
from optirc.knowledge.extractor import knowledge_extractor
from optirc.knowledge.models import (
    AlarmEntity,
    CaseEntity,
    DeviceEntity,
    Entity,
    EntityType,
    ExtractedKnowledge,
    KnowledgeItemEntity,
    RelationType,
    Relationship,
    RootCauseEntity,
    SolutionEntity,
    Subgraph,
    TopologyEntity,
)
from optirc.knowledge.neo4j_client import neo4j_client
from optirc.knowledge.queries import kg_query_service

__all__ = [
    # Client
    "neo4j_client",
    # Services
    "kg_query_service",
    "graph_builder",
    "knowledge_extractor",
    # Models
    "Entity",
    "EntityType",
    "Relationship",
    "RelationType",
    "DeviceEntity",
    "AlarmEntity",
    "RootCauseEntity",
    "CaseEntity",
    "SolutionEntity",
    "TopologyEntity",
    "KnowledgeItemEntity",
    "ExtractedKnowledge",
    "Subgraph",
]
