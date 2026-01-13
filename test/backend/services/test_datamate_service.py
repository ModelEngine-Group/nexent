import pytest
import sys
from unittest.mock import MagicMock, patch

# Mock dotenv module before any other imports that might use it
dotenv_mock = MagicMock()
dotenv_mock.load_dotenv = MagicMock()
sys.modules['dotenv'] = dotenv_mock

# Mock SDK storage modules to avoid MinIO config validation
storage_factory_mock = MagicMock()
minio_config_mock = MagicMock()
minio_config_mock.MinIOStorageConfig = MagicMock()
# Mock the validate method to avoid config validation
minio_config_mock.MinIOStorageConfig.return_value.validate = MagicMock()

sys.modules['sdk.nexent.storage'] = storage_factory_mock
sys.modules['sdk.nexent.storage.storage_client_factory'] = storage_factory_mock
sys.modules['sdk.nexent.storage.minio_config'] = minio_config_mock

# Mock nexent modules BEFORE importing datamate_service
nexent_mock = MagicMock()
nexent_mock.vector_database = MagicMock()
nexent_mock.vector_database.datamate_core = MagicMock()
nexent_mock.vector_database.datamate_core.DataMateCore = MagicMock()
sys.modules['nexent'] = nexent_mock
sys.modules['nexent.vector_database'] = nexent_mock.vector_database
sys.modules['nexent.vector_database.datamate_core'] = nexent_mock.vector_database.datamate_core

# Mock consts module BEFORE any database imports
consts_package_mock = MagicMock()
consts_module_mock = MagicMock()

# Set required constants
consts_module_mock.DATAMATE_BASE_URL = "http://localhost:30000"
consts_module_mock.MINIO_ENDPOINT = "http://localhost:9000"
consts_module_mock.MINIO_ACCESS_KEY = "test_access_key"
consts_module_mock.MINIO_SECRET_KEY = "test_secret_key"
consts_module_mock.MINIO_REGION = "us-east-1"
consts_module_mock.MINIO_DEFAULT_BUCKET = "test-bucket"
consts_module_mock.POSTGRES_HOST = "localhost"
consts_module_mock.POSTGRES_USER = "test_user"
consts_module_mock.NEXENT_POSTGRES_PASSWORD = "test_password"
consts_module_mock.POSTGRES_DB = "test_db"
consts_module_mock.POSTGRES_PORT = 5432
consts_module_mock.DEFAULT_TENANT_ID = "default_tenant"

# Mock the package structure
consts_package_mock.const = consts_module_mock
sys.modules['consts'] = consts_package_mock
sys.modules['consts.const'] = consts_module_mock

# Mock sqlalchemy module BEFORE any database imports
sqlalchemy_mock = MagicMock()
sqlalchemy_mock.func = MagicMock()
sqlalchemy_mock.func.current_timestamp = MagicMock(
    return_value="2023-01-01 00:00:00")
sqlalchemy_mock.exc = MagicMock()


class MockSQLAlchemyError(Exception):
    pass


sqlalchemy_mock.exc.SQLAlchemyError = MockSQLAlchemyError

# Add the mocked sqlalchemy module to sys.modules
sys.modules['sqlalchemy'] = sqlalchemy_mock
sys.modules['sqlalchemy.exc'] = sqlalchemy_mock.exc

# Mock the entire client module to avoid actual database connections
# This MUST be done BEFORE importing any module that uses database.client
client_mock = MagicMock()
client_mock.MinioClient = MagicMock()
client_mock.PostgresClient = MagicMock()
client_mock.db_client = MagicMock()
client_mock.get_db_session = MagicMock()
client_mock.as_dict = MagicMock()
client_mock.filter_property = MagicMock()

# Add the mocked client module to sys.modules
sys.modules['database.client'] = client_mock
sys.modules['backend.database.client'] = client_mock
sys.modules['database'] = client_mock

# Mock db_models module
db_models_mock = MagicMock()
sys.modules['database.db_models'] = db_models_mock
sys.modules['backend.database.db_models'] = db_models_mock

# Mock knowledge_db functions
knowledge_db_mock = MagicMock()
knowledge_db_mock.upsert_knowledge_record = MagicMock()
knowledge_db_mock.get_knowledge_info_by_tenant_and_source = MagicMock()
knowledge_db_mock.delete_knowledge_record = MagicMock()
sys.modules['database.knowledge_db'] = knowledge_db_mock
sys.modules['backend.database.knowledge_db'] = knowledge_db_mock

# Mock utils module
utils_mock = MagicMock()
utils_mock.auth_utils = MagicMock()
utils_mock.auth_utils.get_current_user_id_from_token = MagicMock(
    return_value="test_user_id")

# Add the mocked utils module to sys.modules
sys.modules['utils'] = utils_mock
sys.modules['utils.auth_utils'] = utils_mock.auth_utils

# Provide a stub for the `boto3` module so that it can be imported safely even
# if the testing environment does not have it available.
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

# NOW it's safe to import the module under test
from backend.services import datamate_service


class FakeCore:
    def __init__(self, base_url=None):
        self.base_url = base_url

    def get_user_indices(self):
        return ["kb1", "kb2"]

    def get_indices_detail(self, knowledge_base_ids):
        details = {
            "kb1": {"base_info": {"embedding_model": "model1"}},
            "kb2": {"base_info": {"embedding_model": "model2"}}
        }
        return details, ["KB1", "KB2"]

    def get_documents_detail(self, knowledge_base_id):
        return [{"name": "file1", "size": 123, "knowledge_base_id": knowledge_base_id}]


@pytest.mark.asyncio
async def test_fetch_datamate_knowledge_base_file_list_success(monkeypatch):
    monkeypatch.setattr(
        datamate_service, "_get_datamate_core", lambda: FakeCore())
    result = await datamate_service.fetch_datamate_knowledge_base_file_list("kb1")
    assert isinstance(result, dict)
    assert result["status"] == "success"
    assert isinstance(result["files"], list)
    assert result["files"][0]["knowledge_base_id"] == "kb1"


@pytest.mark.asyncio
async def test_fetch_datamate_knowledge_base_file_list_failure(monkeypatch):
    class BadCore(FakeCore):
        def get_documents_detail(self, knowledge_base_id):
            raise Exception("boom")

    monkeypatch.setattr(
        datamate_service, "_get_datamate_core", lambda: BadCore())
    with pytest.raises(RuntimeError) as excinfo:
        await datamate_service.fetch_datamate_knowledge_base_file_list("kb1")
    assert "Failed to fetch file list for datamate knowledge base kb1" in str(
        excinfo.value)


@pytest.mark.asyncio
async def test_sync_datamate_knowledge_bases_records_success(monkeypatch):
    fake_core = FakeCore()
    monkeypatch.setattr(
        datamate_service, "_get_datamate_core", lambda: fake_core)

    # Mock database functions
    with patch('backend.services.datamate_service.upsert_knowledge_record') as mock_upsert, \
            patch('backend.services.datamate_service.get_knowledge_info_by_tenant_and_source') as mock_get_existing, \
            patch('backend.services.datamate_service.delete_knowledge_record') as mock_delete:

        mock_upsert.side_effect = lambda data: {"id": 1, **data}
        mock_get_existing.return_value = []

        result = await datamate_service.sync_datamate_knowledge_bases_records("tenant1", "user1")

        assert isinstance(result, dict)
        assert result["count"] == 2
        assert len(result["indices"]) == 2
        assert "indices_info" in result

        # Verify upsert was called twice
        assert mock_upsert.call_count == 2


@pytest.mark.asyncio
async def test_sync_datamate_knowledge_bases_records_no_indices(monkeypatch):
    class EmptyCore(FakeCore):
        def get_user_indices(self):
            return []

    monkeypatch.setattr(
        datamate_service, "_get_datamate_core", lambda: EmptyCore())
    result = await datamate_service.sync_datamate_knowledge_bases_records("tenant1", "user1")

    assert result["indices"] == []
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_sync_datamate_knowledge_bases_records_failure(monkeypatch):
    class BadCore(FakeCore):
        def get_user_indices(self):
            raise Exception("boom")

    monkeypatch.setattr(
        datamate_service, "_get_datamate_core", lambda: BadCore())

    result = await datamate_service.sync_datamate_knowledge_bases_records("tenant1", "user1")

    assert result["indices"] == []
    assert result["count"] == 0


def test_soft_delete_datamate_records_success(monkeypatch):
    fake_core = FakeCore()
    monkeypatch.setattr(
        datamate_service, "_get_datamate_core", lambda: fake_core)

    with patch('backend.services.datamate_service.get_knowledge_info_by_tenant_and_source') as mock_get, \
            patch('backend.services.datamate_service.delete_knowledge_record') as mock_delete:

        # Mock existing records in DB
        mock_get.return_value = [
            {"index_name": "kb1"},
            {"index_name": "kb3"}  # This one should be deleted
        ]
        mock_delete.return_value = True

        # Call with current API indices ["kb1", "kb2"]
        datamate_service._soft_delete_datamate_records(
            ["kb1", "kb2"], "tenant1", "user1")

        # Verify delete was called for kb3 only
        mock_delete.assert_called_once_with(
            {"index_name": "kb3", "user_id": "user1"})


def test_soft_delete_datamate_records_delete_failure(monkeypatch):
    fake_core = FakeCore()
    monkeypatch.setattr(
        datamate_service, "_get_datamate_core", lambda: fake_core)

    with patch('backend.services.datamate_service.get_knowledge_info_by_tenant_and_source') as mock_get, \
            patch('backend.services.datamate_service.delete_knowledge_record') as mock_delete:

        mock_get.return_value = [{"index_name": "kb3"}]
        mock_delete.return_value = False  # Delete fails

        datamate_service._soft_delete_datamate_records(
            ["kb1", "kb2"], "tenant1", "user1")

        # Verify delete was attempted but failed
        mock_delete.assert_called_once()


@pytest.mark.asyncio
async def test_create_datamate_knowledge_records_success(monkeypatch):
    with patch('backend.services.datamate_service.upsert_knowledge_record') as mock_upsert:
        mock_upsert.side_effect = lambda data: {"id": 1, **data}

        result = await datamate_service._create_datamate_knowledge_records(
            ["kb1", "kb2"],
            ["KB1", "KB2"],
            ["model1", "model2"],
            "tenant1",
            "user1"
        )

        assert len(result) == 2
        assert result[0]["index_name"] == "kb1"
        assert result[0]["knowledge_name"] == "KB1"
        assert result[0]["knowledge_sources"] == "datamate"
        assert result[0]["tenant_id"] == "tenant1"
        assert result[0]["user_id"] == "user1"
        assert result[0]["embedding_model_name"] == "model1"


@pytest.mark.asyncio
async def test_create_datamate_knowledge_records_upsert_failure(monkeypatch):
    with patch('backend.services.datamate_service.upsert_knowledge_record') as mock_upsert:
        mock_upsert.side_effect = Exception("Database error")

        with pytest.raises(Exception) as excinfo:
            await datamate_service._create_datamate_knowledge_records(
                ["kb1"],
                ["KB1"],
                ["model1"],
                "tenant1",
                "user1"
            )
        assert "Failed to create knowledge record for DataMate KB 'kb1'" in str(
            excinfo.value)
