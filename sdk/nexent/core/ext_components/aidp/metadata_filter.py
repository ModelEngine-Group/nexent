# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Build the AIDP FusionSearch ``metadata_condition`` from the conversation filter.

The conversation-level advanced filter is a list of ``original_file_name``
conditions. AIDP applies ``metadata_condition`` before recall, so an invalid
stored filter must fail loudly instead of silently searching everything.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


FILE_NAME_METADATA_FIELD = "original_file_name"

FILTER_VALUE_MAX_LENGTH = 256
FILTER_CONDITIONS_MAX = 20

# Stored/UI operator key -> AIDP wire spelling.
OPERATOR_MAP = {
    "contains": "contains",
    "is": "is",
    "starts_with": "start with",
    "ends_with": "end with",
}


def normalize_metadata_filter(value: Any) -> Dict[str, Any]:
    """Validate and normalize the stored ``{enabled, match, conditions}`` filter.

    Disabled or absent filters become ``{"enabled": False}``. An enabled filter
    must be a dict with a valid match policy and 1-20 usable conditions; invalid
    stored state raises ``ValueError`` instead of degrading to an unfiltered run.
    """
    if not value:
        return {"enabled": False}
    if not isinstance(value, dict):
        raise ValueError("metadata_filter must be an object")
    if not value.get("enabled"):
        return {"enabled": False}
    match = value.get("match") or "all"
    if match not in ("all", "any"):
        raise ValueError("metadata_filter.match must be 'all' or 'any'")
    conditions = value.get("conditions")
    if not isinstance(conditions, list) or not 1 <= len(conditions) <= FILTER_CONDITIONS_MAX:
        raise ValueError("metadata_filter requires 1-20 conditions when enabled")
    normalized: List[Dict[str, str]] = []
    for item in conditions:
        if not isinstance(item, dict):
            raise ValueError("metadata_filter conditions entries must be objects")
        operator = OPERATOR_MAP.get(str(item.get("operator") or "").strip())
        text = str(item.get("value") or "").strip()
        if operator is None or not 1 <= len(text) <= FILTER_VALUE_MAX_LENGTH:
            raise ValueError(
                "metadata_filter conditions require a known operator and a "
                "1-256 character value"
            )
        normalized.append({"operator": operator, "value": text})
    return {"enabled": True, "match": match, "conditions": normalized}


def build_metadata_condition(
    metadata_filter: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Return the FusionSearch ``metadata_condition`` value, or ``None``."""
    if not metadata_filter.get("enabled"):
        return None
    return {
        "logical_operator": "and" if metadata_filter["match"] == "all" else "or",
        "conditions": [
            {
                "name": FILE_NAME_METADATA_FIELD,
                "comparison_operator": condition["operator"],
                "value": condition["value"],
            }
            for condition in metadata_filter["conditions"]
        ],
    }
