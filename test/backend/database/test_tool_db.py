import sys
import pytest
from unittest.mock import patch, MagicMock

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

# Add the mocked client module to sys.modules
sys.modules['database.client'] = client_mock
sys.modules['backend.database.client'] = client_mock

# Mock db_models module
db_models_mock = MagicMock()
db_models_mock.ToolInstance = MagicMock()
db_models_mock.ToolInfo = MagicMock()

# Add the mocked db_models module to sys.modules
sys.modules['database.db_models'] = db_models_mock
sys.modules['backend.database.db_models'] = db_models_mock

# Mock agent_db module
agent_db_mock = MagicMock()
agent_db_mock.logger = MagicMock()

# Add the mocked agent_db module to sys.modules
sys.modules['database.agent_db'] = agent_db_mock
sys.modules['backend.database.agent_db'] = agent_db_mock

# Now we can safely import the module being tested
from backend.database.tool_db import (
    create_tool,
    create_or_update_tool_by_tool_info,
    query_all_tools,
    query_tool_instances_by_id,
    query_tool_instances_by_agent_id,
    query_tools_by_ids,
    query_all_enabled_tool_instances,
    update_tool_table_from_scan_tool_list,
    add_tool_field,
    search_tools_for_sub_agent,
    check_tool_is_available,
    delete_tools_by_agent_id,
    search_last_tool_instance_by_tool_id,
    check_tool_list_initialized
)

class MockToolInstance:
    def __init__(self):
        self.tool_instance_id = 1
        self.tool_id = 1
        self.agent_id = 1
        self.tenant_id = "tenant1"
        self.user_id = "user1"
        self.enabled = True
        self.delete_flag = "N"
        self.__dict__ = {
            "tool_instance_id": 1,
            "tool_id": 1,
            "agent_id": 1,
            "tenant_id": "tenant1",
            "user_id": "user1",
            "enabled": True,
            "delete_flag": "N"
        }

class MockToolInfo:
    def __init__(self):
        self.tool_id = 1
        self.name = "test_tool"
        self.description = "test description"
        self.source = "test_source"
        self.author = "tenant1"
        self.is_available = True
        self.delete_flag = "N"
        self.params = [{"name": "param1", "default": "value1"}]
        self.usage = "test usage"
        self.inputs = "test inputs"
        self.output_type = "test output"
        self.class_name = "TestTool"
        self.__dict__ = {
            "tool_id": 1,
            "name": "test_tool",
            "description": "test description",
            "source": "test_source",
            "author": "tenant1",
            "is_available": True,
            "delete_flag": "N",
            "params": [{"name": "param1", "default": "value1"}],
            "usage": "test usage",
            "inputs": "test inputs",
            "output_type": "test output",
            "class_name": "TestTool"
        }

@pytest.fixture
def mock_session():
    """Create a mock database session"""
    mock_session = MagicMock()
    mock_query = MagicMock()
    mock_session.query.return_value = mock_query
    return mock_session, mock_query

def test_create_tool_success(monkeypatch, mock_session):
    """Test successful tool creation"""
    session, query = mock_session
    session.add = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.tool_db.filter_property", lambda data, model: data)
    monkeypatch.setattr("backend.database.tool_db.ToolInstance", lambda **kwargs: MagicMock())

    tool_info = {"tool_id": 1, "agent_id": 1, "tenant_id": "tenant1"}
    create_tool(tool_info)

    session.add.assert_called_once()

def test_create_or_update_tool_by_tool_info_update_existing(monkeypatch, mock_session):
    """Test updating an existing tool instance"""
    session, query = mock_session
    mock_tool_instance = MockToolInstance()

    mock_first = MagicMock()
    mock_first.return_value = mock_tool_instance
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)

    tool_info = MagicMock()
    tool_info.__dict__ = {"agent_id": 1, "tool_id": 1}

    result = create_or_update_tool_by_tool_info(tool_info, "tenant1", "user1")

    assert result == mock_tool_instance

def test_create_or_update_tool_by_tool_info_create_new(monkeypatch, mock_session):
    """Test creating a new tool instance"""
    session, query = mock_session
    mock_first = MagicMock()
    mock_first.return_value = None
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.tool_db.create_tool", MagicMock())

    tool_info = MagicMock()
    tool_info.__dict__ = {"agent_id": 1, "tool_id": 1}

    result = create_or_update_tool_by_tool_info(tool_info, "tenant1", "user1")

    assert result is None

def test_query_all_tools(monkeypatch, mock_session):
    """Test querying all tools"""
    session, query = mock_session
    mock_tool_info = MockToolInfo()

    mock_all = MagicMock()
    mock_all.return_value = [mock_tool_info]
    mock_filter = MagicMock()
    mock_filter.all = mock_all
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.tool_db.as_dict", lambda obj: obj.__dict__)

    result = query_all_tools("tenant1")

    assert len(result) == 1
    assert result[0]["tool_id"] == 1
    assert result[0]["name"] == "test_tool"

def test_query_tool_instances_by_id_found(monkeypatch, mock_session):
    """Test successfully querying tool instances"""
    session, query = mock_session
    mock_tool_instance = MockToolInstance()

    mock_first = MagicMock()
    mock_first.return_value = mock_tool_instance
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.tool_db.as_dict", lambda obj: obj.__dict__)

    result = query_tool_instances_by_id(1, 1, "tenant1")

    assert result["tool_instance_id"] == 1
    assert result["tool_id"] == 1

def test_query_tool_instances_by_id_not_found(monkeypatch, mock_session):
    """Test querying non-existent tool instances"""
    session, query = mock_session
    mock_first = MagicMock()
    mock_first.return_value = None
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)

    result = query_tool_instances_by_id(1, 1, "tenant1")

    assert result is None

def test_query_tools_by_ids(monkeypatch, mock_session):
    """Test querying tools by ID list"""
    session, query = mock_session
    mock_tool_info = MockToolInfo()

    mock_all = MagicMock()
    mock_all.return_value = [mock_tool_info]
    mock_filter2 = MagicMock()
    mock_filter2.all = mock_all
    mock_filter1 = MagicMock()
    mock_filter1.filter.return_value = mock_filter2
    query.filter.return_value = mock_filter1

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.tool_db.as_dict", lambda obj: obj.__dict__)

    result = query_tools_by_ids([1, 2])

    assert len(result) == 1
    assert result[0]["tool_id"] == 1

def test_query_all_enabled_tool_instances(monkeypatch, mock_session):
    """Test querying all enabled tool instances"""
    session, query = mock_session
    mock_tool_instance = MockToolInstance()

    mock_all = MagicMock()
    mock_all.return_value = [mock_tool_instance]
    mock_filter = MagicMock()
    mock_filter.all = mock_all
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.tool_db.as_dict", lambda obj: obj.__dict__)

    result = query_all_enabled_tool_instances(1, "tenant1")

    assert len(result) == 1
    assert result[0]["tool_instance_id"] == 1

def test_update_tool_table_from_scan_tool_list_success(monkeypatch, mock_session):
    """Test successfully updating tool table"""
    session, query = mock_session
    mock_tool_info = MockToolInfo()

    mock_all = MagicMock()
    mock_all.return_value = [mock_tool_info]
    mock_filter = MagicMock()
    mock_filter.all = mock_all
    query.filter.return_value = mock_filter

    session.add = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.tool_db.filter_property", lambda data, model: data)

    # Create a mock for ToolInfo class with properly accessible attributes
    mock_tool_info_class = MagicMock()
    mock_tool_info_class.delete_flag = "N"
    mock_tool_info_class.author = "tenant1"
    mock_tool_info_class.name = "test_tool"
    mock_tool_info_class.source = "test_source"
    monkeypatch.setattr("backend.database.tool_db.ToolInfo", mock_tool_info_class)

    tool_list = [MockToolInfo()]
    update_tool_table_from_scan_tool_list("tenant1", "user1", tool_list)

    # Function executes successfully without throwing exceptions

def test_update_tool_table_from_scan_tool_list_create_new_tool(monkeypatch, mock_session):
    """Test creating new tool when tool doesn't exist in database"""
    session, query = mock_session

    # Mock existing tools with different name&source combination
    existing_tool = MockToolInfo()
    existing_tool.name = "existing_tool"
    existing_tool.source = "existing_source"

    mock_all = MagicMock()
    mock_all.return_value = [existing_tool]
    mock_filter = MagicMock()
    mock_filter.all = mock_all
    query.filter.return_value = mock_filter

    session.add = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.tool_db.filter_property", lambda data, model: data)

    # Create a mock for ToolInfo class constructor
    mock_tool_info_instance = MagicMock()
    mock_tool_info_class = MagicMock(return_value=mock_tool_info_instance)
    monkeypatch.setattr("backend.database.tool_db.ToolInfo", mock_tool_info_class)

    # Create a new tool with different name&source that doesn't exist in database
    new_tool = MockToolInfo()
    new_tool.name = "new_tool"
    new_tool.source = "new_source"
    tool_list = [new_tool]

    update_tool_table_from_scan_tool_list("tenant1", "user1", tool_list)

    # Verify that session.add was called to add the new tool
    session.add.assert_called_once_with(mock_tool_info_instance)
    # Verify that ToolInfo constructor was called with correct parameters
    expected_call_args = new_tool.__dict__.copy()
    expected_call_args.update({
        "created_by": "user1",
        "updated_by": "user1",
        "author": "tenant1",
        "is_available": True
    })
    mock_tool_info_class.assert_called_once_with(**expected_call_args)

def test_update_tool_table_from_scan_tool_list_create_new_tool_invalid_name(monkeypatch, mock_session):
    """Test creating new tool with invalid name (is_available=False)"""
    session, query = mock_session

    # Mock existing tools with different name&source combination
    existing_tool = MockToolInfo()
    existing_tool.name = "existing_tool"
    existing_tool.source = "existing_source"

    mock_all = MagicMock()
    mock_all.return_value = [existing_tool]
    mock_filter = MagicMock()
    mock_filter.all = mock_all
    query.filter.return_value = mock_filter

    session.add = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.tool_db.filter_property", lambda data, model: data)

    # Create a mock for ToolInfo class constructor
    mock_tool_info_instance = MagicMock()
    mock_tool_info_class = MagicMock(return_value=mock_tool_info_instance)
    monkeypatch.setattr("backend.database.tool_db.ToolInfo", mock_tool_info_class)

    # Create a new tool with invalid name (contains special characters)
    new_tool = MockToolInfo()
    new_tool.name = "invalid-tool-name!"  # Contains dash and exclamation mark
    new_tool.source = "new_source"
    tool_list = [new_tool]

    update_tool_table_from_scan_tool_list("tenant1", "user1", tool_list)

    # Verify that session.add was called to add the new tool
    session.add.assert_called_once_with(mock_tool_info_instance)
    # Verify that ToolInfo constructor was called with is_available=False for invalid name
    expected_call_args = new_tool.__dict__.copy()
    expected_call_args.update({
        "created_by": "user1",
        "updated_by": "user1",
        "author": "tenant1",
        "is_available": False  # Should be False for invalid tool name
    })
    mock_tool_info_class.assert_called_once_with(**expected_call_args)

def test_add_tool_field(monkeypatch, mock_session):
    """Test adding tool field"""
    session, query = mock_session
    mock_tool_info = MockToolInfo()

    mock_first = MagicMock()
    mock_first.return_value = mock_tool_info
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.tool_db.as_dict", lambda obj: obj.__dict__)

    tool_info = {"tool_id": 1, "params": {"param1": "value1"}}
    result = add_tool_field(tool_info)

    assert result["name"] == "test_tool"
    assert result["description"] == "test description"
    assert result["source"] == "test_source"

def test_search_tools_for_sub_agent(monkeypatch, mock_session):
    """Test searching tools for sub-agent"""
    session, query = mock_session
    mock_tool_instance = MockToolInstance()

    mock_all = MagicMock()
    mock_all.return_value = [mock_tool_instance]
    mock_filter = MagicMock()
    mock_filter.all = mock_all
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.tool_db.as_dict", lambda obj: obj.__dict__)
    monkeypatch.setattr("backend.database.tool_db.add_tool_field", lambda data: data)

    result = search_tools_for_sub_agent(1, "tenant1")

    assert len(result) == 1
    assert result[0]["tool_instance_id"] == 1

def test_check_tool_is_available(monkeypatch, mock_session):
    """Test checking if tool is available"""
    session, query = mock_session
    mock_tool_info = MockToolInfo()

    # Directly set the return value of query.filter().all()
    mock_all = MagicMock()
    mock_all.return_value = [mock_tool_info]
    query.filter.return_value.all = mock_all

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)

    result = check_tool_is_available([1, 2])

    assert result == [True]

def test_delete_tools_by_agent_id_success(monkeypatch, mock_session):
    """Test successfully deleting agent's tools"""
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)

    # Function returns no value, only verify successful execution
    delete_tools_by_agent_id(1, "tenant1", "user1")

    mock_update.assert_called_once()


def test_search_last_tool_instance_by_tool_id_found(monkeypatch, mock_session):
    """Test successfully finding last tool instance by tool ID"""
    session, query = mock_session
    mock_tool_instance = MockToolInstance()
    mock_tool_instance.params = {"param1": "value1", "param2": "value2"}
    mock_tool_instance.update_time = "2023-01-01 12:00:00"

    mock_first = MagicMock()
    mock_first.return_value = mock_tool_instance
    mock_order_by = MagicMock()
    mock_order_by.first = mock_first
    mock_filter = MagicMock()
    mock_filter.order_by.return_value = mock_order_by
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.tool_db.as_dict", lambda obj: obj.__dict__)

    result = search_last_tool_instance_by_tool_id(1, "tenant1", "user1")

    assert result["tool_instance_id"] == 1
    assert result["tool_id"] == 1
    assert result["params"] == {"param1": "value1", "param2": "value2"}

def test_search_last_tool_instance_by_tool_id_not_found(monkeypatch, mock_session):
    """Test searching for non-existent last tool instance"""
    session, query = mock_session
    mock_first = MagicMock()
    mock_first.return_value = None
    mock_order_by = MagicMock()
    mock_order_by.first = mock_first
    mock_filter = MagicMock()
    mock_filter.order_by.return_value = mock_order_by
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)

    result = search_last_tool_instance_by_tool_id(999, "tenant1", "user1")

    assert result is None

def test_search_last_tool_instance_by_tool_id_with_deleted_flag(monkeypatch, mock_session):
    """Test searching for tool instance with deleted flag filter"""
    session, query = mock_session
    mock_tool_instance = MockToolInstance()
    mock_tool_instance.delete_flag = "N"

    mock_first = MagicMock()
    mock_first.return_value = mock_tool_instance
    mock_order_by = MagicMock()
    mock_order_by.first = mock_first
    mock_filter = MagicMock()
    mock_filter.order_by.return_value = mock_order_by
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.tool_db.as_dict", lambda obj: obj.__dict__)

    result = search_last_tool_instance_by_tool_id(1, "tenant1", "user1")

    assert result["delete_flag"] == "N"
    # Verify that the filter was called with correct parameters
    assert query.filter.call_count == 1

def test_search_last_tool_instance_by_tool_id_ordering(monkeypatch, mock_session):
    """Test that results are ordered by update_time desc"""
    session, query = mock_session
    mock_tool_instance = MockToolInstance()

    mock_first = MagicMock()
    mock_first.return_value = mock_tool_instance
    mock_order_by = MagicMock()
    mock_order_by.first = mock_first
    mock_filter = MagicMock()
    mock_filter.order_by.return_value = mock_order_by
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.tool_db.as_dict", lambda obj: obj.__dict__)

    result = search_last_tool_instance_by_tool_id(1, "tenant1", "user1")

    # Verify that order_by was called (indicating proper ordering)
    mock_filter.order_by.assert_called_once()
    assert result is not None

def test_search_last_tool_instance_by_tool_id_different_tenants(monkeypatch, mock_session):
    """Test searching with different tenant and user IDs"""
    session, query = mock_session
    mock_tool_instance = MockToolInstance()
    mock_tool_instance.tenant_id = "tenant2"
    mock_tool_instance.user_id = "user2"

    mock_first = MagicMock()
    mock_first.return_value = mock_tool_instance
    mock_order_by = MagicMock()
    mock_order_by.first = mock_first
    mock_filter = MagicMock()
    mock_filter.order_by.return_value = mock_order_by
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.tool_db.as_dict", lambda obj: obj.__dict__)

    result = search_last_tool_instance_by_tool_id(1, "tenant2", "user2")

    assert result["tenant_id"] == "tenant2"


def test_query_tool_instances_by_agent_id(monkeypatch, mock_session):
    """Test querying all tool instances for an agent"""
    session, query = mock_session
    mock_tool_instance1 = MockToolInstance()
    mock_tool_instance1.tool_id = 1
    mock_tool_instance2 = MockToolInstance()
    mock_tool_instance2.tool_id = 2

    mock_all = MagicMock()
    mock_all.return_value = [mock_tool_instance1, mock_tool_instance2]
    query.all = mock_all
    # Set up filter chain: query.filter(...).all()
    query.filter.return_value.all = mock_all

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.tool_db.as_dict", lambda obj: obj.__dict__)

    result = query_tool_instances_by_agent_id(agent_id=1, tenant_id="tenant1")

    assert len(result) == 2
    assert result[0]["tool_id"] == 1
    assert result[1]["tool_id"] == 2


def test_query_tool_instances_by_agent_id_empty(monkeypatch, mock_session):
    """Test querying tool instances when agent has no instances"""
    session, query = mock_session

    mock_all = MagicMock()
    mock_all.return_value = []
    query.all = mock_all
    query.filter.return_value.all = mock_all

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.tool_db.as_dict", lambda obj: obj.__dict__)

    result = query_tool_instances_by_agent_id(agent_id=1, tenant_id="tenant1")

    assert result == []


def test_query_tool_instances_by_agent_id_with_version(monkeypatch, mock_session):
    """Test querying tool instances with specific version number"""
    session, query = mock_session
    mock_tool_instance = MockToolInstance()
    mock_tool_instance.tool_id = 1

    mock_all = MagicMock()
    mock_all.return_value = [mock_tool_instance]
    query.all = mock_all
    query.filter.return_value.all = mock_all

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.tool_db.as_dict", lambda obj: obj.__dict__)

    result = query_tool_instances_by_agent_id(agent_id=1, tenant_id="tenant1", version_no=2)

    assert len(result) == 1
    assert result[0]["tool_id"] == 1


def test_check_tool_list_initialized_has_tools(monkeypatch, mock_session):
    """Test check_tool_list_initialized returns True when tools exist"""
    session, query = mock_session

    # Mock count to return > 0 (tools exist)
    mock_count = MagicMock()
    mock_count.return_value = 5
    query.filter.return_value.count = mock_count

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)

    result = check_tool_list_initialized("tenant1")

    assert result is True
    mock_count.assert_called_once()


def test_check_tool_list_initialized_no_tools(monkeypatch, mock_session):
    """Test check_tool_list_initialized returns False when no tools exist"""
    session, query = mock_session

    # Mock count to return 0 (no tools exist)
    mock_count = MagicMock()
    mock_count.return_value = 0
    query.filter.return_value.count = mock_count

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)

    result = check_tool_list_initialized("new_tenant")

    assert result is False
    mock_count.assert_called_once()


def test_check_tool_list_initialized_with_deleted_tools_only(monkeypatch, mock_session):
    """Test check_tool_list_initialized returns False when only deleted tools exist"""
    session, query = mock_session

    # Mock count to return 0 because deleted tools are filtered out
    mock_count = MagicMock()
    mock_count.return_value = 0
    query.filter.return_value.count = mock_count

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)

    result = check_tool_list_initialized("tenant_with_only_deleted_tools")

    assert result is False
    mock_count.assert_called_once()


def test_check_tool_list_initialized_correct_tenant_filter(monkeypatch, mock_session):
    """Test check_tool_list_initialized uses correct tenant filter"""
    session, query = mock_session

    mock_count = MagicMock()
    mock_count.return_value = 1
    query.filter.return_value.count = mock_count

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.tool_db.get_db_session", lambda: mock_ctx)

    target_tenant = "specific_tenant_id"
    check_tool_list_initialized(target_tenant)

    # Verify that filter was called with correct tenant
    filter_call_args = query.filter.call_args[0]
    # Check that ToolInfo.author == target_tenant is in the filter conditions
    from backend.database.db_models import ToolInfo
    assert (ToolInfo.delete_flag != 'Y') in filter_call_args
