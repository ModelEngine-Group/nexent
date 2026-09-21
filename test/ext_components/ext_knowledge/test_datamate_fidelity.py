"""DataMate fidelity: drive the real SDK client against the live mock."""
import json
from urllib.parse import quote

import pytest


@pytest.fixture()
def datamate_client(mock_base_url, require_real_nexent):
    from nexent.datamate.datamate_client import DataMateClient

    return DataMateClient(base_url=f"{mock_base_url}/datamate", timeout=10.0)


def test_list_autopaginates_across_pages(datamate_client):
    # 22 seeded KBs with the client's default page size of 20 -> 2 pages.
    kbs = datamate_client.list_knowledge_bases()
    assert len(kbs) == 22
    ids = {kb["id"] for kb in kbs}
    assert "datamate-kb-001" in ids
    assert "datamate-kb-021" in ids
    assert "datamate-kb-graph" in ids


def test_get_user_indices_filters_document_type(mock_base_url, require_real_nexent):
    from nexent.vector_database.datamate_core import DataMateCore

    core = DataMateCore(base_url=f"{mock_base_url}/datamate", timeout=10.0)
    indices = core.get_user_indices()
    assert len(indices) == 21
    assert "datamate-kb-graph" not in indices


def test_files_listing_returns_seed_fields(datamate_client):
    files = datamate_client.get_knowledge_base_files("datamate-kb-001")
    assert len(files) == 3

    by_id = {f["fileId"]: f for f in files}
    assert by_id["f-001"]["fileName"] == "运行手册.pdf"
    assert by_id["f-001"]["errMsg"] == ""
    # A seeded failure row keeps the error path testable.
    assert by_id["f-003"]["errMsg"].startswith("parse failed")


def test_kb_info_fields(datamate_client):
    info = datamate_client.get_knowledge_base_info("datamate-kb-001")
    assert info["fileCount"] == 3
    assert info["name"] == "运行手册知识库"
    assert info["embedding"]["modelName"] == "bge-m3"
    assert info["processSource"] == "Unstructured"


def test_unknown_kb_info_raises_runtime_error(datamate_client):
    with pytest.raises(RuntimeError):
        datamate_client.get_knowledge_base_info("datamate-kb-unknown")


def test_retrieve_entity_shape(datamate_client):
    results = datamate_client.retrieve_knowledge_base(
        "runbook restart redis queue", ["datamate-kb-001"], top_k=5, threshold=0.2
    )
    assert results
    entity = results[0]["entity"]
    assert "runbook" in entity["text"].lower()

    # entity.metadata is a JSON *string* in the real DataMate payload.
    metadata = json.loads(entity["metadata"])
    assert metadata["absolute_directory_path"].endswith("datamate-kb-001")
    assert metadata["original_file_id"] == "f-001"
    assert metadata["file_name"] == "运行手册.pdf"
    assert entity["scoreDetails"]["vsScore"] == pytest.approx(0.82)
    assert entity["score"] >= 0.9  # base 0.9 + term boost


def test_download_url_roundtrip(datamate_client, http_client):
    url = datamate_client.build_file_download_url("datamate-kb-001", "f-001")
    assert url.endswith(
        "/datamate/api/data-management/datasets/datamate-kb-001/files/f-001/download"
    )

    response = http_client.get(url)
    assert response.status_code == 200
    assert "Mock DataMate content" in response.text
    disposition = response.headers.get("content-disposition", "")
    assert disposition.startswith("attachment")
    assert quote("运行手册.pdf") in disposition


def test_download_unknown_file_404(http_client):
    response = http_client.get(
        "/datamate/api/data-management/datasets/datamate-kb-001/files/missing/download"
    )
    assert response.status_code == 404
