import json
from typing import List
from unittest.mock import ANY, MagicMock

import httpx
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
    return DataMateSearchTool(
        server_ip="127.0.0.1",
        server_port=8080,
        observer=mock_observer,
    )


def _build_kb_list_response(ids: List[str]):
    return {
        "data": {
            "content": [
                {"id": kb_id, "chunkCount": 1}
                for kb_id in ids
            ]
        }
    }


def _build_search_response(kb_id: str, count: int = 2):
    return {
        "data": [
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
                        }
                    ),
                    "scoreDetails": {"raw": 0.8},
                }
            }
            for i in range(count)
        ]
    }


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
        ],
    )
    def test_extract_dataset_id(self, datamate_tool: DataMateSearchTool, path, expected):
        assert datamate_tool._extract_dataset_id(path) == expected

    @pytest.mark.parametrize(
        "dataset_id, file_id, expected",
        [
            ("ds1", "f1", "127.0.0.1/api/data-management/datasets/ds1/files/f1/download"),
            ("", "f1", ""),
            ("ds1", "", ""),
        ],
    )
    def test_build_file_download_url(self, datamate_tool: DataMateSearchTool, dataset_id, file_id, expected):
        assert datamate_tool._build_file_download_url(dataset_id, file_id) == expected


class TestKnowledgeBaseList:
    def test_get_knowledge_base_list_success(self, mocker: MockFixture, datamate_tool: DataMateSearchTool):
        client_cls = mocker.patch("sdk.nexent.core.tools.datamate_search_tool.httpx.Client")
        client = client_cls.return_value.__enter__.return_value

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = _build_kb_list_response(["kb1", "kb2"])
        client.post.return_value = response

        kb_ids = datamate_tool._get_knowledge_base_list()

        assert kb_ids == ["kb1", "kb2"]
        client.post.assert_called_once_with(
            f"{datamate_tool.server_base_url}/api/knowledge-base/list",
            json={"page": datamate_tool.kb_page, "size": datamate_tool.kb_page_size},
        )

    def test_get_knowledge_base_list_http_error_json_detail(self, mocker: MockFixture, datamate_tool: DataMateSearchTool):
        client_cls = mocker.patch("sdk.nexent.core.tools.datamate_search_tool.httpx.Client")
        client = client_cls.return_value.__enter__.return_value

        response = MagicMock()
        response.status_code = 500
        response.headers = {"content-type": "application/json"}
        response.json.return_value = {"detail": "server error"}
        client.post.return_value = response

        with pytest.raises(Exception) as excinfo:
            datamate_tool._get_knowledge_base_list()

        assert "Failed to get knowledge base list" in str(excinfo.value)

    def test_get_knowledge_base_list_http_error_text_detail(self, mocker: MockFixture, datamate_tool: DataMateSearchTool):
        client_cls = mocker.patch("sdk.nexent.core.tools.datamate_search_tool.httpx.Client")
        client = client_cls.return_value.__enter__.return_value

        response = MagicMock()
        response.status_code = 400
        response.headers = {"content-type": "text/plain"}
        response.text = "bad request"
        client.post.return_value = response

        with pytest.raises(Exception) as excinfo:
            datamate_tool._get_knowledge_base_list()

        assert "bad request" in str(excinfo.value)

    def test_get_knowledge_base_list_timeout(self, mocker: MockFixture, datamate_tool: DataMateSearchTool):
        client_cls = mocker.patch("sdk.nexent.core.tools.datamate_search_tool.httpx.Client")
        client = client_cls.return_value.__enter__.return_value
        client.post.side_effect = httpx.TimeoutException("timeout")

        with pytest.raises(Exception) as excinfo:
            datamate_tool._get_knowledge_base_list()

        assert "Timeout while getting knowledge base list" in str(excinfo.value)

    def test_get_knowledge_base_list_request_error(self, mocker: MockFixture, datamate_tool: DataMateSearchTool):
        client_cls = mocker.patch("sdk.nexent.core.tools.datamate_search_tool.httpx.Client")
        client = client_cls.return_value.__enter__.return_value
        client.post.side_effect = httpx.RequestError("network", request=MagicMock())

        with pytest.raises(Exception) as excinfo:
            datamate_tool._get_knowledge_base_list()

        assert "Request error while getting knowledge base list" in str(excinfo.value)


class TestRetrieveKnowledgeBaseContent:
    def test_retrieve_content_success(self, mocker: MockFixture, datamate_tool: DataMateSearchTool):
        client_cls = mocker.patch("sdk.nexent.core.tools.datamate_search_tool.httpx.Client")
        client = client_cls.return_value.__enter__.return_value

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = _build_search_response("kb1", count=2)
        client.post.return_value = response

        results = datamate_tool._retrieve_knowledge_base_content(
            "query",
            ["kb1"],
            top_k=3,
            threshold=0.2,
        )

        assert len(results) == 2
        client.post.assert_called_once()

    def test_retrieve_content_http_error(self, mocker: MockFixture, datamate_tool: DataMateSearchTool):
        client_cls = mocker.patch("sdk.nexent.core.tools.datamate_search_tool.httpx.Client")
        client = client_cls.return_value.__enter__.return_value

        response = MagicMock()
        response.status_code = 500
        response.headers = {"content-type": "application/json"}
        response.json.return_value = {"detail": "server error"}
        client.post.return_value = response

        with pytest.raises(Exception) as excinfo:
            datamate_tool._retrieve_knowledge_base_content(
                "query",
                ["kb1"],
                top_k=3,
                threshold=0.2,
            )

        assert "Failed to retrieve knowledge base content" in str(excinfo.value)

    def test_retrieve_content_timeout(self, mocker: MockFixture, datamate_tool: DataMateSearchTool):
        client_cls = mocker.patch("sdk.nexent.core.tools.datamate_search_tool.httpx.Client")
        client = client_cls.return_value.__enter__.return_value
        client.post.side_effect = httpx.TimeoutException("timeout")

        with pytest.raises(Exception) as excinfo:
            datamate_tool._retrieve_knowledge_base_content(
                "query",
                ["kb1"],
                top_k=3,
                threshold=0.2,
            )

        assert "Timeout while retrieving knowledge base content" in str(excinfo.value)

    def test_retrieve_content_request_error(self, mocker: MockFixture, datamate_tool: DataMateSearchTool):
        client_cls = mocker.patch("sdk.nexent.core.tools.datamate_search_tool.httpx.Client")
        client = client_cls.return_value.__enter__.return_value
        client.post.side_effect = httpx.RequestError("network", request=MagicMock())

        with pytest.raises(Exception) as excinfo:
            datamate_tool._retrieve_knowledge_base_content(
                "query",
                ["kb1"],
                top_k=3,
                threshold=0.2,
            )

        assert "Request error while retrieving knowledge base content" in str(excinfo.value)


class TestForward:
    def _setup_success_flow(self, mocker: MockFixture, tool: DataMateSearchTool):
        # Mock knowledge base list
        client_cls = mocker.patch("sdk.nexent.core.tools.datamate_search_tool.httpx.Client")
        client = client_cls.return_value.__enter__.return_value

        kb_response = MagicMock()
        kb_response.status_code = 200
        kb_response.json.return_value = _build_kb_list_response(["kb1"])

        search_response = MagicMock()
        search_response.status_code = 200
        search_response.json.return_value = _build_search_response("kb1", count=2)

        # First call for list, second for retrieve
        client.post.side_effect = [kb_response, search_response]
        return client

    def test_forward_success_with_observer_en(self, mocker: MockFixture, datamate_tool: DataMateSearchTool):
        client = self._setup_success_flow(mocker, datamate_tool)

        result_json = datamate_tool.forward("test query", top_k=2, threshold=0.5)
        results = json.loads(result_json)

        assert len(results) == 2
        # Check that observer received running prompt and card
        datamate_tool.observer.add_message.assert_any_call(
            "", ProcessType.TOOL, datamate_tool.running_prompt_en
        )
        datamate_tool.observer.add_message.assert_any_call(
            "", ProcessType.CARD, json.dumps([{"icon": "search", "text": "test query"}], ensure_ascii=False)
        )
        # Check that search content message is added (payload content is not strictly validated here)
        datamate_tool.observer.add_message.assert_any_call(
            "", ProcessType.SEARCH_CONTENT, ANY
        )
        assert datamate_tool.record_ops == 1 + len(results)
        assert all(isinstance(item["index"], str) for item in results)

        # Ensure both list and retrieve endpoints were called
        assert client.post.call_count == 2

    def test_forward_success_with_observer_zh(self, mocker: MockFixture, datamate_tool: DataMateSearchTool):
        datamate_tool.observer.lang = "zh"
        self._setup_success_flow(mocker, datamate_tool)

        datamate_tool.forward("测试查询")

        datamate_tool.observer.add_message.assert_any_call(
            "", ProcessType.TOOL, datamate_tool.running_prompt_zh
        )

    def test_forward_no_observer(self, mocker: MockFixture):
        tool = DataMateSearchTool(server_ip="127.0.0.1", server_port=8080, observer=None)
        self._setup_success_flow(mocker, tool)

        # Should not raise and should not call observer
        result_json = tool.forward("query")
        assert len(json.loads(result_json)) == 2

    def test_forward_no_knowledge_bases(self, mocker: MockFixture, datamate_tool: DataMateSearchTool):
        client_cls = mocker.patch("sdk.nexent.core.tools.datamate_search_tool.httpx.Client")
        client = client_cls.return_value.__enter__.return_value

        kb_response = MagicMock()
        kb_response.status_code = 200
        kb_response.json.return_value = _build_kb_list_response([])
        client.post.return_value = kb_response

        result = datamate_tool.forward("query")
        assert result == json.dumps("No knowledge base found. No relevant information found.", ensure_ascii=False)

    def test_forward_no_results(self, mocker: MockFixture, datamate_tool: DataMateSearchTool):
        client_cls = mocker.patch("sdk.nexent.core.tools.datamate_search_tool.httpx.Client")
        client = client_cls.return_value.__enter__.return_value

        kb_response = MagicMock()
        kb_response.status_code = 200
        kb_response.json.return_value = _build_kb_list_response(["kb1"])

        search_response = MagicMock()
        search_response.status_code = 200
        search_response.json.return_value = {"data": []}

        client.post.side_effect = [kb_response, search_response]

        with pytest.raises(Exception) as excinfo:
            datamate_tool.forward("query")

        assert "No results found!" in str(excinfo.value)

    def test_forward_wrapped_error(self, mocker: MockFixture, datamate_tool: DataMateSearchTool):
        # Simulate error in underlying method to verify top-level error wrapping
        mocker.patch.object(
            datamate_tool,
            "_get_knowledge_base_list",
            side_effect=Exception("low level error"),
        )

        with pytest.raises(Exception) as excinfo:
            datamate_tool.forward("query")

        msg = str(excinfo.value)
        assert "Error during DataMate knowledge base search" in msg
        assert "low level error" in msg


