"""RAGFlow fidelity: drive the real ragflow adapter against the live mock."""

RAGFLOW_AUTH = {"Authorization": "Bearer mock-ragflow-key"}


def test_datasets_listing_formats_seed(mock_base_url, require_real_nexent):
    from services.ragflow_service import fetch_ragflow_datasets_impl

    result = fetch_ragflow_datasets_impl(f"{mock_base_url}/ragflow", "mock-ragflow-key")
    datasets = {ds["id"]: ds for ds in result["data"]}
    assert len(datasets) == 5

    main = datasets["ragflow-ds-main"]
    assert main["doc_count"] == 25        # mapped from doc_num
    assert main["chunk_count"] == 3100    # mapped from chunk_num
    assert main["create_time"] == "2024-05-01 10:00:00"


def test_search_returns_code_zero_with_sorted_chunks(http_client):
    payload = {
        "question": "ragflow retrieval similarity",
        "top_k": 5,
        "similarity_threshold": 0.0,
        "vector_similarity_weight": 0.3,
        "use_kg": False,
        "keyword": "",
        "highlight": False,
        "dataset_ids": ["ragflow-ds-main", "ragflow-ds-faq"],
    }
    response = http_client.post("/ragflow/api/v1/datasets/search", headers=RAGFLOW_AUTH, json=payload)
    assert response.status_code == 200

    body = response.json()
    assert body["code"] == 0
    chunks = body["data"]["chunks"]
    assert chunks

    similarities = [chunk["similarity"] for chunk in chunks]
    assert similarities == sorted(similarities, reverse=True)

    top = chunks[0]
    assert top["docnm_kwd"] == "ragflow-overview.md"
    assert top["content_with_weight"]
    assert "term_similarity" in top and "vector_similarity" in top


def test_datasets_require_bearer(http_client):
    assert http_client.get("/ragflow/api/v1/datasets").status_code == 401
