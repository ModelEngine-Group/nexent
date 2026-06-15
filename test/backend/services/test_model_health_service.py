import os
import sys
import types
from unittest import mock

import pytest

# Dynamically determine the backend path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.append(backend_dir)


class MockModule(mock.MagicMock):
    @classmethod
    def __getattr__(cls, key):
        return mock.MagicMock()  # Return a regular MagicMock instead of a new MockModule


# Mock required modules before any imports occur
sys.modules['database'] = MockModule()
sys.modules['database.client'] = MockModule()
sys.modules['database.model_management_db'] = MockModule()
sys.modules['utils'] = MockModule()
sys.modules['utils.auth_utils'] = MockModule()
sys.modules['utils.config_utils'] = MockModule()
sys.modules['utils.memory_utils'] = MockModule()
sys.modules['utils.model_name_utils'] = MockModule()
sys.modules['consts'] = MockModule()
consts_const_module = MockModule()
consts_const_module.LOCALHOST_IP = "127.0.0.1"
consts_const_module.LOCALHOST_NAME = "localhost"
consts_const_module.DOCKER_INTERNAL_HOST = "host.docker.internal"
sys.modules['consts.const'] = consts_const_module
sys.modules['consts.model'] = MockModule()
sys.modules['consts.provider'] = MockModule()

# Mock nexent packages and modules with proper hierarchy
sys.modules['nexent'] = MockModule()
sys.modules['nexent.core'] = MockModule()
sys.modules['nexent.core.agents'] = MockModule()
sys.modules['nexent.core.agents.agent_model'] = MockModule()
sys.modules['nexent.core.models'] = MockModule()
sys.modules['nexent.core.models.embedding_model'] = MockModule()

monitor_module = MockModule()
monitor_module.set_monitoring_context = mock.MagicMock()
monitor_module.set_monitoring_operation = mock.MagicMock()
sys.modules['nexent.monitor'] = monitor_module

# Mock rerank_model module with proper class exports


class MockBaseRerank:
    pass


class MockOpenAICompatibleRerank(MockBaseRerank):
    def __init__(self, *args, **kwargs):
        pass


rerank_module = MockModule()
rerank_module.BaseRerank = MockBaseRerank
rerank_module.OpenAICompatibleRerank = MockOpenAICompatibleRerank
sys.modules['nexent.core.models.rerank_model'] = rerank_module

# Mock services packages
sys.modules['services'] = MockModule()
sys.modules['services.voice_service'] = MockModule()

# Define the ModelConnectStatusEnum for testing


class ModelConnectStatusEnum:
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DETECTING = "detecting"

# Define a ModelResponse class for testing


class ModelResponse:
    def __init__(self, code, message="", data=None):
        self.code = code
        self.message = message
        self.data = data or {}


# Now import the module under test
from backend.services.model_health_service import (
    _perform_connectivity_check,
    check_model_connectivity,
    verify_model_config_connectivity,
    _embedding_dimension_check,
    embedding_dimension_check,
)


@pytest.mark.asyncio
async def test_perform_connectivity_check_embedding():
    # Setup
    with mock.patch("backend.services.model_health_service.OpenAICompatibleEmbedding") as mock_embedding:
        mock_embedding_instance = mock.MagicMock()
        mock_embedding_instance.dimension_check = mock.AsyncMock(return_value=[
            [1]
        ])
        mock_embedding.return_value = mock_embedding_instance

        # Execute
        result = await _perform_connectivity_check(
            "text-embedding-ada-002",
            "embedding",
            "https://api.openai.com",
            "test-key",
        )

        # Assert
        assert result is True
        mock_embedding.assert_called_once_with(
            model_name="text-embedding-ada-002",
            base_url="https://api.openai.com/embeddings",
            api_key="test-key",
            embedding_dim=0,
            ssl_verify=True,
        )
        mock_embedding_instance.dimension_check.assert_called_once()


@pytest.mark.asyncio
async def test_perform_connectivity_check_multi_embedding():
    # Setup
    with mock.patch("backend.services.model_health_service.JinaEmbedding") as mock_embedding:
        mock_embedding_instance = mock.MagicMock()
        mock_embedding_instance.dimension_check = mock.AsyncMock(return_value=[
            [1]
        ])
        mock_embedding.return_value = mock_embedding_instance

        # Execute
        result = await _perform_connectivity_check(
            "jina-embeddings-v2",
            "multi_embedding",
            "https://api.jina.ai",
            "test-key",
        )

        # Assert
        assert result is True
        mock_embedding.assert_called_once_with(
            api_key="test-key",
            base_url="https://api.jina.ai/embeddings",
            model_name="jina-embeddings-v2",
            embedding_dim=0,
            ssl_verify=True,
        )


@pytest.mark.asyncio
async def test_perform_connectivity_check_llm():
    # Setup
    with mock.patch("backend.services.model_health_service.MessageObserver") as mock_observer, \
            mock.patch("backend.services.model_health_service.OpenAIModel") as mock_model:
        mock_observer_instance = mock.MagicMock()
        mock_observer.return_value = mock_observer_instance

        mock_model_instance = mock.MagicMock()
        mock_model_instance.check_connectivity = mock.AsyncMock(
            return_value=True)
        mock_model.return_value = mock_model_instance

        # Execute
        result = await _perform_connectivity_check(
            "gpt-4",
            "llm",
            "https://api.openai.com",
            "test-key",
        )

        # Assert
        assert result is True
        mock_model.assert_called_once_with(
            mock_observer_instance,
            model_id="gpt-4",
            api_base="https://api.openai.com",
            api_key="test-key",
            ssl_verify=True,
            timeout_seconds=None,
        )
        mock_model_instance.check_connectivity.assert_called_once()


@pytest.mark.asyncio
async def test_perform_connectivity_check_vlm():
    # Setup
    with mock.patch("backend.services.model_health_service.MessageObserver") as mock_observer, \
            mock.patch("backend.services.model_health_service.OpenAIVLModel") as mock_model:
        mock_observer_instance = mock.MagicMock()
        mock_observer.return_value = mock_observer_instance

        mock_model_instance = mock.MagicMock()
        mock_model_instance.check_connectivity = mock.AsyncMock(
            return_value=True)
        mock_model.return_value = mock_model_instance

        # Execute
        result = await _perform_connectivity_check(
            "gpt-4-vision",
            "vlm",
            "https://api.openai.com",
            "test-key",
        )

        # Assert
        assert result is True
        mock_model.assert_called_once_with(
            mock_observer_instance,
            model_id="gpt-4-vision",
            api_base="https://api.openai.com",
            api_key="test-key",
            ssl_verify=True
        )
        mock_model_instance.check_connectivity.assert_called_once()


@pytest.mark.asyncio
async def test_perform_connectivity_check_dashscope_multimodal_uses_provider_catalog():
    model_provider_service = types.ModuleType("services.model_provider_service")
    model_provider_service.get_provider_models = mock.AsyncMock(return_value=[
        {"id": "qwen-image-max", "model_type": "vlm2"},
    ])

    with mock.patch.dict(sys.modules, {"services.model_provider_service": model_provider_service}), \
            mock.patch("backend.services.model_health_service.OpenAIVLModel") as mock_model:
        result = await _perform_connectivity_check(
            "qwen-image-max",
            "vlm2",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/",
            "test-key",
            model_factory="dashscope",
        )

    assert result is True
    model_provider_service.get_provider_models.assert_awaited_once_with({
        "provider": "dashscope",
        "model_type": "vlm2",
        "api_key": "test-key",
    })
    mock_model.assert_not_called()


@pytest.mark.asyncio
async def test_perform_connectivity_check_tokenpony_multimodal_catalog_error_returns_false():
    model_provider_service = types.ModuleType("services.model_provider_service")
    model_provider_service.get_provider_models = mock.AsyncMock(return_value=[
        {"_error": "authentication_failed", "_message": "Invalid API key"},
    ])

    with mock.patch.dict(sys.modules, {"services.model_provider_service": model_provider_service}):
        result = await _perform_connectivity_check(
            "qwen-vl-plus",
            "vlm3",
            "https://api.tokenpony.cn/v1/",
            "bad-key",
            model_factory="tokenpony",
        )

    assert result is False


@pytest.mark.asyncio
async def test_perform_connectivity_check_stt():
    # Setup
    with mock.patch("backend.services.model_health_service.get_voice_service") as mock_get_voice_service:
        mock_service_instance = mock.MagicMock()
        # Fix: make check_voice_connectivity return an awaitable coroutine instead of a bool
        async_mock = mock.AsyncMock()
        async_mock.return_value = True
        mock_service_instance.check_voice_connectivity = async_mock
        mock_get_voice_service.return_value = mock_service_instance

        # Execute
        result = await _perform_connectivity_check(
            "whisper-1",
            "stt",
            "https://api.openai.com",
            "test-key",
        )

        # Assert
        assert result is True
        mock_service_instance.check_voice_connectivity.assert_called_once_with(
            model_type="stt",
            stt_config={
                "api_key": "test-key",
                "base_url": "https://api.openai.com",
                "model": "whisper-1"
            }
        )


@pytest.mark.asyncio
async def test_perform_connectivity_check_rerank():
    # Setup - mock the rerank model
    with mock.patch("backend.services.model_health_service.OpenAICompatibleRerank") as mock_rerank:
        mock_rerank_instance = mock.MagicMock()
        mock_rerank_instance.connectivity_check = mock.AsyncMock(
            return_value=True)
        mock_rerank.return_value = mock_rerank_instance

        # Execute
        result = await _perform_connectivity_check(
            "rerank-model",
            "rerank",
            "https://api.example.com",
            "test-key",
        )

        # Assert
        assert result is True
        mock_rerank.assert_called_once_with(
            model_name="rerank-model",
            base_url="https://api.example.com",
            api_key="test-key",
            ssl_verify=True
        )
        mock_rerank_instance.connectivity_check.assert_called_once()


@pytest.mark.asyncio
async def test_perform_connectivity_check_base_url_normalization_localhost():
    # Setup
    with mock.patch("backend.services.model_health_service.MessageObserver") as mock_observer, \
            mock.patch("backend.services.model_health_service.OpenAIModel") as mock_model:
        mock_observer_instance = mock.MagicMock()
        mock_observer.return_value = mock_observer_instance

        mock_model_instance = mock.MagicMock()
        mock_model_instance.check_connectivity = mock.AsyncMock(
            return_value=True)
        mock_model.return_value = mock_model_instance

        # Execute with localhost which should be normalized
        result = await _perform_connectivity_check(
            "gpt-4",
            "llm",
            "http://localhost:8080",
            "test-key",
        )

        # Assert
        assert result is True
        # Ensure api_base has been normalized when calling the model
        mock_model.assert_called_once_with(
            mock_observer_instance,
            model_id="gpt-4",
            api_base="http://host.docker.internal:8080",
            api_key="test-key",
            ssl_verify=True,
            timeout_seconds=None,
        )


@pytest.mark.asyncio
async def test_perform_connectivity_check_base_url_normalization_127001():
    # Setup
    with mock.patch("backend.services.model_health_service.MessageObserver") as mock_observer, \
            mock.patch("backend.services.model_health_service.OpenAIModel") as mock_model:
        mock_observer_instance = mock.MagicMock()
        mock_observer.return_value = mock_observer_instance

        mock_model_instance = mock.MagicMock()
        mock_model_instance.check_connectivity = mock.AsyncMock(
            return_value=True)
        mock_model.return_value = mock_model_instance

        # Execute with 127.0.0.1 which should be normalized
        result = await _perform_connectivity_check(
            "gpt-4",
            "llm",
            "http://127.0.0.1:8000",
            "test-key",
        )

        # Assert
        assert result is True
        # Ensure api_base has been normalized when calling the model
        mock_model.assert_called_once_with(
            mock_observer_instance,
            model_id="gpt-4",
            api_base="http://host.docker.internal:8000",
            api_key="test-key",
            ssl_verify=True,
            timeout_seconds=None,
        )


@pytest.mark.asyncio
async def test_perform_connectivity_check_unsupported_type():
    # Execute and Assert
    with pytest.raises(ValueError) as excinfo:
        await _perform_connectivity_check(
            "unsupported-model",
            "unsupported_type",
            "https://api.example.com",
            "test-key",
        )

    assert "Unsupported model type" in str(excinfo.value)


@pytest.mark.asyncio
async def test_check_model_connectivity_success():
    # Setup
    with mock.patch("backend.services.model_health_service._perform_connectivity_check") as mock_connectivity_check, \
            mock.patch("backend.services.model_health_service.get_model_by_display_name") as mock_get_model, \
            mock.patch("backend.services.model_health_service.update_model_record") as mock_update_model, \
            mock.patch("backend.services.model_health_service.ModelConnectStatusEnum") as mock_enum:

        mock_enum.AVAILABLE.value = "available"
        mock_enum.UNAVAILABLE.value = "unavailable"
        mock_enum.DETECTING.value = "detecting"

        mock_get_model.return_value = {
            "model_id": "model123",
            "model_repo": "openai",
            "model_name": "gpt-4",
            "model_type": "llm",
            "base_url": "https://api.openai.com",
            "api_key": "test-key"
        }
        mock_connectivity_check.return_value = True

        # Execute
        response = await check_model_connectivity("GPT-4", "tenant456", "embedding")

        # Assert
        assert response["connectivity"] is True

        mock_get_model.assert_called_once_with("GPT-4", tenant_id="tenant456", model_type="embedding")
        # Detecting first, then available
        mock_update_model.assert_any_call(
            "model123", {"connect_status": "detecting"})
        mock_update_model.assert_any_call(
            "model123", {"connect_status": "available"})
        mock_connectivity_check.assert_called_once_with(
            "openai/gpt-4", "llm", "https://api.openai.com", "test-key", True,
            None, None, None, "GPT-4", None,
        )


@pytest.mark.asyncio
async def test_check_model_connectivity_model_not_found():
    # Setup
    with mock.patch("backend.services.model_health_service.get_model_by_display_name") as mock_get_model:

        mock_get_model.return_value = None

        # Execute & Assert
        with pytest.raises(LookupError):
            await check_model_connectivity("NonexistentModel", "tenant456", "embedding")


@pytest.mark.asyncio
async def test_check_model_connectivity_failure():
    # Setup
    with mock.patch("backend.services.model_health_service._perform_connectivity_check") as mock_connectivity_check, \
            mock.patch("backend.services.model_health_service.get_model_by_display_name") as mock_get_model, \
            mock.patch("backend.services.model_health_service.update_model_record") as mock_update_model, \
            mock.patch("backend.services.model_health_service.ModelConnectStatusEnum") as mock_enum:

        mock_enum.AVAILABLE.value = "available"
        mock_enum.UNAVAILABLE.value = "unavailable"
        mock_enum.DETECTING.value = "detecting"

        mock_get_model.return_value = {
            "model_id": "model123",
            "model_name": "gpt-4",
            "model_type": "llm",
            "base_url": "https://api.openai.com",
            "api_key": "test-key",
            "ssl_verify": False,  # Explicitly set to False to avoid fallback
        }
        mock_connectivity_check.return_value = False

        # Execute
        response = await check_model_connectivity("GPT-4", "tenant456")

        # Assert
        assert response["connectivity"] is False

        # Check that we updated the model status to unavailable
        mock_update_model.assert_any_call(
            "model123", {"connect_status": "unavailable"})


@pytest.mark.asyncio
async def test_check_model_connectivity_exception():
    # Setup
    with mock.patch("backend.services.model_health_service._perform_connectivity_check") as mock_connectivity_check, \
            mock.patch("backend.services.model_health_service.get_model_by_display_name") as mock_get_model, \
            mock.patch("backend.services.model_health_service.update_model_record") as mock_update_model, \
            mock.patch("backend.services.model_health_service.ModelConnectStatusEnum") as mock_enum:

        mock_enum.AVAILABLE.value = "available"
        mock_enum.UNAVAILABLE.value = "unavailable"
        mock_enum.DETECTING.value = "detecting"

        mock_get_model.return_value = {
            "model_id": "model123",
            "model_name": "gpt-4",
            "model_type": "llm",
            "base_url": "https://api.openai.com",
            "api_key": "test-key"
        }
        mock_connectivity_check.side_effect = ValueError(
            "Unsupported model type")

        # Execute & Assert
        with pytest.raises(ValueError):
            await check_model_connectivity("GPT-4", "tenant456")

        # Check that we updated the model status to unavailable
        mock_update_model.assert_any_call(
            "model123", {"connect_status": "unavailable"})


@pytest.mark.asyncio
async def test_check_model_connectivity_general_exception():
    # Setup
    with mock.patch("backend.services.model_health_service.get_model_by_display_name") as mock_get_model, \
            mock.patch("backend.services.model_health_service.update_model_record") as mock_update_model, \
            mock.patch("backend.services.model_health_service.ModelConnectStatusEnum") as mock_enum:

        mock_enum.AVAILABLE.value = "available"
        mock_enum.UNAVAILABLE.value = "unavailable"
        mock_enum.DETECTING.value = "detecting"

        mock_get_model.side_effect = Exception("Database error")

        # Execute & Assert
        with pytest.raises(Exception):
            await check_model_connectivity("GPT-4", "tenant456")

        # Should not update model record since we had an exception before getting to that point
        mock_update_model.assert_not_called()


@pytest.mark.asyncio
async def test_verify_model_config_connectivity_success():
    # Setup
    with mock.patch("backend.services.model_health_service._perform_connectivity_check") as mock_connectivity_check:

        mock_connectivity_check.return_value = True

        model_config = {
            "model_name": "gpt-4",
            "model_type": "llm",
            "base_url": "https://api.openai.com",
            "api_key": "test-key",
            "max_tokens": 2048
        }

        # Execute
        response = await verify_model_config_connectivity(model_config)

        # Assert
        assert response["connectivity"] is True
        assert response["model_name"] == "gpt-4"
        # Success case should not have error field
        assert "error" not in response

        mock_connectivity_check.assert_called_once_with(
            "gpt-4", "llm", "https://api.openai.com", "test-key", True,
            None, None, None, None, None,
        )


@pytest.mark.asyncio
async def test_verify_model_config_connectivity_failure():
    # Setup
    with mock.patch("backend.services.model_health_service._perform_connectivity_check") as mock_connectivity_check:

        mock_connectivity_check.return_value = False

        model_config = {
            "model_name": "gpt-4",
            "model_type": "llm",
            "base_url": "https://api.openai.com",
            "api_key": "test-key"
        }

        # Execute
        response = await verify_model_config_connectivity(model_config)

        # Assert
        assert response["connectivity"] is False
        assert response["model_name"] == "gpt-4"
        # Failure case should have error field with descriptive message
        assert "error" in response
        assert "Failed to connect to model" in response["error"]
        assert "gpt-4" in response["error"]


@pytest.mark.asyncio
async def test_verify_model_config_connectivity_validation_error():
    # Setup
    with mock.patch("backend.services.model_health_service._perform_connectivity_check") as mock_connectivity_check:

        mock_connectivity_check.side_effect = ValueError("Invalid model type")

        model_config = {
            "model_name": "invalid-model",
            "model_type": "invalid_type",
            "base_url": "https://api.example.com",
            "api_key": "test-key"
        }

        # Execute
        response = await verify_model_config_connectivity(model_config)

        # Assert
        assert response["connectivity"] is False
        assert response["model_name"] == "invalid-model"
        # Validation error should be included in error field
        assert "error" in response
        assert "Invalid model type" in response["error"]


@pytest.mark.asyncio
async def test_verify_model_config_connectivity_exception():
    # Setup
    with mock.patch("backend.services.model_health_service._perform_connectivity_check") as mock_connectivity_check:

        mock_connectivity_check.side_effect = Exception("Unexpected error")

        model_config = {
            "model_name": "gpt-4",
            "model_type": "llm",
            "base_url": "https://api.openai.com",
            "api_key": "test-key"
        }

        # Execute
        response = await verify_model_config_connectivity(model_config)

        # Assert
        assert response["connectivity"] is False
        assert response["model_name"] == "gpt-4"
        # Exception should be included in error field
        assert "error" in response
        assert "Connection verification failed" in response["error"]
        assert "Unexpected error" in response["error"]


@pytest.mark.asyncio
async def test_save_config_with_error():
    # This is the placeholder test function provided by the user
    pass


@pytest.mark.asyncio
async def test_embedding_dimension_check_embedding_success():
    with mock.patch("backend.services.model_health_service.OpenAICompatibleEmbedding") as mock_embedding:
        mock_embedding_instance = mock.MagicMock()
        mock_embedding_instance.dimension_check = mock.AsyncMock(
            return_value=[[0.1, 0.2, 0.3]])
        mock_embedding.return_value = mock_embedding_instance

        dimension = await _embedding_dimension_check(
            "test-embedding", "embedding", "http://test.com", "test-key"
        )
        assert dimension == 3
        mock_embedding.assert_called_once_with(
            model_name="test-embedding",
            base_url="http://test.com/embeddings",
            api_key="test-key",
            embedding_dim=0,
            ssl_verify=True,
        )


@pytest.mark.asyncio
async def test_embedding_dimension_check_multi_embedding_success():
    with mock.patch("backend.services.model_health_service.JinaEmbedding") as mock_embedding:
        mock_embedding_instance = mock.MagicMock()
        mock_embedding_instance.dimension_check = mock.AsyncMock(
            return_value=[[0.1, 0.2, 0.3, 0.4]])
        mock_embedding.return_value = mock_embedding_instance

        dimension = await _embedding_dimension_check(
            "test-multi-embedding", "multi_embedding", "http://test.com", "test-key"
        )
        assert dimension == 4
        mock_embedding.assert_called_once_with(
            api_key="test-key",
            base_url="http://test.com/embeddings",
            model_name="test-multi-embedding",
            embedding_dim=0,
            ssl_verify=True,
        )


@pytest.mark.asyncio
async def test_embedding_dimension_check_unsupported_type():
    with pytest.raises(ValueError):
        await _embedding_dimension_check(
            "test-model", "unsupported", "http://test.com", "test-key"
        )


@pytest.mark.asyncio
async def test_embedding_dimension_check_empty_return():
    with mock.patch("backend.services.model_health_service.OpenAICompatibleEmbedding") as mock_embedding:
        mock_embedding_instance = mock.MagicMock()
        mock_embedding_instance.dimension_check = mock.AsyncMock(
            return_value=[])
        mock_embedding.return_value = mock_embedding_instance

        dimension = await _embedding_dimension_check(
            "test-embedding", "embedding", "http://test.com", "test-key"
        )
        assert dimension == 0


@pytest.mark.asyncio
async def test_embedding_dimension_check_wrapper_success():
    with mock.patch("backend.services.model_health_service._embedding_dimension_check") as mock_internal_check, \
            mock.patch("backend.services.model_health_service.get_model_name_from_config") as mock_get_name:
        mock_internal_check.return_value = 1536
        mock_get_name.return_value = "openai/text-embedding-ada-002"
        model_config = {
            "model_repo": "openai",
            "model_name": "text-embedding-ada-002",
            "model_type": "embedding",
            "base_url": "https://api.openai.com",
            "api_key": "test-key"
        }
        dimension = await embedding_dimension_check(model_config)
        assert dimension == 1536
        mock_get_name.assert_called_once_with(model_config)
        mock_internal_check.assert_called_once_with(
            "openai/text-embedding-ada-002", "embedding", "https://api.openai.com", "test-key", True,
            model_factory=None, timeout_seconds=None
        )


@pytest.mark.asyncio
async def test_embedding_dimension_check_wrapper_exception():
    with mock.patch("backend.services.model_health_service._embedding_dimension_check") as mock_internal_check, \
            mock.patch("backend.services.model_health_service.get_model_name_from_config") as mock_get_name, \
            mock.patch("backend.services.model_health_service.logger") as mock_logger:
        mock_internal_check.side_effect = Exception("test error")
        mock_get_name.return_value = "openai/text-embedding-ada-002"
        model_config = {
            "model_repo": "openai",
            "model_name": "text-embedding-ada-002",
            "model_type": "embedding",
            "base_url": "https://api.openai.com",
            "api_key": "test-key"
        }
        dimension = await embedding_dimension_check(model_config)
        assert dimension is None
        mock_get_name.assert_called_once_with(model_config)
        mock_logger.error.assert_called_once()


@pytest.mark.asyncio
async def test_embedding_dimension_check_multi_embedding_empty_response():
    """Test multi_embedding dimension check with empty response (covers line 48-50)"""
    with mock.patch("backend.services.model_health_service.JinaEmbedding") as mock_embedding, \
            mock.patch("backend.services.model_health_service.logging") as mock_logging:
        mock_embedding_instance = mock.MagicMock()
        mock_embedding_instance.dimension_check = mock.AsyncMock(
            return_value=[])
        mock_embedding.return_value = mock_embedding_instance

        dimension = await _embedding_dimension_check(
            "test-multi-embedding", "multi_embedding", "http://test.com", "test-key"
        )

        assert dimension == 0
        mock_embedding.assert_called_once_with(
            api_key="test-key",
            base_url="http://test.com/embeddings",
            model_name="test-multi-embedding",
            embedding_dim=0,
            ssl_verify=True,
        )
        mock_logging.warning.assert_called_once()


@pytest.mark.asyncio
async def test_embedding_dimension_check_wrapper_value_error():
    """Test embedding_dimension_check wrapper with ValueError (covers line 249-250)"""
    with mock.patch("backend.services.model_health_service._embedding_dimension_check") as mock_internal_check, \
            mock.patch("backend.services.model_health_service.get_model_name_from_config") as mock_get_name, \
            mock.patch("backend.services.model_health_service.logger") as mock_logger:
        mock_internal_check.side_effect = ValueError("Unsupported model type")
        mock_get_name.return_value = "test-model"
        model_config = {
            "model_repo": "test",
            "model_name": "test-model",
            "model_type": "unsupported",
            "base_url": "https://api.test.com",
            "api_key": "test-key"
        }

        dimension = await embedding_dimension_check(model_config)

        assert dimension is None
        mock_get_name.assert_called_once_with(model_config)
        mock_internal_check.assert_called_once_with(
            "test-model", "unsupported", "https://api.test.com", "test-key", True,
            model_factory=None, timeout_seconds=None
        )
        # Verify error was logged with the specific ValueError message
        mock_logger.error.assert_called_once_with(
            "Error checking embedding dimension for test-model: Unsupported model type"
        )


@pytest.mark.asyncio
async def test_embedding_dimension_check_ssl_verify_fallback():
    """Test that embedding_dimension_check falls back to ssl_verify=False when first check returns 0"""
    with mock.patch("backend.services.model_health_service._embedding_dimension_check") as mock_internal_check, \
            mock.patch("backend.services.model_health_service.get_model_name_from_config") as mock_get_name:
        mock_internal_check.side_effect = [0, 1536]  # First call returns 0, second returns valid dimension
        mock_get_name.return_value = "openai/text-embedding-ada-002"
        model_config = {
            "model_repo": "openai",
            "model_name": "text-embedding-ada-002",
            "model_type": "embedding",
            "base_url": "https://api.openai.com",
            "api_key": "test-key",
            "ssl_verify": True,
        }
        dimension = await embedding_dimension_check(model_config)

        assert dimension == 1536
        mock_get_name.assert_called_once_with(model_config)
        # Should call twice: first with ssl_verify=True, then with ssl_verify=False
        assert mock_internal_check.call_count == 2
        mock_internal_check.assert_any_call(
            "openai/text-embedding-ada-002", "embedding", "https://api.openai.com", "test-key", True,
            model_factory=None, timeout_seconds=None
        )
        mock_internal_check.assert_any_call(
            "openai/text-embedding-ada-002", "embedding", "https://api.openai.com", "test-key", False,
            model_factory=None, timeout_seconds=None
        )


@pytest.mark.asyncio
async def test_embedding_dimension_check_ssl_verify_fallback_with_timeout():
    """Test that embedding_dimension_check passes timeout_seconds to fallback check"""
    with mock.patch("backend.services.model_health_service._embedding_dimension_check") as mock_internal_check, \
            mock.patch("backend.services.model_health_service.get_model_name_from_config") as mock_get_name:
        mock_internal_check.side_effect = [0, 768]  # First call fails, second returns valid dimension
        mock_get_name.return_value = "jina/jina-embeddings-v2-base-en"
        model_config = {
            "model_repo": "jina",
            "model_name": "jina-embeddings-v2-base-en",
            "model_type": "embedding",
            "base_url": "https://api.jina.ai",
            "api_key": "test-key",
            "ssl_verify": True,
            "timeout_seconds": 30.0,
        }
        dimension = await embedding_dimension_check(model_config)

        assert dimension == 768
        # Should call twice with timeout_seconds passed to both
        assert mock_internal_check.call_count == 2
        mock_internal_check.assert_any_call(
            "jina/jina-embeddings-v2-base-en", "embedding", "https://api.jina.ai", "test-key", True,
            model_factory=None, timeout_seconds=30.0
        )
        mock_internal_check.assert_any_call(
            "jina/jina-embeddings-v2-base-en", "embedding", "https://api.jina.ai", "test-key", False,
            model_factory=None, timeout_seconds=30.0
        )


@pytest.mark.asyncio
async def test_embedding_dimension_check_no_fallback_when_ssl_verify_false():
    """Test that no fallback occurs when ssl_verify is already False"""
    with mock.patch("backend.services.model_health_service._embedding_dimension_check") as mock_internal_check, \
            mock.patch("backend.services.model_health_service.get_model_name_from_config") as mock_get_name:
        mock_internal_check.return_value = 1024  # Returns valid dimension directly
        mock_get_name.return_value = "local/embedding-model"
        model_config = {
            "model_repo": "local",
            "model_name": "embedding-model",
            "model_type": "embedding",
            "base_url": "http://localhost:8080",
            "api_key": "",
            "ssl_verify": False,
        }
        dimension = await embedding_dimension_check(model_config)

        assert dimension == 1024
        # Should only call once since ssl_verify is already False
        assert mock_internal_check.call_count == 1
        mock_internal_check.assert_called_once_with(
            "local/embedding-model", "embedding", "http://localhost:8080", "", False,
            model_factory=None, timeout_seconds=None
        )


@pytest.mark.asyncio
async def test_embedding_dimension_check_fallback_still_fails():
    """Test that dimension returns 0 when both ssl_verify=True and ssl_verify=False fail"""
    with mock.patch("backend.services.model_health_service._embedding_dimension_check") as mock_internal_check, \
            mock.patch("backend.services.model_health_service.get_model_name_from_config") as mock_get_name:
        mock_internal_check.return_value = 0  # Both calls return 0
        mock_get_name.return_value = "unreachable/embedding-model"
        model_config = {
            "model_repo": "unreachable",
            "model_name": "embedding-model",
            "model_type": "embedding",
            "base_url": "https://unreachable.example.com",
            "api_key": "test-key",
            "ssl_verify": True,
        }
        dimension = await embedding_dimension_check(model_config)

        assert dimension is None
        # Should call twice (fallback) but still return 0
        assert mock_internal_check.call_count == 2


@pytest.mark.asyncio
async def test_perform_connectivity_check_llm_sets_monitoring_operation():
    with mock.patch("backend.services.model_health_service.MessageObserver") as mock_observer, \
            mock.patch("backend.services.model_health_service.OpenAIModel") as mock_model, \
            mock.patch("backend.services.model_health_service.set_monitoring_operation") as mock_set_op:
        mock_observer_instance = mock.MagicMock()
        mock_observer.return_value = mock_observer_instance

        mock_model_instance = mock.MagicMock()
        mock_model_instance.check_connectivity = mock.AsyncMock(
            return_value=True)
        mock_model.return_value = mock_model_instance

        await _perform_connectivity_check(
            "gpt-4", "llm", "https://api.openai.com", "test-key",
            display_name="GPT-4",
        )

        mock_set_op.assert_called_once_with(
            "connectivity_check", display_name="GPT-4"
        )


@pytest.mark.asyncio
async def test_perform_connectivity_check_vlm_sets_monitoring_operation():
    with mock.patch("backend.services.model_health_service.MessageObserver") as mock_observer, \
            mock.patch("backend.services.model_health_service.OpenAIVLModel") as mock_model, \
            mock.patch("backend.services.model_health_service.set_monitoring_operation") as mock_set_op:
        mock_observer_instance = mock.MagicMock()
        mock_observer.return_value = mock_observer_instance

        mock_model_instance = mock.MagicMock()
        mock_model_instance.check_connectivity = mock.AsyncMock(
            return_value=True)
        mock_model.return_value = mock_model_instance

        await _perform_connectivity_check(
            "gpt-4-vision", "vlm", "https://api.openai.com", "test-key",
            display_name="Vision",
        )

        mock_set_op.assert_called_once_with(
            "connectivity_check", display_name="Vision"
        )


@pytest.mark.asyncio
async def test_check_model_connectivity_sets_monitoring_context():
    with mock.patch("backend.services.model_health_service.get_model_by_display_name") as mock_get_model, \
            mock.patch("backend.services.model_health_service.update_model_record"), \
            mock.patch("backend.services.model_health_service._perform_connectivity_check",
                       new=mock.AsyncMock(return_value=True)), \
            mock.patch("backend.services.model_health_service.set_monitoring_context") as mock_set_ctx:
        mock_get_model.return_value = {
            "model_id": 1, "model_repo": "openai", "model_name": "gpt-4",
            "model_type": "llm", "base_url": "https://api.openai.com",
            "api_key": "test-key", "ssl_verify": True,
        }

        await check_model_connectivity("GPT-4", tenant_id="t-42")

        mock_set_ctx.assert_called_once_with(tenant_id="t-42")


@pytest.mark.asyncio
async def test_normalize_embedding_url_already_has_suffix():
    """L34: _normalize_embedding_url returns early when URL already ends with /embeddings"""
    with mock.patch("backend.services.model_health_service.OpenAICompatibleEmbedding") as mock_embedding:
        mock_embedding_instance = mock.MagicMock()
        mock_embedding_instance.dimension_check = mock.AsyncMock(return_value=[[0.1, 0.2]])
        mock_embedding.return_value = mock_embedding_instance

        result = await _perform_connectivity_check(
            "text-embedding-ada-002",
            "embedding",
            "https://api.openai.com/v1/embeddings",
            "test-key",
        )
        assert result is True
        mock_embedding.assert_called_once_with(
            model_name="text-embedding-ada-002",
            base_url="https://api.openai.com/v1/embeddings",
            api_key="test-key",
            embedding_dim=0,
            ssl_verify=True,
        )


@pytest.mark.asyncio
async def test_infer_model_factory_dashscope():
    """L47: _infer_model_factory returns DASHSCOPE_MODEL_FACTORY for dashscope URLs"""
    from backend.services.model_health_service import _infer_model_factory
    result = _infer_model_factory("embedding", "https://dashscope.aliyuncs.com/v1/", None)
    assert result == "dashscope"


@pytest.mark.asyncio
async def test_perform_connectivity_check_multi_embedding_dashscope():
    """L181: multi_embedding with model_factory=dasScope uses DashScopeMultimodalEmbedding"""
    with mock.patch("backend.services.model_health_service.DashScopeMultimodalEmbedding") as mock_dashscope:
        mock_instance = mock.MagicMock()
        mock_instance.dimension_check = mock.AsyncMock(return_value=[[0.1, 0.2, 0.3]])
        mock_dashscope.return_value = mock_instance

        result = await _perform_connectivity_check(
            "text-embedding-3-large",
            "multi_embedding",
            "https://dashscope.aliyuncs.com/v1/",
            "test-key",
            model_factory="dashscope",
        )
        assert result is True
        mock_dashscope.assert_called_once()


@pytest.mark.asyncio
async def test_perform_connectivity_check_stt_volc():
    """L249: STT with volcengine factory uses appid/access_token path"""
    with mock.patch("backend.services.model_health_service.get_voice_service") as mock_get_voice_service:
        mock_service_instance = mock.MagicMock()
        async_mock = mock.AsyncMock(return_value=True)
        mock_service_instance.check_voice_connectivity = async_mock
        mock_get_voice_service.return_value = mock_service_instance

        result = await _perform_connectivity_check(
            "some-stt-model", "stt", "https://volc.example.com", "test-key",
            model_factory="volcengine", model_appid="app-123", access_token="tok-456",
        )

        assert result is True
        mock_service_instance.check_voice_connectivity.assert_called_once_with(
            model_type="stt",
            stt_config={
                "model_factory": "volcengine",
                "model_appid": "app-123",
                "access_token": "tok-456",
                "base_url": "https://volc.example.com",
            }
        )


@pytest.mark.asyncio
async def test_perform_connectivity_check_tts_success():
    """L268-294: TTS connectivity check with Ali TTS (default)"""
    with mock.patch("backend.services.model_health_service.get_voice_service") as mock_get_voice_service:
        mock_service_instance = mock.MagicMock()
        async_mock = mock.AsyncMock(return_value=True)
        mock_service_instance.check_voice_connectivity = async_mock
        mock_get_voice_service.return_value = mock_service_instance

        result = await _perform_connectivity_check(
            "some-tts-model", "tts", "https://api.openai.com", "test-key",
        )

        assert result is True
        mock_service_instance.check_voice_connectivity.assert_called_once_with(
            model_type="tts",
            stt_config={
                "api_key": "test-key",
                "base_url": "https://api.openai.com",
                "model": "some-tts-model",
            }
        )


@pytest.mark.asyncio
async def test_perform_connectivity_check_tts_volc():
    """L274-284: TTS with volcengine factory uses appid/access_token path"""
    with mock.patch("backend.services.model_health_service.get_voice_service") as mock_get_voice_service:
        mock_service_instance = mock.MagicMock()
        async_mock = mock.AsyncMock(return_value=True)
        mock_service_instance.check_voice_connectivity = async_mock
        mock_get_voice_service.return_value = mock_service_instance

        result = await _perform_connectivity_check(
            "some-tts-model", "tts", "https://volc.example.com", "test-key",
            model_factory="volcengine", model_appid="app-123", access_token="tok-456",
        )

        assert result is True
        mock_service_instance.check_voice_connectivity.assert_called_once_with(
            model_type="tts",
            stt_config={
                "model_factory": "volcengine",
                "model_appid": "app-123",
                "access_token": "tok-456",
                "base_url": "https://volc.example.com",
            }
        )


@pytest.mark.asyncio
async def test_provider_catalog_connectivity_check_unknown_factory():
    """L117: _provider_catalog_connectivity_check returns False for unknown factory"""
    from backend.services.model_health_service import _provider_catalog_connectivity_check
    result = await _provider_catalog_connectivity_check(
        "some-model", "vlm", "test-key", model_factory="unknown_provider",
    )
    assert result is False


@pytest.mark.asyncio
async def test_check_model_connectivity_ssl_verify_fallback():
    """L334-335, L355: ssl_verify_fallback triggers second connectivity check with ssl_verify=False"""
    with mock.patch("backend.services.model_health_service.get_model_by_display_name") as mock_get_model, \
            mock.patch("backend.services.model_health_service.update_model_record") as mock_update, \
            mock.patch("backend.services.model_health_service.ModelConnectStatusEnum") as mock_enum, \
            mock.patch("backend.services.model_health_service._perform_connectivity_check") as mock_connectivity:

        mock_enum.AVAILABLE.value = "available"
        mock_enum.UNAVAILABLE.value = "unavailable"
        mock_enum.DETECTING.value = "detecting"

        mock_get_model.return_value = {
            "model_id": "model123",
            "model_repo": "openai",
            "model_name": "gpt-4",
            "model_type": "llm",
            "base_url": "https://api.openai.com",
            "api_key": "test-key",
            "ssl_verify": True,
        }
        # First call fails, second succeeds
        mock_connectivity.side_effect = [False, True]

        result = await check_model_connectivity("GPT-4", "tenant456")

        assert result["connectivity"] is True
        assert mock_connectivity.call_count == 2
        # First call with ssl_verify=True
        mock_connectivity.assert_any_call(
            "openai/gpt-4", "llm", "https://api.openai.com", "test-key", True,
            None, None, None, "GPT-4", None,
        )
        # Second call with ssl_verify=False (fallback)
        mock_connectivity.assert_any_call(
            "openai/gpt-4", "llm", "https://api.openai.com", "test-key", False,
            None, None, None, "GPT-4", None,
        )
        # Verify ssl_verify=False was saved to the record
        mock_update.assert_any_call("model123", {"connect_status": "available", "ssl_verify": False})


@pytest.mark.asyncio
async def test_embedding_dimension_check_multi_embedding_dashscope():
    """L83: _embedding_dimension_check uses DashScopeMultimodalEmbedding for dashscope factory"""
    with mock.patch("backend.services.model_health_service.DashScopeMultimodalEmbedding") as mock_dashscope:
        mock_instance = mock.MagicMock()
        mock_instance.dimension_check = mock.AsyncMock(return_value=[[0.1, 0.2, 0.3, 0.4]])
        mock_dashscope.return_value = mock_instance

        dimension = await _embedding_dimension_check(
            "text-embedding-v2", "multi_embedding",
            "https://dashscope.aliyuncs.com/v1/", "test-key",
            model_factory="dashscope",
        )

        assert dimension == 4
        mock_dashscope.assert_called_once()
        mock_instance.dimension_check.assert_called_once()


@pytest.mark.asyncio
async def test_verify_model_config_connectivity_ssl_verify_fallback():
    """verify_model_config_connectivity falls back to ssl_verify=False on failure"""
    with mock.patch("backend.services.model_health_service._perform_connectivity_check") as mock_connectivity:
        # First call fails, second succeeds
        mock_connectivity.side_effect = [False, True]

        model_config = {
            "model_name": "gpt-4",
            "model_type": "llm",
            "base_url": "https://api.openai.com",
            "api_key": "test-key",
            "ssl_verify": True,
        }

        result = await verify_model_config_connectivity(model_config)

        assert result["connectivity"] is True
        assert mock_connectivity.call_count == 2
        mock_connectivity.assert_any_call(
            "gpt-4", "llm", "https://api.openai.com", "test-key", True,
            None, None, None, None, None,
        )
        mock_connectivity.assert_any_call(
            "gpt-4", "llm", "https://api.openai.com", "test-key", False,
            None, None, None, None, None,
        )
