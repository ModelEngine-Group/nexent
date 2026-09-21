"""Haotian fidelity: drive the real haotian adapter against the live mock."""
import asyncio

HAOTIAN_AUTH = {"Authorization": "Bearer mock-haotian-key"}
LIST_URL_PATH = "/haotian/api/knowledge-sets"
# Mirrors haotian_service._DEFAULT_KNOWLEDGE_BASE_ID: the product replaces a
# "null" dify_dataset_id with this UUID.
DEFAULT_KB_ID = "a8d68fbf-bd6e-5461-a9d1-cf1bb3522e38"


def test_knowledge_sets_normalize_null_dataset_id(mock_base_url, require_real_nexent):
    from services.haotian_service import fetch_haotian_knowledge_sets_impl

    result = asyncio.run(
        fetch_haotian_knowledge_sets_impl(
            list_url=f"{mock_base_url}{LIST_URL_PATH}",
            external_authorization="Bearer mock-haotian-key",
        )
    )
    sets = {s["name"]: s for s in result["knowledge_sets"]}
    assert set(sets) == {"军事知识集", "民用知识集"}

    military = sets["军事知识集"]
    ids = {kb["dify_dataset_id"] for kb in military["knowledge_bases"]}
    assert DEFAULT_KB_ID in ids   # the seeded "null" was replaced by the product
    assert "null" not in ids


def test_list_requires_authorization(http_client):
    assert http_client.get(LIST_URL_PATH).status_code == 401


def test_retrieve_returns_records_for_dataset_ids(http_client):
    payload = {
        "query": "equipment communication maintenance",
        "retrieval_model": {
            "search_method": "keyword_search",
            "top_k": 5,
            "reranking_enable": False,
            "weights": None,
            "score_threshold_enabled": False,
            "score_threshold": None,
        },
        "dataset_ids": ["ht-ds-001"],
    }
    response = http_client.post("/haotian/api/retrieve", headers=HAOTIAN_AUTH, json=payload)
    assert response.status_code == 200
    records = response.json()["records"]
    assert records

    top = records[0]
    assert top["segment"]["document"]["name"] == "装备手册-通信系统.pdf"
    assert "maintenance" in top["segment"]["content"].lower()
    assert top["metadata"]["dataset_id"] == "ht-ds-001"


def test_retrieve_via_default_dataset_id(http_client):
    # The product replaces "null" with DEFAULT_KB_ID before searching; chunks
    # seeded under that id keep the flow reachable end to end.
    payload = {"query": "default dataset", "retrieval_model": {"top_k": 5}, "dataset_ids": [DEFAULT_KB_ID]}
    response = http_client.post("/haotian/api/retrieve", headers=HAOTIAN_AUTH, json=payload)
    assert response.status_code == 200
    assert response.json()["records"]
