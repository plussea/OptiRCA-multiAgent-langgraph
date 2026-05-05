import csv
import logging
import os
import re
from typing import Any, Dict, List, Optional

from optirc.core.encoding import detect_encoding

logger = logging.getLogger(__name__)


def normalize_headers(headers: List[str]) -> List[str]:
    """Normalize CSV headers to snake_case."""
    normalized = []
    for h in headers:
        h = h.strip().lower()
        h = re.sub(r"[^\w\s]", "", h)
        h = re.sub(r"\s+", "_", h)
        normalized.append(h)
    return normalized


def extract_topology_ids(rows: List[Dict[str, Any]]) -> List[str]:
    """Extract topology IDs from CSV rows."""
    ids = set()
    for row in rows:
        for key in ["topology_id", "topo_id", "network_id", "net_id"]:
            val = row.get(key)
            if val:
                ids.add(str(val))
    return list(ids)


def parse_csv(file_path: str) -> Dict[str, Any]:
    """Parse a CSV file and return structured data."""
    if not os.path.exists(file_path):
        logger.error("File not found: %s", file_path)
        return {"raw_rows": [], "normalized_headers": [], "topology_ids": []}

    encoding = detect_encoding(file_path) or "utf-8"
    raw_rows = []
    try:
        with open(file_path, "r", encoding=encoding, newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            normalized = normalize_headers(headers)
            for row in reader:
                raw_rows.append(dict(row))
    except Exception as e:
        logger.warning("CSV parse failed for %s: %s", file_path, e)
        return {"raw_rows": [], "normalized_headers": [], "topology_ids": []}

    topology_ids = extract_topology_ids(raw_rows)
    return {
        "raw_rows": raw_rows,
        "normalized_headers": normalized,
        "topology_ids": topology_ids,
    }
