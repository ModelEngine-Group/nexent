import pytest
from unittest.mock import MagicMock

import httpx
from pytest_mock import MockFixture

from sdk.nexent.datamate.datamate_client import DataMateClient


@pytest.fixture
def client() -> DataMateClient:
    return DataMateClient(base_url="http://datamate.local:30000", timeout=1.0)


def _mock_response(mocker: MockFixture, status: int, json_data=None, text: str = ""):
    response = MagicMock()
    response.status_code = status
    response.headers = {"content-type": "application/json"} if json_data is not None else {"content-type": "text/plain"}
    response.json.return_value = json_data
    response.text = text
    return response


class TestListKnowledgeBases:
    def test_success(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.post.return_value = _mock_response(
            mocker,
            200,
            {"data": {"content": [{"id": "kb1"}, {"id": "kb2"}]}},
        )

        kbs = client.list_knowledge_bases(page=1, size=10, authorization="token")

        assert len(kbs) == 2
        http_client.post.assert_called_once_with(
            "http://datamate.local:30000/api/knowledge-base/list",
            json={"page": 1, "size": 10},
            headers={"Authorization": "token"},
        )

    def test_non_200_json_error(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.post.return_value = _mock_response(
            mocker,
            500,
            {"detail": "boom"},
        )

        with pytest.raises(RuntimeError) as excinfo:
            client.list_knowledge_bases()
        assert "Failed to fetch DataMate knowledge bases" in str(excinfo.value)

    def test_http_error(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.post.side_effect = httpx.HTTPError("network")

        with pytest.raises(RuntimeError):
            client.list_knowledge_bases()


class TestGetKnowledgeBaseFiles:
    def test_success(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.get.return_value = _mock_response(
            mocker,
            200,
            {"data": {"content": [{"id": "f1"}, {"id": "f2"}]}},
        )

        files = client.get_knowledge_base_files("kb1")

        assert len(files) == 2
        http_client.get.assert_called_once_with(
            "http://datamate.local:30000/api/knowledge-base/kb1/files",
            headers={},
        )

    def test_non_200(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.get.return_value = _mock_response(
            mocker,
            404,
            {"detail": "not found"},
        )

        with pytest.raises(RuntimeError):
            client.get_knowledge_base_files("kb1")

    def test_http_error(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.get.side_effect = httpx.HTTPError("network")

        with pytest.raises(RuntimeError):
            client.get_knowledge_base_files("kb1")


class TestRetrieveKnowledgeBase:
    def test_success(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.post.return_value = _mock_response(
            mocker,
            200,
            {"data": [{"entity": {"id": "1"}}, {"entity": {"id": "2"}}]},
        )

        results = client.retrieve_knowledge_base("q", ["kb1"], top_k=5, threshold=0.1, authorization="auth")

        assert len(results) == 2
        http_client.post.assert_called_once_with(
            "http://datamate.local:30000/api/knowledge-base/retrieve",
            json={
                "query": "q",
                "topK": 5,
                "threshold": 0.1,
                "knowledgeBaseIds": ["kb1"],
            },
            headers={"Authorization": "auth"},
        )

    def test_non_200(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.post.return_value = _mock_response(
            mocker,
            500,
            {"detail": "error"},
        )

        with pytest.raises(RuntimeError):
            client.retrieve_knowledge_base("q", ["kb1"])

    def test_http_error(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.post.side_effect = httpx.HTTPError("network")

        with pytest.raises(RuntimeError):
            client.retrieve_knowledge_base("q", ["kb1"])


class TestBuildFileDownloadUrl:
    def test_build_url(self, client: DataMateClient):
        assert client.build_file_download_url("ds1", "f1") == \
               "http://datamate.local:30000/api/data-management/datasets/ds1/files/f1/download"

    def test_missing_parts(self, client: DataMateClient):
        assert client.build_file_download_url("", "f1") == ""
        assert client.build_file_download_url("ds1", "") == ""


class TestSyncAllKnowledgeBases:
    def test_success_and_partial_error(self, mocker: MockFixture, client: DataMateClient):
        mocker.patch.object(client, "list_knowledge_bases", return_value=[{"id": "kb1"}, {"id": "kb2"}])
        mocker.patch.object(client, "get_knowledge_base_files", side_effect=[["f1"], RuntimeError("oops")])

        result = client.sync_all_knowledge_bases()

        assert result["success"] is True
        assert result["total_count"] == 2
        assert result["knowledge_bases"][0]["files"] == ["f1"]
        assert result["knowledge_bases"][1]["files"] == []
        assert "oops" in result["knowledge_bases"][1]["error"]

    def test_sync_failure(self, mocker: MockFixture, client: DataMateClient):
        mocker.patch.object(client, "list_knowledge_bases", side_effect=RuntimeError("boom"))

        result = client.sync_all_knowledge_bases()

        assert result["success"] is False
        assert result["total_count"] == 0
        assert "boom" in result["error"]


class TestGetKnowledgeBaseInfo:
    def test_success(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.get.return_value = _mock_response(
            mocker,
            200,
            {"data": {"id": "kb1", "name": "KB1"}},
        )

        kb = client.get_knowledge_base_info("kb1")

        assert isinstance(kb, dict)
        assert kb["id"] == "kb1"
        http_client.get.assert_called_once_with(
            "http://datamate.local:30000/api/knowledge-base/kb1",
            headers={},
        )

    def test_success_with_authorization(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.get.return_value = _mock_response(
            mocker,
            200,
            {"data": {"id": "kb1", "name": "KB1"}},
        )

        kb = client.get_knowledge_base_info("kb1", authorization="Bearer token123")

        assert isinstance(kb, dict)
        assert kb["id"] == "kb1"
        http_client.get.assert_called_once_with(
            "http://datamate.local:30000/api/knowledge-base/kb1",
            headers={"Authorization": "Bearer token123"},
        )

    def test_empty_data(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.get.return_value = _mock_response(
            mocker,
            200,
            {"data": {}},
        )

        kb = client.get_knowledge_base_info("kb1")
        assert kb == {}

    def test_non_200_json_error(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.get.return_value = _mock_response(
            mocker,
            500,
            {"detail": "boom"},
            text="",
        )

        with pytest.raises(RuntimeError) as excinfo:
            client.get_knowledge_base_info("kb1")

        assert "Failed to fetch details for datamate knowledge base kb1" in str(excinfo.value)
        assert "Failed to get knowledge base details" in str(excinfo.value)

    def test_non_200_text_error(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        # simulate plain text error response
        resp = _mock_response(mocker, 404, None, text="not found")
        # override headers to be text/plain
        resp.headers = {"content-type": "text/plain"}
        http_client.get.return_value = resp

        with pytest.raises(RuntimeError) as excinfo:
            client.get_knowledge_base_info("kb1")

        assert "Failed to fetch details for datamate knowledge base kb1" in str(excinfo.value)
        assert "not found" in str(excinfo.value)

    def test_http_error_raised(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.get.side_effect = httpx.HTTPError("network")

        with pytest.raises(RuntimeError) as excinfo:
            client.get_knowledge_base_info("kb1")

        assert "Failed to fetch details for datamate knowledge base kb1" in str(excinfo.value)
        assert "network" in str(excinfo.value)


class TestBuildHeaders:
    """Test the internal _build_headers method."""

    def test_with_authorization(self, client: DataMateClient):
        headers = client._build_headers("Bearer token123")
        assert headers == {"Authorization": "Bearer token123"}

    def test_without_authorization(self, client: DataMateClient):
        headers = client._build_headers()
        assert headers == {}

    def test_with_none_authorization(self, client: DataMateClient):
        headers = client._build_headers(None)
        assert headers == {}


class TestBuildUrl:
    """Test the internal _build_url method."""

    def test_path_with_leading_slash(self, client: DataMateClient):
        url = client._build_url("/api/test")
        assert url == "http://datamate.local:30000/api/test"

    def test_path_without_leading_slash(self, client: DataMateClient):
        url = client._build_url("api/test")
        assert url == "http://datamate.local:30000/api/test"

    def test_base_url_without_trailing_slash(self, client: DataMateClient):
        # base_url is already stripped of trailing slash in __init__
        url = client._build_url("/api/test")
        assert url == "http://datamate.local:30000/api/test"


class TestMakeRequest:
    """Test the internal _make_request method."""

    def test_get_request_success(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.get.return_value = _mock_response(mocker, 200, {"result": "ok"})

        response = client._make_request("GET", "http://test.com/api", {"X-Header": "value"})

        assert response.status_code == 200
        http_client.get.assert_called_once_with("http://test.com/api", headers={"X-Header": "value"})

    def test_post_request_success(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.post.return_value = _mock_response(mocker, 200, {"result": "ok"})

        response = client._make_request(
            "POST", "http://test.com/api", {"X-Header": "value"}, json={"key": "value"}
        )

        assert response.status_code == 200
        http_client.post.assert_called_once_with(
            "http://test.com/api", json={"key": "value"}, headers={"X-Header": "value"}
        )

    def test_custom_timeout(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.get.return_value = _mock_response(mocker, 200, {"result": "ok"})

        client._make_request("GET", "http://test.com/api", {}, timeout=5.0)

        # Verify timeout was passed to Client
        client_cls.assert_called_once()
        call_kwargs = client_cls.call_args[1]
        assert call_kwargs["timeout"] == 5.0

    def test_default_timeout(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.get.return_value = _mock_response(mocker, 200, {"result": "ok"})

        client._make_request("GET", "http://test.com/api", {})

        # Verify default timeout (1.0) was used
        client_cls.assert_called_once()
        call_kwargs = client_cls.call_args[1]
        assert call_kwargs["timeout"] == 1.0

    def test_non_200_status_code(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.get.return_value = _mock_response(mocker, 404, {"detail": "not found"})

        with pytest.raises(Exception) as excinfo:
            client._make_request("GET", "http://test.com/api", {}, error_message="Custom error")

        assert "Custom error" in str(excinfo.value)
        assert "404" in str(excinfo.value)

    def test_unsupported_method(self, client: DataMateClient):
        with pytest.raises(ValueError) as excinfo:
            client._make_request("PUT", "http://test.com/api", {})

        assert "Unsupported HTTP method: PUT" in str(excinfo.value)


class TestHandleErrorResponse:
    """Test the internal _handle_error_response method."""

    def test_json_error_response(self, client: DataMateClient):
        response = MagicMock()
        response.status_code = 500
        response.headers = {"content-type": "application/json"}
        response.json.return_value = {"detail": "Internal server error"}

        with pytest.raises(Exception) as excinfo:
            client._handle_error_response(response, "Test error")

        assert "Test error" in str(excinfo.value)
        assert "500" in str(excinfo.value)
        assert "Internal server error" in str(excinfo.value)

    def test_text_error_response(self, client: DataMateClient):
        response = MagicMock()
        response.status_code = 404
        response.headers = {"content-type": "text/plain"}
        response.text = "Resource not found"

        with pytest.raises(Exception) as excinfo:
            client._handle_error_response(response, "Test error")

        assert "Test error" in str(excinfo.value)
        assert "404" in str(excinfo.value)
        assert "Resource not found" in str(excinfo.value)

    def test_json_error_without_detail(self, client: DataMateClient):
        response = MagicMock()
        response.status_code = 500
        response.headers = {"content-type": "application/json"}
        response.json.return_value = {}

        with pytest.raises(Exception) as excinfo:
            client._handle_error_response(response, "Test error")

        assert "Test error" in str(excinfo.value)
        assert "unknown error" in str(excinfo.value)


class TestListKnowledgeBasesEdgeCases:
    """Test edge cases for list_knowledge_bases."""

    def test_empty_list(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.post.return_value = _mock_response(mocker, 200, {"data": {"content": []}})

        kbs = client.list_knowledge_bases()
        assert kbs == []

    def test_no_data_field(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.post.return_value = _mock_response(mocker, 200, {})

        kbs = client.list_knowledge_bases()
        assert kbs == []

    def test_default_parameters(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.post.return_value = _mock_response(
            mocker, 200, {"data": {"content": [{"id": "kb1"}]}}
        )

        client.list_knowledge_bases()

        http_client.post.assert_called_once_with(
            "http://datamate.local:30000/api/knowledge-base/list",
            json={"page": 0, "size": 20},
            headers={},
        )


class TestGetKnowledgeBaseFilesEdgeCases:
    """Test edge cases for get_knowledge_base_files."""

    def test_empty_file_list(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.get.return_value = _mock_response(mocker, 200, {"data": {"content": []}})

        files = client.get_knowledge_base_files("kb1")
        assert files == []

    def test_no_data_field(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.get.return_value = _mock_response(mocker, 200, {})

        files = client.get_knowledge_base_files("kb1")
        assert files == []

    def test_with_authorization(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.get.return_value = _mock_response(
            mocker, 200, {"data": {"content": [{"id": "f1"}]}}
        )

        client.get_knowledge_base_files("kb1", authorization="Bearer token")

        http_client.get.assert_called_once_with(
            "http://datamate.local:30000/api/knowledge-base/kb1/files",
            headers={"Authorization": "Bearer token"},
        )


class TestRetrieveKnowledgeBaseEdgeCases:
    """Test edge cases for retrieve_knowledge_base."""

    def test_empty_results(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.post.return_value = _mock_response(mocker, 200, {"data": []})

        results = client.retrieve_knowledge_base("query", ["kb1"])
        assert results == []

    def test_no_data_field(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.post.return_value = _mock_response(mocker, 200, {})

        results = client.retrieve_knowledge_base("query", ["kb1"])
        assert results == []

    def test_default_parameters(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.post.return_value = _mock_response(mocker, 200, {"data": []})

        client.retrieve_knowledge_base("query", ["kb1"])

        http_client.post.assert_called_once_with(
            "http://datamate.local:30000/api/knowledge-base/retrieve",
            json={
                "query": "query",
                "topK": 10,
                "threshold": 0.2,
                "knowledgeBaseIds": ["kb1"],
            },
            headers={},
        )

    def test_custom_timeout(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.post.return_value = _mock_response(mocker, 200, {"data": []})

        client.retrieve_knowledge_base("query", ["kb1"])

        # Verify timeout is doubled for retrieve (1.0 * 2 = 2.0)
        client_cls.assert_called_once()
        call_kwargs = client_cls.call_args[1]
        assert call_kwargs["timeout"] == 2.0

    def test_multiple_knowledge_base_ids(self, mocker: MockFixture, client: DataMateClient):
        client_cls = mocker.patch("sdk.nexent.datamate.datamate_client.httpx.Client")
        http_client = client_cls.return_value.__enter__.return_value
        http_client.post.return_value = _mock_response(mocker, 200, {"data": []})

        client.retrieve_knowledge_base("query", ["kb1", "kb2", "kb3"], top_k=5, threshold=0.3)

        http_client.post.assert_called_once_with(
            "http://datamate.local:30000/api/knowledge-base/retrieve",
            json={
                "query": "query",
                "topK": 5,
                "threshold": 0.3,
                "knowledgeBaseIds": ["kb1", "kb2", "kb3"],
            },
            headers={},
        )


class TestSyncAllKnowledgeBasesEdgeCases:
    """Test edge cases for sync_all_knowledge_bases."""

    def test_empty_knowledge_bases_list(self, mocker: MockFixture, client: DataMateClient):
        mocker.patch.object(client, "list_knowledge_bases", return_value=[])

        result = client.sync_all_knowledge_bases()

        assert result["success"] is True
        assert result["total_count"] == 0
        assert result["knowledge_bases"] == []

    def test_all_success(self, mocker: MockFixture, client: DataMateClient):
        mocker.patch.object(
            client, "list_knowledge_bases", return_value=[{"id": "kb1"}, {"id": "kb2"}]
        )
        mocker.patch.object(
            client, "get_knowledge_base_files", side_effect=[[{"id": "f1"}], [{"id": "f2"}]]
        )

        result = client.sync_all_knowledge_bases()

        assert result["success"] is True
        assert result["total_count"] == 2
        assert len(result["knowledge_bases"][0]["files"]) == 1
        assert len(result["knowledge_bases"][1]["files"]) == 1
        assert "error" not in result["knowledge_bases"][0]
        assert "error" not in result["knowledge_bases"][1]

    def test_with_authorization(self, mocker: MockFixture, client: DataMateClient):
        list_mock = mocker.patch.object(
            client, "list_knowledge_bases", return_value=[{"id": "kb1"}]
        )
        files_mock = mocker.patch.object(
            client, "get_knowledge_base_files", return_value=[{"id": "f1"}]
        )

        client.sync_all_knowledge_bases(authorization="Bearer token")

        list_mock.assert_called_once_with(authorization="Bearer token")
        files_mock.assert_called_once_with("kb1", authorization="Bearer token")


class TestClientInitialization:
    """Test DataMateClient initialization."""

    def test_default_timeout(self):
        client = DataMateClient(base_url="http://test.com")
        assert client.timeout == 30.0

    def test_custom_timeout(self):
        client = DataMateClient(base_url="http://test.com", timeout=5.0)
        assert client.timeout == 5.0

    def test_base_url_stripping(self):
        client = DataMateClient(base_url="http://test.com/", timeout=1.0)
        assert client.base_url == "http://test.com"
        # Verify _build_url works correctly
        assert client._build_url("/api/test") == "http://test.com/api/test"


