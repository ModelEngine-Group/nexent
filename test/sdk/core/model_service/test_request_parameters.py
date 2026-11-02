# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Extra body parameters cannot overwrite owned request fields or caller state."""

import json
from copy import deepcopy
from types import MappingProxyType

import pytest
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError
from nexent.core.model_service.profiles.request_parameters import (
    apply_extra_api_parameters,
)


def extra(path, value):
    return {"path": path, "value": value}


def test_extra_values_are_body_only_and_inputs_are_independent():
    body = {
        "model": "exact",
        "messages": [],
        "options": {"old": 1},
        "array": [{"old": 2}],
    }
    original = deepcopy(body)
    extras = [
        extra("/options/new", False),
        extra("/array/0/custom", None),
        extra("/nested/value", [0]),
    ]
    result = apply_extra_api_parameters(body, extras)
    assert result == {
        "model": "exact",
        "messages": [],
        "options": {"old": 1, "new": False},
        "array": [{"old": 2, "custom": None}],
        "nested": {"value": [0]},
    }
    result["nested"]["value"].append(1)
    assert body == original
    assert extras[-1]["value"] == [0]


def test_escaped_pointer_keys_and_numeric_object_keys_keep_literal_meanings():
    result = apply_extra_api_parameters(
        {}, [extra("/a~1b/~0key", 0), extra("/object/00", "")]
    )
    assert result == {"a/b": {"~key": 0}, "object": {"00": ""}}
    assert apply_extra_api_parameters(
        MappingProxyType({"nested": MappingProxyType({})}), []
    ) == {"nested": {}}


@pytest.mark.parametrize(
    "path",
    [
        "/model",
        "/messages/0/content",
        "/tools",
        "/tool_choice",
        "/stream",
        "/stream_options/include_usage",
        "/custom",
        "/custom/owned/value",
    ],
)
def test_owned_paths_and_ancestors_cannot_be_overridden(path):
    with pytest.raises(ParameterValidationError, match="RESERVED_API_PATH"):
        apply_extra_api_parameters(
            {}, [extra(path, "secret")], parameter_paths=["/custom/owned"]
        )


def test_provider_protected_paths_are_checked_after_pointer_decoding():
    with pytest.raises(ParameterValidationError, match="RESERVED_API_PATH"):
        apply_extra_api_parameters(
            {}, [extra("/a~1b", 0)], protected_paths=["/a~1b/owned"]
        )


@pytest.mark.parametrize(
    "paths",
    [
        ["/custom", "/custom"],
        ["/custom", "/custom/nested"],
        ["/custom/nested", "/custom"],
    ],
)
def test_duplicate_and_parent_child_parameters_conflict(paths):
    with pytest.raises(ParameterValidationError, match="API_PATH_CONFLICT"):
        apply_extra_api_parameters({}, [extra(path, 0) for path in paths])


@pytest.mark.parametrize("path", ["", "model", "#/custom", "/~", "/bad~2key"])
def test_malformed_pointers_are_rejected(path):
    with pytest.raises(ParameterValidationError, match="API_PATH_INVALID"):
        apply_extra_api_parameters({}, [extra(path, 0)])


@pytest.mark.parametrize(
    "index", ["00", "01", "-", "-1", "1", "999999999999999999999999"]
)
def test_array_aliases_append_and_out_of_range_indices_are_rejected(index):
    body = {"array": [0]}
    with pytest.raises(ParameterValidationError, match="API_PATH_INVALID"):
        apply_extra_api_parameters(body, [extra("/array/" + index, 1)])
    assert body == {"array": [0]}


@pytest.mark.parametrize("path", ["/scalar/nested", "/scalar/nested/value"])
def test_scalar_parent_conflict_has_no_partial_mutation(path):
    body = {"scalar": 0}
    with pytest.raises(ParameterValidationError, match="API_PATH_CONFLICT"):
        apply_extra_api_parameters(
            body, [extra("/valid", 1), extra(path, 2)]
        )
    assert body == {"scalar": 0}


@pytest.mark.parametrize(
    "entry",
    [{"path": "/custom"}, {"path": "/custom", "value": 1, "header": "secret"}, None],
)
def test_unknown_entry_fields_are_not_a_header_or_auth_escape(entry):
    with pytest.raises(ParameterValidationError, match="EXTRA_API_PARAMETER_INVALID"):
        apply_extra_api_parameters({}, [entry])


def test_leaf_limit_boundary_and_nonfinite_values():
    assert (
        len(
            apply_extra_api_parameters({}, [extra("/custom", list(range(128)))])[
                "custom"
            ]
        )
        == 128
    )
    with pytest.raises(ParameterValidationError, match="EXTRA_API_PARAMETERS_LIMIT"):
        apply_extra_api_parameters({}, [extra("/custom", list(range(129)))])
    for value in [float("inf"), float("nan"), object()]:
        with pytest.raises(ParameterValidationError, match="PARAMETER_JSON_INVALID"):
            apply_extra_api_parameters({}, [extra("/custom", value)])


def test_byte_limit_is_utf8_serialized_extras():
    overhead = len(
        json.dumps(
            [extra("/custom", "")], ensure_ascii=False, separators=(",", ":")
        ).encode()
    )
    limit_value = "a" * (65536 - overhead)
    assert (
        apply_extra_api_parameters({}, [extra("/custom", limit_value)])["custom"]
        == limit_value
    )
    with pytest.raises(ParameterValidationError, match="EXTRA_API_PARAMETERS_LIMIT"):
        apply_extra_api_parameters({}, [extra("/custom", limit_value + "中")])


def test_depth_limit_is_checked_without_modifying_source():
    value = 0
    for _ in range(16):
        value = {"nested": value}
    assert apply_extra_api_parameters({}, [extra("/custom", value)])["custom"] == value
    with pytest.raises(ParameterValidationError, match="EXTRA_API_PARAMETERS_LIMIT"):
        apply_extra_api_parameters({}, [extra("/custom", {"nested": value})])


def test_invalid_json_containers_and_encoding_are_sanitized():
    for body, extras in [
        ([], []),
        ({}, {}),
        ({}, [extra("/custom", "\ud800")]),
        ({}, [extra("/custom", {0: 1})]),
    ]:
        with pytest.raises(ParameterValidationError, match="PARAMETER_JSON_INVALID"):
            apply_extra_api_parameters(body, extras)
