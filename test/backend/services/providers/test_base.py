"""Unit tests for model provider base module.

Tests cover error classification utilities and abstract base class.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from pytest_mock import MockFixture

from backend.services.providers.base import (
    _create_error_response,
    _classify_provider_error,
    AbstractModelProvider,
)


class TestCreateErrorResponse:
    """Tests for _create_error_response function."""

    def test_create_error_response_basic(self):
        """Test basic error response creation."""
        result = _create_error_response("test_error", "Test error message")
        assert result == [{"_error": "test_error",
                           "_message": "Test error message"}]

    def test_create_error_response_with_http_code(self):
        """Test error response creation with HTTP status code."""
        result = _create_error_response(
            "authentication_failed",
            "Invalid API key",
            401
        )
        assert result == [{
            "_error": "authentication_failed",
            "_message": "Invalid API key",
            "_http_code": 401
        }]


class TestClassifyProviderError:
    """Tests for _classify_provider_error function."""

    def test_classify_401_unauthorized(self):
        """Test classification of 401 Unauthorized error."""
        result = _classify_provider_error(
            provider_name="TestProvider",
            status_code=401,
            error_message="Invalid credentials"
        )
        assert result[0]["_error"] == "authentication_failed"
        assert result[0]["_http_code"] == 401

    def test_classify_403_forbidden(self):
        """Test classification of 403 Forbidden error."""
        result = _classify_provider_error(
            provider_name="TestProvider",
            status_code=403,
            error_message="Insufficient permissions"
        )
        assert result[0]["_error"] == "access_forbidden"
        assert result[0]["_http_code"] == 403

    def test_classify_404_not_found(self):
        """Test classification of 404 Not Found error."""
        result = _classify_provider_error(
            provider_name="TestProvider",
            status_code=404,
            error_message="Endpoint not found"
        )
        assert result[0]["_error"] == "endpoint_not_found"
        assert result[0]["_http_code"] == 404

    def test_classify_400_bad_request(self):
        """Test classification of 400 Bad Request error."""
        result = _classify_provider_error(
            provider_name="TestProvider",
            status_code=400,
            error_message="Invalid request"
        )
        assert result[0]["_error"] == "api_error"
        assert result[0]["_http_code"] == 400

    def test_classify_500_server_error(self):
        """Test classification of 500 Server Error."""
        result = _classify_provider_error(
            provider_name="TestProvider",
            status_code=500,
            error_message="Internal server error"
        )
        assert result[0]["_error"] == "server_error"
        assert result[0]["_http_code"] == 500

    def test_classify_502_bad_gateway(self):
        """Test classification of 502 Bad Gateway."""
        result = _classify_provider_error(
            provider_name="TestProvider",
            status_code=502,
            error_message="Bad gateway"
        )
        assert result[0]["_error"] == "server_error"
        assert result[0]["_http_code"] == 502

    def test_classify_ssl_error(self):
        """Test classification of SSL certificate error via generic exception path."""
        # Test with a generic exception that has SSL in the message
        mock_exception = Exception("SSL certificate verify failed")
        result = _classify_provider_error(
            provider_name="TestProvider",
            exception=mock_exception
        )
        # Falls through to generic exception handling
        assert result[0]["_error"] == "connection_failed"

    def test_classify_connection_failed(self):
        """Test classification of connection failed error."""
        # Test with a generic exception that simulates connection failure
        mock_exception = Exception("Connection refused")
        result = _classify_provider_error(
            provider_name="TestProvider",
            exception=mock_exception
        )
        assert result[0]["_error"] == "connection_failed"

    def test_classify_timeout_error(self):
        """Test classification of timeout error."""
        import aiohttp
        mock_exception = aiohttp.ServerTimeoutError()
        result = _classify_provider_error(
            provider_name="TestProvider",
            exception=mock_exception
        )
        assert result[0]["_error"] == "timeout"

    def test_classify_server_disconnected_error(self):
        """Test classification of server disconnected error."""
        import aiohttp
        mock_exception = aiohttp.ServerDisconnectedError(
            message="Server disconnected")
        result = _classify_provider_error(
            provider_name="TestProvider",
            exception=mock_exception
        )
        assert result[0]["_error"] == "connection_failed"

    def test_classify_content_type_error(self):
        """Test classification of content type error."""
        import aiohttp
        mock_exception = aiohttp.ContentTypeError(
            request_info=MagicMock(),
            history=(),
            message="Unexpected content type"
        )
        result = _classify_provider_error(
            provider_name="TestProvider",
            exception=mock_exception
        )
        assert result[0]["_error"] == "invalid_response"

    def test_classify_generic_exception(self):
        """Test classification of generic exception."""
        mock_exception = Exception("Some unknown error")
        result = _classify_provider_error(
            provider_name="TestProvider",
            exception=mock_exception
        )
        assert result[0]["_error"] == "connection_failed"


class TestAbstractModelProvider:
    """Tests for AbstractModelProvider abstract class."""

    @pytest.mark.asyncio
    async def test_abstract_method_raises_not_implemented(self):
        """Test that calling abstract get_models raises NotImplementedError."""
        # Create a subclass that doesn't override get_models
        # This should fail at instantiation time, not at call time
        with pytest.raises(TypeError, match="abstract method"):
            class IncompleteProvider(AbstractModelProvider):
                pass

            # If class definition succeeded (which it shouldn't), try to instantiate
            provider = IncompleteProvider()
            await provider.get_models({})

    def test_is_abstract_class(self):
        """Test that AbstractModelProvider cannot be instantiated directly."""
        with pytest.raises(TypeError):
            AbstractModelProvider()

    def test_concrete_implementation_can_be_instantiated(self):
        """Test that concrete implementations can be instantiated."""

        class ConcreteProvider(AbstractModelProvider):
            async def get_models(self, provider_config):
                return [{"id": "test"}]

        provider = ConcreteProvider()
        assert isinstance(provider, AbstractModelProvider)
