# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Version-one capability partition for the existing model-record row."""

import json
from dataclasses import dataclass
from typing import Mapping

from pydantic import ValidationError

from nexent.core.model_service.profiles.contracts import ProfileCapabilities
from nexent.core.model_service.profiles.parameter_schema import _json_copy


_CONTEXT_COLUMNS = {
    "combined_window": "context_window_tokens",
    "input_limit": "max_input_tokens",
    "output_limit": "max_output_tokens",
}
_STATUS_COLUMNS = {
    "reasoning": "reasoning_supported",
    "tools": "native_tool_call_supported",
    "structured_output": "structured_output_supported",
    "temperature": "temperature_supported",
    "top_p": "top_p_supported",
}
CAPABILITY_COLUMN_KEYS = frozenset(
    {
        *_CONTEXT_COLUMNS.values(),
        *_STATUS_COLUMNS.values(),
        "reasoning_controls",
        "input_modalities",
        "output_modalities",
    }
)


class CapabilityStorageError(ValueError):
    """A fixed diagnostic without arbitrary stored values or Pydantic inputs."""

    def __init__(self):
        super().__init__("PROFILE_STORAGE_INVALID")


@dataclass
class StoredOutletCapabilities:
    """Detached columns and remaining details; neither contains duplicate values."""

    columns: dict[str, object]
    capability_details: dict[str, object]


def _clone(value: object):
    try:
        copied = _json_copy(value)
        encoded = json.dumps(copied, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > 1024 * 1024:
            raise CapabilityStorageError()
        return copied
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise CapabilityStorageError() from None


def _validate(value: object) -> dict:
    try:
        result = ProfileCapabilities.model_validate(value).model_dump(mode="json")
        for number in result["context"].values():
            if number is not None and number >= 2**31:
                raise CapabilityStorageError()
        return result
    except (ValidationError, ValueError, TypeError, UnicodeError):
        raise CapabilityStorageError() from None


def _status(value: object) -> str:
    if value is None:
        return "unknown"
    if type(value) is not bool:
        raise CapabilityStorageError()
    return "supported" if value else "unsupported"


def split_outlet_capabilities(capabilities: ProfileCapabilities) -> StoredOutletCapabilities:
    """Partition a validated complete capability object using fixed field ownership."""
    if not isinstance(capabilities, ProfileCapabilities):
        raise CapabilityStorageError()
    value = _validate(_clone(capabilities.model_dump(mode="json")))
    columns = {column: value["context"][field] for field, column in _CONTEXT_COLUMNS.items()}
    for group, column in _STATUS_COLUMNS.items():
        status = value["sampling"][group]["status"] if group in {"temperature", "top_p"} else value[group]["status"]
        columns[column] = {"supported": True, "unsupported": False, "unknown": None}[status]
    columns["reasoning_controls"] = value["reasoning"]["controls"]
    columns["input_modalities"] = value["modalities"]["input"]
    columns["output_modalities"] = value["modalities"]["output"]
    details = {
        "reasoning": {"response_paths": value["reasoning"]["response_paths"]},
        "tools": {key: value["tools"][key] for key in ("schema_constraints", "result_format")},
        "response": value["response"],
        "usage": value["usage"],
    }
    return StoredOutletCapabilities(columns, details)


def restore_outlet_capabilities(
    *,
    columns: Mapping[str, object],
    capability_details: Mapping[str, object],
) -> ProfileCapabilities:
    """Restore strictly from row-owned fields; no catalog or default composition."""
    columns, details = _clone(columns), _clone(capability_details)
    if not isinstance(columns, dict) or set(columns) != CAPABILITY_COLUMN_KEYS:
        raise CapabilityStorageError()
    if not isinstance(details, dict) or set(details) != {"reasoning", "tools", "response", "usage"}:
        raise CapabilityStorageError()
    expected = {
        "reasoning": {"response_paths"},
        "tools": {"schema_constraints", "result_format"},
        "response": {"supported_finish_reasons", "stream_format"},
        "usage": {"semantics_id", "input_includes_cached", "output_includes_reasoning"},
    }
    for group, keys in expected.items():
        if not isinstance(details[group], dict) or set(details[group]) != keys:
            raise CapabilityStorageError()
    value = {
        "context": {key: columns[column] for key, column in _CONTEXT_COLUMNS.items()},
        "reasoning": {
            "status": _status(columns["reasoning_supported"]),
            "controls": columns["reasoning_controls"],
            **details["reasoning"],
        },
        "tools": {"status": _status(columns["native_tool_call_supported"]), **details["tools"]},
        "structured_output": {"status": _status(columns["structured_output_supported"])},
        "sampling": {
            key: {"status": _status(columns[column])}
            for key, column in _STATUS_COLUMNS.items()
            if key in {"temperature", "top_p"}
        },
        "modalities": {"input": columns["input_modalities"], "output": columns["output_modalities"]},
        "response": details["response"],
        "usage": details["usage"],
    }
    return ProfileCapabilities.model_validate(_validate(_clone(value)))
