# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AIDP-METADATA-D5-001: annotation authorization and source-metadata chain."""
from __future__ import annotations

from pathlib import Path

import pytest

from aidp_ontology_support import (
    REPO_ROOT,
    FakeAidpOntology,
    auth_headers,
    build_client,
    configure_environment,
)

pytestmark = [
    pytest.mark.case_id("AIDP-METADATA-D5-001"),
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


def test_regular_user_cannot_change_field_definitions(user_api):
    fake, client = user_api
    created = client.post(
        "/aidp-mgmt/ontology/domains/1/metadata-fields",
        headers=auth_headers(),
        json={"field_name": "blocked", "field_type": "string"},
    )
    assert created.status_code == 403
    assert "create_field" not in fake.calls

    renamed = client.patch(
        "/aidp-mgmt/ontology/domains/1/metadata-fields/doc_type",
        headers=auth_headers(),
        json={"new_field_name": "blocked"},
    )
    assert renamed.status_code == 403

    deleted = client.delete(
        "/aidp-mgmt/ontology/domains/1/metadata-fields/doc_type", headers=auth_headers()
    )
    assert deleted.status_code == 403


def test_annotation_requires_kb_edit_and_defined_keys(user_api):
    fake, client = user_api
    read_only = client.patch(
        "/aidp-mgmt/ontology/knowledge-bases/kb-b/chunks/metadata",
        headers=auth_headers(),
        json={"domain_id": "1", "metadata": {"doc_type": "FAQ"}, "chunk_ids": [2001]},
    )
    assert read_only.status_code == 403
    assert "batch_metadata" not in fake.calls

    undefined = client.patch(
        "/aidp-mgmt/ontology/knowledge-bases/kb-a/chunks/metadata",
        headers=auth_headers(),
        json={"domain_id": "1", "metadata": {"unknown": "x"}, "chunk_ids": [1001]},
    )
    assert undefined.status_code == 400
    assert "batch_metadata" not in fake.calls


def test_annotation_cannot_target_a_chunk_from_another_kb(admin_api):
    fake, client = admin_api
    foreign = client.patch(
        "/aidp-mgmt/ontology/knowledge-bases/kb-a/chunks/metadata",
        headers=auth_headers(),
        json={"domain_id": "1", "metadata": {"doc_type": "FAQ"}, "chunk_ids": [2001]},
    )
    assert foreign.status_code == 400
    assert foreign.json()["details"]["errors"][0]["message"] == "Chunk 不属于该知识库"
    assert "batch_metadata" not in fake.calls


def test_retrieval_metadata_reaches_the_source_display_chain():
    # META-004 requires checking the existing SDK -> source panel passthrough;
    # the temporary UI must not introduce a new retrieval filter parameter.
    sdk = (REPO_ROOT / "sdk/nexent/core/ext_components/aidp/aidp_search_tool.py").read_text(
        encoding="utf-8"
    )
    assert '"metadata": metadata' in sdk

    source_helper = (REPO_ROOT / "frontend/lib/source.ts").read_text(encoding="utf-8")
    assert "sourceMetadata:" in source_helper
    assert "metadata as JsonObject" in source_helper

    metadata_component = (
        REPO_ROOT / "frontend/components/common/sourceMetadata.tsx"
    ).read_text(encoding="utf-8")
    assert "metadata?: JsonObject" in metadata_component

    sources_panel = (
        REPO_ROOT / "frontend/app/[locale]/newchat/ui/sources-panel.tsx"
    ).read_text(encoding="utf-8")
    assert "<SourceMetadata metadata={item.sourceMetadata} />" in sources_panel

    for relative in (
        "backend/ext_components/aidp/apps/aidp_ontology_app.py",
        "backend/ext_components/aidp/services/aidp_ontology_service.py",
    ):
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "metadata_condition" not in text
