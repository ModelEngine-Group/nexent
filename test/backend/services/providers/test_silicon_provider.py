"""Unit tests for SiliconModelProvider module.

Tests cover model fetching, type handling, and error handling.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Any as MockFixture

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
                {"id": "deepseek-ai/DeepSeek-R1", "name": "DeepSeek R1"},
                {"id": "Qwen/Qwen2.5-VL-72B-Instruct", "name": "Qwen2.5 VL"},
                {"id": "OpenGVLab/InternVL2-26B", "name": "InternVL2 26B"},
                {"id": "Pro/moonshotai/Kimi-K2.6", "name": "Kimi K2.6"},
                {"id": "Pro/moonshotai/Kimi-K2.5", "name": "Kimi K2.5"},
                {"id": "Qwen/Qwen3.6-27B", "name": "Qwen3.6 27B"},
                {"id": "Qwen/Qwen3.6-35B-A3B", "name": "Qwen3.6 35B A3B"},
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

        assert [model["id"] for model in result] == [
            "Qwen/Qwen2.5-VL-72B-Instruct",
            "OpenGVLab/InternVL2-26B",
            "Pro/moonshotai/Kimi-K2.6",
            "Pro/moonshotai/Kimi-K2.5",
            "Qwen/Qwen3.6-27B",
            "Qwen/Qwen3.6-35B-A3B",
        ]
        assert all(model["model_type"] == "vlm" for model in result)
        assert all(model["model_tag"] == "chat" for model in result)

    @pytest.mark.asyncio
    async def test_get_models_vlm3_only_returns_omni_models(self, mocker: MockFixture):
        """Test that SiliconFlow video understanding models are restricted to Omni models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "Qwen/Qwen3-VL-32B-Instruct", "name": "Qwen3 VL"},
                {"id": "Qwen/Qwen3-Omni-30B-A3B-Instruct", "name": "Qwen3 Omni Instruct"},
                {"id": "Qwen/Qwen3-Omni-30B-A3B-Thinking", "name": "Qwen3 Omni Thinking"},
                {"id": "Qwen/Qwen3-Omni-30B-A3B-Captioner", "name": "Qwen3 Omni Captioner"},
                {"id": "zai-org/GLM-4.5V", "name": "GLM 4.5V"},
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
            "model_type": "vlm3",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert [model["id"] for model in result] == [
            "Qwen/Qwen3-Omni-30B-A3B-Instruct",
            "Qwen/Qwen3-Omni-30B-A3B-Thinking",
            "Qwen/Qwen3-Omni-30B-A3B-Captioner",
        ]
        assert all(model["model_type"] == "vlm3" for model in result)
        assert all(model["model_tag"] == "chat" for model in result)
        call_args = mock_client.get.call_args
        assert "sub_type=chat" in call_args[0][0]

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
        """Test unsupported model types are ignored without calling the API."""
        mock_async_client = mocker.patch(
            "backend.services.providers.silicon_provider.httpx.AsyncClient",
            return_value=MagicMock()
        )

        provider = SiliconModelProvider()
        provider_config = {
            "model_type": "stt",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert result == []
        mock_async_client.assert_not_called()

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

    @pytest.mark.asyncio
    async def test_get_models_rerank_success(self, mocker: MockFixture):
        """Test successful model retrieval for rerank models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "gte-rerank-v2", "name": "GTE Rerank V2"},
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
            "model_type": "rerank",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 1
        assert result[0]["id"] == "gte-rerank-v2"
        assert result[0]["model_type"] == "rerank"
        assert result[0]["model_tag"] == "rerank"

    @pytest.mark.asyncio
    async def test_get_models_correct_url_for_rerank(self, mocker: MockFixture):
        """Test that correct URL is used for rerank models."""
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
            "model_type": "rerank",
            "api_key": "test-api-key"
        }

        await provider.get_models(provider_config)

        # Verify the URL contains sub_type=reranker for rerank
        call_args = mock_client.get.call_args
        assert "sub_type=reranker" in call_args[0][0]
