"""Tests for knowledge graph module."""

import pytest

from optirc.knowledge.models import (
    AlarmEntity,
    CaseEntity,
    DeviceEntity,
    EntityType,
    ExtractedKnowledge,
    RelationType,
    Relationship,
    RootCauseEntity,
    SolutionEntity,
)


class TestEntityModels:
    """Test entity model creation and serialization."""

    def test_device_entity(self):
        dev = DeviceEntity(
            id="dev-test-001",
            name="OTN-Node-A",
            device_type="OTN",
            vendor="Huawei",
            model="OSN 9800",
            location="Beijing-DC1",
        )
        assert dev.entity_type == EntityType.DEVICE
        assert dev.properties["device_type"] == "OTN"
        props = dev.to_neo4j_properties()
        assert props["id"] == "dev-test-001"
        assert props["device_type"] == "OTN"

    def test_alarm_entity(self):
        alarm = AlarmEntity(
            id="alm-001",
            name="LOS",
            alarm_code="LOS",
            severity="critical",
            device_id="dev-test-001",
        )
        assert alarm.entity_type == EntityType.ALARM
        assert alarm.properties["severity"] == "critical"

    def test_root_cause_entity(self):
        rc = RootCauseEntity(
            id="rc-001",
            name="Fiber Cut",
            cause_type="physical",
            confidence=0.95,
        )
        assert rc.entity_type == EntityType.ROOT_CAUSE
        assert rc.confidence == 0.95

    def test_case_entity(self):
        case = CaseEntity(
            id="case-001",
            name="Case 001",
            session_id="sess-001",
            status="resolved",
        )
        assert case.entity_type == EntityType.CASE
        assert case.properties["session_id"] == "sess-001"

    def test_solution_entity(self):
        sol = SolutionEntity(
            id="sol-001",
            name="Fix Plan",
            steps=["Step 1", "Step 2"],
            risk_level="medium",
        )
        assert sol.entity_type == EntityType.SOLUTION
        assert len(sol.steps) == 2


class TestRelationshipModel:
    """Test relationship model."""

    def test_relationship_creation(self):
        rel = Relationship(
            source_id="alm-001",
            source_type=EntityType.ALARM,
            target_id="rc-001",
            target_type=EntityType.ROOT_CAUSE,
            relation_type=RelationType.CAUSES,
            confidence=0.9,
        )
        assert rel.relation_type == RelationType.CAUSES
        assert rel.confidence == 0.9

    def test_to_neo4j_pattern(self):
        rel = Relationship(
            source_id="alm-001",
            source_type=EntityType.ALARM,
            target_id="rc-001",
            target_type=EntityType.ROOT_CAUSE,
            relation_type=RelationType.CAUSES,
            confidence=0.9,
        )
        match_clause, merge_clause, params = rel.to_neo4j_pattern()
        assert "(src:Alarm {id: $source_id})" in match_clause
        assert "(tgt:RootCause {id: $target_id})" in match_clause
        assert "MERGE (src)-[r:CAUSES]->(tgt)" in merge_clause
        assert params["source_id"] == "alm-001"
        assert params["rel_props"]["confidence"] == 0.9


class TestExtractedKnowledge:
    """Test extracted knowledge model."""

    def test_to_closure_format(self):
        dev = DeviceEntity(id="dev-001", name="Device 1")
        alarm = AlarmEntity(id="alm-001", name="LOS")
        rel = Relationship(
            source_id="alm-001",
            source_type=EntityType.ALARM,
            target_id="dev-001",
            target_type=EntityType.DEVICE,
            relation_type=RelationType.AFFECTS,
        )

        ek = ExtractedKnowledge(
            entities=[dev, alarm],
            relationships=[rel],
            confidence=0.85,
            source_session_id="sess-001",
        )

        closure_data = ek.to_closure_format()
        assert len(closure_data) == 3  # 2 entities + 1 relationship
        assert closure_data[0]["category"] == "entity"
        assert closure_data[2]["category"] == "relationship"


class TestKnowledgeExtractor:
    """Test knowledge extraction logic."""

    @pytest.mark.asyncio
    async def test_rule_based_extraction(self):
        from optirc.knowledge.extractor import KnowledgeExtractor

        extractor = KnowledgeExtractor(use_llm=False)

        perception = {
            "topology_ids": ["dev-001", "dev-002"],
            "perception_summary": {
                "alarm_type": "LOS",
                "device_id": "dev-001",
                "severity": "critical",
                "description": "Loss of signal",
            },
        }
        diagnosis = {
            "root_cause": "Fiber Cut",
            "confidence": 0.95,
            "reasoning_chain": "Signal lost on fiber path",
        }
        planning = {
            "final_plan": {
                "steps": ["Check fiber", "Replace cable"],
                "risk_level": "medium",
            }
        }

        result = await extractor.extract_from_case(
            session_id="sess-test-001",
            perception=perception,
            diagnosis=diagnosis,
            planning=planning,
        )

        assert result.confidence > 0
        assert len(result.entities) > 0
        assert len(result.relationships) > 0

        # Check entity types
        entity_types = [e.entity_type for e in result.entities]
        assert EntityType.CASE in entity_types
        assert EntityType.DEVICE in entity_types
        assert EntityType.ALARM in entity_types
        assert EntityType.ROOT_CAUSE in entity_types
        assert EntityType.SOLUTION in entity_types

        # Check relationship types
        rel_types = [r.relation_type for r in result.relationships]
        assert RelationType.AFFECTS in rel_types
        assert RelationType.HAS_ROOT_CAUSE in rel_types
        assert RelationType.CAUSES in rel_types
        assert RelationType.HAS_SOLUTION in rel_types

    @pytest.mark.asyncio
    async def test_extraction_without_planning(self):
        from optirc.knowledge.extractor import KnowledgeExtractor

        extractor = KnowledgeExtractor(use_llm=False)

        perception = {
            "topology_ids": ["dev-001"],
            "perception_summary": {
                "alarm_type": "unknown",
                "device_id": "",
            },
        }
        diagnosis = {
            "root_cause": "unknown",
            "confidence": 0.0,
        }

        result = await extractor.extract_from_case(
            session_id="sess-test-002",
            perception=perception,
            diagnosis=diagnosis,
        )

        # Should still create case entity even with minimal data
        assert len(result.entities) >= 1
        assert any(e.entity_type == EntityType.CASE for e in result.entities)


class TestGraphBuilder:
    """Test graph builder operations."""

    def test_init_schema_cypher(self):
        from optirc.knowledge.builder import GraphBuilder

        builder = GraphBuilder()
        # Verify constraints are defined
        assert len(builder.CONSTRAINTS) > 0
        assert any("Device" in c for c in builder.CONSTRAINTS)
        assert any("Alarm" in c for c in builder.CONSTRAINTS)

    def test_batch_params_conversion(self):
        from optirc.knowledge.builder import GraphBuilder
        from optirc.knowledge.models import DeviceEntity, EntityType

        builder = GraphBuilder()
        entities = [
            DeviceEntity(id="dev-001", name="Device 1", device_type="OTN"),
            DeviceEntity(id="dev-002", name="Device 2", device_type="OLT"),
        ]

        # Verify to_neo4j_properties works for batching
        props_list = [e.to_neo4j_properties() for e in entities]
        assert len(props_list) == 2
        assert props_list[0]["entity_type"] == EntityType.DEVICE.value
