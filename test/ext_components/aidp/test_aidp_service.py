import importlib.util
import os
import sys
from types import ModuleType
from unittest.mock import MagicMock

import httpx
import pytest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
BACKEND_ROOT = os.path.join(PROJECT_ROOT, "backend")
SERVICE_PATH = os.path.join(BACKEND_ROOT, "ext_components", "aidp", "services", "aidp_service.py")

if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from consts.error_code import ErrorCode
from consts.exceptions import AppException


@pytest.fixture
def aidp_service_module():
    original_modules = {}

    def register_module(name: str, module: ModuleType):
        if name in sys.modules:
            original_modules[name] = sys.modules[name]
        sys.modules[name] = module

    nexent_pkg = ModuleType("nexent")
    nexent_pkg.__path__ = []
    register_module("nexent", nexent_pkg)

    nexent_utils_pkg = ModuleType("nexent.utils")
    nexent_utils_pkg.__path__ = []
    register_module("nexent.utils", nexent_utils_pkg)

    http_client_mod = ModuleType("nexent.utils.http_client_manager")
    http_client_mod.http_client_manager = MagicMock()
    register_module("nexent.utils.http_client_manager", http_client_mod)

    backend_pkg = ModuleType("backend")
    backend_pkg.__path__ = [os.path.join(PROJECT_ROOT, "backend")]
    register_module("backend", backend_pkg)

    backend_services_pkg = ModuleType("backend.services")
    backend_services_pkg.__path__ = [os.path.join(PROJECT_ROOT, "backend", "services")]
    register_module("backend.services", backend_services_pkg)

    module_name = "backend.ext_components.aidp.services.aidp_service"
    spec = importlib.util.spec_from_file_location(module_name, SERVICE_PATH)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "backend.services"
    register_module(module_name, module)
    spec.loader.exec_module(module)

    try:
        yield module
    finally:
        for name in [
            module_name,
            "backend.services",
            "backend",
            "nexent.utils.http_client_manager",
            "nexent.utils",
            "nexent",
        ]:
            if name in original_modules:
                sys.modules[name] = original_modules[name]
            else:
                sys.modules.pop(name, None)


class TestFetchAidpKnowledgeBasesImpl:
    def test_passthrough_single_page(self, aidp_service_module):
        """Passthrough: returns the AIDP API response directly."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "value": [{"kds_id": "kb-1"}, {"kds_id": "kb-2"}],
            "total_count": 2,
        }
        mock_response.raise_for_status.return_value = None
        mock_client.get.return_value = mock_response

        mock_manager = MagicMock()
        mock_manager.get_sync_client.return_value = mock_client
        aidp_service_module.http_client_manager = mock_manager

        result = aidp_service_module.fetch_aidp_knowledge_bases_impl(
            server_url="http://127.0.0.1:30081",
            api_key="jwt-token",
            page=3,
            page_size=20,
        )

        assert result["value"] == [{"kds_id": "kb-1"}, {"kds_id": "kb-2"}]
        assert result["total_count"] == 2
        mock_client.get.assert_called_once()
        call_url = mock_client.get.call_args[0][0]
        assert "page=3" in call_url
        assert "page_size=20" in call_url

    def test_uses_bearer_auth_header(self, aidp_service_module):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"value": [{"kds_id": "kb-1"}]}
        mock_response.raise_for_status.return_value = None
        mock_client.get.return_value = mock_response

        mock_manager = MagicMock()
        mock_manager.get_sync_client.return_value = mock_client
        aidp_service_module.http_client_manager = mock_manager

        aidp_service_module.fetch_aidp_knowledge_bases_impl(
            server_url="http://127.0.0.1:30081",
            api_key="my-secret-token",
            page=1,
            page_size=10,
        )

        call_args = mock_client.get.call_args
        assert call_args.kwargs["headers"]["Authorization"] == "Bearer my-secret-token"

    @pytest.mark.parametrize(
        "server_url,api_key,error_code",
        [
            ("", "token", ErrorCode.AIDP_CONFIG_INVALID),
            ("ftp://example.com", "token", ErrorCode.AIDP_CONFIG_INVALID),
            ("http://example.com", "", ErrorCode.AIDP_CONFIG_INVALID),
        ],
    )
    def test_fetch_invalid_config(
        self,
        aidp_service_module,
        server_url: str,
        api_key: str,
        error_code: ErrorCode,
    ):
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.fetch_aidp_knowledge_bases_impl(
                server_url=server_url,
                api_key=api_key,
            )
        assert exc_info.value.error_code == error_code

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_fetch_auth_error(self, aidp_service_module, status_code: int):
        request = httpx.Request("GET", "http://127.0.0.1:30081")
        response = httpx.Response(status_code, request=request)
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.HTTPStatusError(
            "auth failed",
            request=request,
            response=response,
        )
        mock_manager = MagicMock()
        mock_manager.get_sync_client.return_value = mock_client
        aidp_service_module.http_client_manager = mock_manager

        with pytest.raises(AppException) as exc_info:
            aidp_service_module.fetch_aidp_knowledge_bases_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_AUTH_ERROR

    def test_fetch_http_status_error_maps_service_error(self, aidp_service_module):
        request = httpx.Request("GET", "http://127.0.0.1:30081")
        response = httpx.Response(500, request=request)
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.HTTPStatusError(
            "server error",
            request=request,
            response=response,
        )
        mock_manager = MagicMock()
        mock_manager.get_sync_client.return_value = mock_client
        aidp_service_module.http_client_manager = mock_manager

        with pytest.raises(AppException) as exc_info:
            aidp_service_module.fetch_aidp_knowledge_bases_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_SERVICE_ERROR

    def test_fetch_request_error_maps_connection_error(self, aidp_service_module):
        request = httpx.Request("GET", "http://127.0.0.1:30081")
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.RequestError("network down", request=request)

        mock_manager = MagicMock()
        mock_manager.get_sync_client.return_value = mock_client
        aidp_service_module.http_client_manager = mock_manager

        with pytest.raises(AppException) as exc_info:
            aidp_service_module.fetch_aidp_knowledge_bases_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_CONNECTION_ERROR

    def test_fetch_invalid_json_shape_maps_service_error(self, aidp_service_module):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = ["unexpected-list"]
        mock_client.get.return_value = mock_response

        mock_manager = MagicMock()
        mock_manager.get_sync_client.return_value = mock_client
        aidp_service_module.http_client_manager = mock_manager

        with pytest.raises(AppException) as exc_info:
            aidp_service_module.fetch_aidp_knowledge_bases_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_SERVICE_ERROR


class TestFetchAllAidpKnowledgeBasesImpl:
    def test_follows_next_link_for_pagination(self, aidp_service_module):
        """Follows next_link from response to fetch subsequent pages."""
        mock_client = MagicMock()

        page1_response = MagicMock()
        page1_response.json.return_value = {
            "value": [{"kds_id": "kb-1"}, {"kds_id": "kb-2"}],
            "next_link": "/KnowledgeBase/Tenants/real-tenant/KnowledgeBases?page=2&page_size=100",
        }
        page1_response.raise_for_status.return_value = None

        page2_response = MagicMock()
        page2_response.json.return_value = {
            "value": [{"kds_id": "kb-3"}, {"kds_id": "kb-4"}],
            "next_link": None,
        }
        page2_response.raise_for_status.return_value = None

        mock_client.get.side_effect = [page1_response, page2_response]

        mock_manager = MagicMock()
        mock_manager.get_sync_client.return_value = mock_client
        aidp_service_module.http_client_manager = mock_manager

        result = aidp_service_module.fetch_all_aidp_knowledge_bases_impl(
            server_url="http://127.0.0.1:30081",
            api_key="jwt-token",
        )

        assert result["total_count"] == 4
        assert result["value"] == [
            {"kds_id": "kb-1"},
            {"kds_id": "kb-2"},
            {"kds_id": "kb-3"},
            {"kds_id": "kb-4"},
        ]
        assert mock_client.get.call_count == 2

    def test_stops_when_next_link_is_null(self, aidp_service_module):
        """Stops pagination when next_link is null/empty."""
        mock_client = MagicMock()
        single_response = MagicMock()
        single_response.json.return_value = {
            "value": [{"kds_id": "kb-1"}],
            "next_link": None,
        }
        single_response.raise_for_status.return_value = None
        mock_client.get.return_value = single_response

        mock_manager = MagicMock()
        mock_manager.get_sync_client.return_value = mock_client
        aidp_service_module.http_client_manager = mock_manager

        result = aidp_service_module.fetch_all_aidp_knowledge_bases_impl(
            server_url="http://127.0.0.1:30081",
            api_key="jwt-token",
        )

        assert result["total_count"] == 1
        assert mock_client.get.call_count == 1

    def test_first_page_uses_page_size_100(self, aidp_service_module):
        """The initial request uses page_size=100."""
        mock_client = MagicMock()
        empty_response = MagicMock()
        empty_response.json.return_value = {"value": [], "next_link": None}
        empty_response.raise_for_status.return_value = None
        mock_client.get.return_value = empty_response

        mock_manager = MagicMock()
        mock_manager.get_sync_client.return_value = mock_client
        aidp_service_module.http_client_manager = mock_manager

        aidp_service_module.fetch_all_aidp_knowledge_bases_impl(
            server_url="http://127.0.0.1:30081",
            api_key="jwt-token",
        )

        call_url = mock_client.get.call_args[0][0]
        assert "page_size=100" in call_url

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_auth_error(self, aidp_service_module, status_code: int):
        request = httpx.Request("GET", "http://127.0.0.1:30081")
        response = httpx.Response(status_code, request=request)
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.HTTPStatusError(
            "auth failed",
            request=request,
            response=response,
        )
        mock_manager = MagicMock()
        mock_manager.get_sync_client.return_value = mock_client
        aidp_service_module.http_client_manager = mock_manager

        with pytest.raises(AppException) as exc_info:
            aidp_service_module.fetch_all_aidp_knowledge_bases_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_AUTH_ERROR

    def test_request_error_maps_connection_error(self, aidp_service_module):
        request = httpx.Request("GET", "http://127.0.0.1:30081")
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.RequestError("network down", request=request)

        mock_manager = MagicMock()
        mock_manager.get_sync_client.return_value = mock_client
        aidp_service_module.http_client_manager = mock_manager

        with pytest.raises(AppException) as exc_info:
            aidp_service_module.fetch_all_aidp_knowledge_bases_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_CONNECTION_ERROR

    def test_invalid_json_shape_maps_service_error(self, aidp_service_module):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = ["unexpected-list"]
        mock_client.get.return_value = mock_response

        mock_manager = MagicMock()
        mock_manager.get_sync_client.return_value = mock_client
        aidp_service_module.http_client_manager = mock_manager

        with pytest.raises(AppException) as exc_info:
            aidp_service_module.fetch_all_aidp_knowledge_bases_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_SERVICE_ERROR

    def test_fetch_http_status_error_maps_service_error(self, aidp_service_module):
        request = httpx.Request("GET", "http://127.0.0.1:30081")
        response = httpx.Response(500, request=request)
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.HTTPStatusError(
            "server error",
            request=request,
            response=response,
        )
        mock_manager = MagicMock()
        mock_manager.get_sync_client.return_value = mock_client
        aidp_service_module.http_client_manager = mock_manager

        with pytest.raises(AppException) as exc_info:
            aidp_service_module.fetch_all_aidp_knowledge_bases_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_SERVICE_ERROR


# ---------------------------------------------------------------------------
# _apply_create_defaults tests
# Pure helper, no mocking required -- tests default injection behavior.
# ---------------------------------------------------------------------------
class TestApplyCreateDefaults:
    """Tests for _apply_create_defaults (AIDP create KB payload defaults)."""

    @pytest.fixture
    def aidp_mod(self, aidp_service_module):
        return aidp_service_module

    def test_fills_all_defaults_when_payload_is_minimal(self, aidp_mod):
        result = aidp_mod._apply_create_defaults({"name": "kb-1"})
        assert result["name"] == "kb-1"
        assert result["chunk_token_num"] == 1024
        assert result["chunk_overlap_num"] == 128
        assert result["embedding_model"] == "default"
        assert result["vlm_model"] == ""
        assert result["is_personal"] == 0
        assert result["topk"] == 10
        assert result["similarity"] == 0.0
        assert result["smartsplit"] == 1
        assert result["caption_enable"] == 0

    def test_preserves_client_supplied_values(self, aidp_mod):
        payload = {
            "name": "kb-custom",
            "description": "my desc",
            "chunk_token_num": 512,
            "embedding_model": "bge-m3",
            "is_personal": 1,
        }
        result = aidp_mod._apply_create_defaults(payload)
        assert result["name"] == "kb-custom"
        assert result["description"] == "my desc"
        assert result["chunk_token_num"] == 512
        assert result["embedding_model"] == "bge-m3"
        assert result["is_personal"] == 1
        assert result["chunk_overlap_num"] == 128
        assert result["vlm_model"] == ""
        assert result["topk"] == 10

    def test_is_multimodal_enables_caption_when_not_set(self, aidp_mod):
        result = aidp_mod._apply_create_defaults(
            {"name": "kb-mm", "is_multimodal": True}
        )
        assert result["is_multimodal"] is True
        assert result["caption_enable"] == 1

    def test_is_multimodal_respects_explicit_caption(self, aidp_mod):
        result = aidp_mod._apply_create_defaults(
            {"name": "kb-mm", "is_multimodal": True, "caption_enable": 0}
        )
        assert result["caption_enable"] == 0

    def test_does_not_mutate_input_payload(self, aidp_mod):
        original = {"name": "kb-x"}
        snapshot = dict(original)
        aidp_mod._apply_create_defaults(original)
        assert original == snapshot

    def test_false_value_preserved_not_replaced_by_default(self, aidp_mod):
        result = aidp_mod._apply_create_defaults(
            {"name": "kb", "chunk_token_num": 0, "vlm_model": "my-vlm"}
        )
        assert result["chunk_token_num"] == 0
        assert result["vlm_model"] == "my-vlm"


# ---------------------------------------------------------------------------
# _request_with_retry tests
# ---------------------------------------------------------------------------
class TestRequestWithRetry:
    """Tests for _request_with_retry (exponential backoff retry helper)."""

    @pytest.fixture
    def mod(self, aidp_service_module):
        return aidp_service_module

    def _mock_response(self, status_code: int, headers: dict = None):
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.headers = headers or {}
        return mock_resp

    def test_success_on_first_attempt(self, mod):
        """200 response on first call — no retry."""
        resp = self._mock_response(200)
        request_fn = MagicMock(return_value=resp)

        result = mod._request_with_retry(request_fn, context="test-success")

        assert result is resp
        assert request_fn.call_count == 1

    def test_retry_then_success(self, mod, monkeypatch):
        """Non-200 responses followed by 200 — retries happen, returns 200."""
        resp_503 = self._mock_response(503)
        resp_200 = self._mock_response(200)
        request_fn = MagicMock(side_effect=[resp_503, resp_503, resp_200])

        # Skip actual sleep during test
        sleep_calls = []
        monkeypatch.setattr(mod.time, "sleep", lambda s: sleep_calls.append(s))

        result = mod._request_with_retry(request_fn, context="test-retry")

        assert result is resp_200
        assert request_fn.call_count == 3
        # Exponential backoff: 0.5s, 1.0s
        assert sleep_calls == [0.5, 1.0]

    def test_all_retries_exhausted_returns_final_response(self, mod, monkeypatch):
        """All requests return non-200 — returns the last response for caller to raise_for_status."""
        resp_503 = self._mock_response(503)
        request_fn = MagicMock(return_value=resp_503)

        sleep_calls = []
        monkeypatch.setattr(mod.time, "sleep", lambda s: sleep_calls.append(s))

        result = mod._request_with_retry(request_fn, context="test-exhausted")

        assert result is resp_503
        assert request_fn.call_count == 3
        assert sleep_calls == [0.5, 1.0]

    def test_network_error_retry_then_success(self, mod, monkeypatch):
        """httpx.RequestError followed by 200 — retries, returns 200."""
        resp_200 = self._mock_response(200)
        request_fn = MagicMock(side_effect=[
            httpx.ConnectError("connection refused"),
            httpx.TimeoutException("timeout"),
            resp_200,
        ])

        sleep_calls = []
        monkeypatch.setattr(mod.time, "sleep", lambda s: sleep_calls.append(s))

        result = mod._request_with_retry(request_fn, context="test-net-retry")

        assert result is resp_200
        assert request_fn.call_count == 3
        assert sleep_calls == [0.5, 1.0]

    def test_network_error_all_retries_exhausted_raises(self, mod, monkeypatch):
        """All requests raise httpx.RequestError — final exception propagates."""
        request_fn = MagicMock(side_effect=httpx.ConnectError("connection refused"))

        sleep_calls = []
        monkeypatch.setattr(mod.time, "sleep", lambda s: sleep_calls.append(s))

        with pytest.raises(httpx.ConnectError):
            mod._request_with_retry(request_fn, context="test-net-fail")

        assert request_fn.call_count == 3
        assert sleep_calls == [0.5, 1.0]

    def test_retry_after_header_honored(self, mod, monkeypatch):
        """429 with Retry-After header — waits specified seconds instead of exponential backoff."""
        resp_429 = self._mock_response(429, headers={"Retry-After": "5"})
        resp_200 = self._mock_response(200)
        request_fn = MagicMock(side_effect=[resp_429, resp_200])

        sleep_calls = []
        monkeypatch.setattr(mod.time, "sleep", lambda s: sleep_calls.append(s))

        result = mod._request_with_retry(request_fn, context="test-retry-after")

        assert result is resp_200
        assert request_fn.call_count == 2
        assert sleep_calls == [5.0]

    def test_mixed_status_codes_trigger_retry(self, mod, monkeypatch):
        """Any non-200 status triggers retry: 400, 404, 500 all treated equally."""
        resp_400 = self._mock_response(400)
        resp_404 = self._mock_response(404)
        resp_200 = self._mock_response(200)
        request_fn = MagicMock(side_effect=[resp_400, resp_404, resp_200])

        sleep_calls = []
        monkeypatch.setattr(mod.time, "sleep", lambda s: sleep_calls.append(s))

        result = mod._request_with_retry(request_fn, context="test-mixed")

        assert result is resp_200
        assert request_fn.call_count == 3

    def test_custom_max_attempts(self, mod, monkeypatch):
        """Passing max_attempts=1 disables retry — returns first response immediately."""
        resp_503 = self._mock_response(503)
        request_fn = MagicMock(return_value=resp_503)

        sleep_calls = []
        monkeypatch.setattr(mod.time, "sleep", lambda s: sleep_calls.append(s))

        result = mod._request_with_retry(request_fn, context="test-no-retry", max_attempts=1)

        assert result is resp_503
        assert request_fn.call_count == 1
        assert sleep_calls == []
