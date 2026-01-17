import sys
import pytest
from unittest.mock import patch, MagicMock

# First mock the consts module to avoid ModuleNotFoundError
consts_mock = MagicMock()
consts_mock.const = MagicMock()
# Set required constants in consts.const
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

# Add the mocked consts module to sys.modules
sys.modules['consts'] = consts_mock
sys.modules['consts.const'] = consts_mock.const

# Mock utils module
utils_mock = MagicMock()
utils_mock.auth_utils = MagicMock()
utils_mock.auth_utils.get_current_user_id_from_token = MagicMock(return_value="test_user_id")
utils_mock.str_utils = MagicMock()
utils_mock.str_utils.convert_list_to_string = MagicMock(side_effect=lambda x: ",".join(str(i) for i in x) if x else "")

# Add the mocked utils module to sys.modules
sys.modules['utils'] = utils_mock
sys.modules['utils.auth_utils'] = utils_mock.auth_utils
sys.modules['utils.str_utils'] = utils_mock.str_utils

# Provide a stub for the `boto3` module so that it can be imported safely even
# if the testing environment does not have it available.
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

# Mock the entire client module
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

# Mock sqlalchemy module
sqlalchemy_mock = MagicMock()
sqlalchemy_mock.func = MagicMock()
sqlalchemy_mock.func.current_timestamp = MagicMock(return_value="2023-01-01 00:00:00")
sqlalchemy_mock.exc = MagicMock()

class MockSQLAlchemyError(Exception):
    pass

sqlalchemy_mock.exc.SQLAlchemyError = MockSQLAlchemyError

# Add the mocked sqlalchemy module to sys.modules
sys.modules['sqlalchemy'] = sqlalchemy_mock
sys.modules['sqlalchemy.exc'] = sqlalchemy_mock.exc

# Mock db_models module
db_models_mock = MagicMock()

class MockKnowledgeRecord:
    def __init__(self, **kwargs):
        self.knowledge_id = kwargs.get('knowledge_id', 1)
        self.index_name = kwargs.get('index_name', 'test_index')
        self.knowledge_name = kwargs.get('knowledge_name', 'test_index')
        self.knowledge_describe = kwargs.get('knowledge_describe', 'test description')
        self.created_by = kwargs.get('created_by', 'test_user')
        self.updated_by = kwargs.get('updated_by', 'test_user')
        self.knowledge_sources = kwargs.get('knowledge_sources', 'elasticsearch')
        self.tenant_id = kwargs.get('tenant_id', 'test_tenant')
        self.embedding_model_name = kwargs.get('embedding_model_name', 'test_model')
        self.group_ids = kwargs.get('group_ids', '1,2,3')  # New field
        self.ingroup_permission = kwargs.get('ingroup_permission', 'READ_ONLY')  # New field, corrected name
        self.delete_flag = kwargs.get('delete_flag', 'N')
        self.update_time = kwargs.get('update_time', "2023-01-01 00:00:00")
        
    # Mock SQLAlchemy column attributes
    knowledge_id = MagicMock(name="knowledge_id_column")
    index_name = MagicMock(name="index_name_column")
    knowledge_name = MagicMock(name="knowledge_name_column")
    knowledge_describe = MagicMock(name="knowledge_describe_column")
    created_by = MagicMock(name="created_by_column")
    updated_by = MagicMock(name="updated_by_column")
    knowledge_sources = MagicMock(name="knowledge_sources_column")
    tenant_id = MagicMock(name="tenant_id_column")
    embedding_model_name = MagicMock(name="embedding_model_name_column")
    group_ids = MagicMock(name="group_ids_column")  # New field
    ingroup_permission = MagicMock(name="ingroup_permission_column")  # New field, corrected name
    delete_flag = MagicMock(name="delete_flag_column")
    update_time = MagicMock(name="update_time_column")

db_models_mock.KnowledgeRecord = MockKnowledgeRecord

# Add the mocked db_models module to sys.modules
sys.modules['database.db_models'] = db_models_mock
sys.modules['backend.database.db_models'] = db_models_mock

# Now we can safely import the module under test
from backend.database.knowledge_db import (
    create_knowledge_record,
    update_knowledge_record,
    delete_knowledge_record,
    get_knowledge_record,
    get_knowledge_info_by_knowledge_ids,
    get_knowledge_ids_by_index_names,
    get_knowledge_info_by_tenant_id,
    update_model_name_by_index_name,
    get_index_name_by_knowledge_name,
    _generate_index_name
)


@pytest.fixture
def mock_session():
    """Create a mock database session"""
    mock_session = MagicMock()
    mock_query = MagicMock()
    mock_session.query.return_value = mock_query
    return mock_session, mock_query


def test_create_knowledge_record_success(monkeypatch, mock_session):
    """Test successful creation of knowledge record"""
    session, _ = mock_session
    
    # Create mock knowledge record
    mock_record = MockKnowledgeRecord(knowledge_name="test_knowledge")
    mock_record.knowledge_id = 123
    mock_record.index_name = "test_knowledge"
    
    # Mock database session context
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    # Prepare test data
    test_query = {
        "index_name": "test_knowledge",
        "knowledge_describe": "Test knowledge description",
        "user_id": "test_user",
        "tenant_id": "test_tenant",
        "embedding_model_name": "test_model",
        "knowledge_name": "test_knowledge",
        "group_ids": [1, 2, 3],
        "ingroup_permission": "READ_ONLY"
    }
    
    # Mock KnowledgeRecord constructor
    with patch('backend.database.knowledge_db.KnowledgeRecord', return_value=mock_record):
        result = create_knowledge_record(test_query)
    
    assert result == {
        "knowledge_id": 123,
        "index_name": "test_knowledge",
        "knowledge_name": "test_knowledge",
    }
    session.add.assert_called_once_with(mock_record)
    assert session.flush.call_count == 1
    session.commit.assert_called_once()


def test_create_knowledge_record_with_group_ids_list(monkeypatch, mock_session):
    """Test successful creation of knowledge record with group IDs as list"""
    session, _ = mock_session

    # Create mock knowledge record
    mock_record = MockKnowledgeRecord(knowledge_name="test_knowledge")
    mock_record.knowledge_id = 123
    mock_record.index_name = "test_knowledge"

    # Mock database session context
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)

    # Prepare test data with group_ids as list
    test_query = {
        "index_name": "test_knowledge",
        "knowledge_describe": "Test knowledge description",
        "user_id": "test_user",
        "tenant_id": "test_tenant",
        "embedding_model_name": "test_model",
        "knowledge_name": "test_knowledge",
        "group_ids": [1, 2, 3],
        "ingroup_permission": "READ_ONLY"
    }

    # Mock KnowledgeRecord constructor
    with patch('backend.database.knowledge_db.KnowledgeRecord', return_value=mock_record) as mock_constructor:
        result = create_knowledge_record(test_query)

    assert result == {
        "knowledge_id": 123,
        "index_name": "test_knowledge",
        "knowledge_name": "test_knowledge",
    }
    # Verify KnowledgeRecord was called with group_ids converted to string
    mock_constructor.assert_called_once()
    call_kwargs = mock_constructor.call_args[1]  # Get kwargs from the call
    assert call_kwargs["group_ids"] == "1,2,3"  # Should be converted to comma-separated string
    session.add.assert_called_once_with(mock_record)
    assert session.flush.call_count == 1
    session.commit.assert_called_once()


def test_create_knowledge_record_exception(monkeypatch, mock_session):
    """Test exception during knowledge record creation"""
    session, _ = mock_session
    session.add.side_effect = MockSQLAlchemyError("Database error")
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    test_query = {
        "index_name": "test_knowledge",
        "knowledge_describe": "Test knowledge description",
        "user_id": "test_user",
        "tenant_id": "test_tenant",
        "embedding_model_name": "test_model"
    }
    
    mock_record = MockKnowledgeRecord()
    with patch('backend.database.knowledge_db.KnowledgeRecord', return_value=mock_record):
        with pytest.raises(MockSQLAlchemyError, match="Database error"):
            create_knowledge_record(test_query)
    
    session.rollback.assert_called_once()


def test_create_knowledge_record_generates_index_name(monkeypatch, mock_session):
    """Test create_knowledge_record generates index_name when not provided"""
    session, _ = mock_session

    mock_record = MockKnowledgeRecord(knowledge_name="kb1")
    mock_record.knowledge_id = 7

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)

    # Deterministic index name
    monkeypatch.setattr("backend.database.knowledge_db._generate_index_name", lambda _: "7-generated")

    test_query = {
        "knowledge_describe": "desc",
        "user_id": "user-1",
        "tenant_id": "tenant-1",
        "embedding_model_name": "model-x",
        "knowledge_name": "kb1",
    }

    with patch('backend.database.knowledge_db.KnowledgeRecord', return_value=mock_record):
        result = create_knowledge_record(test_query)

    assert result == {
        "knowledge_id": 7,
        "index_name": "7-generated",
        "knowledge_name": "kb1",
    }
    assert mock_record.index_name == "7-generated"
    assert session.flush.call_count == 2  # initial insert + index_name update
    session.commit.assert_called_once()


def test_update_knowledge_record_success(monkeypatch, mock_session):
    """Test successful update of knowledge record"""
    session, query = mock_session
    
    # Create mock knowledge record
    mock_record = MockKnowledgeRecord()
    mock_record.knowledge_describe = "old description"
    mock_record.embedding_model_name = "old_model"
    
    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_record
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    test_query = {
        "index_name": "test_knowledge",
        "knowledge_describe": "Updated description",
        "user_id": "test_user"
    }
    
    result = update_knowledge_record(test_query)
    
    assert result is True
    assert mock_record.knowledge_describe == "Updated description"
    assert mock_record.updated_by == "test_user"
    session.flush.assert_called_once()
    session.commit.assert_called_once()


def test_update_knowledge_record_not_found(monkeypatch, mock_session):
    """Test updating non-existent knowledge record"""
    session, query = mock_session
    
    mock_filter = MagicMock()
    mock_filter.first.return_value = None
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    test_query = {
        "index_name": "nonexistent_knowledge",
        "knowledge_describe": "Updated description",
        "user_id": "test_user"
    }
    
    result = update_knowledge_record(test_query)
    
    assert result is False


def test_update_knowledge_record_exception(monkeypatch, mock_session):
    """Test exception during knowledge record update"""
    session, query = mock_session
    session.flush.side_effect = MockSQLAlchemyError("Database error")
    
    mock_record = MockKnowledgeRecord()
    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_record
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    test_query = {
        "index_name": "test_knowledge",
        "knowledge_describe": "Updated description",
        "user_id": "test_user"
    }
    
    with pytest.raises(MockSQLAlchemyError, match="Database error"):
        update_knowledge_record(test_query)
    
    session.rollback.assert_called_once()


def test_delete_knowledge_record_success(monkeypatch, mock_session):
    """Test successful deletion of knowledge record (soft delete)"""
    session, query = mock_session
    
    # Create mock knowledge record
    mock_record = MockKnowledgeRecord()
    mock_record.delete_flag = 'N'
    
    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_record
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    test_query = {
        "index_name": "test_knowledge",
        "user_id": "test_user"
    }
    
    result = delete_knowledge_record(test_query)
    
    assert result is True
    assert mock_record.delete_flag == 'Y'
    assert mock_record.updated_by == "test_user"
    session.flush.assert_called_once()
    session.commit.assert_called_once()


def test_delete_knowledge_record_not_found(monkeypatch, mock_session):
    """Test deleting non-existent knowledge record"""
    session, query = mock_session
    
    mock_filter = MagicMock()
    mock_filter.first.return_value = None
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    test_query = {
        "index_name": "nonexistent_knowledge",
        "user_id": "test_user"
    }
    
    result = delete_knowledge_record(test_query)
    
    assert result is False


def test_delete_knowledge_record_exception(monkeypatch, mock_session):
    """Test exception during knowledge record deletion"""
    session, query = mock_session
    session.flush.side_effect = MockSQLAlchemyError("Database error")
    
    mock_record = MockKnowledgeRecord()
    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_record
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    test_query = {
        "index_name": "test_knowledge",
        "user_id": "test_user"
    }
    
    with pytest.raises(MockSQLAlchemyError, match="Database error"):
        delete_knowledge_record(test_query)
    
    session.rollback.assert_called_once()


def test_get_knowledge_record_found(monkeypatch, mock_session):
    """Test successfully retrieving knowledge record"""
    session, query = mock_session
    
    # Create mock knowledge record
    mock_record = MockKnowledgeRecord()
    mock_record.knowledge_id = 123
    mock_record.index_name = "test_knowledge"
    
    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_record
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    # Mock as_dict function
    expected_result = {
        "knowledge_id": 123,
        "index_name": "test_knowledge",
        "knowledge_describe": "test description"
    }
    monkeypatch.setattr("backend.database.knowledge_db.as_dict", lambda x: expected_result)
    
    test_query = {
        "index_name": "test_knowledge",
        "tenant_id": "test_tenant"
    }
    
    result = get_knowledge_record(test_query)
    
    assert result == expected_result


def test_get_knowledge_record_not_found(monkeypatch, mock_session):
    """Test retrieving non-existent knowledge record"""
    session, query = mock_session

    mock_filter = MagicMock()
    mock_filter.first.return_value = None
    mock_filter.filter.return_value = mock_filter  # Support chaining
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)

    test_query = {
        "index_name": "nonexistent_knowledge"
    }

    result = get_knowledge_record(test_query)

    assert result == {}


def test_get_knowledge_record_without_tenant_id(monkeypatch, mock_session):
    """Test retrieving knowledge record without tenant_id"""
    session, query = mock_session
    
    mock_record = MockKnowledgeRecord()
    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_record
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    expected_result = {"knowledge_id": 1}
    monkeypatch.setattr("backend.database.knowledge_db.as_dict", lambda x: expected_result)
    
    test_query = {
        "index_name": "test_knowledge"
        # Note: no tenant_id
    }
    
    result = get_knowledge_record(test_query)
    
    assert result == expected_result


def test_get_knowledge_record_exception(monkeypatch, mock_session):
    """Test exception during knowledge record retrieval"""
    session, query = mock_session
    query.filter.side_effect = MockSQLAlchemyError("Database error")
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    test_query = {
        "index_name": "test_knowledge"
    }
    
    with pytest.raises(MockSQLAlchemyError, match="Database error"):
        get_knowledge_record(test_query)


def test_get_knowledge_record_with_none_query(monkeypatch, mock_session):
    """Test get_knowledge_record with None query raises TypeError"""
    session, query = mock_session

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)

    # When query is None, checking 'index_name' in query will raise TypeError
    with pytest.raises(TypeError, match="argument of type 'NoneType' is not iterable"):
        get_knowledge_record(None)


def test_get_knowledge_record_without_index_name_key(monkeypatch, mock_session):
    """Test get_knowledge_record with query missing index_name and knowledge_name keys"""
    session, query = mock_session

    mock_filter = MagicMock()
    mock_filter.first.return_value = None
    mock_filter.filter.return_value = mock_filter  # Support chaining
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)

    # When query doesn't have 'index_name' or 'knowledge_name' key, no specific filter is applied
    test_query = {
        "tenant_id": "test_tenant"
        # Missing index_name and knowledge_name keys
    }

    result = get_knowledge_record(test_query)

    assert result == {}


def test_get_knowledge_info_by_knowledge_ids_success(monkeypatch, mock_session):
    """Test retrieving knowledge info by knowledge ID list"""
    session, query = mock_session
    
    # Create a list of mock knowledge records
    mock_record1 = MockKnowledgeRecord()
    mock_record1.knowledge_id = 1
    mock_record1.index_name = "knowledge1"
    mock_record1.knowledge_name = "Knowledge Base 1"
    mock_record1.knowledge_sources = "elasticsearch"
    mock_record1.embedding_model_name = "model1"
    
    mock_record2 = MockKnowledgeRecord()
    mock_record2.knowledge_id = 2
    mock_record2.index_name = "knowledge2"
    mock_record2.knowledge_name = "Knowledge Base 2"
    mock_record2.knowledge_sources = "vectordb"
    mock_record2.embedding_model_name = "model2"
    
    mock_filter = MagicMock()
    mock_filter.all.return_value = [mock_record1, mock_record2]
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    knowledge_ids = ["1", "2"]
    result = get_knowledge_info_by_knowledge_ids(knowledge_ids)
    
    expected = [
        {
            "knowledge_id": 1,
            "index_name": "knowledge1",
            "knowledge_name": "Knowledge Base 1",
            "knowledge_sources": "elasticsearch",
            "embedding_model_name": "model1"
        },
        {
            "knowledge_id": 2,
            "index_name": "knowledge2",
            "knowledge_name": "Knowledge Base 2",
            "knowledge_sources": "vectordb",
            "embedding_model_name": "model2"
        }
    ]
    
    assert result == expected


def test_get_knowledge_info_by_knowledge_ids_exception(monkeypatch, mock_session):
    """Test exception when retrieving knowledge info by knowledge ID list"""
    session, query = mock_session
    query.filter.side_effect = MockSQLAlchemyError("Database error")
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    knowledge_ids = ["1", "2"]
    
    with pytest.raises(MockSQLAlchemyError, match="Database error"):
        get_knowledge_info_by_knowledge_ids(knowledge_ids)


def test_get_knowledge_ids_by_index_names_success(monkeypatch, mock_session):
    """Test retrieving knowledge IDs by index name list"""
    session, _ = mock_session
    
    # Mock query results
    class MockResult:
        def __init__(self, knowledge_id):
            self.knowledge_id = knowledge_id
    
    mock_results = [MockResult("1"), MockResult("2")]
    
    # Create a new mock for this specific function since it uses session.query(KnowledgeRecord.knowledge_id)
    mock_specific_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.all.return_value = mock_results
    mock_specific_query.filter.return_value = mock_filter
    
    # Reset session.query return value to handle specific query parameters
    def mock_query_func(*args, **kwargs):
        return mock_specific_query
    
    session.query = mock_query_func
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    index_names = ["knowledge1", "knowledge2"]
    result = get_knowledge_ids_by_index_names(index_names)
    
    assert result == ["1", "2"]


def test_get_knowledge_ids_by_index_names_exception(monkeypatch, mock_session):
    """Test exception when retrieving knowledge IDs by index name list"""
    session, query = mock_session
    query.filter.side_effect = MockSQLAlchemyError("Database error")
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    index_names = ["knowledge1", "knowledge2"]
    
    with pytest.raises(MockSQLAlchemyError, match="Database error"):
        get_knowledge_ids_by_index_names(index_names)


def test_get_knowledge_info_by_tenant_id_success(monkeypatch, mock_session):
    """Test retrieving knowledge info by tenant ID"""
    session, query = mock_session
    
    mock_record1 = MockKnowledgeRecord()
    mock_record1.knowledge_id = 1
    mock_record1.tenant_id = "tenant1"
    
    mock_record2 = MockKnowledgeRecord()
    mock_record2.knowledge_id = 2
    mock_record2.tenant_id = "tenant1"
    
    mock_filter = MagicMock()
    mock_filter.all.return_value = [mock_record1, mock_record2]
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    # Mock as_dict function
    def mock_as_dict(record):
        return {"knowledge_id": record.knowledge_id, "tenant_id": record.tenant_id}
    
    monkeypatch.setattr("backend.database.knowledge_db.as_dict", mock_as_dict)
    
    tenant_id = "tenant1"
    result = get_knowledge_info_by_tenant_id(tenant_id)
    
    expected = [
        {"knowledge_id": 1, "tenant_id": "tenant1"},
        {"knowledge_id": 2, "tenant_id": "tenant1"}
    ]
    
    assert result == expected


def test_get_knowledge_info_by_tenant_id_exception(monkeypatch, mock_session):
    """Test exception when retrieving knowledge info by tenant ID"""
    session, query = mock_session
    query.filter.side_effect = MockSQLAlchemyError("Database error")
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    tenant_id = "tenant1"
    
    with pytest.raises(MockSQLAlchemyError, match="Database error"):
        get_knowledge_info_by_tenant_id(tenant_id)


def test_update_model_name_by_index_name_success(monkeypatch, mock_session):
    """Test updating model name by index name"""
    session, query = mock_session
    
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    result = update_model_name_by_index_name("test_index", "new_model", "tenant1", "user1")
    
    assert result is True
    mock_update.assert_called_once_with({"embedding_model_name": "new_model", "updated_by": "user1"})
    session.commit.assert_called_once()


def test_update_model_name_by_index_name_exception(monkeypatch, mock_session):
    """Test exception when updating model name by index name"""
    session, query = mock_session
    mock_update = MagicMock(side_effect=MockSQLAlchemyError("Database error"))
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    with pytest.raises(MockSQLAlchemyError, match="Database error"):
        update_model_name_by_index_name("test_index", "new_model", "tenant1", "user1")


def test_create_knowledge_record_with_index_name_only(monkeypatch, mock_session):
    """Test create_knowledge_record when only index_name is provided (no knowledge_name)"""
    session, _ = mock_session
    
    mock_record = MockKnowledgeRecord()
    mock_record.knowledge_id = 123
    mock_record.index_name = "test_index"
    mock_record.knowledge_name = "test_index"  # Should use index_name as knowledge_name
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    test_query = {
        "index_name": "test_index",
        "knowledge_describe": "Test description",
        "user_id": "test_user",
        "tenant_id": "test_tenant",
        "embedding_model_name": "test_model"
        # No knowledge_name provided
    }
    
    with patch('backend.database.knowledge_db.KnowledgeRecord', return_value=mock_record):
        result = create_knowledge_record(test_query)
    
    assert result == {
        "knowledge_id": 123,
        "index_name": "test_index",
        "knowledge_name": "test_index",
    }
    session.add.assert_called_once_with(mock_record)
    assert session.flush.call_count == 1
    session.commit.assert_called_once()


def test_create_knowledge_record_without_user_id(monkeypatch, mock_session):
    """Test create_knowledge_record without user_id"""
    session, _ = mock_session
    
    mock_record = MockKnowledgeRecord()
    mock_record.knowledge_id = 123
    mock_record.index_name = "test_index"
    mock_record.knowledge_name = "test_kb"
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    test_query = {
        "index_name": "test_index",
        "knowledge_name": "test_kb",
        "knowledge_describe": "Test description",
        "tenant_id": "test_tenant",
        "embedding_model_name": "test_model"
        # No user_id provided
    }
    
    with patch('backend.database.knowledge_db.KnowledgeRecord', return_value=mock_record):
        result = create_knowledge_record(test_query)
    
    assert result["knowledge_id"] == 123
    session.add.assert_called_once_with(mock_record)
    session.commit.assert_called_once()


def test_create_knowledge_record_without_index_name_and_knowledge_name(monkeypatch, mock_session):
    """Test create_knowledge_record when neither index_name nor knowledge_name is provided"""
    session, _ = mock_session
    
    mock_record = MockKnowledgeRecord()
    mock_record.knowledge_id = 7
    mock_record.knowledge_name = None  # Both are None, so knowledge_name will be None
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    # Deterministic index name
    monkeypatch.setattr("backend.database.knowledge_db._generate_index_name", lambda _: "7-generated")
    
    test_query = {
        "knowledge_describe": "desc",
        "user_id": "user-1",
        "tenant_id": "tenant-1",
        "embedding_model_name": "model-x"
        # Neither index_name nor knowledge_name provided
    }
    
    with patch('backend.database.knowledge_db.KnowledgeRecord', return_value=mock_record):
        result = create_knowledge_record(test_query)
    
    assert result == {
        "knowledge_id": 7,
        "index_name": "7-generated",
        "knowledge_name": None,
    }
    assert mock_record.index_name == "7-generated"
    assert session.flush.call_count == 2  # initial insert + index_name update
    session.commit.assert_called_once()


def test_update_knowledge_record_without_user_id(monkeypatch, mock_session):
    """Test update_knowledge_record without user_id"""
    session, query = mock_session
    
    mock_record = MockKnowledgeRecord()
    mock_record.knowledge_describe = "old description"
    mock_record.updated_by = "original_user"
    
    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_record
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    test_query = {
        "index_name": "test_knowledge",
        "knowledge_describe": "Updated description"
        # No user_id provided
    }
    
    result = update_knowledge_record(test_query)
    
    assert result is True
    assert mock_record.knowledge_describe == "Updated description"
    # updated_by should remain unchanged when user_id is not provided
    assert mock_record.updated_by == "original_user"
    session.flush.assert_called_once()
    session.commit.assert_called_once()


def test_delete_knowledge_record_without_user_id(monkeypatch, mock_session):
    """Test delete_knowledge_record without user_id"""
    session, query = mock_session
    
    mock_record = MockKnowledgeRecord()
    mock_record.delete_flag = 'N'
    mock_record.updated_by = "original_user"
    
    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_record
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    test_query = {
        "index_name": "test_knowledge"
        # No user_id provided
    }
    
    result = delete_knowledge_record(test_query)
    
    assert result is True
    assert mock_record.delete_flag == 'Y'
    # updated_by should remain unchanged when user_id is not provided
    assert mock_record.updated_by == "original_user"
    session.flush.assert_called_once()
    session.commit.assert_called_once()


def test_get_knowledge_record_with_tenant_id_none(monkeypatch, mock_session):
    """Test get_knowledge_record with tenant_id explicitly set to None"""
    session, query = mock_session

    mock_record = MockKnowledgeRecord()
    mock_record.knowledge_id = 123

    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_record
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)

    expected_result = {"knowledge_id": 123}
    monkeypatch.setattr("backend.database.knowledge_db.as_dict", lambda x: expected_result)

    test_query = {
        "index_name": "test_knowledge",
        "tenant_id": None  # Explicitly None
    }

    result = get_knowledge_record(test_query)

    assert result == expected_result
    # Should not add tenant_id filter when tenant_id is None
    assert query.filter.call_count >= 1


def test_get_knowledge_record_by_knowledge_name_success(monkeypatch, mock_session):
    """Test successfully retrieving knowledge record by knowledge_name"""
    session, query = mock_session

    # Create mock knowledge record
    mock_record = MockKnowledgeRecord()
    mock_record.knowledge_id = 123
    mock_record.knowledge_name = "test_kb"

    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_record
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)

    # Mock as_dict function
    expected_result = {
        "knowledge_id": 123,
        "knowledge_name": "test_kb",
        "index_name": "test_index"
    }
    monkeypatch.setattr("backend.database.knowledge_db.as_dict", lambda x: expected_result)

    test_query = {
        "knowledge_name": "test_kb",
        "tenant_id": "test_tenant"
    }

    result = get_knowledge_record(test_query)

    assert result == expected_result


def test_get_knowledge_record_by_knowledge_name_not_found(monkeypatch, mock_session):
    """Test retrieving knowledge record by knowledge_name when not found"""
    session, query = mock_session

    mock_filter = MagicMock()
    mock_filter.first.return_value = None
    mock_filter.filter.return_value = mock_filter  # Support chaining
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)

    test_query = {
        "knowledge_name": "nonexistent_kb",
        "tenant_id": "test_tenant"
    }

    result = get_knowledge_record(test_query)

    assert result == {}


def test_get_knowledge_info_by_knowledge_ids_empty_list(monkeypatch, mock_session):
    """Test get_knowledge_info_by_knowledge_ids with empty list"""
    session, query = mock_session
    
    mock_filter = MagicMock()
    mock_filter.all.return_value = []
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    knowledge_ids = []
    result = get_knowledge_info_by_knowledge_ids(knowledge_ids)
    
    assert result == []


def test_get_knowledge_info_by_knowledge_ids_includes_knowledge_name(monkeypatch, mock_session):
    """Test get_knowledge_info_by_knowledge_ids includes knowledge_name field"""
    session, query = mock_session
    
    mock_record1 = MockKnowledgeRecord()
    mock_record1.knowledge_id = 1
    mock_record1.index_name = "knowledge1"
    mock_record1.knowledge_name = "Knowledge Base 1"
    mock_record1.knowledge_sources = "elasticsearch"
    mock_record1.embedding_model_name = "model1"
    
    mock_filter = MagicMock()
    mock_filter.all.return_value = [mock_record1]
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    knowledge_ids = ["1"]
    result = get_knowledge_info_by_knowledge_ids(knowledge_ids)
    
    expected = [
        {
            "knowledge_id": 1,
            "index_name": "knowledge1",
            "knowledge_name": "Knowledge Base 1",
            "knowledge_sources": "elasticsearch",
            "embedding_model_name": "model1"
        }
    ]
    
    assert result == expected
    assert "knowledge_name" in result[0]


def test_get_knowledge_info_by_knowledge_ids_with_none_knowledge_name(monkeypatch, mock_session):
    """Test get_knowledge_info_by_knowledge_ids when knowledge_name is None"""
    session, query = mock_session
    
    mock_record1 = MockKnowledgeRecord()
    mock_record1.knowledge_id = 1
    mock_record1.index_name = "knowledge1"
    mock_record1.knowledge_name = None  # None knowledge_name
    mock_record1.knowledge_sources = "elasticsearch"
    mock_record1.embedding_model_name = "model1"
    
    mock_filter = MagicMock()
    mock_filter.all.return_value = [mock_record1]
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    knowledge_ids = ["1"]
    result = get_knowledge_info_by_knowledge_ids(knowledge_ids)
    
    expected = [
        {
            "knowledge_id": 1,
            "index_name": "knowledge1",
            "knowledge_name": None,
            "knowledge_sources": "elasticsearch",
            "embedding_model_name": "model1"
        }
    ]
    
    assert result == expected
    assert result[0]["knowledge_name"] is None


def test_get_index_name_by_knowledge_name_success(monkeypatch, mock_session):
    """Test successfully getting index_name by knowledge_name"""
    session, query = mock_session
    
    mock_record = MockKnowledgeRecord()
    mock_record.knowledge_name = "My Knowledge Base"
    mock_record.index_name = "123-abc123def456"
    mock_record.tenant_id = "tenant1"
    mock_record.delete_flag = 'N'
    
    mock_filter = MagicMock()
    mock_filter.first.return_value = mock_record
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    result = get_index_name_by_knowledge_name("My Knowledge Base", "tenant1")
    
    assert result == "123-abc123def456"


def test_get_index_name_by_knowledge_name_not_found(monkeypatch, mock_session):
    """Test get_index_name_by_knowledge_name when knowledge base is not found"""
    session, query = mock_session
    
    mock_filter = MagicMock()
    mock_filter.first.return_value = None
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    with pytest.raises(ValueError, match="Knowledge base 'Nonexistent KB' not found for the current tenant"):
        get_index_name_by_knowledge_name("Nonexistent KB", "tenant1")


def test_get_index_name_by_knowledge_name_exception(monkeypatch, mock_session):
    """Test exception when getting index_name by knowledge_name"""
    session, query = mock_session
    query.filter.side_effect = MockSQLAlchemyError("Database error")
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    with pytest.raises(MockSQLAlchemyError, match="Database error"):
        get_index_name_by_knowledge_name("My Knowledge Base", "tenant1")


def test_generate_index_name_format(monkeypatch):
    """Test _generate_index_name generates correct format"""
    # Mock uuid to get deterministic result
    mock_uuid = MagicMock()
    mock_uuid.hex = "abc123def456"
    monkeypatch.setattr("backend.database.knowledge_db.uuid.uuid4", lambda: mock_uuid)
    
    result = _generate_index_name(123)
    
    assert result == "123-abc123def456"
    assert result.startswith("123-")
    assert len(result) == len("123-abc123def456")


def test_get_knowledge_ids_by_index_names_empty_list(monkeypatch, mock_session):
    """Test get_knowledge_ids_by_index_names with empty list"""
    session, _ = mock_session
    
    mock_specific_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.all.return_value = []
    mock_specific_query.filter.return_value = mock_filter
    
    def mock_query_func(*args, **kwargs):
        return mock_specific_query
    
    session.query = mock_query_func
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.knowledge_db.get_db_session", lambda: mock_ctx)
    
    index_names = []
    result = get_knowledge_ids_by_index_names(index_names)
    
    assert result == [] 