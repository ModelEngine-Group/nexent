import json
from typing import List
from unittest.mock import ANY, MagicMock

import pytest
from pytest_mock import MockFixture

from sdk.nexent.core.tools.datamate_search_tool import DataMateSearchTool
from sdk.nexent.core.utils.observer import MessageObserver, ProcessType
from sdk.nexent.datamate.datamate_client import DataMateClient


@pytest.fixture
def mock_observer() -> MessageObserver:
    observer = MagicMock(spec=MessageObserver)
    observer.lang = "en"
    return observer


@pytest.fixture
def mock_datamate_client(mocker: MockFixture) -> DataMateClient:
    return mocker.MagicMock(spec=DataMateClient)


@pytest.fixture
def datamate_tool(mock_observer: MessageObserver, mock_datamate_client: DataMateClient) -> DataMateSearchTool:
    tool = DataMateSearchTool(
        server_ip="127.0.0.1",
        server_port=8080,
        index_names=None,
        observer=mock_observer,
    )
    # DataMateSearchTool stores a DataMateCore instance which exposes a `client` attribute.
    # Set the client's mock on the tool's datamate_core to reflect current implementation.
    tool.datamate_core.client = mock_datamate_client
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
            index_names=None,
            observer=mock_observer,
        )

        assert tool.server_ip == "datamate.local"
        assert tool.server_port == 1234
        assert tool.server_base_url == "http://datamate.local:1234"
        assert tool.kb_page == 0
        assert tool.kb_page_size == 20
        assert tool.observer is mock_observer
        assert tool.index_names == []  # Default empty list
        # The tool exposes the DataMate client via datamate_core.client
        assert isinstance(tool.datamate_core.client, DataMateClient)

    def test_init_with_index_names(self, mock_observer: MessageObserver):
        tool = DataMateSearchTool(
            server_ip="datamate.local",
            server_port=1234,
            index_names=["kb1", "kb2"],
            observer=mock_observer,
        )

        assert tool.index_names == ["kb1", "kb2"]

    @pytest.mark.parametrize("server_ip", ["", None])
    def test_init_invalid_server_ip(self, server_ip):
        with pytest.raises(ValueError) as excinfo:
            DataMateSearchTool(server_ip=server_ip, server_port=8080)
        assert "server_ip is required" in str(excinfo.value)

    @pytest.mark.parametrize("server_port", [0, 65536, "8080"])
    def test_init_invalid_server_port(self, server_port):
        with pytest.raises(ValueError) as excinfo:
            DataMateSearchTool(server_ip="127.0.0.1", server_port=server_port)
        assert "server_port must be an integer between 1 and 65535" in str(
            excinfo.value)


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
        ],
    )
    def test_extract_dataset_id(self, datamate_tool: DataMateSearchTool, path, expected):
        assert datamate_tool._extract_dataset_id(path) == expected

    @pytest.mark.parametrize(
        "index_names, expected",
        [
            (None, []),
            ([], []),
            ("single_kb", ["single_kb"]),
            (["kb1", "kb2"], ["kb1", "kb2"]),
            (["kb1"], ["kb1"]),
        ],
    )
    def test_normalize_index_names(self, datamate_tool: DataMateSearchTool, index_names, expected):
        result = datamate_tool._normalize_index_names(index_names)
        assert result == expected


class TestForward:
    def test_forward_success_with_observer_en(self, datamate_tool: DataMateSearchTool, mock_datamate_client: DataMateClient):
        mock_datamate_client.list_knowledge_bases.return_value = _build_kb_list([
                                                                                "kb1"])
        mock_datamate_client.retrieve_knowledge_base.return_value = _build_search_results(
            "kb1", count=2)
        mock_datamate_client.build_file_download_url.side_effect = lambda ds, fid: f"http://dl/{ds}/{fid}"

        result_json = datamate_tool.forward(
            "test query", top_k=2, threshold=0.5)
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

        mock_datamate_client.list_knowledge_bases.assert_called_once_with(
            page=0, size=20)
        # Support both positional and keyword invocation styles from DataMate client wrapper.
        mock_datamate_client.retrieve_knowledge_base.assert_called_once()
        _args, _kwargs = mock_datamate_client.retrieve_knowledge_base.call_args
        if _args:
            assert _args[0] == "test query"
            assert _args[1] == ["kb1"]
            assert _args[2] == 2
            assert _args[3] == 0.5
        else:
            assert _kwargs["query"] == "test query"
            assert _kwargs["knowledge_base_ids"] == ["kb1"]
            assert _kwargs["top_k"] == 2
            assert _kwargs["threshold"] == 0.5
        mock_datamate_client.build_file_download_url.assert_any_call(
            "kb1", "orig-0")

    def test_forward_success_with_observer_zh(self, datamate_tool: DataMateSearchTool, mock_datamate_client: DataMateClient):
        datamate_tool.observer.lang = "zh"
        mock_datamate_client.list_knowledge_bases.return_value = _build_kb_list([
                                                                                "kb1"])
        mock_datamate_client.retrieve_knowledge_base.return_value = _build_search_results(
            "kb1", count=1)
        mock_datamate_client.build_file_download_url.return_value = "http://dl/kb1/file-1"

        datamate_tool.forward("测试查询")

        datamate_tool.observer.add_message.assert_any_call(
            "", ProcessType.TOOL, datamate_tool.running_prompt_zh)

    def test_forward_no_observer(self, mock_datamate_client: DataMateClient):
        tool = DataMateSearchTool(
            server_ip="127.0.0.1", server_port=8080, index_names=None, observer=None)
        tool.datamate_core.client = mock_datamate_client
        mock_datamate_client.list_knowledge_bases.return_value = _build_kb_list([
                                                                                "kb1"])
        mock_datamate_client.retrieve_knowledge_base.return_value = _build_search_results(
            "kb1", count=1)
        mock_datamate_client.build_file_download_url.return_value = "http://dl/kb1/file-1"

        result_json = tool.forward("query")
        assert len(json.loads(result_json)) == 1

    def test_forward_no_knowledge_bases(self, datamate_tool: DataMateSearchTool, mock_datamate_client: DataMateClient):
        mock_datamate_client.list_knowledge_bases.return_value = []

        result = datamate_tool.forward("query")
        assert result == json.dumps(
            "No knowledge base found. No relevant information found.", ensure_ascii=False)
        mock_datamate_client.retrieve_knowledge_base.assert_not_called()

    def test_forward_no_results(self, datamate_tool: DataMateSearchTool, mock_datamate_client: DataMateClient):
        mock_datamate_client.list_knowledge_bases.return_value = _build_kb_list([
                                                                                "kb1"])
        mock_datamate_client.retrieve_knowledge_base.return_value = []

        with pytest.raises(Exception) as excinfo:
            datamate_tool.forward("query")

        assert "No results found!" in str(excinfo.value)

    def test_forward_with_provided_index_names(self, datamate_tool: DataMateSearchTool, mock_datamate_client: DataMateClient):
        """Test forward method when index_names are provided as parameter."""
        mock_datamate_client.retrieve_knowledge_base.return_value = _build_search_results(
            "custom_kb", count=1)
        mock_datamate_client.build_file_download_url.return_value = "http://dl/custom_kb/file-1"

        result_json = datamate_tool.forward(
            "test query", index_names=["custom_kb"])
        results = json.loads(result_json)

        assert len(results) == 1
        # Verify that list_knowledge_bases was not called since index_names were provided
        mock_datamate_client.list_knowledge_bases.assert_not_called()
        # Verify retrieve_knowledge_base was called with provided index_names
        mock_datamate_client.retrieve_knowledge_base.assert_called_once()
        _args, _kwargs = mock_datamate_client.retrieve_knowledge_base.call_args
        if _args:
            assert _args[1] == ["custom_kb"]
        else:
            assert _kwargs["knowledge_base_ids"] == ["custom_kb"]

    def test_forward_with_single_index_name_string(self, datamate_tool: DataMateSearchTool, mock_datamate_client: DataMateClient):
        """Test forward method when index_names is provided as a single string."""
        mock_datamate_client.retrieve_knowledge_base.return_value = _build_search_results(
            "single_kb", count=1)
        mock_datamate_client.build_file_download_url.return_value = "http://dl/single_kb/file-1"

        result_json = datamate_tool.forward(
            "test query", index_names="single_kb")
        results = json.loads(result_json)

        assert len(results) == 1
        mock_datamate_client.list_knowledge_bases.assert_not_called()
        mock_datamate_client.retrieve_knowledge_base.assert_called_once()
        _args, _kwargs = mock_datamate_client.retrieve_knowledge_base.call_args
        if _args:
            assert _args[1] == ["single_kb"]
        else:
            assert _kwargs["knowledge_base_ids"] == ["single_kb"]

    def test_forward_with_init_index_names(self, mock_observer: MessageObserver, mock_datamate_client: DataMateClient):
        """Test forward method using index_names set during initialization."""
        tool = DataMateSearchTool(
            server_ip="127.0.0.1",
            server_port=8080,
            index_names=["init_kb1", "init_kb2"],
            observer=mock_observer,
        )
        tool.datamate_core.client = mock_datamate_client
        # Mock to return results for each knowledge base
        mock_datamate_client.retrieve_knowledge_base.side_effect = lambda *args, **kwargs: _build_search_results(
            "init_kb1", count=1)
        mock_datamate_client.build_file_download_url.return_value = "http://dl/init_kb1/file-1"

        result_json = tool.forward("test query")
        results = json.loads(result_json)

        # Should get 1 result from each of the 2 knowledge bases
        assert len(results) == 2
        mock_datamate_client.list_knowledge_bases.assert_not_called()
        # Should be called twice, once for each knowledge base
        assert mock_datamate_client.retrieve_knowledge_base.call_count == 2

    def test_forward_wrapped_error(self, datamate_tool: DataMateSearchTool, mock_datamate_client: DataMateClient):
        mock_datamate_client.list_knowledge_bases.side_effect = RuntimeError(
            "low level error")

        with pytest.raises(Exception) as excinfo:
            datamate_tool.forward("query")

        msg = str(excinfo.value)
        assert "Error during DataMate knowledge base search" in msg
        assert "low level error" in msg
