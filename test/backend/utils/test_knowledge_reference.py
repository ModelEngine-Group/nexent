# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Contracts for managed knowledge parameters and deletion lock keys."""

import pytest

from backend.utils import knowledge_reference as reference


@pytest.mark.parametrize(
    "value, expected",
    [
        (["idx-1", "idx-1", " idx-2 ", ""], ["idx-1", "idx-2"]),
        ('["kds-1", "kds-2", "kds-1"]', ["kds-1", "kds-2"]),
        ([213, "213", "214"], ["213", "214"]),
        (["name,with,commas"], ["name,with,commas"]),
        ([], []),
        ("[]", []),
    ],
)
def test_parse_actual_selection_formats(value, expected):
    assert reference.parse_knowledge_id_list(value) == expected


@pytest.mark.parametrize(
    "value",
    [None, "", "kds-1,kds-2", "not json", '"kds-1"', "213", 213,
     True, 213.0, {"id": "kds-1"}, ("kds-1",), {"kds-1"}],
)
def test_unsupported_collection_formats_do_not_create_bindings(value):
    assert reference.parse_knowledge_id_list(value) == []


@pytest.mark.parametrize("value", [True, False, 213.0, 213.5, {}, [], None])
def test_non_id_values_are_not_coerced_into_resource_ids(value):
    assert reference.normalize_resource_id(value) == ""
    assert reference.parse_knowledge_id_list([value]) == []


def test_ids_are_trimmed_and_deduplicated_in_input_order():
    assert reference.dedupe_ids([213, "213", "", None, " idx-1 "]) == ["213", "idx-1"]


def test_params_keep_local_and_aidp_ids_separate():
    params = {"index_names": ["213", "213"], "kds_list": '["213"]', "other": ["x"]}
    assert reference.iter_reference_params(params) == [
        ("local", "index_names", "213"),
        ("aidp", "kds_list", "213"),
    ]
    assert reference.optional_resources_from_params(params) == [("local", "213"), ("aidp", "213")]
    assert reference.optional_resources_from_params(None) == []
    assert reference.iter_reference_params({"index_names": ["idx-1"]}) == [
        ("local", "index_names", "idx-1")
    ]


@pytest.mark.parametrize(
    "provider, resource_id, namespace, expected",
    [
        ("local", "idx-1", "", -7504364216728551079),
        ("aidp", "kds-1", "", 6242910072658742),
        ("aidp", "kds-1", "ns", 9012813823394043341),
    ],
)
def test_lock_keys_match_the_existing_delete_and_write_protocol(provider, resource_id, namespace, expected):
    assert reference.resource_lock_key(provider, resource_id, namespace) == expected


def test_lock_keys_separate_providers_and_deployments():
    key = reference.resource_lock_key("aidp", "213", "ns")
    assert reference.resource_lock_key("local", "213", "ns") != key
    assert reference.resource_lock_key("aidp", "213", "other") != key
