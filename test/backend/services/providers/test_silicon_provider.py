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


class TestSiliconModelProviderFiltering:
    """Tests for model filtering in SiliconModelProvider."""

    @pytest.mark.asyncio
    async def test_get_models_llm_excludes_vision_models(self, mocker: MockFixture):
        """Test that LLM filter excludes vision/image models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "gpt-4", "name": "GPT-4"},
                {"id": "gpt-4-vision", "name": "GPT-4 Vision"},
                {"id": "qwen-vl-72b", "name": "Qwen VL"},
                {"id": "stable-diffusion-xl", "name": "SDXL"},
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

        provider = SiliconModelProvider()
        result = await provider.get_models({
            "model_type": "llm",
            "api_key": "test-key"
        })

        assert len(result) == 1
        assert result[0]["id"] == "gpt-4"

    @pytest.mark.asyncio
    async def test_get_models_image_understanding_filter(self, mocker: MockFixture):
        """Test that image_understanding filter includes only vision models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "gpt-4", "name": "GPT-4"},
                {"id": "gpt-4-vision-preview", "name": "GPT-4V"},
                {"id": "qwen-vl-72b", "name": "Qwen VL"},
                {"id": "llava-1.5", "name": "LLaVA"},
                {"id": "stable-diffusion-xl", "name": "SDXL"},
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

        provider = SiliconModelProvider()
        result = await provider.get_models({
            "model_type": "image_understanding",
            "api_key": "test-key"
        })

        result_ids = [m["id"] for m in result]
        assert "gpt-4" not in result_ids
        assert "stable-diffusion-xl" not in result_ids
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_get_models_image_generation_filter(self, mocker: MockFixture):
        """Test that image_generation filter includes only image gen models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "gpt-4", "name": "GPT-4"},
                {"id": "stable-diffusion-xl", "name": "SDXL"},
                {"id": "wanx-t2i", "name": "Wanx T2I"},
                {"id": "flux-pro", "name": "Flux Pro"},
                {"id": "qwen-vl-72b", "name": "Qwen VL"},
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

        provider = SiliconModelProvider()
        result = await provider.get_models({
            "model_type": "image_generation",
            "api_key": "test-key"
        })

        result_ids = [m["id"] for m in result]
        assert "gpt-4" not in result_ids
        assert "qwen-vl-72b" not in result_ids
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_get_models_video_understanding_filter(self, mocker: MockFixture):
        """Test that video_understanding filter includes only video models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "gpt-4", "name": "GPT-4"},
                {"id": "video-understanding-model", "name": "Video Model"},
                {"id": "stable-diffusion-xl", "name": "SDXL"},
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

        provider = SiliconModelProvider()
        result = await provider.get_models({
            "model_type": "video_understanding",
            "api_key": "test-key"
        })

        result_ids = [m["id"] for m in result]
        assert "gpt-4" not in result_ids
        assert "stable-diffusion-xl" not in result_ids
        assert len(result) == 1
        assert result[0]["id"] == "video-understanding-model"

    @pytest.mark.asyncio
    async def test_get_models_correct_url_for_image_generation(self, mocker: MockFixture):
        """Test that correct URL is used for image_generation models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"id": "stable-diffusion-xl"}]}
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

        provider = SiliconModelProvider()
        await provider.get_models({
            "model_type": "image_generation",
            "api_key": "test-key"
        })

        call_args = mock_client.get.call_args
        assert "sub_type=chat" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_models_correct_url_for_video_understanding(self, mocker: MockFixture):
        """Test that correct URL is used for video_understanding models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"id": "video-model"}]}
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

        provider = SiliconModelProvider()
        await provider.get_models({
            "model_type": "video_understanding",
            "api_key": "test-key"
        })

        call_args = mock_client.get.call_args
        assert "sub_type=chat" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_models_image_generation_correct_base_url(self, mocker: MockFixture):
        """Test that image generation models have correct base_url set."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "stable-diffusion-xl", "name": "SDXL"},
                {"id": "flux-pro", "name": "Flux Pro"},
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
            "backend.services.providers.silicon_provider.SILICON_IMAGE_GEN_URL",
            "https://api.siliconflow.cn/v1/images/generations"
        )

        provider = SiliconModelProvider()
        result = await provider.get_models({
            "model_type": "image_generation",
            "api_key": "test-key"
        })

        for model in result:
            assert model["base_url"] == "https://api.siliconflow.cn/v1/images/generations"
            assert model["model_type"] == "image_generation"
            assert model["model_tag"] == "chat"
