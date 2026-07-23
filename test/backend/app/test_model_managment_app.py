import sys
import os
import pytest
from unittest.mock import patch, MagicMock, ANY
from fastapi.testclient import TestClient
from fastapi import FastAPI
from http import HTTPStatus

# Add project root to sys.path so that the top-level `backend` package is importable
PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "../../..")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Also add the backend source directory so that subpackages like `consts` can be imported directly
BACKEND_ROOT = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

# Patch environment variables before any imports that might use them
# Environment variables are now configured in conftest.py

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_client_mock = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_client_mock).start()


@pytest.fixture(scope="function")
def client(mocker):
    """Create test client with mocked dependencies."""
    # Mock boto3 and MinioClient before importing
    mocker.patch('boto3.client')
    # Patch MinioClient at both possible import paths
    mocker.patch('backend.database.client.MinioClient')
    # Stub services.vectordatabase_service to avoid real VDB initialization
    import types
    import sys as _sys
    if "services.vectordatabase_service" not in _sys.modules:
        services_vdb_mod = types.ModuleType("services.vectordatabase_service")

        def _get_vector_db_core():  # minimal stub
            return object()

        services_vdb_mod.get_vector_db_core = _get_vector_db_core
        _sys.modules["services.vectordatabase_service"] = services_vdb_mod
    
    # Import after mocking (only backend path is required by app imports)
    from backend.apps.model_managment_app import router
    
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


@pytest.mark.asyncio
async def test_suggest_capacity_success(client, auth_header, user_credentials, mocker):
    """Test standalone capacity suggestion endpoint."""
    from backend.consts.model import CapacitySuggestionFields, ModelCapacitySuggestionResponse

    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    mock_suggest = mocker.patch(
        'backend.apps.model_managment_app._suggest_capacity_for_request',
        return_value=ModelCapacitySuggestionResponse(
            suggestions=CapacitySuggestionFields(
                context_window_tokens=128000,
                max_output_tokens=16384,
                default_output_reserve_tokens=4096,
                tokenizer_family="o200k_base",
            ),
            match_kind="catalog_exact",
            match_confidence="high",
            match_explanation="Matched approved catalog profile openai/gpt-4o@1",
            suggested_provider="openai",
            canonical_model_name="gpt-4o",
            capability_profile_version="openai/gpt-4o@1",
            capacity_source_on_accept="operator",
        )
    )

    response = client.post(
        "/model/suggest-capacity",
        json={
            "model_name": "gpt-4o",
            "base_url": "https://api.openai.com/v1",
            "model_type": "llm",
        },
        headers=auth_header,
    )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    # Response uses the shared {message, data} envelope so the frontend
    # service layer can unwrap /model/* responses uniformly. See
    # suggest_model_capacity for the rationale.
    assert body["message"] == "Successfully suggested model capacity"
    data = body["data"]
    assert data["match_kind"] == "catalog_exact"
    assert data["suggestions"]["context_window_tokens"] == 128000
    assert data["suggested_provider"] == "openai"
    mock_suggest.assert_called_once()


@pytest.mark.asyncio
async def test_suggest_capacity_real_serialization_uses_envelope(client, auth_header, user_credentials, mocker):
    """End-to-end serialization test: hit /model/suggest-capacity without
    mocking the catalog matcher, so the response goes through the real
    Pydantic serializer and JSONResponse envelope. Asserts the {message,
    data} envelope shape and the nested catalog match. This is the safety
    net for wire-format drift -- the headline W11 V1 bug shipped past
    every existing unit test because nothing exercised the real
    backend-to-wire format.
    """
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    response = client.post(
        "/model/suggest-capacity",
        json={
            "model_name": "gpt-4o",
            "base_url": "https://api.openai.com/v1",
            "model_type": "llm",
        },
        headers=auth_header,
    )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    # Envelope must be present at the top level. This is the contract the
    # frontend modelService reads (`result.data`); breaking it makes both
    # the suggestion alert and the coverage banner dead end-to-end without
    # any unit test catching it.
    assert isinstance(body, dict)
    assert set(body.keys()) >= {"message", "data"}
    assert body["message"] == "Successfully suggested model capacity"

    data = body["data"]
    assert data["match_kind"] == "catalog_exact"
    assert data["match_confidence"] == "high"
    assert data["suggested_provider"] == "openai"
    assert data["canonical_model_name"] == "gpt-4o"
    assert data["capability_profile_version"] == "openai/gpt-4o@1"
    assert data["capacity_source_on_accept"] == "operator"
    # Nested capacity dict is also envelope-free at this level: it sits
    # directly under data.suggestions, mirroring the snake_case wire format
    # that mapCapacitySuggestionFromApi expects.
    assert data["suggestions"]["context_window_tokens"] > 0
    assert data["suggestions"]["max_output_tokens"] > 0


@pytest.mark.asyncio
async def test_capacity_coverage_real_serialization_uses_envelope(client, auth_header, user_credentials, mocker):
    """End-to-end serialization test for /model/capacity-coverage. Mocks the
    service layer but lets the route serialize a real dict through
    JSONResponse so the envelope contract is enforced at the wire boundary.
    """
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    mocker.patch(
        'backend.apps.model_managment_app.get_capacity_coverage',
        return_value={
            "total_llm_vlm": 3,
            "bare_count": 1,
            "bare_models": [
                {
                    "model_id": 99,
                    "model_name": "glm-5",
                    "model_factory": "OpenAI-API-Compatible",
                    "model_type": "llm",
                    "max_tokens": 131072,
                    "suggestion_available": False,
                }
            ],
        },
    )

    response = client.get("/model/capacity-coverage", headers=auth_header)

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert isinstance(body, dict)
    assert set(body.keys()) >= {"message", "data"}
    assert body["message"] == "Successfully retrieved model capacity coverage"

    data = body["data"]
    assert data["total_llm_vlm"] == 3
    assert data["bare_count"] == 1
    assert data["bare_models"][0]["model_id"] == 99
    assert data["bare_models"][0]["suggestion_available"] is False


@pytest.mark.asyncio
async def test_suggest_capacity_bad_request(client, auth_header, user_credentials, mocker):
    """Test standalone capacity suggestion endpoint maps invalid input to 400."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    mocker.patch(
        'backend.apps.model_managment_app._suggest_capacity_for_request',
        side_effect=ValueError("model_name is required"),
    )

    response = client.post(
        "/model/suggest-capacity",
        json={"model_name": "gpt-4o"},
        headers=auth_header,
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "model_name is required" in response.json()["detail"]


@pytest.mark.asyncio
async def test_capacity_coverage_success(client, auth_header, user_credentials, mocker):
    """Test capacity coverage endpoint uses current tenant."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    mock_coverage = mocker.patch(
        'backend.apps.model_managment_app.get_capacity_coverage',
        return_value={
            "total_llm_vlm": 2,
            "bare_count": 1,
            "bare_models": [
                {
                    "model_id": 11,
                    "model_name": "gpt-4o",
                    "model_factory": "openai",
                    "model_type": "llm",
                    "max_tokens": 16384,
                    "suggestion_available": True,
                }
            ],
        },
    )

    response = client.get("/model/capacity-coverage", headers=auth_header)

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body["message"] == "Successfully retrieved model capacity coverage"
    data = body["data"]
    assert data["total_llm_vlm"] == 2
    assert data["bare_count"] == 1
    assert data["bare_models"][0]["max_tokens"] == 16384
    assert data["bare_models"][0]["suggestion_available"] is True
    mock_coverage.assert_called_once_with(user_credentials[1])


# Tests for /model/create endpoint
@pytest.mark.asyncio
async def test_create_model_success(client, auth_header, user_credentials, sample_model_data, mocker):
    """Test successful model creation."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    async def _create(*args, **kwargs):
        return None
    
    mock_create = mocker.patch('backend.apps.model_managment_app.create_model_for_tenant', side_effect=_create)
    
    response = client.post(
        "/model/create", json=sample_model_data, headers=auth_header)
    
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert "Model created successfully" in data.get("message", "")
    mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_create_model_records_accept_signal_when_present(client, auth_header, user_credentials, sample_model_data, mocker):
    """End-to-end SLO data-flow check: when the frontend ships the W11 accept
    signal on a successful save, the app layer must (1) strip the audit-only
    fields before the DB write, and (2) call the metric recorder so
    model_capacity_suggestion_accept_total increments. Spec L709-710.
    """
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    async def _create(*args, **kwargs):
        return None

    mock_create = mocker.patch('backend.apps.model_managment_app.create_model_for_tenant', side_effect=_create)
    mock_record = mocker.patch('backend.apps.model_managment_app._record_capacity_suggestion_accept')

    payload = {
        **sample_model_data,
        "model_factory": "huggingface",
        "context_window_tokens": 128000,
        "max_output_tokens": 16384,
        "capacity_source": "operator",
        "accepted_suggestion_match_kind": "catalog_exact",
        "accepted_capability_profile_version": "openai/gpt-4o@1",
    }
    response = client.post("/model/create", json=payload, headers=auth_header)

    assert response.status_code == HTTPStatus.OK

    # Audit fields must NOT reach the service layer.
    create_args = mock_create.await_args
    sent = create_args.args[2]
    assert "accepted_suggestion_match_kind" not in sent
    assert "accepted_capability_profile_version" not in sent
    # Real capacity fields ARE forwarded.
    assert sent["context_window_tokens"] == 128000
    assert sent["max_output_tokens"] == 16384

    # Metric recorder called with the labels the SLO dashboard expects.
    mock_record.assert_called_once_with("catalog_exact", payload["model_factory"])


@pytest.mark.asyncio
async def test_create_model_skips_accept_recorder_without_match_kind(client, auth_header, user_credentials, sample_model_data, mocker):
    """Ordinary saves (no Use-suggestion click) must NOT fire the recorder.
    Otherwise accept_total inflates and the SLO ratio against
    dispatch_profile_hit_total becomes meaningless.
    """
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    async def _create(*args, **kwargs):
        return None

    mocker.patch('backend.apps.model_managment_app.create_model_for_tenant', side_effect=_create)
    mock_record = mocker.patch('backend.apps.model_managment_app._record_capacity_suggestion_accept')

    response = client.post("/model/create", json=sample_model_data, headers=auth_header)

    assert response.status_code == HTTPStatus.OK
    mock_record.assert_not_called()


@pytest.mark.asyncio
async def test_create_model_conflict(client, auth_header, user_credentials, sample_model_data, mocker):
    """Test model creation with name conflict."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    mock_create = mocker.patch(
        'backend.apps.model_managment_app.create_model_for_tenant', 
        side_effect=ValueError("Name 'Test Model' is already in use, please choose another display name")
    )
    
    response = client.post(
        "/model/create", json=sample_model_data, headers=auth_header)
    
    assert response.status_code == HTTPStatus.CONFLICT
    data = response.json()
    # Now we return the actual error message, not a generic one
    assert "Name 'Test Model' is already in use" in data.get("detail", "")
    mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_create_model_exception(client, auth_header, user_credentials, sample_model_data, mocker):
    """Test model creation with internal error."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    mock_create = mocker.patch(
        'backend.apps.model_managment_app.create_model_for_tenant', 
        side_effect=Exception("DB failure")
    )
    
    response = client.post(
        "/model/create", json=sample_model_data, headers=auth_header)
    
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    data = response.json()
    # Now we return the actual error message
    assert "DB failure" in data.get("detail", "")
    mock_create.assert_called_once()


# Tests for /model/provider/create endpoint
@pytest.mark.asyncio
async def test_create_provider_model_success(client, auth_header, user_credentials, mocker):
    """Test successful provider model creation."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    mock_get = mocker.patch(
        'backend.apps.model_managment_app.create_provider_models_for_tenant', 
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
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    mock_get = mocker.patch(
        'backend.apps.model_managment_app.create_provider_models_for_tenant', 
        side_effect=Exception("Provider API error")
    )
    
    # Fix: Add required model_type field
    request_data = {"provider": "silicon", "model_type": "llm", "api_key": "test_key"}
    response = client.post(
        "/model/provider/create", json=request_data, headers=auth_header)
    
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    data = response.json()
    # Now we return the actual error message
    assert "Provider API error" in data.get("detail", "")
    mock_get.assert_called_once()


# Tests for /model/provider/batch_create endpoint
@pytest.mark.asyncio
async def test_provider_batch_create_success(client, auth_header, user_credentials, mocker):
    """Test successful batch model creation."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    async def _batch(*args, **kwargs):
        return None
    
    mock_batch = mocker.patch('backend.apps.model_managment_app.batch_create_models_for_tenant', side_effect=_batch)
    
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
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    mock_batch = mocker.patch(
        'backend.apps.model_managment_app.batch_create_models_for_tenant', 
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
    # Now we return the actual error message
    assert "boom" in data.get("detail", "")
    mock_batch.assert_called_once()


@pytest.mark.asyncio
async def test_provider_batch_create_strips_accept_signal_and_records(
    client, auth_header, user_credentials, mocker
):
    """Same audit-only contract as /create: per-model accept-signal fields
    must be popped before the batch reaches the service layer (otherwise
    SQLAlchemy raises 'Unconsumed column names' on insert), and the SLO
    counter fires once per accepted row after the persist call succeeds.
    """
    mocker.patch(
        'backend.apps.model_managment_app.get_current_user_id',
        return_value=user_credentials,
    )

    async def _batch(*args, **kwargs):
        return None

    mock_batch = mocker.patch(
        'backend.apps.model_managment_app.batch_create_models_for_tenant',
        side_effect=_batch,
    )
    mock_record = mocker.patch(
        'backend.apps.model_managment_app._record_capacity_suggestion_accept'
    )

    payload = {
        "models": [
            {
                "id": "prov/modelA",
                "accepted_suggestion_match_kind": "catalog_exact",
                "accepted_capability_profile_version": "prov/modelA@1",
            },
            {"id": "prov/modelB"},
        ],
        "provider": "prov",
        "type": "llm",
        "api_key": "k",
    }
    response = client.post(
        "/model/provider/batch_create", json=payload, headers=auth_header)

    assert response.status_code == HTTPStatus.OK
    sent = mock_batch.await_args.args[2]
    for model in sent["models"]:
        assert "accepted_suggestion_match_kind" not in model
        assert "accepted_capability_profile_version" not in model
    mock_record.assert_called_once_with("catalog_exact", "prov")


# Tests for /model/delete endpoint
@pytest.mark.asyncio
async def test_delete_model_success(client, auth_header, user_credentials, mocker):
    """Test successful model deletion."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    async def _delete(*args, **kwargs):
        return "Test Model"
    
    mock_del = mocker.patch('backend.apps.model_managment_app.delete_model_for_tenant', side_effect=_delete)
    
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
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    mock_del = mocker.patch(
        'backend.apps.model_managment_app.delete_model_for_tenant', 
        side_effect=LookupError("Model not found: Missing")
    )
    
    response = client.post(
        "/model/delete", params={"display_name": "Missing"}, headers=auth_header)
    
    assert response.status_code == HTTPStatus.NOT_FOUND
    data = response.json()
    # Now we return the actual error message
    assert "Model not found: Missing" in data.get("detail", "")
    mock_del.assert_called_once()


# Tests for /model/list endpoint
@pytest.mark.asyncio
async def test_get_model_list_success(client, auth_header, user_credentials, mocker):
    """Test successful model list retrieval."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
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
    
    mock_list = mocker.patch('backend.apps.model_managment_app.list_models_for_tenant', side_effect=mock_list_models)
    
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
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
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
    
    mock_list = mocker.patch('backend.apps.model_managment_app.list_llm_models_for_tenant', side_effect=mock_list_llm_models)
    
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
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    async def mock_list_llm_models(*args, **kwargs):
        raise Exception("Database connection error")
    
    mocker.patch('backend.apps.model_managment_app.list_llm_models_for_tenant', side_effect=mock_list_llm_models)
    
    response = client.get("/model/llm_list", headers=auth_header)
    
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    data = response.json()
    # Now we return the actual error message
    assert "Database connection error" in data.get("detail", "")


@pytest.mark.asyncio
async def test_get_llm_model_list_empty(client, auth_header, user_credentials, mocker):
    """Test LLM model list retrieval with empty result."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    async def mock_list_llm_models(*args, **kwargs):
        return []
    
    mock_list = mocker.patch('backend.apps.model_managment_app.list_llm_models_for_tenant', side_effect=mock_list_llm_models)
    
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
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    mock_check = mocker.patch(
        'backend.apps.model_managment_app.check_model_connectivity', 
        return_value={"connectivity": True, "connect_status": "available"}
    )
    
    response = client.post(
        "/model/healthcheck",
        params={"display_name": "Test Model", "model_type": "embedding"},
        headers=auth_header
    )
    
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["message"] == "Successfully checked model connectivity"
    assert data["data"]["connectivity"] is True
    mock_check.assert_called_once_with("Test Model", user_credentials[1], "embedding")


@pytest.mark.asyncio
async def test_check_model_health_lookup_error(client, auth_header, user_credentials, mocker):
    """Test model health check with lookup error."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    mocker.patch(
        'backend.apps.model_managment_app.check_model_connectivity', 
        side_effect=LookupError("missing")
    )
    
    response = client.post(
        "/model/healthcheck",
        params={"display_name": "X", "model_type": "embedding"},
        headers=auth_header
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


# Tests for /model/temporary_healthcheck endpoint
@pytest.mark.asyncio
async def test_verify_model_config_success(client, auth_header, sample_model_data, mocker):
    """Test successful model config verification."""
    mock_verify = mocker.patch(
        'backend.apps.model_managment_app.verify_model_config_connectivity', 
        return_value={"connectivity": True, "model_name": "gpt-4"}
    )
    mock_suggest = mocker.patch(
        'backend.apps.model_managment_app._capacity_suggestion_for_model_request',
        return_value={
            "suggestions": {"context_window_tokens": 128000},
            "match_kind": "catalog_exact",
        },
    )
    
    response = client.post(
        "/model/temporary_healthcheck", json=sample_model_data)
    
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["message"] == "Successfully verified model connectivity"
    assert data["data"]["connectivity"] is True
    assert data["data"]["capacity_suggestion"]["match_kind"] == "catalog_exact"
    # Success case should not have error field in response
    assert "error" not in data["data"]
    mock_verify.assert_called_once()
    mock_suggest.assert_called_once()


@pytest.mark.asyncio
async def test_verify_model_config_failure_with_error(client, auth_header, sample_model_data, mocker):
    """Test model config verification failure with detailed error message."""
    mock_verify = mocker.patch(
        'backend.apps.model_managment_app.verify_model_config_connectivity', 
        return_value={
            "connectivity": False, 
            "model_name": "gpt-4",
            "error": "Failed to connect to model 'gpt-4' at https://api.openai.com. Please verify the URL, API key, and network connection."
        }
    )
    mock_suggest = mocker.patch('backend.apps.model_managment_app._capacity_suggestion_for_model_request')
    
    response = client.post(
        "/model/temporary_healthcheck", json=sample_model_data)
    
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["message"] == "Successfully verified model connectivity"
    assert data["data"]["connectivity"] is False
    # Failure case should have error field with descriptive message
    assert "error" in data["data"]
    assert data["data"]["capacity_suggestion"] is None
    assert "Failed to connect to model" in data["data"]["error"]
    assert "Please verify the URL, API key, and network connection" in data["data"]["error"]
    mock_verify.assert_called_once()
    mock_suggest.assert_not_called()


@pytest.mark.asyncio
async def test_verify_model_config_exception(client, auth_header, sample_model_data, mocker):
    """Test model config verification with exception."""
    mocker.patch(
        'backend.apps.model_managment_app.verify_model_config_connectivity', 
        side_effect=Exception("err")
    )
    
    response = client.post(
        "/model/temporary_healthcheck", json=sample_model_data)
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


# Tests for /model/update endpoint
@pytest.mark.asyncio
async def test_update_single_model_success(client, auth_header, user_credentials, mocker):
    """Test successful single model update."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    async def mock_update_single(*args, **kwargs):
        return None
    
    mock_update = mocker.patch('backend.apps.model_managment_app.update_single_model_for_tenant', side_effect=mock_update_single)
    
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
        "/model/update",
        params={"display_name": "Updated Test Model"},
        json=update_data,
        headers=auth_header,
    )
    
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert "Model updated successfully" in data["message"]
    mock_update.assert_called_once_with(
        user_credentials[0],
        user_credentials[1],
        "Updated Test Model",
        update_data,
    )


@pytest.mark.asyncio
async def test_update_single_model_conflict(client, auth_header, user_credentials, mocker):
    """Test single model update with name conflict."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    mock_update = mocker.patch(
        'backend.apps.model_managment_app.update_single_model_for_tenant',
        side_effect=ValueError("Name 'Conflicting Name' is already in use, please choose another display name"),
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
        "/model/update",
        params={"display_name": "Conflicting Name"},
        json=update_data,
        headers=auth_header,
    )
    
    assert response.status_code == HTTPStatus.CONFLICT
    data = response.json()
    # Now we return the actual error message
    assert "Name 'Conflicting Name' is already in use" in data.get("detail", "")
    mock_update.assert_called_once_with(
        user_credentials[0],
        user_credentials[1],
        "Conflicting Name",
        update_data,
    )


# Tests for /model/batch_update endpoint
@pytest.mark.asyncio
async def test_batch_update_models_success(client, auth_header, user_credentials, mocker):
    """Test successful batch model update."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    async def mock_batch_update(*args, **kwargs):
        return None
    
    mock_batch_update = mocker.patch('backend.apps.model_managment_app.batch_update_models_for_tenant', side_effect=mock_batch_update)
    
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
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)
    
    async def mock_batch_update(*args, **kwargs):
        raise Exception("Update failed")
    
    mock_batch_update = mocker.patch('backend.apps.model_managment_app.batch_update_models_for_tenant', side_effect=mock_batch_update)
    
    models = [{"model_id": "id1", "api_key": "k1"}]
    response = client.post(
        "/model/batch_update", json=models, headers=auth_header)
    
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    data = response.json()
    # Now we return the actual error message
    assert "Update failed" in data.get("detail", "")
    mock_batch_update.assert_called_once_with(user_credentials[0], user_credentials[1], models)


# Tests for /model/manage/list endpoint
@pytest.mark.asyncio
async def test_get_manage_model_list_success(client, auth_header, user_credentials, mocker):
    """Test successful manage model list retrieval for a specified tenant."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    async def mock_list_models_for_admin(*args, **kwargs):
        return {
            "tenant_id": "target_tenant",
            "tenant_name": "Target Tenant",
            "models": [
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
            ],
            "total": 2,
            "page": 1,
            "page_size": 20,
            "total_pages": 1
        }

    mock_list = mocker.patch('backend.apps.model_managment_app.list_models_for_admin', side_effect=mock_list_models_for_admin)

    request_data = {
        "tenant_id": "target_tenant",
        "model_type": None,
        "page": 1,
        "page_size": 20
    }
    response = client.post("/model/manage/list", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert "Successfully retrieved model list" in data["message"]
    assert data["data"]["tenant_id"] == "target_tenant"
    assert data["data"]["tenant_name"] == "Target Tenant"
    assert data["data"]["total"] == 2
    assert data["data"]["page"] == 1
    assert data["data"]["page_size"] == 20
    assert data["data"]["total_pages"] == 1
    assert len(data["data"]["models"]) == 2
    assert data["data"]["models"][0]["model_name"] == "huggingface/llama"
    assert data["data"]["models"][1]["model_name"] == "openai/clip"
    mock_list.assert_called_once_with("target_tenant", None, 1, 20)


@pytest.mark.asyncio
async def test_get_manage_model_list_with_pagination(client, auth_header, user_credentials, mocker):
    """Test manage model list retrieval with pagination parameters."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    async def mock_list_models_for_admin(*args, **kwargs):
        return {
            "tenant_id": "target_tenant",
            "tenant_name": "Target Tenant",
            "models": [
                {
                    "model_id": "model3",
                    "model_name": "openai/gpt-3",
                    "display_name": "GPT-3",
                    "model_type": "llm",
                    "connect_status": "operational"
                }
            ],
            "total": 25,
            "page": 2,
            "page_size": 10,
            "total_pages": 3
        }

    mock_list = mocker.patch('backend.apps.model_managment_app.list_models_for_admin', side_effect=mock_list_models_for_admin)

    request_data = {
        "tenant_id": "target_tenant",
        "model_type": "llm",
        "page": 2,
        "page_size": 10
    }
    response = client.post("/model/manage/list", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["data"]["page"] == 2
    assert data["data"]["page_size"] == 10
    assert data["data"]["total"] == 25
    assert data["data"]["total_pages"] == 3
    assert len(data["data"]["models"]) == 1
    mock_list.assert_called_once_with("target_tenant", "llm", 2, 10)


@pytest.mark.asyncio
async def test_get_manage_model_list_exception(client, auth_header, user_credentials, mocker):
    """Test manage model list retrieval with exception."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    async def mock_list_models_for_admin(*args, **kwargs):
        raise Exception("Database connection error")

    mocker.patch('backend.apps.model_managment_app.list_models_for_admin', side_effect=mock_list_models_for_admin)

    request_data = {
        "tenant_id": "target_tenant",
        "model_type": None,
        "page": 1,
        "page_size": 20
    }
    response = client.post("/model/manage/list", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    data = response.json()
    assert "Database connection error" in data.get("detail", "")


@pytest.mark.asyncio
async def test_get_manage_model_list_empty(client, auth_header, user_credentials, mocker):
    """Test manage model list retrieval with empty result."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    async def mock_list_models_for_admin(*args, **kwargs):
        return {
            "tenant_id": "empty_tenant",
            "tenant_name": "Empty Tenant",
            "models": [],
            "total": 0,
            "page": 1,
            "page_size": 20,
            "total_pages": 0
        }

    mock_list = mocker.patch('backend.apps.model_managment_app.list_models_for_admin', side_effect=mock_list_models_for_admin)

    request_data = {
        "tenant_id": "empty_tenant",
        "model_type": None,
        "page": 1,
        "page_size": 20
    }
    response = client.post("/model/manage/list", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert "Successfully retrieved model list" in data["message"]
    assert data["data"]["total"] == 0
    assert len(data["data"]["models"]) == 0
    mock_list.assert_called_once_with("empty_tenant", None, 1, 20)


# Tests for /model/manage/create endpoint
@pytest.mark.asyncio
async def test_manage_create_model_success(client, auth_header, user_credentials, mocker):
    """Test successful model creation for a specified tenant."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    async def _create(*args, **kwargs):
        return None

    mock_create = mocker.patch('backend.apps.model_managment_app.create_model_for_tenant', side_effect=_create)

    request_data = {
        "tenant_id": "target_tenant",
        "model_repo": "",
        "model_name": "huggingface/llama",
        "model_type": "llm",
        "base_url": "http://localhost:8000",
        "api_key": "test_key",
        "max_tokens": 4096,
        "display_name": "LLaMA Model"
    }
    response = client.post("/model/manage/create", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert "Model created successfully" in data["message"]
    assert data["data"]["tenant_id"] == "target_tenant"
    # Verify the call was made with correct tenant_id and user_id
    mock_create.assert_called_once_with(
        user_credentials[0],
        "target_tenant",
        ANY  # The dict may contain additional optional fields like chunk settings
    )


@pytest.mark.asyncio
async def test_manage_create_model_records_accept_signal_when_present(
    client, auth_header, user_credentials, mocker
):
    """Same SLO contract as /create: when SU/asset-owner saves a model
    through /manage/create with the accept signal in the payload, the
    audit fields must be stripped before reaching the service and the
    accept_total recorder must fire with provider=model_factory. Before
    the fix the manage Pydantic schema did not declare the two fields,
    so Pydantic silently dropped them and the SLO numerator missed
    every accept that landed via the SU surface.
    """
    mocker.patch(
        'backend.apps.model_managment_app.get_current_user_id',
        return_value=user_credentials,
    )

    async def _create(*args, **kwargs):
        return None

    mock_create = mocker.patch(
        'backend.apps.model_managment_app.create_model_for_tenant',
        side_effect=_create,
    )
    mock_record = mocker.patch(
        'backend.apps.model_managment_app._record_capacity_suggestion_accept'
    )

    request_data = {
        "tenant_id": "target_tenant",
        "model_name": "gpt-4o",
        "model_type": "llm",
        "model_factory": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_key": "k",
        "context_window_tokens": 128000,
        "max_output_tokens": 16384,
        "capacity_source": "operator",
        "accepted_suggestion_match_kind": "catalog_exact",
        "accepted_capability_profile_version": "openai/gpt-4o@1",
    }
    response = client.post(
        "/model/manage/create", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.OK
    sent = mock_create.await_args.args[2]
    assert "accepted_suggestion_match_kind" not in sent
    assert "accepted_capability_profile_version" not in sent
    mock_record.assert_called_once_with("catalog_exact", "openai")


@pytest.mark.asyncio
async def test_manage_create_model_conflict(client, auth_header, user_credentials, mocker):
    """Test model creation with conflict error."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    async def _create(*args, **kwargs):
        raise ValueError("Model name already exists")

    mocker.patch('backend.apps.model_managment_app.create_model_for_tenant', side_effect=_create)

    request_data = {
        "tenant_id": "target_tenant",
        "model_name": "duplicate-model",
        "model_type": "llm",
        "base_url": "http://localhost:8000",
        "api_key": "test_key"
    }
    response = client.post("/model/manage/create", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.CONFLICT
    assert "Model name already exists" in response.json()["detail"]


@pytest.mark.asyncio
async def test_manage_create_model_exception(client, auth_header, user_credentials, mocker):
    """Test model creation with unexpected exception."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    async def _create(*args, **kwargs):
        raise Exception("Database error")

    mocker.patch('backend.apps.model_managment_app.create_model_for_tenant', side_effect=_create)

    request_data = {
        "tenant_id": "target_tenant",
        "model_name": "test-model",
        "model_type": "llm",
        "base_url": "http://localhost:8000",
        "api_key": "test_key"
    }
    response = client.post("/model/manage/create", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


# Tests for /model/manage/update endpoint
@pytest.mark.asyncio
async def test_manage_update_model_success(client, auth_header, user_credentials, mocker):
    """Test successful model update for a specified tenant."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    async def _update(*args, **kwargs):
        return None

    mock_update = mocker.patch('backend.apps.model_managment_app.update_single_model_for_tenant', side_effect=_update)

    request_data = {
        "tenant_id": "target_tenant",
        "current_display_name": "Old Model Name",
        "display_name": "New Model Name",
        "base_url": "http://localhost:8000",
        "api_key": "new_api_key",
        "max_tokens": 8192
    }
    response = client.post("/model/manage/update", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert "Model updated successfully" in data["message"]
    assert data["data"]["tenant_id"] == "target_tenant"
    # Verify the call was made with correct tenant_id, user_id and model name
    mock_update.assert_called_once_with(
        user_credentials[0],
        "target_tenant",
        "Old Model Name",
        ANY  # The dict may contain additional optional fields like chunk settings
    )


@pytest.mark.asyncio
async def test_manage_update_model_records_accept_signal_when_present(
    client, auth_header, user_credentials, mocker
):
    """Mirror of test_manage_create_model_records_accept_signal_when_present
    for the /manage/update path. The SU surface routes the same accept
    signal through updateManageTenantModel; the recorder must fire with
    provider=model_factory and the audit fields must not leak into the
    DB update.
    """
    mocker.patch(
        'backend.apps.model_managment_app.get_current_user_id',
        return_value=user_credentials,
    )

    async def _update(*args, **kwargs):
        return None

    mock_update = mocker.patch(
        'backend.apps.model_managment_app.update_single_model_for_tenant',
        side_effect=_update,
    )
    mock_record = mocker.patch(
        'backend.apps.model_managment_app._record_capacity_suggestion_accept'
    )

    request_data = {
        "tenant_id": "target_tenant",
        "current_display_name": "GPT-4o",
        "model_factory": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_key": "k",
        "context_window_tokens": 128000,
        "max_output_tokens": 16384,
        "capacity_source": "operator",
        "accepted_suggestion_match_kind": "catalog_fuzzy",
        "accepted_capability_profile_version": "openai/gpt-4o@1",
    }
    response = client.post(
        "/model/manage/update", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.OK
    sent = mock_update.await_args.args[3]
    assert "accepted_suggestion_match_kind" not in sent
    assert "accepted_capability_profile_version" not in sent
    mock_record.assert_called_once_with("catalog_fuzzy", "openai")


@pytest.mark.asyncio
async def test_manage_update_model_not_found(client, auth_header, user_credentials, mocker):
    """Test model update with not found error."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    async def _update(*args, **kwargs):
        raise LookupError("Model not found")

    mocker.patch('backend.apps.model_managment_app.update_single_model_for_tenant', side_effect=_update)

    request_data = {
        "tenant_id": "target_tenant",
        "current_display_name": "nonexistent-model",
        "display_name": "Updated Name"
    }
    response = client.post("/model/manage/update", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_manage_update_model_conflict(client, auth_header, user_credentials, mocker):
    """Test model update with conflict error."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    async def _update(*args, **kwargs):
        raise ValueError("Display name already exists")

    mocker.patch('backend.apps.model_managment_app.update_single_model_for_tenant', side_effect=_update)

    request_data = {
        "tenant_id": "target_tenant",
        "current_display_name": "test-model",
        "display_name": "duplicate-name"
    }
    response = client.post("/model/manage/update", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.CONFLICT


# Tests for /model/manage/delete endpoint
@pytest.mark.asyncio
async def test_manage_delete_model_success(client, auth_header, user_credentials, mocker):
    """Test successful model deletion for a specified tenant."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    async def _delete(*args, **kwargs):
        return "test-model"

    mock_delete = mocker.patch('backend.apps.model_managment_app.delete_model_for_tenant', side_effect=_delete)

    request_data = {
        "tenant_id": "target_tenant",
        "display_name": "test-model"
    }
    response = client.post("/model/manage/delete", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert "Model deleted successfully" in data["message"]
    assert data["data"]["tenant_id"] == "target_tenant"
    assert data["data"]["display_name"] == "test-model"
    mock_delete.assert_called_once_with(user_credentials[0], "target_tenant", "test-model")


@pytest.mark.asyncio
async def test_manage_delete_model_not_found(client, auth_header, user_credentials, mocker):
    """Test model deletion with not found error."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    async def _delete(*args, **kwargs):
        raise LookupError("Model not found")

    mocker.patch('backend.apps.model_managment_app.delete_model_for_tenant', side_effect=_delete)

    request_data = {
        "tenant_id": "target_tenant",
        "display_name": "nonexistent-model"
    }
    response = client.post("/model/manage/delete", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_manage_delete_model_exception(client, auth_header, user_credentials, mocker):
    """Test model deletion with unexpected exception."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    async def _delete(*args, **kwargs):
        raise Exception("Database error")

    mocker.patch('backend.apps.model_managment_app.delete_model_for_tenant', side_effect=_delete)

    request_data = {
        "tenant_id": "target_tenant",
        "display_name": "test-model"
    }
    response = client.post("/model/manage/delete", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


# Tests for /model/manage/batch_create endpoint
@pytest.mark.asyncio
async def test_manage_batch_create_models_success(client, auth_header, user_credentials, mocker):
    """Test successful batch model creation for a specified tenant."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    async def _batch_create(*args, **kwargs):
        return None

    mock_batch_create = mocker.patch('backend.apps.model_managment_app.batch_create_models_for_tenant', side_effect=_batch_create)

    request_data = {
        "tenant_id": "target_tenant",
        "provider": "silicon",
        "type": "llm",
        "api_key": "test_api_key",
        "models": [
            {
                "id": "silicon/llama-3-1-8b-instruct",
                "object": "model",
                "created": 1699900000,
                "owned_by": "silicon",
                "max_tokens": 4096
            },
            {
                "id": "silicon/llama-3-1-70b-instruct",
                "object": "model",
                "created": 1699900001,
                "owned_by": "silicon",
                "max_tokens": 8192
            }
        ]
    }
    response = client.post("/model/manage/batch_create", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert "Batch create models successfully" in data["message"]
    assert data["data"]["tenant_id"] == "target_tenant"
    assert data["data"]["provider"] == "silicon"
    assert data["data"]["type"] == "llm"
    assert data["data"]["models_count"] == 2
    mock_batch_create.assert_called_once_with(
        user_credentials[0],
        "target_tenant",
        {
            "tenant_id": "target_tenant",
            "provider": "silicon",
            "type": "llm",
            "api_key": "test_api_key",
            "models": [
                {
                    "id": "silicon/llama-3-1-8b-instruct",
                    "object": "model",
                    "created": 1699900000,
                    "owned_by": "silicon",
                    "max_tokens": 4096
                },
                {
                    "id": "silicon/llama-3-1-70b-instruct",
                    "object": "model",
                    "created": 1699900001,
                    "owned_by": "silicon",
                    "max_tokens": 8192
                }
            ]
        }
    )


@pytest.mark.asyncio
async def test_manage_batch_create_models_empty_list(client, auth_header, user_credentials, mocker):
    """Test batch model creation with empty models list."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    async def _batch_create(*args, **kwargs):
        return None

    mock_batch_create = mocker.patch('backend.apps.model_managment_app.batch_create_models_for_tenant', side_effect=_batch_create)

    request_data = {
        "tenant_id": "target_tenant",
        "provider": "modelengine",
        "type": "embedding",
        "api_key": "",
        "models": []
    }
    response = client.post("/model/manage/batch_create", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert "Batch create models successfully" in data["message"]
    assert data["data"]["models_count"] == 0
    mock_batch_create.assert_called_once()


@pytest.mark.asyncio
async def test_manage_batch_create_models_exception(client, auth_header, user_credentials, mocker):
    """Test batch model creation with exception."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    async def _batch_create(*args, **kwargs):
        raise Exception("Database connection error")

    mocker.patch('backend.apps.model_managment_app.batch_create_models_for_tenant', side_effect=_batch_create)

    request_data = {
        "tenant_id": "target_tenant",
        "provider": "silicon",
        "type": "llm",
        "api_key": "test_api_key",
        "models": [
            {"id": "silicon/test-model", "max_tokens": 4096}
        ]
    }
    response = client.post("/model/manage/batch_create", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


# Tests for /model/manage/healthcheck endpoint
@pytest.mark.asyncio
async def test_manage_healthcheck_success(client, auth_header, user_credentials, mocker):
    """Test successful model connectivity check for a specified tenant."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    mock_check = mocker.patch(
        'backend.apps.model_managment_app.check_model_connectivity',
        return_value={"connectivity": True, "connect_status": "available"}
    )

    request_data = {
        "tenant_id": "target_tenant",
        "display_name": "test-model",
        "model_type": "llm"
    }
    response = client.post("/model/manage/healthcheck", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert "Successfully checked model connectivity" in data["message"]
    assert data["data"]["connectivity"] is True
    mock_check.assert_called_once_with("test-model", "target_tenant", "llm")


@pytest.mark.asyncio
async def test_manage_healthcheck_without_model_type_is_backward_compatible(
    client, auth_header, user_credentials, mocker
):
    """Test model connectivity check still accepts requests without model_type."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    mock_check = mocker.patch(
        'backend.apps.model_managment_app.check_model_connectivity',
        return_value={"connectivity": True, "connect_status": "available"}
    )

    request_data = {
        "tenant_id": "target_tenant",
        "display_name": "test-model"
    }
    response = client.post("/model/manage/healthcheck", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.OK
    mock_check.assert_called_once_with("test-model", "target_tenant", None)


@pytest.mark.asyncio
async def test_manage_healthcheck_model_not_found(client, auth_header, user_credentials, mocker):
    """Test model connectivity check when model is not found."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    mocker.patch(
        'backend.apps.model_managment_app.check_model_connectivity',
        side_effect=LookupError("Model configuration not found for test-model")
    )

    request_data = {
        "tenant_id": "target_tenant",
        "display_name": "nonexistent-model"
    }
    response = client.post("/model/manage/healthcheck", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert "Model configuration not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_manage_healthcheck_invalid_config(client, auth_header, user_credentials, mocker):
    """Test model connectivity check with invalid model configuration."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    mocker.patch(
        'backend.apps.model_managment_app.check_model_connectivity',
        side_effect=ValueError("Invalid model configuration")
    )

    request_data = {
        "tenant_id": "target_tenant",
        "display_name": "test-model"
    }
    response = client.post("/model/manage/healthcheck", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "Invalid model configuration" in response.json()["detail"]


@pytest.mark.asyncio
async def test_manage_healthcheck_exception(client, auth_header, user_credentials, mocker):
    """Test model connectivity check with unexpected exception."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    mocker.patch(
        'backend.apps.model_managment_app.check_model_connectivity',
        side_effect=Exception("Database connection error")
    )

    request_data = {
        "tenant_id": "target_tenant",
        "display_name": "test-model"
    }
    response = client.post("/model/manage/healthcheck", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


# Tests for /model/manage/provider/list endpoint
@pytest.mark.asyncio
async def test_manage_provider_list_success(client, auth_header, user_credentials, mocker):
    """Test successful provider model list retrieval for a specified tenant."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    async def mock_list_provider_models(*args, **kwargs):
        return [
            {
                "id": "silicon/llama-3-8b",
                "model_repo": "silicon",
                "model_name": "llama-3-8b",
                "object": "model",
                "created": 1699999999,
                "owned_by": "silicon",
                "max_tokens": 8192
            },
            {
                "id": "silicon/llama-3-70b",
                "model_repo": "silicon",
                "model_name": "llama-3-70b",
                "object": "model",
                "created": 1699999999,
                "owned_by": "silicon",
                "max_tokens": 8192
            }
        ]

    mock_list = mocker.patch('backend.apps.model_managment_app.list_provider_models_for_tenant', side_effect=mock_list_provider_models)

    request_data = {
        "tenant_id": "target_tenant",
        "provider": "silicon",
        "model_type": "llm"
    }
    response = client.post("/model/manage/provider/list", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert "Successfully retrieved provider model list" in data["message"]
    assert len(data["data"]) == 2
    mock_list.assert_called_once_with("target_tenant", "silicon", "llm")


@pytest.mark.asyncio
async def test_manage_provider_list_exception(client, auth_header, user_credentials, mocker):
    """Test provider model list retrieval with exception."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    async def mock_list_provider_models(*args, **kwargs):
        raise Exception("Provider API error")

    mocker.patch('backend.apps.model_managment_app.list_provider_models_for_tenant', side_effect=mock_list_provider_models)

    request_data = {
        "tenant_id": "target_tenant",
        "provider": "silicon",
        "model_type": "llm"
    }
    response = client.post("/model/manage/provider/list", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


@pytest.mark.asyncio
async def test_manage_provider_list_empty(client, auth_header, user_credentials, mocker):
    """Test provider model list retrieval with empty result."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    async def mock_list_provider_models(*args, **kwargs):
        return []

    mock_list = mocker.patch('backend.apps.model_managment_app.list_provider_models_for_tenant', side_effect=mock_list_provider_models)

    request_data = {
        "tenant_id": "empty_tenant",
        "provider": "silicon",
        "model_type": "embedding"
    }
    response = client.post("/model/manage/provider/list", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert len(data["data"]) == 0


# Tests for /model/manage/provider/create endpoint
@pytest.mark.asyncio
async def test_manage_provider_create_success(client, auth_header, user_credentials, mocker):
    """Test successful provider model creation for a specified tenant."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    async def mock_create_provider_models(*args, **kwargs):
        return [
            {
                "id": "silicon/llama-3-8b",
                "object": "model",
                "created": 1699999999,
                "owned_by": "silicon",
                "max_tokens": 8192
            },
            {
                "id": "silicon/llama-3-70b",
                "object": "model",
                "created": 1699999999,
                "owned_by": "silicon",
                "max_tokens": 8192
            }
        ]

    mock_create = mocker.patch('backend.apps.model_managment_app.create_provider_models_for_tenant', side_effect=mock_create_provider_models)

    request_data = {
        "tenant_id": "target_tenant",
        "provider": "silicon",
        "model_type": "llm",
        "api_key": "test_api_key",
        "base_url": ""
    }
    response = client.post("/model/manage/provider/create", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert "Successfully created provider models" in data["message"]
    assert len(data["data"]) == 2
    mock_create.assert_called_once_with(
        "target_tenant",
        {"provider": "silicon", "model_type": "llm", "api_key": "test_api_key", "base_url": ""}
    )


@pytest.mark.asyncio
async def test_manage_provider_create_with_base_url(client, auth_header, user_credentials, mocker):
    """Test provider model creation with base URL for modelengine provider."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    async def mock_create_provider_models(*args, **kwargs):
        return [
            {
                "id": "modelengine/gpt-4",
                "object": "model",
                "created": 1699999999,
                "owned_by": "modelengine",
                "max_tokens": 8192
            }
        ]

    mock_create = mocker.patch('backend.apps.model_managment_app.create_provider_models_for_tenant', side_effect=mock_create_provider_models)

    request_data = {
        "tenant_id": "target_tenant",
        "provider": "modelengine",
        "model_type": "llm",
        "api_key": "test_api_key",
        "base_url": "https://api.modelengine.example.com"
    }
    response = client.post("/model/manage/provider/create", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.OK
    mock_create.assert_called_once_with(
        "target_tenant",
        {"provider": "modelengine", "model_type": "llm", "api_key": "test_api_key", "base_url": "https://api.modelengine.example.com"}
    )


@pytest.mark.asyncio
async def test_manage_provider_create_exception(client, auth_header, user_credentials, mocker):
    """Test provider model creation with exception."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    async def mock_create_provider_models(*args, **kwargs):
        raise Exception("Provider API error")

    mocker.patch('backend.apps.model_managment_app.create_provider_models_for_tenant', side_effect=mock_create_provider_models)

    request_data = {
        "tenant_id": "target_tenant",
        "provider": "silicon",
        "model_type": "llm",
        "api_key": "test_api_key",
        "base_url": ""
    }
    response = client.post("/model/manage/provider/create", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


@pytest.mark.asyncio
async def test_manage_provider_create_empty(client, auth_header, user_credentials, mocker):
    """Test provider model creation with empty result."""
    mocker.patch('backend.apps.model_managment_app.get_current_user_id', return_value=user_credentials)

    async def mock_create_provider_models(*args, **kwargs):
        return []

    mock_create = mocker.patch('backend.apps.model_managment_app.create_provider_models_for_tenant', side_effect=mock_create_provider_models)

    request_data = {
        "tenant_id": "target_tenant",
        "provider": "silicon",
        "model_type": "embedding",
        "api_key": "test_api_key",
        "base_url": ""
    }
    response = client.post("/model/manage/provider/create", json=request_data, headers=auth_header)

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert len(data["data"]) == 0


if __name__ == "__main__":
    pytest.main([__file__])
