"""Unit tests for ext_components.aidp.services.aidp_service.fusion_search_impl.

The evaluation case-generation flow calls this helper server-side; these
tests exercise the wire mapping, response parsing and error translation with
a stubbed HTTP client (no AIDP server, no retries). Everything else imports
for real (backend consts, SDK http client manager, httpx) — no sys.modules
stubs, so this file cannot pollute sibling test modules.
"""

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
for _p in (str(_REPO_ROOT), str(_REPO_ROOT / "backend"), str(_REPO_ROOT / "sdk")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture
def fusion():
    """Freshly imported aidp_service module (stateless helpers under test)."""
    if "ext_components.aidp.services.aidp_service" in sys.modules:
        del sys.modules["ext_components.aidp.services.aidp_service"]
    return importlib.import_module("ext_components.aidp.services.aidp_service")


def _install_client(monkeypatch, fusion, response) -> MagicMock:
    """Swap the shared http client for one returning ``response`` on POST."""
    client = MagicMock()
    client.post.return_value = response
    monkeypatch.setattr(
        fusion.http_client_manager, "get_sync_client", MagicMock(return_value=client)
    )
    return client


def _ok_response(payload: dict) -> httpx.Response:
    return httpx.Response(
        200, json=payload, request=httpx.Request("POST", "http://aidp.example/x")
    )


SERVER_URL = "http://aidp.example"
API_KEY = "test-key"


def _call_fusion(fusion, **overrides):
    kwargs = {
        "server_url": SERVER_URL,
        "api_key": API_KEY,
        "query": "q1",
        "kds_list": ["k1"],
    }
    kwargs.update(overrides)
    return fusion.fusion_search_impl(**kwargs)


class TestFusionSearchImpl:
    def test_posts_to_fusion_search_and_returns_records(self, fusion, monkeypatch):
        records = [{"id": 1, "text": "a"}, {"id": 2, "text": "b"}]
        client = _install_client(monkeypatch, fusion, _ok_response({"result": records}))

        out = _call_fusion(fusion, tenant_id="aidp", kds_list=["k1", "k2"], top_k=3)

        assert out == records
        assert client.post.call_count == 1
        url = client.post.call_args.args[0]
        payload = client.post.call_args.kwargs["json"]
        assert "/KnowledgeBase/Tenants/aidp/Retrieval/FusionSearch" in url
        assert payload["query"] == "q1"
        assert payload["kds_list"] == ["k1", "k2"]
        assert payload["search_method"] == "hybrid_search"
        assert payload["top_k"] == 3
        assert payload["multi_modal"] is False
        assert payload["reranking_enable"] is True
        assert (
            client.post.call_args.kwargs["headers"]["Authorization"]
            == f"Bearer {API_KEY}"
        )

    def test_missing_result_field_returns_empty(self, fusion, monkeypatch):
        _install_client(monkeypatch, fusion, _ok_response({"value": []}))
        assert _call_fusion(fusion) == []

    def test_non_dict_result_returns_empty(self, fusion, monkeypatch):
        _install_client(monkeypatch, fusion, _ok_response([1, 2, 3]))
        assert _call_fusion(fusion) == []

    def test_http_error_translates_to_app_exception(self, fusion, monkeypatch):
        bad = httpx.Response(
            500,
            json={"error": {"message": "internal"}},
            request=httpx.Request("POST", "http://aidp.example/x"),
        )
        client = _install_client(monkeypatch, fusion, bad)
        monkeypatch.setattr(
            fusion, "_request_with_retry", lambda fn, **kw: client.post(None)
        )

        with pytest.raises(Exception) as ei:
            _call_fusion(fusion)
        assert ei.value.error_code == fusion.ErrorCode.AIDP_SERVICE_ERROR

    def test_auth_error_maps_to_auth_code(self, fusion, monkeypatch):
        bad = httpx.Response(
            401, json={}, request=httpx.Request("POST", "http://aidp.example/x")
        )
        client = _install_client(monkeypatch, fusion, bad)
        monkeypatch.setattr(
            fusion, "_request_with_retry", lambda fn, **kw: client.post(None)
        )

        with pytest.raises(Exception) as ei:
            _call_fusion(fusion)
        assert ei.value.error_code == fusion.ErrorCode.AIDP_AUTH_ERROR

    def test_request_error_translates_to_connection_error(self, fusion, monkeypatch):
        client = MagicMock()
        client.post.side_effect = httpx.RequestError("connection refused")
        monkeypatch.setattr(
            fusion.http_client_manager, "get_sync_client", MagicMock(return_value=client)
        )

        with pytest.raises(Exception) as ei:
            _call_fusion(fusion)
        assert ei.value.error_code == fusion.ErrorCode.AIDP_CONNECTION_ERROR
