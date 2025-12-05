import importlib
import sys
import pytest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

# Mock consts module first to avoid ModuleNotFoundError during module import
consts_mock = MagicMock()
consts_mock.const = MagicMock()
# Set required constants on consts.const for tests
consts_mock.const.MINIO_ENDPOINT = "http://localhost:9000"
consts_mock.const.MINIO_ACCESS_KEY = "test_access_key"
consts_mock.const.MINIO_SECRET_KEY = "test_secret_key"
consts_mock.const.MINIO_REGION = "us-east-1"
consts_mock.const.MINIO_DEFAULT_BUCKET = "test-bucket"
consts_mock.const.POSTGRES_HOST = "localhost"
consts_mock.const.POSTGRES_USER = "test_user"
consts_mock.const.NEXENT_POSTGRES_PASSWORD = "test_password"
consts_mock.const.POSTGRES_DB = "test_db"
consts_mock.const.POSTGRES_PORT = 5432
consts_mock.const.DEFAULT_TENANT_ID = "default_tenant"
consts_mock.const.DEFAULT_EXPECTED_CHUNK_SIZE = 1024
consts_mock.const.DEFAULT_MAXIMUM_CHUNK_SIZE = 1536

# Register mocked consts module in sys.modules
sys.modules['consts'] = consts_mock
sys.modules['consts.const'] = consts_mock.const

# Mock utils module used by target module
utils_mock = MagicMock()
utils_mock.auth_utils = MagicMock()
utils_mock.auth_utils.get_current_user_id = MagicMock(return_value=("test_user_id", "test_tenant_id"))

# Register mocked utils module in sys.modules
sys.modules['utils'] = utils_mock
sys.modules['utils.auth_utils'] = utils_mock.auth_utils

# Provide a stub for the `boto3` module so that it can be imported safely even
# if the testing environment does not have it available.
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

# Mock the entire client module used by database layer
client_mock = MagicMock()
client_mock.MinioClient = MagicMock()
client_mock.PostgresClient = MagicMock()
client_mock.db_client = MagicMock()
client_mock.get_db_session = MagicMock()
client_mock.as_dict = MagicMock()

# Register mocked client module in sys.modules
sys.modules['backend.database.client'] = client_mock

"""Now that dependencies are mocked, import the module under test.
Access functions via the module object to avoid direct function imports.
"""
model_mgmt_db = importlib.import_module("backend.database.model_management_db")

@pytest.fixture
def mock_session():
    # mock scalars().all() return value
    mock_model = SimpleNamespace(
        model_id=1,
        model_factory="openai",
        model_type="chat",
        tenant_id="tenant1",
        delete_flag="N",
    )
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_model]
    mock_session = MagicMock()
    mock_session.scalars.return_value = mock_scalars
    return mock_session

def test_get_models_by_tenant_factory_type(monkeypatch, mock_session):
    # patch get_db_session
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = mock_session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.model_management_db.get_db_session", lambda: mock_ctx)
    # patch as_dict
    monkeypatch.setattr("backend.database.model_management_db.as_dict", lambda obj: obj.__dict__)

    tenant_id = "tenant1"
    model_factory = "openai"
    model_type = "chat"
    result = model_mgmt_db.get_models_by_tenant_factory_type(
        tenant_id, model_factory, model_type)
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["model_factory"] == model_factory
    assert result[0]["model_type"] == model_type
    assert result[0]["tenant_id"] == tenant_id


def test_get_model_records_fills_default_chunk_sizes(monkeypatch):
    # Create a mock session returning an embedding record with None chunk sizes
    mock_model = SimpleNamespace(
        model_id=2,
        model_factory="openai",
        model_type="embedding",
        tenant_id="tenant2",
        delete_flag="N",
        expected_chunk_size=None,
        maximum_chunk_size=None,
    )
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_model]
    session = MagicMock()
    session.scalars.return_value = mock_scalars

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr(
        "backend.database.model_management_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(
        "backend.database.model_management_db.as_dict", lambda obj: obj.__dict__)

    records = model_mgmt_db.get_model_records(
        {"model_type": "embedding"}, tenant_id="tenant2")
    assert len(records) == 1
    assert records[0]["expected_chunk_size"] == 1024
    assert records[0]["maximum_chunk_size"] == 1536


def test_get_model_by_model_id_fills_default_chunk_sizes(monkeypatch):
    # Mock session.scalars().first() to return an embedding record with None sizes
    mock_model = SimpleNamespace(
        model_id=3,
        model_factory="openai",
        model_type="embedding",
        tenant_id="tenant3",
        delete_flag="N",
        expected_chunk_size=None,
        maximum_chunk_size=None,
    )
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_model
    session = MagicMock()
    session.scalars.return_value = mock_scalars

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr(
        "backend.database.model_management_db.get_db_session", lambda: mock_ctx)

    out = model_mgmt_db.get_model_by_model_id(3, tenant_id="tenant3")
    assert out is not None
    assert out["expected_chunk_size"] == 1024
    assert out["maximum_chunk_size"] == 1536


def test_create_model_record(monkeypatch):
    """Test create_model_record function (covers lines 23-42)"""
    mock_result = MagicMock()
    mock_result.rowcount = 1
    
    mock_stmt = MagicMock()
    mock_stmt.values.return_value = mock_stmt
    
    mock_insert = MagicMock(return_value=mock_stmt)
    monkeypatch.setattr("backend.database.model_management_db.insert", mock_insert)
    
    session = MagicMock()
    session.execute.return_value = mock_result
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.model_management_db.get_db_session", lambda: mock_ctx)
    
    # Mock clean_string_values and add_creation_tracking
    monkeypatch.setattr("backend.database.model_management_db.db_client.clean_string_values", lambda x: x)
    monkeypatch.setattr("backend.database.model_management_db.add_creation_tracking", lambda x, uid: x)
    monkeypatch.setattr("backend.database.model_management_db.func.current_timestamp", MagicMock())
    
    model_data = {"model_name": "test", "model_type": "llm"}
    result = model_mgmt_db.create_model_record(model_data, user_id="u1", tenant_id="t1")
    
    assert result is True
    session.execute.assert_called_once()


def test_update_model_record(monkeypatch):
    """Test update_model_record function (covers lines 63-84)"""
    mock_result = MagicMock()
    mock_result.rowcount = 1
    
    mock_stmt = MagicMock()
    mock_stmt.where.return_value = mock_stmt
    mock_stmt.values.return_value = mock_stmt
    
    mock_update = MagicMock(return_value=mock_stmt)
    monkeypatch.setattr("backend.database.model_management_db.update", mock_update)
    
    session = MagicMock()
    session.execute.return_value = mock_result
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.model_management_db.get_db_session", lambda: mock_ctx)
    
    # Mock clean_string_values and add_update_tracking
    monkeypatch.setattr("backend.database.model_management_db.db_client.clean_string_values", lambda x: x)
    monkeypatch.setattr("backend.database.model_management_db.add_update_tracking", lambda x, uid: x)
    monkeypatch.setattr("backend.database.model_management_db.func.current_timestamp", MagicMock())
    
    update_data = {"model_name": "updated"}
    result = model_mgmt_db.update_model_record(1, update_data, user_id="u1", tenant_id="t1")
    
    assert result is True
    session.execute.assert_called_once()


def test_delete_model_record(monkeypatch):
    """Test delete_model_record function (covers lines 99-119)"""
    mock_result = MagicMock()
    mock_result.rowcount = 1
    
    mock_stmt = MagicMock()
    mock_stmt.where.return_value = mock_stmt
    mock_stmt.values.return_value = mock_stmt
    
    mock_update = MagicMock(return_value=mock_stmt)
    monkeypatch.setattr("backend.database.model_management_db.update", mock_update)
    
    session = MagicMock()
    session.execute.return_value = mock_result
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.model_management_db.get_db_session", lambda: mock_ctx)
    
    # Mock add_update_tracking
    monkeypatch.setattr("backend.database.model_management_db.add_update_tracking", lambda x, uid: x)
    monkeypatch.setattr("backend.database.model_management_db.func.current_timestamp", MagicMock())
    
    result = model_mgmt_db.delete_model_record(1, user_id="u1", tenant_id="t1")
    
    assert result is True
    session.execute.assert_called_once()


def test_get_model_records_with_tenant_id(monkeypatch):
    """Test get_model_records with tenant_id filter (covers lines 137->141)"""
    mock_model = SimpleNamespace(
        model_id=4,
        model_factory="openai",
        model_type="llm",
        tenant_id="tenant4",
        delete_flag="N",
    )
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_model]
    session = MagicMock()
    session.scalars.return_value = mock_scalars
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.model_management_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.model_management_db.as_dict", lambda obj: obj.__dict__)
    
    records = model_mgmt_db.get_model_records({"model_type": "llm"}, tenant_id="tenant4")
    assert len(records) == 1
    assert records[0]["tenant_id"] == "tenant4"


def test_get_model_records_with_none_filter(monkeypatch):
    """Test get_model_records with None value in filter (covers line 145)"""
    mock_model = SimpleNamespace(
        model_id=5,
        model_factory="openai",
        model_type="llm",
        tenant_id="tenant5",
        delete_flag="N",
        display_name=None,
    )
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_model]
    session = MagicMock()
    session.scalars.return_value = mock_scalars
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.model_management_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.model_management_db.as_dict", lambda obj: obj.__dict__)
    
    records = model_mgmt_db.get_model_records({"display_name": None}, tenant_id="tenant5")
    assert len(records) == 1


def test_get_model_by_display_name(monkeypatch):
    """Test get_model_by_display_name function (covers lines 178-185)"""
    mock_model = SimpleNamespace(
        model_id=6,
        model_factory="openai",
        model_name="gpt-4",
        display_name="GPT-4",
        tenant_id="tenant6",
        delete_flag="N",
    )
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_model]
    session = MagicMock()
    session.scalars.return_value = mock_scalars
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.model_management_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.model_management_db.as_dict", lambda obj: obj.__dict__)
    
    result = model_mgmt_db.get_model_by_display_name("GPT-4", "tenant6")
    assert result is not None
    assert result["display_name"] == "GPT-4"


def test_get_model_id_by_display_name(monkeypatch):
    """Test get_model_id_by_display_name function (covers lines 199-200)"""
    mock_model = SimpleNamespace(
        model_id=7,
        model_factory="openai",
        model_name="gpt-4",
        display_name="GPT-4",
        tenant_id="tenant7",
        delete_flag="N",
    )
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_model]
    session = MagicMock()
    session.scalars.return_value = mock_scalars
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.model_management_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.model_management_db.as_dict", lambda obj: obj.__dict__)
    
    result = model_mgmt_db.get_model_id_by_display_name("GPT-4", "tenant7")
    assert result == 7


def test_get_model_by_model_id_with_tenant_id(monkeypatch):
    """Test get_model_by_model_id with tenant_id filter (covers lines 222->226)"""
    mock_model = SimpleNamespace(
        model_id=8,
        model_factory="openai",
        model_type="llm",
        tenant_id="tenant8",
        delete_flag="N",
    )
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_model
    session = MagicMock()
    session.scalars.return_value = mock_scalars
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.model_management_db.get_db_session", lambda: mock_ctx)
    
    result = model_mgmt_db.get_model_by_model_id(8, tenant_id="tenant8")
    assert result is not None
    assert result["model_id"] == 8


def test_get_model_by_name_factory(monkeypatch):
    """Test get_model_by_name_factory function (covers lines 269-274)"""
    mock_model = SimpleNamespace(
        model_id=9,
        model_factory="openai",
        model_name="gpt-4",
        tenant_id="tenant9",
        delete_flag="N",
    )
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_model]
    session = MagicMock()
    session.scalars.return_value = mock_scalars
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.model_management_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.model_management_db.as_dict", lambda obj: obj.__dict__)
    
    result = model_mgmt_db.get_model_by_name_factory("gpt-4", "openai", "tenant9")
    assert result is not None
    assert result["model_name"] == "gpt-4"
    assert result["model_factory"] == "openai"
