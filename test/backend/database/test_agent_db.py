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
    delete_agent_relationship
)

class MockAgent:
    def __init__(self):
        self.agent_id = 1
        self.name = "test_agent"
        self.tenant_id = "tenant1"
        self.delete_flag = "N"
        self.enabled = True
        self.updated_by = None
        self.business_logic_model_id = None
        self.business_logic_model_name = None

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
    
    update_agent(1, agent_info, "tenant1", "user1")
    
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
        update_agent(999, agent_info, "tenant1", "user1")

def test_delete_agent_by_id_success(monkeypatch, mock_session):
    """测试成功删除agent"""
    session, query = mock_session
    mock_update = MagicMock()
    mock_filter = MagicMock()
    mock_filter.update = mock_update
    query.filter.return_value = mock_filter
    
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = session
    mock_ctx.__exit__.return_value = None
    monkeypatch.setattr("backend.database.agent_db.get_db_session", lambda: mock_ctx)
    
    delete_agent_by_id(1, "tenant1", "user1")
    
    # 验证调用了两次update（一次更新AgentInfo，一次更新ToolInstance）
    assert mock_update.call_count == 2

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
    
    result = insert_related_agent(1, 2, "tenant1")
    
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
    
    result = insert_related_agent(1, 2, "tenant1")
    
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
    
    result = delete_related_agent(1, 2, "tenant1")
    
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
    
    result = delete_related_agent(1, 2, "tenant1")
    
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