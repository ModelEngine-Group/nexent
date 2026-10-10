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


@pytest.mark.parametrize("seconds", [-1, 601])
def test_upload_delay_rejects_out_of_range_values(mock_aidp_server, seconds):
    client = TestClient(mock_aidp_server.app)
    assert client.post("/_mock/upload-seconds", params={"seconds": seconds}).status_code == 422


def test_history_filters_to_recent_records_and_returns_upstream_summary(mock_aidp_server):
    server = mock_aidp_server
    server._KNOWLEDGE_BASES["kb-1"] = {"kds_name": "测试知识库"}
    now = int(server.time.time())
    server._DOCUMENTS_BY_KB["kb-1"] = [
        {
            "file_uuid": "f-success", "file_name": "制度-成功.pdf", "status": 1,
            "first_upload_time": now - 3600,
        },
        {
            "file_uuid": "f-failed", "file_name": "制度-失败.docx", "status": 3,
            "first_upload_time": now - 1800,
        },
        {
            "file_uuid": "f-queued", "file_name": "排队任务.pdf", "status": 4,
            "first_upload_time": now - 900,
        },
        {
            "file_uuid": "f-old", "file_name": "旧失败任务.pdf", "status": 5,
            "first_upload_time": now - 31 * 24 * 60 * 60,
        },
    ]
    client = TestClient(server.app)

    response = client.post(
        "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/KnowledgeFiles/History",
        headers={"Authorization": "Bearer mock-aidp-key"},
        json={
            "fs_id": "fs-1", "dir_path": "/kb-1", "page": 1,
            "page_size": 10, "keyword": "失败", "status": 3,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["file_uuid"] for item in body["value"]] == ["f-failed"]
    assert body["total_count"] == 1
    assert body["total_record_count"] == 3
    assert body["success_record_count"] == 1
    assert body["processing_record_count"] == 0
    assert body["failed_record_count"] == 1
    assert body["queued_record_count"] == 1

    first_page = client.post(
        "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/KnowledgeFiles/History",
        headers={"Authorization": "Bearer mock-aidp-key"},
        json={
            "fs_id": "fs-1", "dir_path": "/kb-1", "page": 1,
            "page_size": 1, "keyword": "制度", "status": 0,
        },
    ).json()
    second_page = client.post(
        "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/KnowledgeFiles/History",
        headers={"Authorization": "Bearer mock-aidp-key"},
        json={
            "fs_id": "fs-1", "dir_path": "/kb-1", "page": 2,
            "page_size": 1, "keyword": "制度", "status": 0,
        },
    ).json()
    assert [item["file_uuid"] for item in first_page["value"]] == ["f-success"]
    assert first_page["next_link"] is not None
    assert [item["file_uuid"] for item in second_page["value"]] == ["f-failed"]
    assert second_page["next_link"] is None
