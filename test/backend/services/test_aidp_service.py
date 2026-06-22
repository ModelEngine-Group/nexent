import importlib.util
import os
import sys
from types import ModuleType
from unittest.mock import MagicMock

import httpx
import pytest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
BACKEND_ROOT = os.path.join(PROJECT_ROOT, "backend")
SERVICE_PATH = os.path.join(BACKEND_ROOT, "services", "aidp_service.py")

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

    module_name = "backend.services.aidp_service"
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
    def test_fetch_success_uses_bearer_header(self, aidp_service_module):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "value": [{"kds_id": "kb-1", "kds_name": "Knowledge Base 1"}],
            "total_count": 1,
        }
        mock_response.raise_for_status.return_value = None
        mock_client.get.return_value = mock_response

        mock_manager = MagicMock()
        mock_manager.get_sync_client.return_value = mock_client
        aidp_service_module.http_client_manager = mock_manager

        result = aidp_service_module.fetch_aidp_knowledge_bases_impl(
            server_url="http://127.0.0.1:30081",
            api_key="jwt-token",
            page=2,
            page_size=15,
        )

        assert result["total_count"] == 1
        mock_client.get.assert_called_once_with(
            "http://127.0.0.1:30081/KnowledgeBase/Tenants/aidp/KnowledgeBases?page=2&page_size=15",
            headers={
                "Authorization": "Bearer jwt-token",
                "Content-Type": "application/json",
            },
        )

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
    def test_fetch_auth_error(
        self,
        aidp_service_module,
        status_code: int,
    ):
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

    def test_fetch_http_status_error_maps_service_error(
        self,
        aidp_service_module,
    ):
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

    def test_fetch_request_error_maps_connection_error(
        self,
        aidp_service_module,
    ):
        request = httpx.Request("GET", "http://127.0.0.1:30081")
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.RequestError(
            "network down",
            request=request,
        )

        mock_manager = MagicMock()
        mock_manager.get_sync_client.return_value = mock_client
        aidp_service_module.http_client_manager = mock_manager

        with pytest.raises(AppException) as exc_info:
            aidp_service_module.fetch_aidp_knowledge_bases_impl(
                server_url="http://127.0.0.1:30081",
                api_key="jwt-token",
            )

        assert exc_info.value.error_code == ErrorCode.AIDP_CONNECTION_ERROR

    def test_fetch_invalid_json_shape_maps_service_error(
        self,
        aidp_service_module,
    ):
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
