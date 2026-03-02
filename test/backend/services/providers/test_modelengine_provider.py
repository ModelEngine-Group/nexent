"""Unit tests for ModelEngineProvider module.

Tests cover model fetching, type mapping, and error handling.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from pytest_mock import MockFixture

import aiohttp

from backend.services.providers.modelengine_provider import (
    ModelEngineProvider,
    MODEL_ENGINE_NORTH_PREFIX,
    get_model_engine_raw_url,
)


class TestModelEngineProvider:
    """Tests for ModelEngineProvider class."""

    @pytest.mark.asyncio
    async def test_get_models_success_with_all_types(self, mocker: MockFixture):
        """Test successful model retrieval with all model types."""
        mock_response_data = {
            "data": [
                {"id": "model-1", "type": "chat"},
                {"id": "model-2", "type": "embed"},
                {"id": "model-3", "type": "asr"},
                {"id": "model-4", "type": "tts"},
                {"id": "model-5", "type": "rerank"},
                {"id": "model-6", "type": "multimodal"},
            ]
        }

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_response_data)
        mock_response.raise_for_status = MagicMock()

        # Create mock client for async context manager
        mock_get_cm = MagicMock()
        mock_get_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_get_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session_instance = MagicMock()
        mock_session_instance.get = MagicMock(return_value=mock_get_cm)

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session_instance)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.modelengine_provider.aiohttp.ClientSession",
            return_value=mock_session_cm
        )

        provider = ModelEngineProvider()
        provider_config = {
            "model_type": "",
            "base_url": "https://test.example.com",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 6
        assert result[0]["id"] == "model-1"
        assert result[0]["model_type"] == "llm"
        assert result[0]["model_tag"] == "chat"
        assert result[0]["max_tokens"] > 0  # LLM type should have max_tokens

    @pytest.mark.asyncio
    async def test_get_models_with_type_filter(self, mocker: MockFixture):
        """Test model retrieval with type filter."""
        mock_response_data = {
            "data": [
                {"id": "llm-model-1", "type": "chat"},
                {"id": "llm-model-2", "type": "chat"},
                {"id": "embed-model-1", "type": "embed"},
            ]
        }

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_response_data)
        mock_response.raise_for_status = MagicMock()

        mock_get_cm = MagicMock()
        mock_get_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_get_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session_instance = MagicMock()
        mock_session_instance.get = MagicMock(return_value=mock_get_cm)

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session_instance)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.modelengine_provider.aiohttp.ClientSession",
            return_value=mock_session_cm
        )

        provider = ModelEngineProvider()
        provider_config = {
            "model_type": "llm",
            "base_url": "https://test.example.com",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 2
        for model in result:
            assert model["model_type"] == "llm"

    @pytest.mark.asyncio
    async def test_get_models_empty_response(self, mocker: MockFixture):
        """Test handling of empty model list from API."""
        mock_response_data = {"data": []}

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_response_data)
        mock_response.raise_for_status = MagicMock()

        mock_get_cm = MagicMock()
        mock_get_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_get_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session_instance = MagicMock()
        mock_session_instance.get = MagicMock(return_value=mock_get_cm)

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session_instance)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.modelengine_provider.aiohttp.ClientSession",
            return_value=mock_session_cm
        )

        provider = ModelEngineProvider()
        provider_config = {
            "model_type": "",
            "base_url": "https://test.example.com",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert result == []

    @pytest.mark.asyncio
    async def test_get_models_missing_host(self, mocker: MockFixture):
        """Test handling when host is missing."""
        provider = ModelEngineProvider()
        provider_config = {
            "model_type": "llm",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert result == []

    @pytest.mark.asyncio
    async def test_get_models_missing_api_key(self, mocker: MockFixture):
        """Test handling when API key is missing."""
        provider = ModelEngineProvider()
        provider_config = {
            "model_type": "llm",
            "base_url": "https://test.example.com"
        }

        result = await provider.get_models(provider_config)

        assert result == []

    @pytest.mark.asyncio
    async def test_get_models_api_error_401(self, mocker: MockFixture):
        """Test handling of 401 API error."""
        mock_response = AsyncMock()
        mock_response.status = 401
        mock_response.text = AsyncMock(return_value="Invalid API key")
        mock_response.raise_for_status = MagicMock()

        mock_get_cm = MagicMock()
        mock_get_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_get_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session_instance = MagicMock()
        mock_session_instance.get = MagicMock(return_value=mock_get_cm)

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session_instance)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.modelengine_provider.aiohttp.ClientSession",
            return_value=mock_session_cm
        )

        provider = ModelEngineProvider()
        provider_config = {
            "model_type": "",
            "base_url": "https://test.example.com",
            "api_key": "invalid-key"
        }

        result = await provider.get_models(provider_config)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["_error"] == "authentication_failed"

    @pytest.mark.asyncio
    async def test_get_models_api_error_500(self, mocker: MockFixture):
        """Test handling of 500 server error."""
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Internal server error")
        mock_response.raise_for_status = MagicMock()

        mock_get_cm = MagicMock()
        mock_get_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_get_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session_instance = MagicMock()
        mock_session_instance.get = MagicMock(return_value=mock_get_cm)

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session_instance)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.modelengine_provider.aiohttp.ClientSession",
            return_value=mock_session_cm
        )

        provider = ModelEngineProvider()
        provider_config = {
            "model_type": "",
            "base_url": "https://test.example.com",
            "api_key": "test-key"
        }

        result = await provider.get_models(provider_config)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["_error"] == "server_error"

    @pytest.mark.asyncio
    async def test_get_models_connection_error(self, mocker: MockFixture):
        """Test handling of connection error."""
        # Use a simple Exception that will be caught by the generic exception handler
        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(side_effect=Exception("Connection refused"))
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.modelengine_provider.aiohttp.ClientSession",
            return_value=mock_session_cm
        )

        provider = ModelEngineProvider()
        provider_config = {
            "model_type": "",
            "base_url": "https://test.example.com",
            "api_key": "test-key"
        }

        result = await provider.get_models(provider_config)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["_error"] == "connection_failed"

    @pytest.mark.asyncio
    async def test_get_models_type_mapping(self, mocker: MockFixture):
        """Test correct type mapping from ModelEngine to internal types."""
        mock_response_data = {
            "data": [
                {"id": "chat-model", "type": "chat"},
                {"id": "embed-model", "type": "embed"},
                {"id": "asr-model", "type": "asr"},
                {"id": "tts-model", "type": "tts"},
                {"id": "rerank-model", "type": "rerank"},
                {"id": "vlm-model", "type": "multimodal"},
            ]
        }

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_response_data)
        mock_response.raise_for_status = MagicMock()

        mock_get_cm = MagicMock()
        mock_get_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_get_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session_instance = MagicMock()
        mock_session_instance.get = MagicMock(return_value=mock_get_cm)

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session_instance)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.modelengine_provider.aiohttp.ClientSession",
            return_value=mock_session_cm
        )

        provider = ModelEngineProvider()
        provider_config = {
            "model_type": "",
            "base_url": "https://test.example.com",
            "api_key": "test-key"
        }

        result = await provider.get_models(provider_config)

        type_mapping = {
            "chat-model": "llm",
            "embed-model": "embedding",
            "asr-model": "stt",
            "tts-model": "tts",
            "rerank-model": "rerank",
            "vlm-model": "vlm",
        }

        for model in result:
            expected_type = type_mapping.get(model["id"])
            assert model["model_type"] == expected_type

    @pytest.mark.asyncio
    async def test_get_models_vlm_has_max_tokens(self, mocker: MockFixture):
        """Test that VLM models have max_tokens set."""
        mock_response_data = {
            "data": [
                {"id": "vlm-model", "type": "multimodal"},
            ]
        }

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_response_data)
        mock_response.raise_for_status = MagicMock()

        mock_get_cm = MagicMock()
        mock_get_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_get_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session_instance = MagicMock()
        mock_session_instance.get = MagicMock(return_value=mock_get_cm)

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session_instance)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.modelengine_provider.aiohttp.ClientSession",
            return_value=mock_session_cm
        )

        provider = ModelEngineProvider()
        provider_config = {
            "model_type": "vlm",
            "base_url": "https://test.example.com",
            "api_key": "test-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 1
        assert result[0]["model_type"] == "vlm"
        assert result[0]["max_tokens"] > 0

    @pytest.mark.asyncio
    async def test_get_models_embedding_no_max_tokens(self, mocker: MockFixture):
        """Test that embedding models have max_tokens set to 0."""
        mock_response_data = {
            "data": [
                {"id": "embed-model", "type": "embed"},
            ]
        }

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_response_data)
        mock_response.raise_for_status = MagicMock()

        mock_get_cm = MagicMock()
        mock_get_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_get_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session_instance = MagicMock()
        mock_session_instance.get = MagicMock(return_value=mock_get_cm)

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session_instance)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.modelengine_provider.aiohttp.ClientSession",
            return_value=mock_session_cm
        )

        provider = ModelEngineProvider()
        provider_config = {
            "model_type": "embedding",
            "base_url": "https://test.example.com",
            "api_key": "test-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 1
        assert result[0]["model_type"] == "embedding"
        assert result[0]["max_tokens"] == 0


class TestModelEngineProviderHelpers:
    """Tests for get_model_engine_raw_url function."""

    def test_get_model_engine_raw_url_with_path(self):
        """Test URL extraction with existing API path."""
        result = get_model_engine_raw_url(
            "https://test.example.com/open/router/v1/models"
        )
        assert result == "https://test.example.com"

    def test_get_model_engine_raw_url_without_path(self):
        """Test URL extraction without API path."""
        result = get_model_engine_raw_url("https://test.example.com")
        assert result == "https://test.example.com"

    def test_get_model_engine_raw_url_with_trailing_slash(self):
        """Test URL extraction with trailing slash."""
        result = get_model_engine_raw_url("https://test.example.com/")
        assert result == "https://test.example.com"

    def test_get_model_engine_raw_url_empty(self):
        """Test URL extraction with empty string."""
        result = get_model_engine_raw_url("")
        assert result == ""

    def test_get_model_engine_raw_url_none(self):
        """Test URL extraction with None."""
        result = get_model_engine_raw_url(None)
        assert result == ""
