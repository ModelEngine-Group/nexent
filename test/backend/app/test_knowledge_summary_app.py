import pytest
import json
import sys
import os
from unittest.mock import patch, MagicMock, AsyncMock

# Add path for correct imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

# Mock external dependencies
sys.modules['boto3'] = MagicMock()
sys.modules['botocore'] = MagicMock()
sys.modules['botocore.client'] = MagicMock()
sys.modules['botocore.exceptions'] = MagicMock()
sys.modules['nexent'] = MagicMock()
sys.modules['nexent.core'] = MagicMock()
sys.modules['nexent.core.agents'] = MagicMock()
sys.modules['nexent.core.agents.agent_model'] = MagicMock()
sys.modules['nexent.core.models'] = MagicMock()
sys.modules['nexent.core.models.embedding_model'] = MagicMock()
sys.modules['nexent.core.models.stt_model'] = MagicMock()
sys.modules['nexent.core.models.tts_model'] = MagicMock()
sys.modules['nexent.core.nlp'] = MagicMock()
sys.modules['nexent.core.nlp.tokenizer'] = MagicMock()
sys.modules['nexent.vector_database'] = MagicMock()
sys.modules['nexent.vector_database.elasticsearch_core'] = MagicMock()

# Mock specific classes that are imported
class MockToolConfig:
    def __init__(self, *args, **kwargs): pass
class MockBaseEmbedding:
    def __init__(self, *args, **kwargs): pass
class MockOpenAICompatibleEmbedding:
    def __init__(self, *args, **kwargs): pass
class MockJinaEmbedding:
    def __init__(self, *args, **kwargs): pass
class MockTokenizer:
    def __init__(self, *args, **kwargs): pass
class MockSTTConfig:
    def __init__(self, *args, **kwargs): pass
class MockSTTModel:
    def __init__(self, *args, **kwargs): pass
class MockTTSConfig:
    def __init__(self, *args, **kwargs): pass
class MockTTSModel:
    def __init__(self, *args, **kwargs): pass

sys.modules['nexent.core.agents.agent_model'].ToolConfig = MockToolConfig
sys.modules['nexent.core.models.embedding_model'].BaseEmbedding = MockBaseEmbedding
sys.modules['nexent.core.models.embedding_model'].OpenAICompatibleEmbedding = MockOpenAICompatibleEmbedding
sys.modules['nexent.core.models.embedding_model'].JinaEmbedding = MockJinaEmbedding
sys.modules['nexent.core.nlp.tokenizer'].Tokenizer = MockTokenizer
sys.modules['nexent.core.models.stt_model'].STTConfig = MockSTTConfig
sys.modules['nexent.core.models.stt_model'].STTModel = MockSTTModel
sys.modules['nexent.core.models.tts_model'].TTSConfig = MockTTSConfig
sys.modules['nexent.core.models.tts_model'].TTSModel = MockTTSModel

# Import the modules we need with all dependencies mocked
with patch('botocore.client.BaseClient._make_api_call'), \
     patch('database.client.MinioClient', MagicMock()), \
     patch('elasticsearch.Elasticsearch', return_value=MagicMock()), \
     patch('database.client.db_client', MagicMock()), \
     patch('database.client.get_db_session', MagicMock()), \
     patch('database.client.as_dict', MagicMock()):
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from pydantic import BaseModel
    from apps.knowledge_summary_app import router

# Define test models
class ChangeSummaryRequest(BaseModel):
    summary_result: str

# Create test app and client
app = FastAPI()
app.include_router(router)
client = TestClient(app)

# Fixture for test setup
@pytest.fixture
def test_data():
    # Sample test data
    data = {
        "index_name": "test_index",
        "user_id": ("test_user_id", "test_tenant_id"),
        "user_info": ("test_user_id", "test_tenant_id", "en"),
        "summary_result": "This is a test summary for the knowledge base",
        "auth_header": {"Authorization": "Bearer test_token"}
    }
    return data

def test_auto_summary_success(test_data):
    """Test successful auto summary generation"""
    # Setup mock responses
    mock_es_core_instance = MagicMock()
    mock_user_info = ("test_user_id", "test_tenant_id", "en")
    
    # Setup service mock
    mock_service_instance = MagicMock()
    mock_service_instance.summary_index_name = AsyncMock()
    stream_response = MagicMock()
    mock_service_instance.summary_index_name.return_value = stream_response

    # Patch all necessary components directly in the app module
    with patch('apps.knowledge_summary_app.ElasticSearchService', return_value=mock_service_instance), \
         patch('apps.knowledge_summary_app.get_es_core', return_value=mock_es_core_instance), \
         patch('apps.knowledge_summary_app.get_current_user_info', return_value=mock_user_info):
        
        # Execute test with model_id parameter
        response = client.post(
            f"/summary/{test_data['index_name']}/auto_summary?batch_size=500&model_id=1",
            headers=test_data["auth_header"]
        )

        # Assertions - verify the function was called exactly once
        assert mock_service_instance.summary_index_name.call_count == 1
        
        # Extract the call arguments to verify expected values without comparing object identity
        call_kwargs = mock_service_instance.summary_index_name.call_args.kwargs
        assert call_kwargs['index_name'] == test_data['index_name']
        assert call_kwargs['batch_size'] == 500
        assert call_kwargs['tenant_id'] == mock_user_info[1]
        assert call_kwargs['language'] == mock_user_info[2]
        assert call_kwargs['model_id'] == 1

def test_auto_summary_without_model_id(test_data):
    """Test successful auto summary generation without model_id parameter"""
    # Setup mock responses
    mock_es_core_instance = MagicMock()
    mock_user_info = ("test_user_id", "test_tenant_id", "en")
    
    # Setup service mock
    mock_service_instance = MagicMock()
    mock_service_instance.summary_index_name = AsyncMock()
    stream_response = MagicMock()
    mock_service_instance.summary_index_name.return_value = stream_response

    # Patch all necessary components directly in the app module
    with patch('apps.knowledge_summary_app.ElasticSearchService', return_value=mock_service_instance), \
         patch('apps.knowledge_summary_app.get_es_core', return_value=mock_es_core_instance), \
         patch('apps.knowledge_summary_app.get_current_user_info', return_value=mock_user_info):
        
        # Execute test without model_id parameter
        response = client.post(
            f"/summary/{test_data['index_name']}/auto_summary?batch_size=500",
            headers=test_data["auth_header"]
        )

        # Assertions - verify the function was called exactly once
        assert mock_service_instance.summary_index_name.call_count == 1
        
        # Extract the call arguments to verify expected values without comparing object identity
        call_kwargs = mock_service_instance.summary_index_name.call_args.kwargs
        assert call_kwargs['index_name'] == test_data['index_name']
        assert call_kwargs['batch_size'] == 500
        assert call_kwargs['tenant_id'] == mock_user_info[1]
        assert call_kwargs['language'] == mock_user_info[2]
        assert call_kwargs['model_id'] is None

def test_auto_summary_exception(test_data):
    """Test auto summary generation with exception"""
    # Setup mock to raise exception
    mock_es_core_instance = MagicMock()
    mock_user_info = ("test_user_id", "test_tenant_id", "en")
    
    # Setup service mock to raise exception
    mock_service_instance = MagicMock()
    mock_service_instance.summary_index_name = AsyncMock(
        side_effect=Exception("Error generating summary")
    )

    # Patch both the ElasticSearchService and get_es_core in the route handler
    with patch('apps.knowledge_summary_app.ElasticSearchService', return_value=mock_service_instance), \
         patch('apps.knowledge_summary_app.get_es_core', return_value=mock_es_core_instance), \
         patch('apps.knowledge_summary_app.get_current_user_info', return_value=mock_user_info):
        
        # Execute test
        response = client.post(
            f"/summary/{test_data['index_name']}/auto_summary",
            headers=test_data["auth_header"]
        )

        # Assertions
        assert response.status_code == 500
        assert "text/event-stream" in response.headers["content-type"]
        assert "Knowledge base summary generation failed" in response.text

def test_change_summary_success(test_data):
    """Test successful summary update"""
    # Setup request data using a dictionary that conforms to ChangeSummaryRequest model
    request_data = {
        "summary_result": test_data["summary_result"]
    }

    # Ensure we return a dictionary instead of a MagicMock object
    expected_response = {
        "success": True,
        "index_name": test_data["index_name"],
        "summary": test_data["summary_result"]
    }

    # Setup service mock
    mock_service_instance = MagicMock()
    mock_service_instance.change_summary.return_value = expected_response

    # Execute test with direct patching of route handler function
    with patch('apps.knowledge_summary_app.ElasticSearchService', return_value=mock_service_instance), \
         patch('apps.knowledge_summary_app.get_current_user_id', return_value=test_data["user_id"]):
        
        response = client.post(
            f"/summary/{test_data['index_name']}/summary",
            json=request_data,
            headers=test_data["auth_header"]
        )

    # Assertions
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["success"] is True
    assert response_json["index_name"] == test_data["index_name"]
    assert response_json["summary"] == test_data["summary_result"]

    # Verify service calls
    mock_service_instance.change_summary.assert_called_once_with(
        index_name=test_data["index_name"],
        summary_result=test_data["summary_result"],
        user_id=test_data["user_id"][0]
    )

def test_change_summary_exception(test_data):
    """Test summary update with exception"""
    # Setup request data
    request_data = {
        "summary_result": test_data["summary_result"]
    }

    # Setup service mock to raise exception
    mock_service_instance = MagicMock()
    mock_service_instance.change_summary.side_effect = Exception("Error updating summary")

    # Execute test
    with patch('apps.knowledge_summary_app.ElasticSearchService', return_value=mock_service_instance), \
         patch('apps.knowledge_summary_app.get_current_user_id', return_value=test_data["user_id"]):
        
        response = client.post(
            f"/summary/{test_data['index_name']}/summary",
            json=request_data,
            headers=test_data["auth_header"]
        )

    # Assertions
    assert response.status_code == 500
    assert "Knowledge base summary update failed" in response.json()["detail"]

def test_get_summary_success(test_data):
    """Test successful summary retrieval"""
    # Ensure we return a dictionary instead of a MagicMock object
    expected_response = {
        "success": True,
        "index_name": test_data["index_name"],
        "summary": test_data["summary_result"]
    }

    # Setup service mock
    mock_service_instance = MagicMock()
    mock_service_instance.get_summary.return_value = expected_response

    with patch('apps.knowledge_summary_app.ElasticSearchService', return_value=mock_service_instance):
        # Execute test
        response = client.get(f"/summary/{test_data['index_name']}/summary")

    # Assertions
    assert response.status_code == 200
    assert response.json() == expected_response

    # Verify service calls
    mock_service_instance.get_summary.assert_called_once_with(
        index_name=test_data["index_name"]
    )

def test_get_summary_exception(test_data):
    """Test summary retrieval with exception"""
    # Setup service mock to raise exception
    mock_service_instance = MagicMock()
    mock_service_instance.get_summary.side_effect = Exception("Error getting summary")

    with patch('apps.knowledge_summary_app.ElasticSearchService', return_value=mock_service_instance):
        # Execute test
        response = client.get(f"/summary/{test_data['index_name']}/summary")

    # Assertions
    assert response.status_code == 500
    assert "Failed to get knowledge base summary" in response.json()["detail"]