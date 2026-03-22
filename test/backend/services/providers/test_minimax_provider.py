"""Unit tests for MiniMaxModelProvider module.

Tests cover model fetching, type classification, and error handling.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from pytest_mock import MockFixture

import httpx

from backend.services.providers.minimax_provider import MiniMaxModelProvider


class TestMiniMaxModelProvider:
    """Tests for MiniMaxModelProvider class."""

    @pytest.mark.asyncio
    async def test_get_models_llm_success(self, mocker: MockFixture):
        """Test successful model retrieval for LLM models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "MiniMax-M2.7",
                    "object": "model",
                    "owned_by": "minimax"
                },
                {
                    "id": "MiniMax-M2.5",
                    "object": "model",
                    "owned_by": "minimax"
                },
                {
                    "id": "MiniMax-M2.5-highspeed",
                    "object": "model",
                    "owned_by": "minimax"
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
            "backend.services.providers.minimax_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.minimax_provider.MINIMAX_GET_URL",
            "https://api.minimax.io/v1/models"
        )
        mocker.patch(
            "backend.services.providers.minimax_provider.DEFAULT_LLM_MAX_TOKENS",
            4096
        )

        provider = MiniMaxModelProvider()
        provider_config = {
            "model_type": "llm",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 3
        assert result[0]["id"] == "MiniMax-M2.7"
        assert result[0]["model_type"] == "llm"
        assert result[0]["model_tag"] == "chat"
        # M2.7 has 1M context window
        assert result[0]["max_tokens"] == 1000000

    @pytest.mark.asyncio
    async def test_get_models_llm_known_context_windows(self, mocker: MockFixture):
        """Test that known MiniMax models get their correct context window sizes."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "MiniMax-M2.7", "object": "model", "owned_by": "minimax"},
                {"id": "MiniMax-M2.5", "object": "model", "owned_by": "minimax"},
                {"id": "MiniMax-M2.5-highspeed", "object": "model", "owned_by": "minimax"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.minimax_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.minimax_provider.MINIMAX_GET_URL",
            "https://api.minimax.io/v1/models"
        )

        provider = MiniMaxModelProvider()
        provider_config = {"model_type": "llm", "api_key": "test-api-key"}

        result = await provider.get_models(provider_config)

        model_map = {m["id"]: m for m in result}
        assert model_map["MiniMax-M2.7"]["max_tokens"] == 1000000
        assert model_map["MiniMax-M2.5"]["max_tokens"] == 204800
        assert model_map["MiniMax-M2.5-highspeed"]["max_tokens"] == 204800

    @pytest.mark.asyncio
    async def test_get_models_embedding_success(self, mocker: MockFixture):
        """Test successful model retrieval for embedding models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "embo-01",
                    "object": "model",
                    "owned_by": "minimax"
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
            "backend.services.providers.minimax_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.minimax_provider.MINIMAX_GET_URL",
            "https://api.minimax.io/v1/models"
        )

        provider = MiniMaxModelProvider()
        provider_config = {
            "model_type": "embedding",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 1
        assert result[0]["id"] == "embo-01"
        assert result[0]["model_type"] == "embedding"
        assert result[0]["model_tag"] == "embedding"

    @pytest.mark.asyncio
    async def test_get_models_tts_success(self, mocker: MockFixture):
        """Test successful model retrieval for TTS models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "speech-2.8-hd",
                    "object": "model",
                    "owned_by": "minimax"
                },
                {
                    "id": "tts-1",
                    "object": "model",
                    "owned_by": "minimax"
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
            "backend.services.providers.minimax_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.minimax_provider.MINIMAX_GET_URL",
            "https://api.minimax.io/v1/models"
        )

        provider = MiniMaxModelProvider()
        provider_config = {
            "model_type": "tts",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 2
        assert result[0]["id"] == "speech-2.8-hd"
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
                    "id": "stt-whisper-v1",
                    "object": "model",
                    "owned_by": "minimax"
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
            "backend.services.providers.minimax_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.minimax_provider.MINIMAX_GET_URL",
            "https://api.minimax.io/v1/models"
        )

        provider = MiniMaxModelProvider()
        provider_config = {
            "model_type": "stt",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 1
        assert result[0]["id"] == "stt-whisper-v1"
        assert result[0]["model_type"] == "stt"
        assert result[0]["model_tag"] == "stt"

    @pytest.mark.asyncio
    async def test_get_models_reranker_success(self, mocker: MockFixture):
        """Test successful model retrieval for reranker models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "rerank-v1",
                    "object": "model",
                    "owned_by": "minimax"
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
            "backend.services.providers.minimax_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.minimax_provider.MINIMAX_GET_URL",
            "https://api.minimax.io/v1/models"
        )

        provider = MiniMaxModelProvider()
        provider_config = {
            "model_type": "reranker",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 1
        assert result[0]["id"] == "rerank-v1"
        assert result[0]["model_type"] == "reranker"
        assert result[0]["model_tag"] == "reranker"

    @pytest.mark.asyncio
    async def test_get_models_vlm_success(self, mocker: MockFixture):
        """Test successful model retrieval for VLM models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "minimax-vl-01",
                    "object": "model",
                    "owned_by": "minimax"
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
            "backend.services.providers.minimax_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.minimax_provider.MINIMAX_GET_URL",
            "https://api.minimax.io/v1/models"
        )

        provider = MiniMaxModelProvider()
        provider_config = {
            "model_type": "vlm",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 1
        assert result[0]["id"] == "minimax-vl-01"
        assert result[0]["model_type"] == "vlm"
        assert result[0]["model_tag"] == "chat"

    @pytest.mark.asyncio
    async def test_get_models_multi_embedding_success(self, mocker: MockFixture):
        """Test successful model retrieval for multi-embedding models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "embo-01",
                    "object": "model",
                    "owned_by": "minimax"
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
            "backend.services.providers.minimax_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.minimax_provider.MINIMAX_GET_URL",
            "https://api.minimax.io/v1/models"
        )

        provider = MiniMaxModelProvider()
        provider_config = {
            "model_type": "multi_embedding",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 1
        assert result[0]["id"] == "embo-01"
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
            "backend.services.providers.minimax_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.minimax_provider.MINIMAX_GET_URL",
            "https://api.minimax.io/v1/models"
        )

        provider = MiniMaxModelProvider()
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
            "backend.services.providers.minimax_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.minimax_provider.MINIMAX_GET_URL",
            "https://api.minimax.io/v1/models"
        )

        provider = MiniMaxModelProvider()
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
            "backend.services.providers.minimax_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.minimax_provider.MINIMAX_GET_URL",
            "https://api.minimax.io/v1/models"
        )

        provider = MiniMaxModelProvider()
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
            "backend.services.providers.minimax_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.minimax_provider.MINIMAX_GET_URL",
            "https://api.minimax.io/v1/models"
        )

        provider = MiniMaxModelProvider()
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
                    "id": "MiniMax-M2.7",
                    "object": "model",
                    "owned_by": "minimax"
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
            "backend.services.providers.minimax_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.minimax_provider.MINIMAX_GET_URL",
            "https://api.minimax.io/v1/models"
        )

        provider = MiniMaxModelProvider()
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
                    "id": "MiniMax-M2.7",
                    "object": "model",
                    "owned_by": "minimax"
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
            "backend.services.providers.minimax_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.minimax_provider.MINIMAX_GET_URL",
            "https://api.minimax.io/v1/models"
        )

        provider = MiniMaxModelProvider()
        provider_config = {
            "model_type": "unknown_type",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert result == []

    @pytest.mark.asyncio
    async def test_get_models_mixed_types_classification(self, mocker: MockFixture):
        """Test classification of mixed model types returns only requested type."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "MiniMax-M2.7", "object": "model", "owned_by": "minimax"},
                {"id": "embo-01", "object": "model", "owned_by": "minimax"},
                {"id": "speech-2.8-hd", "object": "model", "owned_by": "minimax"},
                {"id": "rerank-v1", "object": "model", "owned_by": "minimax"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.minimax_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.minimax_provider.MINIMAX_GET_URL",
            "https://api.minimax.io/v1/models"
        )

        provider = MiniMaxModelProvider()

        # Request LLM - should only return chat models
        result = await provider.get_models({"model_type": "llm", "api_key": "test"})
        assert len(result) == 1
        assert result[0]["id"] == "MiniMax-M2.7"

    @pytest.mark.asyncio
    async def test_get_models_preserves_original_id(self, mocker: MockFixture):
        """Test that original model ID casing is preserved."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "MiniMax-M2.7", "object": "model", "owned_by": "minimax"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.minimax_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.minimax_provider.MINIMAX_GET_URL",
            "https://api.minimax.io/v1/models"
        )

        provider = MiniMaxModelProvider()
        result = await provider.get_models({"model_type": "llm", "api_key": "test"})

        # ID should be preserved as-is (not lowercased)
        assert result[0]["id"] == "MiniMax-M2.7"
