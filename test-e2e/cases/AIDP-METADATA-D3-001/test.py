# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AIDP-METADATA-D3-001: field definitions, annotation and read-back runtime."""
from __future__ import annotations

import json
import urllib.request

import pytest

from aidp_ontology_support import MockAidp, auth_headers, build_client, configure_environment

pytestmark = [
    pytest.mark.case_id("AIDP-METADATA-D3-001"),
    pytest.mark.stage("D3"),
    pytest.mark.p0,
    pytest.mark.api_it,
]

KB_PERMISSIONS = {
    "aidp-kb-faq": "EDIT",
    "aidp-kb-product": "EDIT",
    "aidp-kb-api": "EDIT",
}


def _control(base_url: str, path: str) -> None:
    request = urllib.request.Request(f"{base_url}{path}", method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 200


@pytest.fixture(scope="module")
def mock(tmp_path_factory):
    with MockAidp(tmp_path_factory.mktemp("aidp-metadata-d3")) as server:
        yield server


@pytest.fixture(autouse=True)
def reset_mock(mock):
    _control(mock.base_url, "/_reset")
    _control(mock.base_url, "/_mock/ontology-metadata-fail?chunk_ids=")
    yield


@pytest.fixture
def client(monkeypatch, mock):
    configure_environment(
        monkeypatch,
        role="ADMIN",
        permissions=KB_PERMISSIONS,
        server_url=mock.base_url,
        api_key="mock-aidp-key",
    )
    return build_client()


def _faq_chunk_ids(client) -> list[int]:
    response = client.get(
        "/aidp-mgmt/ontology/knowledge-bases/aidp-kb-faq/chunks",
        headers=auth_headers(),
        params={"file_uuid": "00000000-0000-4000-8000-000000000001"},
    )
    assert response.status_code == 200
    return [item["chunk_id"] for item in response.json()["value"][:2]]


def test_field_definition_create_read_and_unused_delete(client):
    created = client.post(
        "/aidp-mgmt/ontology/domains/2/metadata-fields",
        headers=auth_headers(),
        json={"field_name": "ticket_type", "field_type": "string"},
    )
    assert created.status_code == 200
    created_body = created.json()
    assert created_body["field_name"] == "ticket_type"
    assert created_body["field_type"] == "string"
    assert created_body["id"] is not None

    listed = client.get(
        "/aidp-mgmt/ontology/domains/2/metadata-fields", headers=auth_headers()
    )
    assert "ticket_type" in {
        item["field_name"] for item in listed.json()["value"]
    }

    renamed = client.patch(
        "/aidp-mgmt/ontology/domains/2/metadata-fields/ticket_type",
        headers=auth_headers(),
        json={"new_field_name": "ticket_category"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["field_name"] == "ticket_category"

    deleted = client.delete(
        "/aidp-mgmt/ontology/domains/2/metadata-fields/ticket_category",
        headers=auth_headers(),
    )
    assert deleted.status_code == 200
    # AIDP may answer with an async receipt; acceptance is not completion.
    assert deleted.json().get("accepted") is True
    assert deleted.json().get("task_id")


def test_field_name_uses_conservative_limits(client):
    ok_ascii = client.post(
        "/aidp-mgmt/ontology/domains/2/metadata-fields",
        headers=auth_headers(),
        json={"field_name": "a" * 63, "field_type": "string"},
    )
    assert ok_ascii.status_code == 200

    bad_ascii = client.post(
        "/aidp-mgmt/ontology/domains/2/metadata-fields",
        headers=auth_headers(),
        json={"field_name": "b" * 64, "field_type": "string"},
    )
    assert bad_ascii.status_code == 400

    ok_chinese = client.post(
        "/aidp-mgmt/ontology/domains/2/metadata-fields",
        headers=auth_headers(),
        json={"field_name": "中" * 21, "field_type": "string"},
    )
    assert ok_chinese.status_code == 200

    bad_chinese = client.post(
        "/aidp-mgmt/ontology/domains/2/metadata-fields",
        headers=auth_headers(),
        json={"field_name": "中" * 22, "field_type": "string"},
    )
    assert bad_chinese.status_code == 400


def test_annotation_is_visible_in_list_and_detail(client, mock):
    chunk_ids = _faq_chunk_ids(client)
    response = client.patch(
        "/aidp-mgmt/ontology/knowledge-bases/aidp-kb-faq/chunks/metadata",
        headers=auth_headers(),
        json={
            "domain_id": "1",
            "metadata": {"doc_type": "FAQ", "publish_year": 2026},
            "chunk_ids": chunk_ids,
        },
    )
    assert response.status_code == 200
    assert response.json()["success_count"] == 2

    detail = client.get(
        f"/aidp-mgmt/ontology/knowledge-bases/aidp-kb-faq/chunks/{chunk_ids[0]}",
        headers=auth_headers(),
    )
    assert detail.status_code == 200
    assert detail.json()["metadata"]["doc_type"] == "FAQ"
    assert detail.json()["metadata"]["publish_year"] == 2026

    listed = client.get(
        "/aidp-mgmt/ontology/knowledge-bases/aidp-kb-faq/chunks",
        headers=auth_headers(),
        params={"file_uuid": "00000000-0000-4000-8000-000000000001"},
    )
    assert listed.status_code == 200
    row = next(item for item in listed.json()["value"] if item["chunk_id"] == chunk_ids[0])
    assert row["metadata"]["doc_type"] == "FAQ"


def test_partial_annotation_reports_success_and_failure(client, mock):
    chunk_ids = _faq_chunk_ids(client)
    _control(mock.base_url, f"/_mock/ontology-metadata-fail?chunk_ids={chunk_ids[1]}")
    response = client.patch(
        "/aidp-mgmt/ontology/knowledge-bases/aidp-kb-faq/chunks/metadata",
        headers=auth_headers(),
        json={
            "domain_id": "1",
            "metadata": {"doc_type": "Partial"},
            "chunk_ids": chunk_ids,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success_count"] == 1
    assert body["failed_count"] == 1
    assert body["failed_list"][0]["chunk_id"] == chunk_ids[1]
    assert body["failed_list"][0]["message"] == "模拟标注失败"

    first = client.get(
        f"/aidp-mgmt/ontology/knowledge-bases/aidp-kb-faq/chunks/{chunk_ids[0]}",
        headers=auth_headers(),
    )
    assert first.json()["metadata"]["doc_type"] == "Partial"
    second = client.get(
        f"/aidp-mgmt/ontology/knowledge-bases/aidp-kb-faq/chunks/{chunk_ids[1]}",
        headers=auth_headers(),
    )
    assert second.json()["metadata"].get("doc_type") != "Partial"


def test_in_use_field_delete_is_accepted_without_claiming_completion(client):
    chunk_ids = _faq_chunk_ids(client)
    client.patch(
        "/aidp-mgmt/ontology/knowledge-bases/aidp-kb-faq/chunks/metadata",
        headers=auth_headers(),
        json={"domain_id": "1", "metadata": {"doc_type": "Keep"}, "chunk_ids": [chunk_ids[0]]},
    )
    accepted = client.delete(
        "/aidp-mgmt/ontology/domains/1/metadata-fields/doc_type", headers=auth_headers()
    )
    assert accepted.status_code == 200
    assert accepted.json().get("accepted") is True
    assert accepted.json().get("task_id")

    fields = client.get(
        "/aidp-mgmt/ontology/domains/1/metadata-fields", headers=auth_headers()
    )
    assert "doc_type" in {item["field_name"] for item in fields.json()["value"]}
    detail = client.get(
        f"/aidp-mgmt/ontology/knowledge-bases/aidp-kb-faq/chunks/{chunk_ids[0]}",
        headers=auth_headers(),
    )
    assert detail.json()["metadata"]["doc_type"] == "Keep"


def test_retrieval_returns_chunk_metadata(mock):
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
    metadata_rows = [item.get("metadata") for item in payload["result"]]
    assert metadata_rows
    assert any(row for row in metadata_rows)
