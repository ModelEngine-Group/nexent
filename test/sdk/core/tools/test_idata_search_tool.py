import json
from datetime import datetime
from unittest.mock import ANY, MagicMock, patch

import httpx
import pytest
from pytest_mock import MockFixture

from sdk.nexent.core.tools.idata_search_tool import IdataSearchTool
from sdk.nexent.core.utils.observer import MessageObserver, ProcessType


@pytest.fixture
def mock_observer() -> MessageObserver:
    """Create a mock observer for testing"""
    observer = MagicMock(spec=MessageObserver)
    observer.lang = "en"
    return observer


@pytest.fixture
def idata_tool(mock_observer: MessageObserver) -> IdataSearchTool:
    """Create IdataSearchTool instance for testing"""
    with patch("sdk.nexent.core.tools.idata_search_tool.http_client_manager") as mock_manager:
        mock_client = MagicMock()
        mock_manager.get_sync_client.return_value = mock_client
        tool = IdataSearchTool(
            server_url="https://api.idata.example.com",
            api_key="test_api_key",
            user_id="test_user_id",
            knowledge_space_id="test_knowledge_space_id",
            dataset_ids='["kb1", "kb2"]',
            rerank_model_id="test_rerank_model_id",
            top_k=5,
            similarity_threshold=0.5,
            keyword_similarity_weight=0.1,
            vector_similarity_weight=0.3,
            observer=mock_observer,
        )
        # Store the mock client for tests to use
        tool._mock_http_client = mock_client
        return tool


def _build_search_response(chunks=None, retrieval_data_count=1):
    """Helper function to build mock search response"""
    if chunks is None:
        chunks = [
            {
                "documentId": "doc1",
                "documentName": "document1.txt",
                "content": "test content 1",
                "datasetId": "kb1",
                "createTime": 1609459200000,  # 2021-01-01 00:00:00 in milliseconds
                "reRankScore": 0.9,
                "vsScore": 0.8,
                "esScore": 0.7,
                "title": "Test Document 1"
            },
            {
                "documentId": "doc2",
                "documentName": "document2.txt",
                "content": "test content 2",
                "datasetId": "kb2",
                "createTime": 1609545600000,  # 2021-01-02 00:00:00 in milliseconds
                "reRankScore": 0.85,
                "vsScore": 0.75,
                "esScore": 0.65,
                "title": "Test Document 2"
            }
        ]

    retrieval_data = []
    for i in range(retrieval_data_count):
        retrieval_data.append({"chunks": chunks})

    return {
        "code": "1",
        "msg": "success",
        "data": {
            "retrievalData": retrieval_data
        }
    }


class TestIdataSearchToolInit:
    """Test IdataSearchTool initialization"""

    def test_init_success(self, mock_observer: MessageObserver):
        """Test successful initialization with all parameters"""
        with patch("sdk.nexent.core.tools.idata_search_tool.http_client_manager") as mock_manager:
            mock_client = MagicMock()
            mock_manager.get_sync_client.return_value = mock_client

            tool = IdataSearchTool(
                server_url="https://api.idata.example.com",
                api_key="test_api_key",
                user_id="test_user_id",
                knowledge_space_id="test_knowledge_space_id",
                dataset_ids='["kb1", "kb2"]',
                rerank_model_id="test_rerank_model_id",
                top_k=10,
                similarity_threshold=0.6,
                keyword_similarity_weight=0.15,
                vector_similarity_weight=0.35,
                observer=mock_observer,
            )

            assert tool.server_url == "https://api.idata.example.com"
            assert tool.api_key == "test_api_key"
            assert tool.user_id == "test_user_id"
            assert tool.knowledge_space_id == "test_knowledge_space_id"
            assert tool.dataset_ids == ["kb1", "kb2"]
            assert tool.rerank_model_id == "test_rerank_model_id"
            assert tool.top_k == 10
            assert tool.similarity_threshold == 0.6
            assert tool.keyword_similarity_weight == 0.15
            assert tool.vector_similarity_weight == 0.35
            assert tool.observer == mock_observer
            assert tool.record_ops == 1
            assert tool.running_prompt_zh == "iData知识库检索中..."
            assert tool.running_prompt_en == "Searching iData knowledge base..."

    def test_init_server_url_trailing_slash(self, mock_observer: MessageObserver):
        """Test that trailing slash is stripped from server_url"""
        with patch("sdk.nexent.core.tools.idata_search_tool.http_client_manager") as mock_manager:
            mock_client = MagicMock()
            mock_manager.get_sync_client.return_value = mock_client

            tool = IdataSearchTool(
                server_url="https://api.idata.example.com/",
                api_key="test_api_key",
                user_id="test_user_id",
                knowledge_space_id="test_knowledge_space_id",
                dataset_ids='["kb1"]',
                rerank_model_id="test_rerank_model_id",
                observer=mock_observer,
            )

            assert tool.server_url == "https://api.idata.example.com"

    def test_init_default_values(self, mock_observer: MessageObserver):
        """Test initialization with default values"""
        with patch("sdk.nexent.core.tools.idata_search_tool.http_client_manager") as mock_manager:
            mock_client = MagicMock()
            mock_manager.get_sync_client.return_value = mock_client

            # Pass default values explicitly to test they are accepted
            tool = IdataSearchTool(
                server_url="https://api.idata.example.com",
                api_key="test_api_key",
                user_id="test_user_id",
                knowledge_space_id="test_knowledge_space_id",
                dataset_ids='["kb1"]',
                rerank_model_id="test_rerank_model_id",
                top_k=10,  # Explicitly pass default value
                similarity_threshold=-10.0,  # Explicitly pass default value
                keyword_similarity_weight=0.10,  # Explicitly pass default value
                vector_similarity_weight=0.3,  # Explicitly pass default value
                observer=mock_observer,
            )

            assert tool.top_k == 10  # Default value
            assert tool.similarity_threshold == -10.0  # Default value
            assert tool.keyword_similarity_weight == 0.10  # Default value
            assert tool.vector_similarity_weight == 0.3  # Default value

    @pytest.mark.parametrize("server_url,expected_error", [
        ("", "server_url is required and must be a non-empty string"),
        (None, "server_url is required and must be a non-empty string"),
    ])
    def test_init_invalid_server_url(self, server_url, expected_error, mock_observer: MessageObserver):
        """Test initialization with invalid server_url"""
        with pytest.raises(ValueError) as excinfo:
            IdataSearchTool(
                server_url=server_url,
                api_key="test_api_key",
                user_id="test_user_id",
                knowledge_space_id="test_knowledge_space_id",
                dataset_ids='["kb1"]',
                rerank_model_id="test_rerank_model_id",
                observer=mock_observer,
            )
        assert expected_error in str(excinfo.value)

    @pytest.mark.parametrize("api_key,expected_error", [
        ("", "api_key is required and must be a non-empty string"),
        (None, "api_key is required and must be a non-empty string"),
    ])
    def test_init_invalid_api_key(self, api_key, expected_error, mock_observer: MessageObserver):
        """Test initialization with invalid api_key"""
        with pytest.raises(ValueError) as excinfo:
            IdataSearchTool(
                server_url="https://api.idata.example.com",
                api_key=api_key,
                user_id="test_user_id",
                knowledge_space_id="test_knowledge_space_id",
                dataset_ids='["kb1"]',
                rerank_model_id="test_rerank_model_id",
                observer=mock_observer,
            )
        assert expected_error in str(excinfo.value)

    @pytest.mark.parametrize("user_id,expected_error", [
        ("", "user_id is required and must be a non-empty string"),
        (None, "user_id is required and must be a non-empty string"),
    ])
    def test_init_invalid_user_id(self, user_id, expected_error, mock_observer: MessageObserver):
        """Test initialization with invalid user_id"""
        with pytest.raises(ValueError) as excinfo:
            IdataSearchTool(
                server_url="https://api.idata.example.com",
                api_key="test_api_key",
                user_id=user_id,
                knowledge_space_id="test_knowledge_space_id",
                dataset_ids='["kb1"]',
                rerank_model_id="test_rerank_model_id",
                observer=mock_observer,
            )
        assert expected_error in str(excinfo.value)

    @pytest.mark.parametrize("knowledge_space_id,expected_error", [
        ("", "knowledge_space_id is required and must be a non-empty string"),
        (None, "knowledge_space_id is required and must be a non-empty string"),
    ])
    def test_init_invalid_knowledge_space_id(self, knowledge_space_id, expected_error, mock_observer: MessageObserver):
        """Test initialization with invalid knowledge_space_id"""
        with pytest.raises(ValueError) as excinfo:
            IdataSearchTool(
                server_url="https://api.idata.example.com",
                api_key="test_api_key",
                user_id="test_user_id",
                knowledge_space_id=knowledge_space_id,
                dataset_ids='["kb1"]',
                rerank_model_id="test_rerank_model_id",
                observer=mock_observer,
            )
        assert expected_error in str(excinfo.value)

    @pytest.mark.parametrize("rerank_model_id,expected_error", [
        ("", "rerank_model_id is required and must be a non-empty string"),
        (None, "rerank_model_id is required and must be a non-empty string"),
    ])
    def test_init_invalid_rerank_model_id(self, rerank_model_id, expected_error, mock_observer: MessageObserver):
        """Test initialization with invalid rerank_model_id"""
        with pytest.raises(ValueError) as excinfo:
            IdataSearchTool(
                server_url="https://api.idata.example.com",
                api_key="test_api_key",
                user_id="test_user_id",
                knowledge_space_id="test_knowledge_space_id",
                dataset_ids='["kb1"]',
                rerank_model_id=rerank_model_id,
                observer=mock_observer,
            )
        assert expected_error in str(excinfo.value)

    @pytest.mark.parametrize("dataset_ids,expected_error", [
        ([], "dataset_ids is required and must be a non-empty JSON string array or list"),
        ("", "dataset_ids is required and must be a non-empty JSON string array or list"),
        (None, "dataset_ids is required and must be a non-empty JSON string array or list"),
        ("[]", "dataset_ids must be a non-empty array of strings"),
    ])
    def test_init_invalid_dataset_ids(self, dataset_ids, expected_error, mock_observer: MessageObserver):
        """Test initialization with invalid dataset_ids"""
        with pytest.raises(ValueError) as excinfo:
            IdataSearchTool(
                server_url="https://api.idata.example.com",
                api_key="test_api_key",
                user_id="test_user_id",
                knowledge_space_id="test_knowledge_space_id",
                dataset_ids=dataset_ids,
                rerank_model_id="test_rerank_model_id",
                observer=mock_observer,
            )
        assert expected_error in str(excinfo.value)

    def test_init_dataset_ids_as_list(self, mock_observer: MessageObserver):
        """Test dataset_ids can be passed as a Python list"""
        with patch("sdk.nexent.core.tools.idata_search_tool.http_client_manager") as mock_manager:
            mock_client = MagicMock()
            mock_manager.get_sync_client.return_value = mock_client

            tool = IdataSearchTool(
                server_url="https://api.idata.example.com",
                api_key="test_api_key",
                user_id="test_user_id",
                knowledge_space_id="test_knowledge_space_id",
                dataset_ids=["kb1", "kb2", "kb3"],
                rerank_model_id="test_rerank_model_id",
                observer=mock_observer,
            )

            assert tool.dataset_ids == ["kb1", "kb2", "kb3"]

    def test_init_dataset_ids_as_list_with_numeric_ids(self, mock_observer: MessageObserver):
        """Test dataset_ids list with numeric IDs are converted to strings"""
        with patch("sdk.nexent.core.tools.idata_search_tool.http_client_manager") as mock_manager:
            mock_client = MagicMock()
            mock_manager.get_sync_client.return_value = mock_client

            tool = IdataSearchTool(
                server_url="https://api.idata.example.com",
                api_key="test_api_key",
                user_id="test_user_id",
                knowledge_space_id="test_knowledge_space_id",
                dataset_ids=[123, 456, 789],
                rerank_model_id="test_rerank_model_id",
                observer=mock_observer,
            )

            assert tool.dataset_ids == ["123", "456", "789"]
            assert all(isinstance(id, str) for id in tool.dataset_ids)

    @pytest.mark.parametrize("invalid_json,expected_error_contains", [
        ("invalid_json", "dataset_ids must be a valid JSON string array or list"),
        ("{key: value}", "dataset_ids must be a valid JSON string array or list"),
        ("123", "dataset_ids must be a non-empty array of strings"),
    ])
    def test_init_invalid_json_format(self, invalid_json, expected_error_contains, mock_observer: MessageObserver):
        """Test dataset_ids with invalid JSON format"""
        with pytest.raises(ValueError) as excinfo:
            IdataSearchTool(
                server_url="https://api.idata.example.com",
                api_key="test_api_key",
                user_id="test_user_id",
                knowledge_space_id="test_knowledge_space_id",
                dataset_ids=invalid_json,
                rerank_model_id="test_rerank_model_id",
                observer=mock_observer,
            )
        assert expected_error_contains in str(excinfo.value)

    def test_init_dataset_ids_malformed_json(self, mock_observer: MessageObserver):
        """Test dataset_ids with malformed JSON array"""
        with pytest.raises(ValueError) as excinfo:
            IdataSearchTool(
                server_url="https://api.idata.example.com",
                api_key="test_api_key",
                user_id="test_user_id",
                knowledge_space_id="test_knowledge_space_id",
                dataset_ids='["kb1", "kb2"',  # Missing closing bracket
                rerank_model_id="test_rerank_model_id",
                observer=mock_observer,
            )
        assert "dataset_ids must be a valid JSON string array or list" in str(excinfo.value)


class TestBuildDownloadUrl:
    """Test _build_download_url method"""

    def test_build_download_url_success(self, idata_tool: IdataSearchTool):
        """Test successful download URL building"""
        url = idata_tool._build_download_url("doc1", "kb1")

        expected_url = (
            "https://api.idata.example.com/apiaccess/modelmate/north/machine/v1/documents/download?"
            "userId=test_user_id&knowledgeBaseId=kb1&documentId=doc1"
        )
        assert url == expected_url

    def test_build_download_url_empty_document_id(self, idata_tool: IdataSearchTool):
        """Test download URL building with empty document_id"""
        url = idata_tool._build_download_url("", "kb1")
        assert url == ""

    def test_build_download_url_empty_dataset_id_uses_first(self, idata_tool: IdataSearchTool):
        """Test download URL building with empty dataset_id uses first from dataset_ids"""
        url = idata_tool._build_download_url("doc1", "")

        expected_url = (
            "https://api.idata.example.com/apiaccess/modelmate/north/machine/v1/documents/download?"
            "userId=test_user_id&knowledgeBaseId=kb1&documentId=doc1"
        )
        assert url == expected_url

    def test_build_download_url_both_empty(self, idata_tool: IdataSearchTool):
        """Test download URL building with both document_id and dataset_id empty"""
        url = idata_tool._build_download_url("", "")
        assert url == ""

    def test_build_download_url_no_dataset_ids(self, mock_observer: MessageObserver):
        """Test download URL building when dataset_ids is empty"""
        with patch("sdk.nexent.core.tools.idata_search_tool.http_client_manager") as mock_manager:
            mock_client = MagicMock()
            mock_manager.get_sync_client.return_value = mock_client

            tool = IdataSearchTool(
                server_url="https://api.idata.example.com",
                api_key="test_api_key",
                user_id="test_user_id",
                knowledge_space_id="test_knowledge_space_id",
                dataset_ids='["kb1"]',
                rerank_model_id="test_rerank_model_id",
                observer=mock_observer,
            )
            # Manually set dataset_ids to empty to test edge case
            tool.dataset_ids = []

            url = tool._build_download_url("doc1", "")
            assert url == ""


class TestSearchIdataKnowledgeBase:
    """Test _search_idata_knowledge_base method"""

    def test_search_idata_knowledge_base_success(self, idata_tool: IdataSearchTool):
        """Test successful search"""
        mock_response = MagicMock()
        mock_response.json.return_value = _build_search_response()
        mock_response.raise_for_status = MagicMock()
        idata_tool._mock_http_client.post.return_value = mock_response

        payload = {
            "userId": "test_user_id",
            "knowledgeBaseFilter": [{"knowledgeBaseId": "kb1", "metas": []}],
            "question": "test query",
            "rankTopN": 5,
            "rerankModelId": "test_rerank_model_id",
            "similarityThreshold": 0.5,
            "keywordSimilarityWeight": 0.1,
            "vectorSimilarityWeight": 0.3
        }

        result = idata_tool._search_idata_knowledge_base(payload)

        assert result["code"] == "1"
        assert "data" in result
        assert "retrievalData" in result["data"]

        idata_tool._mock_http_client.post.assert_called_once_with(
            "https://api.idata.example.com/apiaccess/modelmate/north/machine/v1/retrievals",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer test_api_key"
            },
            json=payload
        )

    def test_search_idata_knowledge_base_request_error(self, idata_tool: IdataSearchTool):
        """Test search with RequestError"""
        idata_tool._mock_http_client.post.side_effect = httpx.RequestError(
            "Connection error", request=MagicMock()
        )

        payload = {"userId": "test_user_id", "question": "test query"}

        with pytest.raises(Exception) as excinfo:
            idata_tool._search_idata_knowledge_base(payload)

        assert "iData API request failed" in str(excinfo.value)

    def test_search_idata_knowledge_base_http_status_error(self, idata_tool: IdataSearchTool):
        """Test search with HTTPStatusError"""
        idata_tool._mock_http_client.post.side_effect = httpx.HTTPStatusError(
            "HTTP error", request=MagicMock(), response=MagicMock()
        )

        payload = {"userId": "test_user_id", "question": "test query"}

        with pytest.raises(Exception) as excinfo:
            idata_tool._search_idata_knowledge_base(payload)

        assert "iData API HTTP error" in str(excinfo.value)

    def test_search_idata_knowledge_base_json_decode_error(self, idata_tool: IdataSearchTool):
        """Test search with JSONDecodeError"""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)
        idata_tool._mock_http_client.post.return_value = mock_response

        payload = {"userId": "test_user_id", "question": "test query"}

        with pytest.raises(Exception) as excinfo:
            idata_tool._search_idata_knowledge_base(payload)

        assert "Failed to parse iData API response" in str(excinfo.value)

    def test_search_idata_knowledge_base_invalid_code(self, idata_tool: IdataSearchTool):
        """Test search with invalid response code"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": "0",
            "msg": "Error message"
        }
        mock_response.raise_for_status = MagicMock()
        idata_tool._mock_http_client.post.return_value = mock_response

        payload = {"userId": "test_user_id", "question": "test query"}

        with pytest.raises(Exception) as excinfo:
            idata_tool._search_idata_knowledge_base(payload)

        assert "iData API error: Error message" in str(excinfo.value)

    def test_search_idata_knowledge_base_missing_data_key(self, idata_tool: IdataSearchTool):
        """Test search with missing 'data' key in response"""
        mock_response = MagicMock()
        mock_response.json.return_value = {"code": "1", "msg": "success"}
        mock_response.raise_for_status = MagicMock()
        idata_tool._mock_http_client.post.return_value = mock_response

        payload = {"userId": "test_user_id", "question": "test query"}

        with pytest.raises(Exception) as excinfo:
            idata_tool._search_idata_knowledge_base(payload)

        assert "Unexpected iData API response format: missing 'data' key" in str(excinfo.value)

    def test_search_idata_knowledge_base_missing_retrieval_data_key(self, idata_tool: IdataSearchTool):
        """Test search with missing 'retrievalData' key in response"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": "1",
            "data": {}
        }
        mock_response.raise_for_status = MagicMock()
        idata_tool._mock_http_client.post.return_value = mock_response

        payload = {"userId": "test_user_id", "question": "test query"}

        with pytest.raises(Exception) as excinfo:
            idata_tool._search_idata_knowledge_base(payload)

        assert "Unexpected iData API response format: missing 'retrievalData' key" in str(excinfo.value)


class TestForward:
    """Test forward method"""

    def _setup_success_flow(self, tool: IdataSearchTool, chunks=None):
        """Helper to set up successful search flow"""
        search_response = _build_search_response(chunks=chunks)
        mock_response = MagicMock()
        mock_response.json.return_value = search_response
        mock_response.raise_for_status = MagicMock()
        tool._mock_http_client.post.return_value = mock_response

    def test_forward_success_with_observer_en(self, idata_tool: IdataSearchTool):
        """Test successful forward with English observer"""
        self._setup_success_flow(idata_tool)

        result_json = idata_tool.forward("test query")
        results = json.loads(result_json)

        assert len(results) == 2
        assert results[0]["title"] == "Test Document 1"
        assert results[0]["text"] == "test content 1"
        assert results[1]["title"] == "Test Document 2"
        assert results[1]["text"] == "test content 2"

        # Verify observer messages
        idata_tool.observer.add_message.assert_any_call(
            "", ProcessType.TOOL, idata_tool.running_prompt_en
        )
        idata_tool.observer.add_message.assert_any_call(
            "", ProcessType.CARD, json.dumps([{"icon": "search", "text": "test query"}], ensure_ascii=False)
        )
        idata_tool.observer.add_message.assert_any_call(
            "", ProcessType.SEARCH_CONTENT, ANY
        )

        assert idata_tool.record_ops == 3  # 1 + len(results)

    def test_forward_success_with_observer_zh(self, idata_tool: IdataSearchTool):
        """Test successful forward with Chinese observer"""
        idata_tool.observer.lang = "zh"
        self._setup_success_flow(idata_tool)

        idata_tool.forward("测试查询")

        idata_tool.observer.add_message.assert_any_call(
            "", ProcessType.TOOL, idata_tool.running_prompt_zh
        )

    def test_forward_no_observer(self, mock_observer: MessageObserver):
        """Test forward without observer"""
        with patch("sdk.nexent.core.tools.idata_search_tool.http_client_manager") as mock_manager:
            mock_client = MagicMock()
            mock_manager.get_sync_client.return_value = mock_client

            tool = IdataSearchTool(
                server_url="https://api.idata.example.com",
                api_key="test_api_key",
                user_id="test_user_id",
                knowledge_space_id="test_knowledge_space_id",
                dataset_ids='["kb1"]',
                rerank_model_id="test_rerank_model_id",
                observer=None,
            )
            tool._mock_http_client = mock_client

            search_response = _build_search_response(chunks=[{
                "documentId": "doc1",
                "documentName": "doc1.txt",
                "content": "content",
                "datasetId": "kb1",
                "createTime": 1609459200000,
                "reRankScore": 0.9,
                "vsScore": 0.8,
                "esScore": 0.7,
                "title": "Doc 1"
            }])

            mock_response = MagicMock()
            mock_response.json.return_value = search_response
            mock_response.raise_for_status = MagicMock()
            tool._mock_http_client.post.return_value = mock_response

            result_json = tool.forward("query")
            results = json.loads(result_json)
            assert len(results) == 1

    def test_forward_no_retrieval_data(self, idata_tool: IdataSearchTool):
        """Test forward with no retrieval data"""
        search_response = {
            "code": "1",
            "data": {
                "retrievalData": []
            }
        }
        mock_response = MagicMock()
        mock_response.json.return_value = search_response
        mock_response.raise_for_status = MagicMock()
        idata_tool._mock_http_client.post.return_value = mock_response

        with pytest.raises(Exception) as excinfo:
            idata_tool.forward("test query")

        assert "No results found!" in str(excinfo.value)

    def test_forward_no_chunks(self, idata_tool: IdataSearchTool):
        """Test forward with no chunks in retrieval data"""
        search_response = {
            "code": "1",
            "data": {
                "retrievalData": [{"chunks": []}]
            }
        }
        mock_response = MagicMock()
        mock_response.json.return_value = search_response
        mock_response.raise_for_status = MagicMock()
        idata_tool._mock_http_client.post.return_value = mock_response

        with pytest.raises(Exception) as excinfo:
            idata_tool.forward("test query")

        assert "No chunks found in search results!" in str(excinfo.value)

    def test_forward_multiple_chunks(self, idata_tool: IdataSearchTool):
        """Test forward with multiple chunks"""
        chunks = [
            {
                "documentId": f"doc{i}",
                "documentName": f"document{i}.txt",
                "content": f"content {i}",
                "datasetId": f"kb{i % 2 + 1}",
                "createTime": 1609459200000 + i * 86400000,
                "reRankScore": 0.9 - i * 0.1,
                "vsScore": 0.8 - i * 0.1,
                "esScore": 0.7 - i * 0.1,
                "title": f"Document {i}"
            }
            for i in range(5)
        ]
        self._setup_success_flow(idata_tool, chunks=chunks)

        result_json = idata_tool.forward("test query")
        results = json.loads(result_json)

        assert len(results) == 5
        assert idata_tool.record_ops == 6  # 1 + 5

    def test_forward_chunk_without_title_uses_document_name(self, idata_tool: IdataSearchTool):
        """Test forward when chunk has no title, uses documentName"""
        chunks = [{
            "documentId": "doc1",
            "documentName": "document1.txt",
            "content": "content",
            "datasetId": "kb1",
            "createTime": 1609459200000,
            "reRankScore": 0.9,
            "vsScore": 0.8,
            "esScore": 0.7,
            # No title field
        }]
        self._setup_success_flow(idata_tool, chunks=chunks)

        result_json = idata_tool.forward("test query")
        results = json.loads(result_json)

        assert results[0]["title"] == "document1.txt"

    def test_forward_chunk_with_empty_title_uses_document_name(self, idata_tool: IdataSearchTool):
        """Test forward when chunk has empty title, uses documentName"""
        chunks = [{
            "documentId": "doc1",
            "documentName": "document1.txt",
            "content": "content",
            "datasetId": "kb1",
            "createTime": 1609459200000,
            "reRankScore": 0.9,
            "vsScore": 0.8,
            "esScore": 0.7,
            "title": "",  # Empty title
        }]
        self._setup_success_flow(idata_tool, chunks=chunks)

        result_json = idata_tool.forward("test query")
        results = json.loads(result_json)

        assert results[0]["title"] == "document1.txt"

    def test_forward_chunk_with_zero_create_time(self, idata_tool: IdataSearchTool):
        """Test forward with zero create_time"""
        chunks = [{
            "documentId": "doc1",
            "documentName": "document1.txt",
            "content": "content",
            "datasetId": "kb1",
            "createTime": 0,  # Zero timestamp
            "reRankScore": 0.9,
            "vsScore": 0.8,
            "esScore": 0.7,
            "title": "Doc 1"
        }]
        self._setup_success_flow(idata_tool, chunks=chunks)

        result_json = idata_tool.forward("test query")
        results = json.loads(result_json)

        # Verify result structure (to_model_dict only returns title, text, index)
        assert results[0]["title"] == "Doc 1"
        assert results[0]["text"] == "content"
        assert "index" in results[0]

        # Verify published_date is empty in the detailed search content sent to observer
        call_args_list = idata_tool.observer.add_message.call_args_list
        search_content_call = None
        for call in call_args_list:
            if len(call[0]) >= 3 and call[0][1] == ProcessType.SEARCH_CONTENT:
                search_content_call = call
                break

        if search_content_call:
            search_content_data = json.loads(search_content_call[0][2])
            assert search_content_data[0]["published_date"] == ""

    def test_forward_chunk_with_invalid_create_time(self, idata_tool: IdataSearchTool):
        """Test forward with invalid create_time that causes exception"""
        chunks = [{
            "documentId": "doc1",
            "documentName": "document1.txt",
            "content": "content",
            "datasetId": "kb1",
            "createTime": "invalid",  # Invalid timestamp
            "reRankScore": 0.9,
            "vsScore": 0.8,
            "esScore": 0.7,
            "title": "Doc 1"
        }]
        self._setup_success_flow(idata_tool, chunks=chunks)

        result_json = idata_tool.forward("test query")
        results = json.loads(result_json)

        # Verify result structure (to_model_dict only returns title, text, index)
        assert results[0]["title"] == "Doc 1"
        assert results[0]["text"] == "content"

        # Verify published_date is empty in the detailed search content sent to observer
        call_args_list = idata_tool.observer.add_message.call_args_list
        search_content_call = None
        for call in call_args_list:
            if len(call[0]) >= 3 and call[0][1] == ProcessType.SEARCH_CONTENT:
                search_content_call = call
                break

        if search_content_call:
            search_content_data = json.loads(search_content_call[0][2])
            # Should handle exception gracefully and set empty published_date
            assert search_content_data[0]["published_date"] == ""

    def test_forward_chunk_with_missing_scores(self, idata_tool: IdataSearchTool):
        """Test forward with missing score fields"""
        chunks = [{
            "documentId": "doc1",
            "documentName": "document1.txt",
            "content": "content",
            "datasetId": "kb1",
            "createTime": 1609459200000,
            # Missing score fields
            "title": "Doc 1"
        }]
        self._setup_success_flow(idata_tool, chunks=chunks)

        result_json = idata_tool.forward("test query")
        results = json.loads(result_json)

        # Verify result structure (to_model_dict only returns title, text, index)
        assert results[0]["title"] == "Doc 1"
        assert results[0]["text"] == "content"

        # Verify scores in the detailed search content sent to observer
        call_args_list = idata_tool.observer.add_message.call_args_list
        search_content_call = None
        for call in call_args_list:
            if len(call[0]) >= 3 and call[0][1] == ProcessType.SEARCH_CONTENT:
                search_content_call = call
                break

        if search_content_call:
            search_content_data = json.loads(search_content_call[0][2])
            assert search_content_data[0]["score"] is None
            assert search_content_data[0]["score_details"]["reRankScore"] == 0
            assert search_content_data[0]["score_details"]["vsScore"] == 0
            assert search_content_data[0]["score_details"]["esScore"] == 0

    def test_forward_search_api_error(self, idata_tool: IdataSearchTool):
        """Test forward when search API raises error"""
        idata_tool._mock_http_client.post.side_effect = httpx.RequestError(
            "API error", request=MagicMock()
        )

        with pytest.raises(Exception) as excinfo:
            idata_tool.forward("test query")

        assert "Error searching iData knowledge base" in str(excinfo.value)
        assert "iData API request failed" in str(excinfo.value)

    def test_forward_payload_construction(self, idata_tool: IdataSearchTool):
        """Test that forward constructs correct payload"""
        self._setup_success_flow(idata_tool)

        idata_tool.forward("test question")

        # Verify the payload was constructed correctly
        call_args = idata_tool._mock_http_client.post.call_args
        payload = call_args[1]["json"]

        assert payload["userId"] == "test_user_id"
        assert payload["question"] == "test question"
        assert payload["rankTopN"] == 5
        assert payload["rerankModelId"] == "test_rerank_model_id"
        assert payload["similarityThreshold"] == 0.5
        assert payload["keywordSimilarityWeight"] == 0.1
        assert payload["vectorSimilarityWeight"] == 0.3
        assert len(payload["knowledgeBaseFilter"]) == 2
        assert payload["knowledgeBaseFilter"][0]["knowledgeBaseId"] == "kb1"
        assert payload["knowledgeBaseFilter"][1]["knowledgeBaseId"] == "kb2"

    def test_forward_custom_parameters(self, mock_observer: MessageObserver):
        """Test forward with custom parameters"""
        with patch("sdk.nexent.core.tools.idata_search_tool.http_client_manager") as mock_manager:
            mock_client = MagicMock()
            mock_manager.get_sync_client.return_value = mock_client

            tool = IdataSearchTool(
                server_url="https://api.idata.example.com",
                api_key="test_api_key",
                user_id="test_user_id",
                knowledge_space_id="test_knowledge_space_id",
                dataset_ids='["kb1"]',
                rerank_model_id="test_rerank_model_id",
                top_k=20,
                similarity_threshold=0.8,
                keyword_similarity_weight=0.2,
                vector_similarity_weight=0.4,
                observer=mock_observer,
            )
            tool._mock_http_client = mock_client

            search_response = _build_search_response()
            mock_response = MagicMock()
            mock_response.json.return_value = search_response
            mock_response.raise_for_status = MagicMock()
            tool._mock_http_client.post.return_value = mock_response

            tool.forward("test question")

            call_args = tool._mock_http_client.post.call_args
            payload = call_args[1]["json"]

            assert payload["rankTopN"] == 20
            assert payload["similarityThreshold"] == 0.8
            assert payload["keywordSimilarityWeight"] == 0.2
            assert payload["vectorSimilarityWeight"] == 0.4

    def test_forward_result_format(self, idata_tool: IdataSearchTool):
        """Test that forward returns correctly formatted results"""
        self._setup_success_flow(idata_tool)

        result_json = idata_tool.forward("test query")
        results = json.loads(result_json)

        assert len(results) == 2

        # Verify first result structure (to_model_dict only returns title, text, index)
        result1 = results[0]
        assert "title" in result1
        assert "text" in result1
        assert "index" in result1
        assert result1["title"] == "Test Document 1"
        assert result1["text"] == "test content 1"
        assert result1["index"].startswith("h")  # Should start with tool_sign "h"

        # Verify detailed fields in the search content sent to observer
        call_args_list = idata_tool.observer.add_message.call_args_list
        search_content_call = None
        for call in call_args_list:
            if len(call[0]) >= 3 and call[0][1] == ProcessType.SEARCH_CONTENT:
                search_content_call = call
                break

        if search_content_call:
            search_content_data = json.loads(search_content_call[0][2])
            detail_result = search_content_data[0]
            assert "source_type" in detail_result
            assert "url" in detail_result
            assert "filename" in detail_result
            assert "published_date" in detail_result
            assert "score" in detail_result
            assert "score_details" in detail_result
            assert "search_type" in detail_result
            assert "tool_sign" in detail_result

            assert detail_result["source_type"] == "idata"
            assert detail_result["search_type"] == "idata_search"
            assert detail_result["tool_sign"] == "h"  # IDATA_SEARCH value

    def test_forward_chunk_with_zero_re_rank_score(self, idata_tool: IdataSearchTool):
        """Test forward with zero re_rank_score (falsy value)"""
        chunks = [{
            "documentId": "doc1",
            "documentName": "document1.txt",
            "content": "content",
            "datasetId": "kb1",
            "createTime": 1609459200000,
            "reRankScore": 0,  # Zero (falsy)
            "vsScore": 0.8,
            "esScore": 0.7,
            "title": "Doc 1"
        }]
        self._setup_success_flow(idata_tool, chunks=chunks)

        result_json = idata_tool.forward("test query")
        results = json.loads(result_json)

        # Verify result structure (to_model_dict only returns title, text, index)
        assert results[0]["title"] == "Doc 1"
        assert results[0]["text"] == "content"

        # Verify zero re_rank_score results in None score in the detailed search content sent to observer
        call_args_list = idata_tool.observer.add_message.call_args_list
        search_content_call = None
        for call in call_args_list:
            if len(call[0]) >= 3 and call[0][1] == ProcessType.SEARCH_CONTENT:
                search_content_call = call
                break

        if search_content_call:
            search_content_data = json.loads(search_content_call[0][2])
            # Zero re_rank_score should result in None score
            assert search_content_data[0]["score"] is None

    def test_forward_chunk_with_none_title(self, idata_tool: IdataSearchTool):
        """Test forward when chunk has None title"""
        chunks = [{
            "documentId": "doc1",
            "documentName": "document1.txt",
            "content": "content",
            "datasetId": "kb1",
            "createTime": 1609459200000,
            "reRankScore": 0.9,
            "vsScore": 0.8,
            "esScore": 0.7,
            "title": None,  # None title
        }]
        self._setup_success_flow(idata_tool, chunks=chunks)

        result_json = idata_tool.forward("test query")
        results = json.loads(result_json)

        # None title should fallback to document_name
        assert results[0]["title"] == "document1.txt"

    def test_forward_chunk_with_falsy_title_uses_document_name(self, idata_tool: IdataSearchTool):
        """Test forward when title is falsy (empty string), uses document_name"""
        chunks = [{
            "documentId": "doc1",
            "documentName": "document1.txt",
            "content": "content",
            "datasetId": "kb1",
            "createTime": 1609459200000,
            "reRankScore": 0.9,
            "vsScore": 0.8,
            "esScore": 0.7,
            "title": "",  # Empty string (falsy)
        }]
        self._setup_success_flow(idata_tool, chunks=chunks)

        result_json = idata_tool.forward("test query")
        results = json.loads(result_json)

        # Empty title should fallback to document_name due to "title or document_name" logic
        assert results[0]["title"] == "document1.txt"

    def test_forward_chunk_with_missing_chunk_fields(self, idata_tool: IdataSearchTool):
        """Test forward with minimal chunk data (missing optional fields)"""
        chunks = [{
            "documentId": "doc1",
            "content": "content",
            # Missing most fields
        }]
        self._setup_success_flow(idata_tool, chunks=chunks)

        result_json = idata_tool.forward("test query")
        results = json.loads(result_json)

        assert len(results) == 1
        assert results[0]["text"] == "content"
        assert results[0]["title"] == ""  # Empty document_name

        # Verify detailed fields in the search content sent to observer
        call_args_list = idata_tool.observer.add_message.call_args_list
        search_content_call = None
        for call in call_args_list:
            if len(call[0]) >= 3 and call[0][1] == ProcessType.SEARCH_CONTENT:
                search_content_call = call
                break

        if search_content_call:
            search_content_data = json.loads(search_content_call[0][2])
            detail_result = search_content_data[0]
            assert detail_result["filename"] == ""
            assert detail_result["score"] is None  # Missing reRankScore

    def test_forward_handles_exception_in_datetime_conversion(self, idata_tool: IdataSearchTool):
        """Test forward handles exception during datetime conversion gracefully"""
        # Use a createTime value that will cause an exception when converting
        # Using a very large timestamp that exceeds the valid range for datetime.fromtimestamp
        # This will cause an OSError or ValueError on most systems
        chunks = [{
            "documentId": "doc1",
            "documentName": "document1.txt",
            "content": "content",
            "datasetId": "kb1",
            "createTime": 999999999999999999,  # Extremely large timestamp that will cause conversion error
            "reRankScore": 0.9,
            "vsScore": 0.8,
            "esScore": 0.7,
            "title": "Doc 1"
        }]
        self._setup_success_flow(idata_tool, chunks=chunks)

        result_json = idata_tool.forward("test query")
        results = json.loads(result_json)

        # Verify result structure (to_model_dict only returns title, text, index)
        assert results[0]["title"] == "Doc 1"
        assert results[0]["text"] == "content"

        # Verify published_date is empty in the detailed search content sent to observer
        # The exception during datetime conversion should be caught and result in empty published_date
        call_args_list = idata_tool.observer.add_message.call_args_list
        search_content_call = None
        for call in call_args_list:
            if len(call[0]) >= 3 and call[0][1] == ProcessType.SEARCH_CONTENT:
                search_content_call = call
                break

        if search_content_call:
            search_content_data = json.loads(search_content_call[0][2])
            # Should handle exception and set empty published_date
            assert search_content_data[0]["published_date"] == ""

    def test_forward_with_single_dataset_id(self, mock_observer: MessageObserver):
        """Test forward with single dataset_id"""
        with patch("sdk.nexent.core.tools.idata_search_tool.http_client_manager") as mock_manager:
            mock_client = MagicMock()
            mock_manager.get_sync_client.return_value = mock_client

            tool = IdataSearchTool(
                server_url="https://api.idata.example.com",
                api_key="test_api_key",
                user_id="test_user_id",
                knowledge_space_id="test_knowledge_space_id",
                dataset_ids='["kb1"]',
                rerank_model_id="test_rerank_model_id",
                observer=mock_observer,
            )
            tool._mock_http_client = mock_client

            search_response = _build_search_response()
            mock_response = MagicMock()
            mock_response.json.return_value = search_response
            mock_response.raise_for_status = MagicMock()
            tool._mock_http_client.post.return_value = mock_response

            tool.forward("test question")

            # Verify payload has single knowledge base filter
            call_args = tool._mock_http_client.post.call_args
            payload = call_args[1]["json"]
            assert len(payload["knowledgeBaseFilter"]) == 1
            assert payload["knowledgeBaseFilter"][0]["knowledgeBaseId"] == "kb1"
