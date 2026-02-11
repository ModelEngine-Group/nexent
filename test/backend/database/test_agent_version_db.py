import sys
import pytest
from unittest.mock import patch, MagicMock
from contextlib import contextmanager

# First mock the consts module to avoid ModuleNotFoundError
consts_mock = MagicMock()
consts_mock.const = MagicMock()
# Set up required constants in consts.const
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

# Add the mocked utils module to sys.modules
sys.modules['utils'] = utils_mock
sys.modules['utils.auth_utils'] = utils_mock.auth_utils

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

# Mock db_models module
db_models_mock = MagicMock()
db_models_mock.AgentInfo = MagicMock()
db_models_mock.ToolInstance = MagicMock()
db_models_mock.AgentRelation = MagicMock()
db_models_mock.AgentVersion = MagicMock()

# Create a mock database module to satisfy imports
# This is needed because agent_version_db.py uses "from database.client import ..."
database_mock = MagicMock()
database_mock.client = client_mock
database_mock.db_models = db_models_mock

# Add the mocked modules to sys.modules (order matters!)
# database module must be added before its submodules
sys.modules['database'] = database_mock
sys.modules['database.client'] = client_mock
sys.modules['database.db_models'] = db_models_mock
sys.modules['backend.database.client'] = client_mock
sys.modules['backend.database.db_models'] = db_models_mock

# Now we can safely import the module being tested
import backend.database.agent_version_db as agent_version_db_module
from backend.database.agent_version_db import (
    search_version_by_version_no,
    search_version_by_id,
    query_version_list,
    query_current_version_no,
    query_agent_snapshot,
    query_agent_draft,
    insert_version,
    update_version_status,
    update_agent_current_version,
    insert_agent_snapshot,
    insert_tool_snapshot,
    insert_relation_snapshot,
    update_agent_snapshot,
    delete_agent_snapshot,
    delete_tool_snapshot,
    delete_relation_snapshot,
    get_next_version_no,
    delete_version,
    SOURCE_TYPE_NORMAL,
    SOURCE_TYPE_ROLLBACK,
    STATUS_RELEASED,
    STATUS_DISABLED,
    STATUS_ARCHIVED,
)


class MockAgentVersion:
    def __init__(self):
        self.id = 1
        self.agent_id = 1
        self.tenant_id = "tenant1"
        self.version_no = 1
        self.version_name = "v1.0"
        self.release_note = "Initial release"
        self.source_type = SOURCE_TYPE_NORMAL
        self.source_version_no = None
        self.status = STATUS_RELEASED
        self.delete_flag = "N"
        self.created_by = "user1"
        self.create_time = "2023-01-01 12:00:00"
        self.__dict__ = {
            "id": 1,
            "agent_id": 1,
            "tenant_id": "tenant1",
            "version_no": 1,
            "version_name": "v1.0",
            "release_note": "Initial release",
            "source_type": SOURCE_TYPE_NORMAL,
            "source_version_no": None,
            "status": STATUS_RELEASED,
            "delete_flag": "N",
            "created_by": "user1",
            "create_time": "2023-01-01 12:00:00",
        }


class MockAgentInfo:
    def __init__(self):
        self.agent_id = 1
        self.tenant_id = "tenant1"
        self.version_no = 1
        self.current_version_no = 1
        self.name = "Test Agent"
        self.delete_flag = "N"
        self.__dict__ = {
            "agent_id": 1,
            "tenant_id": "tenant1",
            "version_no": 1,
            "current_version_no": 1,
            "name": "Test Agent",
            "delete_flag": "N",
        }


class MockToolInstance:
    def __init__(self):
        self.tool_instance_id = 1
        self.tool_id = 1
        self.agent_id = 1
        self.tenant_id = "tenant1"
        self.version_no = 1
        self.delete_flag = "N"
        self.__dict__ = {
            "tool_instance_id": 1,
            "tool_id": 1,
            "agent_id": 1,
            "tenant_id": "tenant1",
            "version_no": 1,
            "delete_flag": "N",
        }


class MockAgentRelation:
    def __init__(self):
        self.id = 1
        self.parent_agent_id = 1
        self.selected_agent_id = 2
        self.tenant_id = "tenant1"
        self.version_no = 1
        self.delete_flag = "N"
        self.__dict__ = {
            "id": 1,
            "parent_agent_id": 1,
            "selected_agent_id": 2,
            "tenant_id": "tenant1",
            "version_no": 1,
            "delete_flag": "N",
        }


def mock_as_dict(obj):
    """Helper function to convert mock objects to dict"""
    if obj is None:
        return None
    
    # Check if it's a MagicMock without real data - return empty dict or handle specially
    if isinstance(obj, MagicMock):
        # Check if this MagicMock has been configured with real attributes
        # by checking if it has any of our expected keys as non-MagicMock values
        has_real_data = False
        for attr in ['agent_id', 'version_no', 'id', 'tool_id', 'tool_instance_id', 
                     'parent_agent_id', 'selected_agent_id', 'name']:
            if hasattr(obj, attr):
                try:
                    value = getattr(obj, attr)
                    if not isinstance(value, MagicMock):
                        has_real_data = True
                        break
                except (AttributeError, TypeError):
                    pass
        
        # If it's a MagicMock without real data, return empty dict
        # (This handles cases where MagicMock objects are returned but shouldn't be converted)
        if not has_real_data:
            # Check __dict__ for our mock classes
            if hasattr(obj, '__dict__') and isinstance(obj.__dict__, dict):
                obj_dict = obj.__dict__
                if any(key in obj_dict for key in ['agent_id', 'version_no', 'id', 'tool_id']):
                    return obj_dict.copy()
            return {}
    
    # For our custom mock classes (MockAgentInfo, MockToolInstance, etc.), use __dict__ directly
    # These classes set self.__dict__ explicitly with the data we need
    if hasattr(obj, '__dict__') and isinstance(obj.__dict__, dict):
        # Check if this looks like one of our mock classes by checking for key attributes
        # Our mock classes have __dict__ set with actual data, not just mock internals
        obj_dict = obj.__dict__
        # Check if it has any of our expected keys (not just mock internals)
        if any(key in obj_dict for key in ['agent_id', 'version_no', 'id', 'tool_id', 'tool_instance_id', 
                                           'parent_agent_id', 'selected_agent_id']):
            return obj_dict.copy()
    
    # For other objects, build dict from attributes
    result = {}
    for attr in ['agent_id', 'version_no', 'tenant_id', 'id', 'tool_id', 'selected_agent_id', 
                 'tool_instance_id', 'parent_agent_id', 'name', 'version_name', 'status',
                 'current_version_no', 'delete_flag', 'created_by', 'create_time', 
                 'release_note', 'source_type', 'source_version_no']:
        if hasattr(obj, attr):
            try:
                value = getattr(obj, attr)
                # Skip MagicMock objects that aren't configured (they'll have default MagicMock behavior)
                if not isinstance(value, MagicMock):
                    result[attr] = value
            except (AttributeError, TypeError):
                pass
    # Return the result dict (may be empty for objects without configured attributes)
    return result


def mock_sqlalchemy_insert(monkeypatch):
    """Helper function to mock SQLAlchemy insert"""
    from sqlalchemy.sql import Insert
    
    def insert_wrapper(table):
        """Wrapper that accepts the actual table class (or MagicMock) and returns a mock statement"""
        # Create a mock statement that chains properly
        # This bypasses SQLAlchemy's table validation by directly returning a mock
        mock_stmt = MagicMock(spec=Insert)
        mock_values_result = MagicMock()
        mock_returning_result = MagicMock()
        
        # Chain: .values(**kwargs) returns an object that has .returning()
        mock_values_result.returning = lambda *args, **kwargs: mock_returning_result
        mock_stmt.values = lambda **kwargs: mock_values_result
        
        # The final statement is what gets executed
        return mock_stmt
    
    # Patch the imported function in agent_version_db module (this is what the code actually uses)
    # We patch at the module level after import, so it overrides the imported function
    monkeypatch.setattr(agent_version_db_module, "insert", insert_wrapper)
    return insert_wrapper


def mock_sqlalchemy_update(monkeypatch):
    """Helper function to mock SQLAlchemy update"""
    from sqlalchemy.sql import Update
    
    def update_wrapper(table):
        """Wrapper that accepts the actual table class (or MagicMock) and returns a mock statement"""
        # Create a mock statement that chains properly
        # This bypasses SQLAlchemy's table validation by directly returning a mock
        mock_stmt = MagicMock(spec=Update)
        mock_where_result = MagicMock()
        
        # Chain: .where(...) returns an object that has .values()
        # .values(**kwargs) returns the statement itself (for chaining)
        mock_where_result.values = lambda **kwargs: mock_stmt
        mock_stmt.where = lambda *args, **kwargs: mock_where_result
        
        # The final statement is what gets executed
        return mock_stmt
    
    # Patch the imported function in agent_version_db module (this is what the code actually uses)
    # We patch at the module level after import, so it overrides the imported function
    monkeypatch.setattr(agent_version_db_module, "update", update_wrapper)
    return update_wrapper


@pytest.fixture
def mock_session():
    """Create a mock database session"""
    mock_session = MagicMock()
    mock_query = MagicMock()
    mock_session.query.return_value = mock_query
    return mock_session, mock_query


def test_search_version_by_version_no_found(monkeypatch, mock_session):
    """Test successfully finding version by version_no"""
    session, query = mock_session
    mock_version = MockAgentVersion()
    
    mock_filter = MagicMock()
    mock_filter.first = lambda: mock_version
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    result = search_version_by_version_no(agent_id=1, tenant_id="tenant1", version_no=1)
    
    assert result is not None
    assert result["version_no"] == 1
    assert result["version_name"] == "v1.0"
    assert result["status"] == STATUS_RELEASED


def test_search_version_by_version_no_not_found(monkeypatch, mock_session):
    """Test searching for non-existent version"""
    session, query = mock_session
    
    mock_filter = MagicMock()
    mock_filter.first = lambda: None
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    result = search_version_by_version_no(agent_id=1, tenant_id="tenant1", version_no=999)
    
    assert result is None


def test_search_version_by_id_found(monkeypatch, mock_session):
    """Test successfully finding version by id"""
    session, query = mock_session
    mock_version = MockAgentVersion()
    
    mock_filter = MagicMock()
    mock_filter.first = lambda: mock_version
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    result = search_version_by_id(version_id=1, tenant_id="tenant1")
    
    assert result is not None
    assert result["id"] == 1
    assert result["version_no"] == 1


def test_search_version_by_id_not_found(monkeypatch, mock_session):
    """Test searching for non-existent version by id"""
    session, query = mock_session
    
    mock_filter = MagicMock()
    mock_filter.first = lambda: None
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    result = search_version_by_id(version_id=999, tenant_id="tenant1")
    
    assert result is None


def test_query_version_list_success(monkeypatch, mock_session):
    """Test successfully querying version list"""
    session, query = mock_session
    mock_version1 = MockAgentVersion()
    mock_version2 = MockAgentVersion()
    mock_version2.version_no = 2
    mock_version2.version_name = "v2.0"
    
    mock_order_by = MagicMock()
    mock_order_by.all = lambda: [mock_version2, mock_version1]  # Ordered desc
    mock_filter = MagicMock()
    mock_filter.order_by.return_value = mock_order_by
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    result = query_version_list(agent_id=1, tenant_id="tenant1")
    
    assert len(result) == 2
    assert result[0]["version_no"] == 2  # Should be ordered desc
    assert result[1]["version_no"] == 1


def test_query_version_list_empty(monkeypatch, mock_session):
    """Test querying version list when no versions exist"""
    session, query = mock_session
    
    mock_order_by = MagicMock()
    mock_order_by.all = lambda: []
    mock_filter = MagicMock()
    mock_filter.order_by.return_value = mock_order_by
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    result = query_version_list(agent_id=1, tenant_id="tenant1")
    
    assert result == []


def test_query_current_version_no_found(monkeypatch, mock_session):
    """Test successfully querying current version number"""
    session, query = mock_session
    mock_agent = MockAgentInfo()
    mock_agent.current_version_no = 5
    
    mock_filter = MagicMock()
    mock_filter.first = lambda: mock_agent
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    result = query_current_version_no(agent_id=1, tenant_id="tenant1")
    
    assert result == 5


def test_query_current_version_no_not_found(monkeypatch, mock_session):
    """Test querying current version when agent draft doesn't exist"""
    session, query = mock_session
    
    mock_filter = MagicMock()
    mock_filter.first = lambda: None
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    result = query_current_version_no(agent_id=999, tenant_id="tenant1")
    
    assert result is None


def test_query_agent_snapshot_success(monkeypatch, mock_session):
    """Test successfully querying agent snapshot"""
    session, query = mock_session
    mock_agent = MockAgentInfo()
    mock_tool = MockToolInstance()
    mock_relation = MockAgentRelation()
    
    # Mock query chain for agent
    mock_agent_filter = MagicMock()
    mock_agent_filter.first = lambda: mock_agent
    
    # Mock query chain for tools
    mock_tools_filter = MagicMock()
    mock_tools_filter.all = lambda: [mock_tool]
    
    # Mock query chain for relations
    mock_relations_filter = MagicMock()
    mock_relations_filter.all = lambda: [mock_relation]
    
    # Setup session.query to return different query objects based on model
    def query_side_effect(model_class):
        mock_query = MagicMock()
        if model_class == db_models_mock.AgentInfo:
            mock_query.filter.return_value = mock_agent_filter
        elif model_class == db_models_mock.ToolInstance:
            mock_query.filter.return_value = mock_tools_filter
        elif model_class == db_models_mock.AgentRelation:
            mock_query.filter.return_value = mock_relations_filter
        else:
            mock_query.filter.return_value = MagicMock()
        return mock_query
    
    session.query.side_effect = query_side_effect
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    agent_dict, tools_list, relations_list = query_agent_snapshot(
        agent_id=1, tenant_id="tenant1", version_no=1
    )
    
    assert agent_dict is not None
    assert agent_dict["agent_id"] == 1
    assert len(tools_list) == 1
    assert tools_list[0]["tool_id"] == 1
    assert len(relations_list) == 1
    assert relations_list[0]["selected_agent_id"] == 2


def test_query_agent_snapshot_no_agent(monkeypatch, mock_session):
    """Test querying snapshot when agent doesn't exist"""
    session, query = mock_session
    
    mock_agent_filter = MagicMock()
    mock_agent_filter.first = lambda: None
    
    mock_tools_filter = MagicMock()
    mock_tools_filter.all = lambda: []
    
    mock_relations_filter = MagicMock()
    mock_relations_filter.all = lambda: []
    
    # Setup session.query to return different query objects based on model
    def query_side_effect(model_class):
        mock_query = MagicMock()
        if model_class == db_models_mock.AgentInfo:
            mock_query.filter.return_value = mock_agent_filter
        elif model_class == db_models_mock.ToolInstance:
            mock_query.filter.return_value = mock_tools_filter
        elif model_class == db_models_mock.AgentRelation:
            mock_query.filter.return_value = mock_relations_filter
        else:
            mock_query.filter.return_value = MagicMock()
        return mock_query
    
    session.query.side_effect = query_side_effect
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    agent_dict, tools_list, relations_list = query_agent_snapshot(
        agent_id=999, tenant_id="tenant1", version_no=1
    )
    
    assert agent_dict is None
    assert tools_list == []
    assert relations_list == []


def test_query_agent_draft(monkeypatch, mock_session):
    """Test querying agent draft (version_no=0)"""
    session, query = mock_session
    
    # query_agent_draft calls query_agent_snapshot with version_no=0
    mock_agent = MockAgentInfo()
    mock_agent.version_no = 0
    mock_agent.__dict__['version_no'] = 0
    
    mock_agent_filter = MagicMock()
    mock_agent_filter.first = lambda: mock_agent
    
    mock_tools_filter = MagicMock()
    mock_tools_filter.all = lambda: []
    
    mock_relations_filter = MagicMock()
    mock_relations_filter.all = lambda: []
    
    # Setup session.query to return different query objects based on model
    def query_side_effect(model_class):
        mock_query = MagicMock()
        if model_class == db_models_mock.AgentInfo:
            mock_query.filter.return_value = mock_agent_filter
        elif model_class == db_models_mock.ToolInstance:
            mock_query.filter.return_value = mock_tools_filter
        elif model_class == db_models_mock.AgentRelation:
            mock_query.filter.return_value = mock_relations_filter
        else:
            mock_query.filter.return_value = MagicMock()
        return mock_query
    
    session.query.side_effect = query_side_effect
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    agent_dict, tools_list, relations_list = query_agent_draft(agent_id=1, tenant_id="tenant1")
    
    assert agent_dict is not None
    assert agent_dict["version_no"] == 0


def test_insert_version_success(monkeypatch, mock_session):
    """Test successfully inserting a new version"""
    session, query = mock_session
    
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = 123
    session.execute.return_value = mock_result
    
    # Mock SQLAlchemy insert to avoid ArgumentError
    mock_sqlalchemy_insert(monkeypatch)
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    version_data = {
        "tenant_id": "tenant1",
        "agent_id": 1,
        "version_no": 1,
        "version_name": "v1.0",
        "status": STATUS_RELEASED,
    }
    
    result = insert_version(version_data)
    
    assert result == 123
    session.execute.assert_called_once()


def test_update_version_status_success(monkeypatch, mock_session):
    """Test successfully updating version status"""
    session, query = mock_session
    
    mock_result = MagicMock()
    mock_result.rowcount = 1
    session.execute.return_value = mock_result
    
    # Mock SQLAlchemy update to avoid ArgumentError
    mock_sqlalchemy_update(monkeypatch)
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    result = update_version_status(
        agent_id=1,
        tenant_id="tenant1",
        version_no=1,
        status=STATUS_DISABLED,
        updated_by="user1",
    )
    
    assert result == 1
    session.execute.assert_called_once()


def test_update_version_status_not_found(monkeypatch, mock_session):
    """Test updating status when version doesn't exist"""
    session, query = mock_session
    
    mock_result = MagicMock()
    mock_result.rowcount = 0
    session.execute.return_value = mock_result
    
    # Mock SQLAlchemy update to avoid ArgumentError
    mock_sqlalchemy_update(monkeypatch)
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    result = update_version_status(
        agent_id=999,
        tenant_id="tenant1",
        version_no=999,
        status=STATUS_DISABLED,
        updated_by="user1",
    )
    
    assert result == 0


def test_update_agent_current_version_success(monkeypatch, mock_session):
    """Test successfully updating agent current version"""
    session, query = mock_session
    
    mock_result = MagicMock()
    mock_result.rowcount = 1
    session.execute.return_value = mock_result
    
    # Mock SQLAlchemy update to avoid ArgumentError
    mock_sqlalchemy_update(monkeypatch)
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    result = update_agent_current_version(
        agent_id=1,
        tenant_id="tenant1",
        current_version_no=5,
    )
    
    assert result == 1
    session.execute.assert_called_once()


def test_update_agent_current_version_not_found(monkeypatch, mock_session):
    """Test updating current version when agent draft doesn't exist"""
    session, query = mock_session
    
    mock_result = MagicMock()
    mock_result.rowcount = 0
    session.execute.return_value = mock_result
    
    # Mock SQLAlchemy update to avoid ArgumentError
    mock_sqlalchemy_update(monkeypatch)
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    result = update_agent_current_version(
        agent_id=999,
        tenant_id="tenant1",
        current_version_no=5,
    )
    
    assert result == 0


def test_insert_agent_snapshot_success(monkeypatch, mock_session):
    """Test successfully inserting agent snapshot"""
    session, query = mock_session
    
    session.execute = MagicMock()
    
    # Mock SQLAlchemy insert to avoid ArgumentError
    mock_sqlalchemy_insert(monkeypatch)
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    agent_data = {
        "agent_id": 1,
        "tenant_id": "tenant1",
        "version_no": 1,
        "name": "Test Agent",
    }
    
    insert_agent_snapshot(agent_data)
    
    session.execute.assert_called_once()


def test_insert_tool_snapshot_success(monkeypatch, mock_session):
    """Test successfully inserting tool snapshot"""
    session, query = mock_session
    
    session.execute = MagicMock()
    
    # Mock SQLAlchemy insert to avoid ArgumentError
    mock_sqlalchemy_insert(monkeypatch)
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    tool_data = {
        "tool_id": 1,
        "agent_id": 1,
        "tenant_id": "tenant1",
        "version_no": 1,
    }
    
    insert_tool_snapshot(tool_data)
    
    session.execute.assert_called_once()


def test_insert_relation_snapshot_success(monkeypatch, mock_session):
    """Test successfully inserting relation snapshot"""
    session, query = mock_session
    
    session.execute = MagicMock()
    
    # Mock SQLAlchemy insert to avoid ArgumentError
    mock_sqlalchemy_insert(monkeypatch)
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    relation_data = {
        "parent_agent_id": 1,
        "selected_agent_id": 2,
        "tenant_id": "tenant1",
        "version_no": 1,
    }
    
    insert_relation_snapshot(relation_data)
    
    session.execute.assert_called_once()


def test_update_agent_snapshot_success(monkeypatch, mock_session):
    """Test successfully updating agent snapshot"""
    session, query = mock_session
    
    mock_result = MagicMock()
    mock_result.rowcount = 1
    session.execute.return_value = mock_result
    
    # Mock SQLAlchemy update to avoid ArgumentError
    mock_sqlalchemy_update(monkeypatch)
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    agent_data = {"name": "Updated Agent Name"}
    
    result = update_agent_snapshot(
        agent_id=1,
        tenant_id="tenant1",
        version_no=1,
        agent_data=agent_data,
    )
    
    assert result == 1
    session.execute.assert_called_once()


def test_update_agent_snapshot_not_found(monkeypatch, mock_session):
    """Test updating snapshot when it doesn't exist"""
    session, query = mock_session
    
    mock_result = MagicMock()
    mock_result.rowcount = 0
    session.execute.return_value = mock_result
    
    # Mock SQLAlchemy update to avoid ArgumentError
    mock_sqlalchemy_update(monkeypatch)
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    agent_data = {"name": "Updated Agent Name"}
    
    result = update_agent_snapshot(
        agent_id=999,
        tenant_id="tenant1",
        version_no=999,
        agent_data=agent_data,
    )
    
    assert result == 0


def test_delete_agent_snapshot_success(monkeypatch, mock_session):
    """Test successfully deleting agent snapshot"""
    session, query = mock_session
    
    mock_result = MagicMock()
    mock_result.rowcount = 1
    session.execute.return_value = mock_result
    
    # Mock SQLAlchemy update to avoid ArgumentError (delete uses update)
    mock_sqlalchemy_update(monkeypatch)
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    result = delete_agent_snapshot(
        agent_id=1,
        tenant_id="tenant1",
        version_no=1,
        deleted_by="user1",
    )
    
    assert result == 1
    session.execute.assert_called_once()


def test_delete_tool_snapshot_success(monkeypatch, mock_session):
    """Test successfully deleting tool snapshot"""
    session, query = mock_session
    
    mock_result = MagicMock()
    mock_result.rowcount = 2
    session.execute.return_value = mock_result
    
    # Mock SQLAlchemy update to avoid ArgumentError (delete uses update)
    mock_sqlalchemy_update(monkeypatch)
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    result = delete_tool_snapshot(
        agent_id=1,
        tenant_id="tenant1",
        version_no=1,
        deleted_by="user1",
    )
    
    assert result == 2
    session.execute.assert_called_once()


def test_delete_tool_snapshot_without_deleted_by(monkeypatch, mock_session):
    """Test deleting tool snapshot without deleted_by parameter"""
    session, query = mock_session
    
    mock_result = MagicMock()
    mock_result.rowcount = 1
    session.execute.return_value = mock_result
    
    # Mock SQLAlchemy update to avoid ArgumentError (delete uses update)
    mock_sqlalchemy_update(monkeypatch)
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    result = delete_tool_snapshot(
        agent_id=1,
        tenant_id="tenant1",
        version_no=1,
    )
    
    assert result == 1
    session.execute.assert_called_once()


def test_delete_relation_snapshot_success(monkeypatch, mock_session):
    """Test successfully deleting relation snapshot"""
    session, query = mock_session
    
    mock_result = MagicMock()
    mock_result.rowcount = 1
    session.execute.return_value = mock_result
    
    # Mock SQLAlchemy update to avoid ArgumentError (delete uses update)
    mock_sqlalchemy_update(monkeypatch)
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    result = delete_relation_snapshot(
        agent_id=1,
        tenant_id="tenant1",
        version_no=1,
        deleted_by="user1",
    )
    
    assert result == 1
    session.execute.assert_called_once()


def test_delete_relation_snapshot_without_deleted_by(monkeypatch, mock_session):
    """Test deleting relation snapshot without deleted_by parameter"""
    session, query = mock_session
    
    mock_result = MagicMock()
    mock_result.rowcount = 1
    session.execute.return_value = mock_result
    
    # Mock SQLAlchemy update to avoid ArgumentError (delete uses update)
    mock_sqlalchemy_update(monkeypatch)
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    result = delete_relation_snapshot(
        agent_id=1,
        tenant_id="tenant1",
        version_no=1,
    )
    
    assert result == 1
    session.execute.assert_called_once()


def test_get_next_version_no_first_version(monkeypatch, mock_session):
    """Test getting next version number when no versions exist"""
    session, query = mock_session
    
    mock_filter = MagicMock()
    mock_filter.scalar = lambda: None  # No max version
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    result = get_next_version_no(agent_id=1, tenant_id="tenant1")
    
    assert result == 1  # Should be 0 + 1


def test_get_next_version_no_existing_versions(monkeypatch, mock_session):
    """Test getting next version number when versions exist"""
    session, query = mock_session
    
    mock_filter = MagicMock()
    mock_filter.scalar = lambda: 5  # Max version is 5
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    result = get_next_version_no(agent_id=1, tenant_id="tenant1")
    
    assert result == 6  # Should be 5 + 1


def test_delete_version_success(monkeypatch, mock_session):
    """Test successfully deleting a version"""
    session, query = mock_session
    
    mock_result = MagicMock()
    mock_result.rowcount = 1
    session.execute.return_value = mock_result
    
    # Mock SQLAlchemy update to avoid ArgumentError (delete uses update)
    mock_sqlalchemy_update(monkeypatch)
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    result = delete_version(
        agent_id=1,
        tenant_id="tenant1",
        version_no=1,
        deleted_by="user1",
    )
    
    assert result == 1
    session.execute.assert_called_once()


def test_delete_version_not_found(monkeypatch, mock_session):
    """Test deleting a version that doesn't exist"""
    session, query = mock_session
    
    mock_result = MagicMock()
    mock_result.rowcount = 0
    session.execute.return_value = mock_result
    
    # Mock SQLAlchemy update to avoid ArgumentError (delete uses update)
    mock_sqlalchemy_update(monkeypatch)
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    # Mock the functions directly in the imported module
    # This is needed because agent_version_db imports get_db_session and as_dict at module level
    monkeypatch.setattr(agent_version_db_module, "get_db_session", lambda: mock_ctx)
    monkeypatch.setattr(agent_version_db_module, "as_dict", mock_as_dict)
    
    result = delete_version(
        agent_id=999,
        tenant_id="tenant1",
        version_no=999,
        deleted_by="user1",
    )
    
    assert result == 0
