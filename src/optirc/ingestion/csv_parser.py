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
    """Extract topology IDs from CSV rows.

    Looks under the canonical English keys first, then falls back to
    inspecting the original (un-normalized) Chinese keys so files like
    `告警源` (alarm source / device) still surface as a topology ID.
    """
    ids: set = set()
    canonical_keys = ["topology_id", "topo_id", "network_id", "net_id"]

    for row in rows:
        for key in canonical_keys:
            val = row.get(key)
            if val:
                ids.add(str(val))

        # Fallback: if no canonical key matched, harvest device-like values.
        # We require at least one letter so we don't accidentally grab pure
        # numeric alarm IDs (186, 1, 13142) — the real device identifiers
        # in the demo CSV are `NE1`, `NE2`, `NE3`, `OA1`, all of which have
        # letters.
        if not any(row.get(k) for k in canonical_keys):
            for key, val in row.items():
                if not val:
                    continue
                v = str(val)
                if re.search(r"[A-Za-z]", v) and len(v) <= 32:
                    ids.add(f"{key}={v}")
                    break

    return sorted(ids)


def parse_csv(file_path: str) -> Dict[str, Any]:
    """Parse a CSV file and return structured data.

    Returns:
        Dict with:
          - raw_rows: list of dicts keyed by *original* (un-normalized) headers
          - normalized_headers: snake_case version of the headers
          - header_aliases: mapping normalized -> original header
          - topology_ids: list of topology-related identifiers found in the rows
    """
    if not os.path.exists(file_path):
        logger.error("File not found: %s", file_path)
        return {
            "raw_rows": [],
            "normalized_headers": [],
            "header_aliases": {},
            "topology_ids": [],
        }

    encoding = detect_encoding(file_path) or "utf-8"
    raw_rows: List[Dict[str, Any]] = []
    try:
        with open(file_path, "r", encoding=encoding, newline="") as f:
            reader = csv.DictReader(f)
            headers = list(reader.fieldnames or [])
            normalized = normalize_headers(headers)
            # Build a {normalized: original} map so downstream code can look
            # up the raw Chinese header given the snake_case version.
            header_aliases = {n: h for n, h in zip(normalized, headers) if n and h}
            for row in reader:
                raw_rows.append(dict(row))
    except Exception as e:
        logger.warning("CSV parse failed for %s: %s", file_path, e)
        return {
            "raw_rows": [],
            "normalized_headers": [],
            "header_aliases": {},
            "topology_ids": [],
        }

    topology_ids = extract_topology_ids(raw_rows)
    return {
        "raw_rows": raw_rows,
        "normalized_headers": normalized,
        "header_aliases": header_aliases,
        "topology_ids": topology_ids,
    }
