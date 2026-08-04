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

# Mock database.agent_version_db before agent_db imports it
agent_version_db_mock = MagicMock()
agent_version_db_mock.query_current_version_no = MagicMock(return_value=3)
sys.modules['database.agent_version_db'] = agent_version_db_mock
sys.modules['backend.database.agent_version_db'] = agent_version_db_mock

# 将模拟的db_models模块添加到sys.modules中
sys.modules['database.db_models'] = db_models_mock
sys.modules['backend.database.db_models'] = db_models_mock

# 现在可以安全地导入被测试的模块
from backend.database.agent_db import (
    search_agent_info_by_agent_id,
    search_agent_id_by_agent_name,
    search_blank_sub_agent_by_main_agent_id,
    query_sub_agents_id_list,
    query_sub_agent_relations,
    resolve_sub_agent_version_no,
    create_agent,
    update_agent,
    delete_agent_by_id,
    query_all_agent_info_by_tenant_id,
    insert_related_agent,
    delete_related_agent,
    delete_agent_relationship,
    update_related_agents,
    batch_search_agent_display_names,
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
        self.model_ids = None
        self.max_steps = 5
        self.duty_prompt = None
        self.constraint_prompt = None
        self.few_shots_prompt = None
        self.parent_agent_id = None
        self.provide_run_summary = None
        self.is_main_agent = True
        self.business_description = None
        self.prompt_template_id = None
        self.prompt_template_name = None
        self.group_ids = None
        self.is_new = True
        self.requested_output_tokens = None
        self.enable_context_manager = True
        self.verification_config = None
        self.greeting_message = None
        self.example_questions = None
        self.current_version_no = None
        self.version_no = 0
        self.created_by = None

class MockAgentRelation:
    def __init__(self, selected_agent_version_no=None):
        self.selected_agent_id = 2
        self.selected_agent_version_no = selected_agent_version_no

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


def test_query_sub_agent_relations(monkeypatch, mock_session):
    """Test querying sub-agent relations including pinned version"""
    session, query = mock_session
    mock_relation = MockAgentRelation(selected_agent_version_no=2)

    mock_all = MagicMock()
    mock_all.return_value = [mock_relation]
    mock_filter = MagicMock()
    mock_filter.all = mock_all
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.agent_db.as_dict", lambda obj: obj.__dict__)

    result = query_sub_agent_relations(1, "tenant1", version_no=1)

    assert len(result) == 1
    assert result[0]["selected_agent_id"] == 2
    assert result[0]["selected_agent_version_no"] == 2


def test_resolve_sub_agent_version_no_pinned(monkeypatch):
    """Test resolve uses pinned version when set"""
    result = resolve_sub_agent_version_no(
        selected_agent_id=2,
        selected_agent_version_no=5,
        tenant_id="tenant1",
    )
    assert result == 5


def test_resolve_sub_agent_version_no_fallback(monkeypatch):
    """Test resolve falls back to child current_version_no when pin is NULL"""
    monkeypatch.setattr(
        "backend.database.agent_db.query_current_version_no",
        MagicMock(return_value=3),
    )
    result = resolve_sub_agent_version_no(
        selected_agent_id=2,
        selected_agent_version_no=None,
        tenant_id="tenant1",
    )
    assert result == 3


def test_resolve_sub_agent_version_no_fallback_to_draft(monkeypatch):
    """Test resolve falls back to draft when child has no published version"""
    monkeypatch.setattr(
        "backend.database.agent_db.query_current_version_no",
        MagicMock(return_value=None),
    )
    result = resolve_sub_agent_version_no(
        selected_agent_id=2,
        selected_agent_version_no=None,
        tenant_id="tenant1",
    )
    assert result == 0


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

def test_update_agent_allows_explicit_requested_output_tokens_null(monkeypatch, mock_session):
    """Explicit requested_output_tokens=None should clear the W2 agent override."""
    session, query = mock_session
    mock_agent = MockAgent()
    mock_agent.requested_output_tokens = 2048

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

    class AgentInfoUpdate:
        def __init__(self):
            self.requested_output_tokens = None
            self.model_fields_set = {"requested_output_tokens"}

    agent_info = AgentInfoUpdate()

    update_agent(1, agent_info, "user1")

    assert mock_agent.requested_output_tokens is None
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
    update_related_agents(1, "tenant1", "user1", related_agents=[{"agent_id": 2}, {"agent_id": 3}])

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
    update_related_agents(1, "tenant1", "user1", related_agents=[])

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
    update_related_agents(1, "tenant1", "user1", related_agents=[{"agent_id": 3}, {"agent_id": 4}])

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
    update_related_agents(1, "tenant1", "user1", related_agents=[{"agent_id": 2}, {"agent_id": 3}])

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


# ===================== batch_search_agent_display_names tests =====================


def test_batch_search_agent_display_names_empty_list(monkeypatch):
    """Test batch_search_agent_display_names with empty agent_ids returns empty dict."""
    result = batch_search_agent_display_names(agent_ids=[], tenant_id="tenant1")
    assert result == {}


def test_batch_search_agent_display_names_success(monkeypatch, mock_session):
    """Test batch_search_agent_display_names returns mapping of agent_id -> display_name."""
    session, query = mock_session

    mock_agent1 = MagicMock()
    mock_agent1.agent_id = 1
    mock_agent1.display_name = "Agent One"
    mock_agent1.name = "agent_one"

    mock_agent2 = MagicMock()
    mock_agent2.agent_id = 2
    mock_agent2.display_name = None
    mock_agent2.name = "agent_two"

    mock_all = MagicMock()
    mock_all.return_value = [mock_agent1, mock_agent2]
    mock_filter = MagicMock()
    mock_filter.all = mock_all
    query.filter.return_value = mock_filter

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)

    result = batch_search_agent_display_names(agent_ids=[1, 2], tenant_id="tenant1")

    assert result == {1: "Agent One", 2: "agent_two"}


# ===================== insert_related_agent with selected_agent_version_no tests =====================


def test_insert_related_agent_with_selected_agent_version_no(monkeypatch, mock_session):
    """Test insert_related_agent passes selected_agent_version_no to the relation."""
    session, query = mock_session
    session.add = MagicMock()
    session.flush = MagicMock()

    captured_kwargs = {}
    def mock_agent_relation_init(**kwargs):
        captured_kwargs.update(kwargs)
        return MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.agent_db.filter_property", lambda data, model: data)
    monkeypatch.setattr("backend.database.agent_db.AgentRelation", mock_agent_relation_init)

    result = insert_related_agent(1, 2, "tenant1", "user1", selected_agent_version_no=5)

    assert result is True
    assert captured_kwargs["selected_agent_version_no"] == 5
    session.add.assert_called_once()


def test_insert_related_agent_without_selected_agent_version_no(monkeypatch, mock_session):
    """Test insert_related_agent defaults selected_agent_version_no to None."""
    session, query = mock_session
    session.add = MagicMock()
    session.flush = MagicMock()

    captured_kwargs = {}
    def mock_agent_relation_init(**kwargs):
        captured_kwargs.update(kwargs)
        return MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.agent_db.filter_property", lambda data, model: data)
    monkeypatch.setattr("backend.database.agent_db.AgentRelation", mock_agent_relation_init)

    result = insert_related_agent(1, 2, "tenant1", "user1")

    assert result is True
    assert captured_kwargs["selected_agent_version_no"] is None


# ===================== update_related_agents version update tests =====================


def test_update_related_agents_updates_version_no(monkeypatch, mock_session):
    """Test update_related_agents updates selected_agent_version_no for existing relations."""
    session, query = mock_session

    # Mock existing relation with old version
    mock_relation = MockAgentRelation()
    mock_relation.selected_agent_id = 2
    mock_relation.selected_agent_version_no = 1
    mock_relation.relation_id = 10

    mock_all = MagicMock()
    mock_all.return_value = [mock_relation]
    mock_filter1 = MagicMock()
    mock_filter1.all = mock_all
    query.filter.return_value = mock_filter1

    session.add = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)
    monkeypatch.setattr("backend.database.agent_db.filter_property", lambda data, model: data)

    # Execute - update relation for agent 2 with new version_no=3
    update_related_agents(1, "tenant1", "user1", related_agents=[{"agent_id": 2, "version_no": 3}])

    # Verify: no deletions, no additions, version_no updated
    session.add.assert_not_called()
    assert mock_relation.selected_agent_version_no == 3
    assert mock_relation.updated_by == "user1"


def test_update_related_agents_no_version_no_keeps_existing(monkeypatch, mock_session):
    """Test update_related_agents does not update when version_no is None in related_agents."""
    session, query = mock_session

    mock_relation = MockAgentRelation()
    mock_relation.selected_agent_id = 2
    mock_relation.selected_agent_version_no = 5
    mock_relation.relation_id = 10

    mock_all = MagicMock()
    mock_all.return_value = [mock_relation]
    mock_filter1 = MagicMock()
    mock_filter1.all = mock_all
    query.filter.return_value = mock_filter1

    session.add = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)

    # Execute - related_agents has agent_id=2 but version_no=None
    update_related_agents(1, "tenant1", "user1", related_agents=[{"agent_id": 2, "version_no": None}])

    # Verify: version_no should remain unchanged
    assert mock_relation.selected_agent_version_no == 5


def test_update_related_agents_with_none_related_agents(monkeypatch, mock_session):
    """Test update_related_agents with related_agents=None deletes all existing relations."""
    session, query = mock_session

    mock_relation = MockAgentRelation()
    mock_relation.selected_agent_id = 2

    mock_all = MagicMock()
    mock_all.return_value = [mock_relation]
    mock_filter1 = MagicMock()
    mock_filter1.all = mock_all

    mock_update = MagicMock()
    mock_filter2 = MagicMock()
    mock_filter2.update = mock_update

    query.filter.side_effect = [mock_filter1, mock_filter2]

    session.add = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)

    # Execute - related_agents=None means no new relations
    update_related_agents(1, "tenant1", "user1", related_agents=None)

    # Verify: should soft delete the existing relation
    mock_update.assert_called_once()
    session.add.assert_not_called()


# ===================== _parse_related_agents tests =====================


def test_parse_related_agents_none():
    """Test _parse_related_agents with None input returns empty sets."""
    from backend.database.agent_db import _parse_related_agents
    ids, version_map = _parse_related_agents(None)
    assert ids == set()
    assert version_map == {}


def test_parse_related_agents_empty_list():
    """Test _parse_related_agents with empty list returns empty sets."""
    from backend.database.agent_db import _parse_related_agents
    ids, version_map = _parse_related_agents([])
    assert ids == set()
    assert version_map == {}


def test_parse_related_agents_with_none_agent_id():
    """Test _parse_related_agents skips entries with agent_id=None."""
    from backend.database.agent_db import _parse_related_agents
    ids, version_map = _parse_related_agents([
        {"agent_id": None, "version_no": 1},
        {"agent_id": 2, "version_no": 3},
    ])
    assert ids == {2}
    assert version_map == {2: 3}


def test_parse_related_agents_with_none_version_no():
    """Test _parse_related_agents does not add None version_no to version_map."""
    from backend.database.agent_db import _parse_related_agents
    ids, version_map = _parse_related_agents([
        {"agent_id": 1, "version_no": None},
        {"agent_id": 2, "version_no": 5},
    ])
    assert ids == {1, 2}
    assert version_map == {2: 5}


def test_parse_related_agents_normal_case():
    """Test _parse_related_agents with normal input."""
    from backend.database.agent_db import _parse_related_agents
    ids, version_map = _parse_related_agents([
        {"agent_id": 1, "version_no": 2},
        {"agent_id": 3, "version_no": 4},
        {"agent_id": 5, "version_no": None},
    ])
    assert ids == {1, 3, 5}
    assert version_map == {1: 2, 3: 4}


# ===================== _add_new_relations with version_map tests =====================


def test_add_new_relations_with_version_map(monkeypatch, mock_session):
    """Test _add_new_relations sets selected_agent_version_no from version_map."""
    session, query = mock_session
    session.add = MagicMock()

    captured_relations = []
    class MockAgentRelationClass:
        def __init__(self, **kwargs):
            captured_relations.append(kwargs)

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.filter_property", lambda data, model: data)
    monkeypatch.setattr("backend.database.agent_db.AgentRelation", MockAgentRelationClass)

    from backend.database.agent_db import _add_new_relations
    _add_new_relations(
        session=session,
        parent_agent_id=1,
        tenant_id="tenant1",
        user_id="user1",
        version_no=0,
        ids_to_add={2, 3},
        version_map={2: 5},
    )

    assert len(captured_relations) == 2
    # Relation for agent 2 should have selected_agent_version_no=5
    rel_2 = next(r for r in captured_relations if r["selected_agent_id"] == 2)
    assert rel_2["selected_agent_version_no"] == 5
    # Relation for agent 3 should not have selected_agent_version_no
    rel_3 = next(r for r in captured_relations if r["selected_agent_id"] == 3)
    assert "selected_agent_version_no" not in rel_3


# ===================== update_agent with model_fields_set tests =====================


def test_update_agent_pops_requested_output_tokens_when_not_in_fields_set(monkeypatch, mock_session):
    """Test update_agent pops requested_output_tokens when model_fields_set doesn't include it."""
    session, query = mock_session
    mock_agent = MockAgent()
    mock_agent.requested_output_tokens = 2048

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

    class AgentInfoUpdate:
        def __init__(self):
            self.name = "updated_name"
            # model_fields_set exists but does NOT contain "requested_output_tokens"
            self.model_fields_set = {"name"}

    agent_info = AgentInfoUpdate()

    update_agent(1, agent_info, "user1")

    # requested_output_tokens should be popped from agent_data, so it's not set on mock_agent
    assert mock_agent.name == "updated_name"
    assert mock_agent.updated_by == "user1"


# ===================== _update_existing_relations direct tests =====================


def test_update_existing_relations_skips_none_version_no(monkeypatch):
    """Test _update_existing_relations skips update when new_version_no is None for some relations."""
    from backend.database.agent_db import _update_existing_relations

    mock_rel_with_version = MagicMock()
    mock_rel_with_version.selected_agent_id = 2
    mock_rel_with_version.selected_agent_version_no = 1

    mock_rel_without_version = MagicMock()
    mock_rel_without_version.selected_agent_id = 5
    mock_rel_without_version.selected_agent_version_no = 10

    # version_map only has agent 2, not agent 5
    _update_existing_relations(
        current_relations=[mock_rel_with_version, mock_rel_without_version],
        ids_to_update={2, 5},
        version_map={2: 3},
        user_id="user1",
    )

    # Agent 2 should be updated to version 3
    assert mock_rel_with_version.selected_agent_version_no == 3
    assert mock_rel_with_version.updated_by == "user1"
    # Agent 5 should NOT be updated (new_version_no is None)
    assert mock_rel_without_version.selected_agent_version_no == 10


def test_update_existing_relations_skips_relations_not_in_update_set(monkeypatch):
    """Test _update_existing_relations skips relations not in ids_to_update."""
    from backend.database.agent_db import _update_existing_relations

    mock_rel_to_update = MagicMock()
    mock_rel_to_update.selected_agent_id = 2
    mock_rel_to_update.selected_agent_version_no = 1

    mock_rel_to_skip = MagicMock()
    mock_rel_to_skip.selected_agent_id = 99
    mock_rel_to_skip.selected_agent_version_no = 7

    _update_existing_relations(
        current_relations=[mock_rel_to_update, mock_rel_to_skip],
        ids_to_update={2},
        version_map={2: 5},
        user_id="user1",
    )

    # Agent 2 should be updated
    assert mock_rel_to_update.selected_agent_version_no == 5
    # Agent 99 should NOT be updated (not in ids_to_update)
    assert mock_rel_to_skip.selected_agent_version_no == 7


def test_update_existing_relations_returns_early_when_empty():
    """Test _update_existing_relations returns early when ids_to_update or version_map is empty."""
    from backend.database.agent_db import _update_existing_relations

    mock_rel = MagicMock()
    mock_rel.selected_agent_id = 2
    mock_rel.selected_agent_version_no = 1

    # Empty ids_to_update
    _update_existing_relations(
        current_relations=[mock_rel],
        ids_to_update=set(),
        version_map={2: 3},
        user_id="user1",
    )
    assert mock_rel.selected_agent_version_no == 1  # unchanged

    # Empty version_map
    _update_existing_relations(
        current_relations=[mock_rel],
        ids_to_update={2},
        version_map={},
        user_id="user1",
    )
    assert mock_rel.selected_agent_version_no == 1  # unchanged
