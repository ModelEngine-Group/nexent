import socket
import sys
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

TEST_ROOT = Path(__file__).resolve().parents[2]
if str(TEST_ROOT) not in sys.path:
    sys.path.append(str(TEST_ROOT))

from test.common.test_mocks import bootstrap_test_env

helpers_env = bootstrap_test_env()

helpers_env["mock_const"].DATA_PROCESS_SERVICE = "http://mock-data-process-service"
helpers_env["mock_const"].MODEL_CONFIG_MAPPING = {
    "vlm": "vlm_model_config",
    "vlm3": "video_model_config",
}
mock_const = helpers_env["mock_const"]

from services.image_service import get_image_understanding_model, get_video_understanding_model, get_vlm_model, proxy_image_impl
from services import image_service as image_service_module
from services.image_service import _validate_loopback_url

image_service_module = sys.modules[get_vlm_model.__module__]
if "services" in sys.modules:
    setattr(sys.modules["services"], "image_service", image_service_module)

# Sample test data
test_url = "https://example.com/image.jpg"
success_response = {
    "success": True,
    "data": "base64_encoded_image_data",
    "mime_type": "image/jpeg"
}
error_response = {
    "success": False,
    "error": "Failed to fetch image or image format not supported"
}


@pytest.mark.asyncio
async def test_proxy_image_impl_success():
    """Test successful image proxy implementation"""
    # Create mock response
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value=success_response)

    # Create mock session
    mock_session = AsyncMock()
    mock_get = AsyncMock()
    mock_get.__aenter__.return_value = mock_response
    mock_session.get = MagicMock(return_value=mock_get)

    # Create mock session factory
    mock_client_session = AsyncMock()
    mock_client_session.__aenter__.return_value = mock_session

    # Patch the ClientSession
    with patch.object(image_service_module.aiohttp, 'ClientSession') as mock_session_class:
        mock_session_class.return_value = mock_client_session

        # Test the function
        result = await proxy_image_impl(test_url)

        # Assertions
        assert result == success_response

        # Verify correct URL was called
        mock_session.get.assert_called_once()
        called_url = mock_session.get.call_args[0][0]
        assert "http://mock-data-process-service/tasks/load_image" in called_url
        assert f"url={test_url}" in called_url


@pytest.mark.asyncio
async def test_proxy_image_impl_remote_error():
    """Test image proxy implementation when remote service returns error"""
    # Create mock response
    mock_response = AsyncMock()
    mock_response.status = 404
    mock_response.text = AsyncMock(return_value="Image not found")

    # Create mock session
    mock_session = AsyncMock()
    mock_get = AsyncMock()
    mock_get.__aenter__.return_value = mock_response
    mock_session.get = MagicMock(return_value=mock_get)

    # Create mock session factory
    mock_client_session = AsyncMock()
    mock_client_session.__aenter__.return_value = mock_session

    # Patch the ClientSession
    with patch.object(image_service_module.aiohttp, 'ClientSession') as mock_session_class:
        mock_session_class.return_value = mock_client_session

        # Test the function
        result = await proxy_image_impl(test_url)

        # Assertions
        assert result["success"] is False
        assert result["error"] == "Failed to fetch image or image format not supported"

        # Verify correct URL was called
        mock_session.get.assert_called_once()


@pytest.mark.asyncio
async def test_proxy_image_impl_500_error():
    """Test image proxy implementation when remote service returns 500 error"""
    # Create mock response
    mock_response = AsyncMock()
    mock_response.status = 500
    mock_response.text = AsyncMock(return_value="Internal server error")

    # Create mock session
    mock_session = AsyncMock()
    mock_get = AsyncMock()
    mock_get.__aenter__.return_value = mock_response
    mock_session.get = MagicMock(return_value=mock_get)

    # Create mock session factory
    mock_client_session = AsyncMock()
    mock_client_session.__aenter__.return_value = mock_session

    # Patch the ClientSession
    with patch.object(image_service_module.aiohttp, 'ClientSession') as mock_session_class:
        mock_session_class.return_value = mock_client_session

        # Test the function
        result = await proxy_image_impl(test_url)

        # Assertions
        assert result["success"] is False
        assert result["error"] == "Failed to fetch image or image format not supported"

        # Verify correct URL was called
        mock_session.get.assert_called_once()


@pytest.mark.asyncio
async def test_proxy_image_impl_connection_exception():
    """Test image proxy implementation when connection exception occurs"""
    # Create mock session that raises exception
    mock_session = AsyncMock()
    mock_get = AsyncMock()
    mock_get.__aenter__.side_effect = Exception("Connection error")
    mock_session.get = MagicMock(return_value=mock_get)

    # Create mock session factory
    mock_client_session = AsyncMock()
    mock_client_session.__aenter__.return_value = mock_session

    # Patch the ClientSession
    with patch.object(image_service_module.aiohttp, 'ClientSession') as mock_session_class:
        mock_session_class.return_value = mock_client_session

        # Test the function - should raise the exception
        with pytest.raises(Exception) as exc_info:
            await proxy_image_impl(test_url)

        # Verify the exception message
        assert "Connection error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_proxy_image_impl_with_special_chars():
    """Test image proxy implementation with URL containing special characters"""
    special_url = "https://example.com/image with spaces.jpg"

    # Create mock response
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value=success_response)

    # Create mock session
    mock_session = AsyncMock()
    mock_get = AsyncMock()
    mock_get.__aenter__.return_value = mock_response
    mock_session.get = MagicMock(return_value=mock_get)

    # Create mock session factory
    mock_client_session = AsyncMock()
    mock_client_session.__aenter__.return_value = mock_session

    # Patch the ClientSession
    with patch.object(image_service_module.aiohttp, 'ClientSession') as mock_session_class:
        mock_session_class.return_value = mock_client_session

        # Test the function
        result = await proxy_image_impl(special_url)

        # Assertions
        assert result == success_response

        # Verify URL was correctly passed
        mock_session.get.assert_called_once()
        called_url = mock_session.get.call_args[0][0]
        assert "http://mock-data-process-service/tasks/load_image" in called_url
        assert f"url={special_url}" in called_url


@pytest.mark.asyncio
async def test_proxy_image_impl_json_parse_error():
    """Test image proxy implementation when JSON parsing fails"""
    # Create mock response
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(side_effect=Exception("Invalid JSON"))

    # Create mock session
    mock_session = AsyncMock()
    mock_get = AsyncMock()
    mock_get.__aenter__.return_value = mock_response
    mock_session.get = MagicMock(return_value=mock_get)

    # Create mock session factory
    mock_client_session = AsyncMock()
    mock_client_session.__aenter__.return_value = mock_session

    # Patch the ClientSession
    with patch.object(image_service_module.aiohttp, 'ClientSession') as mock_session_class:
        mock_session_class.return_value = mock_client_session

        # Test the function - should raise the exception
        with pytest.raises(Exception) as exc_info:
            await proxy_image_impl(test_url)

        # Verify the exception message
        assert "Invalid JSON" in str(exc_info.value)


@pytest.mark.asyncio
async def test_proxy_image_impl_different_status_codes():
    """Test image proxy implementation with different HTTP status codes"""
    test_cases = [
        (400, "Bad Request"),
        (401, "Unauthorized"),
        (403, "Forbidden"),
        (429, "Too Many Requests"),
        (502, "Bad Gateway"),
        (503, "Service Unavailable")
    ]

    for status_code, status_text in test_cases:
        # Create mock response
        mock_response = AsyncMock()
        mock_response.status = status_code
        mock_response.text = AsyncMock(return_value=status_text)

        # Create mock session
        mock_session = AsyncMock()
        mock_get = AsyncMock()
        mock_get.__aenter__.return_value = mock_response
        mock_session.get = MagicMock(return_value=mock_get)

        # Create mock session factory
        mock_client_session = AsyncMock()
        mock_client_session.__aenter__.return_value = mock_session

        # Patch the ClientSession
        with patch.object(image_service_module.aiohttp, 'ClientSession') as mock_session_class:
            mock_session_class.return_value = mock_client_session

            # Test the function
            result = await proxy_image_impl(test_url)

            # Assertions
            assert result["success"] is False
            assert result["error"] == "Failed to fetch image or image format not supported"

            # Verify correct URL was called
            mock_session.get.assert_called_once()


@pytest.mark.asyncio
async def test_proxy_image_impl_url_encoding():
    """Test image proxy implementation with URL encoding"""
    encoded_url = "https%3A%2F%2Fexample.com%2Fimage.jpg"
    decoded_url = "https://example.com/image.jpg"

    # Create mock response
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value=success_response)

    # Create mock session
    mock_session = AsyncMock()
    mock_get = AsyncMock()
    mock_get.__aenter__.return_value = mock_response
    mock_session.get = MagicMock(return_value=mock_get)

    # Create mock session factory
    mock_client_session = AsyncMock()
    mock_client_session.__aenter__.return_value = mock_session

    # Patch the ClientSession
    with patch.object(image_service_module.aiohttp, 'ClientSession') as mock_session_class:
        mock_session_class.return_value = mock_client_session

        # Test the function with encoded URL
        result = await proxy_image_impl(encoded_url)

        # Assertions
        assert result == success_response

        # Verify URL was correctly passed (should be URL encoded in the request)
        mock_session.get.assert_called_once()
        called_url = mock_session.get.call_args[0][0]
        assert "http://mock-data-process-service/tasks/load_image" in called_url
        assert f"url={encoded_url}" in called_url


@patch.object(image_service_module, 'OpenAIVLModel')
@patch.object(image_service_module, 'MessageObserver')
@patch.object(image_service_module, 'get_model_name_from_config')
@patch.object(image_service_module, 'tenant_config_manager')
def test_get_vlm_model_success(mock_tenant_config_manager, mock_get_model_name, mock_message_observer, mock_openai_vl_model):
    """Ensure get_vlm_model builds OpenAIVLModel with tenant config."""
    mock_config = {
        "base_url": "https://mock-api",
        "api_key": "secret",
        "model_name": "gpt-4v"
    }
    mock_tenant_config_manager.get_model_config.return_value = mock_config
    mock_get_model_name.return_value = "gpt-4v"
    mock_model_instance = MagicMock()
    mock_openai_vl_model.return_value = mock_model_instance

    result = get_vlm_model("tenant-1")

    mock_tenant_config_manager.get_model_config.assert_called_once_with(
        key="vlm_model_config",
        tenant_id="tenant-1"
    )
    mock_message_observer.assert_called_once_with()
    mock_openai_vl_model.assert_called_once_with(
        observer=mock_message_observer.return_value,
        model_id="gpt-4v",
        api_base="https://mock-api",
        api_key="secret",
        temperature=0.7,
        top_p=0.7,
        frequency_penalty=0.5,
        max_tokens=512,
        ssl_verify=True,
        model_factory=None,
        display_name=None
    )
    assert result == mock_model_instance


@patch.object(image_service_module, 'OpenAIVLModel')
@patch.object(image_service_module, 'MessageObserver')
@patch.object(image_service_module, 'get_model_name_from_config')
@patch.object(image_service_module, 'tenant_config_manager')
def test_get_vlm_model_with_none_config(mock_tenant_config_manager, mock_get_model_name, mock_message_observer, mock_openai_vl_model):
    """Return None when tenant config is None."""
    mock_tenant_config_manager.get_model_config.return_value = None
    mock_model_instance = MagicMock()
    mock_openai_vl_model.return_value = mock_model_instance

    result = get_vlm_model("tenant-3")

    # get_model_name_from_config should not be called because config is None
    mock_get_model_name.assert_not_called()
    # OpenAIVLModel should not be called when config is None
    mock_openai_vl_model.assert_not_called()
    assert result is None


@patch.object(image_service_module, 'get_vlm_model')
def test_get_image_understanding_model_uses_first_multimodal_slot(mock_get_vlm_model):
    """Ensure the image understanding alias keeps using the first multimodal slot."""
    mock_get_vlm_model.return_value = "image-understanding-model"

    result = get_image_understanding_model("tenant-1")

    mock_get_vlm_model.assert_called_once_with(tenant_id="tenant-1")
    assert result == "image-understanding-model"


@patch.object(image_service_module, 'OpenAIVLModel')
@patch.object(image_service_module, 'MessageObserver')
@patch.object(image_service_module, 'get_model_name_from_config')
@patch.object(image_service_module, 'tenant_config_manager')
def test_get_video_understanding_model_success(mock_tenant_config_manager, mock_get_model_name, mock_message_observer, mock_openai_vl_model):
    """Ensure video understanding tools use the third multimodal model slot."""
    mock_config = {
        "base_url": "https://mock-video-api",
        "api_key": "secret",
        "model_name": "video-model"
    }
    mock_tenant_config_manager.get_model_config.return_value = mock_config
    mock_get_model_name.return_value = "video-model"
    mock_model_instance = MagicMock()
    mock_openai_vl_model.return_value = mock_model_instance

    result = get_video_understanding_model("tenant-1")

    mock_tenant_config_manager.get_model_config.assert_called_once_with(
        key="video_model_config",
        tenant_id="tenant-1"
    )
    mock_openai_vl_model.assert_called_once()
    assert result == mock_model_instance


# ---------------------------------------------------------------------------
# SSRF protection tests for _validate_loopback_url
# ---------------------------------------------------------------------------
#
# The proxy_image_impl service exposes an image proxy endpoint that accepts a
# user-controlled URL. The implementation has two paths:
#
#   1. Direct fetch path (only for genuine loopback URLs)
#   2. data-process-service proxy path (for everything else, including all
#      external/knowledge-base images such as AIDP)
#
# CodeQL flags the direct fetch path because it issues a GET to a
# user-controlled URL. The fix validates the loopback URL end-to-end (DNS
# must resolve to 127.0.0.0/8, scheme restricted, URL rewritten to a literal
# IP) so that ONLY genuine loopback URLs take the direct path. Everything
# else (including AIDP knowledge-base images) keeps using the
# data-process-service proxy, which is the safe path CodeQL does not flag.


def _fake_addrinfo(addresses):
    """Build a getaddrinfo-like sequence of tuples for the given addresses."""
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, 0))
        for addr in addresses
    ]


@pytest.mark.parametrize(
    "raw_url,addresses,expected",
    [
        # Plain IPv4 loopback is rewritten to the literal loopback IP.
        (
            "http://127.0.0.1:8080/img.png",
            ["127.0.0.1"],
            "http://127.0.0.1:8080/img.png",
        ),
        # localhost should resolve and be rewritten to the loopback IP.
        (
            "http://localhost:9000/x",
            ["127.0.0.1"],
            "http://127.0.0.1:9000/x",
        ),
        # A loopback alias in 127.0.0.0/8 is accepted. The rewritten URL
        # uses the resolved literal IP rather than the textual 127.0.0.1 so
        # the address aiohttp actually connects to is exactly the address
        # we validated (no implicit re-mapping).
        (
            "http://127.0.0.53:80/x",
            ["127.0.0.53"],
            "http://127.0.0.53:80/x",
        ),
        # Default port must be stripped from the rewritten URL.
        (
            "https://127.0.0.1/path?q=1",
            ["127.0.0.1"],
            "https://127.0.0.1/path?q=1",
        ),
    ],
)
def test_validate_loopback_url_accepts_loopback(raw_url, addresses, expected):
    with patch.object(
        image_service_module.socket,
        "getaddrinfo",
        return_value=_fake_addrinfo(addresses),
    ):
        assert _validate_loopback_url(raw_url) == expected


@pytest.mark.parametrize(
    "raw_url,addresses,reason",
    [
        # External host must be rejected (these are exactly the URLs that
        # need to keep working via the data-process-service path).
        (
            "http://example.com/img.png",
            ["93.184.216.34"],
            "public-ip",
        ),
        # Private RFC1918 IPv4 must be rejected.
        (
            "http://10.0.0.1/img.png",
            ["10.0.0.1"],
            "private-ipv4",
        ),
        (
            "http://192.168.1.10/img.png",
            ["192.168.1.10"],
            "private-ipv4",
        ),
        (
            "http://169.254.169.254/latest/meta-data/",
            ["169.254.169.254"],
            "link-local",
        ),
        # IPv6 loopback should be rejected (we only allow IPv4 loopback).
        (
            "http://[::1]/img.png",
            ["::1"],
            "ipv6-loopback",
        ),
        # Dual-stack hostname resolving to loopback + private address must
        # be rejected to avoid DNS rebinding pivots.
        (
            "http://attacker.example.com/img.png",
            ["127.0.0.1", "10.0.0.5"],
            "mixed-resolve",
        ),
        # Plain IPv6 address without IPv4 loopback must be rejected.
        (
            "http://[fe80::1]/img.png",
            ["fe80::1"],
            "ipv6-link-local",
        ),
    ],
)
def test_validate_loopback_url_rejects_unsafe(raw_url, addresses, reason):
    with patch.object(
        image_service_module.socket,
        "getaddrinfo",
        return_value=_fake_addrinfo(addresses),
    ):
        assert _validate_loopback_url(raw_url) is None, reason


def test_validate_loopback_url_rejects_unsupported_scheme():
    assert _validate_loopback_url("file:///etc/passwd") is None
    assert _validate_loopback_url("ftp://127.0.0.1/img.png") is None
    assert _validate_loopback_url("gopher://127.0.0.1/") is None


def test_validate_loopback_url_handles_dns_failure():
    with patch.object(
        image_service_module.socket,
        "getaddrinfo",
        side_effect=socket.gaierror("no such host"),
    ):
        assert _validate_loopback_url("http://no-such-host.invalid/") is None


def test_validate_loopback_url_rejects_invalid_url():
    assert _validate_loopback_url("") is None
    assert _validate_loopback_url("not a url") is None


@pytest.mark.asyncio
async def test_proxy_image_impl_loopback_uses_safe_url_and_no_redirects():
    """When the URL resolves to loopback, the rewritten IP literal must be
    used, redirects must be disabled and trust_env must be off."""
    rewritten_url = "http://127.0.0.1:8080/img.png"

    def fake_validate(_decoded_url):
        assert _decoded_url == "http://127.0.0.1:8080/img.png"
        return rewritten_url

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.headers = {"Content-Type": "image/png"}
    mock_response.read = AsyncMock(return_value=b"png-bytes")

    mock_get = AsyncMock()
    mock_get.__aenter__.return_value = mock_response
    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_get)

    mock_session_instance = AsyncMock()
    mock_session_instance.__aenter__.return_value = mock_session
    mock_session_instance.__aexit__.return_value = False

    with patch.object(
        image_service_module, "_validate_loopback_url", side_effect=fake_validate
    ), patch.object(
        image_service_module.aiohttp, "ClientSession", return_value=mock_session_instance
    ) as mock_session_class:
        result = await proxy_image_impl("http://127.0.0.1:8080/img.png")

    assert result["success"] is True

    # aiohttp.ClientSession must be created with trust_env=False to avoid
    # honouring HTTP(S)_PROXY environment variables.
    mock_session_class.assert_called_once()
    kwargs = mock_session_class.call_args.kwargs
    assert kwargs.get("trust_env") is False

    # The session.get call must use the rewritten (safe) URL, must not
    # follow redirects, and must not receive the original user-controlled
    # URL as the request target.
    mock_session.get.assert_called_once()
    call_args = mock_session.get.call_args
    assert call_args.args[0] == rewritten_url
    assert call_args.kwargs.get("allow_redirects") is False


@pytest.mark.asyncio
async def test_proxy_image_impl_non_loopback_falls_back_to_data_process_service():
    """When the URL is not loopback (e.g. an AIDP knowledge base image,
    a public CDN, an intranet host, etc.) the service MUST fall back to
    the data-process-service proxy and MUST NOT take the direct fetch
    path."""
    remote_response = {
        "success": True,
        "data": "remote-image",
        "mime_type": "image/jpeg",
    }

    direct_called = {"value": False}

    async def fake_fetch(_safe_url):
        direct_called["value"] = True
        return {"success": True, "base64": "AAAA", "content_type": "image/jpeg"}

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value=remote_response)

    mock_get = AsyncMock()
    mock_get.__aenter__.return_value = mock_response
    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_get)

    mock_session_instance = AsyncMock()
    mock_session_instance.__aenter__.return_value = mock_session
    mock_session_instance.__aexit__.return_value = False

    # _validate_loopback_url rejects the URL (returns None) because the
    # hostname does not resolve to a loopback address.
    with patch.object(
        image_service_module, "_validate_loopback_url", return_value=None
    ), patch.object(
        image_service_module, "_fetch_image_directly", side_effect=fake_fetch
    ), patch.object(
        image_service_module.aiohttp, "ClientSession", return_value=mock_session_instance
    ):
        result = await proxy_image_impl("http://example.com/image.jpg")

    # The direct fetch path must NOT be taken.
    assert direct_called["value"] is False

    # The data-process-service proxy must be called with the user URL
    # embedded in the query string.
    mock_session.get.assert_called_once()
    called_url = mock_session.get.call_args[0][0]
    assert "http://mock-data-process-service/tasks/load_image" in called_url
    assert "url=http://example.com/image.jpg" in called_url

    assert result == remote_response


@pytest.mark.parametrize(
    "external_url",
    [
        # AIDP knowledge base image on a public CDN-style host.
        "https://aidp-files.example.com/dataset/abc/file.png",
        # AIDP knowledge base image served from an internal corporate host.
        "https://aidp.intranet.company.local/files/123/img.jpg",
        # A plain public URL.
        "https://cdn.example.org/path/to/image.webp",
    ],
)
@pytest.mark.asyncio
async def test_proxy_image_impl_aidp_and_external_urls_use_proxy_path(external_url):
    """External URLs (AIDP knowledge base, public CDN, etc.) must be
    forwarded to the data-process-service proxy. They must never reach
    the direct-fetch path that requires a loopback URL."""
    remote_response = {
        "success": True,
        "data": "remote",
        "mime_type": "image/jpeg",
    }

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value=remote_response)

    mock_get = AsyncMock()
    mock_get.__aenter__.return_value = mock_response
    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_get)

    mock_session_instance = AsyncMock()
    mock_session_instance.__aenter__.return_value = mock_session
    mock_session_instance.__aexit__.return_value = False

    # Real validation: a non-loopback URL must produce None so the proxy
    # path is taken. We don't mock this function here; we let the real
    # implementation run to ensure the whole flow works.
    with patch.object(
        image_service_module.aiohttp, "ClientSession", return_value=mock_session_instance
    ):
        result = await proxy_image_impl(external_url)

    # The session.get call should hit the data-process-service, not the
    # external URL directly.
    mock_session.get.assert_called_once()
    called_url = mock_session.get.call_args[0][0]
    assert called_url.startswith("http://mock-data-process-service/tasks/load_image")
    assert f"url={external_url}" in called_url

    assert result == remote_response
