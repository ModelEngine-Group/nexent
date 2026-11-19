# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AIDP-ONTOLOGY-D2-001: ontology, entity, binding, chunk and JSON API contracts."""
from __future__ import annotations

import pytest

from aidp_ontology_support import (
    FakeAidpOntology,
    auth_headers,
    build_client,
    configure_environment,
)

pytestmark = [
    pytest.mark.case_id("AIDP-ONTOLOGY-D2-001"),
    pytest.mark.stage("D2"),
    pytest.mark.p0,
    pytest.mark.api_it,
]


@pytest.fixture
def api(monkeypatch):
    configure_environment(
        monkeypatch,
        role="ADMIN",
        permissions={"kb-a": "EDIT", "kb-b": "READ_ONLY", "kb-c": "EDIT", "kb-d": "EDIT"},
    )
    fake = FakeAidpOntology()
    fake.fields["1"] = [
        {"id": 101, "fieldName": "doc_type", "fieldType": "string"},
        {"id": 102, "fieldName": "publish_year", "fieldType": "number"},
    ]
    fake.install(monkeypatch)
    return fake, build_client()


def test_domain_list_and_crud_contract(api):
    fake, client = api
    response = client.get("/aidp-mgmt/ontology/domains", headers=auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert [item["domain_id"] for item in body["value"]] == ["1", "2"]
    assert [item["bound_kb_count"] for item in body["value"]] == [2, 1]
    assert body["total_reliable"] is True

    created = client.post(
        "/aidp-mgmt/ontology/domains",
        headers=auth_headers(),
        json={"name": "新本体", "description": "desc"},
    )
    assert created.status_code == 200
    assert created.json()["name"] == "新本体"
    assert "create_domain" in fake.calls

    updated = client.patch(
        "/aidp-mgmt/ontology/domains/1",
        headers=auth_headers(),
        json={"description": "changed"},
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "changed"

    deleted = client.delete("/aidp-mgmt/ontology/domains/2", headers=auth_headers())
    assert deleted.status_code == 200
    assert deleted.json()["success"] is True


def test_domain_list_uses_search_and_zero_binding_count(api):
    fake, client = api
    searched = client.get(
        "/aidp-mgmt/ontology/domains",
        headers=auth_headers(),
        params={"search": "电商"},
    )
    assert searched.status_code == 200
    assert fake.last_search == "电商"
    assert searched.json()["total_count"] == 1
    assert [item["name"] for item in searched.json()["value"]] == ["电商本体"]

    created = client.post(
        "/aidp-mgmt/ontology/domains",
        headers=auth_headers(),
        json={"name": "空本体", "description": "no bindings"},
    )
    assert created.status_code == 200
    listed = client.get("/aidp-mgmt/ontology/domains", headers=auth_headers())
    empty = next(
        item for item in listed.json()["value"] if item["name"] == "空本体"
    )
    assert empty["bound_kb_count"] == 0
    assert empty["metadata_count"] is None
    assert empty["entity_count"] is None


def test_domain_id_path_is_numeric(api):
    _fake, client = api
    response = client.get(
        "/aidp-mgmt/ontology/domains/not-a-number", headers=auth_headers()
    )
    assert response.status_code == 422


def test_domain_name_byte_and_empty_validation(api):
    fake, client = api
    too_long = "本" * 22  # 66 UTF-8 bytes
    response = client.post(
        "/aidp-mgmt/ontology/domains",
        headers=auth_headers(),
        json={"name": too_long, "description": ""},
    )
    assert response.status_code == 400
    assert "create_domain" not in fake.calls

    empty = client.post(
        "/aidp-mgmt/ontology/domains",
        headers=auth_headers(),
        json={"name": "   ", "description": ""},
    )
    assert empty.status_code == 400

    description = client.post(
        "/aidp-mgmt/ontology/domains",
        headers=auth_headers(),
        json={"name": "ok", "description": "描" * 171},  # 513 bytes
    )
    assert description.status_code == 400


def test_entity_list_injects_shared_binding_count(api):
    _fake, client = api
    response = client.get(
        "/aidp-mgmt/ontology/domains/1/entities",
        headers=auth_headers(),
        params={"page": 1, "page_size": 20},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["bound_kb_count"] == 2
    assert {item["bound_kb_count"] for item in body["value"]} == {2}
    assert [item["kind"] for item in body["value"]] == ["type", "entity"]


def test_entity_create_and_patch_field_boundaries(api):
    fake, client = api
    bad_type = client.post(
        "/aidp-mgmt/ontology/domains/1/entities",
        headers=auth_headers(),
        json={"kind": "type", "api_name": "BadType", "type_id": "101"},
    )
    assert bad_type.status_code == 422

    unknown_parent = client.post(
        "/aidp-mgmt/ontology/domains/1/entities",
        headers=auth_headers(),
        json={"kind": "entity", "api_name": "Orphan", "type_id": "missing"},
    )
    assert unknown_parent.status_code == 400
    assert "create_entity" not in fake.calls

    created = client.post(
        "/aidp-mgmt/ontology/domains/1/entities",
        headers=auth_headers(),
        json={
            "kind": "entity",
            "api_name": "Tablet",
            "display_name": "平板",
            "type_id": "101",
            "properties": [{"api_name": "price", "display_name": "价格", "value": "2999"}],
            "primary_properties": ["price"],
        },
    )
    assert created.status_code == 200
    assert created.json()["api_name"] == "Tablet"

    immutable = client.patch(
        "/aidp-mgmt/ontology/domains/1/entities/201",
        headers=auth_headers(),
        json={"type_id": "102"},
    )
    assert immutable.status_code == 422

    updated = client.patch(
        "/aidp-mgmt/ontology/domains/1/entities/201",
        headers=auth_headers(),
        json={"display_name": "手机", "properties": []},
    )
    assert updated.status_code == 200
    assert updated.json()["display_name"] == "手机"


def test_binding_one_kb_one_domain_and_unbind(api):
    fake, client = api
    conflict = client.post(
        "/aidp-mgmt/ontology/domains/2/bindings",
        headers=auth_headers(),
        json={"kds_id": "kb-a"},
    )
    assert conflict.status_code == 409
    assert "create_binding" not in fake.calls

    unchanged = client.post(
        "/aidp-mgmt/ontology/domains/1/bindings",
        headers=auth_headers(),
        json={"kds_id": "kb-a"},
    )
    assert unchanged.status_code == 200
    assert unchanged.json()["unchanged"] is True

    created = client.post(
        "/aidp-mgmt/ontology/domains/1/bindings",
        headers=auth_headers(),
        json={"kds_id": "kb-d"},
    )
    assert created.status_code == 200
    assert "create_binding" in fake.calls

    listed = client.get(
        "/aidp-mgmt/ontology/domains/1/bindings", headers=auth_headers()
    )
    assert listed.status_code == 200
    assert {item["kds_id"] for item in listed.json()["value"]} == {"kb-a", "kb-b", "kb-d"}

    removed = client.delete(
        "/aidp-mgmt/ontology/domains/1/bindings/kb-a", headers=auth_headers()
    )
    assert removed.status_code == 200
    assert removed.json()["success"] is True


def test_metadata_field_limit_rename_and_delete(api):
    fake, client = api
    for index in range(18):
        created = client.post(
            "/aidp-mgmt/ontology/domains/1/metadata-fields",
            headers=auth_headers(),
            json={"field_name": f"f{index}", "field_type": "string"},
        )
        assert created.status_code == 200
    assert len(fake.fields["1"]) == 20

    over_limit = client.post(
        "/aidp-mgmt/ontology/domains/1/metadata-fields",
        headers=auth_headers(),
        json={"field_name": "overflow", "field_type": "string"},
    )
    assert over_limit.status_code == 400
    assert "create_field" not in fake.calls[-1:]

    duplicate = client.post(
        "/aidp-mgmt/ontology/domains/1/metadata-fields",
        headers=auth_headers(),
        json={"field_name": "doc_type", "field_type": "string"},
    )
    assert duplicate.status_code == 400

    renamed = client.patch(
        "/aidp-mgmt/ontology/domains/1/metadata-fields/doc_type",
        headers=auth_headers(),
        json={"new_field_name": "document_type"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["field_name"] == "document_type"

    missing = client.patch(
        "/aidp-mgmt/ontology/domains/1/metadata-fields/absent",
        headers=auth_headers(),
        json={"new_field_name": "x"},
    )
    assert missing.status_code == 400

    deleted = client.delete(
        "/aidp-mgmt/ontology/domains/1/metadata-fields/document_type",
        headers=auth_headers(),
    )
    assert deleted.status_code == 200


def test_chunk_read_and_batch_metadata_contract(api):
    fake, client = api
    listed = client.get(
        "/aidp-mgmt/ontology/knowledge-bases/kb-a/chunks",
        headers=auth_headers(),
        params={"file_uuid": "file-a", "page": 1, "page_size": 20},
    )
    assert listed.status_code == 200
    assert listed.json()["value"][0]["chunk_id"] == 1001
    assert listed.json()["total_count"] == 1

    detail = client.get(
        "/aidp-mgmt/ontology/knowledge-bases/kb-a/chunks/1001", headers=auth_headers()
    )
    assert detail.status_code == 200
    assert detail.json()["metadata"] == {"doc_type": "FAQ"}

    annotated = client.patch(
        "/aidp-mgmt/ontology/knowledge-bases/kb-a/chunks/metadata",
        headers=auth_headers(),
        json={
            "domain_id": "1",
            "metadata": {"doc_type": "Guide", "publish_year": 2024},
            "chunk_ids": [1001],
        },
    )
    assert annotated.status_code == 200
    result = annotated.json()
    assert result["success_count"] == 1
    assert result["failed_count"] == 0

    undefined = client.patch(
        "/aidp-mgmt/ontology/knowledge-bases/kb-a/chunks/metadata",
        headers=auth_headers(),
        json={"domain_id": "1", "metadata": {"unknown": "x"}, "chunk_ids": [1001]},
    )
    assert undefined.status_code == 400
    assert any(item["message"].startswith("字段未在") for item in undefined.json()["details"]["errors"])

    wrong_type = client.patch(
        "/aidp-mgmt/ontology/knowledge-bases/kb-a/chunks/metadata",
        headers=auth_headers(),
        json={"domain_id": "1", "metadata": {"publish_year": "2024"}, "chunk_ids": [1001]},
    )
    assert wrong_type.status_code == 400

    oversized = client.patch(
        "/aidp-mgmt/ontology/knowledge-bases/kb-a/chunks/metadata",
        headers=auth_headers(),
        json={"domain_id": "1", "metadata": {"doc_type": "x" * 257}, "chunk_ids": [1001]},
    )
    assert oversized.status_code == 400

    batch_before = fake.calls.count("batch_metadata")
    unbound = client.patch(
        "/aidp-mgmt/ontology/knowledge-bases/kb-a/chunks/metadata",
        headers=auth_headers(),
        json={"domain_id": "2", "metadata": {"channel": "web"}, "chunk_ids": [1001]},
    )
    assert unbound.status_code == 400
    assert fake.calls.count("batch_metadata") == batch_before

    foreign_chunk = client.patch(
        "/aidp-mgmt/ontology/knowledge-bases/kb-a/chunks/metadata",
        headers=auth_headers(),
        json={"domain_id": "1", "metadata": {"doc_type": "FAQ"}, "chunk_ids": [9999]},
    )
    assert foreign_chunk.status_code == 400

    too_many = client.patch(
        "/aidp-mgmt/ontology/knowledge-bases/kb-a/chunks/metadata",
        headers=auth_headers(),
        json={
            "domain_id": "1",
            "metadata": {"doc_type": "FAQ"},
            "chunk_ids": list(range(1, 102)),
        },
    )
    assert too_many.status_code == 422


def test_export_import_sync_and_async_contract(api, monkeypatch):
    fake, client = api
    exported = client.post(
        "/aidp-mgmt/ontology/domains/1/export",
        headers=auth_headers(),
        json={"include_properties": True, "include_relations": True, "kind": None},
    )
    assert exported.status_code == 200
    body = exported.json()
    assert body["accepted"] is False
    assert body["filename"] == "电商本体.json"
    assert "电商本体" in body["data"]

    imported = client.post(
        "/aidp-mgmt/ontology/domains/2/import",
        headers=auth_headers(),
        json={
            "file_name": "export.json",
            "document": {
                "types": [{"api_name": "Category", "display_name": "类目"}],
                "entities": [{"api_name": "Smartphone", "display_name": "手机"}],
                "relations": [
                    {
                        "api_name": "belongs_to",
                        "source_api_name": "Smartphone",
                        "object_api_name": "Category",
                    }
                ],
            },
        },
    )
    assert imported.status_code == 200
    assert imported.json()["imported_count"] == 2
    assert imported.json()["relation_imported"] == 1
    assert imported.json()["counts"]["type_count"] == 1
    assert "import" in fake.calls

    invalid = client.post(
        "/aidp-mgmt/ontology/domains/2/import",
        headers=auth_headers(),
        json={
            "file_name": "bad.json",
            "document": {
                "relations": [
                    {
                        "api_name": "r",
                        "source_api_name": "Missing",
                        "object_api_name": "Category",
                    }
                ]
            },
        },
    )
    assert invalid.status_code == 400
    assert invalid.json()["details"]["errors"][0]["field"] == "source_api_name"

    async_export = {
        "code": 200,
        "message": "OK",
        "data": {"task_id": "task-1", "status": "pending", "progress": 0},
    }
    from ext_components.aidp.services import aidp_ontology_service

    monkeypatch.setattr(
        aidp_ontology_service, "export_ontology_impl", lambda *a, **k: dict(async_export)
    )
    accepted = client.post(
        "/aidp-mgmt/ontology/domains/1/export",
        headers=auth_headers(),
        json={"include_properties": True, "include_relations": True, "kind": None},
    )
    assert accepted.status_code == 200
    assert accepted.json()["accepted"] is True
    assert accepted.json()["task_id"] == "task-1"
    assert "filename" not in accepted.json()

    async_import = {
        "code": 200,
        "message": "OK",
        "data": {"task_id": "task-2", "status": "pending", "progress": 0},
    }
    monkeypatch.setattr(
        aidp_ontology_service, "import_ontology_impl", lambda *a, **k: dict(async_import)
    )
    big_document = {
        "types": [{"api_name": f"T{index}"} for index in range(201)],
    }
    accepted_import = client.post(
        "/aidp-mgmt/ontology/domains/1/import",
        headers=auth_headers(),
        json={"file_name": "big.json", "document": big_document},
    )
    assert accepted_import.status_code == 200
    assert accepted_import.json()["accepted"] is True
    assert accepted_import.json()["task_id"] == "task-2"
