# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Tests for filtering and pagination in the standalone AIDP mock server."""
from __future__ import annotations

import importlib.util
import json
import sys
import time
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
        {"file_uuid": "f-1", "file_name": "制度-第一章.pdf", "status": 1, "first_upload_time": time.time()},
        {"file_uuid": "f-2", "file_name": "制度-第二章.pdf", "status": 1, "first_upload_time": time.time()},
        {"file_uuid": "f-3", "file_name": "普通说明.txt", "status": 1, "first_upload_time": time.time()},
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

    # The live service keeps returning next_link on the last (empty) page.
    last_page = client.get(
        "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/KnowledgeFiles",
        params={"page": 2, "page_size": 10, "keyword": "制度"},
        headers={"Authorization": "Bearer mock-aidp-key"},
    )
    assert last_page.status_code == 200
    assert last_page.json()["value"] == []
    assert last_page.json()["next_link"] is not None


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
    assert "update_time" not in detail
    assert "rerank_model" not in detail
    assert "embedding_model" not in detail
    assert "top_k" in detail
    assert "kms_config_str" in detail
    assert count.status_code == 200
    assert count.json() == {"count": 1}

    filtered = client.post(
        f"{kb_path}/kb-1/KnowledgeFiles/Count",
        headers=headers,
        json={"keyword": "已入库"},
    )
    assert filtered.json() == {"count": 1}
    missing = client.post(
        f"{kb_path}/kb-1/KnowledgeFiles/Count",
        headers=headers,
        json={"keyword": "不存在"},
    )
    assert missing.json() == {"count": 0}


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

    duplicate = client.post(
        upload_path,
        headers=headers,
        files={"files": ("新上传文件.txt", "另一份内容".encode(), "text/plain")},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["summary"] == {"total": 1, "success": 0, "failed": 1}
    assert duplicate.json()["failed_list"][0]["code"] == 1089

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

    assert document["file_status"] == 2


FUSION_PATH = "/KnowledgeBase/Tenants/aidp/Retrieval/FusionSearch"
FUSION_HEADERS = {"Authorization": "Bearer mock-aidp-key"}


def _fusion(server, **payload):
    client = TestClient(server.app)
    return client.post(FUSION_PATH, headers=FUSION_HEADERS, json=payload)


def _hybrid(**overrides):
    config = {"vector_candidates": 10, "full_text_candidates": 10, "hybrid_top_k": 0,
              "vector_score_threshold": 0.0, "full_text_score_threshold": 0.0}
    config.update(overrides)
    return config


def test_fusion_accepts_all_seven_method_shapes(mock_aidp_server):
    server = mock_aidp_server
    shapes = {
        "vector_search": {"hybrid_search_config": _hybrid()},
        "full_text_search": {"hybrid_search_config": _hybrid()},
        "graph_search": {"graph_search_config": {"graph_top_k": 0}},
        "vector_search|full_text_search": {"hybrid_search_config": _hybrid()},
        "vector_search|graph_search": {"hybrid_search_config": _hybrid(),
                                       "graph_search_config": {"graph_top_k": 0}},
        "full_text_search|graph_search": {"hybrid_search_config": _hybrid(),
                                          "graph_search_config": {"graph_top_k": 0}},
        "hybrid_search": {"hybrid_search_config": _hybrid(),
                          "graph_search_config": {"graph_top_k": 0}},
    }
    for method, extra in shapes.items():
        response = _fusion(server, query="AIDP", kds_list=["aidp-kb-faq"],
                           search_method=method, topk=10, multi_modal_enable=True, **extra)
        assert response.status_code == 200, (method, response.text)
        assert isinstance(response.json()["result"], list), method


def test_fusion_rejects_inactive_channel_objects_and_bad_quota(mock_aidp_server):
    server = mock_aidp_server
    pure_graph_with_hybrid = _fusion(
        server, query="q", kds_list=["aidp-kb-faq"], search_method="graph_search",
        graph_search_config={"graph_top_k": 0}, hybrid_search_config=_hybrid())
    assert pure_graph_with_hybrid.status_code == 422

    overflow = _fusion(
        server, query="q", kds_list=["aidp-kb-faq"], search_method="hybrid_search",
        topk=10, hybrid_search_config=_hybrid(hybrid_top_k=8),
        graph_search_config={"graph_top_k": 5})
    assert overflow.status_code == 422

    unknown = _fusion(server, query="q", kds_list=["aidp-kb-faq"],
                      search_method="magic_search", hybrid_search_config=_hybrid())
    assert unknown.status_code == 422


def test_pure_graph_without_graph_returns_nothing_instead_of_falling_back(mock_aidp_server):
    server = mock_aidp_server
    # aidp-kb-product carries no graph; a graph-only request must stay empty.
    response = _fusion(server, query="AIDP", kds_list=["aidp-kb-product"],
                       search_method="graph_search", graph_search_config={"graph_top_k": 0})
    assert response.status_code == 200
    assert response.json()["result"] == []

    # The same KB does answer through vector retrieval.
    vector = _fusion(server, query="AIDP", kds_list=["aidp-kb-product"],
                     search_method="vector_search", hybrid_search_config=_hybrid())
    assert vector.json()["result"]


def test_retrieval_source_reports_actual_channels(mock_aidp_server):
    server = mock_aidp_server
    response = _fusion(server, query="AIDP", kds_list=["aidp-kb-faq"],
                       search_method="vector_search|graph_search",
                       hybrid_search_config=_hybrid(), graph_search_config={"graph_top_k": 0})
    methods = {tuple(item["retrieval_source"]["methods"]) for item in response.json()["result"]}
    assert methods
    for source in methods:
        assert set(source) <= {"vector_search", "graph_search"}


def test_zero_caps_are_not_zero_quotas_and_candidates_truncate(mock_aidp_server):
    server = mock_aidp_server
    zero = _fusion(server, query="AIDP", kds_list=["aidp-kb-faq", "aidp-kb-product"],
                   search_method="vector_search", topk=10,
                   hybrid_search_config=_hybrid(vector_candidates=10, hybrid_top_k=0))
    assert zero.status_code == 200
    assert zero.json()["result"]

    capped = _fusion(server, query="AIDP", kds_list=["aidp-kb-faq", "aidp-kb-product"],
                     search_method="vector_search", topk=10,
                     hybrid_search_config=_hybrid(vector_candidates=1, hybrid_top_k=0))
    assert len(capped.json()["result"]) <= 1


def test_legacy_top_k_alias_is_translated_once(mock_aidp_server):
    server = mock_aidp_server
    response = _fusion(server, query="AIDP", kds_list=["aidp-kb-product"], top_k=1,
                       search_method="vector_search", hybrid_search_config=_hybrid())
    assert response.status_code == 200
    assert len(response.json()["result"]) <= 1

    conflict = _fusion(server, query="AIDP", kds_list=["aidp-kb-product"], top_k=1, topk=5,
                       search_method="vector_search", hybrid_search_config=_hybrid())
    assert conflict.status_code == 422




def test_file_removal_exposes_the_deleting_state_then_hides_the_row(
    mock_aidp_server, monkeypatch
):
    server = mock_aidp_server
    server._KNOWLEDGE_BASES["kb-1"] = {"kds_name": "测试知识库"}
    file_uuid = "00000000-0000-4000-8000-000000000001"
    server._DOCUMENTS_BY_KB["kb-1"] = [
        {
            "file_uuid": file_uuid,
            "file_name": "制度.pdf",
            "status": 1,
            "first_upload_time": time.time(),
        }
    ]
    client = TestClient(server.app)
    headers = {"Authorization": "Bearer mock-aidp-key"}
    list_path = "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/KnowledgeFiles"
    history_path = "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/KnowledgeFiles/History"

    monkeypatch.setattr(server, "_FILE_DELETE_SECONDS", 60)
    removed = client.post(
        "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/KnowledgeFiles/Remove",
        headers=headers,
        json={"file_uuids": [file_uuid]},
    )
    assert removed.status_code == 200
    assert removed.json()["summary"] == {"total": 1, "success": 1, "failed": 0}

    visible = client.get(list_path, headers=headers).json()["value"]
    assert visible[0]["file_uuid"] == file_uuid
    assert visible[0]["file_status"] == 1

    # After the deletion window the row leaves KnowledgeFiles but remains in
    # the history audit log.
    server._DOCUMENTS_BY_KB["kb-1"][0]["_deleted_at"] = 0
    assert client.get(list_path, headers=headers).json()["value"] == []
    history = client.post(
        history_path,
        headers=headers,
        json={"dir_path": "/aidp/knowledge/kb-1", "page": 1},
    )
    assert [item["file_uuid"] for item in history.json()["value"]] == [file_uuid]


def test_history_reports_the_filtered_total_and_keeps_next_link(
    mock_aidp_server,
):
    server = mock_aidp_server
    server._KNOWLEDGE_BASES["kb-1"] = {"kds_name": "测试知识库"}
    server._DOCUMENTS_BY_KB["kb-1"] = [
        {"file_uuid": "f-1", "file_name": "制度-第一章.pdf", "status": 1, "first_upload_time": time.time()},
        {"file_uuid": "f-2", "file_name": "制度-第二章.pdf", "status": 1, "first_upload_time": time.time()},
        {"file_uuid": "f-3", "file_name": "普通说明.txt", "status": 1, "first_upload_time": time.time()},
    ]
    client = TestClient(server.app)
    headers = {"Authorization": "Bearer mock-aidp-key"}

    response = client.post(
        "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/KnowledgeFiles/History",
        headers=headers,
        json={
            "fs_id": "fs-1",
            "dir_path": "/aidp/knowledge/kb-1",
            "page": 1,
            "page_size": 10,
            "keyword": "制度",
        },
    )

    body = response.json()
    assert [item["file_uuid"] for item in body["value"]] == ["f-1", "f-2"]
    assert body["total_count"] == 2
    assert body["total_record_count"] == 2
    assert body["next_link"] is not None


def test_history_total_count_is_page_local(mock_aidp_server):
    server = mock_aidp_server
    server._KNOWLEDGE_BASES["kb-1"] = {"kds_name": "测试知识库"}
    server._DOCUMENTS_BY_KB["kb-1"] = [
        {"file_uuid": f"f-{index}", "file_name": f"制度-{index}.pdf", "status": 1, "first_upload_time": time.time()}
        for index in range(3)
    ]
    client = TestClient(server.app)
    headers = {"Authorization": "Bearer mock-aidp-key"}
    path = "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/KnowledgeFiles/History"

    first = client.post(
        path, headers=headers,
        json={"dir_path": "/aidp/knowledge/kb-1", "page": 1, "page_size": 2},
    ).json()
    second = client.post(
        path, headers=headers,
        json={"dir_path": "/aidp/knowledge/kb-1", "page": 2, "page_size": 2},
    ).json()

    assert len(first["value"]) == 2 and first["total_count"] == 2
    assert len(second["value"]) == 1 and second["total_count"] == 1
    assert first["total_record_count"] == second["total_record_count"] == 3
    assert first["next_link"] is not None and second["next_link"] is not None


def test_history_total_record_count_is_computed_before_status_filter(mock_aidp_server):
    server = mock_aidp_server
    server._KNOWLEDGE_BASES["kb-1"] = {"kds_name": "测试知识库"}
    now = time.time()
    server._DOCUMENTS_BY_KB["kb-1"] = [
        {"file_uuid": "f-1", "file_name": "制度-第一章.pdf", "status": 1, "first_upload_time": now},
        {"file_uuid": "f-2", "file_name": "制度-第二章.pdf", "status": 3, "first_upload_time": now},
        {"file_uuid": "f-3", "file_name": "普通说明.txt", "status": 1, "first_upload_time": now},
    ]
    client = TestClient(server.app)
    headers = {"Authorization": "Bearer mock-aidp-key"}

    body = client.post(
        "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/KnowledgeFiles/History",
        headers=headers,
        json={
            "dir_path": "/aidp/knowledge/kb-1",
            "page": 1,
            "page_size": 10,
            "keyword": "制度",
            "status": 1,
        },
    ).json()

    assert [item["file_uuid"] for item in body["value"]] == ["f-1"]
    assert body["total_count"] == 1
    assert body["total_record_count"] == 2


def test_chinese_demo_failure_reasons_are_json_without_top_level_code(
    mock_aidp_server,
):
    docs = mock_aidp_server._DOCUMENTS_BY_KB["aidp-kb-faq"]
    failed = [doc for doc in docs if doc.get("status") in (3, 5)]
    assert failed
    for doc in failed:
        assert "error_code" not in doc
        parsed = json.loads(doc["extraction_failure_reason"])
        assert parsed["error_code"] and parsed["msg"]


def _folder_client(mock_aidp_server):
    mock_aidp_server._KNOWLEDGE_BASES["kb-1"] = {
        "kds_id": "kb-1",
        "kds_name": "目录测试库",
    }
    mock_aidp_server._FOLDERS_BY_KB["kb-1"] = [
        {"folder_path": "/制度", "create_time": 1},
        {"folder_path": "/制度/法规", "create_time": 1},
        {"folder_path": "/空目录", "create_time": 1},
    ]
    mock_aidp_server._DOCUMENTS_BY_KB["kb-1"] = [
        {
            "file_uuid": "f-1",
            "file_ino_no": 1,
            "file_name": "条例.txt",
            "file_type": "txt",
            "file_size": 10,
            "status": 1,
            "update_time": 1700000000,
            "folder_path": "/制度",
        },
        {
            "file_uuid": "f-2",
            "file_ino_no": 2,
            "file_name": "根文件.pdf",
            "file_type": "pdf",
            "file_size": 20,
            "status": 1,
            "update_time": 1700000100,
            "folder_path": "/",
        },
    ]
    return TestClient(mock_aidp_server.app)


def test_folder_tree_returns_direct_folders_and_paginated_files(mock_aidp_server):
    client = _folder_client(mock_aidp_server)
    headers = {"Authorization": "Bearer mock-aidp-key"}
    folders = "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/Folders"

    root = client.get(
        f"{folders}/0",
        params={"folder_path": "/", "include_files": True, "page": 1, "page_size": 10},
        headers=headers,
    )
    assert root.status_code == 200
    root_body = root.json()
    assert root_body["folder_id"] == 0
    assert root_body["folder_path"] == "/"
    assert [(folder["folder_name"], folder["has_child_folders"]) for folder in root_body["folders"]] == [
        ("制度", True),
        ("空目录", False),
    ]
    assert [item["file_uuid"] for item in root_body["files"]["value"]] == ["f-2"]
    assert root_body["files"]["total"] == 1

    nested_path = "/制度"
    nested = client.get(
        f"{folders}/{mock_aidp_server._folder_id_for_path(nested_path)}",
        params={
            "folder_path": nested_path,
            "include_files": True,
            "page": 1,
            "page_size": 1,
            "keyword": "条例",
        },
        headers=headers,
    ).json()
    assert [folder["folder_name"] for folder in nested["folders"]] == ["法规"]
    assert [item["file_uuid"] for item in nested["files"]["value"]] == ["f-1"]
    assert nested["files"]["total"] == 1
    assert nested["files"]["page_size"] == 1


def test_folder_crud_and_empty_folder_delete_rule(mock_aidp_server):
    client = _folder_client(mock_aidp_server)
    headers = {"Authorization": "Bearer mock-aidp-key"}
    folders = "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/Folders"

    conflict = client.post(
        f"{folders}/0",
        headers=headers,
        json={"parent_folder_path": "/", "folder_name": "制度"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == 1089

    created = client.post(
        f"{folders}/0",
        headers=headers,
        json={"parent_folder_path": "/", "folder_name": "新目录"},
    )
    assert created.status_code == 200
    created_body = created.json()
    assert created_body["folder_path"] == "/新目录"
    assert created_body["folder_id"] == mock_aidp_server._folder_id_for_path("/新目录")

    new_folder_id = mock_aidp_server._folder_id_for_path("/新目录")
    renamed = client.patch(
        f"{folders}/{new_folder_id}",
        headers=headers,
        json={
            "parent_folder_path": "/",
            "old_folder_name": "新目录",
            "new_folder_name": "历史",
        },
    )
    assert renamed.status_code == 200
    assert renamed.json() == {"folder_path": "/历史"}

    non_empty = client.delete(
        f"{folders}/{mock_aidp_server._folder_id_for_path('/制度')}",
        headers=headers,
        params={"folder_path": "/制度"},
    )
    assert non_empty.status_code == 400

    empty = client.delete(
        f"{folders}/{mock_aidp_server._folder_id_for_path('/空目录')}",
        headers=headers,
        params={"folder_path": "/空目录"},
    )
    assert empty.status_code == 204
    tree = client.get(
        f"{folders}/0",
        params={"folder_path": "/", "include_files": True},
        headers=headers,
    ).json()
    assert [folder["folder_name"] for folder in tree["folders"]] == ["制度", "历史"]

    history_id = mock_aidp_server._folder_id_for_path("/历史")
    target_id = mock_aidp_server._folder_id_for_path("/制度")
    moved = client.post(
        f"{folders}/{history_id}/Move",
        headers=headers,
        json={
            "src_parent_folder_path": "/",
            "folder_name": "历史",
            "target_parent_folder_path": "/制度",
            "target_parent_folder_id": target_id,
            "merge_on_conflict": False,
        },
    )
    assert moved.status_code == 200
    assert moved.json()["folder_path"] == "/制度/历史"


def test_directory_upload_preserves_relative_path_and_file_move_rename(mock_aidp_server):
    client = _folder_client(mock_aidp_server)
    headers = {"Authorization": "Bearer mock-aidp-key"}
    files_path = "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/KnowledgeFiles"
    folders_path = files_path.replace("/KnowledgeFiles", "/Folders")

    uploaded = client.post(
        f"{files_path}/Upload",
        headers=headers,
        data={
            "target_folder_path": "/制度",
            "target_folder_id": mock_aidp_server._folder_id_for_path("/制度"),
            "relative_paths": ["合同/2026"],
        },
        files=[("files", ("新条例.txt", b"content", "text/plain"))],
    )
    assert uploaded.status_code == 200
    receipt = uploaded.json()["success_list"][0]
    file_uuid = receipt["file_uuid"]
    assert receipt["relative_path"] == "合同/2026"
    assert receipt["file_path"] == "/制度/合同/2026/新条例.txt"
    assert receipt["folder_id"] == mock_aidp_server._folder_id_for_path("/制度/合同/2026")
    document = next(
        doc
        for doc in mock_aidp_server._DOCUMENTS_BY_KB["kb-1"]
        if doc["file_uuid"] == file_uuid
    )
    assert document["folder_path"] == "/制度/合同/2026"

    target_path = "/制度/合同/2026"
    target_tree = client.get(
        f"{folders_path}/{mock_aidp_server._folder_id_for_path(target_path)}",
        params={"folder_path": target_path, "include_files": True},
        headers=headers,
    ).json()
    assert [item["file_name"] for item in target_tree["files"]["value"]] == ["新条例.txt"]
    assert target_tree["folders"] == []

    target_id = mock_aidp_server._folder_id_for_path("/制度/法规")
    moved = client.post(
        f"{files_path}/Move",
        headers=headers,
        json={
            "file_uuids": [file_uuid],
            "target_folder_path": "/制度/法规",
            "target_folder_id": target_id,
        },
    )
    assert moved.status_code == 200
    assert moved.json()["summary"] == {"total": 1, "success": 1, "failed": 0}
    assert document["folder_path"] == "/制度/法规"

    renamed = client.patch(
        files_path,
        headers=headers,
        json={"file_uuid": file_uuid, "new_file_name": "改名后.txt"},
    )
    assert renamed.status_code == 204
    assert document["file_name"] == "改名后.txt"
