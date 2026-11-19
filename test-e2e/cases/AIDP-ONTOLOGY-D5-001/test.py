# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AIDP-ONTOLOGY-D5-001: authorization, binding and task-endpoint boundaries."""
from __future__ import annotations

import pytest

from aidp_ontology_support import (
    FakeAidpOntology,
    assert_no_internal_task_endpoint,
    auth_headers,
    build_client,
    configure_environment,
)

pytestmark = [
    pytest.mark.case_id("AIDP-ONTOLOGY-D5-001"),
    pytest.mark.stage("D5"),
    pytest.mark.p0,
    pytest.mark.sec,
]


def _api(monkeypatch, *, role: str, permissions: dict[str, str]):
    configure_environment(monkeypatch, role=role, permissions=permissions)
    fake = FakeAidpOntology()
    fake.install(monkeypatch)
    return fake, build_client()


@pytest.fixture
def user_api(monkeypatch):
    return _api(
        monkeypatch,
        role="USER",
        permissions={"kb-a": "EDIT", "kb-b": "READ_ONLY", "kb-c": "EDIT"},
    )


@pytest.fixture
def admin_api(monkeypatch):
    return _api(
        monkeypatch,
        role="ADMIN",
        permissions={"kb-a": "EDIT", "kb-b": "READ_ONLY", "kb-c": "EDIT"},
    )


def test_regular_user_cannot_change_ontology_definitions(user_api):
    fake, client = user_api
    domain = client.post(
        "/aidp-mgmt/ontology/domains",
        headers=auth_headers(),
        json={"name": "blocked", "description": ""},
    )
    assert domain.status_code == 403
    assert "create_domain" not in fake.calls

    entity = client.post(
        "/aidp-mgmt/ontology/domains/1/entities",
        headers=auth_headers(),
        json={"kind": "type", "api_name": "Blocked"},
    )
    assert entity.status_code == 403
    assert "create_entity" not in fake.calls

    field = client.post(
        "/aidp-mgmt/ontology/domains/1/metadata-fields",
        headers=auth_headers(),
        json={"field_name": "blocked", "field_type": "string"},
    )
    assert field.status_code == 403
    assert "create_field" not in fake.calls

    exported = client.post(
        "/aidp-mgmt/ontology/domains/1/export",
        headers=auth_headers(),
        json={"include_properties": True, "include_relations": True, "kind": None},
    )
    assert exported.status_code == 403
    assert "export" not in fake.calls

    imported = client.post(
        "/aidp-mgmt/ontology/domains/1/import",
        headers=auth_headers(),
        json={"file_name": "x.json", "document": {"types": [{"api_name": "X"}]}},
    )
    assert imported.status_code == 403
    assert "import" not in fake.calls


def test_binding_requires_target_kb_edit_and_known_kb(user_api):
    fake, client = user_api
    read_only = client.post(
        "/aidp-mgmt/ontology/domains/1/bindings",
        headers=auth_headers(),
        json={"kds_id": "kb-b"},
    )
    assert read_only.status_code == 403
    assert "create_binding" not in fake.calls

    unknown = client.post(
        "/aidp-mgmt/ontology/domains/1/bindings",
        headers=auth_headers(),
        json={"kds_id": "kb-unknown"},
    )
    assert unknown.status_code == 404
    assert "create_binding" not in fake.calls


def test_chunk_access_is_scoped_by_kb_permission_and_binding(user_api):
    fake, client = user_api
    readable = client.get(
        "/aidp-mgmt/ontology/knowledge-bases/kb-b/chunks",
        headers=auth_headers(),
        params={"file_uuid": "file-b"},
    )
    assert readable.status_code == 200
    assert readable.json()["value"][0]["chunk_id"] == 2001

    list_calls_before = fake.calls.count("list_chunks")
    unknown = client.get(
        "/aidp-mgmt/ontology/knowledge-bases/kb-unknown/chunks",
        headers=auth_headers(),
        params={"file_uuid": "file-x"},
    )
    assert unknown.status_code == 404
    assert fake.calls.count("list_chunks") == list_calls_before

    write_denied = client.patch(
        "/aidp-mgmt/ontology/knowledge-bases/kb-b/chunks/metadata",
        headers=auth_headers(),
        json={"domain_id": "1", "metadata": {"doc_type": "FAQ"}, "chunk_ids": [2001]},
    )
    assert write_denied.status_code == 403
    assert "batch_metadata" not in fake.calls


def test_cross_domain_annotation_is_rejected_before_upstream(admin_api):
    fake, client = admin_api
    not_bound = client.patch(
        "/aidp-mgmt/ontology/knowledge-bases/kb-a/chunks/metadata",
        headers=auth_headers(),
        json={"domain_id": "2", "metadata": {"channel": "web"}, "chunk_ids": [1001]},
    )
    assert not_bound.status_code == 400
    assert "batch_metadata" not in fake.calls

    read_only_kb = client.patch(
        "/aidp-mgmt/ontology/knowledge-bases/kb-b/chunks/metadata",
        headers=auth_headers(),
        json={"domain_id": "1", "metadata": {"doc_type": "FAQ"}, "chunk_ids": [2001]},
    )
    assert read_only_kb.status_code == 403
    assert "batch_metadata" not in fake.calls


def test_async_acceptance_has_no_internal_task_endpoint():
    assert_no_internal_task_endpoint()
