import math

import pytest

from utils.runtime_metadata_utils import (
    MAX_RUNTIME_METADATA_ARRAY_ITEMS,
    MAX_RUNTIME_METADATA_BYTES,
    MAX_RUNTIME_METADATA_DEPTH,
    MAX_RUNTIME_METADATA_KEY_LENGTH,
    MAX_RUNTIME_METADATA_KEYS,
    RuntimeMetadataValidationError,
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

    assert exc_info.value.code == "INVALID_METADATA_TYPE"


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, object()])
def test_validate_runtime_metadata_rejects_non_json_values(value):
    with pytest.raises(RuntimeMetadataValidationError) as exc_info:
        validate_runtime_metadata({"value": value})

    assert exc_info.value.code == "INVALID_METADATA_TYPE"


def test_validate_runtime_metadata_enforces_depth():
    value = current = {}
    for index in range(MAX_RUNTIME_METADATA_DEPTH):
        current["child"] = {}
        current = current["child"]

    with pytest.raises(RuntimeMetadataValidationError) as exc_info:
        validate_runtime_metadata(value)

    assert exc_info.value.code == "METADATA_TOO_DEEP"


def test_validate_runtime_metadata_enforces_total_keys():
    value = {str(index): index for index in range(MAX_RUNTIME_METADATA_KEYS + 1)}

    with pytest.raises(RuntimeMetadataValidationError) as exc_info:
        validate_runtime_metadata(value)

    assert exc_info.value.code == "METADATA_TOO_MANY_ITEMS"


def test_validate_runtime_metadata_enforces_total_array_items():
    value = {"items": list(range(MAX_RUNTIME_METADATA_ARRAY_ITEMS + 1))}

    with pytest.raises(RuntimeMetadataValidationError) as exc_info:
        validate_runtime_metadata(value)

    assert exc_info.value.code == "METADATA_TOO_MANY_ITEMS"


def test_validate_runtime_metadata_enforces_canonical_utf8_size():
    value = {"text": "测" * MAX_RUNTIME_METADATA_BYTES}

    with pytest.raises(RuntimeMetadataValidationError) as exc_info:
        validate_runtime_metadata(value)

    assert exc_info.value.code == "METADATA_TOO_LARGE"


def test_canonical_json_and_hash_are_order_independent():
    left = {"b": 2, "a": {"x": 1}}
    right = {"a": {"x": 1}, "b": 2}

    assert canonical_runtime_metadata_json(left) == canonical_runtime_metadata_json(right)
    assert runtime_metadata_hash(left) == runtime_metadata_hash(right)


def test_validate_runtime_metadata_rejects_non_string_key():
    with pytest.raises(RuntimeMetadataValidationError) as exc_info:
        validate_runtime_metadata({1: "value"})

    assert exc_info.value.code == "INVALID_METADATA_TYPE"


def test_validate_runtime_metadata_rejects_overlong_key():
    long_key = "k" * (MAX_RUNTIME_METADATA_KEY_LENGTH + 1)

    with pytest.raises(RuntimeMetadataValidationError) as exc_info:
        validate_runtime_metadata({long_key: "value"})

    assert exc_info.value.code == "METADATA_TOO_MANY_ITEMS"

