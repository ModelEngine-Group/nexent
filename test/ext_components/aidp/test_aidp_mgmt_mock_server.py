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
    config = {"vector_candidates": 10, "full_text_candidates": 10, "hybrid_top_k": 5,
              "vector_score_threshold": 0.0, "full_text_score_threshold": 0.0}
    config.update(overrides)
    return config


def test_fusion_accepts_all_seven_method_shapes(mock_aidp_server):
    server = mock_aidp_server
    shapes = {
        "vector_search": {"hybrid_search_config": _hybrid()},
        "full_text_search": {"hybrid_search_config": _hybrid()},
        "graph_search": {"graph_search_config": {"graph_top_k": 5}},
        "vector_search|full_text_search": {"hybrid_search_config": _hybrid()},
        "vector_search|graph_search": {"hybrid_search_config": _hybrid(),
                                       "graph_search_config": {"graph_top_k": 5}},
        "full_text_search|graph_search": {"hybrid_search_config": _hybrid(),
                                          "graph_search_config": {"graph_top_k": 5}},
        "hybrid_search": {"hybrid_search_config": _hybrid(),
                          "graph_search_config": {"graph_top_k": 5}},
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
        graph_search_config={"graph_top_k": 5}, hybrid_search_config=_hybrid())
    assert pure_graph_with_hybrid.status_code == 422

    overflow = _fusion(
        server, query="q", kds_list=["aidp-kb-faq"], search_method="hybrid_search",
        topk=10, hybrid_search_config=_hybrid(hybrid_top_k=8),
        graph_search_config={"graph_top_k": 5})
    assert overflow.status_code == 422

    unknown = _fusion(server, query="q", kds_list=["aidp-kb-faq"],
                      search_method="magic_search", hybrid_search_config=_hybrid())
    assert unknown.status_code == 422

    # Real AIDP validates a present cap as 1-100; explicit 0 is rejected.
    zero_hybrid = _fusion(server, query="q", kds_list=["aidp-kb-faq"],
                          search_method="vector_search",
                          hybrid_search_config=_hybrid(hybrid_top_k=0))
    assert zero_hybrid.status_code == 422

    zero_graph = _fusion(server, query="q", kds_list=["aidp-kb-faq"],
                         search_method="graph_search",
                         graph_search_config={"graph_top_k": 0})
    assert zero_graph.status_code == 422


def test_pure_graph_without_graph_returns_nothing_instead_of_falling_back(mock_aidp_server):
    server = mock_aidp_server
    # aidp-kb-product carries no graph; a graph-only request must stay empty.
    response = _fusion(server, query="AIDP", kds_list=["aidp-kb-product"],
                       search_method="graph_search", graph_search_config={"graph_top_k": 5})
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
                       hybrid_search_config=_hybrid(), graph_search_config={"graph_top_k": 5})
    methods = {tuple(item["retrieval_source"]["methods"]) for item in response.json()["result"]}
    assert methods
    for source in methods:
        assert set(source) <= {"vector_search", "graph_search"}


def test_caps_are_required_and_candidates_truncate(mock_aidp_server):
    server = mock_aidp_server
    default = _fusion(server, query="AIDP", kds_list=["aidp-kb-faq", "aidp-kb-product"],
                      search_method="vector_search", topk=10,
                      hybrid_search_config=_hybrid())
    assert default.status_code == 200
    assert default.json()["result"]

    zero = _fusion(server, query="AIDP", kds_list=["aidp-kb-faq", "aidp-kb-product"],
                   search_method="vector_search", topk=10,
                   hybrid_search_config=_hybrid(hybrid_top_k=0))
    assert zero.status_code == 422

    capped = _fusion(server, query="AIDP", kds_list=["aidp-kb-faq", "aidp-kb-product"],
                     search_method="vector_search", topk=10,
                     hybrid_search_config=_hybrid(vector_candidates=1, hybrid_top_k=1))
    assert len(capped.json()["result"]) <= 1


@pytest.mark.parametrize("method,topk,hybrid,graph,expected", [
    ("hybrid_search", 10, {}, {}, 200),
    ("hybrid_search", 5, {"hybrid_top_k": 10}, {"graph_top_k": 10}, 422),
    ("vector_search", 10, {"hybrid_top_k": 5}, None, 200),
    ("vector_search|graph_search", 10, {"hybrid_top_k": 5}, {"graph_top_k": 5}, 200),
    ("hybrid_search", 10, {"hybrid_top_k": 5}, {"graph_top_k": 5}, 200),
])
def test_fusion_quota_matrix(mock_aidp_server, method, topk, hybrid, graph, expected):
    server = mock_aidp_server
    payload = {"query": "AIDP", "kds_list": ["aidp-kb-faq"], "search_method": method, "topk": topk}
    if hybrid is not None:
        payload["hybrid_search_config"] = hybrid
    if graph is not None:
        payload["graph_search_config"] = graph
    response = _fusion(server, **payload)
    assert response.status_code == expected, response.text


def test_legacy_top_k_alias_is_translated_once(mock_aidp_server):
    server = mock_aidp_server
    response = _fusion(server, query="AIDP", kds_list=["aidp-kb-product"], top_k=1,
                       search_method="vector_search", hybrid_search_config=_hybrid(hybrid_top_k=1))
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


def test_preview_uses_explicit_pdf_fixture_for_converted_document(mock_aidp_server, tmp_path):
    server = mock_aidp_server
    server._PREVIEW_FIXTURE_DIR = tmp_path
    file_uuid = "a2fc91f8-d2cc-4912-9c2b-435ac4b0aa14"
    expected = server._synthetic_pdf("Actual demo content")
    (tmp_path / f"{file_uuid}.pdf").write_bytes(expected)

    content, name = server._preview_payload({"file_uuid": file_uuid, "file_name": "demo.html"})

    assert content == expected
    assert name == "demo.pdf"


@pytest.mark.parametrize("file_uuid", ["missing", "../outside", "a2fc91f8-d2cc-4912-9c2b-435ac4b0aa14"])
def test_missing_or_invalid_fixture_keeps_default_mock_preview(mock_aidp_server, tmp_path, file_uuid):
    server = mock_aidp_server
    server._PREVIEW_FIXTURE_DIR = tmp_path

    content, name = server._preview_payload({"file_uuid": file_uuid, "file_name": "demo.md"})

    assert b"AIDP conversion of demo.md" in content
    assert name == "demo.pdf"


def test_preview_rejects_non_pdf_fixture(mock_aidp_server, tmp_path):
    server = mock_aidp_server
    server._PREVIEW_FIXTURE_DIR = tmp_path
    file_uuid = "a2fc91f8-d2cc-4912-9c2b-435ac4b0aa14"
    (tmp_path / f"{file_uuid}.pdf").write_bytes(b"not a PDF")

    with pytest.raises(ValueError, match="Preview fixture is not a PDF"):
        server._preview_payload({"file_uuid": file_uuid, "file_name": "demo.html"})


def test_native_preview_and_download_restore_original_fixture(mock_aidp_server, tmp_path):
    server = mock_aidp_server
    server._DOCUMENT_FIXTURE_DIR = tmp_path
    file_uuid = "a2fc91f8-d2cc-4912-9c2b-435ac4b0aa14"
    expected = b"%PDF-1.4 original uploaded PDF"
    (tmp_path / f"{file_uuid}.bin").write_bytes(expected)
    document = {"file_uuid": file_uuid, "file_name": "demo.pdf"}

    assert server._document_content(document) == expected
    assert server._preview_payload(document) == (expected, "demo.pdf")
    server._DOCUMENT_PAYLOADS[file_uuid] = b"new upload"
    assert server._document_content(document) == b"new upload"


def test_original_fixture_cannot_escape_directory(mock_aidp_server, tmp_path):
    server = mock_aidp_server
    server._DOCUMENT_FIXTURE_DIR = tmp_path / "fixtures"
    (tmp_path / "outside.bin").write_bytes(b"private")

    assert server._document_content({"file_uuid": "../outside", "file_name": "demo.txt"}) == b"Mock AIDP content for demo.txt\n"


# ---------------------------------------------------------------------------
# Document chunk contract (2026-11-05): query list, DELETE body/204, TEXT edit
# ---------------------------------------------------------------------------

_CHUNK_KB = "kb-chunks"
_CHUNK_FILE = "3f8dbd1f-d5f9-43f7-89b9-b70809531647"


def _chunk_client(server):
    server._KNOWLEDGE_BASES[_CHUNK_KB] = {"kds_name": "切片知识库"}
    server._DOCUMENTS_BY_KB[_CHUNK_KB] = [
        {
            "file_uuid": _CHUNK_FILE,
            "file_name": "切片样例.pdf",
            "status": 1,
            "first_upload_time": time.time(),
        }
    ]
    return TestClient(server.app)


def test_chunk_list_uses_query_and_null_next_link_on_last_page(mock_aidp_server):
    client = _chunk_client(mock_aidp_server)
    auth = {"Authorization": "Bearer mock-aidp-key"}
    path = f"/KnowledgeBase/Tenants/aidp/KnowledgeBases/{_CHUNK_KB}/Chunks"

    first = client.get(
        path,
        params={"file_uuid": _CHUNK_FILE, "page": 1, "page_size": 2},
        headers=auth,
    )
    assert first.status_code == 200
    body = first.json()
    assert body["total_count"] == 5
    assert body["next_link"] is not None
    assert [item["chunk_type"] for item in body["value"]] == ["TEXT", "TEXT"]
    assert all(isinstance(item["chunk_id"], int) for item in body["value"])
    assert body["value"][0]["page_ids"] == [1]

    last = client.get(
        path,
        params={"file_uuid": _CHUNK_FILE, "page": 3, "page_size": 2},
        headers=auth,
    )
    assert last.status_code == 200
    assert last.json()["next_link"] is None
    assert [item["chunk_type"] for item in last.json()["value"]] == ["IMAGE"]


def test_chunk_create_returns_string_id_and_appends_to_the_end(mock_aidp_server):
    client = _chunk_client(mock_aidp_server)
    auth = {"Authorization": "Bearer mock-aidp-key"}
    path = f"/KnowledgeBase/Tenants/aidp/KnowledgeBases/{_CHUNK_KB}/Chunks"

    # Generate the file's five seed chunks first so the new id is deterministic.
    client.get(path, params={"file_uuid": _CHUNK_FILE}, headers=auth)
    created = client.put(
        path,
        headers=auth,
        json={"file_uuid": _CHUNK_FILE, "chunk_text": "新增切片"},
    )
    assert created.status_code == 200
    assert created.json() == {"chunk_id": "6"}

    page = client.get(
        path,
        params={"file_uuid": _CHUNK_FILE, "page": 1, "page_size": 100},
        headers=auth,
    ).json()
    assert page["total_count"] == 6
    assert page["value"][-1]["chunk_id"] == 6
    assert page["value"][-1]["chunk_text"] == "新增切片"
    assert page["value"][-1]["chunk_type"] == "TEXT"


def test_chunk_update_returns_the_full_chunk_object(mock_aidp_server):
    client = _chunk_client(mock_aidp_server)
    auth = {"Authorization": "Bearer mock-aidp-key"}
    path = f"/KnowledgeBase/Tenants/aidp/KnowledgeBases/{_CHUNK_KB}/Chunks"

    # Generate the seed chunks, then edit chunk 1 (TEXT).
    client.get(path, params={"file_uuid": _CHUNK_FILE}, headers=auth)
    updated = client.patch(f"{path}/1", headers=auth, json={"chunk_text": "改后文本"})
    assert updated.status_code == 200
    body = updated.json()
    assert body["chunk_id"] == 1
    assert body["chunk_text"] == "改后文本"
    assert body["chunk_type"] == "TEXT"
    assert body["page_ids"] == [1]
    assert body["metadata"]["section"] == "part-1"


def test_chunk_delete_requires_json_body_and_answers_204(mock_aidp_server):
    client = _chunk_client(mock_aidp_server)
    auth = {"Authorization": "Bearer mock-aidp-key"}
    path = f"/KnowledgeBase/Tenants/aidp/KnowledgeBases/{_CHUNK_KB}/Chunks"
    client.get(path, params={"file_uuid": _CHUNK_FILE}, headers=auth)

    removed = client.post(
        f"{path}/Remove",
        headers=auth,
        json={"chunk_ids": [1, 2]},
    )
    assert removed.status_code == 204
    assert removed.content == b""

    page = client.get(
        path,
        params={"file_uuid": _CHUNK_FILE, "page": 1, "page_size": 100},
        headers=auth,
    ).json()
    assert page["total_count"] == 3
    assert [item["chunk_id"] for item in page["value"]] == [3, 4, 5]

    # The DELETE-with-body variant is not served by the real deployment.
    legacy = client.request(
        "DELETE",
        path,
        headers=auth,
        json={"chunk_ids": [3]},
    )
    assert legacy.status_code in (404, 405)


# ---------------------------------------------------------------------------
# File summary contract
# ---------------------------------------------------------------------------

_SUMMARY_KB = "kb-summary"
_SUMMARY_FILE = "acc57fdc-45cc-4f16-bcfa-633bc28e2256"


def _summary_client(server, *, enabled=True, preview=True):
    server._KNOWLEDGE_BASES[_SUMMARY_KB] = {
        "kds_name": "摘要知识库",
        "summary_enable": enabled,
        "summary_model": "qwen3",
        "summary_preview": preview,
    }
    server._DOCUMENTS_BY_KB[_SUMMARY_KB] = [
        {
            "file_uuid": _SUMMARY_FILE,
            "file_name": "年度报告.pdf",
            "status": 1,
            "first_upload_time": time.time(),
        }
    ]
    return TestClient(server.app)


def test_summary_returns_empty_object_when_preview_disabled(mock_aidp_server):
    client = _summary_client(mock_aidp_server, enabled=True, preview=False)
    response = client.post(
        f"/KnowledgeBase/Tenants/aidp/KnowledgeBases/{_SUMMARY_KB}"
        "/KnowledgeFiles/Summary",
        headers={"Authorization": "Bearer mock-aidp-key"},
        json={"file_uuid": _SUMMARY_FILE},
    )
    assert response.status_code == 200
    assert response.json() == {}


def test_summary_state_success_and_failed(mock_aidp_server):
    client = _summary_client(mock_aidp_server)
    auth = {"Authorization": "Bearer mock-aidp-key"}
    path = (
        f"/KnowledgeBase/Tenants/aidp/KnowledgeBases/{_SUMMARY_KB}"
        "/KnowledgeFiles/Summary"
    )

    success = client.post(
        path, headers=auth, json={"file_uuid": _SUMMARY_FILE}
    ).json()
    assert success["summary_status"] == "success"
    assert success["summary_model"] == "qwen3"
    assert "年度报告.pdf" in success["summary_text"]

    failed = client.post(
        "/_mock/summary-status",
        json={
            "kds_id": _SUMMARY_KB,
            "file_uuid": _SUMMARY_FILE,
            "status": "failed",
        },
    )
    assert failed.status_code == 200
    failed_result = client.post(
        path, headers=auth, json={"file_uuid": _SUMMARY_FILE}
    ).json()
    assert failed_result["summary_status"] == "failed"
    assert "summary_text" not in failed_result
    assert failed_result["error_reason"].startswith("llm_failed:")


def test_summary_config_is_echoed_on_create(mock_aidp_server):
    client = TestClient(mock_aidp_server.app)
    auth = {"Authorization": "Bearer mock-aidp-key"}
    created = client.put(
        "/KnowledgeBase/Tenants/aidp/KnowledgeBases",
        headers=auth,
        json={
            "name": "摘要开关库",
            "description": "summary config",
            "embedding_model": "bge-m3",
            "summary_enable": True,
            "summary_model": "qwen3",
            "summary_preview": True,
        },
    )
    assert created.status_code == 200
    kds_id = created.json()["kds_id"]

    detail = client.get(
        f"/KnowledgeBase/Tenants/aidp/KnowledgeBases/{kds_id}", headers=auth
    ).json()
    assert detail["summary_enable"] is True
    assert detail["summary_model"] == "qwen3"
    assert detail["summary_preview"] is True
    config = json.loads(detail["kms_config_str"])
    assert config["summary_enable"] is True
    assert config["summary_preview"] is True


def test_summary_config_can_be_changed_via_kb_patch(mock_aidp_server):
    client = TestClient(mock_aidp_server.app)
    auth = {"Authorization": "Bearer mock-aidp-key"}
    created = client.put(
        "/KnowledgeBase/Tenants/aidp/KnowledgeBases",
        headers=auth,
        json={
            "name": "摘要可编辑库",
            "description": "summary patch",
            "embedding_model": "bge-m3",
            "summary_enable": True,
            "summary_model": "qwen3",
            "summary_preview": True,
        },
    ).json()
    kds_id = created["kds_id"]
    path = f"/KnowledgeBase/Tenants/aidp/KnowledgeBases/{kds_id}"

    off = client.patch(
        path,
        headers=auth,
        json={"summary_enable": False, "summary_preview": False},
    )
    assert off.status_code == 200
    detail = client.get(path, headers=auth).json()
    assert detail["summary_enable"] is False
    assert detail["summary_preview"] is False
    assert detail["summary_model"] == ""

    on = client.patch(
        path,
        headers=auth,
        json={"summary_enable": True, "summary_model": "qwen2.5", "summary_preview": False},
    )
    assert on.status_code == 200
    detail = client.get(path, headers=auth).json()
    assert detail["summary_enable"] is True
    assert detail["summary_model"] == "qwen2.5"
    assert detail["summary_preview"] is False
def test_kb_sensitive_intercept_round_trip(mock_aidp_server):
    client = TestClient(mock_aidp_server.app)
    headers = {"Authorization": "Bearer mock-aidp-key"}
    kb_path = "/KnowledgeBase/Tenants/aidp/KnowledgeBases"

    created = client.put(
        kb_path,
        headers=headers,
        json={
            "name": "敏感词开关",
            "description": "desc",
            "embedding_model": "bge-m3",
            "sensitive_intercept_enable": 0,
        },
    ).json()
    kds_id = created["kds_id"]
    assert created["sensitive_intercept_enable"] == 0

    detail = client.get(f"{kb_path}/{kds_id}", headers=headers).json()
    assert detail["sensitive_intercept_enable"] == 0

    updated = client.patch(
        f"{kb_path}/{kds_id}",
        headers=headers,
        json={"sensitive_intercept_enable": 1},
    ).json()
    assert updated["sensitive_intercept_enable"] == 1
    assert client.get(f"{kb_path}/{kds_id}", headers=headers).json()[
        "sensitive_intercept_enable"
    ] == 1


def test_sensitive_words_are_scoped_to_each_knowledge_base(mock_aidp_server):
    client = TestClient(mock_aidp_server.app)
    headers = {"Authorization": "Bearer mock-aidp-key"}
    kb1 = "/KnowledgeBase/Tenants/aidp/KnowledgeBases/aidp-kb-faq/SensitiveWords"
    kb2 = "/KnowledgeBase/Tenants/aidp/KnowledgeBases/aidp-kb-04/SensitiveWords"

    list1 = client.get(kb1, headers=headers, params={"page": 1, "page_size": 10}).json()
    list2 = client.get(kb2, headers=headers, params={"page": 1, "page_size": 10}).json()
    ids1 = {row["id"] for row in list1["value"]}
    ids2 = {row["id"] for row in list2["value"]}
    assert ids1 and ids2 and not (ids1 & ids2)
    assert list1["total_count"] == len(list1["value"])
    assert list2["total_count"] == len(list2["value"])
    assert "next_link" in list1

    # The same word may exist in two different knowledge bases.
    created1 = client.put(
        kb1,
        headers=headers,
        json={"word": "跨库词", "mode": "BLACK", "description": "kb1"},
    )
    assert created1.status_code == 201
    assert set(created1.json()) == {"id"}
    word_id = created1.json()["id"]

    created2 = client.put(
        kb2,
        headers=headers,
        json={"word": "跨库词", "mode": "BLACK", "description": "kb2"},
    )
    assert created2.status_code == 201

    duplicate = client.put(
        kb1,
        headers=headers,
        json={"word": "跨库词", "mode": "BLACK", "description": "dup"},
    )
    assert duplicate.status_code == 500
    assert duplicate.json()["error"]["code"] == 1022
    assert "knowledge base" in duplicate.json()["error"]["message"]

    # A word id from another knowledge base is not visible here.
    wrong_kb = client.get(f"{kb1}/{created2.json()['id']}", headers=headers)
    assert wrong_kb.status_code == 404
    assert wrong_kb.json()["error"]["code"] == 1004
    assert "not found in knowledge base" in wrong_kb.json()["error"]["message"]

    updated = client.patch(
        f"{kb1}/{word_id}",
        headers=headers,
        json={"mode": "WHITE", "description": "changed"},
    )
    assert updated.status_code == 200
    assert updated.json() == {}

    detail = client.get(f"{kb1}/{word_id}", headers=headers).json()["data"]
    assert detail["mode"] == "WHITE"
    assert detail["description"] == "changed"

    builtin = client.patch(
        f"{kb1}/sw-faq-builtin-black",
        headers=headers,
        json={"description": "不能改"},
    )
    assert builtin.status_code == 500
    assert builtin.json()["error"]["code"] == 1008
    assert "read-only" in builtin.json()["error"]["message"]

    filtered = client.get(
        kb1,
        headers=headers,
        params={
            "page": 1,
            "page_size": 2,
            "mode": "WHITE",
            "keyword": "跨库",
        },
    ).json()
    assert filtered["total_count"] == 1
    assert [row["id"] for row in filtered["value"]] == [word_id]
    assert filtered["next_link"] is None

    paged = client.get(
        kb1,
        headers=headers,
        params={"page": 1, "page_size": 2, "mode": "WHITE"},
    ).json()
    assert paged["next_link"]
    # The upstream next_link drops the active filters; Nexent must keep them.
    assert "mode=" not in paged["next_link"]
    assert "keyword=" not in paged["next_link"]

    deleted = client.delete(f"{kb1}/{word_id}", headers=headers)
    assert deleted.status_code == 204
    assert deleted.content == b""

    missing = client.get(f"{kb1}/{word_id}", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == 1004

    # Deleting the word in kb1 leaves the same word in kb2 untouched.
    still_there = client.get(
        f"{kb2}/{created2.json()['id']}", headers=headers
    )
    assert still_there.status_code == 200
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


def test_folder_move_conflict_uses_1092_and_merge_succeeds(mock_aidp_server):
    client = _folder_client(mock_aidp_server)
    headers = {"Authorization": "Bearer mock-aidp-key"}
    folders = "/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1/Folders"
    mock_aidp_server._FOLDERS_BY_KB["kb-1"].extend(
        [
            {"folder_path": "/mv_src", "create_time": 1},
            {"folder_path": "/mv_dst", "create_time": 1},
            {"folder_path": "/mv_src/dupe", "create_time": 1},
            {"folder_path": "/mv_dst/dupe", "create_time": 1},
        ]
    )
    source_id = mock_aidp_server._folder_id_for_path("/mv_src/dupe")
    target_id = mock_aidp_server._folder_id_for_path("/mv_dst")
    body = {
        "src_parent_folder_path": "/mv_src",
        "folder_name": "dupe",
        "target_parent_folder_path": "/mv_dst",
        "target_parent_folder_id": target_id,
        "merge_on_conflict": False,
    }

    conflict = client.post(
        f"{folders}/{source_id}/Move", headers=headers, json=body
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == 1092

    body["merge_on_conflict"] = True
    merged = client.post(
        f"{folders}/{source_id}/Move", headers=headers, json=body
    )
    assert merged.status_code == 200
    assert merged.json()["folder_path"] == "/mv_dst/dupe"


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


def test_batch_metadata_null_deletes_and_tags_overwrite(mock_aidp_server):
    server = mock_aidp_server
    server._KNOWLEDGE_BASES["14"] = {
        "kds_id": "14",
        "kds_name": "AIDP FAQ",
        "state": 4,
    }
    chunk = {
        "chunk_id": 1,
        "file_uuid": "f-1",
        "metadata_json": {"doc_type": "faq", "publish_year": "2026"},
        "tag": ["旧标签"],
    }
    server._DOCUMENT_CHUNKS_BY_KB["14"] = [chunk]
    client = TestClient(server.app)
    headers = {"Authorization": "Bearer mock-aidp-key"}
    url = (
        "/KnowledgeBase/Tenants/aidp/KnowledgeBases/14"
        "/Chunks/BatchMetadataJson"
    )

    deleted = client.patch(
        url,
        headers=headers,
        json={
            "od_id": 1,
            "metadata_json": {"doc_type": None},
            "chunk_id_list": [1],
        },
    )
    assert deleted.status_code == 200, deleted.text
    assert "doc_type" not in chunk["metadata_json"]
    assert chunk["metadata_json"]["publish_year"] == "2026"

    retagged = client.patch(
        url,
        headers=headers,
        json={"od_id": 1, "tag": ["新标签"], "chunk_id_list": [1]},
    )
    assert retagged.status_code == 200, retagged.text
    assert chunk["tag"] == ["新标签"]

    cleared = client.patch(
        url,
        headers=headers,
        json={"od_id": 1, "tag": [], "chunk_id_list": [1]},
    )
    assert cleared.status_code == 200, cleared.text
    assert chunk["tag"] == []

    missing_payload = client.patch(
        url,
        headers=headers,
        json={"od_id": 1, "chunk_id_list": [1]},
    )
    assert missing_payload.status_code == 400
