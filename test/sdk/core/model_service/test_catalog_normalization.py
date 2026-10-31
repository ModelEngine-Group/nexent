# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Isolated materialization, normalization and revision boundary rules."""

import pytest
from nexent.core.model_service.profiles._models_dev.mapping import SOURCE_MAPPING
from nexent.core.model_service.profiles._models_dev.reader import (
    SourceDocument,
    SourceReadError,
    _freeze,
)
from nexent.core.model_service.profiles.resolver import (
    _controls,
    _entry,
    _revision,
    _tree,
)



def test_canonical_tree_preserves_arrays_empty_objects_and_explicit_null():
    tree = _tree(
        {
            "/reference_metadata/items/0/name": "first",
            "/reference_metadata/items/1/name": "second",
            "/reference_metadata/empty": {},
            "/modalities/output": (),
            "/reasoning/control_candidates/0/values/0": None,
        }
    )
    assert tree["reference_metadata"]["items"] == [
        {"name": "first"},
        {"name": "second"},
    ]
    assert tree["reference_metadata"]["empty"] == {}
    assert tree["modalities"]["output"] == ()
    assert tree["reasoning"]["control_candidates"][0]["values"] == [None]


def test_declared_control_domains_preserve_sentinels_and_unknown_bounds():
    assert _controls({}) is None
    assert _controls({"control_candidates": []}) == []
    assert _controls(
        {
            "control_candidates": [
                {"type": "toggle"},
                {"type": "effort", "values": ["none", "null", "default"]},
                {"type": "budget_tokens", "min": -1, "max": 0},
            ]
        }
    ) == [
        {"mode": "toggle", "values": [True, False]},
        {"mode": "effort", "values": ["none", None, "default"]},
        {"mode": "budget_tokens", "min": None, "max": 0, "special_values": [-1]},
    ]
    assert _controls({"control_candidates": [{"type": "budget_tokens", "min": 0}]}) == [
        {"mode": "budget_tokens", "min": 0, "max": None, "special_values": []}
    ]


def test_revision_is_order_independent_and_length_delimited():
    assert _revision({"parser": "v1", "mapping": "v1"}) == _revision(
        {"mapping": "v1", "parser": "v1"}
    )
    assert _revision({"ab": "c"}) != _revision({"a": "bc"})
    assert _revision({"parser": "v1"}) != _revision({"parser": "v2"})


def test_normalized_source_snapshot_is_deeply_immutable_and_not_an_outlet():
    source = SourceDocument(
        "provider_model",
        "vendor/model",
        "providers/vendor/models/model.toml",
        "a" * 64,
        _freeze(
            {
                "reasoning": True,
                "reasoning_options": [
                    {"type": "toggle"},
                    {"type": "budget_tokens", "min": -1, "max": 10},
                ],
            }
        ),
    )
    provider = SourceDocument(
        "provider",
        "vendor",
        "providers/vendor/provider.toml",
        "b" * 64,
        _freeze({"name": "Vendor"}),
    )
    entry = _entry(
        source,
        source,
        SOURCE_MAPPING,
        {"vendor": provider},
        "catalog-v1",
        {"parser": "v1"},
    )
    assert entry.capabilities["reasoning"]["controls"][1]["special_values"] == (-1,)
    assert entry.capabilities["reasoning"]["controls"][1]["min"] is None
    assert (
        entry.field_origins[
            "/capabilities/reasoning/controls/1/special_values/0"
        ].mapping.source.source_path
        == "reasoning_options[1].min"
    )
    assert (
        entry.field_origins[
            "/capabilities/reasoning/controls/0/values/0"
        ].mapping.source.source_path
        == "reasoning_options[0].type"
    )
    with pytest.raises(TypeError):
        entry.capabilities["reasoning"]["controls"][0]["values"][0] = False
    assert [ref.key for ref in entry.source_refs] == ["vendor/model", "vendor"]
    assert not hasattr(entry, "outlet_id")


@pytest.mark.parametrize(
    "data,path",
    [
        ({"limit": {"context": 10, "output": 20}}, "limit"),
        (
            {
                "reasoning": True,
                "reasoning_options": [{"type": "effort", "values": []}],
            },
            "reasoning_options",
        ),
    ],
)
def test_invalid_normalized_domains_fail_with_sanitized_diagnostics(data, path):
    source = SourceDocument(
        "model" if path == "limit" else "provider_model",
        "lab/model",
        "models/lab/model.toml",
        "a" * 64,
        _freeze(data),
    )
    with pytest.raises(SourceReadError) as error:
        _entry(source, source, SOURCE_MAPPING, {}, "catalog-v1", {})
    assert error.value.category == "SOURCE_NORMALIZATION_INVALID"
    assert error.value.source_path == path


def test_local_provider_reference_and_documentation_are_not_upstream_attribution():
    from nexent.core.model_service.profiles.resolver import load_source_catalog

    provider = load_source_catalog().providers["tokenpony"]
    assert provider.source_refs[0].catalog_revision == "nexent_tokenpony_provider_v1"
    assert provider.reference_metadata["source_origin"] == {
        "kind": "nexent", "revision": "nexent_tokenpony_provider_v1", "url": "https://docs.tokenpony.cn/",
    }
    assert provider.connection_suggestions["base_url"] == "https://api.tokenpony.cn/v1"
