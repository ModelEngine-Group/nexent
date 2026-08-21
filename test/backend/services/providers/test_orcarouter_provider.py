"""Unit tests for OrcaRouterModelProvider module.

Tests cover model fetching, chat-only type filtering, and error handling.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from pytest_mock import MockFixture

from backend.services.providers.orcarouter_provider import OrcaRouterModelProvider


class TestOrcaRouterModelProvider:
    """Tests for OrcaRouterModelProvider class."""

    @pytest.mark.asyncio
    async def test_get_models_llm_success(self, mocker: MockFixture):
        """Test successful model retrieval for LLM models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "orcarouter/auto",
                    "object": "model",
                    "owned_by": "orcarouter"
                },
                {
                    "id": "orcarouter/fusion",
                    "object": "model",
                    "owned_by": "orcarouter"
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.orcarouter_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.orcarouter_provider.ORCAROUTER_GET_URL",
            "https://api.orcarouter.ai/v1/models"
        )
        mocker.patch(
            "backend.services.providers.orcarouter_provider.DEFAULT_LLM_MAX_TOKENS",
            4096
        )

        provider = OrcaRouterModelProvider()
        provider_config = {
            "model_type": "llm",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 2
        assert result[0]["id"] == "orcarouter/auto"
        assert result[0]["model_type"] == "llm"
        assert result[0]["model_tag"] == "chat"
        assert result[0]["max_tokens"] == 4096
        assert "capacity_source" not in result[0]

    @pytest.mark.asyncio
    async def test_get_models_llm_surfaces_capacity_hints(self, mocker: MockFixture):
        """Provider token metadata is returned as advisory capacity hints."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "orcarouter/fusion",
                    "object": "model",
                    "owned_by": "orcarouter",
                    "context_window": 1000000,
                    "max_completion_tokens": "32768",
                    "tokenizer_family": "o200k_base",
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.orcarouter_provider.httpx.AsyncClient",
            return_value=mock_cm
        )

        provider = OrcaRouterModelProvider()
        result = await provider.get_models({
            "model_type": "llm",
            "api_key": "test-api-key",
        })

        assert result[0]["context_window_tokens"] == 1000000
        assert result[0]["max_output_tokens"] == 32768
        assert result[0]["tokenizer_family"] == "o200k_base"
        assert result[0]["capacity_source"] == "provider_candidate"

    @pytest.mark.asyncio
    async def test_get_models_vlm_success(self, mocker: MockFixture):
        """Test successful model retrieval for VLM models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "orcarouter/fusion",
                    "object": "model",
                    "owned_by": "orcarouter"
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.orcarouter_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.orcarouter_provider.ORCAROUTER_GET_URL",
            "https://api.orcarouter.ai/v1/models"
        )

        provider = OrcaRouterModelProvider()
        provider_config = {
            "model_type": "vlm",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 1
        assert result[0]["id"] == "orcarouter/fusion"
        assert result[0]["model_type"] == "vlm"
        assert result[0]["model_tag"] == "chat"

    @pytest.mark.asyncio
    async def test_get_models_non_chat_type_returns_empty(self, mocker: MockFixture):
        """OrcaRouter is a chat-only gateway; non-chat types return empty list."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "orcarouter/auto",
                    "object": "model",
                    "owned_by": "orcarouter"
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.orcarouter_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.orcarouter_provider.ORCAROUTER_GET_URL",
            "https://api.orcarouter.ai/v1/models"
        )

        provider = OrcaRouterModelProvider()
        provider_config = {
            "model_type": "embedding",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert result == []

    @pytest.mark.asyncio
    async def test_get_models_empty_response(self, mocker: MockFixture):
        """Test handling of empty model list from API."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.orcarouter_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.orcarouter_provider.ORCAROUTER_GET_URL",
            "https://api.orcarouter.ai/v1/models"
        )

        provider = OrcaRouterModelProvider()
        provider_config = {
            "model_type": "llm",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert result == []

    @pytest.mark.asyncio
    async def test_get_models_http_error(self, mocker: MockFixture):
        """Test handling of HTTP error."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.HTTPStatusError(
            "Error",
            request=MagicMock(),
            response=MagicMock(status_code=500)
        )

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.orcarouter_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.orcarouter_provider.ORCAROUTER_GET_URL",
            "https://api.orcarouter.ai/v1/models"
        )

        provider = OrcaRouterModelProvider()
        provider_config = {
            "model_type": "llm",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["_error"] == "server_error"

    @pytest.mark.asyncio
    async def test_get_models_401_returns_authentication_failed(self, mocker: MockFixture):
        """401 from provider surfaces the authentication_failed error code."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.HTTPStatusError(
            "Unauthorized",
            request=MagicMock(),
            response=MagicMock(status_code=401),
        )

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.orcarouter_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.orcarouter_provider.ORCAROUTER_GET_URL",
            "https://api.orcarouter.ai/v1/models"
        )

        provider = OrcaRouterModelProvider()
        provider_config = {
            "model_type": "llm",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["_error"] == "authentication_failed"

    @pytest.mark.asyncio
    async def test_get_models_connect_error(self, mocker: MockFixture):
        """Test handling of connection error."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("Connection failed")

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.orcarouter_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.orcarouter_provider.ORCAROUTER_GET_URL",
            "https://api.orcarouter.ai/v1/models"
        )

        provider = OrcaRouterModelProvider()
        provider_config = {
            "model_type": "llm",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["_error"] == "connection_failed"

    @pytest.mark.asyncio
    async def test_get_models_authorization_header(self, mocker: MockFixture):
        """Test that Authorization header is correctly set."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "orcarouter/auto",
                    "object": "model",
                    "owned_by": "orcarouter"
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.orcarouter_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.orcarouter_provider.ORCAROUTER_GET_URL",
            "https://api.orcarouter.ai/v1/models"
        )

        provider = OrcaRouterModelProvider()
        provider_config = {
            "model_type": "llm",
            "api_key": "my-secret-key"
        }

        await provider.get_models(provider_config)

        # Verify Authorization header
        call_args = mock_client.get.call_args
        headers = call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer my-secret-key"

    @pytest.mark.asyncio
    async def test_get_models_unknown_type_returns_empty(self, mocker: MockFixture):
        """Test that unknown model type returns empty list."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "orcarouter/auto",
                    "object": "model",
                    "owned_by": "orcarouter"
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.orcarouter_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.orcarouter_provider.ORCAROUTER_GET_URL",
            "https://api.orcarouter.ai/v1/models"
        )

        provider = OrcaRouterModelProvider()
        provider_config = {
            "model_type": "unknown_type",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert result == []
