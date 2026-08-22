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
        mock_response.status_code = 200
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
        mock_response = MagicMock(status_code=200)
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
        mock_response = MagicMock(status_code=200)
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
    @pytest.fixture(autouse=True)
    def mock_count(self, aidp_service_module, monkeypatch):
        monkeypatch.setattr(
            aidp_service_module,
            "count_aidp_kbs_impl",
            MagicMock(return_value=1),
        )

    def test_fetches_pages_from_count_and_uses_configured_tenant(self, aidp_service_module):
        """Calculates pages from Count and ignores the tenant in next_link."""
        aidp_service_module.count_aidp_kbs_impl.return_value = 101
        mock_client = MagicMock()

        page1_response = MagicMock()
        page1_response.json.return_value = {
            "value": [{"kds_id": "kb-1"}, {"kds_id": "kb-2"}],
            "next_link": "/KnowledgeBase/Tenants/real-tenant/KnowledgeBases?page=2&page_size=100",
        }
        page1_response.status_code = 200
        page1_response.raise_for_status.return_value = None

        page2_response = MagicMock()
        page2_response.json.return_value = {
            "value": [{"kds_id": "kb-3"}, {"kds_id": "kb-4"}],
            "next_link": None,
        }
        page2_response.status_code = 200
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
        requested_urls = [call.args[0] for call in mock_client.get.call_args_list]
        assert requested_urls == [
            "http://127.0.0.1:30081/KnowledgeBase/Tenants/aidp/KnowledgeBases?page=1&page_size=100",
            "http://127.0.0.1:30081/KnowledgeBase/Tenants/aidp/KnowledgeBases?page=2&page_size=100",
        ]

    def test_deduplicates_kds_ids_across_pages(self, aidp_service_module):
        aidp_service_module.count_aidp_kbs_impl.return_value = 101
        page1 = MagicMock(status_code=200)
        page1.raise_for_status.return_value = None
        page1.json.return_value = {
            "value": [{"kds_id": "kb-1"}],
            "next_link": "/KnowledgeBase/Tenants/aidp/KnowledgeBases?page=2&page_size=100",
        }
        page2 = MagicMock(status_code=200)
        page2.raise_for_status.return_value = None
        page2.json.return_value = {
            "value": [{"kds_id": "kb-1"}, {"kds_id": "kb-2"}],
            "next_link": None,
        }
        mock_client = MagicMock()
        mock_client.get.side_effect = [page1, page2]
        mock_manager = MagicMock()
        mock_manager.get_sync_client.return_value = mock_client
        aidp_service_module.http_client_manager = mock_manager

        result = aidp_service_module.fetch_all_aidp_knowledge_bases_impl(
            server_url="http://127.0.0.1:30081",
            api_key="jwt-token",
        )

        assert result["value"] == [{"kds_id": "kb-1"}, {"kds_id": "kb-2"}]
        assert result["total_count"] == 2

    def test_ignores_repeated_next_link(self, aidp_service_module):
        aidp_service_module.count_aidp_kbs_impl.return_value = 101
        repeated_link = "/KnowledgeBase/Tenants/aidp/KnowledgeBases?page=2&page_size=100"
        page1 = MagicMock(status_code=200)
        page1.raise_for_status.return_value = None
        page1.json.return_value = {"value": [{"kds_id": "kb-1"}], "next_link": repeated_link}
        page2 = MagicMock(status_code=200)
        page2.raise_for_status.return_value = None
        page2.json.return_value = {"value": [{"kds_id": "kb-2"}], "next_link": repeated_link}
        mock_client = MagicMock()
        mock_client.get.side_effect = [page1, page2]
        mock_manager = MagicMock()
        mock_manager.get_sync_client.return_value = mock_client
        aidp_service_module.http_client_manager = mock_manager

        result = aidp_service_module.fetch_all_aidp_knowledge_bases_impl(
            server_url="http://127.0.0.1:30081",
            api_key="jwt-token",
        )

        assert result["value"] == [{"kds_id": "kb-1"}, {"kds_id": "kb-2"}]
        assert mock_client.get.call_count == 2

    def test_ignores_next_link_on_different_origin(self, aidp_service_module):
        page1 = MagicMock(status_code=200)
        page1.raise_for_status.return_value = None
        page1.json.return_value = {
            "value": [{"kds_id": "kb-1"}],
            "next_link": "https://unexpected.example/KnowledgeBases?page=2",
        }
        mock_client = MagicMock()
        mock_client.get.return_value = page1
        mock_manager = MagicMock()
        mock_manager.get_sync_client.return_value = mock_client
        aidp_service_module.http_client_manager = mock_manager

        result = aidp_service_module.fetch_all_aidp_knowledge_bases_impl(
            server_url="http://127.0.0.1:30081",
            api_key="jwt-token",
        )

        assert result["value"] == [{"kds_id": "kb-1"}]
        assert mock_client.get.call_count == 1

    def test_fetches_all_counted_pages_when_next_link_is_null(self, aidp_service_module):
        """Count, rather than next_link, controls the number of pages."""
        aidp_service_module.count_aidp_kbs_impl.return_value = 101
        mock_client = MagicMock()
        page1 = MagicMock()
        page1.json.return_value = {
            "value": [{"kds_id": "kb-1"}],
            "next_link": None,
        }
        page1.status_code = 200
        page1.raise_for_status.return_value = None
        page2 = MagicMock()
        page2.json.return_value = {
            "value": [{"kds_id": "kb-2"}],
            "next_link": None,
        }
        page2.status_code = 200
        page2.raise_for_status.return_value = None
        mock_client.get.side_effect = [page1, page2]

        mock_manager = MagicMock()
        mock_manager.get_sync_client.return_value = mock_client
        aidp_service_module.http_client_manager = mock_manager

        result = aidp_service_module.fetch_all_aidp_knowledge_bases_impl(
            server_url="http://127.0.0.1:30081",
            api_key="jwt-token",
        )

        assert result["total_count"] == 2
        assert mock_client.get.call_count == 2

    def test_zero_count_skips_list_requests(self, aidp_service_module):
        aidp_service_module.count_aidp_kbs_impl.return_value = 0
        mock_client = MagicMock()
        mock_manager = MagicMock()
        mock_manager.get_sync_client.return_value = mock_client
        aidp_service_module.http_client_manager = mock_manager

        result = aidp_service_module.fetch_all_aidp_knowledge_bases_impl(
            server_url="http://127.0.0.1:30081",
            api_key="jwt-token",
        )

        assert result == {
            "value": [],
            "total_count": 0,
            "next_link": None,
        }
        mock_client.get.assert_not_called()

    def test_first_page_uses_page_size_100(self, aidp_service_module):
        """The initial request uses page_size=100."""
        mock_client = MagicMock()
        empty_response = MagicMock(status_code=200)
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
        mock_response = MagicMock(status_code=200)
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
            {
                "name": "kb",
                "chunk_token_num": 0,
                "caption_enable": 1,
                "vlm_model": "my-vlm",
            }
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

    @pytest.mark.parametrize("status_code", [400, 401, 403, 404])
    def test_non_retryable_client_error_returns_immediately(self, mod, monkeypatch, status_code):
        response = self._mock_response(status_code)
        request_fn = MagicMock(return_value=response)

        sleep_calls = []
        monkeypatch.setattr(mod.time, "sleep", lambda s: sleep_calls.append(s))

        result = mod._request_with_retry(request_fn, context="test-client-error")

        assert result is response
        assert request_fn.call_count == 1
        assert sleep_calls == []

    @pytest.mark.parametrize("status_code", [201, 202, 204])
    def test_any_success_status_returns_immediately(self, mod, status_code):
        response = self._mock_response(status_code)
        request_fn = MagicMock(return_value=response)

        result = mod._request_with_retry(request_fn, context="test-success-status")

        assert result is response
        assert request_fn.call_count == 1

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

    def test_invalid_retry_after_header_falls_back_to_backoff(self, mod, monkeypatch):
        """Non-numeric Retry-After header — falls back to exponential backoff."""
        resp_429 = self._mock_response(429, headers={"Retry-After": "not-a-number"})
        resp_200 = self._mock_response(200)
        request_fn = MagicMock(side_effect=[resp_429, resp_200])

        sleep_calls = []
        monkeypatch.setattr(mod.time, "sleep", lambda s: sleep_calls.append(s))

        result = mod._request_with_retry(request_fn, context="test-bad-retry-after")

        assert result is resp_200
        assert request_fn.call_count == 2
        # Falls back to exponential backoff: 0.5 * 2^0 = 0.5
        assert sleep_calls == [0.5]


# ---------------------------------------------------------------------------
# _timestamp_to_iso tests
# ---------------------------------------------------------------------------
class TestTimestampToIso:
    """Tests for _timestamp_to_iso (Unix timestamp to ISO-8601 conversion)."""

    @pytest.fixture
    def convert(self, aidp_service_module):
        return aidp_service_module._timestamp_to_iso

    def test_none_returns_none(self, convert):
        assert convert(None) is None

    def test_empty_string_returns_none(self, convert):
        assert convert("") is None

    def test_false_returns_none(self, convert):
        assert convert(False) is None

    def test_numeric_seconds(self, convert):
        result = convert(1700000000)
        assert result.endswith("Z")
        assert "2023-11-14" in result

    def test_numeric_milliseconds(self, convert):
        result = convert(1700000000000)
        assert result.endswith("Z")
        assert "2023-11-14" in result

    def test_string_number(self, convert):
        result = convert("1700000000")
        assert result is not None
        assert result.endswith("Z")

    def test_invalid_string_returns_none(self, convert):
        assert convert("not-a-number") is None

    def test_zero_returns_epoch(self, convert):
        # Numeric zero is the Unix epoch, not "missing" — previous
        # implementation treated 0 as falsy because ``0 == False`` in
        # Python (``bool`` is a subclass of ``int``).
        result = convert(0)
        assert result == "1970-01-01T00:00:00Z"

    def test_zero_point_zero_returns_epoch(self, convert):
        # Float zero should behave the same as integer zero.
        result = convert(0.0)
        assert result == "1970-01-01T00:00:00Z"

    def test_true_converts_to_one_second_after_epoch(self, convert):
        # ``True`` is numeric 1 in Python, so it must NOT be rejected
        # as falsy — it should convert to 1 second past the epoch.
        result = convert(True)
        assert result == "1970-01-01T00:00:01Z"


# ---------------------------------------------------------------------------
# _normalize_aidp_doc tests
# ---------------------------------------------------------------------------
class TestNormalizeAidpDoc:
    """Tests for _normalize_aidp_doc (AIDP document to frontend shape)."""

    @pytest.fixture
    def normalize(self, aidp_service_module):
        return aidp_service_module._normalize_aidp_doc

    def test_uses_first_upload_time_for_created_at(self, normalize):
        result = normalize({"first_upload_time": 1700000000, "name": "doc1"})
        assert result["created_at"] is not None
        assert "2023-11-14" in result["created_at"]
        assert result["name"] == "doc1"

    def test_falls_back_to_create_time(self, normalize):
        result = normalize({"create_time": 1700000000})
        assert result["created_at"] is not None

    def test_uses_update_time_for_updated_at(self, normalize):
        result = normalize({"update_time": 1700000000, "first_upload_time": 1600000000})
        assert result["updated_at"] is not None
        assert result["created_at"] is not None

    def test_missing_timestamps_produce_none(self, normalize):
        result = normalize({"name": "doc"})
        assert result["created_at"] is None
        assert result["updated_at"] is None

    def test_preserves_original_fields(self, normalize):
        raw = {"id": "abc", "size": 100, "first_upload_time": 1700000000}
        result = normalize(raw)
        assert result["id"] == "abc"
        assert result["size"] == 100

    def test_does_not_mutate_input(self, normalize):
        raw = {"first_upload_time": 1700000000}
        snapshot = dict(raw)
        normalize(raw)
        assert raw == snapshot


# ---------------------------------------------------------------------------
# Small gap coverage for existing function tests
# ---------------------------------------------------------------------------
class TestFetchAidpKnowledgeBasesImplGaps:
    """Cover remaining branches in fetch_aidp_knowledge_bases_impl."""

    def test_json_parse_value_error_maps_service_error(self, aidp_service_module):
        """response.json() raises ValueError -> AIDP_SERVICE_ERROR."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.side_effect = ValueError("invalid json")
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


class TestFetchAllAidpKnowledgeBasesImplGaps:
    """Cover remaining branches in fetch_all_aidp_knowledge_bases_impl."""

    @pytest.fixture(autouse=True)
    def mock_count(self, aidp_service_module, monkeypatch):
        monkeypatch.setattr(
            aidp_service_module,
            "count_aidp_kbs_impl",
            MagicMock(return_value=1),
        )

    def test_non_list_page_items_treated_as_empty(self, aidp_service_module):
        """page_items is not a list (e.g. a string) -> treated as empty list."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "value": "not-a-list",
            "next_link": None,
        }
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_client.get.return_value = mock_response

        mock_manager = MagicMock()
        mock_manager.get_sync_client.return_value = mock_client
        aidp_service_module.http_client_manager = mock_manager

        result = aidp_service_module.fetch_all_aidp_knowledge_bases_impl(
            server_url="http://127.0.0.1:30081",
            api_key="jwt-token",
        )
        assert result["value"] == []
        assert result["total_count"] == 0

    def test_json_parse_value_error(self, aidp_service_module):
        """response.json() raises ValueError -> AIDP_SERVICE_ERROR."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.side_effect = ValueError("bad json")
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

    def test_uses_data_key_for_items(self, aidp_service_module):
        """Response uses 'data' key instead of 'value'."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [{"kds_id": "kb-1"}],
            "next_link": None,
        }
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_client.get.return_value = mock_response

        mock_manager = MagicMock()
        mock_manager.get_sync_client.return_value = mock_client
        aidp_service_module.http_client_manager = mock_manager

        result = aidp_service_module.fetch_all_aidp_knowledge_bases_impl(
            server_url="http://127.0.0.1:30081",
            api_key="jwt-token",
        )
        assert result["total_count"] == 1
        assert result["value"] == [{"kds_id": "kb-1"}]


# ---------------------------------------------------------------------------
# _apply_create_defaults remaining gap
# ---------------------------------------------------------------------------
class TestApplyCreateDefaultsGaps:
    """Cover the fallback description branch (line 506)."""

    def test_empty_description_no_name_uses_fallback(self, aidp_service_module):
        """No description and no name -> 'Nexent knowledge base'."""
        result = aidp_service_module._apply_create_defaults({})
        assert result["description"] == "Nexent knowledge base"

    def test_whitespace_only_description_no_name_uses_fallback(self, aidp_service_module):
        result = aidp_service_module._apply_create_defaults({"description": "   "})
        assert result["description"] == "Nexent knowledge base"

    def test_empty_description_with_name_uses_name(self, aidp_service_module):
        result = aidp_service_module._apply_create_defaults({"name": "my-kb", "description": ""})
        assert result["description"] == "my-kb"


# ---------------------------------------------------------------------------
# _normalize_response tests
# ---------------------------------------------------------------------------
class TestNormalizeResponse:
    """Tests for _normalize_response helper."""

    def test_value_key_present(self, aidp_service_module):
        result = aidp_service_module._normalize_response(
            {"value": [1, 2], "total_count": 5, "next_link": "/next"}
        )
        assert result["value"] == [1, 2]
        assert result["total_count"] == 5
        assert result["next_link"] == "/next"

    def test_data_key_fallback(self, aidp_service_module):
        result = aidp_service_module._normalize_response({"data": [1]})
        assert result["value"] == [1]

    def test_items_key_fallback(self, aidp_service_module):
        result = aidp_service_module._normalize_response({"items": [1]})
        assert result["value"] == [1]

    def test_knowledge_bases_key_fallback(self, aidp_service_module):
        result = aidp_service_module._normalize_response({"knowledge_bases": [1]})
        assert result["value"] == [1]

    def test_empty_response(self, aidp_service_module):
        result = aidp_service_module._normalize_response({})
        assert result["value"] == []
        assert result["total_count"] is None
        assert result["next_link"] is None

    def test_total_keys(self, aidp_service_module):
        assert aidp_service_module._normalize_response({"total": 3})["total_count"] == 3
        assert aidp_service_module._normalize_response({"totalRecords": 4})["total_count"] == 4
        assert aidp_service_module._normalize_response({"count": 5})["total_count"] == 5

    def test_next_key_fallback(self, aidp_service_module):
        result = aidp_service_module._normalize_response({"next": "/page2"})
        assert result["next_link"] == "/page2"


# ---------------------------------------------------------------------------
# _get_models_path tests
# ---------------------------------------------------------------------------
class TestGetModelsPath:
    """Tests for _get_models_path helper."""

    def test_default_tenant(self, aidp_service_module):
        path = aidp_service_module._get_models_path()
        assert "/ModelService/Tenants/" in path
        assert "/Service" in path

    def test_custom_tenant(self, aidp_service_module):
        path = aidp_service_module._get_models_path("my-tenant")
        assert "/ModelService/Tenants/my-tenant/Service" == path


# ---------------------------------------------------------------------------
# _is_kb_applicable tests
# ---------------------------------------------------------------------------
class TestIsKbApplicable:
    """Tests for _is_kb_applicable helper."""

    @pytest.fixture
    def check(self, aidp_service_module):
        return aidp_service_module._is_kb_applicable

    def test_string_all(self, check):
        assert check({"application": "All"}) is True

    def test_string_knowledge_base(self, check):
        assert check({"application": "KnowledgeBase"}) is True

    def test_string_unrelated(self, check):
        assert check({"application": "ChatBot"}) is False

    def test_list_with_all(self, check):
        assert check({"application": ["All"]}) is True

    def test_list_with_knowledge_base(self, check):
        assert check({"application": ["ChatBot", "KnowledgeBase"]}) is True

    def test_list_without_knowledge_base(self, check):
        assert check({"application": ["ChatBot", "AgentStudio"]}) is False

    def test_none_returns_false(self, check):
        assert check({"application": None}) is False

    def test_missing_key_returns_false(self, check):
        assert check({}) is False

    def test_empty_string_returns_false(self, check):
        assert check({"application": ""}) is False

    def test_non_string_non_list_returns_false(self, check):
        assert check({"application": 123}) is False


# ---------------------------------------------------------------------------
# _resolve_tenant_id tests
# ---------------------------------------------------------------------------
class TestResolveTenantId:
    """Tests for _resolve_tenant_id helper."""

    def test_explicit_string_tenant(self, aidp_service_module):
        result = aidp_service_module._resolve_tenant_id("my-tenant")
        assert result == "my-tenant"

    def test_none_uses_configured(self, aidp_service_module):
        result = aidp_service_module._resolve_tenant_id(None)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_whitespace_falls_back(self, aidp_service_module):
        result = aidp_service_module._resolve_tenant_id("   ")
        assert result == "aidp"

    def test_non_string_uses_configured(self, aidp_service_module):
        result = aidp_service_module._resolve_tenant_id(123)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Shared helper: mock manager setup
# ---------------------------------------------------------------------------
def _setup_mock_client(aidp_service_module, method="get", response=None, side_effect=None):
    """Create and wire a mock client into the aidp_service_module's http_client_manager."""
    mock_client = MagicMock()
    if side_effect is not None:
        getattr(mock_client, method).side_effect = side_effect
    elif response is not None:
        getattr(mock_client, method).return_value = response
    mock_manager = MagicMock()
    mock_manager.get_sync_client.return_value = mock_client
    aidp_service_module.http_client_manager = mock_manager
    return mock_client


def _make_http_error(status_code, method="GET"):
    """Create an httpx.HTTPStatusError with given status code."""
    request = httpx.Request(method, "http://127.0.0.1:30081")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        f"http {status_code}",
        request=request,
        response=response,
    )


def _make_success_response(json_data, status_code=200):
    """Create a mock response returning given JSON data."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data
    mock_resp.raise_for_status.return_value = None
    return mock_resp


# ---------------------------------------------------------------------------
# count_aidp_kbs_impl tests
# ---------------------------------------------------------------------------
class TestCountAidpKbsImpl:
    """Tests for count_aidp_kbs_impl (POST .../Count endpoint)."""

    @pytest.mark.parametrize(
        "server_url,api_key",
        [("", "token"), ("ftp://bad", "token"), ("http://ok", "")],
    )
    def test_invalid_config(self, aidp_service_module, server_url, api_key):
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.count_aidp_kbs_impl(server_url=server_url, api_key=api_key)
        assert exc_info.value.error_code == ErrorCode.AIDP_CONFIG_INVALID

    def test_success(self, aidp_service_module):
        mock_resp = _make_success_response({"count": 42})
        _setup_mock_client(aidp_service_module, method="post", response=mock_resp)

        result = aidp_service_module.count_aidp_kbs_impl(
            server_url="http://127.0.0.1:30081", api_key="jwt-token"
        )
        assert result == 42

    def test_missing_count_returns_zero(self, aidp_service_module):
        mock_resp = _make_success_response({})
        _setup_mock_client(aidp_service_module, method="post", response=mock_resp)

        result = aidp_service_module.count_aidp_kbs_impl(
            server_url="http://127.0.0.1:30081", api_key="jwt-token"
        )
        assert result == 0

    def test_non_dict_response_raises(self, aidp_service_module):
        mock_resp = _make_success_response(["not-a-dict"])
        _setup_mock_client(aidp_service_module, method="post", response=mock_resp)

        with pytest.raises(AppException) as exc_info:
            aidp_service_module.count_aidp_kbs_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_RESPONSE_ERROR

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_auth_error(self, aidp_service_module, status_code):
        _setup_mock_client(aidp_service_module, method="post", side_effect=_make_http_error(status_code))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.count_aidp_kbs_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_AUTH_ERROR

    def test_rate_limit_error(self, aidp_service_module):
        _setup_mock_client(aidp_service_module, method="post", side_effect=_make_http_error(429))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.count_aidp_kbs_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_RATE_LIMIT

    def test_service_error(self, aidp_service_module):
        _setup_mock_client(aidp_service_module, method="post", side_effect=_make_http_error(500))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.count_aidp_kbs_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_SERVICE_ERROR

    def test_connection_error(self, aidp_service_module):
        request = httpx.Request("POST", "http://127.0.0.1:30081")
        _setup_mock_client(
            aidp_service_module, method="post",
            side_effect=httpx.RequestError("network down", request=request),
        )
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.count_aidp_kbs_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_CONNECTION_ERROR

    def test_json_parse_value_error(self, aidp_service_module):
        mock_resp = _make_success_response({})
        mock_resp.json.side_effect = ValueError("bad json")
        _setup_mock_client(aidp_service_module, method="post", response=mock_resp)
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.count_aidp_kbs_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_RESPONSE_ERROR


# ---------------------------------------------------------------------------
# create_aidp_kb_impl tests
# ---------------------------------------------------------------------------
class TestCreateAidpKbImpl:
    """Tests for create_aidp_kb_impl (PUT create KB endpoint)."""

    @pytest.mark.parametrize(
        "server_url,api_key",
        [("", "token"), ("ftp://bad", "token"), ("http://ok", "")],
    )
    def test_invalid_config(self, aidp_service_module, server_url, api_key):
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.create_aidp_kb_impl(
                server_url=server_url, api_key=api_key, payload={"name": "kb"}
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_CONFIG_INVALID

    def test_success(self, aidp_service_module):
        mock_resp = _make_success_response({"kds_id": "new-kb", "name": "test-kb"})
        _setup_mock_client(aidp_service_module, method="put", response=mock_resp)

        result = aidp_service_module.create_aidp_kb_impl(
            server_url="http://127.0.0.1:30081",
            api_key="jwt-token",
            payload={"name": "test-kb"},
        )
        assert result["kds_id"] == "new-kb"

    def test_non_dict_response_raises(self, aidp_service_module):
        mock_resp = _make_success_response(["not-a-dict"])
        _setup_mock_client(aidp_service_module, method="put", response=mock_resp)

        with pytest.raises(AppException) as exc_info:
            aidp_service_module.create_aidp_kb_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
                payload={"name": "kb"},
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_RESPONSE_ERROR

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_auth_error(self, aidp_service_module, status_code):
        _setup_mock_client(aidp_service_module, method="put", side_effect=_make_http_error(status_code, "PUT"))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.create_aidp_kb_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
                payload={"name": "kb"},
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_AUTH_ERROR

    def test_rate_limit_error(self, aidp_service_module):
        _setup_mock_client(aidp_service_module, method="put", side_effect=_make_http_error(429, "PUT"))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.create_aidp_kb_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
                payload={"name": "kb"},
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_RATE_LIMIT

    def test_service_error(self, aidp_service_module):
        _setup_mock_client(aidp_service_module, method="put", side_effect=_make_http_error(500, "PUT"))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.create_aidp_kb_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
                payload={"name": "kb"},
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_SERVICE_ERROR

    def test_connection_error(self, aidp_service_module):
        request = httpx.Request("PUT", "http://127.0.0.1:30081")
        _setup_mock_client(
            aidp_service_module, method="put",
            side_effect=httpx.RequestError("network down", request=request),
        )
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.create_aidp_kb_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
                payload={"name": "kb"},
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_CONNECTION_ERROR

    def test_json_parse_value_error(self, aidp_service_module):
        mock_resp = _make_success_response({})
        mock_resp.json.side_effect = ValueError("bad json")
        _setup_mock_client(aidp_service_module, method="put", response=mock_resp)
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.create_aidp_kb_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
                payload={"name": "kb"},
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_RESPONSE_ERROR

    def test_non_2xx_logs_body_before_raise(self, aidp_service_module):
        """response.status_code >= 400 triggers diagnostic body logging (line 551)."""
        request = httpx.Request("PUT", "http://127.0.0.1:30081")
        resp = httpx.Response(500, request=request, text='{"error": "internal"}')
        mock_client = MagicMock()
        mock_client.put.return_value = resp
        mock_manager = MagicMock()
        mock_manager.get_sync_client.return_value = mock_client
        aidp_service_module.http_client_manager = mock_manager

        with pytest.raises(AppException) as exc_info:
            aidp_service_module.create_aidp_kb_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
                payload={"name": "kb"},
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_SERVICE_ERROR


# ---------------------------------------------------------------------------
# get_aidp_kb_impl tests
# ---------------------------------------------------------------------------
class TestGetAidpKbImpl:
    """Tests for get_aidp_kb_impl (GET KB detail endpoint)."""

    @pytest.mark.parametrize(
        "server_url,api_key",
        [("", "token"), ("ftp://bad", "token"), ("http://ok", "")],
    )
    def test_invalid_config(self, aidp_service_module, server_url, api_key):
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.get_aidp_kb_impl(
                server_url=server_url, api_key=api_key, kds_id="kb-1"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_CONFIG_INVALID

    def test_success_with_timestamps(self, aidp_service_module):
        mock_resp = _make_success_response({
            "kds_id": "kb-1",
            "name": "Test KB",
            "create_time": 1700000000,
            "update_time": 1700100000,
        })
        _setup_mock_client(aidp_service_module, method="get", response=mock_resp)

        result = aidp_service_module.get_aidp_kb_impl(
            server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
        )
        assert result["kds_id"] == "kb-1"
        assert result["created_at"] is not None
        assert result["updated_at"] is not None

    def test_success_without_timestamps(self, aidp_service_module):
        mock_resp = _make_success_response({"kds_id": "kb-1", "name": "Test KB"})
        _setup_mock_client(aidp_service_module, method="get", response=mock_resp)

        result = aidp_service_module.get_aidp_kb_impl(
            server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
        )
        assert "created_at" not in result
        assert "updated_at" not in result

    def test_non_dict_response_raises(self, aidp_service_module):
        mock_resp = _make_success_response(["not-a-dict"])
        _setup_mock_client(aidp_service_module, method="get", response=mock_resp)

        with pytest.raises(AppException) as exc_info:
            aidp_service_module.get_aidp_kb_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_RESPONSE_ERROR

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_auth_error(self, aidp_service_module, status_code):
        _setup_mock_client(aidp_service_module, method="get", side_effect=_make_http_error(status_code))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.get_aidp_kb_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_AUTH_ERROR

    def test_rate_limit_error(self, aidp_service_module):
        _setup_mock_client(aidp_service_module, method="get", side_effect=_make_http_error(429))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.get_aidp_kb_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_RATE_LIMIT

    def test_service_error(self, aidp_service_module):
        _setup_mock_client(aidp_service_module, method="get", side_effect=_make_http_error(500))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.get_aidp_kb_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_SERVICE_ERROR

    def test_connection_error(self, aidp_service_module):
        request = httpx.Request("GET", "http://127.0.0.1:30081")
        _setup_mock_client(
            aidp_service_module, method="get",
            side_effect=httpx.RequestError("network down", request=request),
        )
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.get_aidp_kb_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_CONNECTION_ERROR

    def test_json_parse_value_error(self, aidp_service_module):
        mock_resp = _make_success_response({})
        mock_resp.json.side_effect = ValueError("bad json")
        _setup_mock_client(aidp_service_module, method="get", response=mock_resp)
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.get_aidp_kb_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_RESPONSE_ERROR


# ---------------------------------------------------------------------------
# update_aidp_kb_impl tests
# ---------------------------------------------------------------------------
class TestUpdateAidpKbImpl:
    """Tests for update_aidp_kb_impl (PATCH update KB endpoint)."""

    @pytest.mark.parametrize(
        "server_url,api_key",
        [("", "token"), ("ftp://bad", "token"), ("http://ok", "")],
    )
    def test_invalid_config(self, aidp_service_module, server_url, api_key):
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.update_aidp_kb_impl(
                server_url=server_url, api_key=api_key, kds_id="kb-1", payload={"name": "new"}
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_CONFIG_INVALID

    def test_success(self, aidp_service_module):
        mock_resp = _make_success_response({"kds_id": "kb-1", "name": "updated"})
        _setup_mock_client(aidp_service_module, method="patch", response=mock_resp)

        result = aidp_service_module.update_aidp_kb_impl(
            server_url="http://127.0.0.1:30081",
            api_key="jwt-token",
            kds_id="kb-1",
            payload={"name": "updated"},
        )
        assert result["name"] == "updated"

    def test_non_dict_response_raises(self, aidp_service_module):
        mock_resp = _make_success_response([1, 2])
        _setup_mock_client(aidp_service_module, method="patch", response=mock_resp)

        with pytest.raises(AppException) as exc_info:
            aidp_service_module.update_aidp_kb_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
                kds_id="kb-1",
                payload={"name": "x"},
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_RESPONSE_ERROR

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_auth_error(self, aidp_service_module, status_code):
        _setup_mock_client(aidp_service_module, method="patch", side_effect=_make_http_error(status_code, "PATCH"))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.update_aidp_kb_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
                kds_id="kb-1",
                payload={"name": "x"},
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_AUTH_ERROR

    def test_rate_limit_error(self, aidp_service_module):
        _setup_mock_client(aidp_service_module, method="patch", side_effect=_make_http_error(429, "PATCH"))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.update_aidp_kb_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
                kds_id="kb-1",
                payload={"name": "x"},
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_RATE_LIMIT

    def test_service_error(self, aidp_service_module):
        _setup_mock_client(aidp_service_module, method="patch", side_effect=_make_http_error(500, "PATCH"))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.update_aidp_kb_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
                kds_id="kb-1",
                payload={"name": "x"},
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_SERVICE_ERROR

    def test_connection_error(self, aidp_service_module):
        request = httpx.Request("PATCH", "http://127.0.0.1:30081")
        _setup_mock_client(
            aidp_service_module, method="patch",
            side_effect=httpx.RequestError("network down", request=request),
        )
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.update_aidp_kb_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
                kds_id="kb-1",
                payload={"name": "x"},
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_CONNECTION_ERROR

    def test_json_parse_value_error(self, aidp_service_module):
        mock_resp = _make_success_response({})
        mock_resp.json.side_effect = ValueError("bad json")
        _setup_mock_client(aidp_service_module, method="patch", response=mock_resp)
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.update_aidp_kb_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
                kds_id="kb-1",
                payload={"name": "x"},
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_RESPONSE_ERROR


# ---------------------------------------------------------------------------
# delete_aidp_kb_impl tests
# ---------------------------------------------------------------------------
class TestDeleteAidpKbImpl:
    """Tests for delete_aidp_kb_impl (DELETE KB endpoint)."""

    @pytest.mark.parametrize(
        "server_url,api_key",
        [("", "token"), ("ftp://bad", "token"), ("http://ok", "")],
    )
    def test_invalid_config(self, aidp_service_module, server_url, api_key):
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.delete_aidp_kb_impl(
                server_url=server_url, api_key=api_key, kds_id="kb-1"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_CONFIG_INVALID

    def test_success(self, aidp_service_module):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        _setup_mock_client(aidp_service_module, method="delete", response=mock_resp)

        result = aidp_service_module.delete_aidp_kb_impl(
            server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
        )
        assert result is True

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_auth_error(self, aidp_service_module, status_code):
        _setup_mock_client(aidp_service_module, method="delete", side_effect=_make_http_error(status_code, "DELETE"))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.delete_aidp_kb_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_AUTH_ERROR

    def test_rate_limit_error(self, aidp_service_module):
        _setup_mock_client(aidp_service_module, method="delete", side_effect=_make_http_error(429, "DELETE"))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.delete_aidp_kb_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_RATE_LIMIT

    def test_service_error(self, aidp_service_module):
        _setup_mock_client(aidp_service_module, method="delete", side_effect=_make_http_error(500, "DELETE"))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.delete_aidp_kb_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_SERVICE_ERROR

    def test_connection_error(self, aidp_service_module):
        request = httpx.Request("DELETE", "http://127.0.0.1:30081")
        _setup_mock_client(
            aidp_service_module, method="delete",
            side_effect=httpx.RequestError("network down", request=request),
        )
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.delete_aidp_kb_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_CONNECTION_ERROR


# ---------------------------------------------------------------------------
# upload_aidp_docs_impl tests
# ---------------------------------------------------------------------------
class TestUploadAidpDocsImpl:
    """Tests for upload_aidp_docs_impl (POST upload files endpoint)."""

    @pytest.fixture
    def mock_file(self):
        f = MagicMock()
        f.filename = "test.pdf"
        f.file = MagicMock()
        f.content_type = "application/pdf"
        return f

    @pytest.fixture
    def mock_file_no_ct(self):
        f = MagicMock()
        f.filename = "data.bin"
        f.file = MagicMock()
        f.content_type = None
        return f

    @pytest.mark.parametrize(
        "server_url,api_key",
        [("", "token"), ("ftp://bad", "token"), ("http://ok", "")],
    )
    def test_invalid_config(self, aidp_service_module, server_url, api_key, mock_file):
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.upload_aidp_docs_impl(
                server_url=server_url, api_key=api_key, kds_id="kb-1", files=[mock_file]
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_CONFIG_INVALID

    def test_success(self, aidp_service_module, mock_file):
        upload_response = {
            "summary": {"total": 1, "success": 0, "failed": 1},
            "success_list": [],
            "failed_list": [{
                "file_name": "test.pdf",
                "reason_zh": "文件内容为空",
                "reason_en": "File content is empty",
            }],
        }
        mock_resp = _make_success_response(upload_response)
        _setup_mock_client(aidp_service_module, method="post", response=mock_resp)

        result = aidp_service_module.upload_aidp_docs_impl(
            server_url="http://127.0.0.1:30081",
            api_key="jwt-token",
            kds_id="kb-1",
            files=[mock_file],
        )
        assert result == upload_response

    def test_file_with_no_content_type_uses_octet_stream(self, aidp_service_module, mock_file_no_ct):
        mock_resp = _make_success_response({"uploaded": 1})
        _setup_mock_client(aidp_service_module, method="post", response=mock_resp)

        aidp_service_module.upload_aidp_docs_impl(
            server_url="http://127.0.0.1:30081",
            api_key="jwt-token",
            kds_id="kb-1",
            files=[mock_file_no_ct],
        )

        call_kwargs = aidp_service_module.http_client_manager.get_sync_client.return_value.post.call_args
        file_tuples = call_kwargs.kwargs["files"]
        assert file_tuples[0][1][2] == "application/octet-stream"

    def test_non_dict_response_raises(self, aidp_service_module, mock_file):
        mock_resp = _make_success_response("string-response")
        _setup_mock_client(aidp_service_module, method="post", response=mock_resp)

        with pytest.raises(AppException) as exc_info:
            aidp_service_module.upload_aidp_docs_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
                kds_id="kb-1",
                files=[mock_file],
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_RESPONSE_ERROR

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_auth_error(self, aidp_service_module, status_code, mock_file):
        _setup_mock_client(aidp_service_module, method="post", side_effect=_make_http_error(status_code))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.upload_aidp_docs_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
                kds_id="kb-1",
                files=[mock_file],
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_AUTH_ERROR

    def test_rate_limit_error(self, aidp_service_module, mock_file):
        _setup_mock_client(aidp_service_module, method="post", side_effect=_make_http_error(429))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.upload_aidp_docs_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
                kds_id="kb-1",
                files=[mock_file],
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_RATE_LIMIT

    def test_service_error(self, aidp_service_module, mock_file):
        _setup_mock_client(aidp_service_module, method="post", side_effect=_make_http_error(500))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.upload_aidp_docs_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
                kds_id="kb-1",
                files=[mock_file],
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_SERVICE_ERROR

    def test_service_error_preserves_structured_upstream_reason(self, aidp_service_module, mock_file):
        request = httpx.Request("POST", "http://127.0.0.1:30081/upload")
        response = httpx.Response(
            500,
            request=request,
            json={"detail": {"reason_zh": "文件解析服务不可用"}},
        )
        error = httpx.HTTPStatusError(
            "http 500",
            request=request,
            response=response,
        )
        _setup_mock_client(aidp_service_module, method="post", side_effect=error)

        with pytest.raises(AppException) as exc_info:
            aidp_service_module.upload_aidp_docs_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
                kds_id="kb-1",
                files=[mock_file],
            )

        assert exc_info.value.message == "文件解析服务不可用"
        assert exc_info.value.details == {
            "upstream_status": 500,
            "upstream_reason": "文件解析服务不可用",
        }

    def test_structured_file_error_returns_localized_failed_list(self, aidp_service_module, mock_file):
        request = httpx.Request("POST", "http://127.0.0.1:30081/upload")
        response = httpx.Response(
            500,
            request=request,
            json={
                "error": {
                    "code": 1001,
                    "message": "Upload knowledge files failed",
                    "details": [
                        {
                            "file_name": "test.pdf",
                            "reason_zh": "文件已存在，请重命名或删除已有文件",
                            "reason_en": "File already exists. Please rename or delete the existing file.",
                        }
                    ],
                }
            },
        )
        error = httpx.HTTPStatusError(
            "http 500",
            request=request,
            response=response,
        )
        _setup_mock_client(aidp_service_module, method="post", side_effect=error)

        result = aidp_service_module.upload_aidp_docs_impl(
            server_url="http://127.0.0.1:30081",
            api_key="jwt-token",
            kds_id="kb-1",
            files=[mock_file],
        )

        assert result == {
            "summary": {"total": 1, "success": 0, "failed": 1},
            "success_list": [],
            "failed_list": [
                {
                    "file_name": "test.pdf",
                    "reason_zh": "文件已存在，请重命名或删除已有文件",
                    "reason_en": "File already exists. Please rename or delete the existing file.",
                }
            ],
        }

    def test_structured_file_error_is_parsed_for_non_server_status(self, aidp_service_module, mock_file):
        request = httpx.Request("POST", "http://127.0.0.1:30081/upload")
        response = httpx.Response(
            409,
            request=request,
            json={
                "error": {
                    "code": 1001,
                    "message": "Upload knowledge files failed",
                    "details": [
                        {
                            "file_name": "test.pdf",
                            "reason_zh": "文件已存在，请重命名或删除已有文件",
                            "reason_en": "File already exists. Please rename or delete the existing file.",
                        }
                    ],
                }
            },
        )
        error = httpx.HTTPStatusError(
            "http 409",
            request=request,
            response=response,
        )
        _setup_mock_client(aidp_service_module, method="post", side_effect=error)

        result = aidp_service_module.upload_aidp_docs_impl(
            server_url="http://127.0.0.1:30081",
            api_key="jwt-token",
            kds_id="kb-1",
            files=[mock_file],
        )

        assert result["summary"] == {"total": 1, "success": 0, "failed": 1}
        assert result["failed_list"] == [
            {
                "file_name": "test.pdf",
                "reason_zh": "文件已存在，请重命名或删除已有文件",
                "reason_en": "File already exists. Please rename or delete the existing file.",
            }
        ]

    def test_service_error_uses_bounded_plain_text_reason(self, aidp_service_module, mock_file):
        request = httpx.Request("POST", "http://127.0.0.1:30081/upload")
        response = httpx.Response(
            500,
            request=request,
            headers={"content-type": "text/plain"},
            text="parser unavailable",
        )
        error = httpx.HTTPStatusError(
            "http 500",
            request=request,
            response=response,
        )
        _setup_mock_client(aidp_service_module, method="post", side_effect=error)

        with pytest.raises(AppException) as exc_info:
            aidp_service_module.upload_aidp_docs_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
                kds_id="kb-1",
                files=[mock_file],
            )

        assert exc_info.value.message == "parser unavailable"
        assert exc_info.value.details["upstream_reason"] == "parser unavailable"

    def test_connection_error(self, aidp_service_module, mock_file):
        request = httpx.Request("POST", "http://127.0.0.1:30081")
        _setup_mock_client(
            aidp_service_module, method="post",
            side_effect=httpx.RequestError("network down", request=request),
        )
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.upload_aidp_docs_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
                kds_id="kb-1",
                files=[mock_file],
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_CONNECTION_ERROR

    def test_json_parse_value_error(self, aidp_service_module, mock_file):
        mock_resp = _make_success_response({})
        mock_resp.json.side_effect = ValueError("bad json")
        _setup_mock_client(aidp_service_module, method="post", response=mock_resp)
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.upload_aidp_docs_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
                kds_id="kb-1",
                files=[mock_file],
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_RESPONSE_ERROR


# ---------------------------------------------------------------------------
# count_aidp_docs_impl tests
# ---------------------------------------------------------------------------
class TestCountAidpDocsImpl:
    """Tests for count_aidp_docs_impl (POST .../KnowledgeFiles/Count)."""

    @pytest.mark.parametrize(
        "server_url,api_key",
        [("", "token"), ("ftp://bad", "token"), ("http://ok", "")],
    )
    def test_invalid_config(self, aidp_service_module, server_url, api_key):
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.count_aidp_docs_impl(
                server_url=server_url, api_key=api_key, kds_id="kb-1"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_CONFIG_INVALID

    def test_success(self, aidp_service_module):
        mock_resp = _make_success_response({"count": 15})
        _setup_mock_client(aidp_service_module, method="post", response=mock_resp)

        result = aidp_service_module.count_aidp_docs_impl(
            server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
        )
        assert result == 15

    def test_missing_count_returns_zero(self, aidp_service_module):
        mock_resp = _make_success_response({})
        _setup_mock_client(aidp_service_module, method="post", response=mock_resp)

        result = aidp_service_module.count_aidp_docs_impl(
            server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
        )
        assert result == 0

    def test_non_dict_response_raises(self, aidp_service_module):
        mock_resp = _make_success_response(999)
        _setup_mock_client(aidp_service_module, method="post", response=mock_resp)

        with pytest.raises(AppException) as exc_info:
            aidp_service_module.count_aidp_docs_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_RESPONSE_ERROR

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_auth_error(self, aidp_service_module, status_code):
        _setup_mock_client(aidp_service_module, method="post", side_effect=_make_http_error(status_code))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.count_aidp_docs_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_AUTH_ERROR

    def test_404_returns_zero(self, aidp_service_module):
        _setup_mock_client(aidp_service_module, method="post", side_effect=_make_http_error(404))
        result = aidp_service_module.count_aidp_docs_impl(
            server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
        )
        assert result == 0

    def test_rate_limit_error(self, aidp_service_module):
        _setup_mock_client(aidp_service_module, method="post", side_effect=_make_http_error(429))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.count_aidp_docs_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_RATE_LIMIT

    def test_service_error(self, aidp_service_module):
        _setup_mock_client(aidp_service_module, method="post", side_effect=_make_http_error(500))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.count_aidp_docs_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_SERVICE_ERROR

    def test_connection_error(self, aidp_service_module):
        request = httpx.Request("POST", "http://127.0.0.1:30081")
        _setup_mock_client(
            aidp_service_module, method="post",
            side_effect=httpx.RequestError("network down", request=request),
        )
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.count_aidp_docs_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_CONNECTION_ERROR

    def test_json_parse_value_error(self, aidp_service_module):
        mock_resp = _make_success_response({})
        mock_resp.json.side_effect = ValueError("bad json")
        _setup_mock_client(aidp_service_module, method="post", response=mock_resp)
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.count_aidp_docs_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_RESPONSE_ERROR


# ---------------------------------------------------------------------------
# list_aidp_docs_impl tests
# ---------------------------------------------------------------------------
class TestListAidpDocsImpl:
    """Tests for list_aidp_docs_impl (GET .../KnowledgeFiles list endpoint)."""

    @pytest.mark.parametrize(
        "server_url,api_key",
        [("", "token"), ("ftp://bad", "token"), ("http://ok", "")],
    )
    def test_invalid_config(self, aidp_service_module, server_url, api_key):
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.list_aidp_docs_impl(
                server_url=server_url, api_key=api_key, kds_id="kb-1"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_CONFIG_INVALID

    def test_success_normalizes_docs(self, aidp_service_module):
        mock_resp = _make_success_response({
            "value": [
                {"name": "doc1", "first_upload_time": 1700000000},
                {"name": "doc2", "create_time": 1700100000, "update_time": 1700200000},
            ],
            "total_count": 2,
        })
        _setup_mock_client(aidp_service_module, method="get", response=mock_resp)

        result = aidp_service_module.list_aidp_docs_impl(
            server_url="http://127.0.0.1:30081",
            api_key="jwt-token",
            kds_id="kb-1",
            page=1,
            page_size=10,
        )
        assert len(result["value"]) == 2
        # Normalization adds created_at / updated_at
        assert result["value"][0]["created_at"] is not None
        assert result["value"][1]["updated_at"] is not None

    def test_success_non_list_value_not_normalized(self, aidp_service_module):
        mock_resp = _make_success_response({"value": "not-a-list", "total_count": 0})
        _setup_mock_client(aidp_service_module, method="get", response=mock_resp)

        result = aidp_service_module.list_aidp_docs_impl(
            server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
        )
        assert result["value"] == "not-a-list"

    def test_non_dict_response_raises(self, aidp_service_module):
        mock_resp = _make_success_response([1, 2, 3])
        _setup_mock_client(aidp_service_module, method="get", response=mock_resp)

        with pytest.raises(AppException) as exc_info:
            aidp_service_module.list_aidp_docs_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_RESPONSE_ERROR

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_auth_error(self, aidp_service_module, status_code):
        _setup_mock_client(aidp_service_module, method="get", side_effect=_make_http_error(status_code))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.list_aidp_docs_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_AUTH_ERROR

    def test_rate_limit_error(self, aidp_service_module):
        _setup_mock_client(aidp_service_module, method="get", side_effect=_make_http_error(429))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.list_aidp_docs_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_RATE_LIMIT

    def test_service_error(self, aidp_service_module):
        _setup_mock_client(aidp_service_module, method="get", side_effect=_make_http_error(500))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.list_aidp_docs_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_SERVICE_ERROR

    def test_connection_error(self, aidp_service_module):
        request = httpx.Request("GET", "http://127.0.0.1:30081")
        _setup_mock_client(
            aidp_service_module, method="get",
            side_effect=httpx.RequestError("network down", request=request),
        )
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.list_aidp_docs_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_CONNECTION_ERROR

    def test_json_parse_value_error(self, aidp_service_module):
        mock_resp = _make_success_response({})
        mock_resp.json.side_effect = ValueError("bad json")
        _setup_mock_client(aidp_service_module, method="get", response=mock_resp)
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.list_aidp_docs_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token", kds_id="kb-1"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_RESPONSE_ERROR


# ---------------------------------------------------------------------------
# list_aidp_models_impl tests
# ---------------------------------------------------------------------------
class TestListAidpModelsImpl:
    """Tests for list_aidp_models_impl (GET .../ModelService/... endpoint)."""

    @pytest.mark.parametrize(
        "server_url,api_key",
        [("", "token"), ("ftp://bad", "token"), ("http://ok", "")],
    )
    def test_invalid_config(self, aidp_service_module, server_url, api_key):
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.list_aidp_models_impl(
                server_url=server_url, api_key=api_key
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_CONFIG_INVALID

    def test_success_filters_models(self, aidp_service_module):
        mock_resp = _make_success_response({
            "models": [
                {"model_name": "gpt-4", "application": "All"},
                {"model_name": "gpt-3.5", "application": "KnowledgeBase"},
                {"model_name": "whisper", "application": "ChatBot"},
                {"model_name": "no-app"},
            ],
        })
        _setup_mock_client(aidp_service_module, method="get", response=mock_resp)

        result = aidp_service_module.list_aidp_models_impl(
            server_url="http://127.0.0.1:30081", api_key="jwt-token"
        )
        assert result["total_count"] == 2
        names = [m["model_name"] for m in result["models"]]
        assert "gpt-4" in names
        assert "gpt-3.5" in names

    def test_empty_models_list(self, aidp_service_module):
        mock_resp = _make_success_response({"models": []})
        _setup_mock_client(aidp_service_module, method="get", response=mock_resp)

        result = aidp_service_module.list_aidp_models_impl(
            server_url="http://127.0.0.1:30081", api_key="jwt-token"
        )
        assert result["total_count"] == 0
        assert result["models"] == []

    def test_missing_models_key(self, aidp_service_module):
        mock_resp = _make_success_response({})
        _setup_mock_client(aidp_service_module, method="get", response=mock_resp)

        result = aidp_service_module.list_aidp_models_impl(
            server_url="http://127.0.0.1:30081", api_key="jwt-token"
        )
        assert result["total_count"] == 0

    def test_non_dict_response_raises(self, aidp_service_module):
        mock_resp = _make_success_response(["not-dict"])
        _setup_mock_client(aidp_service_module, method="get", response=mock_resp)

        with pytest.raises(AppException) as exc_info:
            aidp_service_module.list_aidp_models_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_RESPONSE_ERROR

    def test_models_not_list_raises(self, aidp_service_module):
        mock_resp = _make_success_response({"models": "not-a-list"})
        _setup_mock_client(aidp_service_module, method="get", response=mock_resp)

        with pytest.raises(AppException) as exc_info:
            aidp_service_module.list_aidp_models_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_RESPONSE_ERROR

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_auth_error(self, aidp_service_module, status_code):
        _setup_mock_client(aidp_service_module, method="get", side_effect=_make_http_error(status_code))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.list_aidp_models_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_AUTH_ERROR

    def test_rate_limit_error(self, aidp_service_module):
        _setup_mock_client(aidp_service_module, method="get", side_effect=_make_http_error(429))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.list_aidp_models_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_RATE_LIMIT

    def test_service_error(self, aidp_service_module):
        _setup_mock_client(aidp_service_module, method="get", side_effect=_make_http_error(500))
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.list_aidp_models_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_SERVICE_ERROR

    def test_connection_error(self, aidp_service_module):
        request = httpx.Request("GET", "http://127.0.0.1:30081")
        _setup_mock_client(
            aidp_service_module, method="get",
            side_effect=httpx.RequestError("network down", request=request),
        )
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.list_aidp_models_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_CONNECTION_ERROR

    def test_json_parse_value_error(self, aidp_service_module):
        mock_resp = _make_success_response({})
        mock_resp.json.side_effect = ValueError("bad json")
        _setup_mock_client(aidp_service_module, method="get", response=mock_resp)
        with pytest.raises(AppException) as exc_info:
            aidp_service_module.list_aidp_models_impl(
                server_url="http://127.0.0.1:30081", api_key="jwt-token"
            )
        assert exc_info.value.error_code == ErrorCode.AIDP_RESPONSE_ERROR
