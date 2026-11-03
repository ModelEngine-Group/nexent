# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Pinned inheritance rules and source ownership, independent of semantic mapping."""

import pytest
from nexent.core.model_service.profiles._models_dev.inheritance import (
    resolve_source_model,
)
from nexent.core.model_service.profiles._models_dev.reader import (
    SourceDocument,
    SourceReadError,
    _freeze,
)


def source(kind, key, data):
    path = f"models/{key}.toml" if kind == "model" else f"providers/{key}.toml"
    return SourceDocument(kind, key, path, "a" * 64, _freeze(data))


def test_inheritance_merges_objects_replaces_arrays_and_preserves_field_ownership():
    base = source(
        "model",
        "lab/model",
        {
            "name": "Base",
            "reasoning": True,
            "tool_call": True,
            "limit": {"context": 100, "input": 90, "output": 20},
            "modalities": {"input": ["text", "image"], "output": ["text"]},
        },
    )
    outlet = source(
        "provider_model",
        "vendor/model",
        {
            "base_model": base.key,
            "name": "Hosted",
            "reasoning": False,
            "limit": {"output": 10},
            "modalities": {"input": ["text"]},
        },
    )
    effective = resolve_source_model(outlet, (base, outlet))
    assert effective.data["name"] == "Hosted"
    assert effective.data["reasoning"] is False
    assert dict(effective.data["limit"]) == {"context": 100, "input": 90, "output": 10}
    assert effective.data["modalities"]["input"] == ("text",)
    assert "base_model" not in effective.data
    assert effective.dependencies == (base, outlet)
    assert effective.document.key == "vendor/model"
    assert effective.field_origins["limit.context"].file_path == base.file_path
    assert effective.field_origins["limit.output"].file_path == outlet.file_path
    assert (
        effective.field_origins["modalities.input[0]"].source_path
        == "modalities.input[0]"
    )
    assert "modalities.input[1]" not in effective.field_origins
    assert base.data["limit"]["output"] == 20
    assert base.data["modalities"]["input"] == ("text", "image")
    with pytest.raises(TypeError):
        effective.data["limit"]["output"] = 1


def test_provider_inheritance_excludes_reference_only_fields():
    base = source(
        "model",
        "lab/model",
        {
            "name": "Base",
            "id": "base-id",
            "license": "MIT",
            "links": ["docs"],
            "weights": ["weights"],
            "benchmarks": [{"name": "score", "score": 1}],
        },
    )
    outlet = source("provider_model", "vendor/model", {"base_model": base.key})
    result = resolve_source_model(outlet, (base, outlet))
    assert dict(result.data) == {"name": "Base"}
    assert set(result.field_origins) == {"name"}
    assert base.data["license"] == "MIT"
    atomic = resolve_source_model(base, (base, outlet))
    assert atomic.data["license"] == "MIT"


def test_omit_deletes_nested_paths_and_prunes_empty_parents():
    base = source(
        "model",
        "lab/model",
        {
            "name": "Base",
            "nested": {"only": {"field": 1}},
            "limit": {"context": 100, "output": 10},
        },
    )
    outlet = source(
        "provider_model",
        "vendor/model",
        {
            "base_model": base.key,
            "base_model_omit": ["nested.only.field", "limit.output", "missing.path"],
        },
    )
    result = resolve_source_model(outlet, (base, outlet))
    assert "nested" not in result.data
    assert dict(result.data["limit"]) == {"context": 100}
    assert "limit.output" not in result.field_origins
    assert result.omitted_paths == ("nested.only.field", "limit.output", "missing.path")
    assert "base_model_omit" not in result.data
    assert base.data["nested"]["only"]["field"] == 1


def test_omit_does_not_traverse_arrays_or_scalars():
    base = source("model", "lab/model", {"array": ["item"], "scalar": 1})
    outlet = source(
        "provider_model",
        "vendor/model",
        {
            "base_model": base.key,
            "base_model_omit": ["array.0", "scalar.child"],
        },
    )
    assert dict(resolve_source_model(outlet, (base, outlet)).data) == {
        "array": ("item",),
        "scalar": 1,
    }


def test_empty_array_replacement_preserves_explicit_empty_declaration():
    base = source("model", "lab/model", {"values": ["low", "high"]})
    outlet = source(
        "provider_model", "vendor/model", {"base_model": base.key, "values": []}
    )
    result = resolve_source_model(outlet, (base, outlet))
    assert result.data["values"] == ()
    assert set(result.field_origins) == {"values"}
    assert result.field_origins["values"].file_path == outlet.file_path


def test_without_base_never_infers_identity_or_capabilities_from_name():
    base = source("model", "lab/model", {"name": "Same", "reasoning": True})
    outlet = source("provider_model", "vendor/model", {"name": "Same"})
    result = resolve_source_model(outlet, (base, outlet))
    assert dict(result.data) == {"name": "Same"}
    assert result.dependencies == (outlet,)


@pytest.mark.parametrize(
    "data,category",
    [
        ({"base_model": "missing"}, "SOURCE_BASE_MODEL_MISSING"),
        ({"base_model": False}, "SOURCE_BASE_REFERENCE_INVALID"),
        ({"base_model": " "}, "SOURCE_BASE_REFERENCE_INVALID"),
        ({"base_model": "lab/model", "base_model_omit": "name"}, "SOURCE_OMIT_INVALID"),
        (
            {"base_model": "lab/model", "base_model_omit": [False]},
            "SOURCE_OMIT_INVALID",
        ),
        (
            {"base_model": "lab/model", "base_model_omit": ["limit..output"]},
            "SOURCE_OMIT_INVALID",
        ),
        ({"base_model_omit": ["name"]}, "SOURCE_OMIT_WITHOUT_BASE"),
    ],
)
def test_invalid_references_and_omissions_fail_explicitly(data, category):
    base = source("model", "lab/model", {"name": "Base"})
    outlet = source("provider_model", "vendor/model", data)
    with pytest.raises(SourceReadError) as caught:
        resolve_source_model(outlet, (base, outlet))
    assert caught.value.category == category
    assert caught.value.file_path == outlet.file_path
    assert caught.value.rule_id == "source_inheritance_v1"


def test_duplicate_model_identity_is_rejected():
    base = source("model", "lab/model", {"name": "Base"})
    outlet = source("provider_model", "vendor/model", {"base_model": base.key})
    with pytest.raises(SourceReadError, match="SOURCE_DUPLICATE"):
        resolve_source_model(outlet, (base, base, outlet))


def test_atomic_model_cannot_declare_nested_or_cyclic_base_in_this_source_schema():
    base = source("model", "lab/model", {"base_model": "lab/model"})
    outlet = source("provider_model", "vendor/model", {"base_model": base.key})
    for document in (base, outlet):
        with pytest.raises(SourceReadError, match="SOURCE_BASE_REFERENCE_INVALID"):
            resolve_source_model(document, (base, outlet))


def test_provider_metadata_is_not_a_model_document():
    provider = source("provider", "vendor", {"name": "Vendor"})
    with pytest.raises(SourceReadError, match="SOURCE_MODEL_KIND_INVALID"):
        resolve_source_model(provider, (provider,))


def test_nonempty_overlay_replaces_empty_container_origin_with_leaf_ownership():
    base = source("model", "lab/model", {"limit": {}})
    outlet = source(
        "provider_model",
        "vendor/model",
        {"base_model": base.key, "limit": {"output": 10}},
    )
    result = resolve_source_model(outlet, (base, outlet))
    assert dict(result.data["limit"]) == {"output": 10}
    assert set(result.field_origins) == {"limit.output"}
    assert result.field_origins["limit.output"].file_path == outlet.file_path
    assert dict(base.data["limit"]) == {}


def test_empty_object_overlay_preserves_inherited_leaf_values_and_origins():
    base = source("model", "lab/model", {"limit": {"context": 100}})
    outlet = source(
        "provider_model", "vendor/model", {"base_model": base.key, "limit": {}}
    )
    result = resolve_source_model(outlet, (base, outlet))
    assert dict(result.data["limit"]) == {"context": 100}
    assert set(result.field_origins) == {"limit.context"}
    assert result.field_origins["limit.context"].file_path == base.file_path


def test_omit_prunes_only_empty_parents_and_keeps_sibling_origins():
    base = source("model", "lab/model", {"nested": {"remove": {"leaf": 1}, "keep": 2}})
    outlet = source(
        "provider_model",
        "vendor/model",
        {"base_model": base.key, "base_model_omit": ["nested.remove.leaf"]},
    )
    result = resolve_source_model(outlet, (base, outlet))
    assert dict(result.data["nested"]) == {"keep": 2}
    assert set(result.field_origins) == {"nested.keep"}
    assert result.field_origins["nested.keep"].file_path == base.file_path
