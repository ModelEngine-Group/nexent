import sys
import os
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from http import HTTPStatus

# Add path for correct imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))


@pytest.fixture(scope="function")
def client(mocker):
    """Create test client with mocked dependencies."""
    # Mock boto3 and MinioClient before importing
    mocker.patch('boto3.client')
    # Patch MinioClient at both possible import paths
    mocker.patch('backend.database.client.MinioClient')
    # Stub services.elasticsearch_service to avoid real ES initialization
    import types
    import sys as _sys
    if "services.elasticsearch_service" not in _sys.modules:
        services_es_mod = types.ModuleType("services.elasticsearch_service")

        def _get_es_core():  # minimal stub
            return object()

        services_es_mod.get_es_core = _get_es_core
        _sys.modules["services.elasticsearch_service"] = services_es_mod
    
    # Import after mocking (only backend path is required by app imports)
    from apps.model_managment_app import router
    
    # Create test client
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# Test fixtures
@pytest.fixture
def auth_header():
    """Provide test authorization header."""
    return {"Authorization": "Bearer test_token"}


@pytest.fixture
def user_credentials():
    """Provide test user credentials."""
    return "test_user", "test_tenant"


@pytest.fixture
def sample_model_data():
    """Provide sample model data for testing."""
    return {
        "model_name": "huggingface/llama",
        "display_name": "Test Model",
        "base_url": "http://localhost:8000",
        "api_key": "test_key",
        "model_type": "llm",
        "provider": "huggingface"
    }


# Tests for /model/create endpoint
@pytest.mark.asyncio
async def test_create_model_success(client, auth_header, user_credentials, sample_model_data, mocker):
    """Test successful model creation."""
    mocker.patch('apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    async def _create(*args, **kwargs):
        return None
    
    mock_create = mocker.patch('apps.model_managment_app.create_model_for_tenant', side_effect=_create)
    
    response = client.post(
        "/model/create", json=sample_model_data, headers=auth_header)
    
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert "Model created successfully" in data.get("message", "")
    mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_create_model_conflict(client, auth_header, user_credentials, sample_model_data, mocker):
    """Test model creation with name conflict."""
    mocker.patch('apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    mock_create = mocker.patch(
        'apps.model_managment_app.create_model_for_tenant', 
        side_effect=ValueError("Name conflict")
    )
    
    response = client.post(
        "/model/create", json=sample_model_data, headers=auth_header)
    
    assert response.status_code == HTTPStatus.CONFLICT
    data = response.json()
    assert "Failed to create model: name conflict" in data.get("detail", "")
    mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_create_model_exception(client, auth_header, user_credentials, sample_model_data, mocker):
    """Test model creation with internal error."""
    mocker.patch('apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    mock_create = mocker.patch(
        'apps.model_managment_app.create_model_for_tenant', 
        side_effect=Exception("DB failure")
    )
    
    response = client.post(
        "/model/create", json=sample_model_data, headers=auth_header)
    
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    data = response.json()
    assert "Failed to create model" in data.get("detail", "")
    mock_create.assert_called_once()


# Tests for /model/provider/create endpoint
@pytest.mark.asyncio
async def test_create_provider_model_success(client, auth_header, user_credentials, mocker):
    """Test successful provider model creation."""
    mocker.patch('apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    mock_get = mocker.patch(
        'apps.model_managment_app.create_provider_models_for_tenant', 
        return_value=[{"id": "A1"}, {"id": "a0"}, {"id": "b2"}, {"id": "c3"}]
    )
    
    # Fix: Add required model_type field
    request_data = {"provider": "silicon", "model_type": "llm", "api_key": "test_key"}
    response = client.post(
        "/model/provider/create", json=request_data, headers=auth_header)
    
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert "Provider model created successfully" in data["message"]
    # Check that models are sorted by first letter in ascending order
    assert [m["id"] for m in data["data"]] == ["A1", "a0", "b2", "c3"]
    mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_create_provider_model_exception(client, auth_header, user_credentials, mocker):
    """Test provider model creation with exception."""
    mocker.patch('apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    mock_get = mocker.patch(
        'apps.model_managment_app.create_provider_models_for_tenant', 
        side_effect=Exception("Provider API error")
    )
    
    # Fix: Add required model_type field
    request_data = {"provider": "silicon", "model_type": "llm", "api_key": "test_key"}
    response = client.post(
        "/model/provider/create", json=request_data, headers=auth_header)
    
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    data = response.json()
    assert "Failed to create provider model" in data.get("detail", "")
    mock_get.assert_called_once()


# Tests for /model/provider/batch_create endpoint
@pytest.mark.asyncio
async def test_provider_batch_create_success(client, auth_header, user_credentials, mocker):
    """Test successful batch model creation."""
    mocker.patch('apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    async def _batch(*args, **kwargs):
        return None
    
    mock_batch = mocker.patch('apps.model_managment_app.batch_create_models_for_tenant', side_effect=_batch)
    
    payload = {
        "models": [{"id": "prov/modelA"}],
        "provider": "prov",
        "type": "llm",
        "api_key": "k",
    }
    response = client.post(
        "/model/provider/batch_create", json=payload, headers=auth_header)
    
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert "Batch create models successfully" in data.get("message", "")
    mock_batch.assert_called_once()


@pytest.mark.asyncio
async def test_provider_batch_create_exception(client, auth_header, user_credentials, mocker):
    """Test batch model creation with exception."""
    mocker.patch('apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    mock_batch = mocker.patch(
        'apps.model_managment_app.batch_create_models_for_tenant', 
        side_effect=Exception("boom")
    )
    
    payload = {
        "models": [{"id": "prov/modelA"}],
        "provider": "prov",
        "type": "llm",
        "api_key": "k",
    }
    response = client.post(
        "/model/provider/batch_create", json=payload, headers=auth_header)
    
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    data = response.json()
    assert "Failed to batch create models" in data.get("detail", "")
    mock_batch.assert_called_once()


# Tests for /model/delete endpoint
@pytest.mark.asyncio
async def test_delete_model_success(client, auth_header, user_credentials, mocker):
    """Test successful model deletion."""
    mocker.patch('apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    async def _delete(*args, **kwargs):
        return "Test Model"
    
    mock_del = mocker.patch('apps.model_managment_app.delete_model_for_tenant', side_effect=_delete)
    
    response = client.post(
        "/model/delete", params={"display_name": "Test Model"}, headers=auth_header)
    
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert "Model deleted successfully" in data.get("message", "")
    assert data.get("data") == "Test Model"
    mock_del.assert_called_once()


@pytest.mark.asyncio
async def test_delete_model_not_found(client, auth_header, user_credentials, mocker):
    """Test model deletion when model not found."""
    mocker.patch('apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    mock_del = mocker.patch(
        'apps.model_managment_app.delete_model_for_tenant', 
        side_effect=LookupError("x")
    )
    
    response = client.post(
        "/model/delete", params={"display_name": "Missing"}, headers=auth_header)
    
    assert response.status_code == HTTPStatus.NOT_FOUND
    data = response.json()
    assert "Failed to delete model: model not found" in data.get("detail", "")
    mock_del.assert_called_once()


# Tests for /model/list endpoint
@pytest.mark.asyncio
async def test_get_model_list_success(client, auth_header, user_credentials, mocker):
    """Test successful model list retrieval."""
    mocker.patch('apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    async def mock_list_models(*args, **kwargs):
        return [
            {
                "model_id": "model1",
                "model_name": "huggingface/llama",
                "display_name": "LLaMA Model",
                "model_type": "llm",
                "connect_status": "operational"
            },
            {
                "model_id": "model2",
                "model_name": "openai/clip",
                "display_name": "CLIP Model",
                "model_type": "embedding",
                "connect_status": "not_detected"
            }
        ]
    
    mock_list = mocker.patch('apps.model_managment_app.list_models_for_tenant', side_effect=mock_list_models)
    
    response = client.get("/model/list", headers=auth_header)
    
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert "Successfully retrieved model list" in data["message"]
    assert len(data["data"]) == 2
    assert data["data"][0]["model_name"] == "huggingface/llama"
    assert data["data"][1]["model_name"] == "openai/clip"
    assert data["data"][1]["connect_status"] == "not_detected"
    mock_list.assert_called_once_with(user_credentials[1])


# Tests for /model/llm_list endpoint
@pytest.mark.asyncio
async def test_get_llm_model_list_success(client, auth_header, user_credentials, mocker):
    """Test successful LLM model list retrieval."""
    mocker.patch('apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    async def mock_list_llm_models(*args, **kwargs):
        return [
            {
                "model_id": "llm1",
                "model_name": "huggingface/llama-2",
                "display_name": "LLaMA 2 Model",
                "connect_status": "operational"
            },
            {
                "model_id": "llm2", 
                "model_name": "openai/gpt-4",
                "display_name": "GPT-4 Model",
                "connect_status": "not_detected"
            }
        ]
    
    mock_list = mocker.patch('apps.model_managment_app.list_llm_models_for_tenant', side_effect=mock_list_llm_models)
    
    response = client.get("/model/llm_list", headers=auth_header)
    
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert "Successfully retrieved LLM list" in data["message"]
    assert len(data["data"]) == 2
    assert data["data"][0]["model_name"] == "huggingface/llama-2"
    assert data["data"][1]["model_name"] == "openai/gpt-4"
    assert data["data"][0]["connect_status"] == "operational"
    assert data["data"][1]["connect_status"] == "not_detected"
    mock_list.assert_called_once_with(user_credentials[1])


@pytest.mark.asyncio
async def test_get_llm_model_list_exception(client, auth_header, user_credentials, mocker):
    """Test LLM model list retrieval with exception."""
    mocker.patch('apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    async def mock_list_llm_models(*args, **kwargs):
        raise Exception("Database connection error")
    
    mocker.patch('apps.model_managment_app.list_llm_models_for_tenant', side_effect=mock_list_llm_models)
    
    response = client.get("/model/llm_list", headers=auth_header)
    
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    data = response.json()
    assert "Failed to retrieve LLM list" in data.get("detail", "")


@pytest.mark.asyncio
async def test_get_llm_model_list_empty(client, auth_header, user_credentials, mocker):
    """Test LLM model list retrieval with empty result."""
    mocker.patch('apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    async def mock_list_llm_models(*args, **kwargs):
        return []
    
    mock_list = mocker.patch('apps.model_managment_app.list_llm_models_for_tenant', side_effect=mock_list_llm_models)
    
    response = client.get("/model/llm_list", headers=auth_header)
    
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert "Successfully retrieved LLM list" in data["message"]
    assert len(data["data"]) == 0
    mock_list.assert_called_once_with(user_credentials[1])


# Tests for /model/healthcheck endpoint
@pytest.mark.asyncio
async def test_check_model_health_success(client, auth_header, user_credentials, mocker):
    """Test successful model health check."""
    mocker.patch('apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    mock_check = mocker.patch(
        'apps.model_managment_app.check_model_connectivity', 
        return_value={"connectivity": True, "connect_status": "available"}
    )
    
    response = client.post(
        "/model/healthcheck",
        params={"display_name": "Test Model"},
        headers=auth_header
    )
    
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["message"] == "Successfully checked model connectivity"
    assert data["data"]["connectivity"] is True
    mock_check.assert_called_once_with("Test Model", user_credentials[1])


@pytest.mark.asyncio
async def test_check_model_health_lookup_error(client, auth_header, user_credentials, mocker):
    """Test model health check with lookup error."""
    mocker.patch('apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    mocker.patch(
        'apps.model_managment_app.check_model_connectivity', 
        side_effect=LookupError("missing")
    )
    
    response = client.post(
        "/model/healthcheck",
        params={"display_name": "X"},
        headers=auth_header
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


# Tests for /model/temporary_healthcheck endpoint
@pytest.mark.asyncio
async def test_verify_model_config_success(client, auth_header, sample_model_data, mocker):
    """Test successful model config verification."""
    mock_verify = mocker.patch(
        'apps.model_managment_app.verify_model_config_connectivity', 
        return_value={"connectivity": True, "model_name": "gpt-4"}
    )
    
    response = client.post(
        "/model/temporary_healthcheck", json=sample_model_data)
    
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["message"] == "Successfully verified model connectivity"
    assert data["data"]["connectivity"] is True
    mock_verify.assert_called_once()


@pytest.mark.asyncio
async def test_verify_model_config_exception(client, auth_header, sample_model_data, mocker):
    """Test model config verification with exception."""
    mocker.patch(
        'apps.model_managment_app.verify_model_config_connectivity', 
        side_effect=Exception("err")
    )
    
    response = client.post(
        "/model/temporary_healthcheck", json=sample_model_data)
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


# Tests for /model/update endpoint
@pytest.mark.asyncio
async def test_update_single_model_success(client, auth_header, user_credentials, mocker):
    """Test successful single model update."""
    mocker.patch('apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    async def mock_update_single(*args, **kwargs):
        return None
    
    mock_update = mocker.patch('apps.model_managment_app.update_single_model_for_tenant', side_effect=mock_update_single)
    
    update_data = {
        "model_id": "test_model_id",
        "model_name": "huggingface/llama",
        "display_name": "Updated Test Model",
        "base_url": "http://localhost:8001",
        "api_key": "updated_key",
        "model_type": "llm",
        "provider": "huggingface"
    }
    response = client.post(
        "/model/update", json=update_data, headers=auth_header)
    
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert "Model updated successfully" in data["message"]
    mock_update.assert_called_once_with(user_credentials[0], user_credentials[1], update_data)


@pytest.mark.asyncio
async def test_update_single_model_conflict(client, auth_header, user_credentials, mocker):
    """Test single model update with name conflict."""
    mocker.patch('apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    mock_update = mocker.patch(
        'apps.model_managment_app.update_single_model_for_tenant', 
        side_effect=ValueError("Name conflict")
    )
    
    update_data = {
        "model_id": "test_model_id",
        "model_name": "huggingface/llama",
        "display_name": "Conflicting Name",
        "base_url": "http://localhost:8001",
        "api_key": "updated_key",
        "model_type": "llm",
        "provider": "huggingface"
    }
    response = client.post(
        "/model/update", json=update_data, headers=auth_header)
    
    assert response.status_code == HTTPStatus.CONFLICT
    data = response.json()
    assert "Failed to update model: name conflict" in data.get("detail", "")
    mock_update.assert_called_once_with(user_credentials[0], user_credentials[1], update_data)


# Tests for /model/batch_update endpoint
@pytest.mark.asyncio
async def test_batch_update_models_success(client, auth_header, user_credentials, mocker):
    """Test successful batch model update."""
    mocker.patch('apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    async def mock_batch_update(*args, **kwargs):
        return None
    
    mock_batch_update = mocker.patch('apps.model_managment_app.batch_update_models_for_tenant', side_effect=mock_batch_update)
    
    models = [
        {"model_id": "id1", "api_key": "k1", "max_tokens": 100},
        {"model_id": "id2", "api_key": "k2", "max_tokens": 200},
    ]
    response = client.post(
        "/model/batch_update", json=models, headers=auth_header)
    
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert "Batch update models successfully" in data["message"]
    mock_batch_update.assert_called_once_with(user_credentials[0], user_credentials[1], models)


@pytest.mark.asyncio
async def test_batch_update_models_exception(client, auth_header, user_credentials, mocker):
    """Test batch model update with exception."""
    mocker.patch('apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    async def mock_batch_update(*args, **kwargs):
        raise Exception("Update failed")
    
    mock_batch_update = mocker.patch('apps.model_managment_app.batch_update_models_for_tenant', side_effect=mock_batch_update)
    
    models = [{"model_id": "id1", "api_key": "k1"}]
    response = client.post(
        "/model/batch_update", json=models, headers=auth_header)
    
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    data = response.json()
    assert "Failed to batch update models" in data.get("detail", "")
    mock_batch_update.assert_called_once_with(user_credentials[0], user_credentials[1], models)


if __name__ == "__main__":
    pytest.main([__file__])