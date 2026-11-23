"""Unit tests for aidp_client.AidpClient and AidpAdapterError.

Covers every public method with happy-path and error-path scenarios.
All external I/O (httpx client, http_client_manager) is mocked.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from types import ModuleType
from unittest.mock import MagicMock, PropertyMock

import httpx
import pytest


# ---------------------------------------------------------------------------
# Module loading helpers (pattern copied from test_aidp_service.py)
# ---------------------------------------------------------------------------

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
CLIENT_PATH = os.path.join(
    PROJECT_ROOT, "sdk", "nexent", "core", "ext_components", "aidp", "knowledge_base", "aidp_client.py"
)


def _register_module(name: str, module: ModuleType, originals: dict[str, ModuleType]) -> None:
    if name in sys.modules:
        originals[name] = sys.modules[name]
    sys.modules[name] = module


@pytest.fixture
def aidp_client_module():
    """Load aidp_client.py with all dependencies stubbed so it can be imported."""
    originals: dict[str, ModuleType] = {}

    # -- nexent base packages
    nexent_pkg = ModuleType("nexent")
    nexent_pkg.__path__ = []
    _register_module("nexent", nexent_pkg, originals)

    nexent_utils_pkg = ModuleType("nexent.utils")
    nexent_utils_pkg.__path__ = []
    _register_module("nexent.utils", nexent_utils_pkg, originals)

    http_mgr = MagicMock()
    http_client_mod = ModuleType("nexent.utils.http_client_manager")
    http_client_mod.http_client_manager = http_mgr
    _register_module("nexent.utils.http_client_manager", http_client_mod, originals)

    # -- nexent.core (intermediate packages)
    nexent_core_pkg = ModuleType("nexent.core")
    nexent_core_pkg.__path__ = []
    _register_module("nexent.core", nexent_core_pkg, originals)

    # -- nexent.core.knowledge_base.config (the missing config module)
    kb_pkg = ModuleType("nexent.core.knowledge_base")
    kb_pkg.__path__ = []
    _register_module("nexent.core.knowledge_base", kb_pkg, originals)

    config_mod = ModuleType("nexent.core.knowledge_base.config")
    config_mod.AIDP_API_KEY = "test-api-key"
    config_mod.AIDP_BASE_URL = "https://aidp.example.com"
    config_mod.AIDP_TENANT_ID = "tenant-001"
    config_mod.COUNT_PATH_KDS_ID = "default-kds-id"
    _register_module("nexent.core.knowledge_base.config", config_mod, originals)

    # -- Load the module under test
    module_name = "nexent.core.ext_components.aidp.knowledge_base.aidp_client"
    spec = importlib.util.spec_from_file_location(module_name, CLIENT_PATH)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "nexent.core.ext_components.aidp.knowledge_base"

    # Register intermediate packages so the relative import resolves
    for pkg_name in [
        "nexent.core.ext_components",
        "nexent.core.ext_components.aidp",
        "nexent.core.ext_components.aidp.knowledge_base",
    ]:
        pkg = ModuleType(pkg_name)
        pkg.__path__ = []
        _register_module(pkg_name, pkg, originals)

    _register_module(module_name, module, originals)
    spec.loader.exec_module(module)

    yield module

    # Teardown: restore original sys.modules
    for name in [
        module_name,
        "nexent.core.ext_components.aidp.knowledge_base",
        "nexent.core.ext_components.aidp",
        "nexent.core.ext_components",
        "nexent.core.knowledge_base.config",
        "nexent.core.knowledge_base",
        "nexent.core",
        "nexent.utils.http_client_manager",
        "nexent.utils",
        "nexent",
    ]:
        if name in originals:
            sys.modules[name] = originals[name]
        else:
            sys.modules.pop(name, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(status_code: int = 200, json_data=None, content: bytes | None = None, text: str = ""):
    """Build a minimal httpx.Response mock."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.content = content if content is not None else (b"{}" if status_code != 204 else b"")
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    resp.raise_for_status = MagicMock()
    return resp


def _make_http_status_error(status_code: int, body_json=None, body_text: str = ""):
    """Build an httpx.HTTPStatusError with a mocked response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    if body_json is not None:
        resp.json.return_value = body_json
    else:
        resp.json.side_effect = ValueError("No JSON")
    resp.text = body_text
    return httpx.HTTPStatusError(
        message=f"{status_code} error",
        request=MagicMock(),
        response=resp,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_http_mgr():
    """Return a fresh MagicMock for http_client_manager used by AidpClient."""
    originals: dict[str, ModuleType] = {}
    manager = MagicMock()

    # Patch into sys.modules
    if "nexent.utils.http_client_manager" in sys.modules:
        originals["nexent.utils.http_client_manager"] = sys.modules["nexent.utils.http_client_manager"]
    mod = ModuleType("nexent.utils.http_client_manager")
    mod.http_client_manager = manager
    sys.modules["nexent.utils.http_client_manager"] = mod

    yield manager

    if "nexent.utils.http_client_manager" in originals:
        sys.modules["nexent.utils.http_client_manager"] = originals["nexent.utils.http_client_manager"]


@pytest.fixture
def client(aidp_client_module, mock_http_mgr):
    """Pre-built AidpClient with a mocked underlying HTTP client."""
    mock_http_client = MagicMock()
    mock_http_mgr.get_sync_client.return_value = mock_http_client

    AidpClient = aidp_client_module.AidpClient
    instance = AidpClient(
        base_url="https://aidp.example.com",
        api_key="test-api-key",
        tenant_id="tenant-001",
    )
    instance._client = mock_http_client
    return instance


# ===========================================================================
# AidpAdapterError
# ===========================================================================


class TestAidpAdapterError:
    def test_stores_all_attributes(self, aidp_client_module):
        """Stores message, status_code, and response_body."""
        AidpAdapterError = aidp_client_module.AidpAdapterError
        err = AidpAdapterError("boom", status_code=404, response_body={"detail": "nope"})
        assert str(err) == "boom"
        assert err.status_code == 404
        assert err.response_body == {"detail": "nope"}

    def test_defaults(self, aidp_client_module):
        """Default status_code is 500 and response_body is None."""
        AidpAdapterError = aidp_client_module.AidpAdapterError
        err = AidpAdapterError("fail")
        assert err.status_code == 500
        assert err.response_body is None

    def test_is_runtime_error(self, aidp_client_module):
        """Inherits from RuntimeError."""
        AidpAdapterError = aidp_client_module.AidpAdapterError
        err = AidpAdapterError("x")
        assert isinstance(err, RuntimeError)


# ===========================================================================
# AidpClient.__init__
# ===========================================================================


class TestAidpClientInit:
    def test_successful_construction(self, aidp_client_module, mock_http_mgr):
        """Valid base_url and api_key create a client with attributes set."""
        AidpClient = aidp_client_module.AidpClient
        c = AidpClient(base_url="https://api.example.com", api_key="key123", tenant_id="t1")
        assert c.base_url == "https://api.example.com"
        assert c.api_key == "key123"
        assert c.tenant_id == "t1"
        assert c._client is not None

    def test_strips_trailing_slash(self, aidp_client_module, mock_http_mgr):
        """Trailing slash on base_url is stripped."""
        AidpClient = aidp_client_module.AidpClient
        c = AidpClient(base_url="https://api.example.com/", api_key="key123")
        assert c.base_url == "https://api.example.com"

    def test_invalid_base_url_raises(self, aidp_client_module, mock_http_mgr):
        """base_url without http:// or https:// prefix raises ValueError."""
        AidpClient = aidp_client_module.AidpClient
        with pytest.raises(ValueError, match="base URL must start with"):
            AidpClient(base_url="ftp://bad", api_key="key")

    def test_empty_base_url_raises(self, aidp_client_module, mock_http_mgr):
        """Empty base_url raises ValueError."""
        AidpClient = aidp_client_module.AidpClient
        with pytest.raises(ValueError, match="base URL"):
            AidpClient(base_url="", api_key="key")

    def test_empty_api_key_raises(self, aidp_client_module, mock_http_mgr):
        """Empty api_key raises ValueError."""
        AidpClient = aidp_client_module.AidpClient
        with pytest.raises(ValueError, match="API key is required"):
            AidpClient(base_url="https://ok.com", api_key="")


# ===========================================================================
# health_check
# ===========================================================================


class TestHealthCheck:
    def test_returns_true_on_success(self, client, aidp_client_module):
        """health_check returns True when count_knowledge_bases succeeds."""
        client._client.request.return_value = _make_response(200, json_data={"count": 5})
        assert client.health_check() is True

    def test_propagates_error(self, client, aidp_client_module):
        """health_check raises AidpAdapterError when the underlying call fails."""
        AidpAdapterError = aidp_client_module.AidpAdapterError
        client._client.request.side_effect = httpx.ConnectError("connection refused")
        with pytest.raises(AidpAdapterError):
            client.health_check()


# ===========================================================================
# create_knowledge_base
# ===========================================================================


class TestCreateKnowledgeBase:
    def test_success(self, client, aidp_client_module):
        """Sends PUT with payload and returns the response dict."""
        expected = {"id": "kb-1", "name": "my-kb"}
        client._client.request.return_value = _make_response(200, json_data=expected)
        result = client.create_knowledge_base({"name": "my-kb"})
        assert result == expected
        call_args = client._client.request.call_args
        assert call_args.args[0] == "PUT"
        assert "/KnowledgeBases" in call_args.args[1]

    def test_http_error_raises(self, client, aidp_client_module):
        """HTTP 400 from the server raises AidpAdapterError."""
        AidpAdapterError = aidp_client_module.AidpAdapterError
        client._client.request.side_effect = _make_http_status_error(
            400, body_json={"error": {"message": "bad payload"}}
        )
        with pytest.raises(AidpAdapterError, match="bad payload"):
            client.create_knowledge_base({"name": ""})


# ===========================================================================
# list_knowledge_bases
# ===========================================================================


class TestListKnowledgeBases:
    def test_success(self, client, aidp_client_module):
        """Sends GET with pagination params and returns response."""
        expected = {"items": [{"id": "kb-1"}], "total": 1}
        resp = _make_response(200, json_data=expected)
        client._client.request.return_value = resp
        result = client.list_knowledge_bases(page=1, page_size=10)
        assert result == expected
        call_kwargs = client._client.request.call_args.kwargs
        assert call_kwargs["params"] == {"page": 1, "page_size": 10}

    def test_request_error_raises(self, client, aidp_client_module):
        """Network error raises AidpAdapterError with status 503."""
        AidpAdapterError = aidp_client_module.AidpAdapterError
        client._client.request.side_effect = httpx.ConnectError("timeout")
        with pytest.raises(AidpAdapterError) as exc_info:
            client.list_knowledge_bases(page=1, page_size=10)
        assert exc_info.value.status_code == 503


# ===========================================================================
# count_knowledge_bases
# ===========================================================================


class TestCountKnowledgeBases:
    def test_returns_count(self, client, aidp_client_module):
        """Parses the count field from response."""
        client._client.request.return_value = _make_response(200, json_data={"count": 42})
        assert client.count_knowledge_bases() == 42

    def test_non_dict_response_returns_zero(self, client, aidp_client_module):
        """If the response is not a dict, returns 0."""
        resp = _make_response(200, content=b"not-json", text="not-json")
        resp.json.side_effect = ValueError("not json")
        client._client.request.return_value = resp
        assert client.count_knowledge_bases() == 0

    def test_missing_count_field_returns_zero(self, client, aidp_client_module):
        """If response dict has no 'count' key, returns 0."""
        client._client.request.return_value = _make_response(200, json_data={"other": "data"})
        assert client.count_knowledge_bases(is_personal=1) == 0

    def test_custom_kds_id_in_path(self, client, aidp_client_module):
        """Custom kds_id is used in the URL path."""
        client._client.request.return_value = _make_response(200, json_data={"count": 1})
        client.count_knowledge_bases(kds_id="custom-kds")
        call_url = client._client.request.call_args.args[1]
        assert "custom-kds/Count" in call_url


# ===========================================================================
# get_knowledge_base
# ===========================================================================


class TestGetKnowledgeBase:
    def test_success(self, client, aidp_client_module):
        """Sends GET with the knowledge_base_id in the URL."""
        expected = {"id": "kb-1", "name": "test"}
        client._client.request.return_value = _make_response(200, json_data=expected)
        result = client.get_knowledge_base("kb-1")
        assert result == expected
        call_url = client._client.request.call_args.args[1]
        assert "KnowledgeBases/kb-1" in call_url

    def test_404_raises(self, client, aidp_client_module):
        """404 from the server raises AidpAdapterError."""
        AidpAdapterError = aidp_client_module.AidpAdapterError
        client._client.request.side_effect = _make_http_status_error(404, body_text="not found")
        with pytest.raises(AidpAdapterError, match="not found"):
            client.get_knowledge_base("kb-missing")


# ===========================================================================
# update_knowledge_base
# ===========================================================================


class TestUpdateKnowledgeBase:
    def test_success(self, client, aidp_client_module):
        """Sends PATCH with payload."""
        expected = {"id": "kb-1", "name": "updated"}
        client._client.request.return_value = _make_response(200, json_data=expected)
        result = client.update_knowledge_base("kb-1", {"name": "updated"})
        assert result == expected
        assert client._client.request.call_args.args[0] == "PATCH"

    def test_http_error_raises(self, client, aidp_client_module):
        """Server error raises AidpAdapterError."""
        AidpAdapterError = aidp_client_module.AidpAdapterError
        client._client.request.side_effect = _make_http_status_error(500, body_json={"message": "internal"})
        with pytest.raises(AidpAdapterError, match="internal"):
            client.update_knowledge_base("kb-1", {"name": "bad"})


# ===========================================================================
# delete_knowledge_base
# ===========================================================================


class TestDeleteKnowledgeBase:
    def test_success_204_returns_empty_dict(self, client, aidp_client_module):
        """DELETE with 204 returns an empty dict."""
        client._client.request.return_value = _make_response(204)
        result = client.delete_knowledge_base("kb-1")
        assert result == {}
        assert client._client.request.call_args.args[0] == "DELETE"

    def test_http_error_raises(self, client, aidp_client_module):
        """403 from the server raises AidpAdapterError."""
        AidpAdapterError = aidp_client_module.AidpAdapterError
        client._client.request.side_effect = _make_http_status_error(
            403, body_json={"error": {"code": "FORBIDDEN"}}
        )
        with pytest.raises(AidpAdapterError, match="FORBIDDEN"):
            client.delete_knowledge_base("kb-1")


# ===========================================================================
# upload_documents
# ===========================================================================


class TestUploadDocuments:
    def test_success(self, client, aidp_client_module):
        """Sends POST with multipart files and returns response."""
        expected = {"uploaded": 2}
        client._client.request.return_value = _make_response(200, json_data=expected)
        files = [("doc.pdf", b"%PDF-1.4", "application/pdf")]
        result = client.upload_documents("kb-1", files)
        assert result == expected
        assert client._client.request.call_args.args[0] == "POST"
        # Verify multipart_files structure
        call_kwargs = client._client.request.call_args.kwargs
        sent_files = call_kwargs["files"]
        assert sent_files[0][0] == "file"
        assert sent_files[0][1] == ("doc.pdf", b"%PDF-1.4", "application/pdf")

    def test_empty_content_type_defaults_to_octet_stream(self, client, aidp_client_module):
        """Files with empty content_type default to application/octet-stream."""
        client._client.request.return_value = _make_response(200, json_data={"ok": True})
        files = [("data.bin", b"\x00\x01", "")]
        client.upload_documents("kb-1", files)
        call_kwargs = client._client.request.call_args.kwargs
        sent_files = call_kwargs["files"]
        assert sent_files[0][1][2] == "application/octet-stream"

    def test_request_error_raises(self, client, aidp_client_module):
        """RequestError becomes AidpAdapterError(503)."""
        AidpAdapterError = aidp_client_module.AidpAdapterError
        client._client.request.side_effect = httpx.ReadTimeout("timeout")
        with pytest.raises(AidpAdapterError):
            client.upload_documents("kb-1", [("f.txt", b"data", "text/plain")])


# ===========================================================================
# list_documents
# ===========================================================================


class TestListDocuments:
    def test_success(self, client, aidp_client_module):
        """Sends GET with pagination params."""
        expected = {"items": [{"id": "f-1"}], "total": 1}
        client._client.request.return_value = _make_response(200, json_data=expected)
        result = client.list_documents("kb-1", page=2, page_size=5)
        assert result == expected
        call_kwargs = client._client.request.call_args.kwargs
        assert call_kwargs["params"] == {"page": 2, "page_size": 5}
        assert "KnowledgeFiles" in client._client.request.call_args.args[1]

    def test_http_error_raises(self, client, aidp_client_module):
        """HTTP error raises AidpAdapterError."""
        AidpAdapterError = aidp_client_module.AidpAdapterError
        client._client.request.side_effect = _make_http_status_error(502, body_text="bad gateway")
        with pytest.raises(AidpAdapterError):
            client.list_documents("kb-1", page=1, page_size=10)


# ===========================================================================
# retrieve
# ===========================================================================


class TestRetrieve:
    def test_success(self, client, aidp_client_module):
        """Sends POST to FusionSearch with payload."""
        expected = {"results": [{"text": "answer", "score": 0.95}]}
        client._client.request.return_value = _make_response(200, json_data=expected)
        payload = {"query": "hello", "top_k": 5}
        result = client.retrieve(payload)
        assert result == expected
        assert client._client.request.call_args.args[0] == "POST"
        assert "FusionSearch" in client._client.request.call_args.args[1]
        assert client._client.request.call_args.kwargs["json"] == payload

    def test_http_error_raises(self, client, aidp_client_module):
        """HTTP error raises AidpAdapterError."""
        AidpAdapterError = aidp_client_module.AidpAdapterError
        client._client.request.side_effect = _make_http_status_error(422)
        with pytest.raises(AidpAdapterError):
            client.retrieve({"query": ""})


# ===========================================================================
# _request edge cases (tested through public methods)
# ===========================================================================


class TestRequestEdgeCases:
    def test_empty_body_returns_empty_dict(self, client, aidp_client_module):
        """Response with empty content body returns {}."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.content = b""
        resp.raise_for_status = MagicMock()
        client._client.request.return_value = resp
        result = client.get_knowledge_base("kb-1")
        assert result == {}

    def test_error_message_from_nested_error_dict(self, client, aidp_client_module):
        """Extracts message from {'error': {'message': '...'}} body."""
        AidpAdapterError = aidp_client_module.AidpAdapterError
        client._client.request.side_effect = _make_http_status_error(
            400, body_json={"error": {"message": "invalid field"}}
        )
        with pytest.raises(AidpAdapterError, match="invalid field"):
            client.create_knowledge_base({"bad": True})

    def test_error_message_from_error_code_fallback(self, client, aidp_client_module):
        """Falls back to error.code when error.message is missing."""
        AidpAdapterError = aidp_client_module.AidpAdapterError
        client._client.request.side_effect = _make_http_status_error(
            400, body_json={"error": {"code": "ERR_400"}}
        )
        with pytest.raises(AidpAdapterError, match="ERR_400"):
            client.create_knowledge_base({"bad": True})

    def test_error_message_from_top_level_message(self, client, aidp_client_module):
        """Extracts message from {'message': '...'} body."""
        AidpAdapterError = aidp_client_module.AidpAdapterError
        client._client.request.side_effect = _make_http_status_error(
            400, body_json={"message": "top-level error"}
        )
        with pytest.raises(AidpAdapterError, match="top-level error"):
            client.create_knowledge_base({"bad": True})

    def test_error_message_from_string_body(self, client, aidp_client_module):
        """When response body is a string, uses it as the error message."""
        AidpAdapterError = aidp_client_module.AidpAdapterError
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 500
        resp.json.side_effect = ValueError("no json")
        resp.text = "Internal Server Error plain text"
        error = httpx.HTTPStatusError(
            message="500 error", request=MagicMock(), response=resp
        )
        client._client.request.side_effect = error
        with pytest.raises(AidpAdapterError, match="Internal Server Error plain text"):
            client.create_knowledge_base({"bad": True})

    def test_request_error_becomes_503(self, client, aidp_client_module):
        """httpx.RequestError becomes AidpAdapterError with status 503."""
        AidpAdapterError = aidp_client_module.AidpAdapterError
        client._client.request.side_effect = httpx.ConnectError("connection refused")
        with pytest.raises(AidpAdapterError) as exc_info:
            client.list_knowledge_bases(1, 10)
        assert exc_info.value.status_code == 503
        assert "request failed" in str(exc_info.value)

    def test_error_body_not_dict_or_string(self, client, aidp_client_module):
        """When response body is neither dict nor string, _extract_error_message returns None."""
        AidpAdapterError = aidp_client_module.AidpAdapterError
        # JSON returns a list (not dict, not str) → _extract_error_message returns None
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 500
        resp.json.return_value = ["error1", "error2"]
        resp.text = '["error1", "error2"]'
        error = httpx.HTTPStatusError(
            message="500 error", request=MagicMock(), response=resp
        )
        client._client.request.side_effect = error
        with pytest.raises(AidpAdapterError) as exc_info:
            client.create_knowledge_base({"bad": True})
        # When _extract_error_message returns None, falls back to str(exc)
        assert "500 error" in str(exc_info.value)

    def test_headers_include_auth(self, client, aidp_client_module):
        """Authorization Bearer header is set on all requests."""
        client._client.request.return_value = _make_response(200, json_data={"count": 0})
        client.count_knowledge_bases()
        call_kwargs = client._client.request.call_args.kwargs
        headers = call_kwargs["headers"]
        assert headers["Authorization"] == "Bearer test-api-key"
        assert headers["Content-Type"] == "application/json"

    def test_upload_headers_no_content_type(self, client, aidp_client_module):
        """upload_documents sends headers without Content-Type (multipart sets it)."""
        client._client.request.return_value = _make_response(200, json_data={"ok": True})
        client.upload_documents("kb-1", [("f.txt", b"data", "text/plain")])
        call_kwargs = client._client.request.call_args.kwargs
        headers = call_kwargs["headers"]
        assert "Content-Type" not in headers
        assert headers["Authorization"] == "Bearer test-api-key"
