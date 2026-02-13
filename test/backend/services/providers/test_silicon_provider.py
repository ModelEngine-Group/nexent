"""Unit tests for SiliconModelProvider module.

Tests cover model fetching, type handling, and error handling.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from pytest_mock import MockFixture

import httpx

from backend.services.providers.silicon_provider import SiliconModelProvider


class TestSiliconModelProvider:
    """Tests for SiliconModelProvider class."""

    @pytest.mark.asyncio
    async def test_get_models_llm_success(self, mocker: MockFixture):
        """Test successful model retrieval for LLM models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "gpt-4", "name": "GPT-4"},
                {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        # Create mock client that works as async context manager
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        # Create the context manager mock
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.silicon_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.silicon_provider.SILICON_GET_URL",
            "https://api.siliconflow.com/v1/models"
        )

        provider = SiliconModelProvider()
        provider_config = {
            "model_type": "llm",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 2
        assert result[0]["id"] == "gpt-4"
        assert result[0]["model_type"] == "llm"
        assert result[0]["model_tag"] == "chat"

    @pytest.mark.asyncio
    async def test_get_models_vlm_success(self, mocker: MockFixture):
        """Test successful model retrieval for VLM models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "gpt-4v", "name": "GPT-4 Vision"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.silicon_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.silicon_provider.SILICON_GET_URL",
            "https://api.siliconflow.com/v1/models"
        )

        provider = SiliconModelProvider()
        provider_config = {
            "model_type": "vlm",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 1
        assert result[0]["id"] == "gpt-4v"
        assert result[0]["model_type"] == "vlm"
        assert result[0]["model_tag"] == "chat"

    @pytest.mark.asyncio
    async def test_get_models_embedding_success(self, mocker: MockFixture):
        """Test successful model retrieval for embedding models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "text-embedding-ada-002", "name": "Text Embedding Ada 002"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.silicon_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.silicon_provider.SILICON_GET_URL",
            "https://api.siliconflow.com/v1/models"
        )

        provider = SiliconModelProvider()
        provider_config = {
            "model_type": "embedding",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 1
        assert result[0]["id"] == "text-embedding-ada-002"
        assert result[0]["model_type"] == "embedding"
        assert result[0]["model_tag"] == "embedding"

    @pytest.mark.asyncio
    async def test_get_models_multi_embedding_success(self, mocker: MockFixture):
        """Test successful model retrieval for multi-embedding models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "bge-large", "name": "BGE Large"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.silicon_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.silicon_provider.SILICON_GET_URL",
            "https://api.siliconflow.com/v1/models"
        )

        provider = SiliconModelProvider()
        provider_config = {
            "model_type": "multi_embedding",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 1
        assert result[0]["id"] == "bge-large"
        assert result[0]["model_type"] == "multi_embedding"
        assert result[0]["model_tag"] == "embedding"

    @pytest.mark.asyncio
    async def test_get_models_unknown_type(self, mocker: MockFixture):
        """Test model retrieval for unknown model types."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "unknown-model", "name": "Unknown Model"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.silicon_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.silicon_provider.SILICON_GET_URL",
            "https://api.siliconflow.com/v1/models"
        )

        provider = SiliconModelProvider()
        provider_config = {
            "model_type": "stt",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 1
        assert result[0]["id"] == "unknown-model"

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
            "backend.services.providers.silicon_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.silicon_provider.SILICON_GET_URL",
            "https://api.siliconflow.com/v1/models"
        )

        provider = SiliconModelProvider()
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
            "backend.services.providers.silicon_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.silicon_provider.SILICON_GET_URL",
            "https://api.siliconflow.com/v1/models"
        )

        provider = SiliconModelProvider()
        provider_config = {
            "model_type": "llm",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["_error"] == "connection_failed"

    @pytest.mark.asyncio
    async def test_get_models_connect_error(self, mocker: MockFixture):
        """Test handling of connection error."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("Connection failed")

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.silicon_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.silicon_provider.SILICON_GET_URL",
            "https://api.siliconflow.com/v1/models"
        )

        provider = SiliconModelProvider()
        provider_config = {
            "model_type": "llm",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["_error"] == "connection_failed"

    @pytest.mark.asyncio
    async def test_get_models_timeout(self, mocker: MockFixture):
        """Test handling of connection timeout."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectTimeout("Timeout")

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.silicon_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.silicon_provider.SILICON_GET_URL",
            "https://api.siliconflow.com/v1/models"
        )

        provider = SiliconModelProvider()
        provider_config = {
            "model_type": "llm",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["_error"] == "connection_failed"

    @pytest.mark.asyncio
    async def test_get_models_correct_url_for_llm(self, mocker: MockFixture):
        """Test that correct URL is used for LLM models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"id": "test"}]}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.silicon_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.silicon_provider.SILICON_GET_URL",
            "https://api.siliconflow.com/models"
        )

        provider = SiliconModelProvider()
        provider_config = {
            "model_type": "llm",
            "api_key": "test-api-key"
        }

        await provider.get_models(provider_config)

        # Verify the URL contains sub_type=chat for LLM
        call_args = mock_client.get.call_args
        assert "sub_type=chat" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_models_correct_url_for_embedding(self, mocker: MockFixture):
        """Test that correct URL is used for embedding models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"id": "test"}]}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.silicon_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.silicon_provider.SILICON_GET_URL",
            "https://api.siliconflow.com/models"
        )

        provider = SiliconModelProvider()
        provider_config = {
            "model_type": "embedding",
            "api_key": "test-api-key"
        }

        await provider.get_models(provider_config)

        # Verify the URL contains sub_type=embedding for embedding
        call_args = mock_client.get.call_args
        assert "sub_type=embedding" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_models_authorization_header(self, mocker: MockFixture):
        """Test that Authorization header is correctly set."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"id": "test"}]}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.silicon_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.silicon_provider.SILICON_GET_URL",
            "https://api.siliconflow.com/models"
        )

        provider = SiliconModelProvider()
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
    async def test_get_models_llm_has_max_tokens(self, mocker: MockFixture):
        """Test that LLM models have max_tokens set."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [{"id": "gpt-4"}]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.silicon_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.silicon_provider.SILICON_GET_URL",
            "https://api.siliconflow.com/models"
        )
        mocker.patch(
            "backend.services.providers.silicon_provider.DEFAULT_LLM_MAX_TOKENS",
            4096
        )

        provider = SiliconModelProvider()
        provider_config = {
            "model_type": "llm",
            "api_key": "test-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 1
        assert result[0]["max_tokens"] == 4096
