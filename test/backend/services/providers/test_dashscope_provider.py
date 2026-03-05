"""Unit tests for DashScopeModelProvider module.

Tests cover model fetching, type classification, and error handling.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from pytest_mock import MockFixture

import httpx

from backend.services.providers.dashscope_provider import DashScopeModelProvider


class TestDashScopeModelProvider:
    """Tests for DashScopeModelProvider class."""

    @pytest.mark.asyncio
    async def test_get_models_llm_success(self, mocker: MockFixture):
        """Test successful model retrieval for LLM models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "qwen-turbo",
                        "description": "Text generation model",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"]
                        }
                    },
                    {
                        "model": "qwen-plus",
                        "description": "Advanced text generation",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"]
                        }
                    }
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.dashscope_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.dashscope_provider.DASHSCOPE_GET_URL",
            "https://dashscope.aliyuncs.com/api/v1/models"
        )
        mocker.patch(
            "backend.services.providers.dashscope_provider.DEFAULT_LLM_MAX_TOKENS",
            4096
        )

        provider = DashScopeModelProvider()
        provider_config = {
            "model_type": "llm",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 2
        assert result[0]["id"] == "qwen-turbo"
        assert result[0]["model_type"] == "llm"
        assert result[0]["model_tag"] == "chat"
        assert result[0]["max_tokens"] == 4096

    @pytest.mark.asyncio
    async def test_get_models_embedding_success(self, mocker: MockFixture):
        """Test successful model retrieval for embedding models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "text-embedding-v3",
                        "description": "Embedding model",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"]
                        }
                    }
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.dashscope_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.dashscope_provider.DASHSCOPE_GET_URL",
            "https://dashscope.aliyuncs.com/api/v1/models"
        )

        provider = DashScopeModelProvider()
        provider_config = {
            "model_type": "embedding",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 1
        assert result[0]["id"] == "text-embedding-v3"
        assert result[0]["model_type"] == "embedding"
        assert result[0]["model_tag"] == "embedding"

    @pytest.mark.asyncio
    async def test_get_models_vlm_success(self, mocker: MockFixture):
        """Test successful model retrieval for VLM models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "qwen-vl-plus",
                        "description": "Vision language model",
                        "inference_metadata": {
                            "request_modality": ["Image", "Text"],
                            "response_modality": ["Text"]
                        }
                    }
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.dashscope_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.dashscope_provider.DASHSCOPE_GET_URL",
            "https://dashscope.aliyuncs.com/api/v1/models"
        )

        provider = DashScopeModelProvider()
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
            "output": {
                "models": [
                    {
                        "model": "gte-reranker",
                        "description": "Reranking model",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"]
                        }
                    }
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.dashscope_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.dashscope_provider.DASHSCOPE_GET_URL",
            "https://dashscope.aliyuncs.com/api/v1/models"
        )

        provider = DashScopeModelProvider()
        provider_config = {
            "model_type": "reranker",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 1
        assert result[0]["id"] == "gte-reranker"
        assert result[0]["model_type"] == "reranker"
        assert result[0]["model_tag"] == "reranker"

    @pytest.mark.asyncio
    async def test_get_models_tts_success(self, mocker: MockFixture):
        """Test successful model retrieval for TTS models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "sambert-tts",
                        "description": "Text to speech",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Audio"]
                        }
                    }
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.dashscope_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.dashscope_provider.DASHSCOPE_GET_URL",
            "https://dashscope.aliyuncs.com/api/v1/models"
        )

        provider = DashScopeModelProvider()
        provider_config = {
            "model_type": "tts",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 1
        assert result[0]["id"] == "sambert-tts"
        assert result[0]["model_type"] == "tts"
        assert result[0]["model_tag"] == "tts"

    @pytest.mark.asyncio
    async def test_get_models_stt_success(self, mocker: MockFixture):
        """Test successful model retrieval for STT models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "paraformer-realtime-v2",
                        "description": "Speech recognition",
                        "inference_metadata": {
                            "request_modality": ["Audio"],
                            "response_modality": ["Text"]
                        }
                    }
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.dashscope_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.dashscope_provider.DASHSCOPE_GET_URL",
            "https://dashscope.aliyuncs.com/api/v1/models"
        )

        provider = DashScopeModelProvider()
        provider_config = {
            "model_type": "stt",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 1
        assert result[0]["id"] == "paraformer-realtime-v2"
        assert result[0]["model_type"] == "stt"
        assert result[0]["model_tag"] == "stt"

    @pytest.mark.asyncio
    async def test_get_models_multi_embedding_success(self, mocker: MockFixture):
        """Test successful model retrieval for multi-embedding models."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "text-embedding-multimodal-v3",
                        "description": "Multimodal embedding",
                        "inference_metadata": {
                            "request_modality": ["Text", "Image"],
                            "response_modality": ["Text"]
                        }
                    }
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.dashscope_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.dashscope_provider.DASHSCOPE_GET_URL",
            "https://dashscope.aliyuncs.com/api/v1/models"
        )

        provider = DashScopeModelProvider()
        provider_config = {
            "model_type": "multi_embedding",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert len(result) == 1
        assert result[0]["id"] == "text-embedding-multimodal-v3"
        assert result[0]["model_type"] == "embedding"

    @pytest.mark.asyncio
    async def test_get_models_empty_response(self, mocker: MockFixture):
        """Test handling of empty model list from API."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"output": {"models": []}}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.dashscope_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.dashscope_provider.DASHSCOPE_GET_URL",
            "https://dashscope.aliyuncs.com/api/v1/models"
        )

        provider = DashScopeModelProvider()
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
            "backend.services.providers.dashscope_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.dashscope_provider.DASHSCOPE_GET_URL",
            "https://dashscope.aliyuncs.com/api/v1/models"
        )

        provider = DashScopeModelProvider()
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
            "backend.services.providers.dashscope_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.dashscope_provider.DASHSCOPE_GET_URL",
            "https://dashscope.aliyuncs.com/api/v1/models"
        )

        provider = DashScopeModelProvider()
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
            "backend.services.providers.dashscope_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.dashscope_provider.DASHSCOPE_GET_URL",
            "https://dashscope.aliyuncs.com/api/v1/models"
        )

        provider = DashScopeModelProvider()
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
            "output": {
                "models": [
                    {
                        "model": "qwen-turbo",
                        "description": "Test",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"]
                        }
                    }
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.dashscope_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.dashscope_provider.DASHSCOPE_GET_URL",
            "https://dashscope.aliyuncs.com/api/v1/models"
        )

        provider = DashScopeModelProvider()
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
    async def test_get_models_pagination(self, mocker: MockFixture):
        """Test that pagination works correctly."""
        # First page returns 100 models
        mock_response_page1 = MagicMock()
        mock_response_page1.status_code = 200
        mock_response_page1.json.return_value = {
            "output": {
                "models": [{"model": f"model-{i}", "description": "test",
                           "inference_metadata": {"request_modality": ["Text"], "response_modality": ["Text"]}}
                           for i in range(100)]
            }
        }
        mock_response_page1.raise_for_status = MagicMock()

        # Second page returns 50 models (less than page_size)
        mock_response_page2 = MagicMock()
        mock_response_page2.status_code = 200
        mock_response_page2.json.return_value = {
            "output": {
                "models": [{"model": f"model-{i}", "description": "test",
                           "inference_metadata": {"request_modality": ["Text"], "response_modality": ["Text"]}}
                           for i in range(100, 150)]
            }
        }
        mock_response_page2.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.side_effect = [mock_response_page1, mock_response_page2]

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.dashscope_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.dashscope_provider.DASHSCOPE_GET_URL",
            "https://dashscope.aliyuncs.com/api/v1/models"
        )

        provider = DashScopeModelProvider()
        provider_config = {
            "model_type": "llm",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        # Should get models from both pages
        assert len(result) == 150

    @pytest.mark.asyncio
    async def test_get_models_unknown_type_returns_empty(self, mocker: MockFixture):
        """Test that unknown model type returns empty list."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "qwen-turbo",
                        "description": "Text generation",
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"]
                        }
                    }
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.dashscope_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.dashscope_provider.DASHSCOPE_GET_URL",
            "https://dashscope.aliyuncs.com/api/v1/models"
        )

        provider = DashScopeModelProvider()
        provider_config = {
            "model_type": "unknown_type",
            "api_key": "test-api-key"
        }

        result = await provider.get_models(provider_config)

        assert result == []

    @pytest.mark.asyncio
    async def test_get_models_with_chinese_description(self, mocker: MockFixture):
        """Test model classification by Chinese description."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": {
                "models": [
                    {
                        "model": "embedding-v1",
                        "description": "向量embedding模型",  # Chinese description
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"]
                        }
                    },
                    {
                        "model": "rerank-v1",
                        "description": "重排序模型",  # Chinese description
                        "inference_metadata": {
                            "request_modality": ["Text"],
                            "response_modality": ["Text"]
                        }
                    }
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        mocker.patch(
            "backend.services.providers.dashscope_provider.httpx.AsyncClient",
            return_value=mock_cm
        )
        mocker.patch(
            "backend.services.providers.dashscope_provider.DASHSCOPE_GET_URL",
            "https://dashscope.aliyuncs.com/api/v1/models"
        )

        provider = DashScopeModelProvider()

        # Test embedding classification by Chinese description
        result = await provider.get_models({"model_type": "embedding", "api_key": "test-key"})
        assert len(result) == 1
        assert result[0]["id"] == "embedding-v1"

        # Test reranker classification by Chinese description
        result = await provider.get_models({"model_type": "reranker", "api_key": "test-key"})
        assert len(result) == 1
        assert result[0]["id"] == "rerank-v1"

