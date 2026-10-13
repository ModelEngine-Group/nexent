"""Exact profile selection preserves priority, conflicts and immutable drafts."""

from dataclasses import replace

import pytest
from nexent.core.model_service.profiles.composition import (
    ProfileCompositionError,
    build_profile_catalog,
    compose_provider_model_policy,
)
from nexent.core.model_service.profiles.contracts import VersionedReference
from nexent.core.model_service.profiles.resolver import (
    SourceCatalog,
    SourceCatalogEntry,
)
from nexent.core.model_service.profiles.supplements import (
    SupplementCatalog,
    SupplementEntry,
)

REFERENCE = VersionedReference(ref="test_v1", version=1)
INSTRUCTION = VersionedReference(ref="system_only_v1", version=1)
BINDINGS = {
    key: REFERENCE.model_dump()
    for key in ("protocol", "auth", "adapter", "code_converter", "native_converter")
}


def source(kind, key, capabilities):
    return SourceCatalogEntry(kind, key, {}, capabilities, {}, {}, {}, (), kind + key)


@pytest.fixture
def sources():
    return SourceCatalog(
        "source-v1",
        "upstream",
        "parser",
        "mapping",
        1,
        {
            "family/model": source(
                "model", "family/model", {"tools": {"status": "supported"}}
            )
        },
        {"provider": source("provider", "provider", {})},
        {"provider/exact": source("provider_model", "provider/exact", {})},
    )


def catalog(sources, *, model=None, provider=None, combo=None):
    declarations = {
        "model": ("family/model", model or {}),
        "provider": ("provider", provider or {}),
        "provider_model": (
            "provider/exact",
            {"model_profile_key": "family/model", **(combo or {})},
        ),
    }
    entries = {
        kind: SupplementEntry(
            "rules/" + kind + ".toml",
            kind,
            {
                "target_kind": kind,
                "target_key": key,
                **declaration,
            },
        )
        for kind, (key, declaration) in declarations.items()
    }
    return build_profile_catalog(
        sources, SupplementCatalog("rules-v1", "schema-v1", entries, sources.revision)
    )


def compose(catalog, **changes):
    options = {
        "provider_key": "provider",
        "request_model_id": "exact",
        "model_profile_key": None,
        "base_bindings": BINDINGS,
        "base_instruction": INSTRUCTION,
        "registered_references": {key: [REFERENCE] for key in BINDINGS},
        "submitted_values": {},
    }
    options.update(changes)
    return compose_provider_model_policy(catalog, **options)


def override(value):
    return {
        "path": "/tools/status",
        "value": value,
        "reason": "Service constraint",
        "evidence": "fixture",
    }


def test_exact_combination_override_takes_priority_over_provider(sources):
    value = compose(
        catalog(
            sources,
            provider={"capability_overrides": [override("unsupported")]},
            combo={"capability_overrides": [override("supported")]},
        )
    )
    assert value.capabilities["tools"]["status"] == "supported"
    assert value.overrides[-1]["original_value"] == "unsupported"
    assert value.model_profile_key == "family/model"
    with pytest.raises(TypeError):
        value.capabilities["tools"]["status"] = "unknown"


def test_hosted_source_fact_takes_priority_over_provider_rule(sources):
    hosted = replace(
        sources.provider_models["provider/exact"],
        capabilities={"tools": {"status": "supported"}},
    )
    changed = replace(sources, provider_models={"provider/exact": hosted})
    value = compose(
        catalog(changed, provider={"capability_overrides": [override("unsupported")]})
    )
    assert value.capabilities["tools"]["status"] == "supported"


def test_unknown_exact_id_does_not_select_similar_combination(sources):
    value = compose(catalog(sources), request_model_id="exact-v2")
    assert value.model_profile_key is None
    assert value.capabilities["tools"]["status"] == "unknown"
    assert value.capabilities["context"]["combined_window"] is None


def test_explicit_model_selection_conflict_is_rejected(sources):
    with pytest.raises(ProfileCompositionError, match="PROFILE_CONFLICT"):
        compose(catalog(sources), model_profile_key="different/model")


@pytest.mark.parametrize("field", ["bindings", "instruction_mapping"])
def test_atomic_reference_conflict_needs_explicit_combination(sources, field):
    different = {"ref": "different_v1", "version": 1}
    left = {
        field: {"adapter": REFERENCE.model_dump()}
        if field == "bindings"
        else INSTRUCTION.model_dump()
    }
    right = {field: {"adapter": different} if field == "bindings" else different}
    with pytest.raises(ProfileCompositionError, match="PROFILE_CONFLICT"):
        compose(catalog(sources, model=left, provider=right))
    value = compose(catalog(sources, model=left, provider=right, combo=left))
    assert value.bindings["adapter"]["ref"] == "test_v1"
    assert value.instruction_mapping["strategy_id"] == "system_only"


def test_unavailable_binding_does_not_publish_draft(sources):
    with pytest.raises(ProfileCompositionError, match="PROFILE_BINDING_UNREGISTERED"):
        compose(catalog(sources), registered_references={})


def test_supplements_cannot_be_paired_with_another_source_snapshot(sources):
    supplements = SupplementCatalog("rules", "schema", {}, "obsolete")
    with pytest.raises(
        ProfileCompositionError, match="PROFILE_SOURCE_REVISION_MISMATCH"
    ):
        build_profile_catalog(sources, supplements)


def test_conflicting_capability_overrides_are_rejected(sources):
    with pytest.raises(ProfileCompositionError, match="PROFILE_CONFLICT"):
        catalog(
            sources,
            combo={
                "capability_overrides": [override("supported"), override("unsupported")]
            },
        )


@pytest.mark.parametrize("value", ["", " ", "x" * 101, None, True])
def test_request_model_id_is_not_coerced(sources, value):
    with pytest.raises(ProfileCompositionError, match="REQUEST_MODEL_ID_INVALID"):
        compose(catalog(sources), request_model_id=value)


def test_nullable_default_is_materialized_once_and_detached(sources):
    rule = {
        "key": "effort",
        "schema": {"enum": [None, "low"]},
        "visible": True,
        "editable": True,
        "required": False,
        "allowed_scopes": ["outlet"],
        "ui_group": "reasoning",
        "owner": "model",
        "source": {"ref": "fixture"},
        "default_value": None,
    }
    definitions = catalog(sources, model={"parameters": [rule]})
    value = compose(definitions)
    assert dict(value.parameter_values) == {"effort": None}
    rule["default_value"] = "low"
    assert definitions.models["family/model"].parameters[0]["default_value"] is None
    assert value.parameter_values["effort"] is None
    declarations = value.parameter_rules.declarations
    declarations[0]["schema"]["enum"].append("high")
    assert value.parameter_rules.declarations[0]["schema"]["enum"] == [None, "low"]
