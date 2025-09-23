from consts.exceptions import TimeoutException
import asyncio
import os
import sys
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
sys.modules['utils.model_name_utils'] = MockModule()

# Mock nexent packages and modules with proper hierarchy
sys.modules['nexent'] = MockModule()
sys.modules['nexent.core'] = MockModule()
sys.modules['nexent.core.agents'] = MockModule()
sys.modules['nexent.core.agents.agent_model'] = MockModule()
sys.modules['nexent.core.models'] = MockModule()
sys.modules['nexent.core.models.embedding_model'] = MockModule()

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
try:
    from backend.services.model_health_service import (
        _perform_connectivity_check,
        check_model_connectivity,
        verify_model_config_connectivity,
        _embedding_dimension_check,
        embedding_dimension_check,
    )
except ImportError:
    from backend.services.model_health_service import (
        _perform_connectivity_check,
        check_model_connectivity,
        verify_model_config_connectivity,
        _embedding_dimension_check,
        embedding_dimension_check,
    )

# Mock imported functions/classes after import

# Apply patch before importing the module to be tested
with mock.patch.dict('sys.modules', {
    'nexent': mock.MagicMock(),
    'nexent.core': mock.MagicMock(),
    'nexent.core.agents': mock.MagicMock(),
    'nexent.core.agents.agent_model': mock.MagicMock(),
    'nexent.core.models': mock.MagicMock(),
    'nexent.core.models.embedding_model': mock.MagicMock(),
    'database': mock.MagicMock(),
    'database.client': mock.MagicMock(),
    'database.model_management_db': mock.MagicMock(),
    'utils': mock.MagicMock(),
    'utils.auth_utils': mock.MagicMock(),
    'utils.config_utils': mock.MagicMock(),
    'utils.model_name_utils': mock.MagicMock(),
    'services': mock.MagicMock(),
    'services.voice_service': mock.MagicMock(),
    'consts.model': mock.MagicMock(),
    'consts.const': mock.MagicMock(),
    'consts.provider': mock.MagicMock()
}):
    # Define the mocked enums and classes
    mock_model_enum = mock.MagicMock()
    mock_model_enum.AVAILABLE = "available"
    mock_model_enum.UNAVAILABLE = "unavailable"
    mock_model_enum.DETECTING = "detecting"
    mock.patch('consts.model.ModelConnectStatusEnum', mock_model_enum)

    # Now import the module under test (wrapped with fallback for optional symbols)
    try:
        from backend.services.model_health_service import (
            _perform_connectivity_check,
            check_model_connectivity,
            verify_model_config_connectivity,
            _embedding_dimension_check,
            embedding_dimension_check,
        )
    except ImportError:
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
                                                                 1])
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
            base_url="https://api.openai.com",
            api_key="test-key",
            embedding_dim=0
        )
        mock_embedding_instance.dimension_check.assert_called_once()


@pytest.mark.asyncio
async def test_perform_connectivity_check_multi_embedding():
    # Setup
    with mock.patch("backend.services.model_health_service.JinaEmbedding") as mock_embedding:
        mock_embedding_instance = mock.MagicMock()
        mock_embedding_instance.dimension_check = mock.AsyncMock(return_value=[
                                                                 1])
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
            model_name="jina-embeddings-v2",
            base_url="https://api.jina.ai",
            api_key="test-key",
            embedding_dim=0
        )
        mock_embedding_instance.dimension_check.assert_called_once()


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
            api_key="test-key"
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
            api_key="test-key"
        )
        mock_model_instance.check_connectivity.assert_called_once()


@pytest.mark.asyncio
async def test_perform_connectivity_check_tts():
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
            "tts-1",
            "tts",
            "https://api.openai.com",
            "test-key",
        )

        # Assert
        assert result is True
        mock_service_instance.check_voice_connectivity.assert_called_once_with("tts")


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
        mock_service_instance.check_voice_connectivity.assert_called_once_with("stt")


@pytest.mark.asyncio
async def test_perform_connectivity_check_rerank():
    # Execute
    result = await _perform_connectivity_check(
        "rerank-model",
        "rerank",
        "https://api.example.com",
        "test-key",
    )

    # Assert
    assert result is False


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
            api_key="test-key"
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
            api_key="test-key"
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
        response = await check_model_connectivity("GPT-4", "tenant456")

        # Assert
        assert response["connectivity"] is True

        mock_get_model.assert_called_once_with("GPT-4", tenant_id="tenant456")
        # Detecting first, then available
        mock_update_model.assert_any_call(
            "model123", {"connect_status": "detecting"})
        mock_update_model.assert_any_call(
            "model123", {"connect_status": "available"})
        mock_connectivity_check.assert_called_once_with(
            "openai/gpt-4", "llm", "https://api.openai.com", "test-key"
        )


@pytest.mark.asyncio
async def test_check_model_connectivity_model_not_found():
    # Setup
    with mock.patch("backend.services.model_health_service.get_model_by_display_name") as mock_get_model:

        mock_get_model.return_value = None

        # Execute & Assert
        with pytest.raises(LookupError):
            await check_model_connectivity("NonexistentModel", "tenant456")


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
            "api_key": "test-key"
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

        mock_connectivity_check.assert_called_once_with(
            "gpt-4", "llm", "https://api.openai.com", "test-key"
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
            base_url="http://test.com",
            api_key="test-key",
            embedding_dim=0
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
            model_name="test-multi-embedding",
            base_url="http://test.com",
            api_key="test-key",
            embedding_dim=0
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
            "openai/text-embedding-ada-002", "embedding", "https://api.openai.com", "test-key"
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
        assert dimension == 0
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
            model_name="test-multi-embedding",
            base_url="http://test.com",
            api_key="test-key",
            embedding_dim=0
        )
        # Verify warning was logged
        mock_logging.warning.assert_called_once_with(
            "Embedding dimension check for test-multi-embedding gets empty response"
        )


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

        assert dimension == 0
        mock_get_name.assert_called_once_with(model_config)
        mock_internal_check.assert_called_once_with(
            "test-model", "unsupported", "https://api.test.com", "test-key"
        )
        # Verify error was logged with the specific ValueError message
        mock_logger.error.assert_called_once_with(
            "Error checking embedding dimension: Unsupported model type"
        )


@pytest.mark.asyncio
async def test_check_me_connectivity_impl_success():
    """Test successful ME connectivity check"""
    # Setup
    with mock.patch("backend.services.model_health_service.MODEL_ENGINE_APIKEY", "me-api-key"), \
            mock.patch("backend.services.model_health_service.MODEL_ENGINE_HOST", "https://me-host.com"), \
            mock.patch("backend.services.model_health_service.ModelConnectStatusEnum") as mock_enum, \
            mock.patch("backend.services.model_health_service.aiohttp.ClientSession") as mock_session_class:

        mock_enum.AVAILABLE.value = "available"
        mock_enum.UNAVAILABLE.value = "unavailable"

        # Create mock response
        mock_response = mock.AsyncMock()
        mock_response.status = 200

        # Create mock session
        mock_session = mock.AsyncMock()
        mock_get = mock.AsyncMock()
        mock_get.__aenter__.return_value = mock_response
        mock_session.get = mock.MagicMock(return_value=mock_get)

        # Create mock session factory
        mock_client_session = mock.AsyncMock()
        mock_client_session.__aenter__.return_value = mock_session
        mock_session_class.return_value = mock_client_session

        # Import the function after mocking
        from backend.services.model_health_service import check_me_connectivity_impl

        # Execute - the function should return None on success or raise an exception
        result = await check_me_connectivity_impl(timeout=30)

        # Assert - should return None on success
        assert result is None


@pytest.mark.asyncio
async def test_check_me_connectivity_impl_http_error():
    """Test ME connectivity check with HTTP error response"""
    # Setup
    with mock.patch("backend.services.model_health_service.MODEL_ENGINE_APIKEY", "me-api-key"), \
            mock.patch("backend.services.model_health_service.MODEL_ENGINE_HOST", "https://me-host.com"), \
            mock.patch("backend.services.model_health_service.ModelConnectStatusEnum") as mock_enum, \
            mock.patch("backend.services.model_health_service.aiohttp.ClientSession") as mock_session_class:

        mock_enum.AVAILABLE.value = "available"
        mock_enum.UNAVAILABLE.value = "unavailable"

        # Create mock response with error status
        mock_response = mock.AsyncMock()
        mock_response.status = 500

        # Create mock session
        mock_session = mock.AsyncMock()
        mock_get = mock.AsyncMock()
        mock_get.__aenter__.return_value = mock_response
        mock_session.get = mock.MagicMock(return_value=mock_get)

        # Create mock session factory
        mock_client_session = mock.AsyncMock()
        mock_client_session.__aenter__.return_value = mock_session
        mock_session_class.return_value = mock_client_session

        # Import the function after mocking
        from backend.services.model_health_service import check_me_connectivity_impl

        # Execute and expect an exception
        with pytest.raises(Exception) as exc_info:
            await check_me_connectivity_impl(timeout=30)

        # Assert the exception message
        assert "Unknown error occurred: Connection failed, error code: 500" in str(
            exc_info.value)


@pytest.mark.asyncio
async def test_check_me_connectivity_impl_timeout():
    """Test ME connectivity check with timeout error"""
    # Setup
    with mock.patch("backend.services.model_health_service.MODEL_ENGINE_APIKEY", "me-api-key"), \
            mock.patch("backend.services.model_health_service.MODEL_ENGINE_HOST", "https://me-host.com"), \
            mock.patch("backend.services.model_health_service.ModelConnectStatusEnum") as mock_enum, \
            mock.patch("backend.services.model_health_service.aiohttp.ClientSession") as mock_session_class:

        mock_enum.AVAILABLE.value = "available"
        mock_enum.UNAVAILABLE.value = "unavailable"

        # Create mock session that raises TimeoutError
        mock_session = mock.AsyncMock()
        mock_get = mock.AsyncMock()
        mock_get.__aenter__.side_effect = asyncio.TimeoutError()
        mock_session.get = mock.MagicMock(return_value=mock_get)

        # Create mock session factory
        mock_client_session = mock.AsyncMock()
        mock_client_session.__aenter__.return_value = mock_session
        mock_session_class.return_value = mock_client_session

        # Import the function after mocking
        from backend.services.model_health_service import check_me_connectivity_impl

        # Execute and expect a TimeoutException
        with pytest.raises(TimeoutException) as exc_info:
            await check_me_connectivity_impl(timeout=30)

        # Assert the exception message
        assert "Connection timed out" in str(exc_info.value)


@pytest.mark.asyncio
async def test_check_me_connectivity_impl_exception():
    """Test ME connectivity check with general exception"""
    # Setup
    with mock.patch("backend.services.model_health_service.MODEL_ENGINE_APIKEY", "me-api-key"), \
            mock.patch("backend.services.model_health_service.MODEL_ENGINE_HOST", "https://me-host.com"), \
            mock.patch("backend.services.model_health_service.ModelConnectStatusEnum") as mock_enum, \
            mock.patch("backend.services.model_health_service.aiohttp.ClientSession") as mock_session_class:

        mock_enum.AVAILABLE.value = "available"
        mock_enum.UNAVAILABLE.value = "unavailable"

        # Create mock session that raises general exception
        mock_session = mock.AsyncMock()
        mock_get = mock.AsyncMock()
        mock_get.__aenter__.side_effect = Exception("Connection error")
        mock_session.get = mock.MagicMock(return_value=mock_get)

        # Create mock session factory
        mock_client_session = mock.AsyncMock()
        mock_client_session.__aenter__.return_value = mock_session
        mock_session_class.return_value = mock_client_session

        # Import the function after mocking
        from backend.services.model_health_service import check_me_connectivity_impl

        # Execute and expect an Exception
        with pytest.raises(Exception) as exc_info:
            await check_me_connectivity_impl(timeout=30)

        # Assert the exception message
        assert "Unknown error occurred: Connection error" in str(
            exc_info.value)
