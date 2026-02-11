import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from sdk.nexent.vector_database import datamate_core


def test_parse_timestamp_variants():
    # None -> default
    assert datamate_core._parse_timestamp(None, default=7) == 7

    # Integer already in milliseconds
    ms = 1600000000000
    assert datamate_core._parse_timestamp(ms) == ms

    # Integer in seconds (less than 1e10) should be converted to ms
    seconds = 1600000000
    assert datamate_core._parse_timestamp(seconds) == seconds * 1000

    # ISO8601 string with Z
    iso = "2020-09-13T12:00:00Z"
    expected = int(datetime.fromisoformat(
        iso.replace("Z", "+00:00")).timestamp() * 1000)
    assert datamate_core._parse_timestamp(iso) == expected

    # Numeric string representing seconds
    assert datamate_core._parse_timestamp("123456") == 123456 * 1000

    # Invalid string -> default
    assert datamate_core._parse_timestamp("not-a-ts", default=11) == 11


@patch("sdk.nexent.vector_database.datamate_core.DataMateClient")
def test_user_indices_and_count(mock_client_cls):
    mock_client = MagicMock()
    mock_client.list_knowledge_bases.return_value = [
        {"id": 1, "type": "DOCUMENT"}, {"no_id": True}, {"id": "2", "type": "DOCUMENT"}]
    mock_client.get_knowledge_base_files.return_value = [
        {"fileName": "a"}, {"fileName": "b"}]
    mock_client_cls.return_value = mock_client

    core = datamate_core.DataMateCore(base_url="http://example")

    # get_user_indices filters out entries without id and returns string ids
    assert core.get_user_indices() == ["1", "2"]

    # check_index_exists uses get_user_indices
    assert core.check_index_exists("1") is True
    assert core.check_index_exists("missing") is False

    # get_index_chunks and count_documents rely on get_knowledge_base_files
    chunks = core.get_index_chunks("1")
    assert isinstance(chunks, dict)
    assert chunks["total"] == 2
    assert core.count_documents("1") == 2


@patch("sdk.nexent.vector_database.datamate_core.DataMateClient")
def test_hybrid_search_and_retrieve(mock_client_cls):
    mock_client = MagicMock()
    mock_client.retrieve_knowledge_base.return_value = [{"id": "res1"}]
    mock_client_cls.return_value = mock_client

    core = datamate_core.DataMateCore(base_url="http://example")
    res = core.hybrid_search(
        ["kb1"], "query", embedding_model=None, top_k=2, weight_accurate=0.1)
    assert res == [{"id": "res1"}]
    mock_client.retrieve_knowledge_base.assert_called_once_with("query", [
                                                                "kb1"], 2, 0.1)


@patch("sdk.nexent.vector_database.datamate_core.DataMateClient")
def test_get_documents_detail_parsing(mock_client_cls):
    mock_client = MagicMock()
    mock_client.get_knowledge_base_files.return_value = [
        {
            "path_or_url": "s3://bucket/file.txt",
            "fileName": "file.txt",
            "fileSize": 12345,
            "createdAt": "2021-01-01T00:00:00Z",
            "chunkCount": 3,
            "errMsg": "no error",
        }
    ]
    mock_client_cls.return_value = mock_client

    core = datamate_core.DataMateCore(base_url="http://example")
    details = core.get_documents_detail("kb1")
    assert isinstance(details, list) and len(details) == 1
    d = details[0]
    assert d["file"] == "file.txt"
    assert d["file_size"] == 12345
    assert d["chunk_count"] == 3
    assert isinstance(d["create_time"], int) and d["create_time"] > 0
    assert d["error_reason"] == "no error"


@patch("sdk.nexent.vector_database.datamate_core.DataMateClient")
def test_get_indices_detail_success_and_error(mock_client_cls):
    mock_client = MagicMock()

    def side_effect_get_info(kb_id):
        if kb_id == "bad":
            raise RuntimeError("boom")
        return {
            "fileCount": 10,
            "name": "KnowledgeBaseName",
            "chunkCount": 20,
            "storeSize": 999,
            "processSource": "Unstructured",
            "embedding": {"modelName": "embed-v1"},
            "createdAt": "2022-01-01T00:00:00Z",
            "updatedAt": "2022-02-01T00:00:00Z",
        }

    mock_client.get_knowledge_base_info.side_effect = side_effect_get_info
    mock_client_cls.return_value = mock_client

    core = datamate_core.DataMateCore(base_url="http://example")
    details, names = core.get_indices_detail(
        ["good", "bad"], embedding_dim=512)

    # success case
    assert "good" in details
    assert details["good"]["base_info"]["embedding_model"] == "embed-v1"
    assert details["good"]["base_info"]["embedding_dim"] == 512
    assert "KnowledgeBaseName" in names

    # error case
    assert "bad" in details
    assert "error" in details["bad"]


@patch("sdk.nexent.vector_database.datamate_core.DataMateClient")
def test_not_implemented_methods_raise(mock_client_cls):
    mock_client_cls.return_value = MagicMock()
    core = datamate_core.DataMateCore(base_url="http://example")

    # Methods that are intentionally not implemented should raise NotImplementedError
    with pytest.raises(NotImplementedError):
        core.create_index("i")
    with pytest.raises(NotImplementedError):
        core.delete_index("i")
    with pytest.raises(NotImplementedError):
        core.vectorize_documents("i", None, [])
    with pytest.raises(NotImplementedError):
        core.delete_documents("i", "path")
    with pytest.raises(NotImplementedError):
        core.create_chunk("i", {})
    with pytest.raises(NotImplementedError):
        core.update_chunk("i", "cid", {})
    with pytest.raises(NotImplementedError):
        core.delete_chunk("i", "cid")
    with pytest.raises(NotImplementedError):
        core.search("i", {})
    with pytest.raises(NotImplementedError):
        core.multi_search([], "i")
    with pytest.raises(NotImplementedError):
        core.accurate_search(["i"], "q")
    with pytest.raises(NotImplementedError):
        core.semantic_search(["i"], "q", None)


@patch("sdk.nexent.vector_database.datamate_core.DataMateClient")
def test_ssl_verification_parameter(mock_client_cls):
    """Test that DataMateCore passes SSL verification parameter to DataMateClient."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    # Test default SSL verification (should be True)
    core_default = datamate_core.DataMateCore(base_url="http://example")
    mock_client_cls.assert_called_with(
        base_url="http://example", timeout=5.0, verify_ssl=True
    )

    # Reset mock
    mock_client_cls.reset_mock()

    # Test explicit SSL verification enabled
    core_ssl_enabled = datamate_core.DataMateCore(
        base_url="http://example", verify_ssl=True
    )
    mock_client_cls.assert_called_with(
        base_url="http://example", timeout=5.0, verify_ssl=True
    )

    # Reset mock
    mock_client_cls.reset_mock()

    # Test SSL verification disabled
    core_ssl_disabled = datamate_core.DataMateCore(
        base_url="http://example", verify_ssl=False
    )
    mock_client_cls.assert_called_with(
        base_url="http://example", timeout=5.0, verify_ssl=False
    )

    # Reset mock
    mock_client_cls.reset_mock()

    # Test with custom timeout
    core_custom_timeout = datamate_core.DataMateCore(
        base_url="http://example", timeout=15.0, verify_ssl=False
    )
    mock_client_cls.assert_called_with(
        base_url="http://example", timeout=15.0, verify_ssl=False
    )
