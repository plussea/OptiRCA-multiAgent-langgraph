"""Knowledge extraction engine: extract entities and relationships from case data."""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from optirc.core.llm_client import llm_client
from optirc.knowledge.models import (
    AlarmEntity,
    CaseEntity,
    DeviceEntity,
    Entity,
    EntityType,
    ExtractedKnowledge,
    RelationType,
    Relationship,
    RootCauseEntity,
    SolutionEntity,
)

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """You are an expert knowledge extraction system for optical network operations.

Given a case summary containing alarm data, diagnosis results, and solution plans,
extract structured entities and relationships for a knowledge graph.

## Entity Types
- Device: network equipment (OTN, OLT, ONU, router, switch, etc.)
- Alarm: network alarms with code, severity, description
- RootCause: identified root causes
- Case: the incident/case itself
- Solution: resolution steps and procedures
- Topology: network topology elements

## Relationship Types
- CAUSES: Alarm → RootCause
- AFFECTS: Alarm/Case → Device
- HAS_ROOT_CAUSE: Case → RootCause
- HAS_SOLUTION: Case → Solution
- CONNECTS: Device ↔ Device (topological)
- DEPENDS_ON: Service/Device → Device
- SIMILAR_TO: Case ↔ Case

## Output Format
Return a JSON object with this exact structure:
{
  "entities": [
    {
      "id": "unique-id",
      "entity_type": "Device|Alarm|RootCause|Case|Solution|Topology",
      "name": "human readable name",
      "properties": {
        // type-specific properties
      }
    }
  ],
  "relationships": [
    {
      "source_id": "entity-id",
      "source_type": "EntityType",
      "target_id": "entity-id",
      "target_type": "EntityType",
      "relation_type": "CAUSES|AFFECTS|HAS_ROOT_CAUSE|HAS_SOLUTION|CONNECTS|DEPENDS_ON|SIMILAR_TO",
      "confidence": 0.95,
      "properties": {}
    }
  ],
  "confidence": 0.85
}

## Rules
1. Generate unique IDs using descriptive prefixes (e.g., "dev-", "alm-", "rc-")
2. Include all devices mentioned in alarms
3. Include all alarm codes with their severity
4. Include the root cause with confidence score
5. Include the case itself as an entity
6. Create CAUSES relationships from alarms to root causes
7. Create AFFECTS relationships from alarms/case to devices
8. Create HAS_ROOT_CAUSE from case to root cause
9. Create HAS_SOLUTION from case to solution if available
10. Set confidence based on data completeness

Case Data:
"""


def _generate_id(prefix: str, name: str) -> str:
    """Generate a deterministic ID from prefix and name."""
    import hashlib
    name_hash = hashlib.md5(name.encode()).hexdigest()[:8]
    return f"{prefix}-{name_hash}"


def _parse_entity(data: Dict[str, Any]) -> Optional[Entity]:
    """Parse entity dict into typed entity model."""
    entity_type = data.get("entity_type", "")
    entity_id = data.get("id", "")
    name = data.get("name", "")
    props = data.get("properties", {})

    try:
        et = EntityType(entity_type)
    except ValueError:
        logger.warning("Unknown entity type: %s", entity_type)
        return None

    entity_map = {
        EntityType.DEVICE: DeviceEntity,
        EntityType.ALARM: AlarmEntity,
        EntityType.ROOT_CAUSE: RootCauseEntity,
        EntityType.CASE: CaseEntity,
        EntityType.SOLUTION: SolutionEntity,
    }

    entity_class = entity_map.get(et, Entity)
    return entity_class(id=entity_id, entity_type=et, name=name, properties=props)


def _parse_relationship(data: Dict[str, Any]) -> Optional[Relationship]:
    """Parse relationship dict into Relationship model."""
    try:
        return Relationship(
            source_id=data["source_id"],
            source_type=EntityType(data["source_type"]),
            target_id=data["target_id"],
            target_type=EntityType(data["target_type"]),
            relation_type=RelationType(data["relation_type"]),
            properties=data.get("properties", {}),
            confidence=data.get("confidence", 1.0),
        )
    except (KeyError, ValueError) as e:
        logger.warning("Failed to parse relationship: %s", e)
        return None


class KnowledgeExtractor:
    """Extract knowledge from case data using LLM and rule-based methods."""

    def __init__(self, use_llm: bool = True):
        self.use_llm = use_llm

    async def extract_from_case(
        self,
        session_id: str,
        perception: Dict[str, Any],
        diagnosis: Dict[str, Any],
        planning: Optional[Dict[str, Any]] = None,
    ) -> ExtractedKnowledge:
        """Extract knowledge from a complete case.

        Uses hybrid approach: rule-based extraction + LLM enhancement.
        """
        entities: List[Entity] = []
        relationships: List[Relationship] = []

        # ── Rule-based extraction ──
        rule_entities, rule_rels = self._rule_based_extract(
            session_id, perception, diagnosis, planning
        )
        entities.extend(rule_entities)
        relationships.extend(rule_rels)

        # ── LLM enhancement ──
        if self.use_llm:
            try:
                llm_entities, llm_rels, llm_conf = await self._llm_extract(
                    session_id, perception, diagnosis, planning
                )
                # Merge: LLM entities that don't conflict with rule-based
                existing_ids = {e.id for e in entities}
                for e in llm_entities:
                    if e.id not in existing_ids:
                        entities.append(e)

                existing_rels = {
                    (r.source_id, r.relation_type.value, r.target_id)
                    for r in relationships
                }
                for r in llm_rels:
                    rel_key = (r.source_id, r.relation_type.value, r.target_id)
                    if rel_key not in existing_rels:
                        relationships.append(r)

                confidence = (0.6 * 1.0 + 0.4 * llm_conf)  # weighted average
            except Exception as e:
                logger.warning("LLM extraction failed: %s", e)
                confidence = 0.7  # rule-based confidence
        else:
            confidence = 0.7

        return ExtractedKnowledge(
            entities=entities,
            relationships=relationships,
            confidence=confidence,
            source_session_id=session_id,
        )

    def _rule_based_extract(
        self,
        session_id: str,
        perception: Dict[str, Any],
        diagnosis: Dict[str, Any],
        planning: Optional[Dict[str, Any]] = None,
    ) -> tuple[List[Entity], List[Relationship]]:
        """Extract entities and relationships using deterministic rules."""
        entities: List[Entity] = []
        relationships: List[Relationship] = []

        # Extract devices from perception
        topology_ids = perception.get("topology_ids", [])
        summary = perception.get("perception_summary", {})
        device_id = summary.get("device_id", "")
        alarm_type = summary.get("alarm_type", "unknown")

        # Case entity
        case_entity = CaseEntity(
            id=f"case-{session_id}",
            name=f"Case {session_id[:8]}",
            session_id=session_id,
            status="resolved" if diagnosis.get("root_cause") else "open",
        )
        entities.append(case_entity)

        # Device entities
        device_ids = set(topology_ids)
        if device_id:
            device_ids.add(device_id)

        for did in device_ids:
            dev = DeviceEntity(
                id=_generate_id("dev", did),
                name=did,
                device_type="unknown",
            )
            entities.append(dev)

            # Case → Device (AFFECTS)
            relationships.append(Relationship(
                source_id=case_entity.id,
                source_type=EntityType.CASE,
                target_id=dev.id,
                target_type=EntityType.DEVICE,
                relation_type=RelationType.AFFECTS,
            ))

        # Alarm entity
        if alarm_type != "unknown":
            alarm = AlarmEntity(
                id=_generate_id("alm", f"{alarm_type}-{device_id}"),
                name=alarm_type,
                alarm_code=alarm_type,
                device_id=device_id,
                severity=summary.get("severity", "minor"),
                description=summary.get("description", ""),
            )
            entities.append(alarm)

            # Alarm → Device (AFFECTS)
            if device_id:
                relationships.append(Relationship(
                    source_id=alarm.id,
                    source_type=EntityType.ALARM,
                    target_id=_generate_id("dev", device_id),
                    target_type=EntityType.DEVICE,
                    relation_type=RelationType.AFFECTS,
                ))

        # Root cause entity
        root_cause = diagnosis.get("root_cause", "")
        if root_cause and root_cause != "unknown":
            rc = RootCauseEntity(
                id=_generate_id("rc", root_cause),
                name=root_cause,
                cause_type="diagnosed",
                description=diagnosis.get("reasoning_chain", ""),
                confidence=diagnosis.get("confidence", 0.5),
            )
            entities.append(rc)

            # Case → RootCause
            relationships.append(Relationship(
                source_id=case_entity.id,
                source_type=EntityType.CASE,
                target_id=rc.id,
                target_type=EntityType.ROOT_CAUSE,
                relation_type=RelationType.HAS_ROOT_CAUSE,
                confidence=diagnosis.get("confidence", 0.5),
            ))

            # Alarm → RootCause (if alarm exists)
            if alarm_type != "unknown":
                relationships.append(Relationship(
                    source_id=_generate_id("alm", f"{alarm_type}-{device_id}"),
                    source_type=EntityType.ALARM,
                    target_id=rc.id,
                    target_type=EntityType.ROOT_CAUSE,
                    relation_type=RelationType.CAUSES,
                    confidence=diagnosis.get("confidence", 0.5),
                ))

        # Solution entity
        if planning and planning.get("final_plan"):
            plan = planning["final_plan"]
            sol = SolutionEntity(
                id=_generate_id("sol", session_id),
                name=f"Solution for {session_id[:8]}",
                solution_type="automated",
                steps=plan.get("steps", []),
                risk_level=plan.get("risk_level", "low"),
                rollback_plan=plan.get("rollback", ""),
            )
            entities.append(sol)

            relationships.append(Relationship(
                source_id=case_entity.id,
                source_type=EntityType.CASE,
                target_id=sol.id,
                target_type=EntityType.SOLUTION,
                relation_type=RelationType.HAS_SOLUTION,
            ))

        return entities, relationships

    async def _llm_extract(
        self,
        session_id: str,
        perception: Dict[str, Any],
        diagnosis: Dict[str, Any],
        planning: Optional[Dict[str, Any]] = None,
    ) -> tuple[List[Entity], List[Relationship], float]:
        """Use LLM to extract knowledge."""
        case_data = {
            "session_id": session_id,
            "perception": perception,
            "diagnosis": diagnosis,
            "planning": planning,
        }

        prompt = EXTRACTION_PROMPT + json.dumps(case_data, ensure_ascii=False, indent=2)

        result = await llm_client.generate_json(
            system="You are a precise knowledge extraction system. Output only valid JSON.",
            user_message=prompt,
            temperature=0.1,
            use_fallback=True,
        )

        entities = []
        relationships = []

        for e_data in result.get("entities", []):
            entity = _parse_entity(e_data)
            if entity:
                entities.append(entity)

        for r_data in result.get("relationships", []):
            rel = _parse_relationship(r_data)
            if rel:
                relationships.append(rel)

        confidence = result.get("confidence", 0.5)
        return entities, relationships, confidence


# Global extractor instance
knowledge_extractor = KnowledgeExtractor(use_llm=True)
