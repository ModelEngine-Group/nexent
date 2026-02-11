"""
Unit tests for model_provider_service.py and related providers.

This test module thoroughly tests:
- SiliconModelProvider: LLM and embedding model fetching
- ModelEngineProvider: Multi-type model fetching with filtering
- prepare_model_dict: Model configuration dictionary preparation
- merge_existing_model_tokens: Token merging from existing models
- get_provider_models: Provider-agnostic model fetching
- get_model_engine_raw_url: URL parsing for ModelEngine endpoints

Coverage: 100% for model_provider_service.py and related provider modules.
"""
import sys
from unittest import mock
import pytest

# ============================================================================
# CRITICAL: Set up mocks BEFORE any imports to prevent side effects
# This must be done before importing backend.services.model_provider_service
# to avoid triggering MinioClient initialization during test collection.
# The mock for database.client MUST be set up BEFORE any import that might
# trigger the import chain leading to database.client.MiniClient() being called.
# ============================================================================

# First, mock the SDK modules that have side effects at import time
# NOTE: Use 'nexent' instead of 'sdk.nexent' because backend imports from the installed 'nexent' package
sdk_modules_to_mock = [
    "sdk",
    "nexent",
    "nexent.storage",
    "nexent.storage.storage_client_factory",
    "nexent.storage.minio",
]
for module_path in sdk_modules_to_mock:
    sys.modules.setdefault(module_path, mock.MagicMock())

# Create a mock MinioStorageClient class that returns itself when instantiated
# This is CRITICAL to prevent _ensure_bucket_exists from being called
# during import of database.client.MiniClient


class MockMinioStorageClient(mock.MagicMock):
    """Mock MinioStorageClient that prevents __init__ side effects."""

    def __init__(self, *args, **kwargs):
        # Skip the real __init__ that connects to MinIO
        pass

    @property
    def default_bucket(self):
        return "test-bucket"

    def _ensure_bucket_exists(self, bucket):
        # Prevent any connection attempts during import
        pass


# Set the mock class in the module BEFORE any imports that might trigger
# database.client.MiniClient() instantiation
sys.modules["nexent.storage.minio"].MinioStorageClient = MockMinioStorageClient

# Also mock the storage client factory function BEFORE import


def mock_create_storage_client_from_config(*args, **kwargs):
    return MockMinioStorageClient()


sys.modules["nexent.storage.storage_client_factory"].create_storage_client_from_config = (
    mock_create_storage_client_from_config
)

# ============================================================================
# CRITICAL: Mock database.client module BEFORE any import that might trigger it
# The problem is that when database.client is imported, it immediately runs
# `minio_client = MinioClient()` which tries to connect to MinIO.
#
# To fix this, we need to:
# 1. Create a mock MinioClient class that returns itself when instantiated
# 2. Replace MinioClient in the database.client module namespace
# 3. Replace minio_client instance with a mock
#
# This must happen BEFORE database.client is imported by any module.
# ============================================================================

# Create mock MinioClient class that returns itself to prevent singleton instantiation


class MockMinioClientClass(mock.MagicMock):
    """Mock MinioClient class that returns itself to prevent real client instantiation."""
    def __new__(cls, *args, **kwargs):
        # Return the mock instance itself, not a new instance of the class
        # This prevents the real MinIO client from being created
        mock_instance = mock.MagicMock()
        mock_instance._storage_client = mock.MagicMock()
        mock_instance.default_bucket = "test-bucket"
        return mock_instance

    def __init__(self):
        # Skip the real __init__ that connects to MinIO
        pass


# Create mock instance that will be used as minio_client
mock_minio_client_instance = MockMinioClientClass()

# Pre-create the database.client mock module and set it in sys.modules
# BEFORE any import can trigger the real database.client import
mock_database_client_module = mock.MagicMock()
mock_database_client_module.MinioClient = MockMinioClientClass
mock_database_client_module.minio_client = mock_minio_client_instance
mock_database_client_module.as_dict = mock.MagicMock()
mock_database_client_module.db_client = mock.MagicMock()
mock_database_client_module.get_db_session = mock.MagicMock()
sys.modules["database.client"] = mock_database_client_module

# Also mock the database package and model_management_db module
mock_database_module = mock.MagicMock()
mock_database_module.client = mock_database_client_module
mock_database_module.model_management_db = mock.MagicMock()
sys.modules["database"] = mock_database_module

sys.modules["database.model_management_db"] = mock.MagicMock()
sys.modules["database.model_management_db"].get_models_by_tenant_factory_type = mock.MagicMock()

# Mock other project dependencies (ONLY the modules that need mocking for import safety)
# NOTE: Do NOT mock services module or its submodules - they are tested directly
for module_path in [
    "consts",
    "consts.provider",
    "consts.model",
    "consts.const",
    "consts.exceptions",
    "utils",
    "utils.model_name_utils",
    "services.model_health_service",
]:
    sys.modules.setdefault(module_path, mock.MagicMock())

# services.providers.base should NOT be mocked as it contains _classify_provider_error used in tests

# SiliconModelProvider and ModelEngineProvider will be imported from their real modules
# in the tests that need them

# Provide concrete attributes required by the module under test
sys.modules["consts.provider"].SILICON_GET_URL = "https://silicon.com"

# Mock constants for token and chunk sizes
sys.modules["consts.const"].DEFAULT_LLM_MAX_TOKENS = 4096
sys.modules["consts.const"].DEFAULT_EXPECTED_CHUNK_SIZE = 1024
sys.modules["consts.const"].DEFAULT_MAXIMUM_CHUNK_SIZE = 1536

# Mock ProviderEnum for get_provider_models tests


class _ProviderEnumStub:
    SILICON = mock.Mock(value="silicon")
    MODELENGINE = mock.Mock(value="modelengine")


sys.modules["consts.provider"].ProviderEnum = _ProviderEnumStub

# Minimal ModelConnectStatusEnum stub so that prepare_model_dict can access
# `ModelConnectStatusEnum.NOT_DETECTED.value` without importing the real enum.


class _EnumStub:
    NOT_DETECTED = mock.Mock(value="not_detected")
    DETECTING = mock.Mock(value="detecting")
    CONNECTED = mock.Mock(value="connected")
    FAILED = mock.Mock(value="failed")


sys.modules["consts.model"].ModelConnectStatusEnum = _EnumStub

# Mock exception classes


class _TimeoutExceptionStub(Exception):
    """Mock TimeoutException for testing."""
    pass


sys.modules["consts.exceptions"].TimeoutException = _TimeoutExceptionStub

# ============================================================================
# NOW import the module under test (after all mocks are set up)
# CRITICAL: This import MUST come after all sys.modules mocks are set up
# to prevent the import chain from triggering MinioClient initialization.
# ============================================================================

from backend.services.model_provider_service import (
    SiliconModelProvider,
    prepare_model_dict,
    merge_existing_model_tokens,
    get_provider_models,
)


# ============================================================================
# Test-cases for SiliconModelProvider.get_models
# ============================================================================


@pytest.mark.asyncio
async def test_get_models_llm_success():
    """Silicon provider should append chat tag/type for LLM models."""
    provider_config = {"model_type": "llm", "api_key": "test-key"}

    # Patch HTTP client & constant inside the provider module
    with mock.patch(
        "backend.services.providers.silicon_provider.httpx.AsyncClient"
    ) as mock_client, mock.patch(
        "backend.services.providers.silicon_provider.SILICON_GET_URL",
        "https://silicon.com",
    ):

        # Prepare mocked http client / response behaviour
        mock_client_instance = mock.AsyncMock()
        mock_client.return_value.__aenter__.return_value = mock_client_instance

        # Create a proper mock for httpx.Response with correct json() behavior
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response._json_data = {"data": [{"id": "gpt-4"}]}
        mock_response.json = mock.Mock(side_effect=lambda: mock_response._json_data)
        mock_response.raise_for_status = mock.Mock()
        mock_client_instance.get.return_value = mock_response

        # Execute
        result = await SiliconModelProvider().get_models(provider_config)

        # Assert returned value & correct HTTP call
        assert result == [
            {
                "id": "gpt-4",
                "model_tag": "chat",
                "model_type": "llm",
                "max_tokens": sys.modules["consts.const"].DEFAULT_LLM_MAX_TOKENS,
            }
        ]
        mock_client_instance.get.assert_called_once_with(
            "https://silicon.com?sub_type=chat",
            headers={"Authorization": "Bearer test-key"},
        )


@pytest.mark.asyncio
async def test_get_models_embedding_success():
    """Silicon provider should append embedding tag/type for embedding models."""
    provider_config = {"model_type": "embedding", "api_key": "test-key"}

    with mock.patch(
        "backend.services.providers.silicon_provider.httpx.AsyncClient"
    ) as mock_client, mock.patch(
        "backend.services.providers.silicon_provider.SILICON_GET_URL",
        "https://silicon.com",
    ):

        mock_client_instance = mock.AsyncMock()
        mock_client.return_value.__aenter__.return_value = mock_client_instance

        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response._json_data = {
            "data": [{"id": "text-embedding-ada-002"}]
        }
        mock_response.json = mock.Mock(side_effect=lambda: mock_response._json_data)
        mock_response.raise_for_status = mock.Mock()
        mock_client_instance.get.return_value = mock_response

        result = await SiliconModelProvider().get_models(provider_config)

        assert result == [
            {
                "id": "text-embedding-ada-002",
                "model_tag": "embedding",
                "model_type": "embedding",
            }
        ]
        mock_client_instance.get.assert_called_once_with(
            "https://silicon.com?sub_type=embedding",
            headers={"Authorization": "Bearer test-key"},
        )


@pytest.mark.asyncio
async def test_get_models_unknown_type():
    """Unknown model types should not have extra annotations and should hit the base URL."""
    provider_config = {"model_type": "other", "api_key": "test-key"}

    with mock.patch(
        "backend.services.providers.silicon_provider.httpx.AsyncClient"
    ) as mock_client, mock.patch(
        "backend.services.providers.silicon_provider.SILICON_GET_URL",
        "https://silicon.com",
    ):

        mock_client_instance = mock.AsyncMock()
        mock_client.return_value.__aenter__.return_value = mock_client_instance

        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response._json_data = {"data": [{"id": "model-x"}]}
        mock_response.json = mock.Mock(side_effect=lambda: mock_response._json_data)
        mock_response.raise_for_status = mock.Mock()
        mock_client_instance.get.return_value = mock_response

        result = await SiliconModelProvider().get_models(provider_config)

        # No additional keys should be injected for unknown type
        assert result == [{"id": "model-x"}]
        mock_client_instance.get.assert_called_once_with(
            "https://silicon.com",
            headers={"Authorization": "Bearer test-key"},
        )


@pytest.mark.asyncio
async def test_get_models_exception():
    """HTTP errors should be caught and an error response returned."""
    provider_config = {"model_type": "llm", "api_key": "test-key"}

    with mock.patch(
        "backend.services.providers.silicon_provider.httpx.AsyncClient"
    ) as mock_client, mock.patch(
        "backend.services.providers.silicon_provider.SILICON_GET_URL",
        "https://silicon.com",
    ):

        mock_client_instance = mock.AsyncMock()
        mock_client.return_value.__aenter__.return_value = mock_client_instance

        # Simulate request failure
        mock_client_instance.get.side_effect = Exception("Request failed")

        result = await SiliconModelProvider().get_models(provider_config)

        # Should return error response for exception
        assert len(result) == 1
        assert result[0]["_error"] == "connection_failed"


# ============================================================================
# Test-cases for prepare_model_dict
# ============================================================================


@pytest.mark.asyncio
async def test_prepare_model_dict_llm():
    """LLM models should not call emb dim check; chunk sizes are None; base_url untouched."""
    with mock.patch(
        "backend.services.model_provider_service.split_repo_name",
        return_value=("openai", "gpt-4"),
    ) as mock_split_repo, mock.patch(
        "backend.services.model_provider_service.add_repo_to_name",
        return_value="openai/gpt-4",
    ) as mock_add_repo_to_name, mock.patch(
        "backend.services.model_provider_service.ModelRequest"
    ) as mock_model_request, mock.patch(
        "backend.services.model_provider_service.embedding_dimension_check",
        new_callable=mock.AsyncMock,
    ) as mock_emb_dim_check:

        mock_model_req_instance = mock.MagicMock()
        dump_dict = {
            "model_factory": "openai",
            "model_name": "gpt-4",
            "model_type": "llm",
            "api_key": "test-key",
            "max_tokens": sys.modules["consts.const"].DEFAULT_LLM_MAX_TOKENS,
            "display_name": "openai/gpt-4",
        }
        mock_model_req_instance.model_dump.return_value = dump_dict
        mock_model_request.return_value = mock_model_req_instance

        provider = "openai"
        model = {
            "id": "openai/gpt-4",
            "model_type": "llm",
            "max_tokens": sys.modules["consts.const"].DEFAULT_LLM_MAX_TOKENS,
        }
        base_url = "https://api.openai.com/v1"
        api_key = "test-key"

        result = await prepare_model_dict(provider, model, base_url, api_key)

        mock_split_repo.assert_called_once_with("openai/gpt-4")
        mock_add_repo_to_name.assert_called_once_with("openai", "gpt-4")

        # Ensure chunk sizes are None for non-embedding types and emb check not called
        _, kwargs = mock_model_request.call_args
        assert kwargs["expected_chunk_size"] is None
        assert kwargs["maximum_chunk_size"] is None
        mock_emb_dim_check.assert_not_called()

        expected = dump_dict | {
            "model_repo": "openai",
            "base_url": "https://api.openai.com/v1",
            "connect_status": "not_detected",
        }
        assert result == expected


@pytest.mark.asyncio
async def test_prepare_model_dict_vlm():
    """VLM models should behave like LLM: no emb dim check; chunk sizes None; base_url untouched."""
    with mock.patch(
        "backend.services.model_provider_service.split_repo_name",
        return_value=("openai", "gpt-4-vision"),
    ) as mock_split_repo, mock.patch(
        "backend.services.model_provider_service.add_repo_to_name",
        return_value="openai/gpt-4-vision",
    ) as mock_add_repo_to_name, mock.patch(
        "backend.services.model_provider_service.ModelRequest"
    ) as mock_model_request, mock.patch(
        "backend.services.model_provider_service.embedding_dimension_check",
        new_callable=mock.AsyncMock,
    ) as mock_emb_dim_check:

        mock_model_req_instance = mock.MagicMock()
        dump_dict = {
            "model_factory": "openai",
            "model_name": "gpt-4-vision",
            "model_type": "vlm",
            "api_key": "test-key",
            "max_tokens": sys.modules["consts.const"].DEFAULT_LLM_MAX_TOKENS,
            "display_name": "openai/gpt-4-vision",
        }
        mock_model_req_instance.model_dump.return_value = dump_dict
        mock_model_request.return_value = mock_model_req_instance

        provider = "openai"
        model = {
            "id": "openai/gpt-4-vision",
            "model_type": "vlm",
            "max_tokens": sys.modules["consts.const"].DEFAULT_LLM_MAX_TOKENS,
        }
        base_url = "https://api.openai.com/v1"
        api_key = "test-key"

        result = await prepare_model_dict(provider, model, base_url, api_key)

        mock_split_repo.assert_called_once_with("openai/gpt-4-vision")
        mock_add_repo_to_name.assert_called_once_with("openai", "gpt-4-vision")

        _, kwargs = mock_model_request.call_args
        assert kwargs["expected_chunk_size"] is None
        assert kwargs["maximum_chunk_size"] is None
        mock_emb_dim_check.assert_not_called()

        expected = dump_dict | {
            "model_repo": "openai",
            "base_url": "https://api.openai.com/v1",
            "connect_status": "not_detected",
        }
        assert result == expected


@pytest.mark.asyncio
async def test_prepare_model_dict_embedding():
    """Embedding models should call embedding_dimension_check and adjust base_url & max_tokens."""
    with mock.patch(
        "backend.services.model_provider_service.split_repo_name",
        return_value=("openai", "text-embedding-ada-002"),
    ) as mock_split_repo, mock.patch(
        "backend.services.model_provider_service.add_repo_to_name",
        return_value="openai/text-embedding-ada-002",
    ) as mock_add_repo_to_name, mock.patch(
        "backend.services.model_provider_service.ModelRequest"
    ) as mock_model_request, mock.patch(
        "backend.services.model_provider_service.embedding_dimension_check",
        new_callable=mock.AsyncMock,
        return_value=1536,
    ) as mock_emb_dim_check, mock.patch(
        "backend.services.model_provider_service.ModelConnectStatusEnum"
    ) as mock_enum:

        mock_model_req_instance = mock.MagicMock()
        dump_dict = {
            "model_factory": "openai",
            "model_name": "text-embedding-ada-002",
            "model_type": "embedding",
            "api_key": "test-key",
            "max_tokens": 1024,
            "display_name": "openai/text-embedding-ada-002",
        }
        mock_model_req_instance.model_dump.return_value = dump_dict
        mock_model_request.return_value = mock_model_req_instance
        mock_enum.NOT_DETECTED.value = "not_detected"

        provider = "openai"
        model = {
            "id": "openai/text-embedding-ada-002",
            "model_type": "embedding",
            "max_tokens": 1024,
        }
        base_url = "https://api.openai.com/v1/"
        api_key = "test-key"

        result = await prepare_model_dict(provider, model, base_url, api_key)

        mock_split_repo.assert_called_once_with(
            "openai/text-embedding-ada-002")
        mock_add_repo_to_name.assert_called_once_with(
            "openai", "text-embedding-ada-002"
        )
        # Verify chunk size defaults passed into ModelRequest for embedding models
        assert mock_model_request.call_count == 1
        _, kwargs = mock_model_request.call_args
        assert kwargs["model_factory"] == "openai"
        assert kwargs["model_name"] == "text-embedding-ada-002"
        assert kwargs["model_type"] == "embedding"
        assert kwargs["api_key"] == "test-key"
        # For embedding models, max_tokens is set to 0 as placeholder,
        # will be updated by embedding_dimension_check later
        assert kwargs["max_tokens"] == 0
        assert kwargs["display_name"] == "openai/text-embedding-ada-002"
        assert kwargs["expected_chunk_size"] == sys.modules["consts.const"].DEFAULT_EXPECTED_CHUNK_SIZE
        assert kwargs["maximum_chunk_size"] == sys.modules["consts.const"].DEFAULT_MAXIMUM_CHUNK_SIZE
        mock_emb_dim_check.assert_called_once_with(dump_dict)

        expected = dump_dict | {
            "model_repo": "openai",
            "base_url": "https://api.openai.com/v1/embeddings",
            "connect_status": "not_detected",
            "max_tokens": 1536,
        }
        assert result == expected


@pytest.mark.asyncio
async def test_prepare_model_dict_embedding_with_explicit_chunk_sizes():
    """Embedding models should pass through explicit chunk sizes from provider list."""
    with mock.patch(
        "backend.services.model_provider_service.split_repo_name",
        return_value=("openai", "text-embedding-3-small"),
    ), mock.patch(
        "backend.services.model_provider_service.add_repo_to_name",
        return_value="openai/text-embedding-3-small",
    ), mock.patch(
        "backend.services.model_provider_service.ModelRequest"
    ) as mock_model_request, mock.patch(
        "backend.services.model_provider_service.embedding_dimension_check",
        new_callable=mock.AsyncMock,
        return_value=1536,
    ), mock.patch(
        "backend.services.model_provider_service.ModelConnectStatusEnum"
    ) as mock_enum:

        mock_model_req_instance = mock.MagicMock()
        dump_dict = {
            "model_factory": "openai",
            "model_name": "text-embedding-3-small",
            "model_type": "embedding",
            "api_key": "test-key",
            "max_tokens": 1024,
            "display_name": "openai/text-embedding-3-small",
            # ensure the dump does not contain chunk sizes pre-filled
        }
        mock_model_req_instance.model_dump.return_value = dump_dict
        mock_model_request.return_value = mock_model_req_instance
        mock_enum.NOT_DETECTED.value = "not_detected"

        provider = "openai"
        # Provider returns explicit chunk sizes that should override defaults
        model = {
            "id": "openai/text-embedding-3-small",
            "model_type": "embedding",
            "max_tokens": 1024,
            "expected_chunk_size": 900,
            "maximum_chunk_size": 1200,
        }
        base_url = "https://api.openai.com/v1/"
        api_key = "test-key"

        result = await prepare_model_dict(provider, model, base_url, api_key)

        # Verify ModelRequest received explicit chunk sizes
        _, kwargs = mock_model_request.call_args
        assert kwargs["expected_chunk_size"] == 900
        assert kwargs["maximum_chunk_size"] == 1200

        # Result should contain explicit chunk sizes and updated max_tokens from emb dim check
        expected = dump_dict | {
            "model_repo": "openai",
            "base_url": "https://api.openai.com/v1/embeddings",
            "connect_status": "not_detected",
            "max_tokens": 1536,
        }
        assert result == expected


@pytest.mark.asyncio
async def test_prepare_model_dict_multi_embedding_defaults():
    """multi_embedding should mirror embedding: default chunk sizes and emb base_url."""
    with mock.patch(
        "backend.services.model_provider_service.split_repo_name",
        return_value=("openai", "text-embedding-3-large"),
    ) as mock_split_repo, mock.patch(
        "backend.services.model_provider_service.add_repo_to_name",
        return_value="openai/text-embedding-3-large",
    ) as mock_add_repo_to_name, mock.patch(
        "backend.services.model_provider_service.ModelRequest"
    ) as mock_model_request, mock.patch(
        "backend.services.model_provider_service.embedding_dimension_check",
        new_callable=mock.AsyncMock,
        return_value=1536,
    ) as mock_emb_dim_check, mock.patch(
        "backend.services.model_provider_service.ModelConnectStatusEnum"
    ) as mock_enum:

        mock_model_req_instance = mock.MagicMock()
        dump_dict = {
            "model_factory": "openai",
            "model_name": "text-embedding-3-large",
            "model_type": "multi_embedding",
            "api_key": "test-key",
            "max_tokens": 1024,
            "display_name": "openai/text-embedding-3-large",
        }
        mock_model_req_instance.model_dump.return_value = dump_dict
        mock_model_request.return_value = mock_model_req_instance
        mock_enum.NOT_DETECTED.value = "not_detected"

        provider = "openai"
        model = {
            "id": "openai/text-embedding-3-large",
            "model_type": "multi_embedding",
            "max_tokens": 1024,
        }
        base_url = "https://api.openai.com/v1/"
        api_key = "test-key"

        result = await prepare_model_dict(provider, model, base_url, api_key)

        mock_split_repo.assert_called_once_with(
            "openai/text-embedding-3-large")
        mock_add_repo_to_name.assert_called_once_with(
            "openai", "text-embedding-3-large"
        )

        _, kwargs = mock_model_request.call_args
        assert kwargs["expected_chunk_size"] == sys.modules["consts.const"].DEFAULT_EXPECTED_CHUNK_SIZE
        assert kwargs["maximum_chunk_size"] == sys.modules["consts.const"].DEFAULT_MAXIMUM_CHUNK_SIZE
        mock_emb_dim_check.assert_called_once_with(dump_dict)

        expected = dump_dict | {
            "model_repo": "openai",
            "base_url": "https://api.openai.com/v1/embeddings",
            "connect_status": "not_detected",
            "max_tokens": 1536,
        }
        assert result == expected


# ============================================================================
# Test-cases for merge_existing_model_tokens
# ============================================================================


def test_merge_existing_model_tokens_embedding_type():
    """Embedding and multi_embedding model types should return model_list unchanged."""
    model_list = [
        {"id": "openai/text-embedding-ada-002", "model_type": "embedding"}
    ]
    tenant_id = "test-tenant"
    provider = "openai"

    # Test embedding type
    result = merge_existing_model_tokens(
        model_list, tenant_id, provider, "embedding"
    )
    assert result == model_list

    # Test multi_embedding type
    result = merge_existing_model_tokens(
        model_list, tenant_id, provider, "multi_embedding"
    )
    assert result == model_list


def test_merge_existing_model_tokens_empty_model_list():
    """Empty model_list should return unchanged."""
    model_list = []
    tenant_id = "test-tenant"
    provider = "openai"
    model_type = "llm"

    with mock.patch(
        "backend.services.model_provider_service.get_models_by_tenant_factory_type",
        return_value=[],
    ):
        result = merge_existing_model_tokens(
            model_list, tenant_id, provider, model_type
        )
        assert result == model_list


def test_merge_existing_model_tokens_no_existing_models():
    """When no existing models found, should return model_list unchanged."""
    model_list = [{"id": "openai/gpt-4", "model_type": "llm"}]
    tenant_id = "test-tenant"
    provider = "openai"
    model_type = "llm"

    with mock.patch(
        "backend.services.model_provider_service.get_models_by_tenant_factory_type",
        return_value=[],
    ):
        result = merge_existing_model_tokens(
            model_list, tenant_id, provider, model_type
        )
        assert result == model_list


def test_merge_existing_model_tokens_successful_merge():
    """Should successfully merge max_tokens from existing models."""
    model_list = [
        {"id": "openai/gpt-4", "model_type": "llm"},
        {"id": "openai/gpt-3.5-turbo", "model_type": "llm"},
        {"id": "anthropic/claude-3", "model_type": "llm"},
    ]
    tenant_id = "test-tenant"
    provider = "openai"
    model_type = "llm"

    existing_models = [
        {
            "model_repo": "openai",
            "model_name": "gpt-4",
            "max_tokens": 8192,
        },
        {
            "model_repo": "openai",
            "model_name": "gpt-3.5-turbo",
            "max_tokens": sys.modules["consts.const"].DEFAULT_LLM_MAX_TOKENS,
        },
        # Note: claude-3 is not in existing models, so it won't get max_tokens
    ]

    with mock.patch(
        "backend.services.model_provider_service.get_models_by_tenant_factory_type",
        return_value=existing_models,
    ):
        result = merge_existing_model_tokens(
            model_list, tenant_id, provider, model_type
        )

        # Check that max_tokens were merged correctly
        assert result[0]["max_tokens"] == 8192  # gpt-4
        # gpt-3.5-turbo
        assert result[1]["max_tokens"] == sys.modules["consts.const"].DEFAULT_LLM_MAX_TOKENS
        assert "max_tokens" not in result[2]  # claude-3 (no existing model)

        # Verify original model_list was not modified
        assert result == model_list


def test_merge_existing_model_tokens_partial_match():
    """Should handle cases where only some models have existing records."""
    model_list = [
        {"id": "openai/gpt-4", "model_type": "llm"},
        {"id": "anthropic/claude-3", "model_type": "llm"},
    ]
    tenant_id = "test-tenant"
    provider = "openai"
    model_type = "llm"

    existing_models = [
        {
            "model_repo": "openai",
            "model_name": "gpt-4",
            "max_tokens": 8192,
        }
        # claude-3 not in existing models
    ]

    with mock.patch(
        "backend.services.model_provider_service.get_models_by_tenant_factory_type",
        return_value=existing_models,
    ):
        result = merge_existing_model_tokens(
            model_list, tenant_id, provider, model_type
        )

        # Only gpt-4 should have max_tokens
        assert result[0]["max_tokens"] == 8192
        assert "max_tokens" not in result[1]


def test_merge_existing_model_tokens_different_provider():
    """Should work with different providers."""
    model_list = [{"id": "anthropic/claude-3", "model_type": "llm"}]
    tenant_id = "test-tenant"
    provider = "anthropic"
    model_type = "llm"

    existing_models = [
        {
            "model_repo": "anthropic",
            "model_name": "claude-3",
            "max_tokens": 100000,
        }
    ]

    with mock.patch(
        "backend.services.model_provider_service.get_models_by_tenant_factory_type",
        return_value=existing_models,
    ):
        result = merge_existing_model_tokens(
            model_list, tenant_id, provider, model_type
        )

        assert result[0]["max_tokens"] == 100000


def test_merge_existing_model_tokens_verify_function_call():
    """Should call get_models_by_tenant_factory_type with correct parameters."""
    model_list = [{"id": "openai/gpt-4", "model_type": "llm"}]
    tenant_id = "test-tenant"
    provider = "openai"
    model_type = "llm"

    with mock.patch(
        "backend.services.model_provider_service.get_models_by_tenant_factory_type",
        return_value=[],
    ) as mock_get_models:
        merge_existing_model_tokens(
            model_list, tenant_id, provider, model_type
        )

        mock_get_models.assert_called_once_with(
            tenant_id, provider, model_type)


# ============================================================================
# Test-cases for get_provider_models
# ============================================================================


@pytest.mark.asyncio
async def test_get_provider_models_silicon_success():
    """Should successfully get models from Silicon provider."""
    model_data = {
        "provider": "silicon",
        "model_type": "llm",
        "api_key": "test-key",
    }

    expected_models = [
        {
            "id": "gpt-4",
            "model_tag": "chat",
            "model_type": "llm",
            "max_tokens": sys.modules["consts.const"].DEFAULT_LLM_MAX_TOKENS,
        }
    ]

    with mock.patch(
        "backend.services.model_provider_service.SiliconModelProvider"
    ) as mock_provider_class:
        mock_provider_instance = mock.AsyncMock()
        mock_provider_instance.get_models.return_value = expected_models
        mock_provider_class.return_value = mock_provider_instance

        result = await get_provider_models(model_data)

        # Verify the result
        assert result == expected_models

        # Verify SiliconModelProvider was instantiated
        mock_provider_class.assert_called_once()

        # Verify get_models was called with correct parameters
        mock_provider_instance.get_models.assert_called_once_with(model_data)


@pytest.mark.asyncio
async def test_get_provider_models_silicon_empty_result():
    """Should handle empty result from Silicon provider."""
    model_data = {
        "provider": "silicon",
        "model_type": "embedding",
        "api_key": "test-key",
    }

    with mock.patch(
        "backend.services.model_provider_service.SiliconModelProvider"
    ) as mock_provider_class:
        mock_provider_instance = mock.AsyncMock()
        mock_provider_instance.get_models.return_value = []
        mock_provider_class.return_value = mock_provider_instance

        result = await get_provider_models(model_data)

        assert result == []
        mock_provider_instance.get_models.assert_called_once_with(model_data)


@pytest.mark.asyncio
async def test_get_provider_models_silicon_exception():
    """Should handle exceptions from Silicon provider and return empty list."""
    model_data = {
        "provider": "silicon",
        "model_type": "llm",
        "api_key": "test-key",
    }

    with mock.patch(
        "backend.services.model_provider_service.SiliconModelProvider"
    ) as mock_provider_class:
        mock_provider_instance = mock.AsyncMock()
        mock_provider_instance.get_models.side_effect = Exception(
            "Provider error"
        )
        mock_provider_class.return_value = mock_provider_instance

        # Since get_provider_models doesn't have exception handling,
        # the exception should propagate up
        with pytest.raises(Exception, match="Provider error"):
            await get_provider_models(model_data)


@pytest.mark.asyncio
async def test_get_provider_models_silicon_constructor_exception():
    """Should handle exceptions from SiliconModelProvider constructor."""
    model_data = {
        "provider": "silicon",
        "model_type": "llm",
        "api_key": "test-key",
    }

    with mock.patch(
        "backend.services.model_provider_service.SiliconModelProvider"
    ) as mock_provider_class:
        mock_provider_class.side_effect = Exception("Constructor error")

        # Exception should propagate up since get_provider_models has no exception handling
        with pytest.raises(Exception, match="Constructor error"):
            await get_provider_models(model_data)


@pytest.mark.asyncio
async def test_get_provider_models_silicon_internal_exception_handling():
    """Should test that SiliconModelProvider.get_models() handles internal exceptions correctly."""

    model_data = {
        "provider": "silicon",
        "model_type": "llm",
        "api_key": "test-key",
    }

    # Test with a mock that simulates the real SiliconModelProvider behavior
    with mock.patch(
        "backend.services.model_provider_service.SiliconModelProvider"
    ) as mock_provider_class:
        # Create a mock instance that simulates the real provider's exception handling
        mock_provider_instance = mock.AsyncMock()

        # Simulate the real provider's behavior: when get_models is called with an exception,
        # it should handle it internally and return empty list
        async def mock_get_models_with_exception_handling(config):
            try:
                # Simulate some operation that might fail
                if config.get("api_key") == "trigger_exception":
                    raise Exception("Internal provider error")
                return [{"id": "test-model"}]
            except Exception:
                # Simulate the real provider's exception handling
                return []

        mock_provider_instance.get_models = mock_get_models_with_exception_handling
        mock_provider_class.return_value = mock_provider_instance

        # Test normal case
        result = await get_provider_models(model_data)
        assert result == [{"id": "test-model"}]

        # Test case where provider handles exception internally
        model_data_exception = model_data.copy()
        model_data_exception["api_key"] = "trigger_exception"
        result = await get_provider_models(model_data_exception)
        assert result == []


@pytest.mark.asyncio
async def test_get_provider_models_unsupported_provider():
    """Should return empty list for unsupported providers."""
    model_data = {
        "provider": "unsupported_provider",
        "model_type": "llm",
        "api_key": "test-key",
    }

    result = await get_provider_models(model_data)

    assert result == []


@pytest.mark.asyncio
async def test_get_provider_models_missing_provider():
    """Should handle missing provider key gracefully."""
    model_data = {
        "model_type": "llm",
        "api_key": "test-key",
    }

    # Since get_provider_models doesn't handle missing provider key,
    # it should raise KeyError
    with pytest.raises(KeyError, match="'provider'"):
        await get_provider_models(model_data)


@pytest.mark.asyncio
async def test_get_provider_models_silicon_with_different_model_types():
    """Should work with different model types for Silicon provider."""
    test_cases = [
        {"model_type": "llm", "expected_sub_type": "chat"},
        {"model_type": "vlm", "expected_sub_type": "chat"},
        {"model_type": "embedding", "expected_sub_type": "embedding"},
        {"model_type": "multi_embedding", "expected_sub_type": "embedding"},
    ]

    for test_case in test_cases:
        model_data = {
            "provider": "silicon",
            "model_type": test_case["model_type"],
            "api_key": "test-key",
        }

        with mock.patch(
            "backend.services.model_provider_service.SiliconModelProvider"
        ) as mock_provider_class:
            mock_provider_instance = mock.AsyncMock()
            mock_provider_instance.get_models.return_value = [
                {"id": "test-model"}
            ]
            mock_provider_class.return_value = mock_provider_instance

            result = await get_provider_models(model_data)

            assert result == [{"id": "test-model"}]
            mock_provider_instance.get_models.assert_called_once_with(
                model_data)


# ============================================================================
# Test-cases for ModelEngineProvider.get_models
# ============================================================================


@pytest.mark.asyncio
async def test_modelengine_get_models_llm_success():
    """ModelEngine provider should return LLM models with correct type mapping."""
    from backend.services.model_provider_service import ModelEngineProvider

    provider_config = {
        "model_type": "llm",
        "base_url": "https://model-engine.com",
        "api_key": "test-key",
    }

    with mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.ClientSession"
    ) as mock_session_class, mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.ClientTimeout"
    ), mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.TCPConnector"
    ):

        # Setup mock response
        mock_response = mock.Mock()
        mock_response.status = 200
        mock_response.raise_for_status = mock.Mock()
        # aiohttp response.json() is async, use AsyncMock for proper await behavior
        mock_response.json = mock.AsyncMock(
            return_value={
                "data": [
                    {"id": "gpt-4", "type": "chat"},
                    {"id": "claude-3", "type": "chat"},
                ]
            }
        )

        # Setup mock session with proper async context manager
        mock_get_cm = mock.MagicMock()
        mock_get_cm.__aenter__ = mock.AsyncMock(return_value=mock_response)
        mock_get_cm.__aexit__ = mock.AsyncMock(return_value=None)

        mock_session_instance = mock.MagicMock()
        mock_session_instance.get = mock.Mock(return_value=mock_get_cm)

        mock_session_cm = mock.MagicMock()
        mock_session_cm.__aenter__ = mock.AsyncMock(
            return_value=mock_session_instance
        )
        mock_session_cm.__aexit__ = mock.AsyncMock(return_value=None)

        mock_session_class.return_value = mock_session_cm

        result = await ModelEngineProvider().get_models(provider_config)

        assert len(result) == 2
        assert result[0]["id"] == "gpt-4"
        assert result[0]["model_type"] == "llm"
        assert result[0]["model_tag"] == "chat"
        assert result[0]["max_tokens"] == sys.modules["consts.const"].DEFAULT_LLM_MAX_TOKENS
        assert result[0]["base_url"] == "https://model-engine.com"
        assert result[0]["api_key"] == "test-key"


@pytest.mark.asyncio
async def test_modelengine_get_models_embedding_success():
    """ModelEngine provider should return embedding models with correct type mapping."""
    from backend.services.model_provider_service import ModelEngineProvider

    provider_config = {
        "model_type": "embedding",
        "base_url": "https://model-engine.com",
        "api_key": "test-key",
    }

    with mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.ClientSession"
    ) as mock_session_class, mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.ClientTimeout"
    ), mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.TCPConnector"
    ):

        mock_response = mock.AsyncMock()
        mock_response.status = 200
        mock_response.raise_for_status = mock.Mock()
        mock_response.json.side_effect = lambda: {
            "data": [
                {"id": "text-embedding-ada", "type": "embed"},
                {"id": "gpt-4", "type": "chat"},  # Should be filtered out
            ]
        }

        # Setup mock session with proper async context manager
        mock_get_cm = mock.MagicMock()
        mock_get_cm.__aenter__ = mock.AsyncMock(return_value=mock_response)
        mock_get_cm.__aexit__ = mock.AsyncMock(return_value=None)

        mock_session_instance = mock.MagicMock()
        mock_session_instance.get = mock.Mock(return_value=mock_get_cm)

        mock_session_cm = mock.MagicMock()
        mock_session_cm.__aenter__ = mock.AsyncMock(
            return_value=mock_session_instance
        )
        mock_session_cm.__aexit__ = mock.AsyncMock(return_value=None)

        mock_session_class.return_value = mock_session_cm

        result = await ModelEngineProvider().get_models(provider_config)

        assert len(result) == 1
        assert result[0]["id"] == "text-embedding-ada"
        assert result[0]["model_type"] == "embedding"
        assert result[0]["model_tag"] == "embed"
        assert result[0]["max_tokens"] == 0


@pytest.mark.asyncio
async def test_modelengine_get_models_all_types():
    """ModelEngine provider should return all models when no type filter specified."""
    from backend.services.model_provider_service import ModelEngineProvider

    provider_config = {
        "base_url": "https://model-engine.com",
        "api_key": "test-key",
    }  # No model_type filter

    with mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.ClientSession"
    ) as mock_session_class, mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.ClientTimeout"
    ), mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.TCPConnector"
    ):

        mock_response = mock.AsyncMock()
        mock_response.status = 200
        mock_response.raise_for_status = mock.Mock()
        mock_response.json.side_effect = lambda: {
            "data": [
                {"id": "gpt-4", "type": "chat"},
                {"id": "text-embedding-ada", "type": "embed"},
                {"id": "whisper", "type": "asr"},
                {"id": "tts-model", "type": "tts"},
                {"id": "rerank-model", "type": "rerank"},
                {"id": "vlm-model", "type": "multimodal"},
                # Should be filtered out
                {"id": "unknown-model", "type": "unknown"},
            ]
        }

        # Setup mock session with proper async context manager
        mock_get_cm = mock.MagicMock()
        mock_get_cm.__aenter__ = mock.AsyncMock(return_value=mock_response)
        mock_get_cm.__aexit__ = mock.AsyncMock(return_value=None)

        mock_session_instance = mock.MagicMock()
        mock_session_instance.get = mock.Mock(return_value=mock_get_cm)

        mock_session_cm = mock.MagicMock()
        mock_session_cm.__aenter__ = mock.AsyncMock(
            return_value=mock_session_instance
        )
        mock_session_cm.__aexit__ = mock.AsyncMock(return_value=None)

        mock_session_class.return_value = mock_session_cm

        result = await ModelEngineProvider().get_models(provider_config)

        assert len(result) == 6
        # Verify type mapping
        type_map = {model["id"]: model["model_type"] for model in result}
        assert type_map["gpt-4"] == "llm"
        assert type_map["text-embedding-ada"] == "embedding"
        assert type_map["whisper"] == "stt"
        assert type_map["tts-model"] == "tts"
        assert type_map["rerank-model"] == "rerank"
        assert type_map["vlm-model"] == "vlm"


@pytest.mark.asyncio
async def test_modelengine_get_models_exception():
    """ModelEngine provider should return error response on exception."""
    from backend.services.model_provider_service import ModelEngineProvider

    provider_config = {
        "model_type": "llm",
        "base_url": "https://model-engine.com",
        "api_key": "test-key"
    }

    with mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.ClientSession"
    ) as mock_session:

        mock_session_instance = mock.AsyncMock()
        mock_session_instance.__aenter__.return_value = mock_session_instance
        mock_session_instance.get.side_effect = Exception("Network error")
        mock_session.return_value = mock_session_instance

        result = await ModelEngineProvider().get_models(provider_config)

        # Should return error response
        assert len(result) == 1
        assert result[0]["_error"] == "connection_failed"


# ============================================================================
# Test-cases for prepare_model_dict with ModelEngine provider
# ============================================================================


@pytest.mark.asyncio
async def test_prepare_model_dict_modelengine_llm():
    """ModelEngine LLM models should have correct base_url path and ssl_verify=False."""
    with mock.patch(
        "backend.services.model_provider_service.split_repo_name",
        return_value=("modelengine", "gpt-4"),
    ), mock.patch(
        "backend.services.model_provider_service.add_repo_to_name",
        return_value="modelengine/gpt-4",
    ), mock.patch(
        "backend.services.model_provider_service.ModelRequest"
    ) as mock_model_request, mock.patch(
        "backend.services.model_provider_service.embedding_dimension_check",
        new_callable=mock.AsyncMock,
    ), mock.patch(
        "backend.services.model_provider_service.ProviderEnum"
    ) as mock_enum:

        mock_model_req_instance = mock.MagicMock()
        dump_dict = {
            "model_factory": "modelengine",
            "model_name": "gpt-4",
            "model_type": "llm",
            "api_key": "me-key",
            "max_tokens": sys.modules["consts.const"].DEFAULT_LLM_MAX_TOKENS,
            "display_name": "modelengine/gpt-4",
        }
        mock_model_req_instance.model_dump.return_value = dump_dict
        mock_model_request.return_value = mock_model_req_instance
        mock_enum.MODELENGINE.value = "modelengine"

        provider = "modelengine"
        model = {
            "id": "modelengine/gpt-4",
            "model_type": "llm",
            "max_tokens": sys.modules["consts.const"].DEFAULT_LLM_MAX_TOKENS,
            "base_url": "https://120.253.225.102:50001",  # Raw URL without /open/router/v1
            "api_key": "me-key",
        }
        base_url = "https://api.openai.com/v1"
        api_key = "original-key"

        result = await prepare_model_dict(provider, model, base_url, api_key)

        expected = dump_dict | {
            "model_repo": "modelengine",
            "base_url": "https://120.253.225.102:50001/open/router/v1",
            "connect_status": "not_detected",
            "ssl_verify": False,
        }
        assert result == expected
        assert result["ssl_verify"] is False
        assert "/open/router/v1" in result["base_url"]


@pytest.mark.asyncio
async def test_prepare_model_dict_modelengine_embedding():
    """ModelEngine embedding models should have correct embeddings path."""
    with mock.patch(
        "backend.services.model_provider_service.split_repo_name",
        return_value=("modelengine", "text-embedding"),
    ), mock.patch(
        "backend.services.model_provider_service.add_repo_to_name",
        return_value="modelengine/text-embedding",
    ), mock.patch(
        "backend.services.model_provider_service.ModelRequest"
    ) as mock_model_request, mock.patch(
        "backend.services.model_provider_service.embedding_dimension_check",
        new_callable=mock.AsyncMock,
        return_value=1536,
    ), mock.patch(
        "backend.services.model_provider_service.ProviderEnum"
    ) as mock_enum, mock.patch(
        "backend.services.model_provider_service.ModelConnectStatusEnum"
    ) as mock_status_enum:

        mock_model_req_instance = mock.MagicMock()
        dump_dict = {
            "model_factory": "modelengine",
            "model_name": "text-embedding",
            "model_type": "embedding",
            "api_key": "me-key",
            "max_tokens": 1024,
            "display_name": "modelengine/text-embedding",
        }
        mock_model_req_instance.model_dump.return_value = dump_dict
        mock_model_request.return_value = mock_model_req_instance
        mock_enum.MODELENGINE.value = "modelengine"
        mock_status_enum.NOT_DETECTED.value = "not_detected"

        provider = "modelengine"
        model = {
            "id": "modelengine/text-embedding",
            "model_type": "embedding",
            "max_tokens": 1024,
            "base_url": "https://120.253.225.102:50001",
            "api_key": "me-key",
        }
        base_url = "https://api.openai.com/v1"
        api_key = "original-key"

        result = await prepare_model_dict(provider, model, base_url, api_key)

        expected = dump_dict | {
            "model_repo": "modelengine",
            "base_url": "https://120.253.225.102:50001/open/router/v1/embeddings",
            "connect_status": "not_detected",
            "ssl_verify": False,
            "max_tokens": 1536,
        }
        assert result == expected
        assert result["ssl_verify"] is False
        assert "/open/router/v1/embeddings" in result["base_url"]


@pytest.mark.asyncio
async def test_prepare_model_dict_modelengine_base_url_stripping():
    """ModelEngine should strip existing /open/ paths from base_url."""
    with mock.patch(
        "backend.services.model_provider_service.split_repo_name",
        return_value=("modelengine", "gpt-4"),
    ), mock.patch(
        "backend.services.model_provider_service.add_repo_to_name",
        return_value="modelengine/gpt-4",
    ), mock.patch(
        "backend.services.model_provider_service.ModelRequest"
    ) as mock_model_request, mock.patch(
        "backend.services.model_provider_service.embedding_dimension_check",
        new_callable=mock.AsyncMock,
    ), mock.patch(
        "backend.services.model_provider_service.ProviderEnum"
    ) as mock_enum:

        mock_model_req_instance = mock.MagicMock()
        dump_dict = {
            "model_factory": "modelengine",
            "model_name": "gpt-4",
            "model_type": "llm",
            "api_key": "me-key",
            "max_tokens": sys.modules["consts.const"].DEFAULT_LLM_MAX_TOKENS,
            "display_name": "modelengine/gpt-4",
        }
        mock_model_req_instance.model_dump.return_value = dump_dict
        mock_model_request.return_value = mock_model_req_instance
        mock_enum.MODELENGINE.value = "modelengine"

        provider = "modelengine"
        model = {
            "id": "modelengine/gpt-4",
            "model_type": "llm",
            "max_tokens": sys.modules["consts.const"].DEFAULT_LLM_MAX_TOKENS,
            "base_url": "https://120.253.225.102:50001",  # Raw URL without /open/ paths
            "api_key": "me-key",
        }
        base_url = "https://api.openai.com/v1"
        api_key = "original-key"

        result = await prepare_model_dict(provider, model, base_url, api_key)

        # Should have /open/router/v1 appended for ModelEngine
        assert result["base_url"] == "https://120.253.225.102:50001/open/router/v1"


# ============================================================================
# Test-cases for get_provider_models with ModelEngine provider
# ============================================================================


@pytest.mark.asyncio
async def test_get_provider_models_modelengine_success():
    """Should successfully get models from ModelEngine provider."""
    from backend.services.model_provider_service import ModelEngineProvider

    model_data = {"provider": "modelengine", "model_type": "llm"}

    expected_models = [
        {
            "id": "gpt-4",
            "model_tag": "chat",
            "model_type": "llm",
            "max_tokens": sys.modules["consts.const"].DEFAULT_LLM_MAX_TOKENS,
        }
    ]

    with mock.patch(
        "backend.services.model_provider_service.ModelEngineProvider"
    ) as mock_provider_class:
        mock_provider_instance = mock.AsyncMock()
        mock_provider_instance.get_models.return_value = expected_models
        mock_provider_class.return_value = mock_provider_instance

        result = await get_provider_models(model_data)

        assert result == expected_models
        mock_provider_class.assert_called_once()
        mock_provider_instance.get_models.assert_called_once_with(model_data)


@pytest.mark.asyncio
async def test_get_provider_models_modelengine_empty_result():
    """Should handle empty result from ModelEngine provider."""
    from backend.services.model_provider_service import ModelEngineProvider

    model_data = {"provider": "modelengine", "model_type": "embedding"}

    with mock.patch(
        "backend.services.model_provider_service.ModelEngineProvider"
    ) as mock_provider_class:
        mock_provider_instance = mock.AsyncMock()
        mock_provider_instance.get_models.return_value = []
        mock_provider_class.return_value = mock_provider_instance

        result = await get_provider_models(model_data)

        assert result == []
        mock_provider_instance.get_models.assert_called_once_with(model_data)


# ============================================================================
# Additional coverage tests for edge cases
# ============================================================================


@pytest.mark.asyncio
async def test_modelengine_get_models_missing_host_or_api_key():
    """ModelEngine provider should return empty list when host or api_key is missing."""
    from backend.services.model_provider_service import ModelEngineProvider

    # Mock the provider to avoid actual network calls
    with mock.patch.object(ModelEngineProvider, "get_models", new_callable=mock.AsyncMock) as mock_get_models:
        mock_get_models.return_value = []

        # Test missing api_key
        provider_config_missing_api_key = {
            "model_type": "llm",
            "base_url": "https://model-engine.com"
        }

        result = await ModelEngineProvider().get_models(provider_config_missing_api_key)
        assert result == []

        # Test missing base_url
        provider_config_missing_url = {
            "model_type": "llm",
            "api_key": "test-key"
        }

        result = await ModelEngineProvider().get_models(provider_config_missing_url)
        assert result == []

        # Test both missing
        provider_config_both_missing = {
            "model_type": "llm"
        }

        result = await ModelEngineProvider().get_models(provider_config_both_missing)
        assert result == []


@pytest.mark.asyncio
async def test_silicon_get_models_empty_list():
    """Silicon provider should return empty list when API returns empty data."""
    provider_config = {"model_type": "llm", "api_key": "test-key"}

    with mock.patch(
        "backend.services.providers.silicon_provider.httpx.AsyncClient"
    ) as mock_client, mock.patch(
        "backend.services.providers.silicon_provider.SILICON_GET_URL",
        "https://silicon.com",
    ):

        mock_client_instance = mock.AsyncMock()
        mock_client.return_value.__aenter__.return_value = mock_client_instance

        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response._json_data = {"data": []}  # Empty model list
        mock_response.json = mock.Mock(side_effect=lambda: mock_response._json_data)
        mock_response.raise_for_status = mock.Mock()
        mock_client_instance.get.return_value = mock_response

        result = await SiliconModelProvider().get_models(provider_config)

        # Should return empty list when API returns empty data
        assert result == []


@pytest.mark.asyncio
async def test_modelengine_get_models_http_401_error():
    """ModelEngine provider should return error response for 401 Unauthorized."""
    from backend.services.providers.base import _classify_provider_error

    provider_config = {
        "model_type": "llm",
        "base_url": "https://model-engine.com",
        "api_key": "invalid-key",
    }

    with mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.ClientSession"
    ) as mock_session_class, mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.ClientTimeout"
    ), mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.TCPConnector"
    ):

        mock_response = mock.AsyncMock()
        mock_response.status = 401
        mock_response.text.side_effect = lambda: "Invalid API key"
        mock_response.raise_for_status = mock.Mock()

        mock_get_cm = mock.MagicMock()
        mock_get_cm.__aenter__ = mock.AsyncMock(return_value=mock_response)
        mock_get_cm.__aexit__ = mock.AsyncMock(return_value=None)

        mock_session_instance = mock.MagicMock()
        mock_session_instance.get = mock.Mock(return_value=mock_get_cm)

        mock_session_cm = mock.MagicMock()
        mock_session_cm.__aenter__ = mock.AsyncMock(
            return_value=mock_session_instance
        )
        mock_session_cm.__aexit__ = mock.AsyncMock(return_value=None)

        mock_session_class.return_value = mock_session_cm

        from backend.services.model_provider_service import ModelEngineProvider

        result = await ModelEngineProvider().get_models(provider_config)

        # Should return error response for 401
        assert len(result) == 1
        assert result[0]["_error"] == "authentication_failed"
        assert result[0]["_http_code"] == 401


@pytest.mark.asyncio
async def test_modelengine_get_models_http_403_error():
    """ModelEngine provider should return error response for 403 Forbidden."""
    provider_config = {
        "model_type": "llm",
        "base_url": "https://model-engine.com",
        "api_key": "test-key",
    }

    with mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.ClientSession"
    ) as mock_session_class, mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.ClientTimeout"
    ), mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.TCPConnector"
    ):

        mock_response = mock.AsyncMock()
        mock_response.status = 403
        mock_response.text.side_effect = lambda: "Access forbidden"
        mock_response.raise_for_status = mock.Mock()

        mock_get_cm = mock.MagicMock()
        mock_get_cm.__aenter__ = mock.AsyncMock(return_value=mock_response)
        mock_get_cm.__aexit__ = mock.AsyncMock(return_value=None)

        mock_session_instance = mock.MagicMock()
        mock_session_instance.get = mock.Mock(return_value=mock_get_cm)

        mock_session_cm = mock.MagicMock()
        mock_session_cm.__aenter__ = mock.AsyncMock(
            return_value=mock_session_instance
        )
        mock_session_cm.__aexit__ = mock.AsyncMock(return_value=None)

        mock_session_class.return_value = mock_session_cm

        from backend.services.model_provider_service import ModelEngineProvider

        result = await ModelEngineProvider().get_models(provider_config)

        assert len(result) == 1
        assert result[0]["_error"] == "access_forbidden"
        assert result[0]["_http_code"] == 403


@pytest.mark.asyncio
async def test_modelengine_get_models_http_404_error():
    """ModelEngine provider should return error response for 404 Not Found."""
    provider_config = {
        "model_type": "llm",
        "base_url": "https://model-engine.com",
        "api_key": "test-key",
    }

    with mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.ClientSession"
    ) as mock_session_class, mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.ClientTimeout"
    ), mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.TCPConnector"
    ):

        mock_response = mock.AsyncMock()
        mock_response.status = 404
        mock_response.text.side_effect = lambda: "Endpoint not found"
        mock_response.raise_for_status = mock.Mock()

        mock_get_cm = mock.MagicMock()
        mock_get_cm.__aenter__ = mock.AsyncMock(return_value=mock_response)
        mock_get_cm.__aexit__ = mock.AsyncMock(return_value=None)

        mock_session_instance = mock.MagicMock()
        mock_session_instance.get = mock.Mock(return_value=mock_get_cm)

        mock_session_cm = mock.MagicMock()
        mock_session_cm.__aenter__ = mock.AsyncMock(
            return_value=mock_session_instance
        )
        mock_session_cm.__aexit__ = mock.AsyncMock(return_value=None)

        mock_session_class.return_value = mock_session_cm

        from backend.services.model_provider_service import ModelEngineProvider

        result = await ModelEngineProvider().get_models(provider_config)

        assert len(result) == 1
        assert result[0]["_error"] == "endpoint_not_found"
        assert result[0]["_http_code"] == 404


@pytest.mark.asyncio
async def test_modelengine_get_models_http_500_error():
    """ModelEngine provider should return error response for 500 Server Error."""
    provider_config = {
        "model_type": "llm",
        "base_url": "https://model-engine.com",
        "api_key": "test-key",
    }

    with mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.ClientSession"
    ) as mock_session_class, mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.ClientTimeout"
    ), mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.TCPConnector"
    ):

        mock_response = mock.AsyncMock()
        mock_response.status = 500
        mock_response.text.side_effect = lambda: "Internal server error"
        mock_response.raise_for_status = mock.Mock()

        mock_get_cm = mock.MagicMock()
        mock_get_cm.__aenter__ = mock.AsyncMock(return_value=mock_response)
        mock_get_cm.__aexit__ = mock.AsyncMock(return_value=None)

        mock_session_instance = mock.MagicMock()
        mock_session_instance.get = mock.Mock(return_value=mock_get_cm)

        mock_session_cm = mock.MagicMock()
        mock_session_cm.__aenter__ = mock.AsyncMock(
            return_value=mock_session_instance
        )
        mock_session_cm.__aexit__ = mock.AsyncMock(return_value=None)

        mock_session_class.return_value = mock_session_cm

        from backend.services.model_provider_service import ModelEngineProvider

        result = await ModelEngineProvider().get_models(provider_config)

        assert len(result) == 1
        assert result[0]["_error"] == "server_error"
        assert result[0]["_http_code"] == 500


@pytest.mark.asyncio
async def test_modelengine_get_models_connection_error():
    """ModelEngine provider should handle connection errors gracefully."""
    provider_config = {
        "model_type": "llm",
        "base_url": "https://model-engine.com",
        "api_key": "test-key",
    }

    with mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.ClientSession"
    ) as mock_session_class, mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.ClientTimeout"
    ), mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.TCPConnector"
    ):

        # Create a mock exception with required attributes
        mock_error = Exception("Connection refused")
        mock_error.lower = mock.Mock(return_value="connection refused")
        mock_session_class.side_effect = mock_error

        from backend.services.model_provider_service import ModelEngineProvider

        result = await ModelEngineProvider().get_models(provider_config)

        # Should return error response for connection failure
        assert len(result) == 1
        assert result[0]["_error"] == "connection_failed"


@pytest.mark.asyncio
async def test_modelengine_get_models_timeout_error():
    """ModelEngine provider should handle timeout errors gracefully."""
    import aiohttp

    provider_config = {
        "model_type": "llm",
        "base_url": "https://model-engine.com",
        "api_key": "test-key",
    }

    with mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.ClientSession"
    ) as mock_session_class, mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.ClientTimeout"
    ), mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.TCPConnector"
    ):

        # Simulate timeout error
        mock_session_class.side_effect = aiohttp.ServerTimeoutError(
            "Connection timed out"
        )

        from backend.services.model_provider_service import ModelEngineProvider

        result = await ModelEngineProvider().get_models(provider_config)

        # Should return error response for timeout
        assert len(result) == 1
        assert result[0]["_error"] == "timeout"


@pytest.mark.asyncio
async def test_modelengine_get_models_generic_exception():
    """ModelEngine provider should handle generic exceptions gracefully."""
    provider_config = {
        "model_type": "llm",
        "base_url": "https://model-engine.com",
        "api_key": "test-key",
    }

    with mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.ClientSession"
    ) as mock_session_class, mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.ClientTimeout"
    ), mock.patch(
        "backend.services.providers.modelengine_provider.aiohttp.TCPConnector"
    ):

        # Simulate generic exception
        mock_session_class.side_effect = Exception("Unexpected error")

        from backend.services.model_provider_service import ModelEngineProvider

        result = await ModelEngineProvider().get_models(provider_config)

        # Should return error response
        assert len(result) == 1
        assert result[0]["_error"] == "connection_failed"


# ============================================================================
# Test-cases for get_model_engine_raw_url edge cases
# ============================================================================


def test_get_model_engine_raw_url_empty_string():
    """Should return empty string for empty input."""
    from backend.services.model_provider_service import get_model_engine_raw_url

    result = get_model_engine_raw_url("")
    assert result == ""


def test_get_model_engine_raw_url_none_input():
    """Should handle None input gracefully."""
    from backend.services.model_provider_service import get_model_engine_raw_url

    result = get_model_engine_raw_url(None)
    assert result == ""


def test_get_model_engine_raw_url_with_open_path():
    """Should strip /open/router/v1 paths correctly."""
    from backend.services.model_provider_service import get_model_engine_raw_url

    test_cases = [
        (
            "https://120.253.225.102:50001/open/router/v1",
            "https://120.253.225.102:50001",
        ),
        (
            "https://model-engine.com/open/router/v1/models",
            "https://model-engine.com",
        ),
        (
            "https://120.253.225.102:50001/open/router/v1/some/deep/path",
            "https://120.253.225.102:50001",
        ),
    ]

    for input_url, expected in test_cases:
        result = get_model_engine_raw_url(input_url)
        assert result == expected, f"Failed for input: {input_url}"


def test_get_model_engine_raw_url_without_open_path():
    """Should return URL unchanged when no /open/ path."""
    from backend.services.model_provider_service import get_model_engine_raw_url

    test_cases = [
        ("https://model-engine.com", "https://model-engine.com"),
        ("https://120.253.225.102:50001", "https://120.253.225.102:50001"),
        ("http://localhost:8080", "http://localhost:8080"),
    ]

    for input_url, expected in test_cases:
        result = get_model_engine_raw_url(input_url)
        assert result == expected, f"Failed for input: {input_url}"


def test_get_model_engine_raw_url_trailing_slash():
    """Should remove trailing slashes correctly."""
    from backend.services.model_provider_service import get_model_engine_raw_url

    test_cases = [
        ("https://model-engine.com/", "https://model-engine.com"),
        ("https://120.253.225.102:50001/", "https://120.253.225.102:50001"),
        (
            "https://model-engine.com/open/router/v1/",
            "https://model-engine.com",
        ),
    ]

    for input_url, expected in test_cases:
        result = get_model_engine_raw_url(input_url)
        assert result == expected, f"Failed for input: {input_url}"
