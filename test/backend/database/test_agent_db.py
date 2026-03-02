import sys
import pytest
from unittest.mock import patch, MagicMock

# 首先模拟consts模块，避免ModuleNotFoundError
consts_mock = MagicMock()
consts_mock.const = MagicMock()
# 设置consts.const中需要的常量
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

# 将模拟的consts模块添加到sys.modules中
sys.modules['consts'] = consts_mock
sys.modules['consts.const'] = consts_mock.const

# 模拟utils模块
utils_mock = MagicMock()
utils_mock.auth_utils = MagicMock()
utils_mock.auth_utils.get_current_user_id_from_token = MagicMock(return_value="test_user_id")

# 将模拟的utils模块添加到sys.modules中
sys.modules['utils'] = utils_mock
sys.modules['utils.auth_utils'] = utils_mock.auth_utils

# Stub utils.str_utils to satisfy imports in backend.database.agent_db
str_utils_mock = MagicMock()
str_utils_mock.convert_list_to_string = MagicMock(
    side_effect=lambda items: "" if items is None else ",".join(str(i) for i in items)
)
str_utils_mock.convert_string_to_list = MagicMock(
    side_effect=lambda s: [] if not s else [int(x) for x in str(s).split(",") if str(x).strip().isdigit()]
)
sys.modules['utils.str_utils'] = str_utils_mock

# Provide a stub for the `boto3` module so that it can be imported safely even
# if the testing environment does not have it available.
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

# 模拟整个client模块
client_mock = MagicMock()
client_mock.MinioClient = MagicMock()
client_mock.PostgresClient = MagicMock()
client_mock.db_client = MagicMock()
client_mock.get_db_session = MagicMock()
client_mock.as_dict = MagicMock()
client_mock.filter_property = MagicMock()

# 将模拟的client模块添加到sys.modules中
sys.modules['database.client'] = client_mock
sys.modules['backend.database.client'] = client_mock

# 模拟db_models模块
# First, try to import real classes before mocking (if possible)
_real_agent_info = None
_real_tool_instance = None
_real_agent_relation = None
try:
    # Try to import real classes before they get mocked
    # This will only work if the module can be imported without database connection
    from backend.database.db_models import AgentInfo as _real_agent_info, ToolInstance as _real_tool_instance, AgentRelation as _real_agent_relation
except (ImportError, Exception):
    # If import fails (e.g., database not available), we'll use mocks
    pass

db_models_mock = MagicMock()
db_models_mock.AgentInfo = MagicMock()
db_models_mock.ToolInstance = MagicMock()
db_models_mock.AgentRelation = MagicMock()

# 将模拟的db_models模块添加到sys.modules中
sys.modules['database.db_models'] = db_models_mock
sys.modules['backend.database.db_models'] = db_models_mock

# 现在可以安全地导入被测试的模块
from backend.database.agent_db import (
    search_agent_info_by_agent_id,
    search_agent_id_by_agent_name,
    search_blank_sub_agent_by_main_agent_id,
    query_sub_agents_id_list,
    create_agent,
    update_agent,
    delete_agent_by_id,
    query_all_agent_info_by_tenant_id,
    insert_related_agent,
    delete_related_agent,
    delete_agent_relationship,
    update_related_agents
)

class MockAgent:
    def __init__(self):
        self.agent_id = 1
        self.name = "test_agent"
        self.display_name = "test_agent"
        self.tenant_id = "tenant1"
        self.delete_flag = "N"
        self.enabled = True
        self.updated_by = None
        self.business_logic_model_id = None
        self.business_logic_model_name = None
        self.description = None
        self.author = None
        self.model_id = None
        self.model_name = None
        self.max_steps = 5
        self.duty_prompt = None
        self.constraint_prompt = None
        self.few_shots_prompt = None
        self.parent_agent_id = None
        self.provide_run_summary = None
        self.business_description = None
        self.group_ids = None
        self.is_new = True
        self.current_version_no = None
        self.version_no = 0
        self.created_by = None

class MockAgentRelation:
    def __init__(self):
        self.selected_agent_id = 2

@pytest.fixture
def mock_session():
    """创建模拟的数据库会话"""
    mock_session = MagicMock()
    mock_query = MagicMock()
    mock_session.query.return_value = mock_query
    return mock_session, mock_query

def test_search_agent_info_by_agent_id_success(monkeypatch, mock_session):
    """测试成功搜索agent信息"""
    session, query = mock_session
    mock_agent = MockAgent()

    mock_first = MagicMock()
    mock_first.return_value = mock_agent
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.agent_db.as_dict", lambda obj: obj.__dict__)

    result = search_agent_info_by_agent_id(1, "tenant1")

    assert result["agent_id"] == 1
    assert result["name"] == "test_agent"
    assert result["tenant_id"] == "tenant1"

def test_search_agent_info_by_agent_id_not_found(monkeypatch, mock_session):
    """测试搜索不存在的agent"""
    session, query = mock_session
    mock_first = MagicMock()
    mock_first.return_value = None
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)

    with pytest.raises(ValueError, match="agent not found"):
        search_agent_info_by_agent_id(999, "tenant1")

def test_search_agent_id_by_agent_name_success(monkeypatch, mock_session):
    """测试成功通过agent名称搜索agent ID"""
    session, query = mock_session
    mock_agent = MockAgent()

    mock_first = MagicMock()
    mock_first.return_value = mock_agent
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)

    result = search_agent_id_by_agent_name("test_agent", "tenant1")

    assert result == 1

def test_search_agent_id_by_agent_name_not_found(monkeypatch, mock_session):
    """测试通过不存在的agent名称搜索"""
    session, query = mock_session
    mock_first = MagicMock()
    mock_first.return_value = None
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)

    with pytest.raises(ValueError, match="agent not found"):
        search_agent_id_by_agent_name("nonexistent_agent", "tenant1")

def test_search_blank_sub_agent_by_main_agent_id_found(monkeypatch, mock_session):
    """测试成功搜索空白子agent"""
    session, query = mock_session
    mock_agent = MockAgent()
    mock_agent.enabled = False

    mock_first = MagicMock()
    mock_first.return_value = mock_agent
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)

    result = search_blank_sub_agent_by_main_agent_id("tenant1")

    assert result == 1

def test_search_blank_sub_agent_by_main_agent_id_not_found(monkeypatch, mock_session):
    """测试搜索不到空白子agent"""
    session, query = mock_session
    mock_first = MagicMock()
    mock_first.return_value = None
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)

    result = search_blank_sub_agent_by_main_agent_id("tenant1")

    assert result is None

def test_query_sub_agents_id_list(monkeypatch, mock_session):
    """测试查询子agent ID列表"""
    session, query = mock_session
    mock_relation = MockAgentRelation()

    mock_all = MagicMock()
    mock_all.return_value = [mock_relation]
    mock_filter = MagicMock()
    mock_filter.all = mock_all
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)

    result = query_sub_agents_id_list(1, "tenant1")

    assert result == [2]

def test_create_agent_success(monkeypatch, mock_session):
    """测试成功创建agent"""
    session, query = mock_session
    session.add = MagicMock()
    session.flush = MagicMock()

    mock_agent = MockAgent()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.agent_db.filter_property", lambda data, model: data)
    monkeypatch.setattr("backend.database.agent_db.as_dict", lambda obj: obj.__dict__)
    monkeypatch.setattr("backend.database.agent_db.AgentInfo", lambda **kwargs: mock_agent)

    agent_info = {"name": "new_agent", "description": "test description"}
    result = create_agent(agent_info, "tenant1", "user1")

    assert result["agent_id"] == 1
    session.add.assert_called_once()
    session.flush.assert_called_once()

def test_update_agent_success(monkeypatch, mock_session):
    """测试成功更新agent"""
    session, query = mock_session
    mock_agent = MockAgent()

    mock_first = MagicMock()
    mock_first.return_value = mock_agent
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.agent_db.filter_property", lambda data, model: data)

    agent_info = MagicMock()
    agent_info.__dict__ = {"name": "updated_agent", "description": "updated description"}

    update_agent(1, agent_info, "user1")

    assert mock_agent.updated_by == "user1"

def test_update_agent_skips_none_and_converts_group_ids(monkeypatch, mock_session):
    """update_agent should skip None values and convert group_ids list to string."""
    session, query = mock_session
    mock_agent = MockAgent()

    mock_first = MagicMock()
    mock_first.return_value = mock_agent
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.agent_db.filter_property", lambda data, model: data)

    # Spy on the imported convert_list_to_string in backend.database.agent_db
    from backend.database import agent_db as agent_db_module
    agent_db_module.convert_list_to_string.reset_mock()

    agent_info = MagicMock()
    agent_info.__dict__ = {
        # None should be skipped by update_agent (lines 158-159)
        "name": None,
        # group_ids should be converted (lines 160-161)
        "group_ids": [1, 2],
    }

    update_agent(1, agent_info, "user1")

    # name should remain unchanged because None is skipped
    assert mock_agent.name == "test_agent"
    # group_ids should be set as a comma-separated string
    assert getattr(mock_agent, "group_ids") == "1,2"
    agent_db_module.convert_list_to_string.assert_called_once_with([1, 2])
    assert mock_agent.updated_by == "user1"

def test_update_agent_not_found(monkeypatch, mock_session):
    """测试更新不存在的agent"""
    session, query = mock_session
    mock_first = MagicMock()
    mock_first.return_value = None
    mock_filter = MagicMock()
    mock_filter.first = mock_first
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)

    agent_info = MagicMock()
    agent_info.__dict__ = {"name": "updated_agent"}

    with pytest.raises(ValueError, match="ag_tenant_agent_t Agent not found"):
        update_agent(999, agent_info, "user1")

def test_delete_agent_by_id_success(monkeypatch, mock_session):
    """测试成功删除agent"""
    session, query = mock_session
    # Mock session.execute instead of query.filter.update
    mock_execute = MagicMock()
    session.execute = mock_execute

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)

    # Restore real AgentInfo and ToolInstance classes for SQLAlchemy update
    # Use the real classes that were saved before mocking
    if _real_agent_info is not None:
        monkeypatch.setattr("backend.database.agent_db.AgentInfo", _real_agent_info)
    if _real_tool_instance is not None:
        monkeypatch.setattr("backend.database.agent_db.ToolInstance", _real_tool_instance)

    delete_agent_by_id(1, "tenant1", "user1")

    # 验证调用了两次execute（一次更新AgentInfo，一次更新ToolInstance）
    assert mock_execute.call_count == 2

def test_query_all_agent_info_by_tenant_id(monkeypatch, mock_session):
    """测试查询所有agent信息"""
    session, query = mock_session
    mock_agent = MockAgent()

    mock_all = MagicMock()
    mock_all.return_value = [mock_agent]
    mock_order_by = MagicMock()
    mock_order_by.all = mock_all
    mock_filter = MagicMock()
    mock_filter.order_by.return_value = mock_order_by
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.agent_db.as_dict", lambda obj: obj.__dict__)

    result = query_all_agent_info_by_tenant_id("tenant1")

    assert len(result) == 1
    assert result[0]["agent_id"] == 1

def test_insert_related_agent_success(monkeypatch, mock_session):
    """测试成功插入相关agent"""
    session, query = mock_session
    session.add = MagicMock()
    session.flush = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.agent_db.filter_property", lambda data, model: data)
    monkeypatch.setattr("backend.database.agent_db.AgentRelation", lambda **kwargs: MagicMock())

    result = insert_related_agent(1, 2, "tenant1", "user1")

    assert result is True
    session.add.assert_called_once()
    session.flush.assert_called_once()

def test_insert_related_agent_failure(monkeypatch, mock_session):
    """测试插入相关agent失败"""
    session, query = mock_session
    session.add = MagicMock(side_effect=Exception("Database error"))

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.agent_db.filter_property", lambda data, model: data)
    monkeypatch.setattr("backend.database.agent_db.AgentRelation", lambda **kwargs: MagicMock())

    result = insert_related_agent(1, 2, "tenant1", "user1")

    assert result is False

def test_delete_related_agent_success(monkeypatch, mock_session):
    """测试成功删除相关agent"""
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)

    result = delete_related_agent(1, 2, "tenant1", "user1")

    assert result is True
    mock_update.assert_called_once()

def test_delete_related_agent_failure(monkeypatch, mock_session):
    """测试删除相关agent失败"""
    session, query = mock_session
    mock_update = MagicMock(side_effect=Exception("Database error"))
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)

    result = delete_related_agent(1, 2, "tenant1", "user1")

    assert result is False

def test_delete_agent_relationship_success(monkeypatch, mock_session):
    """测试成功删除agent关系"""
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)

    # 函数不返回任何值，只验证执行成功
    delete_agent_relationship(1, "tenant1", "user1")

    # 验证调用了两次update（一次删除父关系，一次删除子关系）
    assert mock_update.call_count == 2

def test_delete_agent_relationship_failure(monkeypatch, mock_session):
    """测试删除agent关系失败"""
    session, query = mock_session
    mock_update = MagicMock(side_effect=Exception("Database error"))
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)

    # 函数应该抛出异常，因为数据库操作失败
    with pytest.raises(Exception, match="Database error"):
        delete_agent_relationship(1, "tenant1", "user1")


def test_update_related_agents_add_new(monkeypatch, mock_session):
    """测试更新相关agent - 添加新关系"""
    session, query = mock_session

    # Mock current relations (empty initially)
    mock_all = MagicMock()
    mock_all.return_value = []  # No existing relations

    # Mock for querying current relations
    mock_filter1 = MagicMock()
    mock_filter1.all = mock_all

    # Mock for update (soft delete) - should not be called since no deletions
    mock_update = MagicMock()
    mock_filter2 = MagicMock()
    mock_filter2.update = mock_update

    # Setup filter chain: first call returns filter1 (for query)
    # If update is called, it would return filter2, but it shouldn't be called
    query.filter.return_value = mock_filter1

    # Mock for adding new relations
    session.add = MagicMock()
    session.commit = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.agent_db.filter_property", lambda data, model: data)

    # Create a Mock class for AgentRelation that supports both class attribute access and instantiation
    # The class attributes need to support comparison operations (==, !=, .in_()) for SQLAlchemy queries
    class MockAgentRelationClass:
        parent_agent_id = MagicMock()
        tenant_id = MagicMock()
        delete_flag = MagicMock()
        selected_agent_id = MagicMock()
        version_no = MagicMock()

        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    monkeypatch.setattr("backend.database.agent_db.AgentRelation", MockAgentRelationClass)

    # Execute - add new relations [2, 3]
    update_related_agents(1, [2, 3], "tenant1", "user1")

    # Verify: should add 2 new relations, no deletions
    assert session.add.call_count == 2
    # Note: update_related_agents doesn't explicitly call commit(), it relies on context manager
    # Verify update was not called since there are no deletions
    mock_update.assert_not_called()


def test_update_related_agents_delete_existing(monkeypatch, mock_session):
    """测试更新相关agent - 删除现有关系"""
    session, query = mock_session

    # Mock existing relations
    mock_relation1 = MockAgentRelation()
    mock_relation1.selected_agent_id = 2
    mock_relation2 = MockAgentRelation()
    mock_relation2.selected_agent_id = 3

    mock_all = MagicMock()
    mock_all.return_value = [mock_relation1, mock_relation2]

    # Mock for querying current relations
    mock_filter1 = MagicMock()
    mock_filter1.all = mock_all

    # Mock for update (soft delete)
    mock_update = MagicMock()
    mock_filter2 = MagicMock()
    mock_filter2.update = mock_update

    # Setup filter chain: first call returns filter1 (for query), subsequent calls return filter2 (for update)
    query.filter.side_effect = [mock_filter1, mock_filter2]

    session.add = MagicMock()
    session.commit = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)

    # Execute - remove all relations (empty list)
    update_related_agents(1, [], "tenant1", "user1")

    # Verify: should soft delete 2 relations, add none
    mock_update.assert_called_once()
    session.add.assert_not_called()
    # Note: update_related_agents doesn't explicitly call commit(), it relies on context manager


def test_update_related_agents_replace_mixed(monkeypatch, mock_session):
    """测试更新相关agent - 混合添加和删除"""
    session, query = mock_session

    # Mock existing relations [2, 3]
    mock_relation1 = MockAgentRelation()
    mock_relation1.selected_agent_id = 2
    mock_relation2 = MockAgentRelation()
    mock_relation2.selected_agent_id = 3

    mock_all = MagicMock()
    mock_all.return_value = [mock_relation1, mock_relation2]

    # Mock for querying current relations
    mock_filter1 = MagicMock()
    mock_filter1.all = mock_all

    # Mock for update (soft delete) - will be called to delete 2
    mock_update = MagicMock()
    mock_filter2 = MagicMock()
    mock_filter2.update = mock_update

    # Setup filter chain: first call returns filter1 (for query), subsequent calls return filter2 (for update)
    query.filter.side_effect = [mock_filter1, mock_filter2]

    session.add = MagicMock()
    session.commit = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.agent_db.filter_property", lambda data, model: data)

    # Create a Mock class for AgentRelation that supports both class attribute access and instantiation
    # The class attributes need to support comparison operations (==, !=, .in_()) for SQLAlchemy queries
    class MockAgentRelationClass:
        parent_agent_id = MagicMock()
        tenant_id = MagicMock()
        delete_flag = MagicMock()
        selected_agent_id = MagicMock()
        version_no = MagicMock()

        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    monkeypatch.setattr("backend.database.agent_db.AgentRelation", MockAgentRelationClass)

    # Execute - replace [2, 3] with [3, 4] (delete 2, add 4)
    update_related_agents(1, [3, 4], "tenant1", "user1")

    # Verify: should delete 2 (relation with selected_agent_id=2), add 4
    mock_update.assert_called_once()
    assert session.add.call_count == 1
    # Note: update_related_agents doesn't explicitly call commit(), it relies on context manager


def test_update_related_agents_no_changes(monkeypatch, mock_session):
    """测试更新相关agent - 无变化"""
    session, query = mock_session

    # Mock existing relations [2, 3]
    mock_relation1 = MockAgentRelation()
    mock_relation1.selected_agent_id = 2
    mock_relation2 = MockAgentRelation()
    mock_relation2.selected_agent_id = 3

    mock_all = MagicMock()
    mock_all.return_value = [mock_relation1, mock_relation2]

    # Mock for querying current relations
    mock_filter1 = MagicMock()
    mock_filter1.all = mock_all
    query.filter.return_value = mock_filter1

    session.add = MagicMock()
    session.commit = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)

    # Execute - same relations [2, 3]
    update_related_agents(1, [2, 3], "tenant1", "user1")

    # Verify: no deletions, no additions
    session.add.assert_not_called()
    # Note: update_related_agents doesn't explicitly call commit(), it relies on context manager


def test_clear_agent_new_mark_success(monkeypatch):
    """Test successful clearing of agent NEW mark"""
    from backend.database.agent_db import clear_agent_new_mark

    # Mock the entire update operation
    mock_update_result = MagicMock()
    mock_update_result.rowcount = 1

    mock_update = MagicMock(return_value=mock_update_result)
    monkeypatch.setattr("backend.database.agent_db.update", mock_update)

    # Mock session
    mock_session = MagicMock()
    mock_session.execute.return_value = mock_update_result

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = mock_session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)

    # Execute
    result = clear_agent_new_mark(1, "tenant1", "user1")

    # Verify
    assert result == 1
    mock_session.execute.assert_called_once()


def test_clear_agent_new_mark_no_rows_affected(monkeypatch):
    """Test clearing agent NEW mark when no rows are affected"""
    from backend.database.agent_db import clear_agent_new_mark

    # Mock the entire update operation
    mock_update_result = MagicMock()
    mock_update_result.rowcount = 0

    mock_update = MagicMock(return_value=mock_update_result)
    monkeypatch.setattr("backend.database.agent_db.update", mock_update)

    # Mock session
    mock_session = MagicMock()
    mock_session.execute.return_value = mock_update_result

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = mock_session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)

    # Execute
    result = clear_agent_new_mark(999, "tenant1", "user1")

    # Verify
    assert result == 0
    mock_session.execute.assert_called_once()


def test_mark_agents_as_new_success(monkeypatch):
    """Test successful marking agents as new"""
    from backend.database.agent_db import mark_agents_as_new

    # Mock the update function
    mock_update = MagicMock()
    monkeypatch.setattr("backend.database.agent_db.update", mock_update)

    # Mock session
    mock_session = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = mock_session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)

    # Execute
    mark_agents_as_new([1, 2, 3], "tenant1", "user1")

    # Verify
    mock_session.execute.assert_called_once()


def test_mark_agents_as_new_empty_list(monkeypatch):
    """Test marking agents as new with empty list"""
    from backend.database.agent_db import mark_agents_as_new

    # Mock session
    mock_session = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = mock_session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)

    # Execute with empty list
    mark_agents_as_new([], "tenant1", "user1")

    # Verify - should not execute any database operations
    mock_session.execute.assert_not_called()


def test_clear_agent_new_mark_sqlalchemy_error(monkeypatch):
    """Test clear_agent_new_mark with SQLAlchemy error"""
    from backend.database.agent_db import clear_agent_new_mark
    from sqlalchemy.exc import SQLAlchemyError

    # Mock the update function
    mock_update = MagicMock()
    monkeypatch.setattr("backend.database.agent_db.update", mock_update)

    # Mock session to raise SQLAlchemy error
    mock_session = MagicMock()
    mock_session.execute.side_effect = SQLAlchemyError("Database error")

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = mock_session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)

    # Execute and expect exception
    with pytest.raises(SQLAlchemyError):
        clear_agent_new_mark(1, "tenant1", "user1")


def test_mark_agents_as_new_sqlalchemy_error(monkeypatch):
    """Test mark_agents_as_new with SQLAlchemy error"""
    from backend.database.agent_db import mark_agents_as_new
    from sqlalchemy.exc import SQLAlchemyError

    # Mock the update function
    mock_update = MagicMock()
    monkeypatch.setattr("backend.database.agent_db.update", mock_update)

    # Mock session to raise SQLAlchemy error
    mock_session = MagicMock()
    mock_session.execute.side_effect = SQLAlchemyError("Database error")

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = mock_session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)

    # Execute and expect exception
    with pytest.raises(SQLAlchemyError):
        mark_agents_as_new([1, 2, 3], "tenant1", "user1")


def test_clear_agent_new_mark_database_connection_error(monkeypatch):
    """Test clear_agent_new_mark with database connection error"""
    from backend.database.agent_db import clear_agent_new_mark

    # Mock get_db_session to raise an exception
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: (_ for _ in ()).throw(Exception("Connection failed")))

    # Execute and expect exception
    with pytest.raises(Exception):
        clear_agent_new_mark(1, "tenant1", "user1")
