"""
Unit tests for A2A HTTP client utilities.

Tests the A2AHttpClient class and helper functions in backend/utils/a2a_http_client.py.
"""
import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager


class TestBuildA2AHeaders:
    """Test class for build_a2a_headers function."""

    def test_default_headers(self):
        """Test headers without API key."""
        from backend.utils.a2a_http_client import build_a2a_headers

        headers = build_a2a_headers()
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"
        assert "Authorization" not in headers

    def test_headers_with_api_key(self):
        """Test headers with API key."""
        from backend.utils.a2a_http_client import build_a2a_headers

        headers = build_a2a_headers(api_key="test-api-key-123")
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"
        assert headers["Authorization"] == "Bearer test-api-key-123"

    def test_headers_with_none_api_key(self):
        """Test headers with None API key."""
        from backend.utils.a2a_http_client import build_a2a_headers

        headers = build_a2a_headers(api_key=None)
        assert headers["Content-Type"] == "application/json"
        assert "Authorization" not in headers

    def test_headers_with_empty_api_key(self):
        """Test headers with empty API key."""
        from backend.utils.a2a_http_client import build_a2a_headers

        headers = build_a2a_headers(api_key="")
        assert "Authorization" not in headers


class TestA2AHttpClientInit:
    """Test class for A2AHttpClient initialization."""

    def test_default_initialization(self):
        """Test default initialization values."""
        from backend.utils.a2a_http_client import A2AHttpClient, DEFAULT_TIMEOUT, DEFAULT_MAX_RETRIES

        client = A2AHttpClient()
        assert client.timeout.total == DEFAULT_TIMEOUT
        assert client.max_retries == DEFAULT_MAX_RETRIES
        assert client._session is None

    def test_custom_timeout(self):
        """Test custom timeout value."""
        from backend.utils.a2a_http_client import A2AHttpClient

        client = A2AHttpClient(timeout=60.0)
        assert client.timeout.total == 60.0

    def test_custom_max_retries(self):
        """Test custom max retries value."""
        from backend.utils.a2a_http_client import A2AHttpClient

        client = A2AHttpClient(max_retries=5)
        assert client.max_retries == 5

    def test_aggressive_timeout_for_agent_card(self):
        """Test agent card timeout constant."""
        from backend.utils.a2a_http_client import A2AHttpClient, AGENT_CARD_TIMEOUT

        client = A2AHttpClient(timeout=AGENT_CARD_TIMEOUT)
        assert client.timeout.total == 10.0


class TestA2AHttpClientContextManager:
    """Test class for A2AHttpClient async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager_creates_session(self):
        """Test that context manager creates session on entry."""
        from backend.utils.a2a_http_client import A2AHttpClient

        async with A2AHttpClient() as client:
            assert client._session is not None

    @pytest.mark.asyncio
    async def test_context_manager_closes_session(self):
        """Test that context manager closes session on exit."""
        from backend.utils.a2a_http_client import A2AHttpClient

        client = A2AHttpClient()
        async with client:
            assert client._session is not None
            session = client._session

        # Session should be closed after exit
        assert session.closed

    @pytest.mark.asyncio
    async def test_context_manager_error_on_missing_session(self):
        """Test that methods raise error when session not initialized."""
        from backend.utils.a2a_http_client import A2AHttpClient, ERR_CLIENT_NOT_INITIALIZED

        client = A2AHttpClient()
        # Session not initialized - should raise error
        with pytest.raises(RuntimeError, match=ERR_CLIENT_NOT_INITIALIZED):
            await client.get_json("https://example.com")


class TestA2AHttpClientGetJson:
    """Test class for A2AHttpClient.get_json method."""

    @pytest.mark.asyncio
    async def test_get_json_success(self):
        """Test successful GET request."""
        from backend.utils.a2a_http_client import A2AHttpClient

        mock_response_data = {"name": "Test Agent", "version": "1.0"}

        # Create mock response that supports async context manager
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(return_value=json.dumps(mock_response_data).encode())
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        # Create mock session where request returns mock_response when awaited
        mock_session = MagicMock()
        mock_session.request = AsyncMock(return_value=mock_response)
        mock_session.close = AsyncMock()

        client = A2AHttpClient()
        async with client:
            client._session = mock_session
            result = await client.get_json("https://example.com/agent.json")
            assert result == mock_response_data

    @pytest.mark.asyncio
    async def test_get_json_with_headers(self):
        """Test GET request with custom headers."""
        from backend.utils.a2a_http_client import A2AHttpClient

        custom_headers = {"Authorization": "Bearer token123"}

        client = A2AHttpClient()
        async with client:
            with patch.object(client, '_request_with_retry', new_callable=AsyncMock) as mock_request:
                mock_request.return_value = (200, b'{"data": "test"}')

                result = await client.get_json(
                    "https://example.com/agent.json",
                    headers=custom_headers
                )
                # Verify headers were passed
                call_kwargs = mock_request.call_args
                assert "headers" in call_kwargs.kwargs or "headers" in call_kwargs[1]

    @pytest.mark.asyncio
    async def test_get_json_timeout(self):
        """Test GET request timeout handling."""
        from backend.utils.a2a_http_client import A2AHttpClient
        import aiohttp

        client = A2AHttpClient()
        async with client:
            with patch.object(client, '_request_with_retry', new_callable=AsyncMock) as mock_request:
                mock_request.side_effect = asyncio.TimeoutError()

                with pytest.raises(asyncio.TimeoutError):
                    await client.get_json("https://example.com")


class TestA2AHttpClientPostJson:
    """Test class for A2AHttpClient.post_json method."""

    @pytest.mark.asyncio
    async def test_post_json_success(self):
        """Test successful POST request."""
        from backend.utils.a2a_http_client import A2AHttpClient

        request_payload = {"message": "Hello"}
        response_data = {"result": "Hi there!"}

        client = A2AHttpClient()
        async with client:
            with patch.object(client, '_request_with_retry', new_callable=AsyncMock) as mock_request:
                mock_request.return_value = (200, json.dumps(response_data).encode())

                result = await client.post_json(
                    "https://example.com/message:send",
                    payload=request_payload
                )
                assert result == response_data

    @pytest.mark.asyncio
    async def test_post_json_with_headers(self):
        """Test POST request with custom headers."""
        from backend.utils.a2a_http_client import A2AHttpClient

        custom_headers = {"X-Custom-Header": "value"}

        client = A2AHttpClient()
        async with client:
            with patch.object(client, '_request_with_retry', new_callable=AsyncMock) as mock_request:
                mock_request.return_value = (200, b'{}')

                await client.post_json(
                    "https://example.com/message:send",
                    payload={"test": True},
                    headers=custom_headers
                )

                # Verify custom headers were merged with default headers
                call_kwargs = mock_request.call_args
                headers = call_kwargs.kwargs.get('headers', call_kwargs[1].get('headers'))
                assert "X-Custom-Header" in headers

    @pytest.mark.asyncio
    async def test_post_json_with_json_payload(self):
        """Test that POST request sends JSON payload correctly."""
        from backend.utils.a2a_http_client import A2AHttpClient

        request_payload = {
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": "Hello"}]
            }
        }

        client = A2AHttpClient()
        async with client:
            with patch.object(client, '_request_with_retry', new_callable=AsyncMock) as mock_request:
                mock_request.return_value = (200, b'{}')

                await client.post_json(
                    "https://example.com/message:send",
                    payload=request_payload
                )

                # Verify json parameter was passed
                call_kwargs = mock_request.call_args
                assert call_kwargs.kwargs.get('json') == request_payload or call_kwargs[1].get('json') == request_payload


class TestA2AHttpClientPostStream:
    """Test class for A2AHttpClient.post_stream method."""

    @pytest.mark.asyncio
    async def test_post_stream_success(self):
        """Test successful streaming POST request."""
        from backend.utils.a2a_http_client import A2AHttpClient

        # Mock SSE lines
        sse_lines = [
            b'data: {"type": "text", "content": "Hello"}\n',
            b'data: {"type": "text", "content": " World"}\n',
            b'data: [DONE]\n'
        ]

        async def mock_content_iter():
            for line in sse_lines:
                yield line

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        # Create async iterator for content
        mock_content = MagicMock()
        mock_content.__aiter__ = lambda self: mock_content_iter()
        mock_response.content = mock_content

        # Create mock session where post returns mock_response (not a coroutine)
        mock_session = MagicMock()
        mock_session.post = AsyncMock(return_value=mock_response)
        mock_session.close = AsyncMock()

        client = A2AHttpClient()
        async with client:
            client._session = mock_session

            events = []
            async for event in client.post_stream(
                "https://example.com/message:stream",
                payload={"message": {"role": "user", "parts": [{"type": "text", "text": "Hi"}]}}
            ):
                events.append(event)

            # Should have parsed 2 events (skipping [DONE])
            assert len(events) == 2

    @pytest.mark.asyncio
    async def test_post_stream_invalid_json(self):
        """Test streaming with invalid JSON is handled gracefully."""
        from backend.utils.a2a_http_client import A2AHttpClient

        sse_lines = [
            b'data: valid-json\n',
            b'data: {"type": "text", "content": "Hello"}\n'
        ]

        async def mock_content_iter():
            for line in sse_lines:
                yield line

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        # Create async iterator for content
        mock_content = MagicMock()
        mock_content.__aiter__ = lambda self: mock_content_iter()
        mock_response.content = mock_content

        # Create mock session where post returns mock_response (not a coroutine)
        mock_session = MagicMock()
        mock_session.post = AsyncMock(return_value=mock_response)
        mock_session.close = AsyncMock()

        client = A2AHttpClient()
        async with client:
            client._session = mock_session

            events = []
            async for event in client.post_stream(
                "https://example.com/message:stream",
                payload={"message": {}}
            ):
                events.append(event)

            # Should skip invalid JSON and capture valid one
            assert len(events) == 1
            assert events[0]["content"] == "Hello"


class TestA2AHttpClientRetry:
    """Test class for A2AHttpClient retry logic."""

    @pytest.mark.asyncio
    async def test_handle_retryable_success(self):
        """Test _handle_retryable does not raise when retries remaining."""
        from backend.utils.a2a_http_client import A2AHttpClient

        client = A2AHttpClient(max_retries=3)
        # Should not raise when attempt < max_retries - 1
        await client._handle_retryable(
            Exception("Test error"),
            attempt=0,
            url="https://example.com",
            context="Test"
        )

    @pytest.mark.asyncio
    async def test_handle_retryable_exhausted(self):
        """Test _handle_retryable raises when retries exhausted."""
        from backend.utils.a2a_http_client import A2AHttpClient

        client = A2AHttpClient(max_retries=3)
        # Should raise when attempt >= max_retries - 1
        with pytest.raises(Exception, match="Test error"):
            await client._handle_retryable(
                Exception("Test error"),
                attempt=2,  # Last attempt (max_retries - 1)
                url="https://example.com",
                context="Test"
            )

    @pytest.mark.asyncio
    async def test_request_with_retry_success_on_first_attempt(self):
        """Test successful request on first attempt."""
        from backend.utils.a2a_http_client import A2AHttpClient

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(return_value=b'{"result": "success"}')
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        client = A2AHttpClient(max_retries=3)
        mock_session = MagicMock()
        # request() returns a coroutine, when awaited returns mock_response
        mock_session.request = AsyncMock(return_value=mock_response)
        client._session = mock_session

        result = await client._request_with_retry("GET", "https://example.com")

        # Returns (status, body) tuple when status < 500
        assert result[0] == 200
        assert client._session.request.call_count == 1

    @pytest.mark.asyncio
    async def test_request_with_retry_handles_500_error_with_retry(self):
        """Test retry on 500 server error."""
        from backend.utils.a2a_http_client import A2AHttpClient

        # First call returns 500, second call succeeds
        success_response = MagicMock()
        success_response.status = 200
        success_response.read = AsyncMock(return_value=b'{"result": "success"}')
        success_response.__aenter__ = AsyncMock(return_value=success_response)
        success_response.__aexit__ = AsyncMock(return_value=None)

        client = A2AHttpClient(max_retries=3)

        # Mock to fail first time, succeed second time
        call_count = 0
        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Return 500 response
                resp = MagicMock()
                resp.status = 500
                resp.read = AsyncMock(return_value=b'Server Error')
                resp.__aenter__ = AsyncMock(return_value=resp)
                resp.__aexit__ = AsyncMock(return_value=None)
                return resp
            else:
                return success_response

        mock_session = MagicMock()
        mock_session.request = mock_request
        client._session = mock_session

        # After exhausting retries with 500 errors, it should return the last response
        result = await client._request_with_retry("GET", "https://example.com")


class TestA2AHttpClientErrorHandling:
    """Test class for A2AHttpClient error handling."""

    @pytest.mark.asyncio
    async def test_connection_reset_error_triggers_retry(self):
        """Test that connection reset errors trigger retry."""
        from backend.utils.a2a_http_client import A2AHttpClient
        import aiohttp

        client = A2AHttpClient(max_retries=2)
        mock_session = MagicMock()
        # session.request() is not async, it returns context manager
        mock_session.request = MagicMock(
            side_effect=aiohttp.ClientConnectionResetError()
        )
        client._session = mock_session

        with pytest.raises(aiohttp.ClientConnectionResetError):
            await client._request_with_retry("GET", "https://example.com")

    @pytest.mark.asyncio
    async def test_server_disconnected_error_triggers_retry(self):
        """Test that server disconnected errors trigger retry."""
        from backend.utils.a2a_http_client import A2AHttpClient
        import aiohttp

        client = A2AHttpClient(max_retries=2)
        mock_session = MagicMock()
        # session.request() is not async, it returns context manager
        mock_session.request = MagicMock(
            side_effect=aiohttp.ServerDisconnectedError()
        )
        client._session = mock_session

        with pytest.raises(aiohttp.ServerDisconnectedError):
            await client._request_with_retry("GET", "https://example.com")

    @pytest.mark.asyncio
    async def test_timeout_error_triggers_retry(self):
        """Test that timeout errors trigger retry."""
        from backend.utils.a2a_http_client import A2AHttpClient

        client = A2AHttpClient(max_retries=2)
        mock_session = MagicMock()
        # session.request() is not async, it returns context manager
        mock_session.request = MagicMock(
            side_effect=asyncio.TimeoutError()
        )
        client._session = mock_session

        with pytest.raises(asyncio.TimeoutError):
            await client._request_with_retry("GET", "https://example.com")


class TestConstants:
    """Test class for module constants."""

    def test_default_timeout_value(self):
        """Test DEFAULT_TIMEOUT constant."""
        from backend.utils.a2a_http_client import DEFAULT_TIMEOUT
        assert DEFAULT_TIMEOUT == 300.0

    def test_agent_card_timeout_value(self):
        """Test AGENT_CARD_TIMEOUT constant."""
        from backend.utils.a2a_http_client import AGENT_CARD_TIMEOUT
        assert AGENT_CARD_TIMEOUT == 10.0

    def test_default_max_retries_value(self):
        """Test DEFAULT_MAX_RETRIES constant."""
        from backend.utils.a2a_http_client import DEFAULT_MAX_RETRIES
        assert DEFAULT_MAX_RETRIES == 3

    def test_retry_backoff_factor_value(self):
        """Test RETRY_BACKOFF_FACTOR constant."""
        from backend.utils.a2a_http_client import RETRY_BACKOFF_FACTOR
        assert RETRY_BACKOFF_FACTOR == 0.5

    def test_content_type_json_value(self):
        """Test CONTENT_TYPE_JSON constant."""
        from backend.utils.a2a_http_client import CONTENT_TYPE_JSON
        assert CONTENT_TYPE_JSON == "application/json"
