# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

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


def test_top_p_override_has_explicit_support_and_versioned_revision(
    sources, monkeypatch
):
    from nexent.core.model_service.profiles import composition

    override = {
        "path": "/sampling/top_p",
        "value": {"status": "unsupported"},
        "reason": "Service-specific support",
        "evidence": ["fixture"],
    }
    current = catalog(sources, combo={"capability_overrides": [override]})
    assert (
        current.provider_models["provider/exact"].capabilities["sampling"]["top_p"][
            "status"
        ]
        == "unsupported"
    )
    assert (
        current.models["family/model"].capabilities["sampling"]["top_p"]["status"]
        == "unknown"
    )
    assert composition.COMPOSER_REF == "profile_policy_composer_v6"
    monkeypatch.setattr(composition, "COMPOSER_REF", "profile_policy_composer_v1")
    previous = catalog(sources, combo={"capability_overrides": [override]})
    assert current.revision != previous.revision
    assert (
        current.models["family/model"].revision
        != previous.models["family/model"].revision
    )


def compose(catalog, **changes):
    options = {
        "provider_key": "provider",
        "request_model_id": "exact",
        "model_profile_key": None,
        "base_bindings": BINDINGS,
        "base_instruction": INSTRUCTION,
        "registered_references": {
            key: [REFERENCE] for key in (*BINDINGS, "parameter_transform")
        },
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


def test_provider_experience_takes_priority_over_hosted_source_fact(sources):
    hosted = replace(
        sources.provider_models["provider/exact"],
        capabilities={"tools": {"status": "supported"}},
    )
    changed = replace(sources, provider_models={"provider/exact": hosted})
    value = compose(
        catalog(changed, provider={"capability_overrides": [override("unsupported")]})
    )
    assert value.capabilities["tools"]["status"] == "unsupported"
    assert value.overrides[-1]["original_value"] == "supported"


def test_unknown_exact_id_does_not_select_similar_combination(sources):
    value = compose(catalog(sources), request_model_id="exact-v2")
    assert value.model_profile_key is None
    assert value.capabilities["tools"]["status"] == "unknown"
    assert value.capabilities["context"]["combined_window"] is None


def test_explicit_model_selection_conflict_is_rejected(sources):
    with pytest.raises(ProfileCompositionError, match="PROFILE_CONFLICT"):
        compose(catalog(sources), model_profile_key="different/model")


def test_provider_instruction_overrides_model_instruction(sources):
    value = compose(catalog(
        sources,
        model={"instruction_mapping": {"ref": "developer_then_system_v1", "version": 1}},
        provider={"instruction_mapping": INSTRUCTION.model_dump()},
    ))
    assert value.instruction_mapping["strategy_id"] == "system_only"
    combination = compose(catalog(sources,
        model={"instruction_mapping": INSTRUCTION.model_dump()},
        provider={"instruction_mapping": {"ref": "unavailable_v1", "version": 1}},
        combo={"instruction_mapping": INSTRUCTION.model_dump()},
    ))
    assert combination.instruction_mapping["strategy_id"] == "system_only"


def test_provider_binding_overrides_model_but_still_requires_registration(sources):
    different = {"ref": "different_v1", "version": 1}
    definitions = catalog(sources,
        model={"bindings": {"adapter": different}},
        provider={"bindings": {"adapter": REFERENCE.model_dump()}},
    )
    assert compose(definitions).bindings["adapter"]["ref"] == "test_v1"
    combination = catalog(sources,
        model={"bindings": {"adapter": REFERENCE.model_dump()}},
        provider={"bindings": {"adapter": different}},
        combo={"bindings": {"adapter": REFERENCE.model_dump()}},
    )
    assert compose(combination).bindings["adapter"]["ref"] == "test_v1"
    with pytest.raises(ProfileCompositionError, match="PROFILE_BINDING_UNREGISTERED"):
        compose(catalog(sources, model={"bindings": {"adapter": REFERENCE.model_dump()}},
                        provider={"bindings": {"adapter": different}}))


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
        "api_binding": {
            "path": "/effort",
            "transform_ref": "test_v1",
            "transform_version": 1,
        },
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


def test_oversized_atomic_definition_is_rejected_in_utf8_bytes(sources):
    with pytest.raises(ProfileCompositionError, match="PROFILE_SIZE_LIMIT"):
        catalog(sources, model={"aliases": ["中" * 350000]})


def test_declared_thinking_control_requires_parameter_binding(sources):
    model = replace(
        sources.models["family/model"],
        capabilities={
            "reasoning": {
                "status": "supported",
                "controls": [{"mode": "toggle", "values": [False, True]}],
            },
        },
    )
    changed = replace(sources, models={"family/model": model})
    with pytest.raises(
        ProfileCompositionError, match="REASONING_PARAMETER_BINDING_MISSING"
    ):
        compose(catalog(changed))


def test_thinking_control_values_must_fit_declared_parameter_schema(sources):
    model = replace(
        sources.models["family/model"],
        capabilities={
            "reasoning": {
                "status": "supported",
                "controls": [{"mode": "toggle", "values": [False, True]}],
            },
        },
    )
    changed = replace(sources, models={"family/model": model})
    parameter = {
        "key": "enable_thinking",
        "schema": {"enum": [False]},
        "visible": True,
        "editable": True,
        "required": False,
        "allowed_scopes": ["outlet"],
        "ui_group": "reasoning",
        "owner": "combination",
        "source": {"ref": "fixture"},
        "api_binding": {
            "path": "/enable_thinking",
            "transform_ref": "test_v1",
            "transform_version": 1,
        },
    }
    with pytest.raises(
        ProfileCompositionError, match="REASONING_PARAMETER_SCHEMA_CONFLICT"
    ):
        compose(catalog(changed, combo={"parameters": [parameter]}))
    parameter["schema"] = {"type": "boolean"}
    value = compose(catalog(changed, combo={"parameters": [parameter]}))
    assert value.parameter_bindings["enable_thinking"]["path"] == "/enable_thinking"


def test_composition_propagates_adapter_owned_path_protection(sources):
    parameter = {
        "key": "effort",
        "schema": {"type": "string"},
        "visible": True,
        "editable": True,
        "required": False,
        "allowed_scopes": ["outlet"],
        "ui_group": "reasoning",
        "owner": "provider",
        "source": {"ref": "fixture"},
        "api_binding": {
            "path": "/options/effort",
            "transform_ref": "test_v1",
            "transform_version": 1,
        },
    }
    from nexent.core.model_service.profiles.parameter_schema import (
        ParameterValidationError,
    )

    with pytest.raises(ParameterValidationError, match="RESERVED_API_PATH"):
        compose(
            catalog(sources, provider={"parameters": [parameter]}),
            protected_api_paths=["/options"],
        )


def test_invalid_unicode_model_id_is_rejected_without_raw_values(sources):
    with pytest.raises(
        ProfileCompositionError, match="PROFILE_JSON_INVALID"
    ) as captured:
        compose(catalog(sources), request_model_id="private-\ud800")
    assert "private" not in str(captured.value)


def test_resolved_policy_size_includes_submitted_parameter_values(sources):
    parameter = {
        "key": "custom",
        "schema": {"type": "string"},
        "visible": True,
        "editable": True,
        "required": False,
        "allowed_scopes": ["outlet"],
        "ui_group": "advanced",
        "owner": "provider",
        "source": {"ref": "fixture"},
        "api_binding": {
            "path": "/custom",
            "transform_ref": "test_v1",
            "transform_version": 1,
        },
    }
    definitions = catalog(sources, provider={"parameters": [parameter]})
    with pytest.raises(ProfileCompositionError, match="PROFILE_SIZE_LIMIT"):
        compose(definitions, submitted_values={"custom": "中" * 350000})
    value = compose(definitions, submitted_values={"custom": "中" * 1000})
    assert len(value.parameter_values["custom"]) == 1000


def test_frozen_supplement_instruction_reference_is_materialized(sources):
    from types import MappingProxyType

    value = compose(
        catalog(
            sources,
            model={"instruction_mapping": MappingProxyType(INSTRUCTION.model_dump())},
        )
    )
    assert value.instruction_mapping["strategy_id"] == "system_only"


def test_top_p_is_explicit_without_claiming_unknown_capability(sources):
    from nexent.core.model_service.profiles.protocol_parameters import openai_chat_parameter_rules

    value = compose(catalog(sources), protocol_parameter_rules=openai_chat_parameter_rules(),
        registered_references={**{key: [REFERENCE] for key in BINDINGS},
                               "parameter_transform": [VersionedReference(ref="identity_v1", version=1)]})
    top_p = next(rule for rule in value.parameter_rules.declarations if rule["key"] == "top_p")
    assert top_p["visible"] is True
    assert top_p["allowed_scopes"] == ["outlet", "conversation"]
    assert top_p["schema"]["minimum"] == 0
    assert top_p["schema"]["maximum"] == 1
    assert "top_p" not in value.parameter_values
    assert value.capabilities["sampling"]["top_p"]["status"] == "unknown"


@pytest.mark.parametrize("value", [0, 1, 0.85])
def test_top_p_accepts_explicit_values(sources, value):
    from nexent.core.model_service.profiles.protocol_parameters import openai_chat_parameter_rules

    policy = compose(catalog(sources), protocol_parameter_rules=openai_chat_parameter_rules(),
        registered_references={**{key: [REFERENCE] for key in BINDINGS},
                               "parameter_transform": [VersionedReference(ref="identity_v1", version=1)]},
                     submitted_values={"top_p": value})
    assert policy.parameter_values["top_p"] == value


@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_top_p_rejects_out_of_range_values(sources, value):
    from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError
    from nexent.core.model_service.profiles.protocol_parameters import openai_chat_parameter_rules

    with pytest.raises(ParameterValidationError):
        compose(catalog(sources), protocol_parameter_rules=openai_chat_parameter_rules(),
        registered_references={**{key: [REFERENCE] for key in BINDINGS},
                               "parameter_transform": [VersionedReference(ref="identity_v1", version=1)]},
                submitted_values={"top_p": value})


def test_explicitly_unsupported_top_p_keeps_configuration(sources):
    from nexent.core.model_service.profiles.protocol_parameters import openai_chat_parameter_rules

    current = catalog(sources, combo={"capability_overrides": [{
        "path": "/sampling/top_p", "value": {"status": "unsupported"},
        "reason": "Service does not accept top_p", "evidence": "fixture",
    }]})
    value = compose(current, protocol_parameter_rules=openai_chat_parameter_rules(),
        registered_references={**{key: [REFERENCE] for key in BINDINGS},
                               "parameter_transform": [VersionedReference(ref="identity_v1", version=1)]})
    assert any(rule["key"] == "top_p" for rule in value.parameter_rules.declarations)
    assert value.capabilities["sampling"]["top_p"]["status"] == "unsupported"


@pytest.mark.parametrize("provider", [None, "volcengine-coding-plan"])
@pytest.mark.parametrize("submitted,expected", [({}, 0.95), ({"top_p": 0.8}, 0.8)])
def test_kimi_sampling_preference_is_composed_without_fixing_user_values(provider, submitted, expected):
    from nexent.core.model_service.profiles.resolver import load_profile_catalog
    from nexent.core.model_service.registry import model_service_references
    from nexent.core.model_service.profiles.protocol_parameters import openai_chat_parameter_rules

    refs = model_service_references()
    policy = compose_provider_model_policy(
        load_profile_catalog(), provider_key=provider, request_model_id="kimi-k3",
        model_profile_key="moonshotai/kimi-k3",
        base_bindings={key: values[0].model_dump() for key, values in refs.items() if key != "parameter_transform"},
        base_instruction=VersionedReference(ref="system_only_v1", version=1),
        registered_references=refs, submitted_values=submitted,
        protocol_parameter_rules=openai_chat_parameter_rules(),
    )
    assert policy.parameter_values["top_p"] == expected
