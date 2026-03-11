import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

import pytest
from unittest.mock import MagicMock, patch


# First mock the consts module to avoid ModuleNotFoundError
consts_mock = MagicMock()
consts_mock.const = MagicMock()
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

sys.modules['consts'] = consts_mock
sys.modules['consts.const'] = consts_mock.const

# Mock database client
client_mock = MagicMock()
client_mock.MinioClient = MagicMock()
client_mock.PostgresClient = MagicMock()
client_mock.db_client = MagicMock()
client_mock.get_db_session = MagicMock()
client_mock.as_dict = MagicMock()
client_mock.filter_property = MagicMock()

sys.modules['database.client'] = client_mock
sys.modules['backend.database.client'] = client_mock


# Create mock classes that work with SQLAlchemy query
class MockUserTokenInfo:
    """Mock UserTokenInfo for testing."""
    _instances = []
    
    def __init__(self, token_id=1, access_key="nexent-abc123", user_id="user123",
                 delete_flag="N", create_time=None, update_time=None, created_by=None, updated_by=None):
        self.token_id = token_id
        self.access_key = access_key
        self.user_id = user_id
        self.delete_flag = delete_flag
        self.create_time = create_time
        self.update_time = update_time
        self.created_by = created_by or user_id
        self.updated_by = updated_by or user_id
        MockUserTokenInfo._instances.append(self)
    
    @property
    def token_id(self):
        return self._token_id
    
    @token_id.setter
    def token_id(self, value):
        self._token_id = value
    
    @property
    def user_id(self):
        return self._user_id
    
    @user_id.setter
    def user_id(self, value):
        self._user_id = value
    
    @property
    def access_key(self):
        return self._access_key
    
    @access_key.setter
    def access_key(self, value):
        self._access_key = value
    
    @property
    def delete_flag(self):
        return self._delete_flag
    
    @delete_flag.setter
    def delete_flag(self, value):
        self._delete_flag = value
    
    @property
    def create_time(self):
        return self._create_time
    
    @create_time.setter
    def create_time(self, value):
        self._create_time = value
    
    @classmethod
    def reset(cls):
        cls._instances = []


class MockUserTokenUsageLog:
    """Mock UserTokenUsageLog for testing."""
    _instances = []
    
    def __init__(self, token_usage_id=1, token_id=1, call_function_name="run_chat",
                 related_id=123, created_by="user123", meta_data=None, create_time=None):
        self.token_usage_id = token_usage_id
        self.token_id = token_id
        self.call_function_name = call_function_name
        self.related_id = related_id
        self.created_by = created_by
        self.meta_data = meta_data
        self.create_time = create_time
        MockUserTokenUsageLog._instances.append(self)
    
    @classmethod
    def reset(cls):
        cls._instances = []


# Set class attributes for SQLAlchemy filter operations
MockUserTokenInfo.token_id = 1
MockUserTokenInfo.access_key = "test"
MockUserTokenInfo.user_id = "test"
MockUserTokenInfo.delete_flag = "N"

# Mock the create_time attribute with a mock that supports .desc()
class MockColumn:
    def desc(self):
        return "desc"

MockUserTokenInfo.create_time = MockColumn()

MockUserTokenUsageLog.token_usage_id = 1
MockUserTokenUsageLog.token_id = 1
MockUserTokenUsageLog.call_function_name = "test"
MockUserTokenUsageLog.related_id = 1
MockUserTokenUsageLog.create_time = MockColumn()

db_models_mock = MagicMock()
db_models_mock.UserTokenInfo = MockUserTokenInfo
db_models_mock.UserTokenUsageLog = MockUserTokenUsageLog
sys.modules['database.db_models'] = db_models_mock
sys.modules['backend.database.db_models'] = db_models_mock

# Mock exceptions
exceptions_mock = MagicMock()
sys.modules['consts.exceptions'] = exceptions_mock
sys.modules['backend.consts.exceptions'] = exceptions_mock

# Mock sqlalchemy
sqlalchemy_mock = MagicMock()
sqlalchemy_mock.exc.SQLAlchemyError = type("SQLAlchemyError", (Exception,), {})
sys.modules['sqlalchemy'] = sqlalchemy_mock
sys.modules['sqlalchemy.exc'] = sqlalchemy_mock.exc


# Import the module under test
from backend.database import token_db


class MockQuery:
    """Mock query object for testing."""
    def __init__(self, model_class, instances):
        self._model_class = model_class
        self._instances = instances
        self._filters = []
        self._order_by = None

    def filter(self, *args):
        self._filters.append(args)
        return self

    def filter_by(self, **kwargs):
        self._filters.append(kwargs)
        return self

    def order_by(self, *args):
        self._order_by = args
        return self

    def first(self):
        # Simple implementation - return first matching instance
        if not self._instances:
            return None
        return self._instances[0] if self._instances else None

    def all(self):
        return list(self._instances)


class MockSession:
    """Mock database session for testing."""
    def __init__(self):
        self.added_objects = []
        MockUserTokenInfo.reset()
        MockUserTokenUsageLog.reset()
        self._tokens = []
        self._usage_logs = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def add(self, obj):
        self.added_objects.append(obj)
        if isinstance(obj, MockUserTokenInfo):
            obj.token_id = len(self._tokens) + 1
            self._tokens.append(obj)
        if isinstance(obj, MockUserTokenUsageLog):
            obj.token_usage_id = len(self._usage_logs) + 1
            self._usage_logs.append(obj)

    def flush(self):
        pass

    def query(self, model_class):
        if model_class == MockUserTokenInfo:
            return MockQuery(model_class, self._tokens)
        if model_class == MockUserTokenUsageLog:
            return MockQuery(model_class, self._usage_logs)
        return MockQuery(model_class, [])


@pytest.fixture
def mock_session():
    """Fixture to provide a mock database session."""
    return MockSession()


@pytest.fixture
def mock_db_session(mock_session):
    """Fixture to mock get_db_session."""
    with patch.object(token_db, 'get_db_session', return_value=mock_session):
        yield mock_session


class TestGenerateAccessKey:
    """Tests for generate_access_key function."""

    def test_generate_access_key_format(self):
        """Test that generated access key has correct format."""
        key = token_db.generate_access_key()
        assert key.startswith("nexent-")
        assert len(key) > len("nexent-")

    def test_generate_access_key_unique(self):
        """Test that generated access keys are unique."""
        keys = [token_db.generate_access_key() for _ in range(10)]
        assert len(set(keys)) == 10


class TestCreateToken:
    """Tests for create_token function."""

    def test_create_token_success(self, mock_db_session):
        """Test successful token creation."""
        result = token_db.create_token("nexent-test123", "user123")

        assert result["token_id"] is not None
        assert result["access_key"] == "nexent-test123"
        assert result["user_id"] == "user123"
        assert len(mock_db_session.added_objects) == 1


class TestListTokensByUser:
    """Tests for list_tokens_by_user function."""

    def test_list_tokens_by_user_success(self, mock_db_session):
        """Test successful token listing."""
        # Add some tokens
        token1 = MockUserTokenInfo(token_id=1, access_key="nexent-key1", user_id="user123")
        token2 = MockUserTokenInfo(token_id=2, access_key="nexent-key2", user_id="user123")
        mock_db_session._tokens.extend([token1, token2])

        result = token_db.list_tokens_by_user("user123")

        assert len(result) >= 1

    def test_list_tokens_by_user_empty(self, mock_db_session):
        """Test listing tokens when user has none."""
        result = token_db.list_tokens_by_user("user_nonexistent")
        assert isinstance(result, list)


class TestGetTokenById:
    """Tests for get_token_by_id function."""

    def test_get_token_by_id_success(self, mock_db_session):
        """Test successful token retrieval by ID."""
        token = MockUserTokenInfo(token_id=1, access_key="nexent-key1", user_id="user123")
        mock_db_session._tokens.append(token)

        result = token_db.get_token_by_id(1)
        assert result is not None

    def test_get_token_by_id_not_found(self, mock_db_session):
        """Test token retrieval with non-existent ID."""
        result = token_db.get_token_by_id(999)
        assert result is None


class TestGetTokenByAccessKey:
    """Tests for get_token_by_access_key function."""

    def test_get_token_by_access_key_success(self, mock_db_session):
        """Test successful token retrieval by access key."""
        token = MockUserTokenInfo(token_id=1, access_key="nexent-key1", user_id="user123", delete_flag="N")
        mock_db_session._tokens.append(token)

        result = token_db.get_token_by_access_key("nexent-key1")
        assert result is not None
        assert result["access_key"] == "nexent-key1"
        assert result["user_id"] == "user123"

    def test_get_token_by_access_key_not_found(self, mock_db_session):
        """Test token retrieval with non-existent access key."""
        result = token_db.get_token_by_access_key("nexent-nonexistent")
        assert result is None


class TestDeleteToken:
    """Tests for delete_token function."""

    def test_delete_token_success(self, mock_db_session):
        """Test successful token deletion."""
        token = MockUserTokenInfo(token_id=1, access_key="nexent-key1", user_id="user123", delete_flag="N")
        mock_db_session._tokens.append(token)

        result = token_db.delete_token(1, "user123")
        assert result is True
        assert token.delete_flag == "Y"

    def test_delete_token_not_found(self, mock_db_session):
        """Test deletion of non-existent token."""
        result = token_db.delete_token(999, "user123")
        assert result is False


class TestLogTokenUsage:
    """Tests for log_token_usage function."""

    def test_log_token_usage_success(self, mock_db_session):
        """Test successful token usage logging."""
        result = token_db.log_token_usage(
            token_id=1,
            call_function_name="run_chat",
            related_id=123,
            created_by="user123",
            metadata={"query": "test"}
        )

        assert result is not None
        assert len(mock_db_session.added_objects) == 1

    def test_log_token_usage_without_metadata(self, mock_db_session):
        """Test token usage logging without metadata."""
        result = token_db.log_token_usage(
            token_id=1,
            call_function_name="get_agent_info_list",
            related_id=None,
            created_by="user123"
        )

        assert result is not None


class TestGetLatestUsageMetadata:
    """Tests for get_latest_usage_metadata function."""

    def test_get_latest_usage_metadata_success(self, mock_db_session):
        """Test successful metadata retrieval."""
        usage_log = MockUserTokenUsageLog(
            token_usage_id=1,
            token_id=1,
            call_function_name="run_chat",
            related_id=123,
            meta_data={"query": "test query"}
        )
        mock_db_session._usage_logs.append(usage_log)

        result = token_db.get_latest_usage_metadata(1, 123, "run_chat")
        assert result is not None
        assert result["query"] == "test query"

    def test_get_latest_usage_metadata_not_found(self, mock_db_session):
        """Test metadata retrieval with no matching records."""
        result = token_db.get_latest_usage_metadata(999, 999, "nonexistent")
        assert result is None
