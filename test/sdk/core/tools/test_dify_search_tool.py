import json
from typing import List
from unittest.mock import ANY, MagicMock, patch

import httpx
import pytest
from pytest_mock import MockFixture

from sdk.nexent.core.tools.dify_search_tool import DifySearchTool
from sdk.nexent.core.utils.observer import MessageObserver, ProcessType


@pytest.fixture
def mock_observer() -> MessageObserver:
    observer = MagicMock(spec=MessageObserver)
    observer.lang = "en"
    return observer


@pytest.fixture
def dify_tool(mock_observer: MessageObserver) -> DifySearchTool:
    with patch("sdk.nexent.core.tools.dify_search_tool.http_client_manager") as mock_manager:
        mock_client = MagicMock()
        mock_manager.get_sync_client.return_value = mock_client
        tool = DifySearchTool(
            server_url="https://api.dify.ai/v1",
            api_key="test_api_key",
            dataset_ids='["dataset1", "dataset2"]',
            top_k=3,
            observer=mock_observer,
        )
        # Store the mock client for tests to use
        tool._mock_http_client = mock_client
        return tool


def _build_search_response(records: List[dict] = None, query: str = "test query"):
    if records is None:
        records = [
            {
                "segment": {
                    "content": "test content 1",
                    "document": {
                        "id": "doc1",
                        "name": "document1.txt"
                    }
                },
                "score": 0.9
            },
            {
                "segment": {
                    "content": "test content 2",
                    "document": {
                        "id": "doc2",
                        "name": "document2.txt"
                    }
                },
                "score": 0.8
            }
        ]
    return {"query": query, "records": records}


def _build_download_url_response(download_url: str = "https://download.example.com/file.pdf"):
    return {"download_url": download_url}


class TestDifySearchToolInit:
    def test_init_success(self, mock_observer: MessageObserver):
        tool = DifySearchTool(
            server_url="https://api.dify.ai/v1",
            api_key="test_key",
            dataset_ids='["ds1", "ds2"]',
            top_k=5,
            observer=mock_observer,
        )

        assert tool.server_url == "https://api.dify.ai/v1"
        assert tool.dataset_ids == ["ds1", "ds2"]
        assert tool.api_key == "test_key"
        assert tool.top_k == 5
        assert tool.observer is mock_observer
        assert tool.record_ops == 1
        assert tool.running_prompt_zh == "Dify知识库检索中..."
        assert tool.running_prompt_en == "Searching Dify knowledge base..."

    def test_init_singledataset_id(self, mock_observer: MessageObserver):
        tool = DifySearchTool(
            server_url="https://api.dify.ai/v1/",
            api_key="test_key",
            dataset_ids='["single_dataset"]',
            observer=mock_observer,
        )

        assert tool.server_url == "https://api.dify.ai/v1"
        assert tool.dataset_ids == ["single_dataset"]

    def test_init_json_string_array_dataset_ids(self, mock_observer: MessageObserver):
        tool = DifySearchTool(
            server_url="https://api.dify.ai/v1/",
            api_key="test_key",
            dataset_ids='["0ab7096c-dfa5-4e0e-9dad-9265781447a3"]',
            observer=mock_observer,
        )

        assert tool.server_url == "https://api.dify.ai/v1"
        assert tool.dataset_ids == ["0ab7096c-dfa5-4e0e-9dad-9265781447a3"]

    def test_init_json_string_array_multiple_dataset_ids(self, mock_observer: MessageObserver):
        tool = DifySearchTool(
            server_url="https://api.dify.ai/v1/",
            api_key="test_key",
            dataset_ids='["ds1", "ds2", "ds3"]',
            observer=mock_observer,
        )

        assert tool.server_url == "https://api.dify.ai/v1"
        assert tool.dataset_ids == ["ds1", "ds2", "ds3"]

    @pytest.mark.parametrize("server_url,expected_error", [
        ("", "server_url is required and must be a non-empty string"),
        (None, "server_url is required and must be a non-empty string"),
    ])
    def test_init_invalid_server_url(self, server_url, expected_error):
        with pytest.raises(ValueError) as excinfo:
            DifySearchTool(
                server_url=server_url,
                api_key="test_key",
                dataset_ids='["ds1"]',
            )
        assert expected_error in str(excinfo.value)

    @pytest.mark.parametrize("api_key,expected_error", [
        ("", "api_key is required and must be a non-empty string"),
        (None, "api_key is required and must be a non-empty string"),
    ])
    def test_init_invalid_api_key(self, api_key, expected_error):
        with pytest.raises(ValueError) as excinfo:
            DifySearchTool(
                server_url="https://api.dify.ai/v1",
                api_key=api_key,
                dataset_ids='["ds1"]',
            )
        assert expected_error in str(excinfo.value)

    @pytest.mark.parametrize("dataset_ids,expected_error", [
        ([], "dataset_ids is required and must be a non-empty JSON string array or list"),
        ("", "dataset_ids is required and must be a non-empty JSON string array or list"),
        (None, "dataset_ids is required and must be a non-empty JSON string array or list"),
    ])
    def test_init_invaliddataset_ids(self, dataset_ids, expected_error):
        with pytest.raises(ValueError) as excinfo:
            DifySearchTool(
                server_url="https://api.dify.ai/v1",
                api_key="test_key",
                dataset_ids=dataset_ids,
            )
        assert expected_error in str(excinfo.value)

    def test_init_dataset_ids_empty_json_array_string(self, mock_observer: MessageObserver):
        """Test that empty JSON array '[]' raises ValueError."""
        with pytest.raises(ValueError) as excinfo:
            DifySearchTool(
                server_url="https://api.dify.ai/v1",
                api_key="test_key",
                dataset_ids="[]",
                observer=mock_observer,
            )
        # Empty JSON array passes the first check (not falsy), but fails the list/empty check
        assert "dataset_ids must be a non-empty array of strings" in str(excinfo.value)

    def test_init_dataset_ids_as_list(self, mock_observer: MessageObserver):
        """Test dataset_ids can be passed as a Python list instead of JSON string."""
        tool = DifySearchTool(
            server_url="https://api.dify.ai/v1",
            api_key="test_key",
            dataset_ids=["ds1", "ds2", "ds3"],
            observer=mock_observer,
        )

        assert tool.dataset_ids == ["ds1", "ds2", "ds3"]
        assert len(tool.dataset_ids) == 3

    def test_init_dataset_ids_as_list_single_item(self, mock_observer: MessageObserver):
        """Test dataset_ids as a list with single item."""
        tool = DifySearchTool(
            server_url="https://api.dify.ai/v1",
            api_key="test_key",
            dataset_ids=["single_dataset"],
            observer=mock_observer,
        )

        assert tool.dataset_ids == ["single_dataset"]
        assert len(tool.dataset_ids) == 1

    def test_init_dataset_ids_as_list_with_numeric_ids(self, mock_observer: MessageObserver):
        """Test dataset_ids list with numeric IDs are converted to strings."""
        tool = DifySearchTool(
            server_url="https://api.dify.ai/v1",
            api_key="test_key",
            dataset_ids=[123, 456, 789],
            observer=mock_observer,
        )

        assert tool.dataset_ids == ["123", "456", "789"]
        assert all(isinstance(id, str) for id in tool.dataset_ids)

    @pytest.mark.parametrize("invalid_json,expected_error_contains", [
        ("invalid_json", "dataset_ids must be a valid JSON string array or list"),
        ("{key: value}", "dataset_ids must be a valid JSON string array or list"),
        ("{'key': 'value'}", "dataset_ids must be a valid JSON string array or list"),
        ("123", "dataset_ids must be a non-empty array of strings"),
    ])
    def test_init_invalid_json_format(self, invalid_json, expected_error_contains, mock_observer: MessageObserver):
        """Test dataset_ids with invalid JSON format raises appropriate error."""
        with pytest.raises(ValueError) as excinfo:
            DifySearchTool(
                server_url="https://api.dify.ai/v1",
                api_key="test_key",
                dataset_ids=invalid_json,
                observer=mock_observer,
            )
        assert expected_error_contains in str(excinfo.value)

    def test_init_dataset_ids_with_malformed_json_array(self, mock_observer: MessageObserver):
        """Test dataset_ids with malformed JSON array."""
        with pytest.raises(ValueError) as excinfo:
            DifySearchTool(
                server_url="https://api.dify.ai/v1",
                api_key="test_key",
                dataset_ids='["ds1", "ds2"',  # Missing closing bracket
                observer=mock_observer,
            )
        assert "dataset_ids must be a valid JSON string array or list" in str(excinfo.value)

    def test_init_dataset_ids_json_string_with_non_string_elements(self, mock_observer: MessageObserver):
        """Test that non-string elements in JSON array are converted to strings."""
        tool = DifySearchTool(
            server_url="https://api.dify.ai/v1",
            api_key="test_key",
            dataset_ids='["ds1", 123, true, null]',
            observer=mock_observer,
        )

        # Elements should be converted to strings using Python's str()
        # JSON true -> Python True -> str() -> 'True'
        # JSON null -> Python None -> str() -> 'None'
        assert tool.dataset_ids == ["ds1", "123", "True", "None"]
        assert all(isinstance(id, str) for id in tool.dataset_ids)


class TestGetDocumentDownloadUrl:
    def test_get_document_download_url_success(self, mocker: MockFixture, dify_tool: DifySearchTool):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _build_download_url_response()
        dify_tool._mock_http_client.get.return_value = mock_response

        url = dify_tool._get_document_download_url("doc1", "dataset1")

        assert url == "https://download.example.com/file.pdf"
        dify_tool._mock_http_client.get.assert_called_once_with(
            "https://api.dify.ai/v1/datasets/dataset1/documents/doc1/upload-file",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer test_api_key"
            }
        )

    def test_get_document_download_url_empty_document_id(self, dify_tool: DifySearchTool):
        url = dify_tool._get_document_download_url("", "dataset1")
        assert url == ""

    def test_get_document_download_url_nodataset_id(self, dify_tool: DifySearchTool):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _build_download_url_response()
        dify_tool._mock_http_client.get.return_value = mock_response

        url = dify_tool._get_document_download_url("doc1")

        # Should use first dataset_id from list
        assert url == "https://download.example.com/file.pdf"
        dify_tool._mock_http_client.get.assert_called_once_with(
            "https://api.dify.ai/v1/datasets/dataset1/documents/doc1/upload-file",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer test_api_key"
            }
        )

    def test_get_document_download_url_request_error(self, dify_tool: DifySearchTool):
        dify_tool._mock_http_client.get.side_effect = httpx.RequestError("Connection error", request=MagicMock())

        url = dify_tool._get_document_download_url("doc1", "dataset1")

        assert url == ""

    def test_get_document_download_url_json_decode_error(self, dify_tool: DifySearchTool):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)
        dify_tool._mock_http_client.get.return_value = mock_response

        url = dify_tool._get_document_download_url("doc1", "dataset1")

        assert url == ""

    def test_get_document_download_url_missing_key(self, dify_tool: DifySearchTool):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}  # Missing download_url key
        dify_tool._mock_http_client.get.return_value = mock_response

        url = dify_tool._get_document_download_url("doc1", "dataset1")

        assert url == ""


class TestSearchDifyKnowledgeBase:
    def test_search_dify_knowledge_base_success(self, dify_tool: DifySearchTool):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = _build_search_response()
        dify_tool._mock_http_client.post.return_value = response

        result = dify_tool._search_dify_knowledge_base("test query", 3, "semantic_search", "dataset1")

        assert result["query"] == "test query"
        assert len(result["records"]) == 2
        assert result["records"][0]["segment"]["content"] == "test content 1"
        assert result["records"][1]["segment"]["content"] == "test content 2"

        # Note: Current implementation has URL construction issue
        # The URL is constructed as f"{self.server_url}/datasets/{dataset_id}/retrieve"
        # where server_url is "https://api.dify.ai/v1", so it becomes "https://api.dify.ai/v1/datasets/dataset1/retrieve"
        # This is a bug in the implementation that needs to be fixed
        dify_tool._mock_http_client.post.assert_called_once_with(
            "https://api.dify.ai/v1/datasets/dataset1/retrieve",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer test_api_key"
            },
            json={
                "query": "test query",
                "retrieval_model": {
                    "search_method": "semantic_search",
                    "reranking_enable": False,
                    "reranking_mode": None,
                    "reranking_model": {
                        "reranking_provider_name": "",
                        "reranking_model_name": ""
                    },
                    "weights": None,
                    "top_k": 3,
                    "score_threshold_enabled": False,
                    "score_threshold": None
                }
            }
        )

    def test_search_dify_knowledge_base_no_records(self, dify_tool: DifySearchTool):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"query": "test query", "records": []}
        dify_tool._mock_http_client.post.return_value = response

        result = dify_tool._search_dify_knowledge_base("test query", 3, "semantic_search", "dataset1")

        assert result == {"query": "test query", "records": []}

    def test_search_dify_knowledge_base_request_error(self, dify_tool: DifySearchTool):
        dify_tool._mock_http_client.post.side_effect = httpx.RequestError("API error", request=MagicMock())

        with pytest.raises(Exception) as excinfo:
            dify_tool._search_dify_knowledge_base("test query", 3, "semantic_search", "dataset1")

        assert "Dify API request failed" in str(excinfo.value)

    def test_search_dify_knowledge_base_json_decode_error(self, dify_tool: DifySearchTool):
        response = MagicMock()
        response.status_code = 200
        response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)
        dify_tool._mock_http_client.post.return_value = response

        with pytest.raises(Exception) as excinfo:
            dify_tool._search_dify_knowledge_base("test query", 3, "semantic_search", "dataset1")

        assert "Failed to parse Dify API response" in str(excinfo.value)

    def test_search_dify_knowledge_base_missing_key(self, dify_tool: DifySearchTool):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {}  # Missing records key
        dify_tool._mock_http_client.post.return_value = response

        with pytest.raises(Exception) as excinfo:
            dify_tool._search_dify_knowledge_base("test query", 3, "semantic_search", "dataset1")

        assert "Unexpected Dify API response format" in str(excinfo.value)


class TestForward:
    def _setup_success_flow(self, tool: DifySearchTool):
        # Mock search method to return records
        search_response = {
            "query": "test query",
            "records": [
                {
                    "segment": {
                        "content": "test content 1",
                        "document": {
                            "id": "doc1",
                            "name": "document1.txt"
                        }
                    },
                    "score": 0.9
                }
            ]
        }

        # Mock download URL response
        download_response = {"download_url": "https://download.example.com/doc1.pdf"}

        # Set up responses for both post and get calls
        mock_search_response = MagicMock()
        mock_search_response.status_code = 200
        mock_search_response.json.return_value = search_response

        mock_download_response = MagicMock()
        mock_download_response.status_code = 200
        mock_download_response.json.return_value = download_response

        # Configure mock client to return different responses based on URL
        def mock_post(url, **kwargs):
            if "/retrieve" in url:
                return mock_search_response
            else:
                raise ValueError(f"Unexpected URL: {url}")

        def mock_get(url, **kwargs):
            if "/upload-file" in url:
                return mock_download_response
            else:
                raise ValueError(f"Unexpected URL: {url}")

        tool._mock_http_client.post.side_effect = mock_post
        tool._mock_http_client.get.side_effect = mock_get

    def test_forward_success_with_observer_en(self, dify_tool: DifySearchTool):
        self._setup_success_flow(dify_tool)

        # Set search_method as instance attribute
        dify_tool.search_method = "keyword_search"

        result_json = dify_tool.forward("test query")
        results = json.loads(result_json)

        assert len(results) == 2  # 2 datasets * 1 record each
        assert all(isinstance(item["index"], str) for item in results)
        assert results[0]["title"] == "document1.txt"
        assert results[0]["text"] == "test content 1"

        # Check that observer received running prompt and card
        dify_tool.observer.add_message.assert_any_call(
            "", ProcessType.TOOL, dify_tool.running_prompt_en
        )
        dify_tool.observer.add_message.assert_any_call(
            "", ProcessType.CARD, json.dumps([{"icon": "search", "text": "test query"}], ensure_ascii=False)
        )
        # Check that search content message is added
        dify_tool.observer.add_message.assert_any_call(
            "", ProcessType.SEARCH_CONTENT, ANY
        )

        assert dify_tool.record_ops == 3  # 1 + len(results)

        # Verify API calls were made for both datasets
        assert dify_tool._mock_http_client.post.call_count == 2  # Called once per dataset

    def test_forward_success_with_observer_zh(self, dify_tool: DifySearchTool):
        dify_tool.observer.lang = "zh"
        self._setup_success_flow(dify_tool)

        dify_tool.forward("测试查询")

        dify_tool.observer.add_message.assert_any_call(
            "", ProcessType.TOOL, dify_tool.running_prompt_zh
        )

    def test_forward_no_observer(self):
        with patch("sdk.nexent.core.tools.dify_search_tool.http_client_manager") as mock_manager:
            mock_client = MagicMock()
            mock_manager.get_sync_client.return_value = mock_client
            tool = DifySearchTool(
                server_url="https://api.dify.ai/v1",
                api_key="test_api_key",
                dataset_ids='["dataset1"]',
                observer=None,
            )
            tool._mock_http_client = mock_client
            self._setup_success_flow(tool)

            # Should not raise and should not call observer
            result_json = tool.forward("query")
            assert len(json.loads(result_json)) == 1

    def test_forward_no_results(self, dify_tool: DifySearchTool):
        # Mock empty search results
        search_response = {"query": "test query", "records": []}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = search_response

        dify_tool._mock_http_client.post.return_value = mock_response

        with pytest.raises(Exception) as excinfo:
            dify_tool.forward("test query")

        # The exception message includes the prefix "Error searching Dify knowledge base: "
        assert "No results found!" in str(excinfo.value)
        assert "Error searching Dify knowledge base" in str(excinfo.value)

    def test_forward_search_api_error(self, dify_tool: DifySearchTool):
        dify_tool._mock_http_client.post.side_effect = httpx.RequestError("API error", request=MagicMock())

        with pytest.raises(Exception) as excinfo:
            dify_tool.forward("test query")

        assert "Error searching Dify knowledge base" in str(excinfo.value)
        assert "Dify API request failed" in str(excinfo.value)

    def test_forward_download_url_error_still_works(self, dify_tool: DifySearchTool):
        # Mock successful search but failed download URL
        search_response = {
            "query": "test query",
            "records": [
                {
                    "segment": {
                        "content": "test content",
                        "document": {
                            "id": "doc1",
                            "name": "document1.txt"
                        }
                    },
                    "score": 0.9
                }
            ]
        }

        mock_search_response = MagicMock()
        mock_search_response.status_code = 200
        mock_search_response.json.return_value = search_response

        # Configure client to succeed on post but fail on get
        dify_tool._mock_http_client.post.return_value = mock_search_response
        dify_tool._mock_http_client.get.side_effect = httpx.RequestError("Download failed", request=MagicMock())

        # Should still work but with empty URL
        result_json = dify_tool.forward("test query")
        results = json.loads(result_json)

        assert len(results) == 2  # Still processes results even with download URL failure
        assert results[0]["title"] == "document1.txt"
        # URL should be empty string due to download failure
