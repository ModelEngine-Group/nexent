# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Actual source-to-outlet collaboration, independent of traditional unit tests."""

import hashlib
import shutil
import socket
from dataclasses import replace
from pathlib import Path

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

ROOT = Path(__file__).resolve().parents[3] / "sdk/nexent/core/model_service/profiles"
REFERENCE = VersionedReference(ref="component_available_v1", version=1)
REGISTRY = {key: [REFERENCE] for key in ("protocol", "auth", "adapter", "code_converter", "native_converter")}
REGISTRY["parameter_transform"] = [VersionedReference(ref="identity_v1", version=1)]
pytestmark = [pytest.mark.case_id("MPR-D1-001"), pytest.mark.stage("D1")]


def source_hashes(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob("*.toml")}


@pytest.fixture(autouse=True)
def external_boundaries_and_source_ownership(monkeypatch):
    before = source_hashes(ROOT)
    def forbidden(*args, **kwargs):
        raise AssertionError("Outlet construction crossed a network/database boundary")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    yield
    assert source_hashes(ROOT) == before


def policy(catalog, *, provider="alibaba-cn", model="qwen3.5-plus", atom=None, values=None):
    return compose_provider_model_policy(
        catalog, provider_key=provider, request_model_id=model, model_profile_key=atom,
        base_bindings={key: REFERENCE.model_dump() for key in REGISTRY if key != "parameter_transform"},
        base_instruction=VersionedReference(ref="system_only_v1", version=1),
        registered_references=REGISTRY, submitted_values={} if values is None else values,
    )


def construct(catalog, draft, **changes):
    arguments = {
        "tenant_id": "component-tenant", "display_name": "source outlet", "model_type": "llm",
        "provider_id": "custom-or-known-provider",
        "connection": OutletConnection(base_url="https://fixture.invalid/v1", ssl_verify=True,
                                       timeout_seconds=120, concurrency_limit=2,
                                       credential_ref={"kind": "model_record", "model_id": None}),
        "connection_rules": ConnectionRules(credential_kind="model_record", relative_path="/chat/completions",
                                            method="POST", headers={"Accept": "application/json"}),
        "context_configuration": ContextConfiguration(output_reserve_tokens=None, tokenizer_family=None,
                                                      capacity_source="profile", capability_profile_version=None),
        "registered_references": REGISTRY,
    }
    arguments.update(changes)
    return construct_resolved_model_profile(draft, catalog, **arguments)


def saved_row(snapshot):
    row = encode_resolved_model_profile(snapshot, registered_references=REGISTRY)
    row["model_id"] = 7
    return row


def expected_saved(snapshot):
    document = snapshot.model_dump(mode="json")
    document["outlet_id"] = 7
    document["connection"]["credential_ref"]["model_id"] = 7
    return document


def test_shipped_policy_constructs_and_restores_complete_outlet():
    catalog = load_profile_catalog(ROOT)
    snapshot = construct(catalog, policy(catalog, values={"enable_thinking": True, "reasoning_budget_tokens": 0}))
    row = saved_row(snapshot)
    restored = decode_resolved_model_profile(row, registered_references=REGISTRY)
    assert restored.model_dump(mode="json") == expected_saved(snapshot)
    assert restored.identity.request_model_id == "qwen3.5-plus"
    assert restored.parameter_values == {"enable_thinking": True, "reasoning_budget_tokens": 0}
    assert row["enable_thinking"] is True and row["reasoning_budget_tokens"] == 0
    assert row["extra_params"]["parameter_values"] == {}
    assert "api_key" not in row
    assert restored.bindings.role_mapping == VersionedReference(ref="system_only_v1", version=1)
    assert restored.instruction_mapping.supported_roles == ["system", "user", "assistant", "tool"]
    refs = restored.provenance.atomic_refs
    assert refs.model.key == "alibaba/qwen3.5-plus"
    assert refs.provider.key == "alibaba-cn"
    assert refs.provider_model.key == "alibaba-cn/qwen3.5-plus"
    for reference in (refs.model, refs.provider, refs.provider_model):
        assert hashlib.sha256((ROOT / reference.file_path).read_bytes()).hexdigest() == reference.content_sha256
    assert any(item.path == "/reasoning/controls" for item in restored.provenance.overrides)
    assert any(item.target_path == "/capabilities/context/combined_window" for item in restored.provenance.field_sources)
    assert restored.provenance.interpretation_versions.composer.version == 2


def test_custom_selection_survives_source_changes_without_reloading(tmp_path, monkeypatch):
    copied = tmp_path / "profiles"
    shutil.copytree(ROOT, copied)
    catalog = load_profile_catalog(copied)
    draft = policy(catalog, provider=None, model="tenant/Exact-Request-Name", atom="alibaba/qwen3.5-plus")
    snapshot = construct(catalog, draft)
    row = saved_row(snapshot)
    original_reference = snapshot.provenance.atomic_refs.model
    source = copied / original_reference.file_path
    source.write_text('invalid = [', encoding="utf-8")
    assert hashlib.sha256(source.read_bytes()).hexdigest() != original_reference.content_sha256
    def forbidden(*args, **kwargs):
        raise AssertionError("Saved outlet tried loading catalog or source files")
    monkeypatch.setattr("nexent.core.model_service.profiles.resolver.load_profile_catalog", forbidden)
    monkeypatch.setattr("nexent.core.model_service.profiles.resolver.load_source_catalog", forbidden)
    # Source access is forbidden at the filesystem boundary as well as the public loader.
    read_bytes, read_text = Path.read_bytes, Path.read_text
    def guarded_bytes(path, *args, **kwargs):
        if path.is_relative_to(copied):
            return forbidden()
        return read_bytes(path, *args, **kwargs)
    def guarded_text(path, *args, **kwargs):
        if path.is_relative_to(copied):
            return forbidden()
        return read_text(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_bytes", guarded_bytes)
    monkeypatch.setattr(Path, "read_text", guarded_text)
    restored = decode_resolved_model_profile(row, registered_references=REGISTRY)
    assert restored.model_dump(mode="json") == expected_saved(snapshot)
    assert restored.identity.request_model_id == "tenant/Exact-Request-Name"
    assert restored.model_profile_key == "alibaba/qwen3.5-plus"
    assert restored.provenance.atomic_refs.provider is None
    assert restored.provenance.atomic_refs.provider_model is None
    assert restored.parameter_values == {}


def test_invalid_collaborating_inputs_do_not_publish_a_snapshot():
    catalog = load_profile_catalog(ROOT)
    draft = policy(catalog)
    variants = [
        (replace(catalog, revision="updated-catalog"), draft, {}, "PROFILE_CATALOG_REVISION_MISMATCH"),
        (catalog, replace(draft, model_profile_key=None), {}, "PROFILE_SELECTION_INVALID"),
        (catalog, draft, {"registered_references": {}}, "PROFILE_RESOLUTION_INVALID"),
        (catalog, draft, {"protected_paths": ["/model"],
                          "extra_api_parameters": [{"path": "/model", "value": "private-parameter-value"}]},
         "PROFILE_RESOLUTION_INVALID"),
    ]
    for selected_catalog, selected_policy, arguments, expected_category in variants:
        with pytest.raises(OutletResolutionError) as failure:
            construct(selected_catalog, selected_policy, **arguments)
        assert failure.value.category == expected_category
        assert "private-parameter-value" not in str(failure.value)
