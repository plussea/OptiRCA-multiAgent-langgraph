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
    summary: Dict[str, Any] = {
        "input_type": state.get("input_type", "unknown"),
        "raw_rows_count": len(state.get("raw_rows") or []),
        "normalized_headers": state.get("normalized_headers") or [],
        "topology_ids": state.get("topology_ids") or [],
        "ocr_text": state.get("ocr_text") or "",
        "detected_encoding": state.get("detected_encoding") or "utf-8",
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
