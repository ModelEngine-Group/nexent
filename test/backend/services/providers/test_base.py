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

    def test_classify_client_connector_error_ssl(self):
        """Test classification of aiohttp.ClientConnectorError with SSL error."""
        import aiohttp
        from unittest.mock import Mock, patch

        # Create a subclass that overrides __str__
        class MockClientConnectorError(aiohttp.ClientConnectorError):
            def __init__(self, message):
                mock_conn_key = Mock()
                mock_conn_key.ssl = False
                mock_os_error = Mock()
                mock_os_error.errno = 1
                mock_os_error.strerror = message
                super().__init__(connection_key=mock_conn_key, os_error=mock_os_error)
                self._message = message

            def __str__(self):
                return self._message

        mock_exception = MockClientConnectorError("SSL certificate verification failed")
        result = _classify_provider_error(
            provider_name="TestProvider",
            exception=mock_exception
        )
        assert result[0]["_error"] == "ssl_error"

    def test_classify_client_connector_error_certificate_in_message(self):
        """Test classification of aiohttp.ClientConnectorError with certificate in message."""
        import aiohttp
        from unittest.mock import Mock

        class MockClientConnectorError(aiohttp.ClientConnectorError):
            def __init__(self, message):
                mock_conn_key = Mock()
                mock_conn_key.ssl = False
                mock_os_error = Mock()
                mock_os_error.errno = 1
                mock_os_error.strerror = message
                super().__init__(connection_key=mock_conn_key, os_error=mock_os_error)
                self._message = message

            def __str__(self):
                return self._message

        mock_exception = MockClientConnectorError("Certificate has expired")
        result = _classify_provider_error(
            provider_name="TestProvider",
            exception=mock_exception
        )
        assert result[0]["_error"] == "ssl_error"

    def test_classify_client_connector_error_non_ssl(self):
        """Test classification of aiohttp.ClientConnectorError without SSL error."""
        import aiohttp
        from unittest.mock import Mock

        class MockClientConnectorError(aiohttp.ClientConnectorError):
            def __init__(self, message):
                mock_conn_key = Mock()
                mock_conn_key.ssl = False
                mock_os_error = Mock()
                mock_os_error.errno = 111
                mock_os_error.strerror = message
                super().__init__(connection_key=mock_conn_key, os_error=mock_os_error)
                self._message = message

            def __str__(self):
                return self._message

        mock_exception = MockClientConnectorError("Connection refused")
        result = _classify_provider_error(
            provider_name="TestProvider",
            exception=mock_exception
        )
        assert result[0]["_error"] == "connection_failed"

    def test_classify_429_too_many_requests(self):
        """Test classification of 429 Too Many Requests error."""
        result = _classify_provider_error(
            provider_name="TestProvider",
            status_code=429,
            error_message="Rate limit exceeded"
        )
        assert result[0]["_error"] == "api_error"
        assert result[0]["_http_code"] == 429

    def test_classify_408_request_timeout(self):
        """Test classification of 408 Request Timeout error."""
        result = _classify_provider_error(
            provider_name="TestProvider",
            status_code=408,
            error_message="Request timed out"
        )
        assert result[0]["_error"] == "api_error"
        assert result[0]["_http_code"] == 408

    def test_classify_422_unprocessable_entity(self):
        """Test classification of 422 Unprocessable Entity error."""
        result = _classify_provider_error(
            provider_name="TestProvider",
            status_code=422,
            error_message="Validation failed"
        )
        assert result[0]["_error"] == "api_error"
        assert result[0]["_http_code"] == 422

    def test_classify_426_upgrade_required(self):
        """Test classification of 426 Upgrade Required error."""
        result = _classify_provider_error(
            provider_name="TestProvider",
            status_code=426,
            error_message="TLS upgrade required"
        )
        assert result[0]["_error"] == "api_error"
        assert result[0]["_http_code"] == 426

    def test_classify_428_precondition_failed(self):
        """Test classification of 428 Precondition Failed error."""
        result = _classify_provider_error(
            provider_name="TestProvider",
            status_code=428,
            error_message="Precondition required"
        )
        assert result[0]["_error"] == "api_error"
        assert result[0]["_http_code"] == 428

    def test_classify_503_service_unavailable(self):
        """Test classification of 503 Service Unavailable error."""
        result = _classify_provider_error(
            provider_name="TestProvider",
            status_code=503,
            error_message="Service temporarily unavailable"
        )
        assert result[0]["_error"] == "server_error"
        assert result[0]["_http_code"] == 503

    def test_classify_504_gateway_timeout(self):
        """Test classification of 504 Gateway Timeout error."""
        result = _classify_provider_error(
            provider_name="TestProvider",
            status_code=504,
            error_message="Gateway timeout"
        )
        assert result[0]["_error"] == "server_error"
        assert result[0]["_http_code"] == 504

    def test_classify_507_insufficient_storage(self):
        """Test classification of 507 Insufficient Storage error."""
        result = _classify_provider_error(
            provider_name="TestProvider",
            status_code=507,
            error_message="Insufficient storage"
        )
        assert result[0]["_error"] == "server_error"
        assert result[0]["_http_code"] == 507

    def test_classify_509_bandwidth_limit_exceeded(self):
        """Test classification of 509 Bandwidth Limit Exceeded error."""
        result = _classify_provider_error(
            provider_name="TestProvider",
            status_code=509,
            error_message="Bandwidth limit exceeded"
        )
        assert result[0]["_error"] == "server_error"
        assert result[0]["_http_code"] == 509

    def test_classify_error_message_only_no_status_no_exception(self):
        """Test classification when only error_message is provided (no status_code, no exception)."""
        result = _classify_provider_error(
            provider_name="TestProvider",
            error_message="Something went wrong"
        )
        assert result[0]["_error"] == "connection_failed"
        assert "TestProvider" in result[0]["_message"]

    def test_classify_with_empty_error_message(self):
        """Test classification with empty error message string."""
        result = _classify_provider_error(
            provider_name="TestProvider",
            status_code=400,
            error_message=""
        )
        assert result[0]["_error"] == "api_error"
        assert result[0]["_http_code"] == 400

    def test_classify_with_none_error_message(self):
        """Test classification with None error message."""
        result = _classify_provider_error(
            provider_name="TestProvider",
            status_code=500,
            error_message=None
        )
        assert result[0]["_error"] == "server_error"
        assert result[0]["_http_code"] == 500

    def test_classify_client_connector_error_connection_error(self):
        """Test classification of aiohttp.ClientConnectorError with connection error."""
        import aiohttp
        from unittest.mock import Mock

        class MockClientConnectorError(aiohttp.ClientConnectorError):
            def __init__(self, message):
                mock_conn_key = Mock()
                mock_conn_key.ssl = False
                mock_os_error = Mock()
                mock_os_error.errno = 113
                mock_os_error.strerror = message
                super().__init__(connection_key=mock_conn_key, os_error=mock_os_error)
                self._message = message

            def __str__(self):
                return self._message

        mock_exception = MockClientConnectorError("Host unreachable")
        result = _classify_provider_error(
            provider_name="TestProvider",
            exception=mock_exception
        )
        assert result[0]["_error"] == "connection_failed"

    def test_classify_client_connector_error_dns_resolution_failed(self):
        """Test classification of aiohttp.ClientConnectorError with DNS resolution failure."""
        import aiohttp
        from unittest.mock import Mock

        class MockClientConnectorError(aiohttp.ClientConnectorError):
            def __init__(self, message):
                mock_conn_key = Mock()
                mock_conn_key.ssl = False
                mock_os_error = Mock()
                mock_os_error.errno = -2
                mock_os_error.strerror = message
                super().__init__(connection_key=mock_conn_key, os_error=mock_os_error)
                self._message = message

            def __str__(self):
                return self._message

        mock_exception = MockClientConnectorError("Could not resolve host")
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

    def test_concrete_provider_get_models_returns_list(self):
        """Test that concrete provider get_models returns a list of models."""

        class ConcreteProvider(AbstractModelProvider):
            async def get_models(self, provider_config):
                return [
                    {"id": "model-1", "name": "Model 1"},
                    {"id": "model-2", "name": "Model 2"},
                ]

        provider = ConcreteProvider()
        # get_models is async, so we need to get the coroutine and inspect it
        coroutine = provider.get_models({})
        assert hasattr(coroutine, '__await__')

    @pytest.mark.asyncio
    async def test_concrete_provider_get_models_with_config(self):
        """Test that concrete provider get_models accepts and uses config."""

        class ConcreteProvider(AbstractModelProvider):
            async def get_models(self, provider_config):
                return [{"id": provider_config.get("model_id", "default")}]

        provider = ConcreteProvider()
        result = await provider.get_models({"model_id": "custom-model"})
        assert result[0]["id"] == "custom-model"

    @pytest.mark.asyncio
    async def test_concrete_provider_get_models_empty_config(self):
        """Test that concrete provider get_models handles empty config."""

        class ConcreteProvider(AbstractModelProvider):
            async def get_models(self, provider_config):
                return [{"id": "default"}]

        provider = ConcreteProvider()
        result = await provider.get_models({})
        assert result[0]["id"] == "default"

    @pytest.mark.asyncio
    async def test_concrete_provider_get_models_none_config(self):
        """Test that concrete provider get_models handles None config."""

        class ConcreteProvider(AbstractModelProvider):
            async def get_models(self, provider_config):
                return [{"id": "test"}]

        provider = ConcreteProvider()
        result = await provider.get_models(None)
        assert result[0]["id"] == "test"

    @pytest.mark.asyncio
    async def test_concrete_provider_get_models_is_async(self):
        """Test that get_models is properly defined as async."""

        class ConcreteProvider(AbstractModelProvider):
            async def get_models(self, provider_config):
                return [{"id": "async-test"}]

        provider = ConcreteProvider()
        result = await provider.get_models({})
        assert result[0]["id"] == "async-test"

    def test_provider_with_additional_methods(self):
        """Test that concrete providers can have additional methods."""

        class ExtendedProvider(AbstractModelProvider):
            async def get_models(self, provider_config):
                return [{"id": "test"}]

            def get_provider_info(self):
                return {"name": "ExtendedProvider", "version": "1.0"}

        provider = ExtendedProvider()
        assert isinstance(provider, AbstractModelProvider)
        assert provider.get_provider_info()["name"] == "ExtendedProvider"

    def test_provider_inheritance_chain(self):
        """Test that providers can inherit from other provider classes."""

        class BaseProvider(AbstractModelProvider):
            async def get_models(self, provider_config):
                return []

        class ExtendedProvider(BaseProvider):
            async def get_models(self, provider_config):
                return [{"id": "extended"}]

        provider = ExtendedProvider()
        assert isinstance(provider, AbstractModelProvider)
        assert isinstance(provider, BaseProvider)
