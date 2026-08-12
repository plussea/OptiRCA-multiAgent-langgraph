import base64
import logging
import os
from typing import Any, Dict

from langgraph.graph import END, StateGraph

from optirc.core.llm_client import llm_client
from optirc.core.state import PerceptionInternalState
from optirc.ingestion.csv_parser import parse_csv

logger = logging.getLogger(__name__)


def detect_input_type(state: PerceptionInternalState) -> Dict[str, Any]:
    """Detect if input is CSV or image."""
    raw_input = state["raw_input"]
    if os.path.isfile(raw_input):
        ext = os.path.splitext(raw_input)[1].lower()
        if ext in [".csv", ".txt"]:
            return {"input_type": "csv"}
        elif ext in [".png", ".jpg", ".jpeg", ".bmp"]:
            return {"input_type": "image"}
    return {"input_type": "text"}


def detect_encoding_node(state: PerceptionInternalState) -> Dict[str, Any]:
    """Detect CSV file encoding."""
    from optirc.core.encoding import detect_encoding
    raw_input = state["raw_input"]
    if os.path.isfile(raw_input):
        encoding = detect_encoding(raw_input)
        return {"detected_encoding": encoding}
    return {"detected_encoding": "utf-8"}


def parse_csv_node(state: PerceptionInternalState) -> Dict[str, Any]:
    """Parse CSV file."""
    raw_input = state["raw_input"]
    result = parse_csv(raw_input)
    return {
        "raw_rows": result["raw_rows"],
        "normalized_headers": result["normalized_headers"],
        "header_aliases": result.get("header_aliases", {}),
        "topology_ids": result["topology_ids"],
    }


async def extract_ocr_node(state: PerceptionInternalState) -> Dict[str, Any]:
    """Extract text from image via OCR."""
    raw_input = state["raw_input"]
    try:
        with open(raw_input, "rb") as f:
            image_bytes = f.read()
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        ocr_text = await llm_client.ocr(image_base64)
        return {"ocr_text": ocr_text}
    except Exception as e:
        logger.warning("OCR extraction failed: %s", e)
        return {"ocr_text": ""}


def summarize_node(state: PerceptionInternalState) -> Dict[str, Any]:
    """Construct unified perception summary."""
    raw_rows = state.get("raw_rows") or []
    # Surface the first row (un-normalized, original headers) so the
    # diagnosis LLM has something concrete to reason about even when the
    # CSV uses Chinese or non-standard column names.
    first_row = raw_rows[0] if raw_rows else {}
    # Also surface unique alarm-name / source values so the LLM can see the
    # distribution of faults at a glance.
    header_aliases = state.get("header_aliases") or {}

    # Try to pick the "alarm type/name" column dynamically. We look for
    # any of: `name`, `名称`, `alarm_name`, `alarm_type` (normalized) and
    # fall back to the second column if the CSV only has Chinese headers.
    alarm_name_col = None
    for candidate in ("名称", "alarm_name", "alarm_type", "name", "type"):
        if candidate in first_row:
            alarm_name_col = candidate
            break
    if alarm_name_col is None and len(first_row) >= 1:
        # Fall back to whichever column has the most repeated text-y values
        # (looks more like a name than a number).
        col_counts: Dict[str, set] = {}
        for row in raw_rows[:50]:
            for k, v in row.items():
                col_counts.setdefault(k, set()).add(str(v))
        if col_counts:
            alarm_name_col = max(col_counts, key=lambda k: len(col_counts[k]))

    source_col = None
    for candidate in ("告警源", "source", "device_id", "device", "ne_id"):
        if candidate in first_row:
            source_col = candidate
            break

    location_col = None
    for candidate in ("定位信息", "location", "position", "loc"):
        if candidate in first_row:
            location_col = candidate
            break

    alarm_name = first_row.get(alarm_name_col, "") if alarm_name_col else ""
    source = first_row.get(source_col, "") if source_col else ""
    location = first_row.get(location_col, "") if location_col else ""

    # Collect unique alarm names across all rows (capped) for richer context.
    unique_alarms: List[str] = []
    seen: set = set()
    for row in raw_rows:
        if alarm_name_col and alarm_name_col in row:
            v = str(row[alarm_name_col]).strip()
            if v and v not in seen:
                seen.add(v)
                unique_alarms.append(v)
        if len(unique_alarms) >= 8:
            break

    summary: Dict[str, Any] = {
        "input_type": state.get("input_type", "unknown"),
        "raw_rows_count": len(raw_rows),
        "normalized_headers": state.get("normalized_headers") or [],
        "header_aliases": header_aliases,
        "topology_ids": state.get("topology_ids") or [],
        "ocr_text": state.get("ocr_text") or "",
        "detected_encoding": state.get("detected_encoding") or "utf-8",
        # Demo-friendly fields — populated from whichever columns the CSV
        # actually has, regardless of language.
        "alarm_type": alarm_name or "unknown",
        "device_id": source or "",
        "description": location or "",
        "first_row": first_row,
        "unique_alarm_types": unique_alarms,
    }
    return {"perception_summary": summary}


def route_input_type(state: PerceptionInternalState) -> str:
    """Route based on input type."""
    input_type = state.get("input_type", "text")
    if input_type == "csv":
        return "parse_csv"
    elif input_type == "image":
        return "extract_ocr"
    return "summarize"


def build_perception_subgraph() -> StateGraph:
    """Build perception subgraph."""
    builder = StateGraph(PerceptionInternalState)
    builder.add_node("detect_input_type", detect_input_type)
    builder.add_node("detect_encoding", detect_encoding_node)
    builder.add_node("parse_csv", parse_csv_node)
    builder.add_node("extract_ocr", extract_ocr_node)
    builder.add_node("summarize", summarize_node)

    builder.set_entry_point("detect_input_type")
    builder.add_conditional_edges(
        "detect_input_type",
        route_input_type,
        {
            "parse_csv": "detect_encoding",
            "extract_ocr": "extract_ocr",
            "summarize": "summarize",
        },
    )
    builder.add_edge("detect_encoding", "parse_csv")
    builder.add_edge("parse_csv", "summarize")
    builder.add_edge("extract_ocr", "summarize")
    builder.add_edge("summarize", END)

    return builder.compile()
