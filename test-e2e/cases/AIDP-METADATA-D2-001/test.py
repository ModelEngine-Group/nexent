# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AIDP-METADATA-D2-001: field-definition and chunk-annotation API contracts."""
from __future__ import annotations

import pytest

from aidp_ontology_support import (
    FakeAidpOntology,
    auth_headers,
    build_client,
    configure_environment,
)

pytestmark = [
    pytest.mark.case_id("AIDP-METADATA-D2-001"),
    pytest.mark.stage("D2"),
    pytest.mark.p0,
    pytest.mark.api_it,
]


@pytest.fixture
def api(monkeypatch):
    configure_environment(
        monkeypatch,
        role="ADMIN",
        permissions={"kb-a": "EDIT", "kb-b": "READ_ONLY", "kb-c": "EDIT"},
    )
    fake = FakeAidpOntology()
    fake.fields["1"] = [
        {"id": 101, "fieldName": "doc_type", "fieldType": "string"},
        {"id": 102, "fieldName": "publish_year", "fieldType": "number"},
        {"id": 103, "fieldName": "effective_date", "fieldType": "time"},
    ]
    fake.install(monkeypatch)
    return fake, build_client()


def test_field_definitions_are_typed_and_limited(api):
    fake, client = api
    listed = client.get(
        "/aidp-mgmt/ontology/domains/1/metadata-fields", headers=auth_headers()
    )
    assert listed.status_code == 200
    assert listed.json()["limit"] == 20
    assert [item["field_name"] for item in listed.json()["value"]] == [
        "doc_type",
        "publish_year",
        "effective_date",
    ]

    for index in range(17):
        response = client.post(
            "/aidp-mgmt/ontology/domains/1/metadata-fields",
            headers=auth_headers(),
            json={"field_name": f"f{index}", "field_type": "string"},
        )
        assert response.status_code == 200

    blocked = client.post(
        "/aidp-mgmt/ontology/domains/1/metadata-fields",
        headers=auth_headers(),
        json={"field_name": "overflow", "field_type": "string"},
    )
    assert blocked.status_code == 400
    assert "20" in blocked.json()["message"]

    invalid_type = client.post(
        "/aidp-mgmt/ontology/domains/1/metadata-fields",
        headers=auth_headers(),
        json={"field_name": "bad", "field_type": "list"},
    )
    assert invalid_type.status_code == 422

    too_long = client.post(
        "/aidp-mgmt/ontology/domains/1/metadata-fields",
        headers=auth_headers(),
        json={"field_name": "x" * 65, "field_type": "string"},
    )
    assert too_long.status_code == 400


def test_field_name_uses_63_char_and_64_byte_limit(api):
    _fake, client = api
    ascii_63 = client.post(
        "/aidp-mgmt/ontology/domains/1/metadata-fields",
        headers=auth_headers(),
        json={"field_name": "a" * 63, "field_type": "string"},
    )
    assert ascii_63.status_code == 200

    ascii_64 = client.post(
        "/aidp-mgmt/ontology/domains/1/metadata-fields",
        headers=auth_headers(),
        json={"field_name": "b" * 64, "field_type": "string"},
    )
    assert ascii_64.status_code == 400

    chinese_21 = client.post(
        "/aidp-mgmt/ontology/domains/1/metadata-fields",
        headers=auth_headers(),
        json={"field_name": "中" * 21, "field_type": "string"},
    )
    assert chinese_21.status_code == 200

    chinese_22 = client.post(
        "/aidp-mgmt/ontology/domains/1/metadata-fields",
        headers=auth_headers(),
        json={"field_name": "中" * 22, "field_type": "string"},
    )
    assert chinese_22.status_code == 400
    assert "64" in chinese_22.json()["message"]

    renamed_64 = client.patch(
        "/aidp-mgmt/ontology/domains/1/metadata-fields/doc_type",
        headers=auth_headers(),
        json={"new_field_name": "c" * 64},
    )
    assert renamed_64.status_code == 400


@pytest.mark.parametrize("field_type", ["int", "list", "list<string>", "date"])
def test_field_type_is_limited_to_string_number_time(api, field_type):
    _fake, client = api
    response = client.post(
        "/aidp-mgmt/ontology/domains/1/metadata-fields",
        headers=auth_headers(),
        json={"field_name": "unsupported", "field_type": field_type},
    )
    assert response.status_code == 422


def test_field_rename_and_delete_async_receipts(api, monkeypatch):
    _fake, client = api
    from ext_components.aidp.services import aidp_ontology_service

    monkeypatch.setattr(
        aidp_ontology_service,
        "rename_ontology_metadata_field_impl",
        lambda *a, **k: {"task_id": "rename-task", "status": "pending", "progress": 0},
    )
    renamed = client.patch(
        "/aidp-mgmt/ontology/domains/1/metadata-fields/doc_type",
        headers=auth_headers(),
        json={"new_field_name": "document_type"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["accepted"] is True
    assert renamed.json()["task_id"] == "rename-task"
    assert renamed.json()["field_name"] == "document_type"

    monkeypatch.setattr(
        aidp_ontology_service,
        "delete_ontology_metadata_field_impl",
        lambda *a, **k: {"task_id": "delete-task", "status": "pending", "progress": 0},
    )
    deleted = client.delete(
        "/aidp-mgmt/ontology/domains/1/metadata-fields/doc_type",
        headers=auth_headers(),
    )
    assert deleted.status_code == 200
    assert deleted.json()["accepted"] is True
    assert deleted.json()["task_id"] == "delete-task"


def test_field_rename_only_changes_the_name(api):
    _fake, client = api
    renamed = client.patch(
        "/aidp-mgmt/ontology/domains/1/metadata-fields/doc_type",
        headers=auth_headers(),
        json={"new_field_name": "document_type"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["field_name"] == "document_type"
    assert renamed.json()["field_type"] in (None, "string")

    same = client.patch(
        "/aidp-mgmt/ontology/domains/1/metadata-fields/publish_year",
        headers=auth_headers(),
        json={"new_field_name": "publish_year"},
    )
    assert same.status_code == 400

    duplicate = client.patch(
        "/aidp-mgmt/ontology/domains/1/metadata-fields/publish_year",
        headers=auth_headers(),
        json={"new_field_name": "document_type"},
    )
    assert duplicate.status_code == 400


def test_chunk_annotation_accepts_defined_types_and_reports_results(api):
    fake, client = api
    response = client.patch(
        "/aidp-mgmt/ontology/knowledge-bases/kb-a/chunks/metadata",
        headers=auth_headers(),
        json={
            "domain_id": "1",
            "metadata": {
                "doc_type": "FAQ",
                "publish_year": 2026,
                "effective_date": "2026-01-01",
            },
            "chunk_ids": [1001],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["success_count"] == 1
    assert body["failed_count"] == 0
    assert body["success_list"] == [{"chunk_id": 1001}]
    assert "batch_metadata" in fake.calls

    reread = client.get(
        "/aidp-mgmt/ontology/knowledge-bases/kb-a/chunks/1001", headers=auth_headers()
    )
    assert reread.status_code == 200
    assert reread.json()["metadata"]["doc_type"] == "FAQ"
    assert reread.json()["metadata"]["publish_year"] == 2026


@pytest.mark.parametrize(
    "metadata,expected_fragment",
    [
        ({"unknown": "x"}, "未在当前本体库中定义"),
        ({"publish_year": "2026"}, "需要数字值"),
        ({"effective_date": ""}, "需要时间文本值"),
        ({"doc_type": "x" * 257}, "256 字节"),
        ({"k" * 65: "x"}, "不能超过 64 字节"),
    ],
)
def test_annotation_rejects_invalid_keys_and_values(api, metadata, expected_fragment):
    fake, client = api
    batch_before = fake.calls.count("batch_metadata")
    response = client.patch(
        "/aidp-mgmt/ontology/knowledge-bases/kb-a/chunks/metadata",
        headers=auth_headers(),
        json={"domain_id": "1", "metadata": metadata, "chunk_ids": [1001]},
    )
    assert response.status_code == 400
    errors = response.json()["details"]["errors"]
    assert any(expected_fragment in item["message"] for item in errors)
    assert fake.calls.count("batch_metadata") == batch_before


def test_annotation_rejects_more_than_twenty_keys_and_foreign_chunks(api):
    fake, client = api
    too_many = client.patch(
        "/aidp-mgmt/ontology/knowledge-bases/kb-a/chunks/metadata",
        headers=auth_headers(),
        json={
            "domain_id": "1",
            "metadata": {f"k{index}": "x" for index in range(21)},
            "chunk_ids": [1001],
        },
    )
    assert too_many.status_code == 400

    foreign = client.patch(
        "/aidp-mgmt/ontology/knowledge-bases/kb-a/chunks/metadata",
        headers=auth_headers(),
        json={"domain_id": "1", "metadata": {"doc_type": "FAQ"}, "chunk_ids": [2001]},
    )
    assert foreign.status_code == 400
    assert foreign.json()["details"]["errors"][0]["message"] == "Chunk 不属于该知识库"

    empty = client.patch(
        "/aidp-mgmt/ontology/knowledge-bases/kb-a/chunks/metadata",
        headers=auth_headers(),
        json={"domain_id": "1", "metadata": {"doc_type": "FAQ"}, "chunk_ids": []},
    )
    assert empty.status_code == 422
