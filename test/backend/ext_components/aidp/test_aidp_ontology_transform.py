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


def _reasons(exc):
    return [(issue["field"], issue["reason"]) for issue in exc.errors]


def test_document_shape_errors():
    with pytest.raises(OntologyImportValidationError) as error:
        build_import_request([], "Demo")
    assert _reasons(error.value) == [("$", "json_root_object")]

    with pytest.raises(OntologyImportValidationError) as error:
        build_import_request({"other": {}}, "Demo")
    assert _reasons(error.value) == [("$", "group_missing")]

    with pytest.raises(OntologyImportValidationError) as error:
        build_import_request(
            {"Demo": {"types": "bad", "entities": [], "relations": []}}, "Demo"
        )
    assert ("types", "field_array_required") in _reasons(error.value)


def test_kind_mismatch_and_property_shape():
    with pytest.raises(OntologyImportValidationError) as error:
        build_import_request(
            _document(
                types=[{"api_name": "Category", "kind": "entity"}], relations=[]
            ),
            "Demo",
        )
    assert ("kind", "kind_mismatch") in _reasons(error.value)

    with pytest.raises(OntologyImportValidationError) as error:
        build_import_request(
            _document(
                entities=[{"api_name": "Phone", "properties": ["bad"]}],
                relations=[],
            ),
            "Demo",
        )
    assert _reasons(error.value) == [
        ("properties[0].api_name", "property_api_name_required")
    ]


def test_relation_endpoint_errors():
    cases = [
        (
            {"api_name": "r", "source_api_name": "", "object_api_name": "Category"},
            ("source_api_name", "relation_field_required"),
        ),
        (
            {
                "api_name": "r",
                "source_api_name": "Phone",
                "source_kind": "bad",
                "object_api_name": "Category",
            },
            ("source_kind", "relation_kind_invalid"),
        ),
        (
            {
                "api_name": "r",
                "source_api_name": "Phone",
                "source_kind": "type",
                "object_api_name": "Category",
            },
            ("source_kind", "relation_kind_mismatch"),
        ),
        (
            {
                "api_name": "r",
                "source_api_name": "Missing",
                "source_kind": "entity",
                "object_api_name": "Category",
            },
            ("source_api_name", "relation_endpoint_missing"),
        ),
    ]
    for relation, expected in cases:
        with pytest.raises(OntologyImportValidationError) as error:
            build_import_request(_document(relations=[relation]), "Demo")
        assert expected in _reasons(error.value)


def test_relation_endpoint_ambiguity():
    document = _document(
        types=[{"api_name": "Same"}],
        entities=[{"api_name": "Same"}],
        relations=[
            {
                "api_name": "r",
                "source_api_name": "Same",
                "object_api_name": "Category",
            }
        ],
    )
    with pytest.raises(OntologyImportValidationError) as error:
        build_import_request(document, "Demo")
    assert ("source_kind", "relation_kind_ambiguous") in _reasons(error.value)


def test_async_import_and_export_normalization():
    from ext_components.aidp.services import aidp_ontology_transform as transform

    assert transform.unwrap_payload([]) == {}
    assert transform.is_async_task_payload({"data": {"task_id": "1"}}) is True
    assert transform.is_async_task_payload({"data": {"imported_count": 1}}) is False
    assert transform.async_task_summary({"data": {"taskId": "1", "status": "ok"}}) == {
        "accepted": True,
        "task_id": None,
        "status": "ok",
    }
    assert transform.normalize_import_result(
        {
            "data": {
                "result": {
                    "imported_count": 2,
                    "failed_count": 1,
                    "first_error": {"message": "bad"},
                    "errors": [{"message": "bad"}, {"index": 1, "api_name": "x"}],
                }
            }
        }
    )["imported_count"] == 2
    assert transform.sanitize_export_filename("a/b:c", "fallback") == "a_b_c.json"
    assert transform.normalize_export_result({"data": {"Demo": {}}})["domain_name"] == "Demo"
    assert transform.normalize_export_result({"data": {"task_id": "1"}})["accepted"] is True
    with pytest.raises(ValueError):
        transform.normalize_export_result({"data": {}})


def test_more_shape_and_relation_errors():
    with pytest.raises(OntologyImportValidationError) as error:
        build_import_request(
            _document(entities=[{"api_name": 1}], relations=[]), "Demo"
        )
    assert ("api_name", "api_name_required") in _reasons(error.value)

    with pytest.raises(OntologyImportValidationError) as error:
        build_import_request(_document(relations=["bad"]), "Demo")
    assert ("$", "item_not_object") in _reasons(error.value)

    with pytest.raises(OntologyImportValidationError) as error:
        build_import_request(
            {"Demo": {"types": [], "entities": [], "relations": "bad"}}, "Demo"
        )
    assert ("relations", "field_array_required") in _reasons(error.value)

    body, _ = build_import_request(
        _document(
            entities=[{"api_name": "Phone", "primary_properties": ["p"]}],
            relations=[],
        ),
        "Demo",
    )
    assert body["Demo"]["entities"][0]["primary_properties"] == ["p"]


def test_import_message_and_export_fallback():
    from ext_components.aidp.services import aidp_ontology_transform as transform

    assert transform._extract_error_message({"reason_zh": "原因"}) == "原因"
    assert transform._extract_error_message({}) == "Import failed"
    assert transform.normalize_import_result({})["imported_count"] == 0
    assert transform.normalize_import_errors(
        {"data": {"result": {"errors": ["bad", {"index": 1, "api_name": "x"}]}}}
    )[0]["api_name"] == "x"
    assert transform.normalize_export_result({"Demo": {}})["domain_name"] == "Demo"
    with pytest.raises(ValueError):
        transform.normalize_export_result([])
