import sys
from unittest import mock
import pytest

# Create proper mock modules with proper structure
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
sys.modules['consts'] = MockModule()
sys.modules['consts.model'] = MockModule()
sys.modules['consts.const'] = MockModule()

# Mock nexent packages and modules with proper hierarchy
sys.modules['nexent'] = MockModule()
sys.modules['nexent.core'] = MockModule()
sys.modules['nexent.core.agents'] = MockModule()
sys.modules['nexent.core.agents.agent_model'] = MockModule()
sys.modules['nexent.core.models'] = MockModule()
sys.modules['nexent.core.models.embedding_model'] = MockModule()
sys.modules['nexent.core.models.restful_llm'] = MockModule()
sys.modules['nexent.core.utils'] = MockModule()

# Mock apps packages
sys.modules['apps'] = MockModule()
sys.modules['apps.voice_app'] = MockModule()

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
    check_me_model_connectivity,
    verify_model_config_connectivity,
    _embedding_dimension_check,
    embedding_dimension_check,
)

# Mock imported functions/classes after import
import httpx
from fastapi import Header

# Apply patch before importing the module to be tested
with mock.patch.dict('sys.modules', {
    'nexent': mock.MagicMock(),
    'nexent.core': mock.MagicMock(),
    'nexent.core.agents': mock.MagicMock(),
    'nexent.core.agents.agent_model': mock.MagicMock(),
    'nexent.core.models': mock.MagicMock(),
    'nexent.core.models.embedding_model': mock.MagicMock(),
    'nexent.core.models.restful_llm': mock.MagicMock(),
    'nexent.core.utils': mock.MagicMock(),
    'database': mock.MagicMock(),
    'database.client': mock.MagicMock(), 
    'database.model_management_db': mock.MagicMock(),
    'utils': mock.MagicMock(),
    'utils.auth_utils': mock.MagicMock(),
    'utils.config_utils': mock.MagicMock(),
    'apps': mock.MagicMock(),
    'apps.voice_app': mock.MagicMock(),
    'consts.model': mock.MagicMock(),
    'consts.const': mock.MagicMock()
}):
    # Define the mocked enums and classes
    mock_model_enum = mock.MagicMock()
    mock_model_enum.AVAILABLE = "available"
    mock_model_enum.UNAVAILABLE = "unavailable"
    mock_model_enum.DETECTING = "detecting"
    mock.patch('consts.model.ModelConnectStatusEnum', mock_model_enum)
    
    # Mock MessageObserver
    mock_message_observer = mock.MagicMock()
    mock.patch('nexent.core.MessageObserver', mock_message_observer)

    # Now import the module under test
    from backend.services.model_health_service import (
        _perform_connectivity_check,
        check_model_connectivity,
        check_me_model_connectivity,
        verify_model_config_connectivity,
        _embedding_dimension_check,
        embedding_dimension_check,
    )

@pytest.mark.asyncio
async def test_perform_connectivity_check_embedding():
    # Setup
    with mock.patch("backend.services.model_health_service.OpenAICompatibleEmbedding") as mock_embedding:
        mock_embedding_instance = mock.MagicMock()
        mock_embedding_instance.dimension_check.return_value = [1]
        mock_embedding.return_value = mock_embedding_instance

        # Execute
        result = await _perform_connectivity_check(
            "text-embedding-ada-002", 
            "embedding", 
            "https://api.openai.com", 
            "test-key",
            1536
        )

        # Assert
        assert result is True
        mock_embedding.assert_called_once_with(
            model_name="text-embedding-ada-002",
            base_url="https://api.openai.com",
            api_key="test-key",
            embedding_dim=1536
        )
        mock_embedding_instance.dimension_check.assert_called_once()

@pytest.mark.asyncio
async def test_perform_connectivity_check_multi_embedding():
    # Setup
    with mock.patch("backend.services.model_health_service.JinaEmbedding") as mock_embedding:
        mock_embedding_instance = mock.MagicMock()
        mock_embedding_instance.dimension_check.return_value = [1]
        mock_embedding.return_value = mock_embedding_instance

        # Execute
        result = await _perform_connectivity_check(
            "jina-embeddings-v2", 
            "multi_embedding", 
            "https://api.jina.ai", 
            "test-key",
            1024
        )

        # Assert
        assert result is True
        mock_embedding.assert_called_once_with(
            model_name="jina-embeddings-v2",
            base_url="https://api.jina.ai",
            api_key="test-key",
            embedding_dim=1024
        )
        mock_embedding_instance.dimension_check.assert_called_once()

@pytest.mark.asyncio
async def test_perform_connectivity_check_llm():
    # Setup
    with mock.patch("backend.services.model_health_service.MessageObserver") as mock_observer, \
         mock.patch("backend.services.model_health_service.OpenAIModel") as mock_model, \
         mock.patch("backend.services.model_health_service.get_model_factory_type") as mock_factory_type:
        mock_observer_instance = mock.MagicMock()
        mock_observer.return_value = mock_observer_instance
        
        mock_model_instance = mock.MagicMock()
        mock_model_instance.check_connectivity.return_value = True
        mock_model.return_value = mock_model_instance

        mock_factory_type.return_value = "openai"

        # Execute
        result = await _perform_connectivity_check(
            "gpt-4", 
            "llm", 
            "https://api.openai.com", 
            "test-key"
        )

        # Assert
        assert result is True
        mock_factory_type.assert_called_once_with("https://api.openai.com")
        mock_model.assert_called_once_with(
            observer=mock_observer_instance,
            model_id="gpt-4",
            api_base="https://api.openai.com",
            api_key="test-key"
        )
        mock_model_instance.check_connectivity.assert_called_once()

@pytest.mark.asyncio
async def test_perform_connectivity_check_llm_restful():
    # Setup
    with mock.patch("backend.services.model_health_service.MessageObserver") as mock_observer, \
         mock.patch("backend.services.model_health_service.RestfulLLMModel") as mock_model, \
         mock.patch("backend.services.model_health_service.get_model_factory_type") as mock_factory_type:
        mock_observer_instance = mock.MagicMock()
        mock_observer.return_value = mock_observer_instance

        mock_model_instance = mock.MagicMock()
        mock_model_instance.check_connectivity.return_value = True
        mock_model.return_value = mock_model_instance

        mock_factory_type.return_value = "restful"

        # Execute
        result = await _perform_connectivity_check(
            "gpt-4",
            "llm",
            "https://api.openai.com",
            "test-key"
        )

        # Assert
        assert result is True
        mock_factory_type.assert_called_once_with("https://api.openai.com")
        mock_model.assert_called_once_with(
            observer=mock_observer_instance,
            base_url="https://api.openai.com",
            api_key="test-key",
            model_name="gpt-4"
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
        mock_model_instance.check_connectivity.return_value = True
        mock_model.return_value = mock_model_instance

        # Execute
        result = await _perform_connectivity_check(
            "gpt-4-vision", 
            "vlm", 
            "https://api.openai.com", 
            "test-key"
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
    with mock.patch("backend.services.model_health_service.VoiceService") as mock_voice_service:
        mock_service_instance = mock.MagicMock()
        # Fix: make check_connectivity return an awaitable coroutine instead of a bool
        async_mock = mock.AsyncMock()
        async_mock.return_value = True
        mock_service_instance.check_connectivity = async_mock
        mock_voice_service.return_value = mock_service_instance

        # Execute
        result = await _perform_connectivity_check(
            "tts-1", 
            "tts", 
            "https://api.openai.com", 
            "test-key"
        )

        # Assert
        assert result is True
        mock_service_instance.check_connectivity.assert_called_once_with("tts")

@pytest.mark.asyncio
async def test_perform_connectivity_check_stt():
    # Setup
    with mock.patch("backend.services.model_health_service.VoiceService") as mock_voice_service:
        mock_service_instance = mock.MagicMock()
        # Fix: make check_connectivity return an awaitable coroutine instead of a bool
        async_mock = mock.AsyncMock()
        async_mock.return_value = True
        mock_service_instance.check_connectivity = async_mock
        mock_voice_service.return_value = mock_service_instance

        # Execute
        result = await _perform_connectivity_check(
            "whisper-1", 
            "stt", 
            "https://api.openai.com", 
            "test-key"
        )

        # Assert
        assert result is True
        mock_service_instance.check_connectivity.assert_called_once_with("stt")

@pytest.mark.asyncio
async def test_perform_connectivity_check_rerank():
    # Execute
    result = await _perform_connectivity_check(
        "rerank-model", 
        "rerank", 
        "https://api.example.com", 
        "test-key"
    )

    # Assert
    assert result is False

@pytest.mark.asyncio
async def test_perform_connectivity_check_unsupported_type():
    # Execute and Assert
    with pytest.raises(ValueError) as excinfo:
        await _perform_connectivity_check(
            "unsupported-model", 
            "unsupported_type", 
            "https://api.example.com", 
            "test-key"
        )
    
    assert "Unsupported model type" in str(excinfo.value)

@pytest.mark.asyncio
async def test_check_model_connectivity_success():
    # Setup
    with mock.patch("backend.services.model_health_service._perform_connectivity_check") as mock_connectivity_check, \
         mock.patch("backend.services.model_health_service.get_current_user_id") as mock_get_user_id, \
         mock.patch("backend.services.model_health_service.get_model_by_display_name") as mock_get_model, \
         mock.patch("backend.services.model_health_service.update_model_record") as mock_update_model, \
         mock.patch("backend.services.model_health_service.ModelConnectStatusEnum") as mock_enum, \
         mock.patch("backend.services.model_health_service.ModelResponse", side_effect=ModelResponse) as mock_response:
        
        mock_enum.AVAILABLE.value = "available"
        mock_enum.UNAVAILABLE.value = "unavailable"
        mock_enum.DETECTING.value = "detecting"
        
        mock_get_user_id.return_value = ("user123", "tenant456")
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
        response = await check_model_connectivity("GPT-4", "Bearer test-token")

        # Assert
        assert response.code == 200
        assert response.data["connectivity"] is True
        assert response.data["connect_status"] == "available"
        
        mock_get_user_id.assert_called_once_with("Bearer test-token")
        mock_get_model.assert_called_once_with("GPT-4", tenant_id="tenant456")
        mock_update_model.assert_called_with("model123", {"connect_status": "available"})
        mock_connectivity_check.assert_called_once_with(
            "openai/gpt-4", "llm", "https://api.openai.com", "test-key"
        )

@pytest.mark.asyncio
async def test_check_model_connectivity_model_not_found():
    # Setup
    with mock.patch("backend.services.model_health_service.get_current_user_id") as mock_get_user_id, \
         mock.patch("backend.services.model_health_service.get_model_by_display_name") as mock_get_model, \
         mock.patch("backend.services.model_health_service.ModelResponse", side_effect=ModelResponse) as mock_response:
        
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_get_model.return_value = None

        # Execute
        response = await check_model_connectivity("NonexistentModel", "Bearer test-token")

        # Assert
        assert response.code == 404
        assert response.data["connectivity"] is False
        assert response.data["connect_status"] == "Not Found"

@pytest.mark.asyncio
async def test_check_model_connectivity_failure():
    # Setup
    with mock.patch("backend.services.model_health_service._perform_connectivity_check") as mock_connectivity_check, \
         mock.patch("backend.services.model_health_service.get_current_user_id") as mock_get_user_id, \
         mock.patch("backend.services.model_health_service.get_model_by_display_name") as mock_get_model, \
         mock.patch("backend.services.model_health_service.update_model_record") as mock_update_model, \
         mock.patch("backend.services.model_health_service.ModelConnectStatusEnum") as mock_enum, \
         mock.patch("backend.services.model_health_service.ModelResponse", side_effect=ModelResponse) as mock_response:
        
        mock_enum.AVAILABLE.value = "available"
        mock_enum.UNAVAILABLE.value = "unavailable"
        mock_enum.DETECTING.value = "detecting"
        
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_get_model.return_value = {
            "model_id": "model123",
            "model_name": "gpt-4",
            "model_type": "llm",
            "base_url": "https://api.openai.com",
            "api_key": "test-key"
        }
        mock_connectivity_check.return_value = False

        # Execute
        response = await check_model_connectivity("GPT-4", "Bearer test-token")

        # Assert
        assert response.code == 200
        assert response.data["connectivity"] is False
        assert response.data["connect_status"] == "unavailable"
        
        # Check that we updated the model status to unavailable
        mock_update_model.assert_called_with("model123", {"connect_status": "unavailable"})

@pytest.mark.asyncio
async def test_check_model_connectivity_exception():
    # Setup
    with mock.patch("backend.services.model_health_service._perform_connectivity_check") as mock_connectivity_check, \
         mock.patch("backend.services.model_health_service.get_current_user_id") as mock_get_user_id, \
         mock.patch("backend.services.model_health_service.get_model_by_display_name") as mock_get_model, \
         mock.patch("backend.services.model_health_service.update_model_record") as mock_update_model, \
         mock.patch("backend.services.model_health_service.ModelConnectStatusEnum") as mock_enum, \
         mock.patch("backend.services.model_health_service.ModelResponse", side_effect=ModelResponse) as mock_response:
        
        mock_enum.AVAILABLE.value = "available"
        mock_enum.UNAVAILABLE.value = "unavailable"
        mock_enum.DETECTING.value = "detecting"
        
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_get_model.return_value = {
            "model_id": "model123",
            "model_name": "gpt-4",
            "model_type": "llm",
            "base_url": "https://api.openai.com",
            "api_key": "test-key"
        }
        mock_connectivity_check.side_effect = ValueError("Unsupported model type")

        # Execute
        response = await check_model_connectivity("GPT-4", "Bearer test-token")

        # Assert
        assert response.code == 400
        assert response.data["connectivity"] is False
        assert response.data["connect_status"] == "unavailable"
        
        # Check that we updated the model status to unavailable
        mock_update_model.assert_called_with("model123", {"connect_status": "unavailable"})

@pytest.mark.asyncio
async def test_check_model_connectivity_general_exception():
    # Setup
    with mock.patch("backend.services.model_health_service.get_current_user_id") as mock_get_user_id, \
         mock.patch("backend.services.model_health_service.get_model_by_display_name") as mock_get_model, \
         mock.patch("backend.services.model_health_service.update_model_record") as mock_update_model, \
         mock.patch("backend.services.model_health_service.ModelConnectStatusEnum") as mock_enum, \
         mock.patch("backend.services.model_health_service.ModelResponse", side_effect=ModelResponse) as mock_response:
        
        mock_enum.AVAILABLE.value = "available"
        mock_enum.UNAVAILABLE.value = "unavailable"
        mock_enum.DETECTING.value = "detecting"
        
        mock_get_user_id.return_value = ("user123", "tenant456")
        mock_get_model.side_effect = Exception("Database error")

        # Execute
        response = await check_model_connectivity("GPT-4", "Bearer test-token")

        # Assert
        assert response.code == 500
        assert response.data["connectivity"] is False
        assert response.data["connect_status"] == "unavailable"
        
        # Should not update model record since we had an exception before getting to that point
        mock_update_model.assert_not_called()

@pytest.mark.asyncio
async def test_check_me_model_connectivity_llm_success():
    # Setup
    with mock.patch("backend.services.model_health_service.httpx.AsyncClient") as mock_client, \
         mock.patch("backend.services.model_health_service.MODEL_ENGINE_APIKEY", "me-api-key"), \
         mock.patch("backend.services.model_health_service.MODEL_ENGINE_HOST", "https://me-host.com"), \
         mock.patch("backend.services.model_health_service.ModelConnectStatusEnum") as mock_enum, \
         mock.patch("backend.services.model_health_service.ModelResponse", side_effect=ModelResponse) as mock_response:
        
        mock_enum.AVAILABLE.value = "available"
        mock_enum.UNAVAILABLE.value = "unavailable"
        
        mock_client_instance = mock.AsyncMock()
        mock_client.return_value.__aenter__.return_value = mock_client_instance
        
        # Mock first API call to get models
        mock_models_response = mock.Mock()
        mock_models_response.status_code = 200
        mock_models_response.json.return_value = {
            "data": [
                {"id": "gpt-4", "type": "llm"},
                {"id": "text-embedding-ada-002", "type": "embedding"}
            ]
        }
        mock_client_instance.get.return_value = mock_models_response
        
        # Mock second API call to test model
        mock_test_response = mock.Mock()
        mock_test_response.status_code = 200
        mock_test_response.text = "Success"
        mock_client_instance.post.return_value = mock_test_response

        # Execute
        response = await check_me_model_connectivity("gpt-4")

        # Assert
        assert response.code == 200
        assert response.data["connectivity"] is True
        assert response.data["connect_status"] == "available"
        
        # Verify API calls
        mock_client_instance.get.assert_called_once_with(
            "https://me-host.com/open/router/v1/models", 
            headers={"Authorization": "Bearer me-api-key"}
        )
        mock_client_instance.post.assert_called_once_with(
            "https://me-host.com/open/router/v1/chat/completions",
            headers={"Authorization": "Bearer me-api-key"},
            json={"model": "gpt-4", "messages": [{"role": "user", "content": "hello"}]}
        )

@pytest.mark.asyncio
async def test_check_me_model_connectivity_embedding_success():
    # Setup
    with mock.patch("backend.services.model_health_service.httpx.AsyncClient") as mock_client, \
         mock.patch("backend.services.model_health_service.MODEL_ENGINE_APIKEY", "me-api-key"), \
         mock.patch("backend.services.model_health_service.MODEL_ENGINE_HOST", "https://me-host.com"), \
         mock.patch("backend.services.model_health_service.ModelConnectStatusEnum") as mock_enum, \
         mock.patch("backend.services.model_health_service.ModelResponse", side_effect=ModelResponse) as mock_response:
        
        mock_enum.AVAILABLE.value = "available"
        mock_enum.UNAVAILABLE.value = "unavailable"
        
        mock_client_instance = mock.AsyncMock()
        mock_client.return_value.__aenter__.return_value = mock_client_instance
        
        # Mock first API call to get models
        mock_models_response = mock.Mock()
        mock_models_response.status_code = 200
        mock_models_response.json.return_value = {
            "data": [
                {"id": "gpt-4", "type": "llm"},
                {"id": "text-embedding-ada-002", "type": "embedding"}
            ]
        }
        mock_client_instance.get.return_value = mock_models_response
        
        # Mock second API call to test model
        mock_test_response = mock.Mock()
        mock_test_response.status_code = 200
        mock_test_response.text = "Success"
        mock_client_instance.post.return_value = mock_test_response

        # Execute
        response = await check_me_model_connectivity("text-embedding-ada-002")

        # Assert
        assert response.code == 200
        assert response.data["connectivity"] is True
        assert response.data["connect_status"] == "available"
        
        # Verify API calls
        mock_client_instance.get.assert_called_once_with(
            "https://me-host.com/open/router/v1/models", 
            headers={"Authorization": "Bearer me-api-key"}
        )
        mock_client_instance.post.assert_called_once_with(
            "https://me-host.com/open/router/v1/embeddings",
            headers={"Authorization": "Bearer me-api-key"},
            json={"model": "text-embedding-ada-002", "input": "Hello"}
        )

@pytest.mark.asyncio
async def test_check_me_model_connectivity_model_not_found():
    # Setup
    with mock.patch("backend.services.model_health_service.httpx.AsyncClient") as mock_client, \
         mock.patch("backend.services.model_health_service.MODEL_ENGINE_APIKEY", "me-api-key"), \
         mock.patch("backend.services.model_health_service.MODEL_ENGINE_HOST", "https://me-host.com"), \
         mock.patch("backend.services.model_health_service.ModelResponse", side_effect=ModelResponse) as mock_response:
        
        mock_client_instance = mock.AsyncMock()
        mock_client.return_value.__aenter__.return_value = mock_client_instance
        
        # Mock API call to get models
        mock_response_obj = mock.Mock()
        mock_response_obj.status_code = 200
        mock_response_obj.json.return_value = {
            "data": [
                {"id": "gpt-4", "type": "llm"}
            ]
        }
        mock_client_instance.get.return_value = mock_response_obj

        # Execute
        response = await check_me_model_connectivity("nonexistent-model")

        # Assert
        assert response.code == 404
        assert response.data["connectivity"] is False
        assert response.data["message"] == "Specified model not found"

@pytest.mark.asyncio
async def test_check_me_model_connectivity_unsupported_type():
    # Setup
    with mock.patch("backend.services.model_health_service.httpx.AsyncClient") as mock_client, \
         mock.patch("backend.services.model_health_service.MODEL_ENGINE_APIKEY", "me-api-key"), \
         mock.patch("backend.services.model_health_service.MODEL_ENGINE_HOST", "https://me-host.com"), \
         mock.patch("backend.services.model_health_service.ModelConnectStatusEnum") as mock_enum, \
         mock.patch("backend.services.model_health_service.ModelResponse", side_effect=ModelResponse) as mock_response:
        
        mock_enum.UNAVAILABLE.value = "unavailable"
        
        mock_client_instance = mock.AsyncMock()
        mock_client.return_value.__aenter__.return_value = mock_client_instance
        
        # Mock API call to get models
        mock_response_obj = mock.Mock()
        mock_response_obj.status_code = 200
        mock_response_obj.json.return_value = {
            "data": [
                {"id": "unsupported-model", "type": "unsupported"}
            ]
        }
        mock_client_instance.get.return_value = mock_response_obj

        # Execute
        response = await check_me_model_connectivity("unsupported-model")

        # Assert
        assert response.code == 400
        assert response.data["connectivity"] is False
        assert response.data["connect_status"] == "unavailable"
        assert "Health check not supported" in response.data["message"]

@pytest.mark.asyncio
async def test_check_me_model_connectivity_api_error():
    # Setup
    with mock.patch("backend.services.model_health_service.httpx.AsyncClient") as mock_client, \
         mock.patch("backend.services.model_health_service.MODEL_ENGINE_APIKEY", "me-api-key"), \
         mock.patch("backend.services.model_health_service.MODEL_ENGINE_HOST", "https://me-host.com"), \
         mock.patch("backend.services.model_health_service.ModelConnectStatusEnum") as mock_enum, \
         mock.patch("backend.services.model_health_service.ModelResponse", side_effect=ModelResponse) as mock_response:
        
        mock_enum.UNAVAILABLE.value = "unavailable"
        
        mock_client_instance = mock.AsyncMock()
        mock_client.return_value.__aenter__.return_value = mock_client_instance
        
        # Mock first API call to get models
        mock_models_response = mock.Mock()
        mock_models_response.status_code = 200
        mock_models_response.json.return_value = {
            "data": [
                {"id": "gpt-4", "type": "llm"}
            ]
        }
        mock_client_instance.get.return_value = mock_models_response
        
        # Mock second API call to fail
        mock_test_response = mock.Mock()
        mock_test_response.status_code = 500
        mock_test_response.text = "Internal Server Error"
        mock_client_instance.post.return_value = mock_test_response

        # Execute
        response = await check_me_model_connectivity("gpt-4")

        # Assert
        assert response.code == 500
        assert response.data["connectivity"] is False
        assert response.data["connect_status"] == "unavailable"
        assert "response failed" in response.data["message"]

@pytest.mark.asyncio
async def test_check_me_model_connectivity_exception():
    # Setup
    with mock.patch("backend.services.model_health_service.httpx.AsyncClient") as mock_client, \
         mock.patch("backend.services.model_health_service.MODEL_ENGINE_APIKEY", "me-api-key"), \
         mock.patch("backend.services.model_health_service.MODEL_ENGINE_HOST", "https://me-host.com"), \
         mock.patch("backend.services.model_health_service.ModelConnectStatusEnum") as mock_enum, \
         mock.patch("backend.services.model_health_service.ModelResponse", side_effect=ModelResponse) as mock_response:
        
        mock_enum.UNAVAILABLE.value = "unavailable"
        
        mock_client.return_value.__aenter__.side_effect = Exception("Connection error")

        # Execute
        response = await check_me_model_connectivity("gpt-4")

        # Assert
        assert response.code == 500
        assert response.data["connectivity"] is False
        assert response.data["connect_status"] == "unavailable"
        assert "Unknown error" in response.data["message"]

@pytest.mark.asyncio
async def test_verify_model_config_connectivity_success():
    # Setup
    with mock.patch("backend.services.model_health_service._perform_connectivity_check") as mock_connectivity_check, \
         mock.patch("backend.services.model_health_service.ModelConnectStatusEnum") as mock_enum, \
         mock.patch("backend.services.model_health_service.ModelResponse", side_effect=ModelResponse) as mock_response:
        
        mock_enum.AVAILABLE.value = "available"
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
        assert response.code == 200
        assert response.data["connectivity"] is True
        assert response.data["connect_status"] == "available"
        assert response.data["error_code"] == "MODEL_VALIDATION_SUCCESS"
        
        mock_connectivity_check.assert_called_once_with(
            "gpt-4", "llm", "https://api.openai.com", "test-key", 2048
        )

@pytest.mark.asyncio
async def test_verify_model_config_connectivity_failure():
    # Setup
    with mock.patch("backend.services.model_health_service._perform_connectivity_check") as mock_connectivity_check, \
         mock.patch("backend.services.model_health_service.ModelConnectStatusEnum") as mock_enum, \
         mock.patch("backend.services.model_health_service.ModelResponse", side_effect=ModelResponse) as mock_response:
        
        mock_enum.UNAVAILABLE.value = "unavailable"
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
        assert response.code == 200
        assert response.data["connectivity"] is False
        assert response.data["connect_status"] == "unavailable"
        assert response.data["error_code"] == "MODEL_VALIDATION_FAILED"

@pytest.mark.asyncio
async def test_verify_model_config_connectivity_validation_error():
    # Setup
    with mock.patch("backend.services.model_health_service._perform_connectivity_check") as mock_connectivity_check, \
         mock.patch("backend.services.model_health_service.ModelConnectStatusEnum") as mock_enum, \
         mock.patch("backend.services.model_health_service.ModelResponse", side_effect=ModelResponse) as mock_response:
        
        mock_enum.UNAVAILABLE.value = "unavailable"
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
        assert response.code == 400
        assert response.data["connectivity"] is False
        assert response.data["connect_status"] == "unavailable"
        assert response.data["error_code"] == "MODEL_VALIDATION_ERROR"
        assert response.data["message"] == "Invalid model type"

@pytest.mark.asyncio
async def test_verify_model_config_connectivity_exception():
    # Setup
    with mock.patch("backend.services.model_health_service._perform_connectivity_check") as mock_connectivity_check, \
         mock.patch("backend.services.model_health_service.ModelConnectStatusEnum") as mock_enum, \
         mock.patch("backend.services.model_health_service.ModelResponse", side_effect=ModelResponse) as mock_response:
        
        mock_enum.UNAVAILABLE.value = "unavailable"
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
        assert response.code == 500
        assert response.data["connectivity"] is False
        assert response.data["connect_status"] == "unavailable"
        assert response.data["error_code"] == "MODEL_VALIDATION_ERROR_UNKNOWN"
        assert response.data["error_details"] == "Unexpected error"

@pytest.mark.asyncio
async def test_save_config_with_error():
    # This is the placeholder test function provided by the user
    pass

@pytest.mark.asyncio
async def test_embedding_dimension_check_embedding_success():
    with mock.patch("backend.services.model_health_service.OpenAICompatibleEmbedding") as mock_embedding:
        mock_embedding_instance = mock.MagicMock()
        mock_embedding_instance.dimension_check.return_value = [[0.1, 0.2, 0.3]]
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
        mock_embedding_instance.dimension_check.return_value = [[0.1, 0.2, 0.3, 0.4]]
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
    dimension = await _embedding_dimension_check(
        "test-model", "unsupported", "http://test.com", "test-key"
    )
    assert dimension == 0

@pytest.mark.asyncio
async def test_embedding_dimension_check_empty_return():
    with mock.patch("backend.services.model_health_service.OpenAICompatibleEmbedding") as mock_embedding:
        mock_embedding_instance = mock.MagicMock()
        mock_embedding_instance.dimension_check.return_value = []
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
        mock_logger.warning.assert_called_once()
