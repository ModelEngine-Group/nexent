"""Tests for filtering and pagination in the standalone AIDP mock server."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_aidp_server(tmp_path, monkeypatch):
    """Load the mock with isolated persisted state so tests never touch user data."""
    mock_path = Path(__file__).parent / "mock_servers" / "aidp_mgmt_mock_server.py"
    monkeypatch.setenv("AIDP_MOCK_STATE_FILE", str(tmp_path / "mock-state.json"))
    module_name = "isolated_aidp_mgmt_mock_server_for_tests"
    spec = importlib.util.spec_from_file_location(module_name, mock_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    try:
        yield module
    finally:
        sys.modules.pop(module_name, None)


def test_file_listing_filters_before_pagination(mock_aidp_server):
    server = mock_aidp_server
    server._KNOWLEDGE_BASES["kb-1"] = {"kds_name": "测试知识库"}
    server._DOCUMENTS_BY_KB["kb-1"] = [
        {"file_uuid": "f-1", "file_name": "制度-第一章.pdf", "status": 1},
        {"file_uuid": "f-2", "file_name": "制度-第二章.pdf", "status": 1},
        {"file_uuid": "f-3", "file_name": "普通说明.txt", "status": 1},
    ]
    client = TestClient(server.app)

    response = client.get(
        "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/KnowledgeFiles",
        params={"page": 1, "page_size": 1, "keyword": "制度"},
        headers={"Authorization": "Bearer mock-aidp-key"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["file_uuid"] for item in body["value"]] == ["f-1"]
    assert body["next_link"] is not None
    assert "keyword=%E5%88%B6%E5%BA%A6" in body["next_link"]


def test_kb_metadata_uses_the_dedicated_document_count_endpoint(mock_aidp_server):
    server = mock_aidp_server
    server._KNOWLEDGE_BASES["kb-1"] = {
        "kds_id": "kb-1",
        "kds_name": "测试知识库",
        "document_count": 999,
    }
    server._DOCUMENTS_BY_KB["kb-1"] = [
        {"file_uuid": "f-1", "file_name": "已入库.txt", "status": 1}
    ]
    client = TestClient(server.app)
    headers = {"Authorization": "Bearer mock-aidp-key"}
    kb_path = "/KnowledgeBase/Tenants/aidp/KnowledgeBases"

    listed = client.get(kb_path, headers=headers).json()["value"][0]
    detail = client.get(f"{kb_path}/kb-1", headers=headers).json()
    count = client.post(f"{kb_path}/kb-1/KnowledgeFiles/Count", headers=headers)

    assert "document_count" not in listed
    assert "document_count" not in detail
    assert count.status_code == 200
    assert count.json() == {"count": 1}


def test_upload_delay_is_applied_once_per_batch(mock_aidp_server, monkeypatch):
    server = mock_aidp_server
    server._KNOWLEDGE_BASES["kb-1"] = {"kds_name": "测试知识库"}
    sleep = AsyncMock()
    monkeypatch.setattr(server.asyncio, "sleep", sleep)
    client = TestClient(server.app)

    setting = client.post("/_mock/upload-seconds", params={"seconds": 10})
    assert setting.status_code == 200
    assert setting.json() == {"upload_seconds": 10}
    assert client.get("/health").json()["upload_seconds"] == 10

    response = client.post(
        "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/KnowledgeFiles/Upload",
        headers={"Authorization": "Bearer mock-aidp-key"},
        files=[
            ("files", ("first.txt", b"first", "text/plain")),
            ("files", ("second.txt", b"second", "text/plain")),
        ],
    )
    assert response.status_code == 200
    assert response.json()["summary"] == {"total": 2, "success": 2, "failed": 0}
    sleep.assert_awaited_once_with(10)

    assert client.post("/_mock/upload-seconds", params={"seconds": 0}).status_code == 200
    sleep.reset_mock()
    response = client.post(
        "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/KnowledgeFiles/Upload",
        headers={"Authorization": "Bearer mock-aidp-key"},
        files={"files": ("instant.txt", b"instant", "text/plain")},
    )
    assert response.status_code == 200
    sleep.assert_not_awaited()


def test_uploaded_file_is_visible_after_successful_response_by_default(mock_aidp_server):
    server = mock_aidp_server
    server._KNOWLEDGE_BASES["kb-1"] = {"kds_name": "测试知识库"}
    client = TestClient(server.app)
    headers = {"Authorization": "Bearer mock-aidp-key"}
    upload_path = "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/KnowledgeFiles/Upload"
    list_path = "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/KnowledgeFiles"

    response = client.post(
        upload_path,
        headers=headers,
        files={"files": ("新上传文件.txt", "测试内容".encode(), "text/plain")},
    )

    assert response.status_code == 200
    assert response.json()["summary"] == {"total": 1, "success": 1, "failed": 0}
    listed = client.get(list_path, headers=headers)
    assert listed.status_code == 200
    assert [item["file_name"] for item in listed.json()["value"]] == ["新上传文件.txt"]


def test_processing_delay_can_still_hide_new_upload_until_ingestion_finishes(mock_aidp_server):
    server = mock_aidp_server
    server._KNOWLEDGE_BASES["kb-1"] = {"kds_name": "测试知识库"}
    client = TestClient(server.app)
    headers = {"Authorization": "Bearer mock-aidp-key"}
    upload_path = "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/KnowledgeFiles/Upload"
    list_path = "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/KnowledgeFiles"

    assert client.post("/_mock/processing-seconds", params={"seconds": 60}).status_code == 200
    uploaded = client.post(
        upload_path,
        headers=headers,
        files={"files": ("处理中.txt", "测试内容".encode(), "text/plain")},
    )
    assert uploaded.status_code == 200
    assert client.get(list_path, headers=headers).json()["value"] == []

    history = client.post(
        "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/KnowledgeFiles/History",
        headers=headers,
        json={"dir_path": "/aidp/knowledge/kb-1", "page": 1},
    )
    assert history.status_code == 200
    assert any(item["file_name"] == "处理中.txt" for item in history.json()["value"])


@pytest.mark.parametrize("seconds", [-1, 601])
def test_upload_delay_rejects_out_of_range_values(mock_aidp_server, seconds):
    client = TestClient(mock_aidp_server.app)
    assert client.post("/_mock/upload-seconds", params={"seconds": seconds}).status_code == 422


def test_file_query_failure_can_be_enabled_and_reset(mock_aidp_server):
    server = mock_aidp_server
    server._KNOWLEDGE_BASES["kb-1"] = {"kds_name": "测试知识库"}
    server._DOCUMENTS_BY_KB["kb-1"] = [
        {"file_uuid": "f-1", "file_name": "制度.pdf", "status": 1},
    ]
    client = TestClient(server.app)
    path = "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/KnowledgeFiles"
    headers = {"Authorization": "Bearer mock-aidp-key"}
    assert client.post("/_mock/file-faults", params={"query_fail": True}).status_code == 200
    failed = client.get(path, headers=headers)
    assert failed.status_code == 503
    assert failed.json()["detail"]["code"] == "130501"
    client.post("/_mock/file-faults")
    restored = client.get(path, headers=headers)
    assert restored.status_code == 200
    assert restored.json()["value"][0]["file_uuid"] == "f-1"


def test_file_removal_failure_reports_the_file_without_removing_data(mock_aidp_server):
    server = mock_aidp_server
    server._KNOWLEDGE_BASES["kb-1"] = {"kds_name": "测试知识库"}
    file_uuid = "00000000-0000-4000-8000-000000000001"
    document = {"file_uuid": file_uuid, "file_name": "制度.pdf", "status": 1}
    server._DOCUMENTS_BY_KB["kb-1"] = [document]
    client = TestClient(server.app)
    client.post("/_mock/file-faults", params={"delete_fail": True})
    response = client.post(
        "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/KnowledgeFiles/Remove",
        headers={"Authorization": "Bearer mock-aidp-key"},
        json={"file_uuids": [file_uuid]},
    )
    assert response.status_code == 200
    assert response.json()["summary"] == {"total": 1, "success": 0, "failed": 1}
    assert response.json()["failed_list"][0]["file_uuid"] == file_uuid
    assert response.json()["failed_list"][0]["code"] == "130501"
    assert server._DOCUMENTS_BY_KB["kb-1"] == [document]
