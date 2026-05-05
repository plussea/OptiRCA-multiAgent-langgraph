import logging
from typing import Optional

import chardet

logger = logging.getLogger(__name__)


def detect_encoding(file_path: str) -> Optional[str]:
    """Detect CSV file encoding using chardet."""
    try:
        with open(file_path, "rb") as f:
            raw = f.read(65536)
            result = chardet.detect(raw)
            encoding = result.get("encoding")
            if encoding:
                logger.info("Detected encoding %s for %s", encoding, file_path)
                return encoding
    except Exception as e:
        logger.warning("Encoding detection failed for %s: %s", file_path, e)
    return "utf-8"
