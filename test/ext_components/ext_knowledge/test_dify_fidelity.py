# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Dify fidelity: drive the real dify adapter against the live mock."""
import pytest

DIFY_AUTH = {"Authorization": "Bearer mock-dify-key"}


def test_datasets_listing_maps_seed_to_datamate_format(mock_base_url, require_real_nexent):
    from management.services.knowledge_base.providers.dify import fetch_dify_datasets_impl

    result = fetch_dify_datasets_impl(mock_base_url, "mock-dify-key")

    assert result["count"] == 6
    assert result["indices"][0] == "dify-ds-handbook"
    info = {item["name"]: item for item in result["indices_info"]}
    assert info["dify-ds-handbook"]["display_name"] == "Nexent Product Handbook"

    base_info = info["dify-ds-handbook"]["stats"]["base_info"]
    assert base_info["doc_count"] == 2
    assert base_info["process_source"] == "Dify"
    assert base_info["embedding_model"] == "bge-m3"
    assert base_info["creation_date"] == 1718000100 * 1000  # seconds -> ms

    # dify_service aggregates embedding_available from the last dataset.
    assert result["pagination"]["embedding_available"] is True


def test_datasets_401_maps_to_dify_auth_error(mock_base_url, http_client, require_real_nexent):
    from consts.error_code import ErrorCode
    from consts.exceptions import AppException
    from management.services.knowledge_base.providers.dify import fetch_dify_datasets_impl

    plan = http_client.post("/_mock/fail-next", json={"service": "dify", "count": 1, "status": 401})
    assert plan.status_code == 200

    with pytest.raises(AppException) as excinfo:
        fetch_dify_datasets_impl(mock_base_url, "mock-dify-key")
    assert getattr(excinfo.value, "error_code", None) == ErrorCode.DIFY_AUTH_ERROR


def test_datasets_require_bearer(http_client):
    assert http_client.get("/v1/datasets").status_code == 401


def test_retrieve_returns_records_in_dify_shape(http_client):
    response = http_client.post(
        "/datasets/dify-ds-handbook/retrieve",
        headers=DIFY_AUTH,
        json={
            "query": "retrieval overview datasets",
            "retrieval_model": {"search_method": "hybrid_search", "top_k": 2, "reranking_enable": False},
        },
    )
    assert response.status_code == 200
    records = response.json()["records"]
    assert records, "expected seeded chunks to match the query"

    top = records[0]
    assert top["segment"]["document"]["id"] == "doc-handbook-001"
    assert top["segment"]["content"]
    assert isinstance(top["score"], float)
    # Base score 0.92 plus a term boost for a matching query.
    assert top["score"] >= 0.92


def test_empty_datasets_are_marked_and_honest(http_client):
    # Datasets without retrieval chunks carry a （空库） marker and honest
    # zero document counts; content datasets lead the list. Querying a
    # marked dataset returns no records (the product tool then raises
    # "No results found!" by design).
    datasets = http_client.get("/v1/datasets", headers=DIFY_AUTH).json()["data"]

    assert datasets[0]["id"] == "dify-ds-handbook"
    assert datasets[1]["id"] == "dify-ds-faq"

    content_ids = {"dify-ds-handbook", "dify-ds-faq"}
    for ds in datasets:
        if "（空库）" in ds["name"]:
            assert ds["id"] not in content_ids
            assert ds["document_count"] == 0, ds["id"]
            response = http_client.post(
                f"/datasets/{ds['id']}/retrieve",
                headers=DIFY_AUTH,
                json={"query": "anything", "retrieval_model": {"top_k": 5}},
            )
            assert response.status_code == 200
            assert response.json()["records"] == []
        else:
            assert ds["id"] in content_ids
            assert ds["document_count"] >= 1


def test_retrieve_answers_both_path_conventions(http_client):
    payload = {"query": "faq", "retrieval_model": {"top_k": 5}}
    without_v1 = http_client.post("/datasets/dify-ds-faq/retrieve", headers=DIFY_AUTH, json=payload)
    with_v1 = http_client.post("/v1/datasets/dify-ds-faq/retrieve", headers=DIFY_AUTH, json=payload)
    assert without_v1.status_code == 200
    assert with_v1.status_code == 200
    assert without_v1.json()["records"] == with_v1.json()["records"]


def test_upload_file_hands_out_reachable_download_url(http_client):
    response = http_client.get(
        "/datasets/dify-ds-handbook/documents/doc-handbook-001/upload-file",
        headers=DIFY_AUTH,
    )
    assert response.status_code == 200
    download_url = response.json()["download_url"]
    # Self-referential: derived from the request's own host.
    assert "/files/doc-handbook-001" in download_url

    downloaded = http_client.get(download_url, headers=DIFY_AUTH)
    assert downloaded.status_code == 200
    assert "Mock Dify file content" in downloaded.text
    assert "attachment" in downloaded.headers["content-disposition"]


def test_upload_file_unknown_document_404(http_client):
    response = http_client.get(
        "/datasets/dify-ds-handbook/documents/missing-doc/upload-file",
        headers=DIFY_AUTH,
    )
    assert response.status_code == 404
