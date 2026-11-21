# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Metadata filter rules for AIDP retrieval.

The conversation-level advanced filter is a single ``original_file_name``
condition. AIDP accepts one flat condition list, applies it before recall, and
rejects unsupported fields/operators instead of silently ignoring them. The
graph channel does not consume ``metadata_condition`` (still unverified
upstream), so a filtered run with graph retrieval enabled fails closed instead
of issuing an unfiltered request.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional


FILE_NAME_METADATA_FIELD = "original_file_name"

FILTER_UNAVAILABLE_MESSAGE = (
    "Advanced filtering is temporarily unavailable. No search was performed. "
    "Adjust the file-name filter or turn it off, then try again."
)

FILTER_GRAPH_UNSUPPORTED_MESSAGE = (
    "Advanced filtering is not available with the current retrieval method. "
    "No search was performed. Disable graph retrieval or turn off advanced "
    "filtering, then try again."
)

FILTER_VALUE_MAX_LENGTH = 256

# UI operator key -> AIDP wire spelling. Wire spellings are accepted as stored
# values too, so scopes written by older clients keep working.
OPERATOR_MAP = {
    "contains": "contains",
    "is": "is",
    "starts_with": "start with",
    "ends_with": "end with",
}
WIRE_OPERATORS = frozenset(OPERATOR_MAP.values())


class AidpMetadataFilterUnavailableError(RuntimeError):
    """Raised when a stored filter cannot be represented as a safe request condition."""


def _file_name_condition(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("metadata_filter.file_name must be an object")
    operator = str(value.get("operator") or "").strip()
    text = str(value.get("value") or "").strip()
    if not operator and not text:
        return {}
    return {"operator": operator, "value": text}


def normalize_metadata_filter(value: Any) -> Dict[str, Any]:
    """Return a validated ``{enabled, file_name?}`` filter or raise ``ValueError``."""
    if value is None or value == "":
        return {"enabled": False}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"metadata_filter must be valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("metadata_filter must be an object")
    if not value.get("enabled"):
        return {"enabled": False}
    result: Dict[str, Any] = {"enabled": True}
    file_name = value.get("file_name")
    if file_name is not None:
        condition = _file_name_condition(file_name)
        if condition:
            result["file_name"] = condition
    return result


def _wire_operator(operator: str) -> Optional[str]:
    if operator in WIRE_OPERATORS:
        return operator
    return OPERATOR_MAP.get(operator)


def build_metadata_condition(
    metadata_filter: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Return the FusionSearch ``metadata_condition`` payload, or ``None``.

    Raises ``AidpMetadataFilterUnavailableError`` when the filter is enabled but
    cannot be expressed as one safe condition; the caller must fail closed.
    """
    if not isinstance(metadata_filter, dict) or not metadata_filter.get("enabled"):
        return None
    file_name = metadata_filter.get("file_name")
    if not isinstance(file_name, dict):
        raise AidpMetadataFilterUnavailableError(
            "enabled filter has no file-name condition"
        )
    operator = _wire_operator(str(file_name.get("operator") or "").strip())
    value = str(file_name.get("value") or "").strip()
    if operator is None:
        raise AidpMetadataFilterUnavailableError("unsupported file-name operator")
    if not value or len(value) > FILTER_VALUE_MAX_LENGTH:
        raise AidpMetadataFilterUnavailableError("invalid file-name filter value")
    return {
        "metadata_condition": {
            "logical_operator": "and",
            "conditions": [
                {
                    "name": FILE_NAME_METADATA_FIELD,
                    "comparison_operator": operator,
                    "value": value,
                }
            ],
        }
    }
