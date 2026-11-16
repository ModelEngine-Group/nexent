# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Save-time construction preserves composed facts and rejects invalid snapshots."""

from dataclasses import replace

import pytest
from nexent.core.model_service.profiles.composition import compose_provider_model_policy
from nexent.core.model_service.profiles.contracts import VersionedReference
from nexent.core.model_service.profiles.outlet_resolution import (
    OutletResolutionError,
    construct_resolved_model_profile,
)
from nexent.core.model_service.profiles.outlet_storage import (
    decode_resolved_model_profile,
    encode_resolved_model_profile,
)
from nexent.core.model_service.profiles.resolved_profile import (
    ConnectionRules,
    ContextConfiguration,
    OutletConnection,
)
from nexent.core.model_service.profiles.resolver import load_profile_catalog

REF = VersionedReference(ref="construction_fixture_v1", version=1)
REGISTRY = {key: [REF] for key in ("protocol", "auth", "adapter", "code_converter", "native_converter")}
REGISTRY["parameter_transform"] = [VersionedReference(ref="identity_v1", version=1)]


@pytest.fixture(scope="module")
def catalog():
    return load_profile_catalog()


def compose(catalog, **changes):
    options = {
        "provider_key": "alibaba-cn", "request_model_id": "qwen3.5-plus", "model_profile_key": None,
        "base_bindings": {key: REF.model_dump() for key in REGISTRY if key != "parameter_transform"},
        "base_instruction": VersionedReference(ref="system_only_v1", version=1),
        "registered_references": REGISTRY, "submitted_values": {},
    }
    options.update(changes)
    return compose_provider_model_policy(catalog, **options)


def construct(catalog, policy=None, **changes):
    options = {
        "tenant_id": "tenant", "display_name": "outlet", "model_type": "llm", "provider_id": "operator-provider",
        "connection": OutletConnection(base_url="https://fixture.invalid/v1", ssl_verify=True,
                                       timeout_seconds=120, concurrency_limit=None,
                                       credential_ref={"kind": "model_record", "model_id": None}),
        "connection_rules": ConnectionRules(credential_kind="model_record", relative_path="/chat/completions",
                                            method="POST", headers={}),
        "context_configuration": ContextConfiguration(output_reserve_tokens=None, tokenizer_family=None,
                                                      capacity_source="profile", capability_profile_version=None),
        "registered_references": REGISTRY,
    }
    options.update(changes)
    return construct_resolved_model_profile(policy or compose(catalog), catalog, **options)


def test_known_combination_constructs_complete_detached_snapshot(catalog):
    policy = compose(catalog, submitted_values={"enable_thinking": False})
    snapshot = construct(catalog, policy)
    assert snapshot.outlet_id is None and snapshot.config_revision == 1
    assert snapshot.identity.request_model_id == "qwen3.5-plus"
    assert snapshot.parameter_values == {"enable_thinking": False}
    assert snapshot.provider_key == "alibaba-cn" and snapshot.model_profile_key == "alibaba/qwen3.5-plus"
    assert snapshot.provenance.atomic_refs.provider_model.key == "alibaba-cn/qwen3.5-plus"
    assert snapshot.provenance.overrides and snapshot.provenance.field_sources
    assert snapshot.provenance.interpretation_versions.composer.version == 4
    snapshot.parameter_values["enable_thinking"] = True
    assert policy.parameter_values["enable_thinking"] is False


def test_custom_provider_retains_exact_request_identity_and_selected_model(catalog):
    policy = compose(catalog, provider_key=None, request_model_id="tenant/Exact-ID",
                     model_profile_key="alibaba/qwen3.5-plus")
    snapshot = construct(catalog, policy)
    assert snapshot.identity.request_model_id == "tenant/Exact-ID"
    assert snapshot.provenance.atomic_refs.provider is None
    assert snapshot.provenance.atomic_refs.provider_model is None
    assert snapshot.model_profile_key == "alibaba/qwen3.5-plus"
    assert snapshot.parameter_values == {}


def test_unmatched_outlet_keeps_unknown_capabilities(catalog):
    snapshot = construct(catalog, compose(catalog, provider_key=None, request_model_id="tenant/model"))
    assert snapshot.capabilities.tools.status == "unknown"
    assert snapshot.capabilities.context.combined_window is None
    assert snapshot.provenance.atomic_refs.model is None


def test_saved_row_restores_without_constructing_or_filling_defaults(catalog, monkeypatch):
    snapshot = construct(catalog, compose(catalog, submitted_values={"enable_thinking": False}))
    row = encode_resolved_model_profile(snapshot, registered_references=REGISTRY)
    row["model_id"] = 10
    def forbidden(*args, **kwargs):
        raise AssertionError("saved row attempted source access")
    monkeypatch.setattr("nexent.core.model_service.profiles.resolver.load_profile_catalog", forbidden)
    restored = decode_resolved_model_profile(row, registered_references=REGISTRY)
    assert restored.parameter_values == {"enable_thinking": False}
    assert restored.provenance.model_dump() == snapshot.provenance.model_dump()


@pytest.mark.parametrize("mutation,category", [
    ({"catalog_revision": "stale"}, "PROFILE_CATALOG_REVISION_MISMATCH"),
    ({"provider_key": "missing"}, "PROFILE_SELECTION_INVALID"),
    ({"model_profile_key": "missing"}, "PROFILE_SELECTION_INVALID"),
    ({"model_profile_key": None}, "PROFILE_SELECTION_INVALID"),
])
def test_stale_or_inconsistent_selection_fails(catalog, mutation, category):
    with pytest.raises(OutletResolutionError) as failure:
        construct(catalog, replace(compose(catalog), **mutation))
    assert failure.value.category == category


@pytest.mark.parametrize("changes", [
    {"registered_references": {}},
    {"extra_api_parameters": [{"path": "/vendor/option", "value": float("nan")}]},
    {"tenant_id": ""},
    {"connection": None},
    {"extra_api_parameters": [{"path": "/model", "value": "private-value"}], "protected_paths": ["/model"]},
    {"extra_api_parameters": [{"path": "/enable_thinking", "value": "private-value"}]},
])
def test_invalid_or_unavailable_snapshot_is_safely_rejected(catalog, changes):
    with pytest.raises(OutletResolutionError) as failure:
        construct(catalog, **changes)
    assert failure.value.category == "PROFILE_RESOLUTION_INVALID"
    assert "private-value" not in str(failure.value)


def test_missing_primary_source_reference_fails(catalog):
    policy = compose(catalog)
    atom = catalog.models[policy.model_profile_key]
    broken = replace(atom, source=replace(atom.source, source_refs=()))
    altered = replace(catalog, models={**catalog.models, atom.key: broken})
    with pytest.raises(OutletResolutionError) as failure:
        construct(altered, policy)
    assert failure.value.category == "PROFILE_SOURCE_REFERENCE_INVALID"


@pytest.mark.parametrize("policy,catalog_value", [(None, None), ("private-input", None)])
def test_wrong_internal_input_types_fail_safely(policy, catalog_value):
    with pytest.raises(OutletResolutionError) as failure:
        construct_resolved_model_profile(
            policy, catalog_value, tenant_id="tenant", display_name="outlet", model_type="llm",
            provider_id="provider", connection=None, connection_rules=None, context_configuration=None,
            registered_references=REGISTRY,
        )
    assert str(failure.value) == "PROFILE_SELECTION_INVALID"


def test_composed_defaults_are_applied_only_once_and_budget_zero_survives(catalog):
    policy = compose(catalog, submitted_values={"reasoning_budget_tokens": 0})
    snapshot = construct(catalog, policy)
    assert snapshot.parameter_values == {"enable_thinking": True, "reasoning_budget_tokens": 0}
    assert snapshot.provenance.interpretation_versions.source_mapping.ref == "models_dev_source_v1"
    assert all("#" in source.source_path for source in snapshot.provenance.field_sources)
    assert snapshot.provenance.atomic_refs.model.file_path.startswith("models/")
