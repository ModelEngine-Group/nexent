"""Unit tests for backend.database.skill_db module."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../sdk"))

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

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
sys.modules['consts.model'] = MagicMock()

client_mock = MagicMock()
client_mock.MinioClient = MagicMock()
client_mock.PostgresClient = MagicMock()
client_mock.db_client = MagicMock()
client_mock.get_db_session = MagicMock()
client_mock.as_dict = MagicMock()
client_mock.filter_property = MagicMock()
sys.modules['database.client'] = client_mock
sys.modules['backend.database.client'] = client_mock

db_models_mock = MagicMock()
sys.modules['database.db_models'] = db_models_mock
sys.modules['backend.database.db_models'] = db_models_mock

utils_skill_params_mock = MagicMock()
utils_skill_params_mock.strip_params_comments_for_db = lambda x: x
sys.modules['utils'] = MagicMock()
sys.modules['utils.auth_utils'] = MagicMock()
sys.modules['utils.skill_params_utils'] = utils_skill_params_mock
sys.modules['backend.utils'] = MagicMock()
sys.modules['backend.utils.skill_params_utils'] = utils_skill_params_mock

from backend.database.skill_db import (
    _params_value_for_db,
    create_or_update_skill_by_skill_info,
    query_skill_instances_by_agent_id,
    query_enabled_skill_instances,
    query_skill_instance_by_id,
    search_skills_for_agent,
    delete_skills_by_agent_id,
    delete_skill_instances_by_skill_id,
    list_skills,
    get_skill_by_name,
    get_skill_by_id,
    create_skill,
    update_skill,
    delete_skill,
    get_tool_names_by_ids,
    get_tool_ids_by_names,
    get_tool_names_by_skill_name,
    get_skill_with_tool_names,
    _get_tool_ids,
    _to_dict,
)


class MockSkillInstance:
    """Mock SkillInstance model for testing."""
    def __init__(self, **kwargs):
        self.skill_instance_id = kwargs.get('skill_instance_id', 1)
        self.skill_id = kwargs.get('skill_id', 1)
        self.agent_id = kwargs.get('agent_id', 1)
        self.user_id = kwargs.get('user_id', 'user1')
        self.tenant_id = kwargs.get('tenant_id', 'tenant1')
        self.enabled = kwargs.get('enabled', True)
        self.delete_flag = kwargs.get('delete_flag', 'N')
        self.version_no = kwargs.get('version_no', 0)
        self.created_by = kwargs.get('created_by', 'user1')
        self.updated_by = kwargs.get('updated_by', 'user1')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')
        self.create_time = kwargs.get('create_time', datetime.now())
        self.update_time = kwargs.get('update_time', datetime.now())
        self.__dict__.update(kwargs)


class MockSkillInfo:
    """Mock SkillInfo model for testing."""
    def __init__(self, **kwargs):
        self.skill_id = kwargs.get('skill_id', 1)
        self.skill_name = kwargs.get('skill_name', 'test_skill')
        self.skill_description = kwargs.get('skill_description', 'Test description')
        self.skill_tags = kwargs.get('skill_tags', ['tag1'])
        self.skill_content = kwargs.get('skill_content', 'Test content')
        self.params = kwargs.get('params', {})
        self.source = kwargs.get('source', 'custom')
        self.created_by = kwargs.get('created_by', 'creator1')
        self.create_time = kwargs.get('create_time', datetime.now())
        self.updated_by = kwargs.get('updated_by', 'updater1')
        self.update_time = kwargs.get('update_time', datetime.now())
        self.delete_flag = kwargs.get('delete_flag', 'N')
        self.__dict__.update(kwargs)


class MockSkillToolRelation:
    """Mock SkillToolRelation model for testing."""
    def __init__(self, **kwargs):
        self.skill_id = kwargs.get('skill_id', 1)
        self.tool_id = kwargs.get('tool_id', 1)
        self.create_time = kwargs.get('create_time', datetime.now())
        self.__dict__.update(kwargs)


class MockToolInfo:
    """Mock ToolInfo model for testing."""
    def __init__(self, **kwargs):
        self.tool_id = kwargs.get('tool_id', 1)
        self.name = kwargs.get('name', 'test_tool')
        self.delete_flag = kwargs.get('delete_flag', 'N')
        self.author = kwargs.get('author', 'tenant1')
        self.__dict__.update(kwargs)


@pytest.fixture
def mock_session():
    """Create a mock database session."""
    mock_session = MagicMock()
    mock_query = MagicMock()
    mock_session.query.return_value = mock_query
    return mock_session, mock_query


# ===== _params_value_for_db Tests =====

class TestParamsValueForDb:
    """Tests for _params_value_for_db helper function."""

    def test_params_value_for_db_none(self):
        """Test that None input returns None."""
        result = _params_value_for_db(None)
        assert result is None

    def test_params_value_for_db_dict_with_comments(self, monkeypatch):
        """Test stripping _comment keys from dict."""
        monkeypatch.setattr(
            "backend.database.skill_db.strip_params_comments_for_db",
            lambda x: {k: v for k, v in x.items() if k != '_comment'} if isinstance(x, dict) else x
        )
        input_data = {"key1": "value1", "_comment": "This is a comment"}
        result = _params_value_for_db(input_data)
        assert "_comment" not in result
        assert result["key1"] == "value1"

    def test_params_value_for_db_nested_structure(self, monkeypatch):
        """Test handling nested dict structures."""
        monkeypatch.setattr(
            "backend.database.skill_db.strip_params_comments_for_db",
            lambda x: x
        )
        input_data = {
            "outer": {"inner": "value", "_comment": "nested comment"},
            "_comment": "top comment"
        }
        result = _params_value_for_db(input_data)
        assert "outer" in result


# ===== create_or_update_skill_by_skill_info Tests =====

class TestCreateOrUpdateSkillBySkillInfo:
    """Tests for create_or_update_skill_by_skill_info function."""

    def test_update_existing_skill_instance(self, monkeypatch, mock_session):
        """Test updating an existing skill instance."""
        session, query = mock_session
        mock_skill_instance = MockSkillInstance(
            skill_instance_id=1,
            skill_id=1,
            agent_id=1,
            tenant_id='tenant1',
            enabled=True
        )

        mock_first = MagicMock()
        mock_first.return_value = mock_skill_instance
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db.as_dict",
            lambda obj: obj.__dict__ if hasattr(obj, '__dict__') else obj
        )

        skill_info = MagicMock()
        skill_info.__dict__ = {
            'agent_id': 1,
            'skill_id': 1,
            'enabled': False
        }

        result = create_or_update_skill_by_skill_info(
            skill_info, 'tenant1', 'user1'
        )

        mock_first.assert_called_once()
        assert mock_skill_instance.enabled is False
        assert mock_skill_instance.updated_by == 'user1'

    def test_create_new_skill_instance(self, monkeypatch, mock_session):
        """Test creating a new skill instance."""
        session, query = mock_session

        mock_first = MagicMock()
        mock_first.return_value = None
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db.as_dict",
            lambda obj: obj.__dict__ if hasattr(obj, '__dict__') else obj
        )
        monkeypatch.setattr(
            "backend.database.skill_db.filter_property",
            lambda data, model: data
        )

        class MockSkillInstanceClass:
            tenant_id = MagicMock()
            agent_id = MagicMock()
            skill_id = MagicMock()
            delete_flag = MagicMock()
            version_no = MagicMock()
            user_id = MagicMock()
            created_by = MagicMock()
            updated_by = MagicMock()
            enabled = MagicMock()

            def __init__(self, **kwargs):
                for key, value in kwargs.items():
                    setattr(self, key, value)

        monkeypatch.setattr(
            "backend.database.skill_db.SkillInstance",
            MockSkillInstanceClass
        )
        session.add = MagicMock()
        session.flush = MagicMock()

        skill_info = MagicMock()
        skill_info.__dict__ = {
            'agent_id': 1,
            'skill_id': 1,
            'enabled': True
        }

        result = create_or_update_skill_by_skill_info(
            skill_info, 'tenant1', 'user1'
        )

        session.add.assert_called_once()
        session.flush.assert_called_once()

    def test_skill_info_as_dict(self, monkeypatch, mock_session):
        """Test when skill_info is already a dict."""
        session, query = mock_session
        mock_skill_instance = MockSkillInstance(skill_id=1)

        mock_first = MagicMock()
        mock_first.return_value = mock_skill_instance
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db.as_dict",
            lambda obj: obj.__dict__ if hasattr(obj, '__dict__') else obj
        )

        skill_info = {'agent_id': 1, 'skill_id': 1, 'enabled': True}

        result = create_or_update_skill_by_skill_info(
            skill_info, 'tenant1', 'user1'
        )

        assert mock_skill_instance.skill_id == 1

    def test_skill_info_setdefault_values(self, monkeypatch, mock_session):
        """Test that setdefault values are applied correctly."""
        session, query = mock_session
        mock_skill_instance = MockSkillInstance(skill_id=1)

        mock_first = MagicMock()
        mock_first.return_value = mock_skill_instance
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db.as_dict",
            lambda obj: obj.__dict__ if hasattr(obj, '__dict__') else obj
        )

        skill_info = MagicMock()
        skill_info.__dict__ = {
            'agent_id': 1,
            'skill_id': 1
        }

        result = create_or_update_skill_by_skill_info(
            skill_info, 'tenant1', 'user1', version_no=5
        )

        assert mock_skill_instance.tenant_id == 'tenant1'
        assert mock_skill_instance.user_id == 'user1'
        assert mock_skill_instance.version_no == 5
        assert mock_skill_instance.created_by == 'user1'
        assert mock_skill_instance.updated_by == 'user1'

    def test_update_with_non_model_attribute(self, monkeypatch, mock_session):
        """Test that non-model attributes are ignored during update."""
        session, query = mock_session
        mock_skill_instance = MockSkillInstance(skill_id=1)

        mock_first = MagicMock()
        mock_first.return_value = mock_skill_instance
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db.as_dict",
            lambda obj: obj.__dict__ if hasattr(obj, '__dict__') else obj
        )

        skill_info = MagicMock()
        skill_info.__dict__ = {
            'agent_id': 1,
            'skill_id': 1,
            'enabled': True,
            'non_model_field': 'should_be_ignored'
        }

        result = create_or_update_skill_by_skill_info(
            skill_info, 'tenant1', 'user1'
        )

        assert mock_skill_instance.skill_id == 1

    def test_update_with_existing_tenant_id_in_skill_info(self, monkeypatch, mock_session):
        """Test that skill_info's tenant_id is not overwritten."""
        session, query = mock_session
        mock_skill_instance = MockSkillInstance(skill_id=1, tenant_id='original_tenant')

        mock_first = MagicMock()
        mock_first.return_value = mock_skill_instance
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db.as_dict",
            lambda obj: obj.__dict__ if hasattr(obj, '__dict__') else obj
        )

        skill_info = MagicMock()
        skill_info.__dict__ = {
            'agent_id': 1,
            'skill_id': 1,
            'tenant_id': 'skill_tenant'
        }

        result = create_or_update_skill_by_skill_info(
            skill_info, 'tenant1', 'user1'
        )

        assert mock_skill_instance.tenant_id == 'skill_tenant'


# ===== query_skill_instances_by_agent_id Tests =====

class TestQuerySkillInstancesByAgentId:
    """Tests for query_skill_instances_by_agent_id function."""

    def test_query_returns_multiple_instances(self, monkeypatch, mock_session):
        """Test querying with multiple results."""
        session, query = mock_session
        mock_instance1 = MockSkillInstance(skill_instance_id=1, skill_id=1)
        mock_instance2 = MockSkillInstance(skill_instance_id=2, skill_id=2)

        mock_all = MagicMock()
        mock_all.return_value = [mock_instance1, mock_instance2]
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db.as_dict",
            lambda obj: obj.__dict__ if hasattr(obj, '__dict__') else obj
        )

        result = query_skill_instances_by_agent_id(1, 'tenant1')

        assert len(result) == 2
        assert result[0]['skill_instance_id'] == 1
        assert result[1]['skill_instance_id'] == 2

    def test_query_returns_empty_list(self, monkeypatch, mock_session):
        """Test querying with no results."""
        session, query = mock_session

        mock_all = MagicMock()
        mock_all.return_value = []
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db.as_dict",
            lambda obj: obj.__dict__ if hasattr(obj, '__dict__') else obj
        )

        result = query_skill_instances_by_agent_id(1, 'tenant1')

        assert result == []

    def test_query_with_custom_version_no(self, monkeypatch, mock_session):
        """Test querying with specific version number."""
        session, query = mock_session
        mock_instance = MockSkillInstance(skill_instance_id=1, version_no=5)

        mock_all = MagicMock()
        mock_all.return_value = [mock_instance]
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db.as_dict",
            lambda obj: obj.__dict__ if hasattr(obj, '__dict__') else obj
        )

        result = query_skill_instances_by_agent_id(1, 'tenant1', version_no=5)

        assert len(result) == 1
        assert result[0]['version_no'] == 5


# ===== query_enabled_skill_instances Tests =====

class TestQueryEnabledSkillInstances:
    """Tests for query_enabled_skill_instances function."""

    def test_query_enabled_returns_enabled_only(self, monkeypatch, mock_session):
        """Test querying only returns enabled instances."""
        session, query = mock_session
        mock_instance = MockSkillInstance(
            skill_instance_id=1,
            enabled=True
        )

        mock_all = MagicMock()
        mock_all.return_value = [mock_instance]
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db.as_dict",
            lambda obj: obj.__dict__ if hasattr(obj, '__dict__') else obj
        )

        result = query_enabled_skill_instances(1, 'tenant1')

        assert len(result) == 1
        assert result[0]['enabled'] is True

    def test_query_enabled_empty_result(self, monkeypatch, mock_session):
        """Test querying enabled returns empty when none exist."""
        session, query = mock_session

        mock_all = MagicMock()
        mock_all.return_value = []
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db.as_dict",
            lambda obj: obj.__dict__ if hasattr(obj, '__dict__') else obj
        )

        result = query_enabled_skill_instances(999, 'tenant1')

        assert result == []

    def test_query_enabled_with_version(self, monkeypatch, mock_session):
        """Test querying enabled with specific version."""
        session, query = mock_session
        mock_instance = MockSkillInstance(
            skill_instance_id=1,
            enabled=True,
            version_no=3
        )

        mock_all = MagicMock()
        mock_all.return_value = [mock_instance]
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db.as_dict",
            lambda obj: obj.__dict__ if hasattr(obj, '__dict__') else obj
        )

        result = query_enabled_skill_instances(1, 'tenant1', version_no=3)

        assert len(result) == 1
        assert result[0]['version_no'] == 3


# ===== query_skill_instance_by_id Tests =====

class TestQuerySkillInstanceById:
    """Tests for query_skill_instance_by_id function."""

    def test_query_by_id_found(self, monkeypatch, mock_session):
        """Test querying by agent_id and skill_id returns result."""
        session, query = mock_session
        mock_instance = MockSkillInstance(
            skill_instance_id=1,
            skill_id=5,
            agent_id=10
        )

        mock_first = MagicMock()
        mock_first.return_value = mock_instance
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db.as_dict",
            lambda obj: obj.__dict__ if hasattr(obj, '__dict__') else obj
        )

        result = query_skill_instance_by_id(10, 5, 'tenant1')

        assert result is not None
        assert result['skill_id'] == 5
        assert result['agent_id'] == 10

    def test_query_by_id_not_found(self, monkeypatch, mock_session):
        """Test querying by agent_id and skill_id returns None when not found."""
        session, query = mock_session

        mock_first = MagicMock()
        mock_first.return_value = None
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)

        result = query_skill_instance_by_id(10, 999, 'tenant1')

        assert result is None

    def test_query_by_id_with_version(self, monkeypatch, mock_session):
        """Test querying by id with specific version."""
        session, query = mock_session
        mock_instance = MockSkillInstance(
            skill_instance_id=1,
            skill_id=5,
            agent_id=10,
            version_no=7
        )

        mock_first = MagicMock()
        mock_first.return_value = mock_instance
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db.as_dict",
            lambda obj: obj.__dict__ if hasattr(obj, '__dict__') else obj
        )

        result = query_skill_instance_by_id(10, 5, 'tenant1', version_no=7)

        assert result is not None
        assert result['version_no'] == 7


# ===== search_skills_for_agent Tests =====

class TestSearchSkillsForAgent:
    """Tests for search_skills_for_agent function."""

    def test_search_returns_enabled_skills(self, monkeypatch, mock_session):
        """Test searching returns only enabled skills."""
        session, query = mock_session
        mock_instance = MockSkillInstance(
            skill_instance_id=1,
            skill_id=5,
            enabled=True
        )

        mock_all = MagicMock()
        mock_all.return_value = [mock_instance]
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db.as_dict",
            lambda obj: obj.__dict__ if hasattr(obj, '__dict__') else obj
        )

        result = search_skills_for_agent(1, 'tenant1')

        assert len(result) == 1
        assert result[0]['enabled'] is True

    def test_search_returns_empty_for_disabled_only(self, monkeypatch, mock_session):
        """Test searching returns empty when all skills are disabled."""
        session, query = mock_session

        mock_all = MagicMock()
        mock_all.return_value = []
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db.as_dict",
            lambda obj: obj.__dict__ if hasattr(obj, '__dict__') else obj
        )

        result = search_skills_for_agent(999, 'tenant1')

        assert result == []

    def test_search_with_version(self, monkeypatch, mock_session):
        """Test searching with specific version number."""
        session, query = mock_session
        mock_instance = MockSkillInstance(
            skill_instance_id=1,
            version_no=4
        )

        mock_all = MagicMock()
        mock_all.return_value = [mock_instance]
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db.as_dict",
            lambda obj: obj.__dict__ if hasattr(obj, '__dict__') else obj
        )

        result = search_skills_for_agent(1, 'tenant1', version_no=4)

        assert len(result) == 1
        assert result[0]['version_no'] == 4

    def test_search_multiple_skills(self, monkeypatch, mock_session):
        """Test searching with multiple enabled skills."""
        session, query = mock_session
        mock_instance1 = MockSkillInstance(skill_instance_id=1, skill_id=1)
        mock_instance2 = MockSkillInstance(skill_instance_id=2, skill_id=2)
        mock_instance3 = MockSkillInstance(skill_instance_id=3, skill_id=3)

        mock_all = MagicMock()
        mock_all.return_value = [mock_instance1, mock_instance2, mock_instance3]
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db.as_dict",
            lambda obj: obj.__dict__ if hasattr(obj, '__dict__') else obj
        )

        result = search_skills_for_agent(1, 'tenant1')

        assert len(result) == 3


# ===== delete_skills_by_agent_id Tests =====

class TestDeleteSkillsByAgentId:
    """Tests for delete_skills_by_agent_id function."""

    def test_delete_soft_deletes_all_instances(self, monkeypatch, mock_session):
        """Test that delete sets delete_flag='Y' for all instances."""
        session, query = mock_session

        mock_update = MagicMock()
        mock_filter = MagicMock()
        mock_filter.update = mock_update
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)

        delete_skills_by_agent_id(1, 'tenant1', 'user1')

        mock_update.assert_called_once()
        assert query.filter.called

    def test_delete_with_version(self, monkeypatch, mock_session):
        """Test delete with specific version number."""
        session, query = mock_session

        mock_update = MagicMock()
        mock_filter = MagicMock()
        mock_filter.update = mock_update
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)

        delete_skills_by_agent_id(1, 'tenant1', 'user1', version_no=5)

        mock_update.assert_called_once()

    def test_delete_updates_updated_by(self, monkeypatch, mock_session):
        """Test that delete updates the updated_by field."""
        session, query = mock_session

        mock_update = MagicMock()
        mock_filter = MagicMock()
        mock_filter.update = mock_update
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)

        delete_skills_by_agent_id(1, 'tenant1', 'deleter_user')

        update_call_args = mock_update.call_args
        update_dict = update_call_args[0][0]
        assert update_dict['updated_by'] == 'deleter_user'


# ===== delete_skill_instances_by_skill_id Tests =====

class TestDeleteSkillInstancesBySkillId:
    """Tests for delete_skill_instances_by_skill_id function."""

    def test_delete_by_skill_id_soft_deletes(self, monkeypatch, mock_session):
        """Test that delete by skill_id sets delete_flag='Y'."""
        session, query = mock_session

        mock_update = MagicMock()
        mock_filter = MagicMock()
        mock_filter.update = mock_update
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)

        delete_skill_instances_by_skill_id(5, 'user1')

        mock_update.assert_called_once()

    def test_delete_by_skill_id_updates_updated_by(self, monkeypatch, mock_session):
        """Test that delete by skill_id updates the updated_by field."""
        session, query = mock_session

        mock_update = MagicMock()
        mock_filter = MagicMock()
        mock_filter.update = mock_update
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)

        delete_skill_instances_by_skill_id(5, 'skill_deleter')

        update_call_args = mock_update.call_args
        update_dict = update_call_args[0][0]
        assert update_dict['updated_by'] == 'skill_deleter'

    def test_delete_by_nonexistent_skill_id(self, monkeypatch, mock_session):
        """Test deleting a non-existent skill (no instances to delete)."""
        session, query = mock_session

        mock_update = MagicMock()
        mock_filter = MagicMock()
        mock_filter.update = mock_update
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)

        delete_skill_instances_by_skill_id(999, 'user1')

        mock_update.assert_called_once()


# ===== _get_tool_ids Tests =====

class TestGetToolIds:
    """Tests for _get_tool_ids helper function."""

    def test_get_tool_ids_returns_tool_ids(self, monkeypatch, mock_session):
        """Test that tool IDs are extracted from relations."""
        session, query = mock_session

        mock_rel1 = MagicMock()
        mock_rel1.tool_id = 1
        mock_rel2 = MagicMock()
        mock_rel2.tool_id = 2
        mock_rel3 = MagicMock()
        mock_rel3.tool_id = 3

        mock_all = MagicMock()
        mock_all.return_value = [mock_rel1, mock_rel2, mock_rel3]
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter

        result = _get_tool_ids(session, skill_id=5)

        assert result == [1, 2, 3]

    def test_get_tool_ids_empty(self, monkeypatch, mock_session):
        """Test that empty list is returned when no tool relations exist."""
        session, query = mock_session

        mock_all = MagicMock()
        mock_all.return_value = []
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter

        result = _get_tool_ids(session, skill_id=999)

        assert result == []


# ===== _to_dict Tests =====

class TestToDict:
    """Tests for _to_dict helper function."""

    def test_to_dict_basic_fields(self):
        """Test basic field conversion."""
        skill = MockSkillInfo(
            skill_id=1,
            skill_name='test_skill',
            skill_description='Test description',
            skill_tags=['tag1', 'tag2'],
            skill_content='Test content',
            params={'param1': 'value1'},
            source='custom',
            created_by='creator1',
            create_time=datetime(2024, 1, 1, 12, 0, 0),
            updated_by='updater1',
            update_time=datetime(2024, 1, 2, 12, 0, 0)
        )

        result = _to_dict(skill)

        assert result['skill_id'] == 1
        assert result['name'] == 'test_skill'
        assert result['description'] == 'Test description'
        assert result['tags'] == ['tag1', 'tag2']
        assert result['content'] == 'Test content'
        assert result['params'] == {'param1': 'value1'}
        assert result['source'] == 'custom'
        assert result['created_by'] == 'creator1'
        assert result['create_time'] == '2024-01-01T12:00:00'
        assert result['updated_by'] == 'updater1'
        assert result['update_time'] == '2024-01-02T12:00:00'

    def test_to_dict_empty_tags(self):
        """Test handling of None/empty tags."""
        skill = MockSkillInfo(
            skill_id=1,
            skill_name='test',
            skill_tags=None,
            skill_content='',
            params=None,
            create_time=None,
            update_time=None
        )

        result = _to_dict(skill)

        assert result['tags'] == []
        assert result['content'] == ''
        assert result['params'] == {}


# ===== list_skills Tests =====

class TestListSkills:
    """Tests for list_skills function."""

    def test_list_skills_returns_all(self, monkeypatch, mock_session):
        """Test listing all skills."""
        session, query = mock_session

        skill1 = MockSkillInfo(skill_id=1, skill_name='skill1')
        skill2 = MockSkillInfo(skill_id=2, skill_name='skill2')

        mock_all = MagicMock()
        mock_all.return_value = [skill1, skill2]
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db._get_tool_ids",
            lambda s, skill_id: [1, 2] if skill_id == 1 else []
        )

        result = list_skills()

        assert len(result) == 2
        assert result[0]['name'] == 'skill1'
        assert result[0]['tool_ids'] == [1, 2]
        assert result[1]['tool_ids'] == []

    def test_list_skills_empty(self, monkeypatch, mock_session):
        """Test listing when no skills exist."""
        session, query = mock_session

        mock_all = MagicMock()
        mock_all.return_value = []
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)

        result = list_skills()

        assert result == []


# ===== get_skill_by_name Tests =====

class TestGetSkillByName:
    """Tests for get_skill_by_name function."""

    def test_get_skill_by_name_found(self, monkeypatch, mock_session):
        """Test getting skill by name when it exists."""
        session, query = mock_session

        skill = MockSkillInfo(skill_id=5, skill_name='my_skill')

        mock_first = MagicMock()
        mock_first.return_value = skill
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db._get_tool_ids",
            lambda s, skill_id: [1, 2]
        )

        result = get_skill_by_name('my_skill')

        assert result is not None
        assert result['skill_id'] == 5
        assert result['name'] == 'my_skill'
        assert result['tool_ids'] == [1, 2]

    def test_get_skill_by_name_not_found(self, monkeypatch, mock_session):
        """Test getting skill by name when it doesn't exist."""
        session, query = mock_session

        mock_first = MagicMock()
        mock_first.return_value = None
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)

        result = get_skill_by_name('nonexistent')

        assert result is None


# ===== get_skill_by_id Tests =====

class TestGetSkillById:
    """Tests for get_skill_by_id function."""

    def test_get_skill_by_id_found(self, monkeypatch, mock_session):
        """Test getting skill by ID when it exists."""
        session, query = mock_session

        skill = MockSkillInfo(skill_id=10, skill_name='specific_skill')

        mock_first = MagicMock()
        mock_first.return_value = skill
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db._get_tool_ids",
            lambda s, skill_id: [3]
        )

        result = get_skill_by_id(10)

        assert result is not None
        assert result['skill_id'] == 10
        assert result['tool_ids'] == [3]

    def test_get_skill_by_id_not_found(self, monkeypatch, mock_session):
        """Test getting skill by ID when it doesn't exist."""
        session, query = mock_session

        mock_first = MagicMock()
        mock_first.return_value = None
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)

        result = get_skill_by_id(999)

        assert result is None


# ===== create_skill Tests =====

class TestCreateSkill:
    """Tests for create_skill function."""

    def test_create_skill_basic(self, monkeypatch, mock_session):
        """Test creating a basic skill."""
        session, query = mock_session

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db._params_value_for_db",
            lambda x: x
        )

        class MockSkillInfoClass:
            skill_id = MagicMock()
            skill_name = MagicMock()
            skill_description = MagicMock()
            skill_tags = MagicMock()
            skill_content = MagicMock()
            params = MagicMock()
            source = MagicMock()
            created_by = MagicMock()
            create_time = MagicMock()
            updated_by = MagicMock()
            update_time = MagicMock()

            def __init__(self, **kwargs):
                self.skill_id = 1
                for key, value in kwargs.items():
                    setattr(self, key, value)

        monkeypatch.setattr(
            "backend.database.skill_db.SkillInfo",
            MockSkillInfoClass
        )
        session.add = MagicMock()
        session.flush = MagicMock()
        session.commit = MagicMock()

        skill_data = {
            'name': 'new_skill',
            'description': 'A new skill',
            'tags': ['tag1'],
            'content': 'Skill content',
            'params': {'param1': 'value1'},
            'source': 'custom',
            'created_by': 'creator1',
            'updated_by': 'updater1',
            'tool_ids': []
        }

        result = create_skill(skill_data)

        session.add.assert_called()
        session.commit.assert_called()

    def test_create_skill_with_tool_ids(self, monkeypatch, mock_session):
        """Test creating a skill with associated tool IDs."""
        session, query = mock_session

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db._params_value_for_db",
            lambda x: x
        )

        class MockSkillInfoClass:
            skill_id = 1
            skill_name = 'tool_skill'
            skill_description = ''
            skill_tags = []
            skill_content = ''
            params = {}
            source = 'custom'
            created_by = 'user1'
            create_time = datetime.now()
            updated_by = 'user1'
            update_time = datetime.now()

            def __init__(self, **kwargs):
                for key, value in kwargs.items():
                    setattr(self, key, value)

        class MockSkillToolRelationClass:
            skill_id = None
            tool_id = None
            create_time = None

            def __init__(self, **kwargs):
                for key, value in kwargs.items():
                    setattr(self, key, value)

        monkeypatch.setattr(
            "backend.database.skill_db.SkillInfo",
            MockSkillInfoClass
        )
        monkeypatch.setattr(
            "backend.database.skill_db.SkillToolRelation",
            MockSkillToolRelationClass
        )
        session.add = MagicMock()
        session.flush = MagicMock()
        session.commit = MagicMock()

        skill_data = {
            'name': 'tool_skill',
            'tool_ids': [1, 2, 3]
        }

        result = create_skill(skill_data)

        assert result['skill_id'] == 1
        assert result['tool_ids'] == [1, 2, 3]
        session.commit.assert_called()


# ===== update_skill Tests =====

class TestUpdateSkill:
    """Tests for update_skill function."""

    def test_update_skill_not_found(self, monkeypatch, mock_session):
        """Test updating a skill that doesn't exist raises ValueError."""
        session, query = mock_session

        mock_first = MagicMock()
        mock_first.return_value = None
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)

        with pytest.raises(ValueError, match="Skill not found"):
            update_skill('nonexistent', {})

    def test_update_skill_basic(self, monkeypatch, mock_session):
        """Test updating basic skill fields."""
        session, query = mock_session

        existing_skill = MockSkillInfo(skill_id=1, skill_name='old_name')
        refreshed_skill = MockSkillInfo(
            skill_id=1,
            skill_name='old_name',
            skill_description='new description',
            skill_content='new content'
        )

        call_count = [0]

        def mock_query_side_effect(model):
            mock_q = MagicMock()
            if call_count[0] == 0:
                mock_first = MagicMock()
                mock_first.return_value = existing_skill
                mock_q.filter.return_value.first = mock_first
                mock_q.filter.return_value.first.side_effect = None
            else:
                mock_first = MagicMock()
                mock_first.return_value = refreshed_skill
                mock_q.filter.return_value.first = mock_first
            call_count[0] += 1
            return mock_q

        session.query.side_effect = mock_query_side_effect

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db._params_value_for_db",
            lambda x: x
        )
        monkeypatch.setattr(
            "backend.database.skill_db._get_tool_ids",
            lambda s, skill_id: []
        )
        monkeypatch.setattr(
            "backend.database.skill_db.sa_update",
            lambda x: MagicMock()
        )
        session.execute = MagicMock()
        session.commit = MagicMock()

        skill_data = {
            'description': 'new description',
            'content': 'new content'
        }

        result = update_skill('old_name', skill_data)

        session.execute.assert_called()

    def test_update_skill_with_tool_ids(self, monkeypatch, mock_session):
        """Test updating skill with new tool IDs."""
        session, query = mock_session

        existing_skill = MockSkillInfo(skill_id=5, skill_name='my_skill')
        refreshed_skill = MockSkillInfo(skill_id=5, skill_name='my_skill')

        call_count = [0]

        def mock_query_side_effect(model):
            mock_q = MagicMock()
            if call_count[0] == 0:
                mock_first = MagicMock()
                mock_first.return_value = existing_skill
                mock_q.filter.return_value.first = mock_first
            else:
                mock_first = MagicMock()
                mock_first.return_value = refreshed_skill
                mock_q.filter.return_value.first = mock_first
            call_count[0] += 1
            return mock_q

        session.query.side_effect = mock_query_side_effect

        deleted_relations = []

        def mock_filter_side_effect(model):
            mock_q = MagicMock()
            mock_q.delete = MagicMock()
            deleted_relations.append(True)
            return mock_q

        session.query.return_value.filter.side_effect = mock_filter_side_effect

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db._get_tool_ids",
            lambda s, skill_id: [1, 2]
        )
        monkeypatch.setattr(
            "backend.database.skill_db.sa_update",
            lambda x: MagicMock()
        )
        session.execute = MagicMock()
        session.commit = MagicMock()

        class MockSkillToolRelationClass:
            skill_id = None
            tool_id = None
            create_time = None

            def __init__(self, **kwargs):
                for key, value in kwargs.items():
                    setattr(self, key, value)

        monkeypatch.setattr(
            "backend.database.skill_db.SkillToolRelation",
            MockSkillToolRelationClass
        )

        skill_data = {'tool_ids': [1, 2, 3]}

        result = update_skill('my_skill', skill_data)

        session.execute.assert_called()

    def test_update_skill_after_refresh_not_found(self, monkeypatch, mock_session):
        """Test that ValueError is raised when skill is not found after refresh."""
        session, query = mock_session

        existing_skill = MockSkillInfo(skill_id=1, skill_name='volatile_skill')

        call_count = [0]

        def mock_query_side_effect(model):
            mock_q = MagicMock()
            if call_count[0] == 0:
                mock_first = MagicMock()
                mock_first.return_value = existing_skill
                mock_q.filter.return_value.first = mock_first
            else:
                mock_first = MagicMock()
                mock_first.return_value = None
                mock_q.filter.return_value.first = mock_first
            call_count[0] += 1
            return mock_q

        session.query.side_effect = mock_query_side_effect

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db.sa_update",
            lambda x: MagicMock()
        )
        session.execute = MagicMock()
        session.commit = MagicMock()

        with pytest.raises(ValueError, match="Skill not found after update"):
            update_skill('volatile_skill', {'description': 'new'})

    def test_update_skill_with_all_fields(self, monkeypatch, mock_session):
        """Test updating skill with all possible fields."""
        session, query = mock_session

        existing_skill = MockSkillInfo(skill_id=3, skill_name='full_update')
        refreshed_skill = MockSkillInfo(
            skill_id=3,
            skill_name='full_update',
            skill_description='updated desc',
            skill_tags=['new', 'tags'],
            skill_content='updated content',
            source='builtin',
            params={'key': 'value'}
        )

        call_count = [0]

        def mock_query_side_effect(model):
            mock_q = MagicMock()
            if call_count[0] == 0:
                mock_first = MagicMock()
                mock_first.return_value = existing_skill
                mock_q.filter.return_value.first = mock_first
            else:
                mock_first = MagicMock()
                mock_first.return_value = refreshed_skill
                mock_q.filter.return_value.first = mock_first
            call_count[0] += 1
            return mock_q

        session.query.side_effect = mock_query_side_effect

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db._params_value_for_db",
            lambda x: x
        )
        monkeypatch.setattr(
            "backend.database.skill_db._get_tool_ids",
            lambda s, skill_id: []
        )
        monkeypatch.setattr(
            "backend.database.skill_db.sa_update",
            lambda x: MagicMock()
        )
        session.execute = MagicMock()
        session.commit = MagicMock()

        skill_data = {
            'description': 'updated desc',
            'tags': ['new', 'tags'],
            'content': 'updated content',
            'source': 'builtin',
            'params': {'key': 'value'}
        }

        result = update_skill('full_update', skill_data, updated_by='admin')

        session.execute.assert_called()

    def test_update_skill_without_updated_by(self, monkeypatch, mock_session):
        """Test updating skill without updated_by parameter."""
        session, query = mock_session

        existing_skill = MockSkillInfo(skill_id=4, skill_name='no_updater')
        refreshed_skill = MockSkillInfo(
            skill_id=4,
            skill_name='no_updater'
        )

        call_count = [0]

        def mock_query_side_effect(model):
            mock_q = MagicMock()
            if call_count[0] == 0:
                mock_first = MagicMock()
                mock_first.return_value = existing_skill
                mock_q.filter.return_value.first = mock_first
            else:
                mock_first = MagicMock()
                mock_first.return_value = refreshed_skill
                mock_q.filter.return_value.first = mock_first
            call_count[0] += 1
            return mock_q

        session.query.side_effect = mock_query_side_effect

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db._get_tool_ids",
            lambda s, skill_id: []
        )
        monkeypatch.setattr(
            "backend.database.skill_db.sa_update",
            lambda x: MagicMock()
        )
        session.execute = MagicMock()
        session.commit = MagicMock()

        skill_data = {'description': 'desc only'}

        result = update_skill('no_updater', skill_data)

        session.execute.assert_called()


# ===== delete_skill Tests =====

class TestDeleteSkill:
    """Tests for delete_skill function."""

    def test_delete_skill_not_found(self, monkeypatch, mock_session):
        """Test deleting a skill that doesn't exist returns False."""
        session, query = mock_session

        mock_first = MagicMock()
        mock_first.return_value = None
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)

        result = delete_skill('nonexistent')

        assert result is False

    def test_delete_skill_success(self, monkeypatch, mock_session):
        """Test successfully deleting a skill."""
        session, query = mock_session

        skill_to_delete = MockSkillInfo(skill_id=5, skill_name='to_delete')
        skill_to_delete.delete_flag = 'N'

        mock_first = MagicMock()
        mock_first.return_value = skill_to_delete
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_update = MagicMock()
        mock_filter.update = mock_update

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        session.commit = MagicMock()

        result = delete_skill('to_delete', updated_by='deleter1')

        assert result is True
        assert skill_to_delete.delete_flag == 'Y'
        assert skill_to_delete.updated_by == 'deleter1'
        session.commit.assert_called()

    def test_delete_skill_without_updated_by(self, monkeypatch, mock_session):
        """Test deleting a skill without specifying updated_by."""
        session, query = mock_session

        skill_to_delete = MockSkillInfo(skill_id=5, skill_name='to_delete')

        mock_first = MagicMock()
        mock_first.return_value = skill_to_delete
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_update = MagicMock()
        mock_filter.update = mock_update

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        session.commit = MagicMock()

        result = delete_skill('to_delete')

        assert result is True

    def test_delete_skill_already_deleted(self, monkeypatch, mock_session):
        """Test deleting a skill that is already deleted returns False."""
        session, query = mock_session

        mock_first = MagicMock()
        mock_first.return_value = None
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)

        result = delete_skill('already_deleted_skill')

        assert result is False


# ===== get_tool_names_by_ids Tests =====

class TestGetToolNamesByIds:
    """Tests for get_tool_names_by_ids function."""

    def test_get_tool_names_by_ids_empty(self, mock_session):
        """Test with empty tool IDs list."""
        session, query = mock_session

        result = get_tool_names_by_ids(session, [])

        assert result == []

    def test_get_tool_names_by_ids_with_results(self, mock_session):
        """Test with valid tool IDs."""
        session, query = mock_session

        tool1 = MagicMock()
        tool1.name = 'tool_a'
        tool2 = MagicMock()
        tool2.name = 'tool_b'

        mock_all = MagicMock()
        mock_all.return_value = [tool1, tool2]
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter

        result = get_tool_names_by_ids(session, [1, 2])

        assert result == ['tool_a', 'tool_b']


# ===== get_tool_ids_by_names Tests =====

class TestGetToolIdsByNames:
    """Tests for get_tool_ids_by_names function."""

    def test_get_tool_ids_by_names_empty(self, monkeypatch, mock_session):
        """Test with empty tool names list."""
        session, query = mock_session

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)

        result = get_tool_ids_by_names([], 'tenant1')

        assert result == []

    def test_get_tool_ids_by_names_with_results(self, monkeypatch, mock_session):
        """Test with valid tool names."""
        session, query = mock_session

        tool1 = MagicMock()
        tool1.tool_id = 10
        tool2 = MagicMock()
        tool2.tool_id = 20

        mock_all = MagicMock()
        mock_all.return_value = [tool1, tool2]
        mock_filter = MagicMock()
        mock_filter.all = mock_all
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)

        result = get_tool_ids_by_names(['tool_a', 'tool_b'], 'tenant1')

        assert result == [10, 20]


# ===== get_tool_names_by_skill_name Tests =====

class TestGetToolNamesBySkillName:
    """Tests for get_tool_names_by_skill_name function."""

    def test_get_tool_names_by_skill_name_not_found(self, monkeypatch, mock_session):
        """Test when skill doesn't exist."""
        session, query = mock_session

        mock_first = MagicMock()
        mock_first.return_value = None
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)

        result = get_tool_names_by_skill_name('nonexistent')

        assert result == []

    def test_get_tool_names_by_skill_name_found(self, monkeypatch, mock_session):
        """Test when skill exists."""
        session, query = mock_session

        skill = MockSkillInfo(skill_id=5, skill_name='my_skill')

        mock_first = MagicMock()
        mock_first.return_value = skill
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db._get_tool_ids",
            lambda s, skill_id: [1, 2]
        )
        monkeypatch.setattr(
            "backend.database.skill_db.get_tool_names_by_ids",
            lambda s, ids: ['tool_a', 'tool_b']
        )

        result = get_tool_names_by_skill_name('my_skill')

        assert result == ['tool_a', 'tool_b']


# ===== get_skill_with_tool_names Tests =====

class TestGetSkillWithToolNames:
    """Tests for get_skill_with_tool_names function."""

    def test_get_skill_with_tool_names_not_found(self, monkeypatch, mock_session):
        """Test when skill doesn't exist."""
        session, query = mock_session

        mock_first = MagicMock()
        mock_first.return_value = None
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)

        result = get_skill_with_tool_names('nonexistent')

        assert result is None

    def test_get_skill_with_tool_names_found(self, monkeypatch, mock_session):
        """Test when skill exists with tool names."""
        session, query = mock_session

        skill = MockSkillInfo(skill_id=5, skill_name='my_skill')

        mock_first = MagicMock()
        mock_first.return_value = skill
        mock_filter = MagicMock()
        mock_filter.first = mock_first
        query.filter.return_value = mock_filter

        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = session
        mock_ctx.__exit__.return_value = None
        monkeypatch.setattr(
            "backend.database.skill_db.get_db_session", lambda: mock_ctx)
        monkeypatch.setattr(
            "backend.database.skill_db._get_tool_ids",
            lambda s, skill_id: [1, 2]
        )
        monkeypatch.setattr(
            "backend.database.skill_db.get_tool_names_by_ids",
            lambda s, ids: ['tool_a', 'tool_b']
        )

        result = get_skill_with_tool_names('my_skill')

        assert result is not None
        assert result['skill_id'] == 5
        assert result['tool_ids'] == [1, 2]
        assert result['allowed_tools'] == ['tool_a', 'tool_b']


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
