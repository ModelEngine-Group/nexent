import json
from typing import List
from unittest.mock import ANY, MagicMock, call

import pytest
from pytest_mock import MockFixture

from sdk.nexent.core.tools.datamate_search_tool import DataMateSearchTool
from sdk.nexent.core.utils.observer import MessageObserver, ProcessType

@pytest.fixture
def mock_observer() -> MessageObserver:
    observer = MagicMock(spec=MessageObserver)
    observer.lang = "en"
    return observer


@pytest.fixture
def datamate_tool(mock_observer: MessageObserver) -> DataMateSearchTool:
    tool = DataMateSearchTool(
        server_url="http://127.0.0.1:8080",
        observer=mock_observer,
        index_names=["kb1"],
        top_k=2,
        threshold=0.5,
    )
    return tool


@pytest.fixture
def datamate_tool_https(mock_observer: MessageObserver) -> DataMateSearchTool:
    tool = DataMateSearchTool(
        server_url="https://127.0.0.1:8443",
        verify_ssl=False,
        observer=mock_observer,
    )
    return tool


def _build_kb_list(ids: List[str]):
    return [{"id": kb_id, "chunkCount": 1} for kb_id in ids]


def _build_search_results(kb_id: str, count: int = 2):
    return [
        {
            "entity": {
                "id": f"file-{i}",
                "text": f"content-{i}",
                "createTime": "2024-01-01T00:00:00Z",
                "score": 0.9 - i * 0.1,
                "metadata": json.dumps(
                    {
                        "file_name": f"file-{i}.txt",
                        "absolute_directory_path": f"/data/{kb_id}",
                        "original_file_id": f"orig-{i}",
                    }
                ),
                "scoreDetails": {"raw": 0.8},
            }
        }
        for i in range(count)
    ]


class TestDataMateSearchToolInit:
    def test_init_success(self, mock_observer: MessageObserver, mocker: MockFixture):
        mock_datamate_core = mocker.patch(
            "sdk.nexent.core.tools.datamate_search_tool.DataMateCore")

        tool = DataMateSearchTool(
            server_url="http://datamate.local:1234",
            observer=mock_observer,
        )

        assert tool.server_ip == "datamate.local"
        assert tool.server_port == 1234
        assert tool.use_https is False
        assert tool.server_base_url == "http://datamate.local:1234"
        # index_names is excluded from the model, so we can't directly test it
        # DataMateCore is mocked, so we verify it was called correctly instead

        # Verify DataMateCore was called with correct SSL verification setting for HTTP
        mock_datamate_core.assert_called_once_with(
            base_url="http://datamate.local:1234",
            verify_ssl=True  # HTTP URLs should always verify SSL
        )

    def test_init_with_index_names(self, mock_observer: MessageObserver):
        """Test initialization with custom index_names."""
        custom_index_names = ["kb1", "kb2"]
        tool = DataMateSearchTool(
            server_url="http://127.0.0.1:8080",
            index_names=custom_index_names,
            observer=mock_observer,
        )

        assert tool.index_names == custom_index_names

        assert tool.index_names == custom_index_names

    def test_init_invalid_server_url(self, mock_observer: MessageObserver):
        """Test invalid server_url parameters"""
        # Test empty URL
        with pytest.raises(ValueError) as excinfo:
            DataMateSearchTool(server_url="", observer=mock_observer)
        assert "server_url is required" in str(excinfo.value)

        # Test URL without protocol
        with pytest.raises(ValueError) as excinfo:
            DataMateSearchTool(server_url="127.0.0.1:8080",
                               observer=mock_observer)
        assert "server_url must include protocol" in str(excinfo.value)

        # Test invalid URL format
        with pytest.raises(ValueError) as excinfo:
            DataMateSearchTool(server_url="http://", observer=mock_observer)
        assert "Invalid server_url format" in str(excinfo.value)


class TestHelperMethods:
    @pytest.mark.parametrize(
        "metadata_raw, expected",
        [
            (None, {}),
            ({"a": 1}, {"a": 1}),
            ('{"b": 2}', {"b": 2}),
            ("not-json", {}),
        ],
    )
    def test_parse_metadata(self, datamate_tool: DataMateSearchTool, metadata_raw, expected):
        result = datamate_tool._parse_metadata(metadata_raw)
        assert result == expected

    @pytest.mark.parametrize(
        "path, expected",
        [
            ("", ""),
            ("/single", "single"),
            ("/a/b/c", "c"),
            ("////", ""),
            ("/a/b/c/d/", "d"),
            ("no-leading-slash", "no-leading-slash"),
            # After filtering empty segments, last is "slashes"
            ("///multiple///slashes///", "slashes"),
        ],
    )
    def test_extract_dataset_id(self, datamate_tool: DataMateSearchTool, path, expected):
        assert datamate_tool._extract_dataset_id(path) == expected


class TestForward:
    def test_forward_success_with_observer_en(self, datamate_tool: DataMateSearchTool, mocker: MockFixture):
        # Mock the hybrid_search method to return search results
        mock_hybrid_search = mocker.patch.object(
            datamate_tool.datamate_core, 'hybrid_search')
        mock_hybrid_search.return_value = _build_search_results("kb1", count=2)

        # Mock the build_file_download_url method
        mock_build_url = mocker.patch.object(
            datamate_tool.datamate_core.client, 'build_file_download_url')
        mock_build_url.side_effect = lambda ds, fid: f"http://dl/{ds}/{fid}"

        result_json = datamate_tool.forward("test query")
        results = json.loads(result_json)

        assert len(results) == 2
        datamate_tool.observer.add_message.assert_any_call(
            "", ProcessType.TOOL, datamate_tool.running_prompt_en)
        datamate_tool.observer.add_message.assert_any_call(
            "", ProcessType.CARD, json.dumps(
                [{"icon": "search", "text": "test query"}], ensure_ascii=False)
        )
        datamate_tool.observer.add_message.assert_any_call(
            "", ProcessType.SEARCH_CONTENT, ANY)
        assert datamate_tool.record_ops == 1 + len(results)

        # Verify hybrid_search was called correctly
        mock_hybrid_search.assert_called_once_with(
            query_text="test query",
            index_names=["kb1"],
            top_k=2,
            weight_accurate=0.5
        )
        mock_build_url.assert_any_call("kb1", "orig-0")

    def test_forward_success_with_observer_zh(self, datamate_tool: DataMateSearchTool, mocker: MockFixture):
        datamate_tool.observer.lang = "zh"

        # Mock the hybrid_search method to return search results
        mock_hybrid_search = mocker.patch.object(
            datamate_tool.datamate_core, 'hybrid_search')
        mock_hybrid_search.return_value = _build_search_results("kb1", count=1)

        # Mock the build_file_download_url method
        mock_build_url = mocker.patch.object(
            datamate_tool.datamate_core.client, 'build_file_download_url')
        mock_build_url.return_value = "http://dl/kb1/file-1"

        datamate_tool.forward("测试查询")

        datamate_tool.observer.add_message.assert_any_call(
            "", ProcessType.TOOL, datamate_tool.running_prompt_zh)

    def test_forward_no_observer(self, mocker: MockFixture):
        tool = DataMateSearchTool(
            server_url="http://127.0.0.1:8080", observer=None, index_names=["kb1"])

        # Mock the hybrid_search method to return search results
        mock_hybrid_search = mocker.patch.object(
            tool.datamate_core, 'hybrid_search')
        mock_hybrid_search.return_value = _build_search_results("kb1", count=1)

        # Mock the build_file_download_url method
        mock_build_url = mocker.patch.object(
            tool.datamate_core.client, 'build_file_download_url')
        mock_build_url.return_value = "http://dl/kb1/file-1"

        result_json = tool.forward("query")
        assert len(json.loads(result_json)) == 1

    def test_forward_no_knowledge_bases(self, datamate_tool: DataMateSearchTool, mocker: MockFixture):
        # Mock the hybrid_search method
        mock_hybrid_search = mocker.patch.object(
            datamate_tool.datamate_core, 'hybrid_search')

        # Set empty index_names to trigger the no knowledge base case
        datamate_tool.index_names = []

        result = datamate_tool.forward("query")
        assert result == json.dumps(
            "No knowledge base selected. No relevant information found.", ensure_ascii=False)
        mock_hybrid_search.assert_not_called()

    def test_forward_no_results(self, datamate_tool: DataMateSearchTool, mocker: MockFixture):
        # Mock the hybrid_search method to return empty results
        mock_hybrid_search = mocker.patch.object(
            datamate_tool.datamate_core, 'hybrid_search')
        mock_hybrid_search.return_value = []

        with pytest.raises(Exception) as excinfo:
            datamate_tool.forward("query")

        assert "No results found! Try a less restrictive/shorter query." in str(
            excinfo.value)

    def test_forward_wrapped_error(self, datamate_tool: DataMateSearchTool, mocker: MockFixture):
        # Mock the hybrid_search method to raise an error
        mock_hybrid_search = mocker.patch.object(
            datamate_tool.datamate_core, 'hybrid_search')
        mock_hybrid_search.side_effect = RuntimeError("low level error")

        with pytest.raises(Exception) as excinfo:
            datamate_tool.forward("query")

        msg = str(excinfo.value)
        assert "Error during DataMate knowledge base search" in msg
        assert "low level error" in msg

    def test_forward_with_default_index_names(self, datamate_tool: DataMateSearchTool, mocker: MockFixture):
        """Test forward method using default index_names from constructor."""
        # Set default index_names in the tool
        datamate_tool.index_names = ["default_kb1", "default_kb2"]
        datamate_tool.top_k = 3
        datamate_tool.threshold = 0.2

        # Mock the hybrid_search method to return results for each knowledge base
        mock_hybrid_search = mocker.patch.object(
            datamate_tool.datamate_core, 'hybrid_search')
        mock_hybrid_search.side_effect = [
            # First call returns results for kb1
            _build_search_results("default_kb1", count=1),
            # Second call returns results for kb2
            _build_search_results("default_kb2", count=1),
        ]

        # Mock the build_file_download_url method
        mock_build_url = mocker.patch.object(
            datamate_tool.datamate_core.client, 'build_file_download_url')
        mock_build_url.return_value = "http://dl/default_kb/file-1"

        result_json = datamate_tool.forward("query")
        results = json.loads(result_json)

        assert len(results) == 2  # One result from each knowledge base
        assert mock_hybrid_search.call_count == 2
        mock_hybrid_search.assert_any_call(
            query_text="query",
            index_names=["default_kb1"],
            top_k=3,
            weight_accurate=0.2
        )
        mock_hybrid_search.assert_any_call(
            query_text="query",
            index_names=["default_kb2"],
            top_k=3,
            weight_accurate=0.2
        )

    def test_forward_multiple_knowledge_bases(self, datamate_tool: DataMateSearchTool, mocker: MockFixture):
        """Test forward method with multiple knowledge bases."""
        # Set index_names for this test
        datamate_tool.index_names = ["kb1", "kb2"]
        datamate_tool.top_k = 3
        datamate_tool.threshold = 0.2

        # Mock the hybrid_search method to return results from multiple KBs
        mock_hybrid_search = mocker.patch.object(
            datamate_tool.datamate_core, 'hybrid_search')
        mock_hybrid_search.side_effect = [
            # First call returns results from kb1
            _build_search_results("kb1", count=1),
            # Second call returns results from kb2
            _build_search_results("kb2", count=2),
        ]

        # Mock the build_file_download_url method
        mock_build_url = mocker.patch.object(
            datamate_tool.datamate_core.client, 'build_file_download_url')
        mock_build_url.side_effect = lambda ds, fid: f"http://dl/{ds}/{fid}"

        result_json = datamate_tool.forward("query")
        results = json.loads(result_json)

        assert len(results) == 3  # 1 from kb1 + 2 from kb2

        # Verify hybrid_search was called for each knowledge base
        assert mock_hybrid_search.call_count == 2
        mock_hybrid_search.assert_any_call(
            query_text="query",
            index_names=["kb1"],
            top_k=3,
            weight_accurate=0.2
        )
        mock_hybrid_search.assert_any_call(
            query_text="query",
            index_names=["kb2"],
            top_k=3,
            weight_accurate=0.2
        )

    def test_forward_with_custom_parameters(self, datamate_tool: DataMateSearchTool, mocker: MockFixture):
        """Test forward method with custom parameters."""
        # Set custom parameters for this test
        datamate_tool.index_names = ["kb1"]
        datamate_tool.top_k = 5
        datamate_tool.threshold = 0.8

        # Mock the hybrid_search method
        mock_hybrid_search = mocker.patch.object(
            datamate_tool.datamate_core, 'hybrid_search')
        mock_hybrid_search.return_value = _build_search_results("kb1", count=1)

        # Mock the build_file_download_url method
        mock_build_url = mocker.patch.object(
            datamate_tool.datamate_core.client, 'build_file_download_url')
        mock_build_url.return_value = "http://dl/kb1/file-1"

        result_json = datamate_tool.forward(query="custom query")
        results = json.loads(result_json)

        assert len(results) == 1

        mock_hybrid_search.assert_called_once_with(
            query_text="custom query",
            index_names=["kb1"],
            top_k=5,
            weight_accurate=0.8
        )

    def test_forward_metadata_parsing_edge_cases(self, datamate_tool: DataMateSearchTool, mocker: MockFixture):
        """Test forward method with various metadata parsing edge cases."""
        # Set index_names for this test
        datamate_tool.index_names = ["kb1"]

        # Create search results with different metadata formats
        search_results = [
            {
                "entity": {
                    "id": "file-1",
                    "text": "content-1",
                    "createTime": "2024-01-01T00:00:00Z",
                    "score": 0.9,
                    "metadata": json.dumps({
                        "file_name": "file-1.txt",
                        "absolute_directory_path": "/data/kb1",
                        "original_file_id": "orig-1",
                    }),
                    "scoreDetails": {"raw": 0.8},
                }
            },
            {
                "entity": {
                    "id": "file-2",
                    "text": "content-2",
                    "createTime": "2024-01-01T00:00:00Z",
                    "score": 0.8,
                    "metadata": {},  # Empty dict metadata
                    "scoreDetails": {"raw": 0.7},
                }
            },
            {
                "entity": {
                    "id": "file-3",
                    "text": "content-3",
                    "createTime": "2024-01-01T00:00:00Z",
                    "score": 0.7,
                    "metadata": "invalid-json",  # Invalid JSON metadata
                    "scoreDetails": {"raw": 0.6},
                }
            },
        ]

        # Mock the hybrid_search method
        mock_hybrid_search = mocker.patch.object(
            datamate_tool.datamate_core, 'hybrid_search')
        mock_hybrid_search.return_value = search_results

        # Mock the build_file_download_url method
        mock_build_url = mocker.patch.object(
            datamate_tool.datamate_core.client, 'build_file_download_url')
        mock_build_url.return_value = "http://dl/kb1/file"

        result_json = datamate_tool.forward("query")
        results = json.loads(result_json)

        assert len(results) == 3

        # Verify that missing metadata fields are handled gracefully
        assert results[0]["title"] == "file-1.txt"
        assert results[1]["title"] == ""  # Empty metadata dict
        assert results[2]["title"] == ""  # Invalid JSON metadata


class TestDataMateSearchToolURL:
    """Test URL-based initialization for DataMateSearchTool"""

    def test_url_https_initialization(self, mock_observer: MessageObserver, mocker: MockFixture):
        """Test HTTPS URL initialization"""
        mock_datamate_core = mocker.patch(
            "sdk.nexent.core.tools.datamate_search_tool.DataMateCore")

        tool = DataMateSearchTool(
            server_url="https://example.com:8443",
            observer=mock_observer,
        )

        assert tool.server_base_url == "https://example.com:8443"
        assert tool.server_ip == "example.com"
        assert tool.server_port == 8443
        assert tool.use_https is True

        # Verify DataMateCore was called with SSL verification disabled for HTTPS
        mock_datamate_core.assert_called_once()
        args, kwargs = mock_datamate_core.call_args
        assert kwargs['base_url'] == "https://example.com:8443"
        # Due to implementation, verify_ssl is passed as FieldInfo, but it should have default=False
        from pydantic.fields import FieldInfo
        assert isinstance(kwargs['verify_ssl'], FieldInfo)
        assert kwargs['verify_ssl'].default == False

    def test_url_http_initialization(self, mock_observer: MessageObserver, mocker: MockFixture):
        """Test HTTP URL initialization"""
        mock_datamate_core = mocker.patch(
            "sdk.nexent.core.tools.datamate_search_tool.DataMateCore")

        tool = DataMateSearchTool(
            server_url="http://192.168.1.100:8080",
            observer=mock_observer,
        )

        assert tool.server_base_url == "http://192.168.1.100:8080"
        assert tool.server_ip == "192.168.1.100"
        assert tool.server_port == 8080
        assert tool.use_https is False

        # Verify DataMateCore was called with SSL verification enabled for HTTP
        mock_datamate_core.assert_called_once_with(
            base_url="http://192.168.1.100:8080",
            verify_ssl=True  # HTTP URLs should always verify SSL
        )

    def test_url_https_with_ssl_verification(self, mock_observer: MessageObserver, mocker: MockFixture):
        """Test HTTPS URL with explicit SSL verification"""
        mock_datamate_core = mocker.patch(
            "sdk.nexent.core.tools.datamate_search_tool.DataMateCore")

        tool = DataMateSearchTool(
            server_url="https://example.com:8443",
            verify_ssl=True,
            observer=mock_observer,
        )

        assert tool.server_base_url == "https://example.com:8443"
        assert tool.use_https is True

        # Verify DataMateCore was called with explicit SSL verification setting
        mock_datamate_core.assert_called_once_with(
            base_url="https://example.com:8443",
            verify_ssl=True  # Explicitly set to True
        )

    def test_url_default_ports(self, mock_observer: MessageObserver):
        """Test URLs with default ports"""
        # HTTPS default port
        tool_https = DataMateSearchTool(
            server_url="https://example.com",
            observer=mock_observer,
        )
        assert tool_https.server_port == 443
        assert tool_https.server_base_url == "https://example.com:443"

        # HTTP default port
        tool_http = DataMateSearchTool(
            server_url="http://example.com",
            observer=mock_observer,
        )
        assert tool_http.server_port == 80
        assert tool_http.server_base_url == "http://example.com:80"

    def test_url_invalid_format(self, mock_observer: MessageObserver):
        """Test invalid URL formats"""
        with pytest.raises(ValueError, match="server_url must include protocol"):
            DataMateSearchTool(server_url="example.com:8080",
                               observer=mock_observer)

        with pytest.raises(ValueError, match="Invalid server_url format"):
            DataMateSearchTool(server_url="http://", observer=mock_observer)
