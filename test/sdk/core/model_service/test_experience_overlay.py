# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Experience precedence is explicit and separate from upstream source composition."""

import pytest

from nexent.core.model_service.profiles.composition import build_profile_catalog, compose_provider_model_policy
from nexent.core.model_service.profiles.contracts import VersionedReference
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError
from nexent.core.model_service.profiles.resolver import SourceCatalog, SourceCatalogEntry
from nexent.core.model_service.profiles.supplements import SupplementCatalog, SupplementEntry


REF = VersionedReference(ref="fixture_v1", version=1)
BINDINGS = {name: REF.model_dump() for name in ("protocol", "auth", "adapter", "code_converter", "native_converter")}


def definitions(*, model=None, provider=None, combination=None):
    def source(kind, key, facts):
        return SourceCatalogEntry(kind, key, {}, facts, {}, {}, {}, (), kind + key)

    sources = SourceCatalog(
        "source",
        "upstream",
        "parser",
        "mapping",
        1,
        {
            "family/model": source(
                "model", "family/model", {"context": {"combined_window": 200000, "output_limit": 16000}}
            )
        },
        {"provider": source("provider", "provider", {})},
        {"provider/exact": source("provider_model", "provider/exact", {"context": {"output_limit": 12000}})},
    )
    entries = {}
    for kind, key, rule in (
        ("model", "family/model", model),
        ("provider", "provider", provider),
        ("provider_model", "provider/exact", combination),
    ):
        entries[kind] = SupplementEntry(
            "rules/" + kind + ".toml",
            kind,
            {
                "target_kind": kind,
                "target_key": key,
                **(rule or {}),
                **({"model_profile_key": "family/model"} if kind == "provider_model" else {}),
            },
        )
    return build_profile_catalog(sources, SupplementCatalog("supplements", "schema", entries, sources.revision))


def resolve(catalog, values=None):
    return compose_provider_model_policy(
        catalog,
        provider_key="provider",
        request_model_id="exact",
        model_profile_key=None,
        base_bindings=BINDINGS,
        base_instruction=VersionedReference(ref="system_only_v1", version=1),
        registered_references={name: [REF] for name in (*BINDINGS, "parameter_transform")},
        submitted_values=values or {},
    )


def parameter(value, **changes):
    return {
        "key": "temperature",
        "schema": {"type": "number", "minimum": 0, "maximum": 2},
        "visible": True,
        "editable": True,
        "required": False,
        "allowed_scopes": ["outlet"],
        "ui_group": "sampling",
        "owner": "model",
        "source": {"ref": "fixture"},
        "default_value": value,
        "api_binding": {"path": "/temperature", "transform_ref": REF.ref, "transform_version": 1},
        **changes,
    }


@pytest.mark.parametrize("layer,expected", [("model", 0.2), ("provider", 0.4), ("combination", 0.6)])
def test_defaults_are_layered_before_permitted_user_values(layer, expected):
    rules = {"model": {"parameters": [parameter(0.2)]}}
    if layer != "model":
        rules["provider"] = {"parameters": [parameter(0.4, owner="provider")]}
    if layer == "combination":
        rules["combination"] = {"parameters": [parameter(0.6, owner="combination")]}
    catalog = definitions(**rules)
    before = resolve(catalog)
    assert before.parameter_values["temperature"] == expected
    assert resolve(catalog, {"temperature": 0.9}).parameter_values["temperature"] == 0.9
    assert before.parameter_values["temperature"] == expected
    assert before.parameter_rules.declarations[0]["source"]["ref"] == "fixture"


def test_model_experience_is_applied_after_exact_upstream_facts():
    rule = {
        "capability_overrides": [
            {
                "path": "/context/output_limit",
                "value": 8000,
                "reason": "Reviewed service behavior",
                "evidence": "controlled fixture",
            }
        ]
    }
    policy = resolve(definitions(model=rule))
    assert policy.capabilities["context"]["output_limit"] == 8000
    assert policy.overrides[0]["original_value"] == 12000
    assert policy.overrides[0]["source"] == "rules/model.toml"
    assert policy.capabilities["context"]["combined_window"] == 200000


def test_effective_fixed_value_and_range_still_reject_user_changes():
    catalog = definitions(
        model={"parameters": [parameter(0.2)]},
        provider={"parameters": [parameter(0.4)]},
        combination={"parameters": [parameter(0.6, fixed_value=0.6, editable=False)]},
    )
    assert resolve(catalog).parameter_values["temperature"] == 0.6
    with pytest.raises(ParameterValidationError, match="FIXED_PARAMETER"):
        resolve(catalog, {"temperature": 0.9})
    with pytest.raises(ParameterValidationError, match="PARAMETER_VALUE_INVALID"):
        resolve(definitions(model={"parameters": [parameter(0.2)]}), {"temperature": 3})
