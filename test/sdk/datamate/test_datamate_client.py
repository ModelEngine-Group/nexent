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


