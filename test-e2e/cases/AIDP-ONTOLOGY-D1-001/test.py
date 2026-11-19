# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AIDP-ONTOLOGY-D1-001: export-to-import conversion and pre-submit validation."""
from __future__ import annotations

import pytest

from aidp_ontology_support import ensure_backend_imports

ensure_backend_imports()

pytestmark = [
    pytest.mark.case_id("AIDP-ONTOLOGY-D1-001"),
    pytest.mark.stage("D1"),
    pytest.mark.p0,
    pytest.mark.be_ut,
]

from ext_components.aidp.services.aidp_ontology_transform import (  # noqa: E402
    OntologyImportValidationError,
    async_task_summary,
    build_import_request,
    is_async_task_payload,
    normalize_export_result,
    normalize_import_errors,
    normalize_import_result,
    sanitize_export_filename,
)

EXPORT_DOCUMENT = {
    "电商本体": {
        "display_name": "电商本体",
        "description": "desc",
        "types": [
            {
                "api_name": "Category",
                "display_name": "类目",
                "description": "",
                "properties": [{"api_name": "code", "display_name": "编码"}],
                "primary_properties": ["code"],
                "source_info": [],
                "entity_id": 101,
                "created_at": "2025-01-01",
            },
            {"api_name": "Brand", "display_name": "品牌"},
        ],
        "entities": [
            {
                "api_name": "Smartphone",
                "display_name": "智能手机",
                "properties": [
                    {"api_name": "price", "display_name": "价格", "value": "3999"}
                ],
                "primary_properties": ["price"],
                "_search_text": "internal",
                "entity_id": 201,
            }
        ],
        "relations": [
            {
                "api_name": "belongs_to",
                "display_name": "属于",
                "source_api_name": "Smartphone",
                "source_kind": "entity",
                "object_api_name": "Category",
                "object_kind": "type",
                "source_ids": [1],
                "relation_id": 9,
            }
        ],
    }
}


def test_ontology_domain_ids_are_normalized_to_integers():
    from contracts.errors.exceptions import AppException
    from ext_components.aidp.services.aidp_ontology_service import _domain_id_value

    assert _domain_id_value("1") == 1
    assert _domain_id_value(2) == 2
    try:
        _domain_id_value("not-a-number")
    except AppException:
        pass
    else:
        raise AssertionError("non-numeric ontology domain ID must be rejected")


def test_export_document_converts_to_flat_uppercase_request():
    body, counts = build_import_request(EXPORT_DOCUMENT, 7)

    assert body["DOMAIN_ID"] == 7
    assert counts == {"type_count": 2, "entity_count": 1, "relation_count": 1}
    assert [item["api_name"] for item in body["ENTITIES"]] == [
        "Category",
        "Brand",
        "Smartphone",
    ]
    assert [item["kind"] for item in body["ENTITIES"]] == ["type", "type", "entity"]
    assert "domain_id" not in body
    assert "ontology" not in body
    assert "entity_id" not in body["ENTITIES"][0]
    assert "created_at" not in body["ENTITIES"][0]
    assert "_search_text" not in body["ENTITIES"][2]
    relation = body["RELATIONS"][0]
    assert relation["source_kind"] == "entity"
    assert relation["object_kind"] == "type"
    assert "relation_id" not in relation


def test_dynamic_domain_key_and_inner_group_are_accepted():
    inner = EXPORT_DOCUMENT["电商本体"]
    body, counts = build_import_request(inner, 3)
    assert counts["type_count"] == 2
    assert len(body["ENTITIES"]) == 3

    multi = {"a": {"types": [{"api_name": "A"}]}, "b": {"types": [{"api_name": "B"}]}}
    body, counts = build_import_request(multi, 3)
    assert counts["type_count"] == 2
    assert {item["api_name"] for item in body["ENTITIES"]} == {"A", "B"}


def test_relation_kind_is_derived_from_entity_group():
    document = {
        "types": [{"api_name": "Category"}],
        "entities": [{"api_name": "Smartphone"}],
        "relations": [
            {
                "api_name": "belongs_to",
                "source_api_name": "Smartphone",
                "object_api_name": "Category",
            }
        ],
    }
    body, _counts = build_import_request(document, 1)
    assert body["RELATIONS"][0]["source_kind"] == "entity"
    assert body["RELATIONS"][0]["object_kind"] == "type"


def test_ambiguous_endpoint_requires_explicit_kind():
    document = {
        "types": [{"api_name": "Node"}],
        "entities": [{"api_name": "Node"}],
        "relations": [
            {
                "api_name": "links",
                "source_api_name": "Node",
                "object_api_name": "Node",
            }
        ],
    }
    try:
        build_import_request(document, 1)
    except OntologyImportValidationError as error:
        assert error.errors[0]["field"] == "source_kind"
        assert "同时以 type 和 entity 出现" in error.errors[0]["message"]
    else:
        raise AssertionError("ambiguous endpoint must be rejected")


def test_unresolved_relation_endpoint_is_rejected_without_submit():
    document = {
        "types": [{"api_name": "Category"}],
        "relations": [
            {
                "api_name": "belongs_to",
                "source_api_name": "Missing",
                "object_api_name": "Category",
            }
        ],
    }
    try:
        build_import_request(document, 1)
    except OntologyImportValidationError as error:
        assert error.errors[0]["api_name"] == "belongs_to"
        assert "不在本次导入的实体中" in error.errors[0]["message"]
    else:
        raise AssertionError("unresolved endpoint must be rejected")


def test_duplicate_and_kind_mismatch_are_rejected():
    duplicate = {"types": [{"api_name": "A"}, {"api_name": "A"}]}
    try:
        build_import_request(duplicate, 1)
    except OntologyImportValidationError as error:
        assert "(api_name, kind) 重复" in error.errors[0]["message"]
    else:
        raise AssertionError("duplicate entity must be rejected")

    mismatch = {"types": [{"api_name": "A", "kind": "entity"}]}
    try:
        build_import_request(mismatch, 1)
    except OntologyImportValidationError as error:
        assert "kind 与分组不一致" in error.errors[0]["message"]
    else:
        raise AssertionError("kind mismatch must be rejected")


def test_async_and_result_normalization():
    assert is_async_task_payload({"data": {"task_id": "t-1", "status": "pending", "progress": 0}})
    assert not is_async_task_payload(
        {"data": {"imported_count": 1, "skipped_count": 0, "failed_count": 0}}
    )
    summary = async_task_summary({"data": {"task_id": "t-1", "status": "pending"}})
    assert summary == {"accepted": True, "task_id": "t-1", "status": "pending"}

    payload = {
        "code": 4001,
        "data": {
            "imported_count": 2,
            "skipped_count": 1,
            "failed_count": 1,
            "relation_imported": 1,
            "relation_failed": 1,
            "first_error": {
                "index": 3,
                "type": "entity",
                "api_name": "Bad",
                "error_code": 4002,
                "message_zh": "模拟失败",
            },
            "errors": [
                {
                    "index": 4,
                    "type": "relation",
                    "api_name": "r",
                    "message": "关系失败",
                }
            ],
        },
    }
    result = normalize_import_result(payload)
    assert result["imported_count"] == 2
    assert result["failed_count"] == 1
    assert [item["message"] for item in result["errors"]] == ["模拟失败", "关系失败"]
    assert "error_code" not in result["errors"][0]
    assert len(normalize_import_errors(payload)) == 2


def test_export_result_and_filename_safety():
    sync = normalize_export_result(
        {"code": 200, "message": "OK", "data": {"电商本体": {"types": [], "entities": [], "relations": []}}}
    )
    assert sync["accepted"] is False
    assert sync["domain_name"] == "电商本体"

    async_result = normalize_export_result({"data": {"task_id": "t-2", "progress": 0}})
    assert async_result == {"accepted": True, "task_id": "t-2", "status": None}

    assert sanitize_export_filename("电商/本体:1") == "电商_本体_1.json"
    assert sanitize_export_filename("../../etc/passwd") == "etc_passwd.json"

    try:
        normalize_export_result({"code": 200, "data": {}})
    except ValueError:
        pass
    else:
        raise AssertionError("missing domain document must raise")
