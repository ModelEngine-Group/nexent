# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Tests for ontology import document validation and projection."""

import pytest

from ext_components.aidp.services.aidp_ontology_transform import (
    OntologyImportValidationError,
    build_import_request,
)


def _document(**overrides):
    document = {
        "Demo": {
            "types": [{"api_name": "Category"}],
            "entities": [{"api_name": "Phone", "properties": [{"api_name": "price"}]}],
            "relations": [
                {
                    "api_name": "Phone_is_Category",
                    "source_api_name": "Phone",
                    "object_api_name": "Category",
                }
            ],
        }
    }
    document["Demo"].update(overrides)
    return document


def _reasons(exc: OntologyImportValidationError):
    return [(issue["field"], issue["reason"]) for issue in exc.errors]


def test_builds_request_and_defaults_property_values():
    body, counts = build_import_request(_document(), "Demo")

    assert counts == {
        "type_count": 1,
        "entity_count": 1,
        "relation_count": 1,
    }
    properties = body["Demo"]["entities"][0]["properties"]
    assert properties == [{"api_name": "price", "data_type": "string", "value": ""}]
    assert body["Demo"]["relations"][0]["source_kind"] == "entity"
    assert body["Demo"]["relations"][0]["object_kind"] == "type"


def test_missing_api_name_maps_to_reason():
    with pytest.raises(OntologyImportValidationError) as error:
        build_import_request(_document(entities=[{"display_name": "Phone"}], relations=[]), "Demo")

    assert _reasons(error.value) == [("api_name", "api_name_required")]


def test_non_object_entity_maps_to_reason():
    with pytest.raises(OntologyImportValidationError) as error:
        build_import_request(_document(entities=["bad"], relations=[]), "Demo")

    assert _reasons(error.value) == [("$", "item_not_object")]


def test_properties_must_be_array():
    with pytest.raises(OntologyImportValidationError) as error:
        build_import_request(
            _document(
                entities=[{"api_name": "Phone", "properties": "bad"}],
                relations=[],
            ),
            "Demo",
        )

    assert _reasons(error.value) == [("properties", "properties_not_array")]


def test_property_requires_api_name():
    with pytest.raises(OntologyImportValidationError) as error:
        build_import_request(
            _document(
                entities=[{"api_name": "Phone", "properties": [{}]}],
                relations=[],
            ),
            "Demo",
        )

    assert _reasons(error.value) == [
        ("properties[0].api_name", "property_api_name_required")
    ]


def test_primary_properties_must_be_array():
    with pytest.raises(OntologyImportValidationError) as error:
        build_import_request(
            _document(
                entities=[{"api_name": "Phone", "primary_properties": "price"}],
                relations=[],
            ),
            "Demo",
        )

    assert _reasons(error.value) == [
        ("primary_properties", "primary_properties_not_array")
    ]


def test_relation_endpoint_must_exist():
    with pytest.raises(OntologyImportValidationError) as error:
        build_import_request(
            _document(
                relations=[
                    {
                        "api_name": "Phone_is_Missing",
                        "source_api_name": "Phone",
                        "object_api_name": "Missing",
                    }
                ]
            ),
            "Demo",
        )

    assert _reasons(error.value) == [
        ("object_api_name", "relation_endpoint_kind_unknown")
    ]


def test_duplicate_api_name_is_rejected():
    with pytest.raises(OntologyImportValidationError) as error:
        build_import_request(
            _document(
                entities=[
                    {"api_name": "Phone"},
                    {"api_name": "Phone"},
                ]
            ),
            "Demo",
        )

    assert _reasons(error.value) == [("api_name", "duplicate_api_name")]
