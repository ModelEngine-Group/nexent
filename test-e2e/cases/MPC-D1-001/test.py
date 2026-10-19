# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""MPC-D1-001: real source, supplement and composed policy component contract."""

import hashlib
import os
import shutil
import socket
import tomllib
from pathlib import Path

import pytest

from nexent.core.model_service.profiles.composition import (
    ProfileCompositionError,
    compose_provider_model_policy,
)
from nexent.core.model_service.profiles.contracts import VersionedReference
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError
from nexent.core.model_service.profiles.resolver import load_profile_catalog
from nexent.core.model_service.profiles.supplements import SupplementReadError


ROOT = Path(__file__).resolve().parents[3] / "sdk/nexent/core/model_service/profiles"
COMBINATION = "rules/providers/alibaba-cn/qwen3.5-plus.toml"
REFERENCE = VersionedReference(ref="component_boundary_v1", version=1)
TRANSFORM = VersionedReference(ref="identity_v1", version=1)
BINDING_NAMES = ("protocol", "auth", "adapter", "code_converter", "native_converter")
pytestmark = [pytest.mark.case_id("MPC-D1-001"), pytest.mark.stage("D1")]


@pytest.fixture
def no_external_access(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError(
            "Profile composition crossed an external execution boundary"
        )

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(os, "getenv", forbidden)


def hashes(root):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*.toml")
    }


def copied_root(tmp_path):
    root = tmp_path / "profiles"
    shutil.copytree(ROOT, root)
    return root


def change_rule(root, path, transform):
    file = root / path
    old = file.read_bytes()
    new = transform(old.decode("utf-8")).encode("utf-8")
    assert new != old
    file.write_bytes(new)
    manifest = root / "rules/manifest.toml"
    old_hash, new_hash = (
        hashlib.sha256(old).hexdigest(),
        hashlib.sha256(new).hexdigest(),
    )
    blocks = manifest.read_text().split("[[rules]]")
    matches = 0
    for index, block in enumerate(blocks[1:], 1):
        entry = tomllib.loads(block)
        if entry["path"] == path:
            assert entry["content_sha256"] == old_hash
            blocks[index] = block.replace(old_hash, new_hash)
            matches += 1
    assert matches == 1
    manifest.write_text("[[rules]]".join(blocks))


def compose(catalog, *, values=None, registry=None):
    # Implementation availability is the controlled service boundary; no transport
    # implementation or provider execution is claimed by this component Case.
    references = {name: [REFERENCE] for name in BINDING_NAMES}
    references["parameter_transform"] = [TRANSFORM]
    return compose_provider_model_policy(
        catalog,
        provider_key="alibaba-cn",
        request_model_id="qwen3.5-plus",
        model_profile_key=None,
        base_bindings={name: REFERENCE.model_dump() for name in BINDING_NAMES},
        base_instruction=VersionedReference(ref="system_only_v1", version=1),
        registered_references=references if registry is None else registry,
        submitted_values={} if values is None else values,
    )


def test_complete_supplemented_policy_and_source_trace(no_external_access):
    before = hashes(ROOT)
    catalog = load_profile_catalog(ROOT)
    policy = compose(catalog)
    assert (
        len(catalog.models),
        len(catalog.providers),
        len(catalog.provider_models),
    ) == (26, 6, 35)
    assert policy.provider_key == "alibaba-cn"
    assert policy.model_profile_key == "alibaba/qwen3.5-plus"
    assert policy.request_model_id == "qwen3.5-plus"
    assert policy.capabilities["context"]["combined_window"] == 1_000_000
    assert policy.capabilities["tools"]["status"] == "supported"
    assert policy.capabilities["reasoning"]["controls"][0]["values"] == (False, True)
    assert policy.instruction_mapping["mappings"]["application_instruction"] == "system"
    assert policy.parameter_values["enable_thinking"] is True
    assert policy.parameter_bindings["enable_thinking"] == {
        "path": "/enable_thinking",
        "transform_ref": "identity_v1",
        "transform_version": 1,
    }
    assert (
        compose(catalog, values={"enable_thinking": False}).parameter_values[
            "enable_thinking"
        ]
        is False
    )
    hosted = catalog.provider_models["alibaba-cn/qwen3.5-plus"]
    origin = hosted.source.field_origins["/capabilities/context/combined_window"]
    assert origin.mapping.source.source_path == "limit.context"
    assert (
        origin.mapping.source.file_path
        == "providers/alibaba-cn/models/qwen3.5-plus.toml"
    )
    assert hosted.source.source_refs
    assert all(
        ref.catalog_revision == hosted.source.source_refs[0].catalog_revision
        for ref in hosted.source.source_refs
    )
    assert policy.overrides[-1]["path"] == "/reasoning/controls"
    original_controls = policy.overrides[-1]["original_value"]
    assert original_controls[0]["values"] == (True, False)
    assert original_controls[1]["parameter_key"] == "reasoning_budget_tokens"
    assert original_controls[1]["min"] is None
    assert original_controls[1]["max"] == 81920
    assert policy.capabilities["reasoning"]["controls"][1]["min"] is None
    assert "reasoning_budget_tokens" not in policy.parameter_values
    budget = compose(catalog, values={"reasoning_budget_tokens": 50})
    assert budget.parameter_values["reasoning_budget_tokens"] == 50
    assert (
        budget.parameter_bindings["reasoning_budget_tokens"]["path"]
        == "/thinking_budget"
    )
    with pytest.raises(ParameterValidationError, match="PARAMETER_DEPENDENCY"):
        compose(
            catalog, values={"enable_thinking": False, "reasoning_budget_tokens": 50}
        )
    assert policy.overrides[-1]["source"] == COMBINATION
    assert "alibabacloud.com" in policy.overrides[-1]["evidence"]
    with pytest.raises(TypeError):
        policy.parameter_values["enable_thinking"] = False
    assert hashes(ROOT) == before


def test_supplement_revision_changes_without_mutating_prior_snapshots(
    no_external_access, tmp_path
):
    before = hashes(ROOT)
    root = copied_root(tmp_path)
    first = load_profile_catalog(root)
    old_policy = compose(first)
    repeated = load_profile_catalog(root)
    assert repeated.revision == first.revision
    assert compose(repeated).revision == old_policy.revision
    change_rule(
        root,
        COMBINATION,
        lambda text: text.replace("default_value = true", "default_value = false"),
    )
    changed = load_profile_catalog(root)
    new_policy = compose(changed)
    assert changed.revision != first.revision
    assert new_policy.revision != old_policy.revision
    assert new_policy.parameter_values["enable_thinking"] is False
    assert old_policy.parameter_values["enable_thinking"] is True
    key = "alibaba-cn/qwen3.5-plus"
    assert changed.provider_models[key].revision != first.provider_models[key].revision
    assert (
        changed.provider_models[key].source.profile_revision
        == first.provider_models[key].source.profile_revision
    )
    assert (
        changed.models["alibaba/qwen3.5-plus"].revision
        == first.models["alibaba/qwen3.5-plus"].revision
    )
    assert load_profile_catalog(root).revision == changed.revision
    assert hashes(ROOT) == before


def test_invalid_rules_references_conflicts_and_values_are_atomic(
    no_external_access, tmp_path
):
    before = hashes(ROOT)
    root = copied_root(tmp_path / "version")
    catalog = load_profile_catalog(root)
    policy = compose(catalog)
    for invalid in (None, "false", 0):
        with pytest.raises(ParameterValidationError, match="PARAMETER_VALUE_INVALID"):
            compose(catalog, values={"enable_thinking": invalid})
    with pytest.raises(ProfileCompositionError, match="PROFILE_BINDING_UNREGISTERED"):
        compose(catalog, registry={})
    change_rule(
        root,
        COMBINATION,
        lambda text: text.replace("schema_version = 1", "schema_version = 9"),
    )
    with pytest.raises(SupplementReadError, match="SUPPLEMENT_RULE_INVALID"):
        load_profile_catalog(root)
    references_root = copied_root(tmp_path / "references")
    change_rule(
        references_root,
        COMBINATION,
        lambda text: text.replace(
            'transform_ref = "identity_v1"', 'transform_ref = "unregistered_v1"'
        ),
    )
    with pytest.raises(
        ParameterValidationError, match="PARAMETER_TRANSFORM_UNREGISTERED"
    ):
        compose(load_profile_catalog(references_root))
    conflict_root = copied_root(tmp_path / "conflict")
    change_rule(
        conflict_root,
        COMBINATION,
        lambda text: (
            text
            + '\n[[capability_overrides]]\npath = "/reasoning/controls"\nvalue = []\nreason = "Conflict fixture"\nevidence = "Case-controlled declaration"\n'
        ),
    )
    with pytest.raises(ProfileCompositionError, match="PROFILE_CONFLICT"):
        load_profile_catalog(conflict_root)
    condition_root = copied_root(tmp_path / "condition")
    conditional_parameter = '\n[[parameters]]\nkey = "fixture_detail"\nvisible = true\neditable = true\nrequired = false\nallowed_scopes = ["outlet"]\nui_group = "fixture"\nowner = "combination"\n[parameters.schema]\ntype = "string"\n[parameters.source]\nref = "case-controlled"\n[parameters.api_binding]\npath = "/fixture_detail"\ntransform_ref = "identity_v1"\ntransform_version = 1\n[parameters.condition]\nkey = "enable_thinking"\nop = "eq"\nvalue = true\n'
    change_rule(condition_root, COMBINATION, lambda text: text + conditional_parameter)
    conditional_catalog = load_profile_catalog(condition_root)
    assert (
        compose(
            conditional_catalog, values={"fixture_detail": "allowed"}
        ).parameter_values["fixture_detail"]
        == "allowed"
    )
    with pytest.raises(
        ParameterValidationError, match="PARAMETER_DEPENDENCY"
    ) as captured:
        compose(
            conditional_catalog,
            values={"enable_thinking": False, "fixture_detail": "private-value"},
        )
    assert "private-value" not in str(captured.value)
    assert policy.parameter_values["enable_thinking"] is True
    assert load_profile_catalog(ROOT).revision == catalog.revision
    assert hashes(ROOT) == before


def test_experience_layers_follow_source_baseline(no_external_access, tmp_path):
    root = copied_root(tmp_path)
    original = load_profile_catalog(root)
    source_output = original.provider_models["alibaba-cn/qwen3.5-plus"].source.capabilities["context"]["output_limit"]
    layers = [
        ("rules/models/alibaba/qwen3.5-plus.toml", "model", 16000, 0.2),
        ("rules/providers/alibaba-cn/provider.toml", "provider", 12000, 0.4),
        (COMBINATION, "combination", 8000, 0.6),
    ]
    previous = compose(original)
    for path, owner, output, temperature in layers:
        addition = f"""
[[capability_overrides]]
path = "/context/output_limit"
value = {output}
reason = "Case-controlled experience correction"
evidence = "MPC-D1-001 fixture"

[[parameters]]
key = "temperature"
schema = {{ type = "number", minimum = 0, maximum = 2 }}
visible = true
editable = true
required = false
allowed_scopes = ["outlet"]
ui_group = "sampling"
owner = "{owner}"
source = {{ ref = "experience-fixture" }}
default_value = {temperature}
api_binding = {{ path = "/temperature", transform_ref = "identity_v1", transform_version = 1 }}
"""
        change_rule(root, path, lambda text: text + addition)
        current = load_profile_catalog(root)
        policy = compose(current)
        assert policy.capabilities["context"]["output_limit"] == output
        assert policy.parameter_values["temperature"] == temperature
        output_changes = [item for item in policy.overrides if item["path"] == "/context/output_limit"]
        assert output_changes[-1]["source"] == path
        assert policy.revision != previous.revision
        assert current.provider_models["alibaba-cn/qwen3.5-plus"].source.capabilities["context"]["output_limit"] == source_output
        assert compose(current, values={"temperature": 0.9}).parameter_values["temperature"] == 0.9
        previous = policy
    assert compose(original).parameter_values.get("temperature") is None
    assert load_profile_catalog(ROOT).revision == original.revision
