import sys
import pytest
from unittest.mock import MagicMock

# Setup common mocks
from test.common.test_mocks import setup_common_mocks, patch_minio_client_initialization

# Initialize common mocks
mocks = setup_common_mocks()

# Mock the specific database modules that datamate_service imports
knowledge_db_mock = MagicMock()
knowledge_db_mock.upsert_knowledge_record = MagicMock()
knowledge_db_mock.get_knowledge_info_by_tenant_and_source = MagicMock()
knowledge_db_mock.delete_knowledge_record = MagicMock()

# Mock database client and models
database_client_mock = MagicMock()
database_client_mock.get_db_session = MagicMock()

database_models_mock = MagicMock()
database_models_mock.TenantConfig = MagicMock()

# Mock database functions
tenant_config_db_mock = MagicMock()
tenant_config_db_mock.get_all_configs_by_tenant_id = MagicMock()
tenant_config_db_mock.get_single_config_info = MagicMock()
tenant_config_db_mock.insert_config = MagicMock()
tenant_config_db_mock.delete_config_by_tenant_config_id = MagicMock()
tenant_config_db_mock.update_config_by_tenant_config_id_and_data = MagicMock()

model_management_db_mock = MagicMock()
model_management_db_mock.get_model_by_model_id = MagicMock()

# Mock the nexent modules
datamate_core_mock = MagicMock()

# Mock consts
consts_mock = MagicMock()
consts_mock.DATAMATE_URL = "DATAMATE_URL"

# Mock sqlalchemy
sqlalchemy_mock = MagicMock()
sqlalchemy_exc_mock = MagicMock()
sqlalchemy_exc_mock.SQLAlchemyError = Exception
sqlalchemy_sql_mock = MagicMock()
sqlalchemy_sql_mock.func = MagicMock()

sqlalchemy_mock.exc = sqlalchemy_exc_mock
sqlalchemy_mock.sql = sqlalchemy_sql_mock

# Set up sys.modules mocks
sys.modules['database.knowledge_db'] = knowledge_db_mock
sys.modules['database.client'] = database_client_mock
sys.modules['database.db_models'] = database_models_mock
sys.modules['database.tenant_config_db'] = tenant_config_db_mock
sys.modules['database.model_management_db'] = model_management_db_mock
sys.modules['nexent.vector_database.datamate_core'] = datamate_core_mock
sys.modules['consts.const'] = consts_mock
sys.modules['sqlalchemy'] = sqlalchemy_mock
sys.modules['sqlalchemy.exc'] = sqlalchemy_exc_mock
sys.modules['sqlalchemy.sql'] = sqlalchemy_sql_mock

# Patch storage factory before importing the module under test
with patch_minio_client_initialization():
    from backend.services.datamate_service import (
        fetch_datamate_knowledge_base_file_list,
        sync_datamate_knowledge_bases_and_create_records,
        _get_datamate_core,
        _create_datamate_knowledge_records
    )


@pytest.fixture
def mock_datamate_sync_setup(monkeypatch):
    """Fixture to set up common mocks for DataMate sync tests."""
    # Mock MODEL_ENGINE_ENABLED
    monkeypatch.setattr(
        "backend.services.datamate_service.MODEL_ENGINE_ENABLED", "true"
    )

    # Mock tenant_config_manager to return a valid DataMate URL
    mock_config_manager = MagicMock()
    mock_config_manager.get_app_config.return_value = "http://datamate.example.com"
    monkeypatch.setattr(
        "backend.services.datamate_service.tenant_config_manager", mock_config_manager
    )

    return mock_config_manager


class FakeClient:
    def __init__(self, base_url=None):
        self.base_url = base_url

    def list_knowledge_bases(self):
        return [{"id": "kb1", "name": "KB1"}]

    def get_knowledge_base_files(self, knowledge_base_id):
        return [{"name": "file1", "size": 123, "knowledge_base_id": knowledge_base_id}]

    def sync_all_knowledge_bases(self):
        return {"success": True, "knowledge_bases": [{"id": "kb1"}], "total_count": 1}


def test_get_datamate_core_success(monkeypatch):
    """Test _get_datamate_core function with valid configuration."""
    # Mock DATAMATE_URL constant in the service module
    monkeypatch.setattr(
        "backend.services.datamate_service.DATAMATE_URL", "DATAMATE_URL"
    )

    # Mock tenant_config_manager
    mock_config_manager = MagicMock()
    mock_config_manager.get_app_config.return_value = "http://datamate.example.com"

    # Mock DataMateCore
    mock_datamate_core = MagicMock()
    datamate_core_class = MagicMock(return_value=mock_datamate_core)

    monkeypatch.setattr(
        "backend.services.datamate_service.tenant_config_manager", mock_config_manager)
    monkeypatch.setattr(
        "backend.services.datamate_service.DataMateCore", datamate_core_class)

    result = _get_datamate_core("tenant1")

    assert result == mock_datamate_core
    mock_config_manager.get_app_config.assert_called_once_with(
        "DATAMATE_URL", tenant_id="tenant1")
    datamate_core_class.assert_called_once_with(
        base_url="http://datamate.example.com", verify_ssl=True)


def test_get_datamate_core_https_ssl_verification(monkeypatch):
    """Test _get_datamate_core function with HTTPS URL disables SSL verification."""
    # Mock DATAMATE_URL constant in the service module
    monkeypatch.setattr(
        "backend.services.datamate_service.DATAMATE_URL", "DATAMATE_URL"
    )

    # Mock tenant_config_manager
    mock_config_manager = MagicMock()
    mock_config_manager.get_app_config.return_value = "https://datamate.example.com"

    # Mock DataMateCore
    mock_datamate_core = MagicMock()
    datamate_core_class = MagicMock(return_value=mock_datamate_core)

    monkeypatch.setattr(
        "backend.services.datamate_service.tenant_config_manager", mock_config_manager)
    monkeypatch.setattr(
        "backend.services.datamate_service.DataMateCore", datamate_core_class)

    result = _get_datamate_core("tenant1")

    assert result == mock_datamate_core
    mock_config_manager.get_app_config.assert_called_once_with(
        "DATAMATE_URL", tenant_id="tenant1")
    datamate_core_class.assert_called_once_with(
        base_url="https://datamate.example.com", verify_ssl=False)


def test_get_datamate_core_http_ssl_verification(monkeypatch):
    """Test _get_datamate_core function with HTTP URL enables SSL verification."""
    # Mock DATAMATE_URL constant in the service module
    monkeypatch.setattr(
        "backend.services.datamate_service.DATAMATE_URL", "DATAMATE_URL"
    )

    # Mock tenant_config_manager
    mock_config_manager = MagicMock()
    mock_config_manager.get_app_config.return_value = "http://datamate.example.com"

    # Mock DataMateCore
    mock_datamate_core = MagicMock()
    datamate_core_class = MagicMock(return_value=mock_datamate_core)

    monkeypatch.setattr(
        "backend.services.datamate_service.tenant_config_manager", mock_config_manager)
    monkeypatch.setattr(
        "backend.services.datamate_service.DataMateCore", datamate_core_class)

    result = _get_datamate_core("tenant1")

    assert result == mock_datamate_core
    mock_config_manager.get_app_config.assert_called_once_with(
        "DATAMATE_URL", tenant_id="tenant1")
    datamate_core_class.assert_called_once_with(
        base_url="http://datamate.example.com", verify_ssl=True)


def test_get_datamate_core_missing_config(monkeypatch):
    """Test _get_datamate_core function with missing configuration."""
    # Mock DATAMATE_URL constant in the service module
    monkeypatch.setattr(
        "backend.services.datamate_service.DATAMATE_URL", "DATAMATE_URL"
    )

    # Mock tenant_config_manager to return None
    mock_config_manager = MagicMock()
    mock_config_manager.get_app_config.return_value = None

    monkeypatch.setattr(
        "backend.services.datamate_service.tenant_config_manager", mock_config_manager)

    with pytest.raises(ValueError) as excinfo:
        _get_datamate_core("tenant1")

    assert "DataMate URL not configured for tenant tenant1" in str(
        excinfo.value)
    mock_config_manager.get_app_config.assert_called_once_with(
        "DATAMATE_URL", tenant_id="tenant1")


@pytest.mark.asyncio
async def test_fetch_datamate_knowledge_base_file_list_success(monkeypatch):
    """Test fetch_datamate_knowledge_base_file_list function with successful response."""
    # Mock the _get_datamate_core function
    fake_core = MagicMock()
    fake_core.get_documents_detail.return_value = [
        {"name": "doc1.pdf", "size": 1234, "upload_date": "2023-01-01"},
        {"name": "doc2.txt", "size": 5678, "upload_date": "2023-01-02"}
    ]

    monkeypatch.setattr(
        "backend.services.datamate_service._get_datamate_core", lambda tenant_id: fake_core)

    result = await fetch_datamate_knowledge_base_file_list("kb1", "tenant1")

    expected_result = {
        "status": "success",
        "files": [
            {"name": "doc1.pdf", "size": 1234, "upload_date": "2023-01-01"},
            {"name": "doc2.txt", "size": 5678, "upload_date": "2023-01-02"}
        ]
    }

    assert result == expected_result
    fake_core.get_documents_detail.assert_called_once_with("kb1")


@pytest.mark.asyncio
async def test_fetch_datamate_knowledge_base_file_list_failure(monkeypatch):
    """Test fetch_datamate_knowledge_base_file_list function with error."""
    # Mock the _get_datamate_core function
    fake_core = MagicMock()
    fake_core.get_documents_detail.side_effect = Exception("API error")

    monkeypatch.setattr(
        "backend.services.datamate_service._get_datamate_core", lambda tenant_id: fake_core)

    with pytest.raises(RuntimeError) as excinfo:
        await fetch_datamate_knowledge_base_file_list("kb1", "tenant1")

    assert "Failed to fetch file list for knowledge base kb1" in str(
        excinfo.value)
    fake_core.get_documents_detail.assert_called_once_with("kb1")


@pytest.mark.asyncio
async def test_create_datamate_knowledge_records_success(monkeypatch):
    """Test _create_datamate_knowledge_records function with successful record creation."""
    # Reset mock state from previous tests
    knowledge_db_mock.upsert_knowledge_record.side_effect = None
    knowledge_db_mock.upsert_knowledge_record.reset_mock()

    # Mock upsert_knowledge_record
    mock_created_record = {"id": "record1", "index_name": "kb1"}
    knowledge_db_mock.upsert_knowledge_record.return_value = mock_created_record

    result = await _create_datamate_knowledge_records(
        knowledge_base_ids=["kb1", "kb2"],
        knowledge_base_names=["Knowledge Base 1", "Knowledge Base 2"],
        embedding_model_names=["embedding1", "embedding2"],
        tenant_id="tenant1",
        user_id="user1"
    )

    assert len(result) == 2
    assert result[0] == mock_created_record
    assert result[1] == mock_created_record

    # Verify upsert_knowledge_record was called twice
    assert knowledge_db_mock.upsert_knowledge_record.call_count == 2

    # Check the call arguments for first record
    first_call_args = knowledge_db_mock.upsert_knowledge_record.call_args_list[0][0][0]
    assert first_call_args["index_name"] == "kb1"
    assert first_call_args["knowledge_name"] == "Knowledge Base 1"
    assert first_call_args["tenant_id"] == "tenant1"
    assert first_call_args["user_id"] == "user1"
    assert first_call_args["embedding_model_name"] == "embedding1"


@pytest.mark.asyncio
async def test_create_datamate_knowledge_records_partial_failure(monkeypatch):
    """Test _create_datamate_knowledge_records function with partial failure."""
    # Reset mock state from previous tests
    knowledge_db_mock.upsert_knowledge_record.reset_mock()

    # Mock upsert_knowledge_record to fail on second call
    knowledge_db_mock.upsert_knowledge_record.side_effect = [
        {"id": "record1", "index_name": "kb1"},  # First call succeeds
        Exception("Database error")  # Second call fails
    ]

    result = await _create_datamate_knowledge_records(
        knowledge_base_ids=["kb1", "kb2"],
        knowledge_base_names=["Knowledge Base 1", "Knowledge Base 2"],
        embedding_model_names=["embedding1", "embedding2"],
        tenant_id="tenant1",
        user_id="user1"
    )

    # Should only return the successful record
    assert len(result) == 1
    assert result[0]["id"] == "record1"

    # Verify upsert_knowledge_record was called twice (second failed but didn't crash)
    assert knowledge_db_mock.upsert_knowledge_record.call_count == 2


@pytest.mark.asyncio
async def test_sync_datamate_knowledge_bases_success(monkeypatch, mock_datamate_sync_setup):
    """Test sync_datamate_knowledge_bases_and_create_records with successful sync."""
    # Reset mock state from previous tests
    knowledge_db_mock.get_knowledge_info_by_tenant_and_source.reset_mock()
    knowledge_db_mock.upsert_knowledge_record.reset_mock()
    knowledge_db_mock.delete_knowledge_record.reset_mock()

    # Mock the _get_datamate_core function
    fake_core = MagicMock()

    # Mock core methods
    fake_core.get_user_indices.return_value = ["kb1", "kb2"]
    fake_core.get_indices_detail.return_value = (
        {
            "kb1": {"base_info": {"embedding_model": "embedding1"}},
            "kb2": {"base_info": {"embedding_model": "embedding2"}}
        },
        ["Knowledge Base 1", "Knowledge Base 2"]
    )

    monkeypatch.setattr(
        "backend.services.datamate_service._get_datamate_core", lambda tenant_id: fake_core)

    # Mock database functions that are imported directly
    monkeypatch.setattr(
        "backend.services.datamate_service.get_knowledge_info_by_tenant_and_source",
        MagicMock(return_value=[])
    )
    monkeypatch.setattr(
        "backend.services.datamate_service.delete_knowledge_record",
        MagicMock(return_value=True)
    )

    # Mock _create_datamate_knowledge_records to return a coroutine
    async def mock_create_records(*args, **kwargs):
        return [{"id": "record1"}, {"id": "record2"}]

    monkeypatch.setattr(
        "backend.services.datamate_service._create_datamate_knowledge_records",
        mock_create_records
    )

    result = await sync_datamate_knowledge_bases_and_create_records("tenant1", "user1")

    assert result["indices"] == ["Knowledge Base 1", "Knowledge Base 2"]
    assert result["count"] == 2
    assert "indices_info" in result
    assert len(result["indices_info"]) == 2

    fake_core.get_user_indices.assert_called_once()
    fake_core.get_indices_detail.assert_called_once_with(["kb1", "kb2"])


@pytest.mark.asyncio
async def test_sync_datamate_knowledge_bases_no_indices(monkeypatch, mock_datamate_sync_setup):
    """Test sync_datamate_knowledge_bases_and_create_records when no knowledge bases exist."""
    # Reset mock state from previous tests
    knowledge_db_mock.get_knowledge_info_by_tenant_and_source.reset_mock()
    knowledge_db_mock.upsert_knowledge_record.reset_mock()
    knowledge_db_mock.delete_knowledge_record.reset_mock()

    # Mock the _get_datamate_core function
    fake_core = MagicMock()
    fake_core.get_user_indices.return_value = []  # No indices

    monkeypatch.setattr(
        "backend.services.datamate_service._get_datamate_core", lambda tenant_id: fake_core)

    result = await sync_datamate_knowledge_bases_and_create_records("tenant1", "user1")

    assert result["indices"] == []
    assert result["count"] == 0
    assert "indices_info" not in result  # Should not be present when no indices

    fake_core.get_user_indices.assert_called_once()
    # get_indices_detail should not be called when no indices
    fake_core.get_indices_detail.assert_not_called()


@pytest.mark.asyncio
async def test_sync_datamate_knowledge_bases_with_deletions(monkeypatch, mock_datamate_sync_setup):
    """Test sync_datamate_knowledge_bases_and_create_records with soft deletions."""
    # Reset mock state from previous tests
    knowledge_db_mock.get_knowledge_info_by_tenant_and_source.reset_mock()
    knowledge_db_mock.upsert_knowledge_record.reset_mock()
    knowledge_db_mock.delete_knowledge_record.reset_mock()

    # Mock the _get_datamate_core function
    fake_core = MagicMock()

    # Mock core methods - only kb1 exists in API now
    fake_core.get_user_indices.return_value = ["kb1"]
    fake_core.get_indices_detail.return_value = (
        {"kb1": {"base_info": {"embedding_model": "embedding1"}}},
        ["Knowledge Base 1"]
    )

    monkeypatch.setattr(
        "backend.services.datamate_service._get_datamate_core", lambda tenant_id: fake_core)

    # Mock database functions that are imported directly - kb1 and kb2 exist in DB, but kb2 was deleted from API
    mock_get_knowledge_info = MagicMock(return_value=[
        {"index_name": "kb1"},
        {"index_name": "kb2"}  # This should be deleted
    ])
    mock_delete_record = MagicMock(return_value=True)

    monkeypatch.setattr(
        "backend.services.datamate_service.get_knowledge_info_by_tenant_and_source",
        mock_get_knowledge_info
    )
    monkeypatch.setattr(
        "backend.services.datamate_service.delete_knowledge_record",
        mock_delete_record
    )

    # Mock _create_datamate_knowledge_records to return a coroutine
    async def mock_create_records(*args, **kwargs):
        return [{"id": "record1"}]

    monkeypatch.setattr(
        "backend.services.datamate_service._create_datamate_knowledge_records",
        mock_create_records
    )

    result = await sync_datamate_knowledge_bases_and_create_records("tenant1", "user1")

    # kb2 should be deleted
    mock_delete_record.assert_called_once_with({
        "index_name": "kb2",
        "user_id": "user1"
    })


@pytest.mark.asyncio
async def test_sync_datamate_knowledge_bases_datamate_url_not_configured(monkeypatch):
    """Test sync_datamate_knowledge_bases_and_create_records when DataMate URL is not configured."""
    # Mock MODEL_ENGINE_ENABLED to be true
    monkeypatch.setattr(
        "backend.services.datamate_service.MODEL_ENGINE_ENABLED", "true"
    )

    # Mock tenant_config_manager to return None (no DataMate URL configured)
    mock_config_manager = MagicMock()
    mock_config_manager.get_app_config.return_value = None
    monkeypatch.setattr(
        "backend.services.datamate_service.tenant_config_manager", mock_config_manager
    )

    # Mock logger to capture warning message
    mock_logger = MagicMock()
    monkeypatch.setattr(
        "backend.services.datamate_service.logger", mock_logger
    )

    result = await sync_datamate_knowledge_bases_and_create_records("tenant1", "user1")

    # Verify the warning was logged
    mock_logger.warning.assert_called_once_with(
        "DataMate URL not configured for tenant tenant1, skipping sync"
    )

    # Verify the correct default response is returned
    expected_result = {
        "indices": [],
        "count": 0,
        "indices_info": [],
        "created_records": []
    }
    assert result == expected_result

    # Verify tenant_config_manager.get_app_config was called correctly
    mock_config_manager.get_app_config.assert_called_once_with(
        "DATAMATE_URL", tenant_id="tenant1"
    )


@pytest.mark.asyncio
async def test_sync_datamate_knowledge_bases_datamate_url_empty_string(monkeypatch):
    """Test sync_datamate_knowledge_bases_and_create_records when DataMate URL is empty string."""
    # Mock MODEL_ENGINE_ENABLED to be true
    monkeypatch.setattr(
        "backend.services.datamate_service.MODEL_ENGINE_ENABLED", "true"
    )

    # Mock tenant_config_manager to return empty string (no DataMate URL configured)
    mock_config_manager = MagicMock()
    mock_config_manager.get_app_config.return_value = ""
    monkeypatch.setattr(
        "backend.services.datamate_service.tenant_config_manager", mock_config_manager
    )

    # Mock logger to capture warning message
    mock_logger = MagicMock()
    monkeypatch.setattr(
        "backend.services.datamate_service.logger", mock_logger
    )

    result = await sync_datamate_knowledge_bases_and_create_records("tenant1", "user1")

    # Verify the warning was logged
    mock_logger.warning.assert_called_once_with(
        "DataMate URL not configured for tenant tenant1, skipping sync"
    )

    # Verify the correct default response is returned
    expected_result = {
        "indices": [],
        "count": 0,
        "indices_info": [],
        "created_records": []
    }
    assert result == expected_result

    # Verify tenant_config_manager.get_app_config was called correctly
    mock_config_manager.get_app_config.assert_called_once_with(
        "DATAMATE_URL", tenant_id="tenant1"
    )


@pytest.mark.asyncio
async def test_sync_datamate_knowledge_bases_error_handling(monkeypatch):
    """Test sync_datamate_knowledge_bases_and_create_records with error handling."""
    # Mock the _get_datamate_core function to raise an exception
    monkeypatch.setattr(
        "backend.services.datamate_service._get_datamate_core",
        MagicMock(side_effect=Exception("API connection failed"))
    )

    result = await sync_datamate_knowledge_bases_and_create_records("tenant1", "user1")

    # Should return empty result on error
    assert result["indices"] == []
    assert result["count"] == 0
