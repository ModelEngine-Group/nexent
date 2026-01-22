import json
from typing import List
from unittest.mock import ANY, MagicMock

import pytest
from pytest_mock import MockFixture

from sdk.nexent.core.tools.datamate_search_tool import DataMateSearchTool, _normalize_index_names
from sdk.nexent.core.utils.observer import MessageObserver, ProcessType
from sdk.nexent.datamate.datamate_client import DataMateClient


@pytest.fixture
def mock_observer() -> MessageObserver:
    observer = MagicMock(spec=MessageObserver)
    observer.lang = "en"
    return observer




@pytest.fixture
def datamate_tool(mock_observer: MessageObserver) -> DataMateSearchTool:
    tool = DataMateSearchTool(
        server_ip="127.0.0.1",
        server_port=8080,
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
    def test_init_success(self, mock_observer: MessageObserver):
        tool = DataMateSearchTool(
            server_ip=" datamate.local ",
            server_port=1234,
            observer=mock_observer,
        )

        assert tool.server_ip == "datamate.local"
        assert tool.server_port == 1234
        assert tool.server_base_url == "http://datamate.local:1234"
        assert tool.kb_page == 0
        assert tool.kb_page_size == 20
        assert tool.observer is mock_observer
        # index_names is excluded from the model, so we can't directly test it
        # The tool exposes the DataMate client via datamate_core.client
        assert isinstance(tool.datamate_core.client, DataMateClient)

    def test_init_with_index_names(self, mock_observer: MessageObserver):
        """Test initialization with custom index_names."""
        custom_index_names = ["kb1", "kb2"]
        tool = DataMateSearchTool(
            server_ip="127.0.0.1",
            server_port=8080,
            index_names=custom_index_names,
            observer=mock_observer,
        )

        assert tool.index_names == custom_index_names

    @pytest.mark.parametrize("server_ip", ["", None])
    def test_init_invalid_server_ip(self, server_ip):
        with pytest.raises(ValueError) as excinfo:
            DataMateSearchTool(server_ip=server_ip, server_port=8080)
        assert "server_ip is required" in str(excinfo.value)

    @pytest.mark.parametrize("server_port", [0, 65536, "8080"])
    def test_init_invalid_server_port(self, server_port):
        with pytest.raises(ValueError) as excinfo:
            DataMateSearchTool(server_ip="127.0.0.1", server_port=server_port)
        assert "server_port must be an integer between 1 and 65535" in str(excinfo.value)


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
            ("///multiple///slashes///", "slashes"),  # After filtering empty segments, last is "slashes"
        ],
    )
    def test_extract_dataset_id(self, datamate_tool: DataMateSearchTool, path, expected):
        assert datamate_tool._extract_dataset_id(path) == expected


class TestNormalizeIndexNames:
    @pytest.mark.parametrize(
        "input_names, expected",
        [
            (None, []),
            ("single_kb", ["single_kb"]),
            (["kb1", "kb2"], ["kb1", "kb2"]),
            ([], []),
            ("", [""]),  # Edge case: empty string becomes list with empty string
        ],
    )
    def test_normalize_index_names(self, input_names, expected):
        result = _normalize_index_names(input_names)
        assert result == expected


class TestForward:
    def test_forward_success_with_observer_en(self, datamate_tool: DataMateSearchTool, mocker: MockFixture):
        # Mock the hybrid_search method to return search results
        mock_hybrid_search = mocker.patch.object(datamate_tool.datamate_core, 'hybrid_search')
        mock_hybrid_search.return_value = _build_search_results("kb1", count=2)

        # Mock the build_file_download_url method
        mock_build_url = mocker.patch.object(datamate_tool.datamate_core.client, 'build_file_download_url')
        mock_build_url.side_effect = lambda ds, fid: f"http://dl/{ds}/{fid}"

        result_json = datamate_tool.forward("test query", index_names=["kb1"], top_k=2, threshold=0.5)
        results = json.loads(result_json)

        assert len(results) == 2
        datamate_tool.observer.add_message.assert_any_call("", ProcessType.TOOL, datamate_tool.running_prompt_en)
        datamate_tool.observer.add_message.assert_any_call(
            "", ProcessType.CARD, json.dumps([{"icon": "search", "text": "test query"}], ensure_ascii=False)
        )
        datamate_tool.observer.add_message.assert_any_call("", ProcessType.SEARCH_CONTENT, ANY)
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
        mock_hybrid_search = mocker.patch.object(datamate_tool.datamate_core, 'hybrid_search')
        mock_hybrid_search.return_value = _build_search_results("kb1", count=1)

        # Mock the build_file_download_url method
        mock_build_url = mocker.patch.object(datamate_tool.datamate_core.client, 'build_file_download_url')
        mock_build_url.return_value = "http://dl/kb1/file-1"

        datamate_tool.forward("测试查询", index_names=["kb1"])

        datamate_tool.observer.add_message.assert_any_call("", ProcessType.TOOL, datamate_tool.running_prompt_zh)

    def test_forward_no_observer(self, mocker: MockFixture):
        tool = DataMateSearchTool(server_ip="127.0.0.1", server_port=8080, observer=None)

        # Mock the hybrid_search method to return search results
        mock_hybrid_search = mocker.patch.object(tool.datamate_core, 'hybrid_search')
        mock_hybrid_search.return_value = _build_search_results("kb1", count=1)

        # Mock the build_file_download_url method
        mock_build_url = mocker.patch.object(tool.datamate_core.client, 'build_file_download_url')
        mock_build_url.return_value = "http://dl/kb1/file-1"

        result_json = tool.forward("query", index_names=["kb1"])
        assert len(json.loads(result_json)) == 1

    def test_forward_no_knowledge_bases(self, datamate_tool: DataMateSearchTool, mocker: MockFixture):
        # Mock the hybrid_search method
        mock_hybrid_search = mocker.patch.object(datamate_tool.datamate_core, 'hybrid_search')

        result = datamate_tool.forward("query", index_names=[])
        assert result == json.dumps("No knowledge base selected. No relevant information found.", ensure_ascii=False)
        mock_hybrid_search.assert_not_called()

    def test_forward_no_results(self, datamate_tool: DataMateSearchTool, mocker: MockFixture):
        # Mock the hybrid_search method to return empty results
        mock_hybrid_search = mocker.patch.object(datamate_tool.datamate_core, 'hybrid_search')
        mock_hybrid_search.return_value = []

        with pytest.raises(Exception) as excinfo:
            datamate_tool.forward("query", index_names=["kb1"])

        assert "No results found! Try a less restrictive/shorter query." in str(excinfo.value)

    def test_forward_wrapped_error(self, datamate_tool: DataMateSearchTool, mocker: MockFixture):
        # Mock the hybrid_search method to raise an error
        mock_hybrid_search = mocker.patch.object(datamate_tool.datamate_core, 'hybrid_search')
        mock_hybrid_search.side_effect = RuntimeError("low level error")

        with pytest.raises(Exception) as excinfo:
            datamate_tool.forward("query", index_names=["kb1"])

        msg = str(excinfo.value)
        assert "Error during DataMate knowledge base search" in msg
        assert "low level error" in msg

    def test_forward_with_default_index_names(self, datamate_tool: DataMateSearchTool, mocker: MockFixture):
        """Test forward method using default index_names from constructor."""
        # Set default index_names in the tool
        datamate_tool.index_names = ["default_kb1", "default_kb2"]

        # Mock the hybrid_search method to return results for each knowledge base
        mock_hybrid_search = mocker.patch.object(datamate_tool.datamate_core, 'hybrid_search')
        mock_hybrid_search.side_effect = [
            _build_search_results("default_kb1", count=1),  # First call returns results for kb1
            _build_search_results("default_kb2", count=1),  # Second call returns results for kb2
        ]

        # Mock the build_file_download_url method
        mock_build_url = mocker.patch.object(datamate_tool.datamate_core.client, 'build_file_download_url')
        mock_build_url.return_value = "http://dl/default_kb/file-1"

        result_json = datamate_tool.forward("query")
        results = json.loads(result_json)

        assert len(results) == 2  # One result from each knowledge base
        assert mock_hybrid_search.call_count == 2
        mock_hybrid_search.assert_any_call(
            query_text="query",
            index_names=["default_kb1"],
            top_k=10,
            weight_accurate=0.2
        )
        mock_hybrid_search.assert_any_call(
            query_text="query",
            index_names=["default_kb2"],
            top_k=10,
            weight_accurate=0.2
        )

    def test_forward_multiple_knowledge_bases(self, datamate_tool: DataMateSearchTool, mocker: MockFixture):
        """Test forward method with multiple knowledge bases."""
        # Mock the hybrid_search method to return results from multiple KBs
        mock_hybrid_search = mocker.patch.object(datamate_tool.datamate_core, 'hybrid_search')
        mock_hybrid_search.side_effect = [
            _build_search_results("kb1", count=1),  # First call returns results from kb1
            _build_search_results("kb2", count=2),  # Second call returns results from kb2
        ]

        # Mock the build_file_download_url method
        mock_build_url = mocker.patch.object(datamate_tool.datamate_core.client, 'build_file_download_url')
        mock_build_url.side_effect = lambda ds, fid: f"http://dl/{ds}/{fid}"

        result_json = datamate_tool.forward("query", index_names=["kb1", "kb2"])
        results = json.loads(result_json)

        assert len(results) == 3  # 1 from kb1 + 2 from kb2

        # Verify hybrid_search was called for each knowledge base
        assert mock_hybrid_search.call_count == 2
        mock_hybrid_search.assert_any_call(
            query_text="query",
            index_names=["kb1"],
            top_k=10,
            weight_accurate=0.2
        )
        mock_hybrid_search.assert_any_call(
            query_text="query",
            index_names=["kb2"],
            top_k=10,
            weight_accurate=0.2
        )

    def test_forward_with_custom_parameters(self, datamate_tool: DataMateSearchTool, mocker: MockFixture):
        """Test forward method with custom parameters."""
        # Mock the hybrid_search method
        mock_hybrid_search = mocker.patch.object(datamate_tool.datamate_core, 'hybrid_search')
        mock_hybrid_search.return_value = _build_search_results("kb1", count=1)

        # Mock the build_file_download_url method
        mock_build_url = mocker.patch.object(datamate_tool.datamate_core.client, 'build_file_download_url')
        mock_build_url.return_value = "http://dl/kb1/file-1"

        result_json = datamate_tool.forward(
            query="custom query",
            index_names=["kb1"],
            top_k=5,
            threshold=0.8,
            kb_page=2,
            kb_page_size=50
        )
        results = json.loads(result_json)

        assert len(results) == 1
        assert datamate_tool.kb_page == 2
        assert datamate_tool.kb_page_size == 50

        mock_hybrid_search.assert_called_once_with(
            query_text="custom query",
            index_names=["kb1"],
            top_k=5,
            weight_accurate=0.8
        )

    def test_forward_metadata_parsing_edge_cases(self, datamate_tool: DataMateSearchTool, mocker: MockFixture):
        """Test forward method with various metadata parsing edge cases."""
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
        mock_hybrid_search = mocker.patch.object(datamate_tool.datamate_core, 'hybrid_search')
        mock_hybrid_search.return_value = search_results

        # Mock the build_file_download_url method
        mock_build_url = mocker.patch.object(datamate_tool.datamate_core.client, 'build_file_download_url')
        mock_build_url.return_value = "http://dl/kb1/file"

        result_json = datamate_tool.forward("query", index_names=["kb1"])
        results = json.loads(result_json)

        assert len(results) == 3

        # Verify that missing metadata fields are handled gracefully
        assert results[0]["title"] == "file-1.txt"
        assert results[1]["title"] == ""  # Empty metadata dict
        assert results[2]["title"] == ""  # Invalid JSON metadata
