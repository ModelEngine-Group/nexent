"""Unit tests for TokenPonyModelProvider module.

Tests cover model fetching, type classification, and error handling.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from pytest_mock import MockFixture

import httpx

from backend.services.providers.tokenpony_provider import TokenPonyModelProvider


class TestTokenPonyModelProvider:
    """Tests for TokenPonyModelProvider class."""

    @pytest.mark.asyncio
    async def test_get_models_llm_success(self, mocker: MockFixture):
        """Test successful model retrieval for LLM models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "gpt-4",
                    "object": "model",
                    "owned_by": "openai"
                },
                {
                    "id": "claude-3-opus",
                    "object": "model",
                    "owned_by": "anthropic"
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
            "backend.services.providers.tokenpony_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.tokenpony_provider.TOKENPONY_GET_URL",
            "https://api.tokenpony.cn/v1/models"
        )
        mocker.patch(
            "backend.services.providers.tokenpony_provider.DEFAULT_LLM_MAX_TOKENS",
            4096
        )

        provider = TokenPonyModelProvider()
        provider_config = {
            "model_type": "llm",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 2
        assert result[0]["id"] == "gpt-4"
        assert result[0]["model_type"] == "llm"
        assert result[0]["model_tag"] == "chat"
        assert result[0]["max_tokens"] == 4096

    @pytest.mark.asyncio
    async def test_get_models_embedding_success(self, mocker: MockFixture):
        """Test successful model retrieval for embedding models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "text-embedding-ada-002",
                    "object": "model",
                    "owned_by": "openai"
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
            "backend.services.providers.tokenpony_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.tokenpony_provider.TOKENPONY_GET_URL",
            "https://api.tokenpony.cn/v1/models"
        )

        provider = TokenPonyModelProvider()
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
    async def test_get_models_vlm_success(self, mocker: MockFixture):
        """Test successful model retrieval for VLM models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "qwen-vl-plus",
                    "object": "model",
                    "owned_by": "qwen"
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
            "backend.services.providers.tokenpony_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.tokenpony_provider.TOKENPONY_GET_URL",
            "https://api.tokenpony.cn/v1/models"
        )

        provider = TokenPonyModelProvider()
        provider_config = {
            "model_type": "vlm",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 1
        assert result[0]["id"] == "qwen-vl-plus"
        assert result[0]["model_type"] == "vlm"
        assert result[0]["model_tag"] == "chat"

    @pytest.mark.asyncio
    async def test_get_models_reranker_success(self, mocker: MockFixture):
        """Test successful model retrieval for reranker models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "gte-reranker-base",
                    "object": "model",
                    "owned_by": "gte"
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
            "backend.services.providers.tokenpony_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.tokenpony_provider.TOKENPONY_GET_URL",
            "https://api.tokenpony.cn/v1/models"
        )

        provider = TokenPonyModelProvider()
        provider_config = {
            "model_type": "reranker",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 1
        assert result[0]["id"] == "gte-reranker-base"
        assert result[0]["model_type"] == "reranker"
        assert result[0]["model_tag"] == "reranker"

    @pytest.mark.asyncio
    async def test_get_models_tts_success(self, mocker: MockFixture):
        """Test successful model retrieval for TTS models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "tts-1-hd",
                    "object": "model",
                    "owned_by": "openai"
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
            "backend.services.providers.tokenpony_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.tokenpony_provider.TOKENPONY_GET_URL",
            "https://api.tokenpony.cn/v1/models"
        )

        provider = TokenPonyModelProvider()
        provider_config = {
            "model_type": "tts",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 1
        assert result[0]["id"] == "tts-1-hd"
        assert result[0]["model_type"] == "tts"
        assert result[0]["model_tag"] == "tts"

    @pytest.mark.asyncio
    async def test_get_models_stt_success(self, mocker: MockFixture):
        """Test successful model retrieval for STT models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "whisper-1",
                    "object": "model",
                    "owned_by": "openai"
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
            "backend.services.providers.tokenpony_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.tokenpony_provider.TOKENPONY_GET_URL",
            "https://api.tokenpony.cn/v1/models"
        )

        provider = TokenPonyModelProvider()
        provider_config = {
            "model_type": "stt",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 1
        assert result[0]["id"] == "whisper-1"
        assert result[0]["model_type"] == "stt"
        assert result[0]["model_tag"] == "stt"

    @pytest.mark.asyncio
    async def test_get_models_multi_embedding_success(self, mocker: MockFixture):
        """Test successful model retrieval for multi-embedding models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "bge-large",
                    "object": "model",
                    "owned_by": "bge"
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
            "backend.services.providers.tokenpony_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.tokenpony_provider.TOKENPONY_GET_URL",
            "https://api.tokenpony.cn/v1/models"
        )

        provider = TokenPonyModelProvider()
        provider_config = {
            "model_type": "multi_embedding",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 1
        assert result[0]["id"] == "bge-large"
        assert result[0]["model_type"] == "embedding"

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
            "backend.services.providers.tokenpony_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.tokenpony_provider.TOKENPONY_GET_URL",
            "https://api.tokenpony.cn/v1/models"
        )

        provider = TokenPonyModelProvider()
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
            "backend.services.providers.tokenpony_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.tokenpony_provider.TOKENPONY_GET_URL",
            "https://api.tokenpony.cn/v1/models"
        )

        provider = TokenPonyModelProvider()
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
            "backend.services.providers.tokenpony_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.tokenpony_provider.TOKENPONY_GET_URL",
            "https://api.tokenpony.cn/v1/models"
        )

        provider = TokenPonyModelProvider()
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
            "backend.services.providers.tokenpony_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.tokenpony_provider.TOKENPONY_GET_URL",
            "https://api.tokenpony.cn/v1/models"
        )

        provider = TokenPonyModelProvider()
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
                    "id": "gpt-4",
                    "object": "model",
                    "owned_by": "openai"
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
            "backend.services.providers.tokenpony_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.tokenpony_provider.TOKENPONY_GET_URL",
            "https://api.tokenpony.cn/v1/models"
        )

        provider = TokenPonyModelProvider()
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
                    "id": "gpt-4",
                    "object": "model",
                    "owned_by": "openai"
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
            "backend.services.providers.tokenpony_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.tokenpony_provider.TOKENPONY_GET_URL",
            "https://api.tokenpony.cn/v1/models"
        )

        provider = TokenPonyModelProvider()
        provider_config = {
            "model_type": "unknown_type",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert result == []

    @pytest.mark.asyncio
    async def test_get_models_vlm_by_keyword(self, mocker: MockFixture):
        """Test VLM classification by keywords like -vl, vl-, ocr, vision."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "qwen-vl-plus",
                    "object": "model",
                    "owned_by": "qwen"
                },
                {
                    "id": "vl-ocr-v1",
                    "object": "model",
                    "owned_by": "ocr"
                },
                {
                    "id": "vision-model-v2",
                    "object": "model",
                    "owned_by": "vision"
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
            "backend.services.providers.tokenpony_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.tokenpony_provider.TOKENPONY_GET_URL",
            "https://api.tokenpony.cn/v1/models"
        )

        provider = TokenPonyModelProvider()
        provider_config = {
            "model_type": "vlm",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 3
        for model in result:
            assert model["model_type"] == "vlm"
            assert model["model_tag"] == "chat"

    @pytest.mark.asyncio
    async def test_get_models_bge_prefix_embedding(self, mocker: MockFixture):
        """Test that models with bge- prefix are classified as embedding."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "bge-large-zh-v1.5",
                    "object": "model",
                    "owned_by": "bge"
                },
                {
                    "id": "bge-base-en-v1.5",
                    "object": "model",
                    "owned_by": "bge"
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
            "backend.services.providers.tokenpony_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.tokenpony_provider.TOKENPONY_GET_URL",
            "https://api.tokenpony.cn/v1/models"
        )

        provider = TokenPonyModelProvider()
        provider_config = {
            "model_type": "embedding",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 2
        for model in result:
            assert model["model_type"] == "embedding"
            assert model["model_tag"] == "embedding"

    @pytest.mark.asyncio
    async def test_get_models_llm_has_max_tokens(self, mocker: MockFixture):
        """Test that LLM models have max_tokens set."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "gpt-4",
                    "object": "model",
                    "owned_by": "openai"
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
            "backend.services.providers.tokenpony_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.tokenpony_provider.TOKENPONY_GET_URL",
            "https://api.tokenpony.cn/v1/models"
        )
        mocker.patch(
            "backend.services.providers.tokenpony_provider.DEFAULT_LLM_MAX_TOKENS",
            4096
        )

        provider = TokenPonyModelProvider()
        provider_config = {
            "model_type": "llm",
            "api_key": "test-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 1
        assert result[0]["max_tokens"] == 4096

