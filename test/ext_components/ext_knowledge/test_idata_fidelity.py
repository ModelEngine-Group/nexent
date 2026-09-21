"""iData fidelity: drive the real idata adapter against the live mock."""

IDATA_AUTH = {"Authorization": "Bearer mock-idata-key"}
RETRIEVALS_PATH = "/idata/apiaccess/modelmate/north/machine/v1/retrievals"


def test_knowledge_spaces_listing(mock_base_url, require_real_nexent):
    from services.idata_service import fetch_idata_knowledge_spaces_impl

    spaces = fetch_idata_knowledge_spaces_impl(
        f"{mock_base_url}/idata", "mock-idata-key", "user-001"
    )
    assert spaces == [
        {"id": "space-alpha", "name": "Alpha Knowledge Space"},
        {"id": "space-beta", "name": "Beta 知识空间"},
    ]


def test_datasets_listing_maps_file_count(mock_base_url, require_real_nexent):
    from services.idata_service import fetch_idata_datasets_impl

    result = fetch_idata_datasets_impl(
        f"{mock_base_url}/idata", "mock-idata-key", "user-001", "space-alpha"
    )
    assert result["count"] == 2
    info = {item["name"]: item for item in result["indices_info"]}
    assert info["idata-kb-alpha-1"]["display_name"] == "设备维护手册"
    assert info["idata-kb-alpha-1"]["stats"]["base_info"]["doc_count"] == 7
    assert info["idata-kb-alpha-1"]["stats"]["base_info"]["process_source"] == "iData"


def test_retrievals_response_shape(http_client):
    payload = {
        "userId": "user-001",
        "knowledgeBaseFilter": [{"knowledgeBaseId": "idata-kb-alpha-1", "metas": []}],
        "question": "设备维护 周期",
        "rankTopN": 5,
        "rerankModelId": "",
        "similarityThreshold": 0.2,
        "keywordSimilarityWeight": 0.5,
        "vectorSimilarityWeight": 0.5,
    }
    response = http_client.post(RETRIEVALS_PATH, headers=IDATA_AUTH, json=payload)
    assert response.status_code == 200

    body = response.json()
    assert body["code"] == "1"
    chunks = body["data"]["retrievalData"][0]["chunks"]
    assert chunks
    assert chunks[0]["documentId"] == "idoc-001"
    assert "维护" in chunks[0]["content"]
    assert isinstance(chunks[0]["createTime"], int)  # milliseconds
    assert "reRankScore" in chunks[0] and "vsScore" in chunks[0] and "esScore" in chunks[0]


def test_documents_download_serves_built_url(http_client):
    response = http_client.get(
        "/idata/apiaccess/modelmate/north/machine/v1/documents/download",
        params={
            "userId": "user-001",
            "knowledgeBaseId": "idata-kb-alpha-1",
            "documentId": "idoc-001",
        },
        headers=IDATA_AUTH,
    )
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment")


def test_queries_require_bearer(http_client):
    assert (
        http_client.post(
            RETRIEVALS_PATH, json={"userId": "user-001", "question": "x"}
        ).status_code
        == 401
    )
