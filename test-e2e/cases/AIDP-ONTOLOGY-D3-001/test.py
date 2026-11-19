# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AIDP-ONTOLOGY-D3-001: real backend-to-AIDP-mock ontology runtime."""
from __future__ import annotations

import json
import urllib.request

import pytest

from aidp_ontology_support import (
    MockAidp,
    auth_headers,
    build_client,
    configure_environment,
)

pytestmark = [
    pytest.mark.case_id("AIDP-ONTOLOGY-D3-001"),
    pytest.mark.stage("D3"),
    pytest.mark.p0,
    pytest.mark.api_it,
]

KB_PERMISSIONS = {
    "aidp-kb-faq": "EDIT",
    "aidp-kb-product": "EDIT",
    "aidp-kb-api": "EDIT",
    "aidp-kb-04": "EDIT",
}


def _control(base_url: str, path: str) -> None:
    request = urllib.request.Request(f"{base_url}{path}", method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 200


@pytest.fixture(scope="module")
def mock(tmp_path_factory):
    with MockAidp(tmp_path_factory.mktemp("aidp-ontology-d3")) as server:
        yield server


@pytest.fixture(autouse=True)
def reset_mock(mock):
    _control(mock.base_url, "/_reset")
    _control(mock.base_url, "/_mock/ontology-import-fail?api_names=")
    _control(mock.base_url, "/_mock/ontology-metadata-fail?chunk_ids=")
    yield


@pytest.fixture
def client(monkeypatch, mock):
    configure_environment(
        monkeypatch,
        role="ADMIN",
        permissions=KB_PERMISSIONS,
        kb_names={key: f"KB {key}" for key in KB_PERMISSIONS},
        server_url=mock.base_url,
        api_key="mock-aidp-key",
    )
    return build_client()


def test_seed_domains_and_bindings_are_consistent(client):
    domains = client.get("/aidp-mgmt/ontology/domains", headers=auth_headers())
    assert domains.status_code == 200
    body = domains.json()
    assert body["total_count"] == 2
    assert {item["name"] for item in body["value"]} == {"电商本体", "客服本体"}
    counts = {item["domain_id"]: item["bound_kb_count"] for item in body["value"]}
    assert counts == {"1": 2, "2": 1}

    bindings = client.get(
        "/aidp-mgmt/ontology/domains/1/bindings", headers=auth_headers()
    )
    assert bindings.status_code == 200
    assert {item["kds_id"] for item in bindings.json()["value"]} == {
        "aidp-kb-faq",
        "aidp-kb-product",
    }


def test_domain_list_search_total_and_optional_fields(client):
    first_page = client.get(
        "/aidp-mgmt/ontology/domains",
        headers=auth_headers(),
        params={"page": 1, "page_size": 1},
    )
    assert first_page.status_code == 200
    body = first_page.json()
    assert len(body["value"]) == 1
    assert body["total_count"] == 2
    assert body["total_reliable"] is True

    searched = client.get(
        "/aidp-mgmt/ontology/domains",
        headers=auth_headers(),
        params={"search": "客服"},
    )
    assert searched.status_code == 200
    assert searched.json()["total_count"] == 1
    assert [item["name"] for item in searched.json()["value"]] == ["客服本体"]

    # Search is confirmed for names only; a description-only match must not hit.
    description_only = client.get(
        "/aidp-mgmt/ontology/domains",
        headers=auth_headers(),
        params={"search": "商品"},
    )
    assert description_only.status_code == 200
    assert description_only.json()["total_count"] == 0

    all_domains = client.get(
        "/aidp-mgmt/ontology/domains", headers=auth_headers()
    ).json()["value"]
    ecommerce = next(item for item in all_domains if item["name"] == "电商本体")
    assert ecommerce["metadata_count"] == 3
    assert ecommerce["entity_count"] == 4
    assert ecommerce["created_by"] == "李东升"
    assert ecommerce["create_time"] == "2026-01-23"
    assert ecommerce["update_time"] == "2026-01-24"
    assert ecommerce["bound_kb_count"] == 2


def test_domain_entity_and_binding_round_trip(client):
    created = client.post(
        "/aidp-mgmt/ontology/domains",
        headers=auth_headers(),
        json={"name": "D3 本体", "description": "runtime"},
    )
    assert created.status_code == 200
    domain_id = created.json()["domain_id"]
    assert domain_id == "3"

    type_response = client.post(
        f"/aidp-mgmt/ontology/domains/{domain_id}/entities",
        headers=auth_headers(),
        json={"kind": "type", "api_name": "Device", "display_name": "设备"},
    )
    assert type_response.status_code == 200
    type_id = type_response.json()["entity_id"]

    entity_response = client.post(
        f"/aidp-mgmt/ontology/domains/{domain_id}/entities",
        headers=auth_headers(),
        json={
            "kind": "entity",
            "api_name": "Router",
            "display_name": "路由器",
            "type_id": type_id,
            "properties": [{"api_name": "price", "display_name": "价格", "value": "199"}],
            "primary_properties": ["price"],
        },
    )
    assert entity_response.status_code == 200

    entities = client.get(
        f"/aidp-mgmt/ontology/domains/{domain_id}/entities",
        headers=auth_headers(),
        params={"keyword": "Router"},
    )
    assert entities.status_code == 200
    assert entities.json()["value"][0]["bound_kb_count"] == 0

    bound = client.post(
        f"/aidp-mgmt/ontology/domains/{domain_id}/bindings",
        headers=auth_headers(),
        json={"kb_id": "aidp-kb-04"},
    )
    assert bound.status_code == 200
    binding_id = bound.json()["binding_id"]
    assert binding_id

    refreshed = client.get(
        f"/aidp-mgmt/ontology/domains/{domain_id}/entities",
        headers=auth_headers(),
    )
    assert refreshed.json()["bound_kb_count"] == 1
    assert refreshed.json()["value"][0]["bound_kb_count"] == 1

    conflict = client.post(
        "/aidp-mgmt/ontology/domains/1/bindings",
        headers=auth_headers(),
        json={"kb_id": "aidp-kb-04"},
    )
    assert conflict.status_code == 409

    unbound = client.delete(
        f"/aidp-mgmt/ontology/domains/{domain_id}/bindings/{binding_id}",
        headers=auth_headers(),
        params={"kds_id": "aidp-kb-04"},
    )
    assert unbound.status_code == 200
    assert client.get(
        f"/aidp-mgmt/ontology/domains/{domain_id}/entities", headers=auth_headers()
    ).json()["bound_kb_count"] == 0


def test_export_import_round_trip_and_repeat_skip(client):
    exported = client.post(
        "/aidp-mgmt/ontology/domains/1/export",
        headers=auth_headers(),
        json={"include_properties": True, "include_relations": True, "kind": None},
    )
    assert exported.status_code == 200
    document = exported.json()["data"]

    first = client.post(
        "/aidp-mgmt/ontology/domains/2/import",
        headers=auth_headers(),
        json={"file_name": "export.json", "document": document},
    )
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["imported_count"] == 4
    assert first_body["failed_count"] == 0
    assert first_body["relation_imported"] == 2

    second = client.post(
        "/aidp-mgmt/ontology/domains/2/import",
        headers=auth_headers(),
        json={"file_name": "export.json", "document": document},
    )
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["imported_count"] == 0
    assert second_body["skipped_count"] == 4


def test_partial_import_failure_is_reported_per_item(client, mock):
    _control(mock.base_url, "/_mock/ontology-import-fail?api_names=BadEntity")
    response = client.post(
        "/aidp-mgmt/ontology/domains/2/import",
        headers=auth_headers(),
        json={
            "file_name": "partial.json",
            "document": {
                "types": [{"api_name": "GoodType"}],
                "entities": [{"api_name": "BadEntity"}],
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["imported_count"] == 1
    assert body["failed_count"] == 1
    assert body["errors"][0]["api_name"] == "BadEntity"
    assert body["errors"][0]["message"] == "模拟导入失败"


def test_async_import_accepts_without_counts_or_progress_polling(client):
    document = {"types": [{"api_name": f"T{index}"} for index in range(201)]}
    response = client.post(
        "/aidp-mgmt/ontology/domains/2/import",
        headers=auth_headers(),
        json={"file_name": "big.json", "document": document},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["task_id"].startswith("ontology-import-")
    assert "imported_count" not in body


def test_metadata_field_and_chunk_annotation_round_trip(client, mock):
    fields = client.get(
        "/aidp-mgmt/ontology/domains/1/metadata-fields", headers=auth_headers()
    )
    assert fields.status_code == 200
    assert {item["field_name"] for item in fields.json()["value"]} == {
        "doc_type",
        "publish_year",
        "effective_date",
    }

    chunks = client.get(
        "/aidp-mgmt/ontology/knowledge-bases/aidp-kb-faq/chunks",
        headers=auth_headers(),
        params={"file_uuid": "00000000-0000-4000-8000-000000000001"},
    )
    assert chunks.status_code == 200
    chunk_ids = [item["chunk_id"] for item in chunks.json()["value"][:2]]
    assert len(chunk_ids) == 2

    annotated = client.patch(
        "/aidp-mgmt/ontology/knowledge-bases/aidp-kb-faq/chunks/metadata",
        headers=auth_headers(),
        json={
            "domain_id": "1",
            "metadata": {"doc_type": "Guide", "publish_year": 2026},
            "chunk_ids": chunk_ids,
        },
    )
    assert annotated.status_code == 200
    assert annotated.json()["success_count"] == 2

    detail = client.get(
        f"/aidp-mgmt/ontology/knowledge-bases/aidp-kb-faq/chunks/{chunk_ids[0]}",
        headers=auth_headers(),
    )
    assert detail.status_code == 200
    assert detail.json()["metadata"]["doc_type"] == "Guide"
    assert detail.json()["metadata"]["publish_year"] == 2026

    _control(mock.base_url, f"/_mock/ontology-metadata-fail?chunk_ids={chunk_ids[1]}")
    partial = client.patch(
        "/aidp-mgmt/ontology/knowledge-bases/aidp-kb-faq/chunks/metadata",
        headers=auth_headers(),
        json={
            "domain_id": "1",
            "metadata": {"doc_type": "Partial"},
            "chunk_ids": chunk_ids,
        },
    )
    assert partial.status_code == 200
    assert partial.json()["success_count"] == 1
    assert partial.json()["failed_count"] == 1
    failed = partial.json()["failed_list"][0]
    assert failed["message"] == "模拟标注失败"

    in_use = client.delete(
        "/aidp-mgmt/ontology/domains/1/metadata-fields/doc_type",
        headers=auth_headers(),
    )
    assert in_use.status_code == 200
    assert in_use.json().get("accepted") is True
    assert in_use.json().get("task_id")

    created = client.post(
        "/aidp-mgmt/ontology/domains/2/metadata-fields",
        headers=auth_headers(),
        json={"field_name": "channel", "field_type": "string"},
    )
    assert created.status_code == 400  # seed already defines channel in domain 2

    renamed = client.patch(
        "/aidp-mgmt/ontology/domains/2/metadata-fields/channel",
        headers=auth_headers(),
        json={"new_field_name": "source_channel"},
    )
    assert renamed.status_code == 200
    deleted = client.delete(
        "/aidp-mgmt/ontology/domains/2/metadata-fields/source_channel",
        headers=auth_headers(),
    )
    assert deleted.status_code == 200
    assert deleted.json().get("accepted") is True


def test_retrieval_metadata_is_returned_by_the_provider(mock):
    body = json.dumps(
        {
            "query": "知识库",
            "kds_list": ["aidp-kb-faq"],
            "search_method": "vector_search",
            "topk": 3,
            "hybrid_search_config": {"vector_candidates": 10, "hybrid_top_k": 0},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{mock.base_url}/KnowledgeBase/Tenants/aidp/Retrieval/FusionSearch",
        data=body,
        method="POST",
        headers={
            "Authorization": "Bearer mock-aidp-key",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    assert payload["result"], "seeded retrieval returned no chunks"
    assert any("metadata" in item for item in payload["result"])
