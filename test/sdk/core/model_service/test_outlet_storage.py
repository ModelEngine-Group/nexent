# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Whole-row outlet codec validates ownership, versions and saved configuration."""

from copy import deepcopy

import pytest
from nexent.core.model_service.profiles.contracts import VersionedReference
from nexent.core.model_service.profiles.instruction_mapping import (
    resolve_instruction_mapping,
)
from nexent.core.model_service.profiles.outlet_storage import (
    ProfileStorageError,
    decode_resolved_model_profile,
    encode_resolved_model_profile,
)
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
from pydantic import ValidationError

REFERENCE = VersionedReference(ref="fixture_v1", version=1)
ROLE = VersionedReference(ref="system_only_v1", version=1)
REGISTRY = {
    key: [REFERENCE]
    for key in (
        "protocol",
        "auth",
        "adapter",
        "code_converter",
        "native_converter",
        "parameter_transform",
    )
}


def rule(key, **changes):
    value = {
        "key": key,
        "schema": {},
        "visible": True,
        "editable": True,
        "required": False,
        "allowed_scopes": ["outlet", "conversation"],
        "ui_group": "common",
        "owner": "provider",
        "source": {"rule_id": "fixture"},
        "api_binding": {
            "path": "/" + key,
            "transform_ref": "fixture_v1",
            "transform_version": 1,
        },
    }
    value.update(changes)
    return value


@pytest.fixture
def document():
    return {
        "schema_version": 1,
        "outlet_id": 12,
        "config_revision": 1,
        "identity": {
            "tenant_id": "tenant",
            "display_name": "model display",
            "model_type": "llm",
            "provider_id": "custom-provider",
            "request_model_id": "Exact/MODEL",
            "provider_key": None,
            "model_profile_key": None,
        },
        "connection": {
            "base_url": "http://localhost:8000/v1",
            "ssl_verify": False,
            "timeout_seconds": 120,
            "concurrency_limit": None,
            "credential_ref": {"kind": "model_record", "model_id": 12},
        },
        "connection_rules": {
            "credential_kind": "model_record",
            "relative_path": "/chat/completions",
            "method": "POST",
            "headers": {"Accept": "application/json"},
        },
        "context_configuration": {
            "output_reserve_tokens": None,
            "tokenizer_family": None,
            "capacity_source": "operator",
            "capability_profile_version": None,
        },
        "capabilities": {},
        "instruction_mapping": resolve_instruction_mapping(ROLE).model_dump(
            mode="json"
        ),
        "parameter_rules": [
            rule("temperature", schema={"type": "number"}, fixed_value=0),
            rule("custom", default_value="default"),
        ],
        "parameter_values": {"temperature": 0, "custom": None},
        "extra_api_parameters": [{"path": "/vendor/option", "value": False}],
        "bindings": {
            **{
                key: REFERENCE.model_dump()
                for key in REGISTRY
                if key != "parameter_transform"
            },
            "role_mapping": ROLE.model_dump(),
        },
        "provenance": {
            "atomic_refs": {"model": None, "provider": None, "provider_model": None},
            "interpretation_versions": {
                "source_parser": None,
                "source_mapping": None,
                "supplement_schema": None,
                "composer": None,
            },
            "overrides": [],
            "field_sources": [],
            "provider_metadata": {},
        },
    }


def encode(document):
    return encode_resolved_model_profile(
        ResolvedModelProfile.model_validate(document), registered_references=REGISTRY
    )


def decode(row):
    return decode_resolved_model_profile(row, registered_references=REGISTRY)


def test_output_cap_and_request_default_have_independent_single_locations(document):
    document["capabilities"] = {"context": {"output_limit": 32000}}
    document["parameter_rules"].append(rule("max_output_tokens"))
    document["parameter_values"]["max_output_tokens"] = 4096
    row = encode(document)
    assert row["max_output_tokens"] == 32000
    assert row["default_max_output_tokens"] == 4096
    assert "max_output_tokens" not in row["extra_params"]["parameter_values"]
    restored = decode(row)
    assert restored.capabilities.context.output_limit == 32000
    assert restored.parameter_values["max_output_tokens"] == 4096


def test_complete_snapshot_round_trip_without_duplicate_values_or_credentials(document):
    profile = ResolvedModelProfile.model_validate(document)
    row = encode(document)
    assert "api_key" not in row
    assert "max_tokens" not in row
    assert row["temperature"] == 0
    assert row["extra_params"]["parameter_values"] == {"custom": None}
    assert row["resolved_profile"]["parameter_rules"][0]["fixed_to_saved_value"] is True
    assert "fixed_value" not in row["resolved_profile"]["parameter_rules"][0]
    assert "protocol" not in row["resolved_profile"]["bindings"]
    assert row["protocol_id"] == "fixture_v1"
    assert row["resolved_profile"]["bindings"]["protocol_version"] == 1
    assert decode(row).model_dump() == profile.model_dump()
    row["api_key"] = "credential-private"
    assert decode(row).model_dump() == profile.model_dump()
    assert "credential-private" not in repr(decode(row))


def test_creation_before_database_id_assignment_and_no_default_application(document):
    document["outlet_id"] = None
    document["connection"]["credential_ref"]["model_id"] = None
    document["parameter_values"].pop("custom")
    row = encode(document)
    assert "model_id" not in row
    row["model_id"] = 27
    profile = decode(row)
    assert profile.outlet_id == profile.connection.credential_ref.model_id == 27
    assert "custom" not in profile.parameter_values


def test_snapshot_load_is_detached_and_ignores_unrelated_row_fields(document):
    row = encode(document)
    row["create_time"] = object()
    original = deepcopy(row["resolved_profile"])
    restored = decode(row)
    restored.parameter_rules[0]["schema"]["type"] = "string"
    restored.connection_rules.headers["Accept"] = "changed"
    assert row["resolved_profile"] == original


@pytest.mark.parametrize(
    "key",
    [
        "model_id",
        "resolved_profile",
        "protocol_id",
        "extra_params",
        "timeout_seconds",
        "config_revision",
    ],
)
def test_incomplete_rows_fail_without_catalog_fallback(document, key):
    row = encode(document)
    row.pop(key)
    with pytest.raises(ProfileStorageError, match="^PROFILE_STORAGE_INVALID$"):
        decode(row)


@pytest.mark.parametrize(
    "key,value",
    [
        ("profile_schema_version", None),
        ("profile_schema_version", True),
        ("profile_schema_version", 2),
        ("model_id", True),
        ("model_id", 0),
        ("config_revision", 0),
        ("temperature", True),
        ("protocol_id", "x" * 31),
        ("timeout_seconds", -1),
    ],
)
def test_invalid_row_types_and_versions_are_rejected(document, key, value):
    row = encode(document)
    row[key] = value
    with pytest.raises(ProfileStorageError):
        decode(row)


@pytest.mark.parametrize(
    "group",
    [
        "protocol",
        "auth",
        "adapter",
        "code_converter",
        "native_converter",
        "parameter_transform",
    ],
)
def test_unavailable_implementation_versions_fail_both_save_and_load(document, group):
    row = encode(document)
    registry = {key: refs for key, refs in REGISTRY.items() if key != group}
    with pytest.raises(ProfileStorageError):
        encode_resolved_model_profile(
            ResolvedModelProfile.model_validate(document),
            registered_references=registry,
        )
    with pytest.raises(ProfileStorageError):
        decode_resolved_model_profile(row, registered_references=registry)


@pytest.mark.parametrize(
    "group,value",
    [
        ("extra_params", {"temperature": 0}),
        ("extra_params", None),
        ("resolved_profile", None),
        ("resolved_profile", {"api_key": "private"}),
    ],
)
def test_legacy_or_bare_configuration_is_not_treated_as_resolved(
    document, group, value
):
    row = encode(document)
    row[group] = value
    with pytest.raises(ProfileStorageError) as captured:
        decode(row)
    assert "private" not in str(captured.value)


def test_duplicate_storage_and_conflicting_null_marker_fail(document):
    row = encode(document)
    row["extra_params"]["parameter_values"]["temperature"] = 0
    with pytest.raises(ProfileStorageError):
        decode(row)
    row = encode(document)
    row["resolved_profile"]["explicit_null_parameters"] = ["temperature"]
    with pytest.raises(ProfileStorageError):
        decode(row)


def test_protected_adapter_paths_are_enforced_at_both_storage_boundaries(document):
    row = encode(document)
    with pytest.raises(ProfileStorageError):
        decode_resolved_model_profile(
            row, registered_references=REGISTRY, protected_paths=["/vendor"]
        )
    with pytest.raises(ProfileStorageError):
        encode_resolved_model_profile(
            ResolvedModelProfile.model_validate(document),
            registered_references=REGISTRY,
            protected_paths=["/temperature"],
        )


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["connection"]["credential_ref"].update(model_id=99),
        lambda d: d["connection"].update(api_key="private"),
        lambda d: d["provenance"].update(unknown=True),
        lambda d: d["bindings"].update(role_mapping={"ref": "other", "version": 1}),
        lambda d: d.update(schema_version=True),
        lambda d: d["identity"].update(request_model_id="x" * 101),
        lambda d: d["extra_api_parameters"].append(
            {"path": "/model", "value": "other"}
        ),
    ],
)
def test_complete_contract_rejects_unowned_or_conflicting_fields(document, change):
    change(document)
    with pytest.raises((ValueError, ValidationError)):
        ResolvedModelProfile.model_validate(document)


def test_serialization_revalidates_mutated_nested_values(document):
    profile = ResolvedModelProfile.model_validate(document)
    profile.parameter_values["temperature"] = 1
    with pytest.raises(ProfileStorageError):
        encode_resolved_model_profile(profile, registered_references=REGISTRY)


def test_atomic_identity_restores_from_provenance_without_source_reads(
    document, monkeypatch
):
    from pathlib import Path

    reference = {
        "key": "provider/family",
        "catalog_revision": "catalog-one",
        "file_path": "providers/family/provider.toml",
        "content_sha256": "a" * 64,
    }
    document["provenance"]["atomic_refs"]["provider"] = reference
    document["identity"]["provider_key"] = "provider/family"
    row = encode(document)

    def unexpected_read(*args, **kwargs):
        pytest.fail("Saved outlet loading must not read source files")

    monkeypatch.setattr(Path, "read_text", unexpected_read)
    restored = decode(row)
    assert restored.identity.provider_key == restored.provider_key == "provider/family"
    assert "identity" not in row["resolved_profile"]
    assert restored.provenance.atomic_refs.provider.content_sha256 == "a" * 64


@pytest.mark.parametrize(
    "key,control,schema,value",
    [
        (
            "enable_thinking",
            {"mode": "toggle", "values": [False, True]},
            {"type": "boolean", "enum": [False, True]},
            False,
        ),
        (
            "reasoning_effort",
            {"mode": "effort", "values": [None, "high"]},
            {"type": ["string", "null"], "enum": [None, "high"]},
            None,
        ),
        (
            "reasoning_budget_tokens",
            {"mode": "budget_tokens", "min": 0, "max": 10, "special_values": [-1]},
            {"type": "integer"},
            -1,
        ),
    ],
)
def test_full_row_round_trip_includes_reasoning_domains_and_null_presence(
    document, key, control, schema, value
):
    document["capabilities"] = {
        "reasoning": {"status": "supported", "controls": [control]}
    }
    document["parameter_rules"].append(rule(key, schema=schema))
    document["parameter_values"][key] = value
    row = encode(document)
    assert key not in row["extra_params"]["parameter_values"]
    assert decode(row).parameter_values[key] == value
    assert row["resolved_profile"]["explicit_null_parameters"] == (
        [key] if value is None else []
    )


@pytest.mark.parametrize(
    "control,value",
    [
        ({"mode": "toggle", "values": [False]}, True),
        ({"mode": "budget_tokens", "min": 0, "max": 10}, -1),
        ({"mode": "budget_tokens", "min": 0, "max": 10}, 11),
    ],
)
def test_saved_values_cannot_exceed_declared_reasoning_domain(document, control, value):
    key = (
        "enable_thinking" if control["mode"] == "toggle" else "reasoning_budget_tokens"
    )
    document["capabilities"] = {
        "reasoning": {"status": "supported", "controls": [control]}
    }
    document["parameter_rules"].append(rule(key))
    document["parameter_values"][key] = value
    with pytest.raises(ValueError):
        ResolvedModelProfile.model_validate(document)


def test_control_declaration_requires_a_rule_even_when_value_is_not_sent(document):
    document["capabilities"] = {
        "reasoning": {"controls": [{"mode": "toggle", "values": [False, True]}]}
    }
    with pytest.raises(ValueError):
        ResolvedModelProfile.model_validate(document)
    document["parameter_rules"].append(rule("enable_thinking"))
    assert "enable_thinking" not in decode(encode(document)).parameter_values


def test_schema_with_missing_parameter_binding_is_not_persistable(document):
    document["parameter_rules"][0]["api_binding"].pop("path")
    with pytest.raises(ValueError):
        ResolvedModelProfile.model_validate(document)


def test_duplicate_protocol_reference_in_remaining_json_fails(document):
    row = encode(document)
    row["resolved_profile"]["bindings"]["protocol"] = REFERENCE.model_dump()
    with pytest.raises(ProfileStorageError):
        decode(row)


def test_oversized_complete_configuration_is_rejected(document):
    profile = ResolvedModelProfile.model_validate(document)
    profile.provenance.provider_metadata["filler"] = "x" * (1024 * 1024)
    with pytest.raises(ProfileStorageError):
        encode_resolved_model_profile(profile, registered_references=REGISTRY)


def test_atomic_key_cannot_contradict_provenance(document):
    document["identity"]["model_profile_key"] = "unrelated-model"
    with pytest.raises(ValueError):
        ResolvedModelProfile.model_validate(document)


def test_integer_sampling_schema_survives_postgresql_float_column(document):
    document["parameter_rules"][0]["schema"] = {"type": "integer"}
    row = encode(document)
    row["temperature"] = (
        0.0  # PostgreSQL FLOAT returns a Python float for an integer insert.
    )
    profile = decode(row)
    assert type(profile.parameter_values["temperature"]) is int
    assert profile.parameter_values["temperature"] == 0
