# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import math

import pytest

from contracts.errors.exceptions import RuntimeMetadataValidationError
from contracts.errors.codes import RuntimeMetadataValidationCode

from infrastructure.serialization.runtime_metadata import (
    MAX_MCP_HEADERS_TOTAL_BYTES,
    MAX_MCP_HEADER_VALUE_BYTES,
    MAX_RUNTIME_METADATA_ARRAY_ITEMS,
    MAX_RUNTIME_METADATA_BYTES,
    MAX_RUNTIME_METADATA_DEPTH,
    MAX_RUNTIME_METADATA_KEY_LENGTH,
    MAX_RUNTIME_METADATA_KEYS,
    canonical_runtime_metadata_json,
    runtime_metadata_hash,
    validate_runtime_metadata,
)


def test_validate_runtime_metadata_accepts_nested_json_object():
    value = {
        "project-id": "P001",
        "nested": {"enabled": True, "values": [1, 2.5, None]},
    }

    assert validate_runtime_metadata(value) is value


@pytest.mark.parametrize("value", [[], "text", 1, None])
def test_validate_runtime_metadata_rejects_non_object_root(value):
    with pytest.raises(RuntimeMetadataValidationError) as exc_info:
        validate_runtime_metadata(value)

    assert exc_info.value.code == RuntimeMetadataValidationCode.INVALID_METADATA_TYPE


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, object()])
def test_validate_runtime_metadata_rejects_non_json_values(value):
    with pytest.raises(RuntimeMetadataValidationError) as exc_info:
        validate_runtime_metadata({"value": value})

    assert exc_info.value.code == RuntimeMetadataValidationCode.INVALID_METADATA_TYPE


def test_validate_runtime_metadata_enforces_depth():
    value = current = {}
    for index in range(MAX_RUNTIME_METADATA_DEPTH):
        current["child"] = {}
        current = current["child"]

    with pytest.raises(RuntimeMetadataValidationError) as exc_info:
        validate_runtime_metadata(value)

    assert exc_info.value.code == RuntimeMetadataValidationCode.METADATA_TOO_DEEP


def test_validate_runtime_metadata_enforces_total_keys():
    value = {str(index): index for index in range(MAX_RUNTIME_METADATA_KEYS + 1)}

    with pytest.raises(RuntimeMetadataValidationError) as exc_info:
        validate_runtime_metadata(value)

    assert exc_info.value.code == RuntimeMetadataValidationCode.METADATA_TOO_MANY_ITEMS


def test_validate_runtime_metadata_enforces_total_array_items():
    value = {"items": list(range(MAX_RUNTIME_METADATA_ARRAY_ITEMS + 1))}

    with pytest.raises(RuntimeMetadataValidationError) as exc_info:
        validate_runtime_metadata(value)

    assert exc_info.value.code == RuntimeMetadataValidationCode.METADATA_TOO_MANY_ITEMS


def test_validate_runtime_metadata_enforces_canonical_utf8_size():
    value = {"text": "测" * MAX_RUNTIME_METADATA_BYTES}

    with pytest.raises(RuntimeMetadataValidationError) as exc_info:
        validate_runtime_metadata(value)

    assert exc_info.value.code == RuntimeMetadataValidationCode.METADATA_TOO_LARGE


def test_canonical_json_and_hash_are_order_independent():
    left = {"b": 2, "a": {"x": 1}}
    right = {"a": {"x": 1}, "b": 2}

    assert canonical_runtime_metadata_json(left) == canonical_runtime_metadata_json(right)
    assert runtime_metadata_hash(left) == runtime_metadata_hash(right)


def test_validate_runtime_metadata_rejects_non_string_key():
    with pytest.raises(RuntimeMetadataValidationError) as exc_info:
        validate_runtime_metadata({1: "value"})

    assert exc_info.value.code == RuntimeMetadataValidationCode.INVALID_METADATA_TYPE


def test_validate_runtime_metadata_rejects_overlong_key():
    long_key = "k" * (MAX_RUNTIME_METADATA_KEY_LENGTH + 1)

    with pytest.raises(RuntimeMetadataValidationError) as exc_info:
        validate_runtime_metadata({long_key: "value"})

    assert exc_info.value.code == RuntimeMetadataValidationCode.METADATA_TOO_MANY_ITEMS


# ---------------------------------------------------------------------------
# Phase 1: northbound MCP header passthrough reserved fields
# UT-BE-PASS-004 (key whitelist) / UT-BE-PASS-005 (size limits)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", ["authorization", "Cookie", "X-User-Id", "x-trace-id"])
def test_ut_be_pass_004_accepts_whitelisted_and_x_prefixed_keys(key):
    value = {"_mcp_headers": {key: "value"}}

    assert validate_runtime_metadata(value) is value


@pytest.mark.parametrize("key", ["Host", "content-length", "Connection", "TE"])
def test_ut_be_pass_004_rejects_hop_by_hop_headers(key):
    with pytest.raises(RuntimeMetadataValidationError) as exc_info:
        validate_runtime_metadata({"_mcp_headers": {key: "value"}})

    assert exc_info.value.code == RuntimeMetadataValidationCode.MCP_HEADER_KEY_FORBIDDEN


@pytest.mark.parametrize("key", ["Referer", "User-Agent", "Set-Cookie"])
def test_ut_be_pass_004_rejects_non_whitelisted_headers(key):
    with pytest.raises(RuntimeMetadataValidationError) as exc_info:
        validate_runtime_metadata({"_mcp_headers": {key: "value"}})

    assert exc_info.value.code == RuntimeMetadataValidationCode.MCP_HEADER_KEY_FORBIDDEN


def test_ut_be_pass_004_rejects_non_object_header_block():
    for metadata in (
        {"_mcp_headers": ["Cookie"]},
        {"_mcp_headers": {"Cookie": 1}},
        {"_mcp_headers": {"": "value"}},
        {"_mcp_headers_by_server": ["http://a/mcp"]},
        {"_mcp_headers_by_server": {"": {"Cookie": "value"}}},
    ):
        with pytest.raises(RuntimeMetadataValidationError) as exc_info:
            validate_runtime_metadata(metadata)

        assert exc_info.value.code == RuntimeMetadataValidationCode.MCP_HEADER_TYPE_INVALID


def test_ut_be_pass_005_rejects_oversized_single_header_value():
    oversized = "a" * (MAX_MCP_HEADER_VALUE_BYTES + 1)

    with pytest.raises(RuntimeMetadataValidationError) as exc_info:
        validate_runtime_metadata({"_mcp_headers": {"Cookie": oversized}})

    assert exc_info.value.code == RuntimeMetadataValidationCode.MCP_HEADER_VALUE_TOO_LARGE


def test_ut_be_pass_005_rejects_oversized_cumulative_header_values():
    per_value = "a" * (MAX_MCP_HEADER_VALUE_BYTES - 1)
    # Each block stays under the per-header limit; together they blow the cap.
    blocks = {
        f"http://server-{index}/mcp": {f"X-Header-{index}": per_value}
        for index in range(MAX_MCP_HEADERS_TOTAL_BYTES // MAX_MCP_HEADER_VALUE_BYTES + 2)
    }

    with pytest.raises(RuntimeMetadataValidationError) as exc_info:
        validate_runtime_metadata({"_mcp_headers_by_server": blocks})

    assert exc_info.value.code == RuntimeMetadataValidationCode.MCP_HEADER_VALUE_TOO_LARGE


def test_ut_be_pass_005_accepts_values_at_the_size_limit():
    value = {"_mcp_headers": {"Cookie": "a" * MAX_MCP_HEADER_VALUE_BYTES}}

    assert validate_runtime_metadata(value) is value


def test_ut_be_pass_004_blank_header_key_is_never_allowed():
    # The public validator rejects blank keys earlier; the predicate must stay
    # safe on its own for any future caller.
    from infrastructure.serialization import runtime_metadata as module

    assert module._is_passthrough_header_allowed("   ") is False


def test_validate_runtime_metadata_wraps_serialization_failures(monkeypatch):
    from infrastructure.serialization import runtime_metadata as module

    def _raise_type_error(_value):
        raise TypeError("not serializable")

    monkeypatch.setattr(module, "runtime_metadata_size_bytes", _raise_type_error)

    with pytest.raises(RuntimeMetadataValidationError) as exc_info:
        validate_runtime_metadata({"project_id": "P001"})

    assert exc_info.value.code == RuntimeMetadataValidationCode.INVALID_METADATA_TYPE


# ---------------------------------------------------------------------------
# Phase 1 reserved-field stripping — keep transport-only headers out of
# persistence.  These tests guard against regression where a future edit
# accidentally forgets to clean metadata before handing it to the DB.
# ---------------------------------------------------------------------------

def test_strip_reserved_fields_removes_underscore_prefixed_top_level_keys():
    from infrastructure.serialization.runtime_metadata import (
        strip_reserved_runtime_metadata_fields,
    )

    metadata = {
        "project_id": "P001",
        "tenant": "tenant-1",
        "_mcp_headers": {"Cookie": "sid=super-secret"},
        "_mcp_headers_by_server": {
            "http://echo-mcp/mcp": {"Authorization": "Bearer xyz"}
        },
        # A future Phase-2 reserved field that does not exist yet — the
        # underscore convention guarantees it is stripped too.
        "_future_reserved": {"nested": "also-stripped"},
    }

    clean = strip_reserved_runtime_metadata_fields(metadata)

    # Public keys survive intact.
    assert clean == {"project_id": "P001", "tenant": "tenant-1"}
    # Transport-only keys never reach persistence.
    assert "_mcp_headers" not in clean
    assert "_mcp_headers_by_server" not in clean
    assert "_future_reserved" not in clean
    # The caller's original dict is untouched — passthrough still needs it.
    assert "_mcp_headers" in metadata


@pytest.mark.parametrize("metadata", [None, {}, ["a", "b"], "text", 123])
def test_strip_reserved_fields_is_defensive_on_non_dict_input(metadata):
    from infrastructure.serialization.runtime_metadata import (
        strip_reserved_runtime_metadata_fields,
    )

    assert strip_reserved_runtime_metadata_fields(metadata) == {}


def test_strip_reserved_fields_keeps_underscore_nested_values():
    """Only TOP-LEVEL keys are transport-reserved.  Nested dicts may legally
    carry underscore-prefixed keys — those belong to the caller's domain and
    must not be touched."""
    from infrastructure.serialization.runtime_metadata import (
        strip_reserved_runtime_metadata_fields,
    )

    metadata = {
        "audit_context": {
            "_actor": "system",
            "_trace": {"_id": "xyz"},
            "event": "login",
        },
        "_mcp_headers": {"Cookie": "secret"},
    }

    clean = strip_reserved_runtime_metadata_fields(metadata)

    # Top-level _mcp_headers stripped.
    assert "_mcp_headers" not in clean
    # Nested underscore keys untouched.
    assert clean["audit_context"] == metadata["audit_context"]
