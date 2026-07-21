import asyncio
import sys
import types
import pytest
from unittest.mock import patch, MagicMock
from contextlib import contextmanager

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
consts_mock.const.AGENT_PROMPTS_HIDDEN_FLAG = "prompts_hidden"
consts_mock.const.ASSET_OWNER_ROLE = "ASSET_OWNER"
consts_mock.const.ASSET_OWNER_TENANT_ID = "asset_owner_tenant_id"
consts_mock.const.ENABLE_ASSET_OWNER_ROLE = False
consts_mock.const.PERMISSION_EDIT = "EDIT"
consts_mock.const.PERMISSION_READ = "READ_ONLY"

sys.modules['consts'] = consts_mock
sys.modules['consts.const'] = consts_mock.const

agent_runtime_mod = types.ModuleType("consts.agent_runtime")
agent_runtime_mod.normalize_agent_runtime_framework = (
    lambda value, default="smolagents": default if value is None else value
)
sys.modules['consts.agent_runtime'] = agent_runtime_mod

consts_exceptions_mod = types.ModuleType("consts.exceptions")


class ValidationError(Exception):
    pass


class AppException(Exception):
    def __init__(self, error_code, message, details=None):
        super().__init__(message)
        self.error_code = error_code
        self.details = details


consts_exceptions_mod.ValidationError = ValidationError
consts_exceptions_mod.AppException = AppException
sys.modules['consts.exceptions'] = consts_exceptions_mod

error_code_mod = types.ModuleType("consts.error_code")
error_code_mod.ErrorCode = type(
    "ErrorCode",
    (),
    {
        "AGENT_RUNTIME_FRAMEWORK_REQUIRED": "AGENT_RUNTIME_FRAMEWORK_REQUIRED",
        "AGENT_RUNTIME_FRAMEWORK_MISMATCH": "AGENT_RUNTIME_FRAMEWORK_MISMATCH",
        "AGENT_RUNTIME_FRAMEWORK_IMMUTABLE": "AGENT_RUNTIME_FRAMEWORK_IMMUTABLE",
    },
)
sys.modules['consts.error_code'] = error_code_mod

# Mock consts.agent_unavailable_reasons
agent_unavailable_reasons_mock = MagicMock()
agent_unavailable_reasons_mock.AgentUnavailableReason = type('AgentUnavailableReason', (), {
    'DUPLICATE_NAME': 'duplicate_name',
    'DUPLICATE_DISPLAY_NAME': 'duplicate_display_name',
    'MODEL_NOT_CONFIGURED': 'model_not_configured',
    'MODEL_UNAVAILABLE': 'model_unavailable',
    'TOOL_UNAVAILABLE': 'tool_unavailable',
    'ALL_TOOLS_DISABLED': 'all_tools_disabled',
    'AGENT_NOT_FOUND': 'agent_not_found',
    'all_reasons': classmethod(lambda cls: [
        'duplicate_name', 'duplicate_display_name', 'model_not_configured',
        'model_unavailable', 'tool_unavailable', 'all_tools_disabled', 'agent_not_found'
    ]),
    'is_valid_reason': classmethod(lambda cls, reason: reason in [
        'duplicate_name', 'duplicate_display_name', 'model_not_configured',
        'model_unavailable', 'tool_unavailable', 'all_tools_disabled', 'agent_not_found'
    ]),
})()
sys.modules['consts.agent_unavailable_reasons'] = agent_unavailable_reasons_mock

# Mock utils module
utils_mock = MagicMock()
utils_mock.auth_utils = MagicMock()
utils_mock.auth_utils.get_current_user_id_from_token = MagicMock(return_value="test_user_id")
utils_mock.str_utils = MagicMock()
utils_mock.str_utils.convert_string_to_list = MagicMock(
    side_effect=lambda s: [] if not s else [int(x) for x in str(s).split(",") if str(x).strip().isdigit()]
)
utils_mock.skill_params_utils = MagicMock()
utils_mock.skill_params_utils.strip_params_comments_for_db = MagicMock(
    side_effect=lambda x: x if x is not None else {}
)

sys.modules['utils'] = utils_mock
sys.modules['utils.auth_utils'] = utils_mock.auth_utils
sys.modules['utils.str_utils'] = utils_mock.str_utils
sys.modules['utils.skill_params_utils'] = utils_mock.skill_params_utils

# Mock boto3
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

# Mock database.client
client_mock = MagicMock()
client_mock.MinioClient = MagicMock()
client_mock.PostgresClient = MagicMock()
client_mock.db_client = MagicMock()
client_mock.get_db_session = MagicMock()
client_mock.as_dict = MagicMock()

sys.modules['database.client'] = client_mock
sys.modules['backend.database.client'] = client_mock

# Mock database.db_models
db_models_mock = MagicMock()
db_models_mock.AgentInfo = MagicMock()
db_models_mock.ToolInstance = MagicMock()
db_models_mock.AgentRelation = MagicMock()
db_models_mock.AgentVersion = MagicMock()
db_models_mock.SkillInfo = MagicMock()
db_models_mock.SkillToolRelation = MagicMock()
db_models_mock.SkillInstance = MagicMock()
db_models_mock.ToolInfo = MagicMock()

sys.modules['database.db_models'] = db_models_mock
sys.modules['backend.database.db_models'] = db_models_mock

# Mock database.agent_version_db
agent_version_db_mock = MagicMock()
agent_version_db_mock.SOURCE_TYPE_NORMAL = "NORMAL"
agent_version_db_mock.SOURCE_TYPE_ROLLBACK = "ROLLBACK"
agent_version_db_mock.STATUS_RELEASED = "RELEASED"
agent_version_db_mock.STATUS_DISABLED = "DISABLED"
agent_version_db_mock.STATUS_ARCHIVED = "ARCHIVED"

sys.modules['database.agent_version_db'] = agent_version_db_mock
sys.modules['backend.database.agent_version_db'] = agent_version_db_mock

# Mock database.model_management_db
model_management_db_mock = MagicMock()
# Default pass-through behavior for get_valid_model_ids
model_management_db_mock.get_valid_model_ids = MagicMock(
    side_effect=lambda model_ids, tenant_id: model_ids
)
sys.modules['database.model_management_db'] = model_management_db_mock
sys.modules['backend.database.model_management_db'] = model_management_db_mock

# Mock database.agent_db (for list_published_agents_impl)
agent_db_mock = MagicMock()
agent_db_mock.search_agent_info_by_agent_id.return_value = {
    "runtime_framework": "smolagents"
}
sys.modules['database.agent_db'] = agent_db_mock
sys.modules['backend.database.agent_db'] = agent_db_mock

# Mock database.skill_db
skill_db_mock = MagicMock()
skill_db_mock.query_skill_instances_by_agent_id = MagicMock(return_value=[])
skill_db_mock.strip_params_comments_for_db = MagicMock(side_effect=lambda x: x)
sys.modules['database.skill_db'] = skill_db_mock
sys.modules['backend.database.skill_db'] = skill_db_mock

# Mock services.agent_service (for list_published_agents_impl)
agent_service_mock = MagicMock()
agent_service_mock.CAN_EDIT_ALL_USER_ROLES = ["ADMIN", "SUPER_ADMIN"]
agent_service_mock.PERMISSION_EDIT = "EDIT"
agent_service_mock.PERMISSION_READ = "READ"
sys.modules['services.agent_service'] = agent_service_mock
sys.modules['backend.services.agent_service'] = agent_service_mock

# Mock database module
database_mock = MagicMock()
database_mock.skill_db = skill_db_mock
database_mock.agent_db = agent_db_mock
sys.modules['database'] = database_mock
sys.modules['backend.database'] = database_mock

# Mock database.a2a_agent_db
a2a_agent_db_mock = MagicMock()
a2a_agent_db_mock.create_server_agent = MagicMock()
a2a_agent_db_mock.get_server_agent_by_agent_id = MagicMock()
sys.modules['database.a2a_agent_db'] = a2a_agent_db_mock
sys.modules['backend.database.a2a_agent_db'] = a2a_agent_db_mock

# Now import the service module
import backend.services.agent_version_service as agent_version_service_module
from backend.services.agent_version_service import (
    publish_version_impl,
    get_version_list_impl,
    get_version_impl,
    get_version_detail_impl,
    rollback_version_impl,
    update_version_status_impl,
    update_version_impl,
    delete_version_impl,
    get_current_version_impl,
    compare_versions_impl,
    list_published_agents_impl,
    _check_version_snapshot_availability,
    _get_version_detail_or_draft,
    _remove_audit_fields_for_insert,
)


@pytest.fixture
def mock_agent_draft():
    """Mock agent draft data"""
    return {
        "agent_id": 1,
        "tenant_id": "tenant1",
        "version_no": 0,
        "name": "Test Agent",
        "description": "Test Description",
        "model_ids": [1],
        "business_logic_model_id": 2,
        "max_steps": 10,
        "duty_prompt": "Test prompt",
        "group_ids": "1,2",
        "create_time": "2023-01-01 12:00:00",
        "update_time": "2023-01-01 12:00:00",
        "created_by": "user1",
        "updated_by": "user1",
        "delete_flag": "N",
        "runtime_framework": "smolagents",
    }


@pytest.fixture
def mock_tools_draft():
    """Mock tools draft data"""
    return [
        {
            "tool_instance_id": 1,
            "tool_id": 1,
            "agent_id": 1,
            "tenant_id": "tenant1",
            "version_no": 0,
            "enabled": True,
        },
        {
            "tool_instance_id": 2,
            "tool_id": 2,
            "agent_id": 1,
            "tenant_id": "tenant1",
            "version_no": 0,
            "enabled": True,
        },
    ]


@pytest.fixture
def mock_relations_draft(monkeypatch):
    """Mock relations draft data"""
    monkeypatch.setattr(
        agent_version_service_module,
        "query_current_version_no",
        MagicMock(return_value=1),
    )
    return [
        {
            "id": 1,
            "parent_agent_id": 1,
            "selected_agent_id": 2,
            "tenant_id": "tenant1",
            "version_no": 0,
        }
    ]


@pytest.fixture
def mock_skills_draft():
    """Mock skills draft data"""
    return [
        {
            "skill_instance_id": 1,
            "skill_id": 1,
            "agent_id": 1,
            "tenant_id": "tenant1",
            "version_no": 0,
            "enabled": True,
        }
    ]


def test_publish_version_rejects_mixed_framework_child_before_snapshot_write(monkeypatch):
    monkeypatch.setattr(
        agent_version_service_module,
        "query_agent_draft",
        MagicMock(
            return_value=(
                {"agent_id": 1, "runtime_framework": "openjiuwen"},
                [],
                [{"selected_agent_id": 2}],
            )
        ),
    )
    monkeypatch.setattr(
        agent_version_service_module,
        "query_current_version_no",
        MagicMock(return_value=3),
    )
    monkeypatch.setattr(
        agent_version_service_module,
        "search_agent_info_by_agent_id",
        MagicMock(return_value={"runtime_framework": "smolagents"}),
    )
    insert_snapshot = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_agent_snapshot", insert_snapshot)

    with pytest.raises(AppException) as exc_info:
        publish_version_impl(1, "tenant1", "user1")

    assert exc_info.value.error_code == "AGENT_RUNTIME_FRAMEWORK_MISMATCH"
    insert_snapshot.assert_not_called()


def test_rollback_rejects_snapshot_that_would_change_framework(monkeypatch):
    monkeypatch.setattr(
        agent_version_service_module,
        "search_version_by_version_no",
        MagicMock(return_value={"version_name": "V1"}),
    )
    monkeypatch.setattr(
        agent_version_service_module,
        "query_agent_snapshot",
        MagicMock(return_value=({"runtime_framework": "openjiuwen"}, [], [])),
    )
    monkeypatch.setattr(
        agent_version_service_module,
        "query_agent_draft",
        MagicMock(return_value=({"runtime_framework": "smolagents"}, [], [])),
    )
    restore = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "restore_agent_draft", restore)

    with pytest.raises(AppException) as exc_info:
        rollback_version_impl(1, "tenant1", 1)

    assert exc_info.value.error_code == "AGENT_RUNTIME_FRAMEWORK_IMMUTABLE"
    restore.assert_not_called()


def test_publish_version_impl_success(monkeypatch, mock_agent_draft, mock_tools_draft, mock_relations_draft, mock_skills_draft):
    """Test successfully publishing a version"""
    # Mock query_agent_draft
    mock_query_draft = MagicMock(return_value=(mock_agent_draft, mock_tools_draft, mock_relations_draft))
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)

    # Mock get_next_version_no
    mock_get_next = MagicMock(return_value=1)
    monkeypatch.setattr(agent_version_service_module, "get_next_version_no", mock_get_next)

    # Mock insert functions
    mock_insert_agent = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_agent_snapshot", mock_insert_agent)
    mock_insert_tool = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_tool_snapshot", mock_insert_tool)
    mock_insert_relation = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_relation_snapshot", mock_insert_relation)
    mock_insert_skill = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_skill_snapshot", mock_insert_skill)

    # Mock insert_version
    mock_insert_version = MagicMock(return_value=100)
    monkeypatch.setattr(agent_version_service_module, "insert_version", mock_insert_version)

    # Mock update_agent_current_version
    mock_update_current = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "update_agent_current_version", mock_update_current)

    # Mock skill_db query_skill_instances_by_agent_id
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=mock_skills_draft))

    result = publish_version_impl(
        agent_id=1,
        tenant_id="tenant1",
        user_id="user1",
        version_name="v1.0",
        release_note="Initial release",
    )

    assert result["version_no"] == 1
    assert result["id"] == 100
    assert "message" in result
    mock_insert_agent.assert_called_once()
    assert mock_insert_tool.call_count == 2
    assert mock_insert_relation.call_count == 1
    relation_snapshot = mock_insert_relation.call_args[0][0]
    assert relation_snapshot["selected_agent_version_no"] == 1
    assert mock_insert_skill.call_count == 1

    # Verify updated_by is set to user_id on all snapshot types
    agent_snapshot = mock_insert_agent.call_args[0][0]
    assert agent_snapshot["updated_by"] == "user1"

    tool_snapshot_0 = mock_insert_tool.call_args_list[0][0][0]
    tool_snapshot_1 = mock_insert_tool.call_args_list[1][0][0]
    assert tool_snapshot_0["updated_by"] == "user1"
    assert tool_snapshot_1["updated_by"] == "user1"

    assert relation_snapshot["updated_by"] == "user1"

    skill_snapshot = mock_insert_skill.call_args[0][0]
    assert skill_snapshot["updated_by"] == "user1"


def test_publish_version_impl_unpublished_sub_agent(
    monkeypatch, mock_agent_draft, mock_tools_draft, mock_relations_draft, mock_skills_draft
):
    """Test publishing fails when a sub-agent has no published version"""
    mock_query_draft = MagicMock(
        return_value=(mock_agent_draft, mock_tools_draft, mock_relations_draft)
    )
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)
    monkeypatch.setattr(
        agent_version_service_module,
        "query_current_version_no",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(agent_version_service_module, "get_next_version_no", MagicMock(return_value=1))

    with pytest.raises(ValueError, match="Sub-agent 2 has no published version"):
        publish_version_impl(
            agent_id=1,
            tenant_id="tenant1",
            user_id="user1",
        )


def test_publish_version_impl_no_draft(monkeypatch):
    """Test publishing when draft doesn't exist"""
    mock_query_draft = MagicMock(return_value=(None, [], []))
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)

    with pytest.raises(ValueError, match="Agent draft not found"):
        publish_version_impl(
            agent_id=1,
            tenant_id="tenant1",
            user_id="user1",
        )


def test_publish_version_impl_with_rollback_source(monkeypatch, mock_agent_draft, mock_tools_draft, mock_relations_draft, mock_skills_draft):
    """Test publishing a version with rollback source type"""
    mock_query_draft = MagicMock(return_value=(mock_agent_draft, mock_tools_draft, mock_relations_draft))
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)
    mock_get_next = MagicMock(return_value=2)
    monkeypatch.setattr(agent_version_service_module, "get_next_version_no", mock_get_next)
    mock_insert_agent = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_agent_snapshot", mock_insert_agent)
    mock_insert_tool = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_tool_snapshot", mock_insert_tool)
    mock_insert_relation = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_relation_snapshot", mock_insert_relation)
    mock_insert_skill = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_skill_snapshot", mock_insert_skill)
    mock_insert_version = MagicMock(return_value=101)
    monkeypatch.setattr(agent_version_service_module, "insert_version", mock_insert_version)
    mock_update_current = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "update_agent_current_version", mock_update_current)
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=mock_skills_draft))

    result = publish_version_impl(
        agent_id=1,
        tenant_id="tenant1",
        user_id="user1",
        source_type="ROLLBACK",
        source_version_no=1,
    )

    assert result["version_no"] == 2
    # Verify insert_version was called with correct source_type
    call_args = mock_insert_version.call_args[0][0]
    assert call_args["source_type"] == "ROLLBACK"
    assert call_args["source_version_no"] == 1

    # Verify updated_by is set on all snapshot types
    agent_snapshot = mock_insert_agent.call_args[0][0]
    assert agent_snapshot["updated_by"] == "user1"
    for call in mock_insert_tool.call_args_list:
        assert call[0][0]["updated_by"] == "user1"
    assert mock_insert_relation.call_args[0][0]["updated_by"] == "user1"
    assert mock_insert_skill.call_args[0][0]["updated_by"] == "user1"


def test_publish_version_impl_with_skills(monkeypatch, mock_agent_draft, mock_tools_draft, mock_relations_draft, mock_skills_draft):
    """Test publishing version with skill instances"""
    mock_query_draft = MagicMock(return_value=(mock_agent_draft, mock_tools_draft, mock_relations_draft))
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)
    mock_get_next = MagicMock(return_value=3)
    monkeypatch.setattr(agent_version_service_module, "get_next_version_no", mock_get_next)
    mock_insert_agent = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_agent_snapshot", mock_insert_agent)
    mock_insert_tool = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_tool_snapshot", mock_insert_tool)
    mock_insert_relation = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_relation_snapshot", mock_insert_relation)
    mock_insert_skill = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_skill_snapshot", mock_insert_skill)
    mock_insert_version = MagicMock(return_value=102)
    monkeypatch.setattr(agent_version_service_module, "insert_version", mock_insert_version)
    mock_update_current = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "update_agent_current_version", mock_update_current)
    # Return skills with multiple items
    multiple_skills = [
        {"skill_instance_id": 1, "skill_id": 1, "enabled": True},
        {"skill_instance_id": 2, "skill_id": 2, "enabled": True},
        {"skill_instance_id": 3, "skill_id": 3, "enabled": False},
    ]
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=multiple_skills))

    result = publish_version_impl(
        agent_id=1,
        tenant_id="tenant1",
        user_id="user1",
    )

    assert result["version_no"] == 3
    assert mock_insert_skill.call_count == 3

    # Verify updated_by is set on all skill snapshots
    for i, call in enumerate(mock_insert_skill.call_args_list):
        skill_snapshot = call[0][0]
        assert skill_snapshot["updated_by"] == "user1"


def test_publish_version_impl_empty_tools_relations(monkeypatch, mock_agent_draft, mock_skills_draft):
    """Test publishing version with no tools or relations"""
    mock_query_draft = MagicMock(return_value=(mock_agent_draft, [], []))
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)
    mock_get_next = MagicMock(return_value=4)
    monkeypatch.setattr(agent_version_service_module, "get_next_version_no", mock_get_next)
    mock_insert_agent = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_agent_snapshot", mock_insert_agent)
    mock_insert_tool = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_tool_snapshot", mock_insert_tool)
    mock_insert_relation = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_relation_snapshot", mock_insert_relation)
    mock_insert_skill = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_skill_snapshot", mock_insert_skill)
    mock_insert_version = MagicMock(return_value=103)
    monkeypatch.setattr(agent_version_service_module, "insert_version", mock_insert_version)
    mock_update_current = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "update_agent_current_version", mock_update_current)
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=[]))

    result = publish_version_impl(
        agent_id=1,
        tenant_id="tenant1",
        user_id="user1",
    )

    assert result["version_no"] == 4
    mock_insert_agent.assert_called_once()
    mock_insert_tool.assert_not_called()
    mock_insert_relation.assert_not_called()
    mock_insert_skill.assert_not_called()


def test_get_version_list_impl_success(monkeypatch):
    """Test successfully getting version list"""
    mock_versions = [
        {"version_no": 2, "version_name": "v2.0"},
        {"version_no": 1, "version_name": "v1.0"},
    ]
    mock_query_list = MagicMock(return_value=mock_versions)
    monkeypatch.setattr(agent_version_service_module, "query_version_list", mock_query_list)

    result = get_version_list_impl(agent_id=1, tenant_id="tenant1")

    assert result["total"] == 2
    assert len(result["items"]) == 2
    assert result["items"][0]["version_no"] == 2


def test_get_version_list_impl_empty(monkeypatch):
    """Test getting version list when no versions exist"""
    mock_query_list = MagicMock(return_value=[])
    monkeypatch.setattr(agent_version_service_module, "query_version_list", mock_query_list)

    result = get_version_list_impl(agent_id=1, tenant_id="tenant1")

    assert result["total"] == 0
    assert result["items"] == []


def test_get_version_impl_success(monkeypatch):
    """Test successfully getting a version"""
    mock_version = {
        "version_no": 1,
        "version_name": "v1.0",
        "status": "RELEASED",
    }
    mock_search = MagicMock(return_value=mock_version)
    monkeypatch.setattr(agent_version_service_module, "search_version_by_version_no", mock_search)

    result = get_version_impl(agent_id=1, tenant_id="tenant1", version_no=1)

    assert result["version_no"] == 1
    assert result["version_name"] == "v1.0"


def test_get_version_detail_impl_success(monkeypatch):
    """Test successfully getting version detail"""
    mock_version = {
        "version_no": 1,
        "version_name": "v1.0",
        "status": "RELEASED",
        "release_note": "Test note",
        "source_type": "NORMAL",
        "source_version_no": None,
    }

    mock_agent_snapshot = {
        "agent_id": 1,
        "name": "Test Agent",
        "model_ids": [1],
        "business_logic_model_id": 2,
        "max_steps": 10,
        "description": "Test",
        "duty_prompt": "Test prompt",
        "group_ids": "1,2",
    }

    mock_tools_snapshot = [
        {"tool_id": 1, "enabled": True},
        {"tool_id": 2, "enabled": True},
    ]

    mock_relations_snapshot = [
        {"selected_agent_id": 2},
    ]

    mock_search = MagicMock(return_value=mock_version)
    monkeypatch.setattr(agent_version_service_module, "search_version_by_version_no", mock_search)
    mock_query_snapshot = MagicMock(
        return_value=(mock_agent_snapshot, mock_tools_snapshot, mock_relations_snapshot)
    )
    monkeypatch.setattr(agent_version_service_module, "query_agent_snapshot", mock_query_snapshot)

    mock_model_info = {"display_name": "Test Model"}
    mock_get_model = MagicMock(return_value=mock_model_info)
    monkeypatch.setattr(agent_version_service_module, "get_model_by_model_id", mock_get_model)

    # Mock skill_db query_skill_instances_by_agent_id
    mock_skills = [
        {"skill_instance_id": 1, "skill_id": 1, "enabled": True},
    ]
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=mock_skills))

    result = get_version_detail_impl(agent_id=1, tenant_id="tenant1", version_no=1)

    assert result["name"] == "Test Agent"
    assert result["version"]["version_name"] == "v1.0"
    assert len(result["tools"]) == 2
    assert result["sub_agent_id_list"] == [2]
    assert result["model_name"] == "Test Model"
    assert "is_available" in result
    assert "unavailable_reasons" in result
    assert "skills" in result
    assert len(result["skills"]) == 1


def test_get_version_detail_impl_version_not_found(monkeypatch):
    """Test getting version detail when version doesn't exist"""
    mock_search = MagicMock(return_value=None)
    monkeypatch.setattr(agent_version_service_module, "search_version_by_version_no", mock_search)

    with pytest.raises(ValueError, match="Version 1 not found"):
        get_version_detail_impl(agent_id=1, tenant_id="tenant1", version_no=1)


def test_get_version_detail_impl_snapshot_not_found(monkeypatch):
    """Test getting version detail when snapshot doesn't exist"""
    mock_version = {"version_no": 1}
    mock_search = MagicMock(return_value=mock_version)
    monkeypatch.setattr(agent_version_service_module, "search_version_by_version_no", mock_search)
    mock_query_snapshot = MagicMock(return_value=(None, [], []))
    monkeypatch.setattr(agent_version_service_module, "query_agent_snapshot", mock_query_snapshot)

    with pytest.raises(ValueError, match="Agent snapshot for version 1 not found"):
        get_version_detail_impl(agent_id=1, tenant_id="tenant1", version_no=1)


def test_get_version_detail_impl_with_skills(monkeypatch):
    """Test version detail with skill instances"""
    mock_version = {
        "version_no": 1,
        "version_name": "v1.0",
        "status": "RELEASED",
        "release_note": "Test note",
        "source_type": "NORMAL",
        "source_version_no": None,
    }

    mock_agent_snapshot = {
        "agent_id": 1,
        "name": "Test Agent",
        "model_ids": [1],
        "business_logic_model_id": 0,
        "max_steps": 10,
        "description": "Test",
        "duty_prompt": "Test prompt",
        "group_ids": "1,2",
    }

    mock_tools_snapshot = [
        {"tool_id": 1, "enabled": True},
    ]

    mock_relations_snapshot = []

    mock_search = MagicMock(return_value=mock_version)
    monkeypatch.setattr(agent_version_service_module, "search_version_by_version_no", mock_search)
    mock_query_snapshot = MagicMock(
        return_value=(mock_agent_snapshot, mock_tools_snapshot, mock_relations_snapshot)
    )
    monkeypatch.setattr(agent_version_service_module, "query_agent_snapshot", mock_query_snapshot)

    mock_get_model = MagicMock(return_value=None)
    monkeypatch.setattr(agent_version_service_module, "get_model_by_model_id", mock_get_model)

    # Skills with some disabled
    mock_skills = [
        {"skill_instance_id": 1, "skill_id": 1, "enabled": True},
        {"skill_instance_id": 2, "skill_id": 2, "enabled": False},
    ]
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=mock_skills))

    result = get_version_detail_impl(agent_id=1, tenant_id="tenant1", version_no=1)

    assert len(result["skills"]) == 1  # Only enabled skills


def test_get_version_detail_impl_no_model(monkeypatch):
    """Test version detail when model_id is 0 (no model configured)"""
    mock_version = {
        "version_no": 1,
        "version_name": "v1.0",
        "status": "RELEASED",
        "release_note": "Test note",
        "source_type": "NORMAL",
        "source_version_no": None,
    }

    mock_agent_snapshot = {
        "agent_id": 1,
        "name": "Test Agent",
        "model_ids": [],  # No model configured (empty list)
        "business_logic_model_id": 0,
        "max_steps": 10,
        "description": "Test",
        "duty_prompt": "Test prompt",
        "group_ids": None,  # group_ids is None -> empty list
    }

    mock_tools_snapshot = []
    mock_relations_snapshot = []

    mock_search = MagicMock(return_value=mock_version)
    monkeypatch.setattr(agent_version_service_module, "search_version_by_version_no", mock_search)
    mock_query_snapshot = MagicMock(
        return_value=(mock_agent_snapshot, mock_tools_snapshot, mock_relations_snapshot)
    )
    monkeypatch.setattr(agent_version_service_module, "query_agent_snapshot", mock_query_snapshot)
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=[]))

    result = get_version_detail_impl(agent_id=1, tenant_id="tenant1", version_no=1)

    assert result["model_name"] is None
    assert result["model_names"] == []
    assert result["business_logic_model_name"] is None
    assert result["group_ids"] == []  # group_ids is None -> empty list


def test_rollback_version_impl_success(monkeypatch):
    """Test successfully rolling back to a version"""
    mock_version = {
        "version_no": 1,
        "version_name": "v1.0",
    }

    # Assign the mock to a variable
    mock_search = MagicMock(return_value=mock_version)
    monkeypatch.setattr(
        agent_version_service_module,
        "search_version_by_version_no",
        mock_search
    )

    # Assign the mock to a variable
    mock_query_snapshot = MagicMock(return_value=(
        {"agent_id": 1, "name": "Test Agent"},
        [],
        [],
    ))
    monkeypatch.setattr(
        agent_version_service_module,
        "query_agent_snapshot",
        mock_query_snapshot
    )

    # Mock query_agent_draft - THIS WAS MISSING
    mock_query_draft = MagicMock(return_value=(
        {"agent_id": 1, "version_no": 0, "name": "Test Agent Draft"},
        [],
        [],
    ))
    monkeypatch.setattr(
        agent_version_service_module,
        "query_agent_draft",
        mock_query_draft
    )

    # mock restore
    mock_restore = MagicMock()
    monkeypatch.setattr(
        agent_version_service_module,
        "restore_agent_draft",
        mock_restore
    )

    # mock skills
    monkeypatch.setattr(
        skill_db_mock,
        "query_skill_instances_by_agent_id",
        MagicMock(return_value=[])
    )

    result = rollback_version_impl(
        agent_id=1,
        tenant_id="tenant1",
        target_version_no=1,
    )

    assert result["version_no"] == 1
    assert result["version_name"] == "v1.0"
    assert "Successfully rolled back" in result["message"]
    
    mock_search.assert_called_once_with(1, "tenant1", 1)
    mock_query_snapshot.assert_called_once_with(1, "tenant1", 1)
    mock_query_draft.assert_called_once_with(1, "tenant1")  # Verify it was called
    mock_restore.assert_called_once()
    

def test_rollback_version_impl_version_not_found(monkeypatch):
    """Test rolling back when version doesn't exist"""
    mock_search = MagicMock(return_value=None)
    monkeypatch.setattr(agent_version_service_module, "search_version_by_version_no", mock_search)

    with pytest.raises(ValueError, match="Version 999 not found"):
        rollback_version_impl(
            agent_id=1,
            tenant_id="tenant1",
            target_version_no=999,
        )


def test_rollback_version_impl_snapshot_not_found(monkeypatch):

    monkeypatch.setattr(
        agent_version_service_module,
        "search_version_by_version_no",
        MagicMock(return_value={"version_no": 1})
    )

    monkeypatch.setattr(
        agent_version_service_module,
        "query_agent_snapshot",
        MagicMock(return_value=(None, [], []))
    )

    with pytest.raises(
        ValueError,
        match="Agent snapshot for version 1 not found"
    ):
        rollback_version_impl(
            agent_id=1,
            tenant_id="tenant1",
            target_version_no=1,
        )
        
        
def test_rollback_version_impl_draft_not_found(monkeypatch):
    """Test rolling back when draft doesn't exist"""
    mock_version = {"version_no": 1}
    mock_search = MagicMock(return_value=mock_version)
    monkeypatch.setattr(agent_version_service_module, "search_version_by_version_no", mock_search)
    mock_query_snapshot = MagicMock(
        return_value=(
            {"agent_id": 1, "version_no": 1, "name": "Test Agent"},
            [],
            [],
        )
    )
    monkeypatch.setattr(agent_version_service_module, "query_agent_snapshot", mock_query_snapshot)
    mock_query_draft = MagicMock(return_value=(None, [], []))
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft) 
    
    with pytest.raises(ValueError, match="Agent draft not found"):
        rollback_version_impl(
            agent_id=1,
            tenant_id="tenant1",
            target_version_no=1,
        )


def test_update_version_status_impl_success(monkeypatch):
    """Test successfully updating version status"""
    mock_update_status = MagicMock(return_value=1)
    monkeypatch.setattr(agent_version_service_module, "update_version_status", mock_update_status)

    result = update_version_status_impl(
        agent_id=1,
        tenant_id="tenant1",
        user_id="user1",
        version_no=1,
        status="DISABLED",
    )

    assert "message" in result
    mock_update_status.assert_called_once()


def test_update_version_status_impl_invalid_status(monkeypatch):
    """Test updating status with invalid status value"""
    with pytest.raises(ValueError, match="Invalid status"):
        update_version_status_impl(
            agent_id=1,
            tenant_id="tenant1",
            user_id="user1",
            version_no=1,
            status="INVALID",
        )


def test_update_version_status_impl_archived_status(monkeypatch):
    """Test updating status to ARCHIVED"""
    mock_update_status = MagicMock(return_value=1)
    monkeypatch.setattr(agent_version_service_module, "update_version_status", mock_update_status)

    result = update_version_status_impl(
        agent_id=1,
        tenant_id="tenant1",
        user_id="user1",
        version_no=1,
        status="ARCHIVED",
    )

    assert "message" in result
    mock_update_status.assert_called_once()
    # Verify ARCHIVED status is passed
    call_kwargs = mock_update_status.call_args[1]
    assert call_kwargs["status"] == "ARCHIVED"


def test_update_version_status_impl_not_found(monkeypatch):
    """Test updating status when version doesn't exist"""
    mock_update_status = MagicMock(return_value=0)
    monkeypatch.setattr(agent_version_service_module, "update_version_status", mock_update_status)

    with pytest.raises(ValueError, match="Version 999 not found"):
        update_version_status_impl(
            agent_id=1,
            tenant_id="tenant1",
            user_id="user1",
            version_no=999,
            status="DISABLED",
        )


def test_update_version_impl_success(monkeypatch):
    """Test successfully updating version metadata"""
    mock_version = {"version_no": 1, "version_name": "v1.0"}
    mock_search = MagicMock(return_value=mock_version)
    monkeypatch.setattr(agent_version_service_module, "search_version_by_version_no", mock_search)
    mock_update = MagicMock(return_value=1)
    monkeypatch.setattr(agent_version_service_module, "update_version", mock_update)

    result = update_version_impl(
        agent_id=1,
        tenant_id="tenant1",
        user_id="user1",
        version_no=1,
        version_name="Updated Version Name",
        release_note="Updated release note",
    )

    assert "message" in result
    assert result["version_no"] == 1
    mock_update.assert_called_once()


def test_update_version_impl_version_not_found(monkeypatch):
    """Test updating version when version doesn't exist"""
    mock_search = MagicMock(return_value=None)
    monkeypatch.setattr(agent_version_service_module, "search_version_by_version_no", mock_search)

    with pytest.raises(ValueError, match="Version 999 not found"):
        update_version_impl(
            agent_id=1,
            tenant_id="tenant1",
            user_id="user1",
            version_no=999,
            version_name="Non-existent version",
        )


def test_update_version_impl_no_changes(monkeypatch):
    """Test updating version with no actual changes"""
    mock_version = {"version_no": 1, "version_name": "v1.0"}
    mock_search = MagicMock(return_value=mock_version)
    monkeypatch.setattr(agent_version_service_module, "search_version_by_version_no", mock_search)
    mock_update = MagicMock(return_value=0)
    monkeypatch.setattr(agent_version_service_module, "update_version", mock_update)

    with pytest.raises(ValueError, match="No changes to update"):
        update_version_impl(
            agent_id=1,
            tenant_id="tenant1",
            user_id="user1",
            version_no=1,
        )


def test_delete_version_impl_success(monkeypatch):
    """Test successfully deleting a version"""
    mock_version = {"version_no": 2}
    mock_search = MagicMock(return_value=mock_version)
    monkeypatch.setattr(agent_version_service_module, "search_version_by_version_no", mock_search)
    mock_query_current = MagicMock(return_value=3)
    monkeypatch.setattr(agent_version_service_module, "query_current_version_no", mock_query_current)
    mock_delete_version = MagicMock(return_value=1)
    monkeypatch.setattr(agent_version_service_module, "delete_version", mock_delete_version)
    mock_delete_agent = MagicMock(return_value=1)
    monkeypatch.setattr(agent_version_service_module, "delete_agent_snapshot", mock_delete_agent)
    mock_delete_tool = MagicMock(return_value=2)
    monkeypatch.setattr(agent_version_service_module, "delete_tool_snapshot", mock_delete_tool)
    mock_delete_relation = MagicMock(return_value=1)
    monkeypatch.setattr(agent_version_service_module, "delete_relation_snapshot", mock_delete_relation)
    mock_delete_skill = MagicMock(return_value=1)
    monkeypatch.setattr(agent_version_service_module, "delete_skill_snapshot", mock_delete_skill)

    result = delete_version_impl(
        agent_id=1,
        tenant_id="tenant1",
        user_id="user1",
        version_no=2,
    )

    assert "deleted successfully" in result["message"]
    mock_delete_version.assert_called_once()
    mock_delete_agent.assert_called_once()
    mock_delete_tool.assert_called_once()
    mock_delete_relation.assert_called_once()
    mock_delete_skill.assert_called_once()


def test_delete_version_impl_delete_version_returns_zero(monkeypatch):
    """Test deleting version when delete_version returns 0 (line 435)"""
    mock_version = {"version_no": 2}
    mock_search = MagicMock(return_value=mock_version)
    monkeypatch.setattr(agent_version_service_module, "search_version_by_version_no", mock_search)
    mock_query_current = MagicMock(return_value=3)
    monkeypatch.setattr(agent_version_service_module, "query_current_version_no", mock_query_current)
    mock_delete_version = MagicMock(return_value=0)  # Returns 0 - triggers line 435
    monkeypatch.setattr(agent_version_service_module, "delete_version", mock_delete_version)

    with pytest.raises(ValueError, match="Version 2 not found"):
        delete_version_impl(
            agent_id=1,
            tenant_id="tenant1",
            user_id="user1",
            version_no=2,
        )


def test_delete_version_impl_version_not_found(monkeypatch):
    """Test deleting when version doesn't exist"""
    mock_search = MagicMock(return_value=None)
    monkeypatch.setattr(agent_version_service_module, "search_version_by_version_no", mock_search)

    with pytest.raises(ValueError, match="Version 999 not found"):
        delete_version_impl(
            agent_id=1,
            tenant_id="tenant1",
            user_id="user1",
            version_no=999,
        )


def test_delete_version_impl_current_version(monkeypatch):
    """Test deleting current published version (should fail)"""
    mock_version = {"version_no": 1}
    mock_search = MagicMock(return_value=mock_version)
    monkeypatch.setattr(agent_version_service_module, "search_version_by_version_no", mock_search)
    mock_query_current = MagicMock(return_value=1)
    monkeypatch.setattr(agent_version_service_module, "query_current_version_no", mock_query_current)

    with pytest.raises(ValueError, match="Cannot delete the current published version"):
        delete_version_impl(
            agent_id=1,
            tenant_id="tenant1",
            user_id="user1",
            version_no=1,
        )


def test_delete_version_impl_draft_version(monkeypatch):
    """Test deleting draft version (should fail)"""
    mock_version = {"version_no": 0}
    mock_search = MagicMock(return_value=mock_version)
    monkeypatch.setattr(agent_version_service_module, "search_version_by_version_no", mock_search)

    with pytest.raises(ValueError, match="Cannot delete draft version"):
        delete_version_impl(
            agent_id=1,
            tenant_id="tenant1",
            user_id="user1",
            version_no=0,
        )


def test_get_current_version_impl_success(monkeypatch):
    """Test successfully getting current version"""
    mock_query_current = MagicMock(return_value=5)
    monkeypatch.setattr(agent_version_service_module, "query_current_version_no", mock_query_current)
    mock_version = {
        "version_no": 5,
        "version_name": "v5.0",
        "status": "RELEASED",
        "source_type": "NORMAL",
        "source_version_no": None,
        "release_note": "Test note",
        "created_by": "user1",
        "create_time": "2023-01-01 12:00:00",
    }
    mock_search = MagicMock(return_value=mock_version)
    monkeypatch.setattr(agent_version_service_module, "search_version_by_version_no", mock_search)

    result = get_current_version_impl(agent_id=1, tenant_id="tenant1")

    assert result["version_no"] == 5
    assert result["version_name"] == "v5.0"
    assert result["status"] == "RELEASED"


def test_get_current_version_impl_no_published_version(monkeypatch):
    """Test getting current version when none exists"""
    mock_query_current = MagicMock(return_value=None)
    monkeypatch.setattr(agent_version_service_module, "query_current_version_no", mock_query_current)

    with pytest.raises(ValueError, match="No published version"):
        get_current_version_impl(agent_id=1, tenant_id="tenant1")


def test_get_current_version_impl_version_not_found(monkeypatch):
    """Test getting current version when version metadata doesn't exist"""
    mock_query_current = MagicMock(return_value=5)
    monkeypatch.setattr(agent_version_service_module, "query_current_version_no", mock_query_current)
    mock_search = MagicMock(return_value=None)
    monkeypatch.setattr(agent_version_service_module, "search_version_by_version_no", mock_search)

    with pytest.raises(ValueError, match="Version 5 not found"):
        get_current_version_impl(agent_id=1, tenant_id="tenant1")


def test_compare_versions_impl_success(monkeypatch):
    """Test successfully comparing two versions"""
    # Mock _get_version_detail_or_draft
    version_a = {
        "name": "Agent A",
        "model_ids": [1, 2],
        "model_names": ["Model A1", "Model A2"],
        "model_name": "Model A1",
        "max_steps": 10,
        "description": "Desc A",
        "duty_prompt": "Prompt A",
        "tools": [{"tool_id": 1}],
        "sub_agent_id_list": [2],
        "skills": [],
    }
    version_b = {
        "name": "Agent B",
        "model_ids": [3, 4],
        "model_names": ["Model B1", "Model B2"],
        "model_name": "Model B1",
        "max_steps": 20,
        "description": "Desc B",
        "duty_prompt": "Prompt B",
        "tools": [{"tool_id": 1}, {"tool_id": 2}],
        "sub_agent_id_list": [2, 3],
        "skills": [],
    }

    with patch('backend.services.agent_version_service._get_version_detail_or_draft') as mock_get_detail:
        mock_get_detail.side_effect = [version_a, version_b]

        result = compare_versions_impl(
            agent_id=1,
            tenant_id="tenant1",
            version_no_a=1,
            version_no_b=2,
        )

        assert "version_a" in result
        assert "version_b" in result
        assert "differences" in result
        assert len(result["differences"]) > 0
        # Check that differences are detected
        difference_fields = [d["field"] for d in result["differences"]]
        assert "name" in difference_fields
        assert "model_ids" in difference_fields
        assert "max_steps" in difference_fields
        assert "tools_count" in difference_fields


def test_compare_versions_impl_no_differences(monkeypatch):
    """Test comparing identical versions"""
    version = {
        "name": "Same Agent",
        "model_ids": [1, 2],
        "model_names": ["Model A", "Model B"],
        "model_name": "Model A",
        "max_steps": 10,
        "description": "Same Desc",
        "duty_prompt": "Same Prompt",
        "tools": [{"tool_id": 1}],
        "sub_agent_id_list": [2],
        "skills": [],
    }

    with patch('backend.services.agent_version_service._get_version_detail_or_draft') as mock_get_detail:
        mock_get_detail.side_effect = [version, version]

        result = compare_versions_impl(
            agent_id=1,
            tenant_id="tenant1",
            version_no_a=1,
            version_no_b=2,
        )

        assert len(result["differences"]) == 0


def test_compare_versions_impl_skills_count_difference(monkeypatch):
    """Test comparing versions with different skills count"""
    version_a = {
        "name": "Agent A",
        "model_ids": [1],
        "model_names": ["Model A"],
        "model_name": "Model A",
        "max_steps": 10,
        "description": "Desc A",
        "duty_prompt": "Prompt A",
        "tools": [],
        "sub_agent_id_list": [],
        "skills": [{"skill_id": 1}],
    }
    version_b = {
        "name": "Agent A",
        "model_ids": [1],
        "model_names": ["Model A"],
        "model_name": "Model A",
        "max_steps": 10,
        "description": "Desc A",
        "duty_prompt": "Prompt A",
        "tools": [],
        "sub_agent_id_list": [],
        "skills": [{"skill_id": 1}, {"skill_id": 2}],
    }

    with patch('backend.services.agent_version_service._get_version_detail_or_draft') as mock_get_detail:
        mock_get_detail.side_effect = [version_a, version_b]

        result = compare_versions_impl(
            agent_id=1,
            tenant_id="tenant1",
            version_no_a=1,
            version_no_b=2,
        )

        difference_fields = [d["field"] for d in result["differences"]]
        assert "skills_count" in difference_fields


def test_compare_versions_impl_sub_agents_count_difference(monkeypatch):
    """Test comparing versions with different sub_agents count"""
    version_a = {
        "name": "Agent A",
        "model_ids": [1],
        "model_names": ["Model A"],
        "model_name": "Model A",
        "max_steps": 10,
        "description": "Desc A",
        "duty_prompt": "Prompt A",
        "tools": [],
        "sub_agent_id_list": [1],
        "skills": [],
    }
    version_b = {
        "name": "Agent A",
        "model_ids": [1],
        "model_names": ["Model A"],
        "model_name": "Model A",
        "max_steps": 10,
        "description": "Desc A",
        "duty_prompt": "Prompt A",
        "tools": [],
        "sub_agent_id_list": [1, 2, 3],
        "skills": [],
    }

    with patch('backend.services.agent_version_service._get_version_detail_or_draft') as mock_get_detail:
        mock_get_detail.side_effect = [version_a, version_b]

        result = compare_versions_impl(
            agent_id=1,
            tenant_id="tenant1",
            version_no_a=1,
            version_no_b=2,
        )

        difference_fields = [d["field"] for d in result["differences"]]
        assert "sub_agents_count" in difference_fields


def test_check_version_snapshot_availability_success():
    """Test checking availability when agent is available"""
    agent_info = {
        "model_ids": [1],
    }
    tool_instances = [
        {"tool_id": 1, "enabled": True},
    ]

    is_available, reasons = _check_version_snapshot_availability(
        agent_id=1,
        tenant_id="tenant1",
        agent_info=agent_info,
        tool_instances=tool_instances,
    )

    assert is_available is True
    assert len(reasons) == 0


def test_check_version_snapshot_availability_no_agent():
    """Test checking availability when agent doesn't exist"""
    is_available, reasons = _check_version_snapshot_availability(
        agent_id=1,
        tenant_id="tenant1",
        agent_info=None,
        tool_instances=[],
    )

    assert is_available is False
    assert "agent_not_found" in reasons


def test_check_version_snapshot_availability_no_model():
    """Test checking availability when model is not configured"""
    agent_info = {
        "model_ids": [],
    }
    tool_instances = [{"tool_id": 1, "enabled": True}]

    is_available, reasons = _check_version_snapshot_availability(
        agent_id=1,
        tenant_id="tenant1",
        agent_info=agent_info,
        tool_instances=tool_instances,
    )

    assert is_available is False
    assert "model_not_configured" in reasons


def test_check_version_snapshot_availability_empty_model_ids():
    """Test checking availability when model_ids is empty list"""
    agent_info = {
        "model_ids": [],
    }
    tool_instances = [{"tool_id": 1, "enabled": True}]

    is_available, reasons = _check_version_snapshot_availability(
        agent_id=1,
        tenant_id="tenant1",
        agent_info=agent_info,
        tool_instances=tool_instances,
    )

    assert is_available is False
    assert "model_not_configured" in reasons


def test_check_version_snapshot_availability_no_model_ids_key():
    """Test checking availability when model_ids key is missing"""
    agent_info = {
        "name": "Test Agent",  # Other fields present, but model_ids is not
    }
    tool_instances = [{"tool_id": 1, "enabled": True}]

    is_available, reasons = _check_version_snapshot_availability(
        agent_id=1,
        tenant_id="tenant1",
        agent_info=agent_info,
        tool_instances=tool_instances,
    )

    assert is_available is False
    assert "model_not_configured" in reasons


def test_check_version_snapshot_availability_no_tools():
    """Test checking availability when no tools exist (should be available)"""
    agent_info = {"model_ids": [1]}

    is_available, reasons = _check_version_snapshot_availability(
        agent_id=1,
        tenant_id="tenant1",
        agent_info=agent_info,
        tool_instances=[],
    )

    # Having no tools configured is valid - availability should not be affected
    assert is_available is True
    assert "no_tools" not in reasons


def test_check_version_snapshot_availability_all_tools_disabled():
    """Test checking availability when all tools are disabled"""
    agent_info = {"model_ids": [1]}
    tool_instances = [
        {"tool_id": 1, "enabled": False},
        {"tool_id": 2, "enabled": False},
    ]

    is_available, reasons = _check_version_snapshot_availability(
        agent_id=1,
        tenant_id="tenant1",
        agent_info=agent_info,
        tool_instances=tool_instances,
    )

    assert is_available is False
    assert "all_tools_disabled" in reasons


def test_get_version_detail_or_draft_draft_version(monkeypatch):
    """Test getting draft version detail"""
    mock_agent_draft = {
        "agent_id": 1,
        "name": "Draft Agent",
        "model_ids": [1],
        "business_logic_model_id": 2,
        "group_ids": "1,2",
    }
    mock_tools_draft = [{"tool_id": 1}]
    mock_relations_draft = [{"selected_agent_id": 2}]
    mock_skills_draft = [{"skill_instance_id": 1, "skill_id": 1, "enabled": True}]

    mock_query_draft = MagicMock(
        return_value=(mock_agent_draft, mock_tools_draft, mock_relations_draft)
    )
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)
    mock_get_model = MagicMock(return_value={"display_name": "Test Model"})
    monkeypatch.setattr(agent_version_service_module, "get_model_by_model_id", mock_get_model)
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=mock_skills_draft))

    result = _get_version_detail_or_draft(agent_id=1, tenant_id="tenant1", version_no=0)

    assert result["name"] == "Draft Agent"
    assert result["version"]["version_name"] == "Draft"
    assert result["version"]["version_status"] == "DRAFT"
    assert len(result["tools"]) == 1
    assert result["sub_agent_id_list"] == [2]
    assert result["sub_agent_relations"] == [{"agent_id": 2, "version_no": None}]
    assert len(result["skills"]) == 1


def test_get_version_detail_or_draft_draft_version_no_skills(monkeypatch):
    """Test getting draft version detail with no skills"""
    mock_agent_draft = {
        "agent_id": 1,
        "name": "Draft Agent",
        "model_ids": [1],
        "business_logic_model_id": 0,
        "group_ids": "",
    }
    mock_tools_draft = []
    mock_relations_draft = []

    mock_query_draft = MagicMock(
        return_value=(mock_agent_draft, mock_tools_draft, mock_relations_draft)
    )
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)
    # model_info is None
    mock_get_model = MagicMock(return_value=None)
    monkeypatch.setattr(agent_version_service_module, "get_model_by_model_id", mock_get_model)
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=[]))

    result = _get_version_detail_or_draft(agent_id=1, tenant_id="tenant1", version_no=0)

    assert result["name"] == "Draft Agent"
    assert result["model_name"] is None
    assert result["model_names"] == []
    assert result["business_logic_model_name"] is None
    assert result["group_ids"] == []
    assert len(result["skills"]) == 0


def test_get_version_detail_or_draft_model_ids_empty(monkeypatch):
    """Test _get_version_detail_or_draft when model_ids is empty list"""
    mock_agent_draft = {
        "agent_id": 1,
        "name": "Draft Agent",
        "model_ids": [],
        "business_logic_model_id": None,
        "group_ids": None,
    }
    mock_tools_draft = []
    mock_relations_draft = []

    mock_query_draft = MagicMock(
        return_value=(mock_agent_draft, mock_tools_draft, mock_relations_draft)
    )
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)
    mock_get_model = MagicMock(return_value=None)
    monkeypatch.setattr(agent_version_service_module, "get_model_by_model_id", mock_get_model)
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=[]))

    result = _get_version_detail_or_draft(agent_id=1, tenant_id="tenant1", version_no=0)

    assert result["name"] == "Draft Agent"
    assert result["model_name"] is None
    assert result["model_names"] == []
    assert result["business_logic_model_name"] is None
    assert result["group_ids"] == []

    mock_query_draft = MagicMock(
        return_value=(mock_agent_draft, mock_tools_draft, mock_relations_draft)
    )
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)
    monkeypatch.setattr(agent_version_service_module, "get_model_by_model_id", MagicMock(return_value=None))
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=[]))

    result = _get_version_detail_or_draft(agent_id=1, tenant_id="tenant1", version_no=0)

    assert result["name"] == "Draft Agent"
    # Line 658: model_id is None -> else branch
    assert result["model_name"] is None
    # Line 665: business_logic_model_id is None -> else branch
    assert result["business_logic_model_name"] is None
    # Line 676: group_ids is None -> else branch
    assert result["group_ids"] == []


def test_get_version_detail_or_draft_draft_not_found(monkeypatch):
    """Test getting draft version detail when draft doesn't exist"""
    mock_query_draft = MagicMock(return_value=(None, [], []))
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)

    with pytest.raises(ValueError, match="Draft version not found"):
        _get_version_detail_or_draft(agent_id=1, tenant_id="tenant1", version_no=0)


def test_get_version_detail_or_draft_published_version(monkeypatch):
    """Test getting published version detail"""
    mock_version_detail = {
        "name": "Published Agent",
        "version": {"version_name": "v1.0"},
        "model_ids": [1],
        "business_logic_model_id": 2,
        "group_ids": "1,2",
        "tools": [],
        "sub_agent_id_list": [],
        "skills": [],
    }

    mock_get_detail = MagicMock(return_value=mock_version_detail)
    monkeypatch.setattr(agent_version_service_module, "get_version_detail_impl", mock_get_detail)
    mock_get_model = MagicMock(return_value={"display_name": "Test Model"})
    monkeypatch.setattr(agent_version_service_module, "get_model_by_model_id", mock_get_model)
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=[]))

    result = _get_version_detail_or_draft(agent_id=1, tenant_id="tenant1", version_no=1)

    assert result["name"] == "Published Agent"
    assert result["version"]["version_name"] == "v1.0"
    assert result["model_names"] == ["Test Model"]


def test_get_version_detail_or_draft_group_ids_as_list(monkeypatch):
    """Test _get_version_detail_or_draft when group_ids is already a list"""
    mock_agent_draft = {
        "agent_id": 1,
        "name": "Draft Agent",
        "model_ids": [1],
        "business_logic_model_id": 0,
        "group_ids": [1, 2, 3],  # Already a list
    }
    mock_tools_draft = []
    mock_relations_draft = []

    mock_query_draft = MagicMock(
        return_value=(mock_agent_draft, mock_tools_draft, mock_relations_draft)
    )
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)
    mock_get_model = MagicMock(return_value=None)
    monkeypatch.setattr(agent_version_service_module, "get_model_by_model_id", mock_get_model)
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=[]))

    result = _get_version_detail_or_draft(agent_id=1, tenant_id="tenant1", version_no=0)

    # Should keep it as a list
    assert result["group_ids"] == [1, 2, 3]


def test_remove_audit_fields_for_insert():
    """Test removing audit fields from data dict"""
    data = {
        "name": "Test",
        "create_time": "2023-01-01",
        "update_time": "2023-01-02",
        "created_by": "user1",
        "updated_by": "user2",
        "delete_flag": "N",
        "other_field": "keep",
    }

    _remove_audit_fields_for_insert(data)

    assert "name" in data
    assert "other_field" in data
    assert "create_time" not in data
    assert "update_time" not in data
    assert "created_by" in data
    assert data["created_by"] == "user1"
    assert "updated_by" in data
    assert data["updated_by"] == "user2"
    assert "delete_flag" not in data


def test_remove_audit_fields_for_insert_missing_fields():
    """Test removing audit fields when some fields are missing"""
    data = {
        "name": "Test",
        "other_field": "keep",
    }

    _remove_audit_fields_for_insert(data)

    assert "name" in data
    assert "other_field" in data
    assert "create_time" not in data
    assert "update_time" not in data


def test_list_published_agents_impl_success(monkeypatch):
    """Test successfully listing published agents"""
    # Mock dependencies
    agent_db_mock.query_all_agent_info_by_tenant_id = MagicMock(
        return_value=[
            {
                "agent_id": 1,
                "enabled": True,
                "current_version_no": 1,
                "group_ids": "1,2",
                "created_by": "user1",
                "name": "Test Agent",
                "display_name": "Test Agent",
                "description": "Test",
                "author": "Author",
                "is_new": False,
            }
        ]
    )

    agent_service_mock.get_user_tenant_by_user_id = MagicMock(
        return_value={"user_role": "ADMIN"}
    )
    agent_service_mock.query_group_ids_by_user = MagicMock(return_value=[1, 2])

    agent_version_db_mock.query_agent_snapshot = MagicMock(
        return_value=(
            {
                "agent_id": 1,
                "name": "Test Agent",
                "model_ids": [1],
                "description": "Test",
            },
            [{"tool_id": 1, "enabled": True}],
            [],
        )
    )

    agent_service_mock.check_agent_availability = MagicMock(
        return_value=(True, [])
    )
    agent_service_mock._apply_duplicate_name_availability_rules = MagicMock()
    agent_service_mock.get_model_by_model_id = MagicMock(
        return_value={"display_name": "Test Model", "model_name": "test_model"}
    )

    result = asyncio.run(list_published_agents_impl(tenant_id="tenant1", user_id="user1"))

    assert len(result) == 1
    assert result[0]["agent_id"] == 1
    assert result[0]["name"] == "Test Agent"
    assert result[0]["model_ids"] == [1]
    assert result[0]["model_names"] == ["Test Model"]


def test_list_published_agents_impl_no_published_version(monkeypatch):
    """Test listing when agent has no published version"""
    agent_db_mock.query_all_agent_info_by_tenant_id = MagicMock(
        return_value=[
            {
                "agent_id": 1,
                "enabled": True,
                "current_version_no": None,  # No published version
                "group_ids": "1,2",
            }
        ]
    )

    agent_service_mock.get_user_tenant_by_user_id = MagicMock(
        return_value={"user_role": "ADMIN"}
    )

    result = asyncio.run(list_published_agents_impl(tenant_id="tenant1", user_id="user1"))

    assert len(result) == 0  # Should be filtered out


def test_list_published_agents_impl_disabled_agent(monkeypatch):
    """Test listing when agent is disabled"""
    agent_db_mock.query_all_agent_info_by_tenant_id = MagicMock(
        return_value=[
            {
                "agent_id": 1,
                "enabled": False,  # Disabled
                "current_version_no": 1,
                "group_ids": "1,2",
            }
        ]
    )

    agent_service_mock.get_user_tenant_by_user_id = MagicMock(
        return_value={"user_role": "ADMIN"}
    )

    result = asyncio.run(list_published_agents_impl(tenant_id="tenant1", user_id="user1"))

    assert len(result) == 0  # Should be filtered out


def test_list_published_agents_impl_no_group_overlap(monkeypatch):
    """Test listing when agent has no group overlap with user"""
    agent_db_mock.query_all_agent_info_by_tenant_id = MagicMock(
        return_value=[
            {
                "agent_id": 1,
                "enabled": True,
                "current_version_no": 1,
                "group_ids": "5,6",  # Different groups
                "created_by": "user2",  # Different creator to test group filtering
                "name": "Test Agent",
            }
        ]
    )

    agent_service_mock.get_user_tenant_by_user_id = MagicMock(
        return_value={"user_role": "USER"}  # Not ADMIN
    )
    agent_service_mock.query_group_ids_by_user = MagicMock(return_value=[1, 2])  # Different groups

    # Mock query_agent_snapshot - though it should not be called since agent is filtered by groups
    agent_version_db_mock.query_agent_snapshot = MagicMock(
        return_value=({}, [], [])
    )

    result = asyncio.run(list_published_agents_impl(tenant_id="tenant1", user_id="user1"))

    assert len(result) == 0  # Should be filtered out


def test_list_published_agents_impl_snapshot_not_found(monkeypatch):
    """Test listing when published version snapshot doesn't exist"""
    agent_db_mock.query_all_agent_info_by_tenant_id = MagicMock(
        return_value=[
            {
                "agent_id": 1,
                "enabled": True,
                "current_version_no": 1,
                "group_ids": "1,2",
                "created_by": "user1",
                "name": "Test Agent",
            }
        ]
    )

    agent_service_mock.get_user_tenant_by_user_id = MagicMock(
        return_value={"user_role": "ADMIN"}
    )

    agent_version_db_mock.query_agent_snapshot = MagicMock(
        return_value=(None, [], [])  # Snapshot not found
    )

    result = asyncio.run(list_published_agents_impl(tenant_id="tenant1", user_id="user1"))

    assert len(result) == 0  # Should be filtered out


def test_list_published_agents_impl_user_with_groups(monkeypatch):
    """Test listing with non-admin user that has group permissions"""
    agent_db_mock.query_all_agent_info_by_tenant_id = MagicMock(
        return_value=[
            {
                "agent_id": 1,
                "enabled": True,
                "current_version_no": 1,
                "group_ids": "1,2",  # Matches user's groups
                "created_by": "user2",  # Different creator
                "name": "Test Agent",
                "display_name": "Test Agent",
                "description": "Test",
                "author": "Author",
            }
        ]
    )

    agent_service_mock.get_user_tenant_by_user_id = MagicMock(
        return_value={"user_role": "USER"}  # Not ADMIN
    )
    agent_service_mock.query_group_ids_by_user = MagicMock(return_value=[1, 2])  # Has group access

    agent_version_db_mock.query_agent_snapshot = MagicMock(
        return_value=(
            {
                "agent_id": 1,
                "name": "Test Agent",
                "model_ids": [1],
                "description": "Test",
            },
            [{"tool_id": 1, "enabled": True}],
            [],
        )
    )

    agent_service_mock.check_agent_availability = MagicMock(
        return_value=(True, [])
    )
    agent_service_mock._apply_duplicate_name_availability_rules = MagicMock()
    agent_service_mock.get_model_by_model_id = MagicMock(
        return_value={"display_name": "Test Model", "model_name": "test_model"}
    )

    result = asyncio.run(list_published_agents_impl(tenant_id="tenant1", user_id="user1"))

    assert len(result) == 1
    # User should have READ_ONLY permission (not EDIT)
    assert result[0]["permission"] == "READ_ONLY"


def test_list_published_agents_impl_model_cache(monkeypatch):
    """Test listing with model cache - model info is fetched once and cached"""
    agent_db_mock.query_all_agent_info_by_tenant_id = MagicMock(
        return_value=[
            {
                "agent_id": 1,
                "enabled": True,
                "current_version_no": 1,
                "group_ids": "1,2",
                "created_by": "user1",
                "name": "Agent 1",
            },
            {
                "agent_id": 2,
                "enabled": True,
                "current_version_no": 2,
                "group_ids": "1,2",
                "created_by": "user1",
                "name": "Agent 2",
            },
        ]
    )

    agent_service_mock.get_user_tenant_by_user_id = MagicMock(
        return_value={"user_role": "ADMIN"}
    )

    # Both agents use the same model_ids
    agent_version_db_mock.query_agent_snapshot = MagicMock(
        side_effect=[
            ({"agent_id": 1, "name": "Agent 1", "model_ids": [1], "description": "Test"}, [], []),
            ({"agent_id": 2, "name": "Agent 2", "model_ids": [1], "description": "Test"}, [], []),
        ]
    )

    agent_service_mock.check_agent_availability = MagicMock(
        return_value=(True, [])
    )
    agent_service_mock._apply_duplicate_name_availability_rules = MagicMock()
    agent_service_mock.get_model_by_model_id = MagicMock(
        return_value={"display_name": "Test Model", "model_name": "test_model"}
    )

    result = asyncio.run(list_published_agents_impl(tenant_id="tenant1", user_id="user1"))

    assert len(result) == 2
    # Verify model info is used in results
    assert result[0]["model_ids"] == [1]
    assert result[1]["model_ids"] == [1]
    assert result[0]["model_names"] == ["Test Model"]
    assert result[1]["model_names"] == ["Test Model"]


def test_list_published_agents_impl_group_ids_query_exception(monkeypatch):
    """Test listing when group_ids query raises exception - exception is caught and logged"""
    agent_db_mock.query_all_agent_info_by_tenant_id = MagicMock(
        return_value=[
            {
                "agent_id": 1,
                "enabled": True,
                "current_version_no": 1,
                "group_ids": "",  # Empty group_ids - will be filtered by intersection check
                "created_by": "user2",  # Different creator to test group filtering
                "name": "Test Agent",
            }
        ]
    )

    agent_service_mock.get_user_tenant_by_user_id = MagicMock(
        return_value={"user_role": "USER"}  # Not ADMIN - triggers line 721
    )
    # query_group_ids_by_user raises exception - triggers line 724-728
    agent_service_mock.query_group_ids_by_user = MagicMock(
        side_effect=RuntimeError("Database error")
    )

    # Mock query_agent_snapshot - though it should not be called since agent is filtered by groups
    agent_version_db_mock.query_agent_snapshot = MagicMock(
        return_value=({}, [], [])
    )

    result = asyncio.run(list_published_agents_impl(tenant_id="tenant1", user_id="user1"))

    # Exception is caught, user_group_ids becomes empty set
    # Agent has empty group_ids, intersection is empty, agent is filtered out
    assert len(result) == 0


def test_list_published_agents_impl_is_available_false(monkeypatch):
    """Test listing with unavailable agents"""
    agent_db_mock.query_all_agent_info_by_tenant_id = MagicMock(
        return_value=[
            {
                "agent_id": 1,
                "enabled": True,
                "current_version_no": 1,
                "group_ids": "1,2",
                "created_by": "user1",
                "name": "Test Agent",
                "display_name": "Test Agent",
                "description": "Test",
            }
        ]
    )

    agent_service_mock.get_user_tenant_by_user_id = MagicMock(
        return_value={"user_role": "ADMIN"}
    )

    agent_version_db_mock.query_agent_snapshot = MagicMock(
        return_value=(
            {"agent_id": 1, "name": "Test Agent", "model_ids": [], "description": "Test"},
            [],
            [],
        )
    )

    # Agent is unavailable due to no model configured
    agent_service_mock.check_agent_availability = MagicMock(
        return_value=(False, ["model_not_configured"])
    )
    agent_service_mock._apply_duplicate_name_availability_rules = MagicMock()
    agent_service_mock.get_model_by_model_id = MagicMock(return_value=None)

    result = asyncio.run(list_published_agents_impl(tenant_id="tenant1", user_id="user1"))

    assert len(result) == 1
    assert result[0]["is_available"] is False
    assert "model_not_configured" in result[0]["unavailable_reasons"]


def test_list_published_agents_impl_exception_handling(monkeypatch):
    """Test exception handling in list_published_agents_impl"""
    # Mock query_all_agent_info_by_tenant_id to raise an exception
    test_exception = RuntimeError("Database connection failed")
    agent_db_mock.query_all_agent_info_by_tenant_id = MagicMock(
        side_effect=test_exception
    )

    # Mock get_user_tenant_by_user_id to avoid early exception
    agent_service_mock.get_user_tenant_by_user_id = MagicMock(
        return_value={"user_role": "ADMIN"}
    )

    # Verify that the exception is caught and re-raised as ValueError
    with pytest.raises(ValueError, match="Failed to list published agents: Database connection failed"):
        asyncio.run(list_published_agents_impl(tenant_id="tenant1", user_id="user1"))


def test_publish_version_impl_with_a2a_new_agent(monkeypatch, mock_agent_draft, mock_tools_draft, mock_relations_draft, mock_skills_draft):
    """Test publishing version with publish_as_a2a=True for a new A2A agent"""
    mock_query_draft = MagicMock(return_value=(mock_agent_draft, mock_tools_draft, mock_relations_draft))
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)
    mock_get_next = MagicMock(return_value=1)
    monkeypatch.setattr(agent_version_service_module, "get_next_version_no", mock_get_next)
    mock_insert_agent = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_agent_snapshot", mock_insert_agent)
    mock_insert_tool = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_tool_snapshot", mock_insert_tool)
    mock_insert_relation = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_relation_snapshot", mock_insert_relation)
    mock_insert_skill = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_skill_snapshot", mock_insert_skill)
    mock_insert_version = MagicMock(return_value=100)
    monkeypatch.setattr(agent_version_service_module, "insert_version", mock_insert_version)
    mock_update_current = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "update_agent_current_version", mock_update_current)
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=mock_skills_draft))

    # Mock A2A agent not existing
    a2a_agent_db_mock.get_server_agent_by_agent_id = MagicMock(return_value=None)
    # Mock create_server_agent returns a new agent
    a2a_agent_db_mock.create_server_agent = MagicMock(return_value={
        "agent_id": 1,
        "endpoint_id": "a2a_1_abc12345",
        "name": "Test Agent",
        "description": "Test Description",
        "version": "1",
        "streaming": False,
    })

    result = publish_version_impl(
        agent_id=1,
        tenant_id="tenant1",
        user_id="user1",
        publish_as_a2a=True,
    )

    assert result["version_no"] == 1
    assert result["id"] == 100
    assert "a2a_agent" in result
    assert "a2a_agent_card" in result
    assert result["a2a_agent"]["endpoint_id"] == "a2a_1_abc12345"
    assert result["a2a_agent_card"]["endpoint_id"] == "a2a_1_abc12345"
    assert result["a2a_agent_card"]["agent_card_url"] == "/nb/a2a/a2a_1_abc12345/.well-known/agent-card.json"
    assert result["a2a_agent_card"]["rest_endpoints"]["message_send"] == "/nb/a2a/a2a_1_abc12345/message:send"
    assert result["a2a_agent_card"]["rest_endpoints"]["message_stream"] == "/nb/a2a/a2a_1_abc12345/message:stream"
    assert result["a2a_agent_card"]["rest_endpoints"]["tasks_get"] == "/nb/a2a/a2a_1_abc12345/tasks/{task_id}"
    assert result["a2a_agent_card"]["jsonrpc_url"] == "/nb/a2a/a2a_1_abc12345/v1"
    assert result["a2a_agent_card"]["jsonrpc_methods"] == ["SendMessage", "SendStreamingMessage", "GetTask"]

    # Verify create_server_agent was called
    a2a_agent_db_mock.create_server_agent.assert_called_once_with(
        agent_id=1,
        user_id="user1",
        tenant_id="tenant1",
        name="Test Agent",
        description="Test Description",
        version="1",
    )

    # Verify updated_by is set on all snapshot types
    agent_snapshot = mock_insert_agent.call_args[0][0]
    assert agent_snapshot["updated_by"] == "user1"
    for call in mock_insert_tool.call_args_list:
        assert call[0][0]["updated_by"] == "user1"
    assert mock_insert_relation.call_args[0][0]["updated_by"] == "user1"
    assert mock_insert_skill.call_args[0][0]["updated_by"] == "user1"


def test_publish_version_impl_with_a2a_existing_agent(monkeypatch, mock_agent_draft, mock_tools_draft, mock_relations_draft, mock_skills_draft):
    """Test publishing version with publish_as_a2a=True for an existing A2A agent"""
    mock_query_draft = MagicMock(return_value=(mock_agent_draft, mock_tools_draft, mock_relations_draft))
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)
    mock_get_next = MagicMock(return_value=2)
    monkeypatch.setattr(agent_version_service_module, "get_next_version_no", mock_get_next)
    mock_insert_agent = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_agent_snapshot", mock_insert_agent)
    mock_insert_tool = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_tool_snapshot", mock_insert_tool)
    mock_insert_relation = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_relation_snapshot", mock_insert_relation)
    mock_insert_skill = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_skill_snapshot", mock_insert_skill)
    mock_insert_version = MagicMock(return_value=101)
    monkeypatch.setattr(agent_version_service_module, "insert_version", mock_insert_version)
    mock_update_current = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "update_agent_current_version", mock_update_current)
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=mock_skills_draft))

    # Mock A2A agent already exists
    existing_a2a = {
        "agent_id": 1,
        "endpoint_id": "a2a_1_existing",
        "name": "Test Agent",
        "description": "Test Description",
        "version": "0",
        "streaming": False,
    }
    a2a_agent_db_mock.get_server_agent_by_agent_id = MagicMock(return_value=existing_a2a)
    # Mock create_server_agent returns updated agent
    a2a_agent_db_mock.create_server_agent = MagicMock(return_value={
        "agent_id": 1,
        "endpoint_id": "a2a_1_existing",
        "name": "Test Agent",
        "description": "Test Description",
        "version": "2",
        "streaming": False,
    })

    result = publish_version_impl(
        agent_id=1,
        tenant_id="tenant1",
        user_id="user1",
        publish_as_a2a=True,
    )

    assert result["version_no"] == 2
    assert result["a2a_agent"]["endpoint_id"] == "a2a_1_existing"
    assert result["a2a_agent"]["version"] == "2"
    assert result["a2a_agent_card"]["endpoint_id"] == "a2a_1_existing"

    # Verify get_server_agent_by_agent_id was called first
    a2a_agent_db_mock.get_server_agent_by_agent_id.assert_called_once_with(1, "tenant1")
    # Verify create_server_agent was called
    a2a_agent_db_mock.create_server_agent.assert_called_once()


def test_publish_version_impl_with_a2a_no_name_uses_default(monkeypatch, mock_tools_draft, mock_relations_draft, mock_skills_draft):
    """Test publishing with A2A when agent has no name - uses default 'Agent-{agent_id}'"""
    agent_draft_no_name = {
        "agent_id": 42,
        "tenant_id": "tenant1",
        "version_no": 0,
        "name": None,
        "description": "Test Description",
        "model_ids": [1],
        "business_logic_model_id": 0,
        "max_steps": 10,
        "duty_prompt": "Test prompt",
        "group_ids": "1,2",
        "runtime_framework": "smolagents",
    }

    mock_query_draft = MagicMock(return_value=(agent_draft_no_name, mock_tools_draft, mock_relations_draft))
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)
    mock_get_next = MagicMock(return_value=1)
    monkeypatch.setattr(agent_version_service_module, "get_next_version_no", mock_get_next)
    mock_insert_agent = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_agent_snapshot", mock_insert_agent)
    mock_insert_tool = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_tool_snapshot", mock_insert_tool)
    mock_insert_relation = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_relation_snapshot", mock_insert_relation)
    mock_insert_skill = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_skill_snapshot", mock_insert_skill)
    mock_insert_version = MagicMock(return_value=100)
    monkeypatch.setattr(agent_version_service_module, "insert_version", mock_insert_version)
    mock_update_current = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "update_agent_current_version", mock_update_current)
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=mock_skills_draft))

    a2a_agent_db_mock.get_server_agent_by_agent_id = MagicMock(return_value=None)
    a2a_agent_db_mock.create_server_agent = MagicMock(return_value={
        "agent_id": 42,
        "endpoint_id": "a2a_42_def678",
        "name": "Agent-42",
        "description": "Test Description",
        "version": "1",
        "streaming": False,
    })

    result = publish_version_impl(
        agent_id=42,
        tenant_id="tenant1",
        user_id="user1",
        publish_as_a2a=True,
    )

    assert result["a2a_agent"]["name"] == "Agent-42"
    # Verify create_server_agent was called with default name
    call_kwargs = a2a_agent_db_mock.create_server_agent.call_args[1]
    assert call_kwargs["name"] == "Agent-42"


def test_publish_version_impl_without_a2a(monkeypatch, mock_agent_draft, mock_tools_draft, mock_relations_draft, mock_skills_draft):
    """Test publishing version without A2A (publish_as_a2a=False)"""
    mock_query_draft = MagicMock(return_value=(mock_agent_draft, mock_tools_draft, mock_relations_draft))
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)
    mock_get_next = MagicMock(return_value=1)
    monkeypatch.setattr(agent_version_service_module, "get_next_version_no", mock_get_next)
    mock_insert_agent = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_agent_snapshot", mock_insert_agent)
    mock_insert_tool = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_tool_snapshot", mock_insert_tool)
    mock_insert_relation = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_relation_snapshot", mock_insert_relation)
    mock_insert_skill = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_skill_snapshot", mock_insert_skill)
    mock_insert_version = MagicMock(return_value=100)
    monkeypatch.setattr(agent_version_service_module, "insert_version", mock_insert_version)
    mock_update_current = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "update_agent_current_version", mock_update_current)
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=mock_skills_draft))

    # A2A functions should NOT be called
    a2a_agent_db_mock.get_server_agent_by_agent_id = MagicMock(return_value=None)
    a2a_agent_db_mock.create_server_agent = MagicMock(return_value={
        "agent_id": 1,
        "endpoint_id": "a2a_1_abc",
        "name": "Test Agent",
        "description": "Test Description",
        "version": "1",
        "streaming": False,
    })

    result = publish_version_impl(
        agent_id=1,
        tenant_id="tenant1",
        user_id="user1",
        publish_as_a2a=False,
    )

    assert result["version_no"] == 1
    assert "a2a_agent" not in result
    assert "a2a_agent_card" not in result
    # Verify A2A functions were NOT called
    a2a_agent_db_mock.get_server_agent_by_agent_id.assert_not_called()
    a2a_agent_db_mock.create_server_agent.assert_not_called()

    # Verify updated_by is set on all snapshot types
    agent_snapshot = mock_insert_agent.call_args[0][0]
    assert agent_snapshot["updated_by"] == "user1"
    for call in mock_insert_tool.call_args_list:
        assert call[0][0]["updated_by"] == "user1"
    assert mock_insert_relation.call_args[0][0]["updated_by"] == "user1"
    assert mock_insert_skill.call_args[0][0]["updated_by"] == "user1"


def test_publish_version_impl_with_a2a_streaming_agent(monkeypatch, mock_agent_draft, mock_tools_draft, mock_relations_draft, mock_skills_draft):
    """Test publishing A2A agent that supports streaming"""
    mock_query_draft = MagicMock(return_value=(mock_agent_draft, mock_tools_draft, mock_relations_draft))
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)
    mock_get_next = MagicMock(return_value=1)
    monkeypatch.setattr(agent_version_service_module, "get_next_version_no", mock_get_next)
    mock_insert_agent = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_agent_snapshot", mock_insert_agent)
    mock_insert_tool = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_tool_snapshot", mock_insert_tool)
    mock_insert_relation = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_relation_snapshot", mock_insert_relation)
    mock_insert_skill = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_skill_snapshot", mock_insert_skill)
    mock_insert_version = MagicMock(return_value=100)
    monkeypatch.setattr(agent_version_service_module, "insert_version", mock_insert_version)
    mock_update_current = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "update_agent_current_version", mock_update_current)
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=mock_skills_draft))

    a2a_agent_db_mock.get_server_agent_by_agent_id = MagicMock(return_value=None)
    a2a_agent_db_mock.create_server_agent = MagicMock(return_value={
        "agent_id": 1,
        "endpoint_id": "a2a_1_stream",
        "name": "Test Agent",
        "description": "Test Description",
        "version": "1",
        "streaming": True,
    })

    result = publish_version_impl(
        agent_id=1,
        tenant_id="tenant1",
        user_id="user1",
        publish_as_a2a=True,
    )

    assert result["a2a_agent"]["streaming"] is True
    assert result["a2a_agent_card"]["streaming"] is True

    # Verify updated_by is set on all snapshot types
    agent_snapshot = mock_insert_agent.call_args[0][0]
    assert agent_snapshot["updated_by"] == "user1"
    for call in mock_insert_tool.call_args_list:
        assert call[0][0]["updated_by"] == "user1"
    assert mock_insert_relation.call_args[0][0]["updated_by"] == "user1"
    assert mock_insert_skill.call_args[0][0]["updated_by"] == "user1"


def test_publish_version_impl_with_a2a_existing_agent_no_name(monkeypatch, mock_tools_draft, mock_relations_draft, mock_skills_draft):
    """Test publishing version with publish_as_a2a=True for an existing A2A agent that has no name - uses default name"""
    agent_draft_no_name = {
        "agent_id": 99,
        "tenant_id": "tenant1",
        "version_no": 0,
        "name": None,
        "description": "Test Description",
        "model_ids": [1],
        "business_logic_model_id": 0,
        "max_steps": 10,
        "duty_prompt": "Test prompt",
        "group_ids": "1,2",
        "runtime_framework": "smolagents",
    }

    mock_query_draft = MagicMock(return_value=(agent_draft_no_name, mock_tools_draft, mock_relations_draft))
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)
    mock_get_next = MagicMock(return_value=1)
    monkeypatch.setattr(agent_version_service_module, "get_next_version_no", mock_get_next)
    mock_insert_agent = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_agent_snapshot", mock_insert_agent)
    mock_insert_tool = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_tool_snapshot", mock_insert_tool)
    mock_insert_relation = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_relation_snapshot", mock_insert_relation)
    mock_insert_skill = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_skill_snapshot", mock_insert_skill)
    mock_insert_version = MagicMock(return_value=100)
    monkeypatch.setattr(agent_version_service_module, "insert_version", mock_insert_version)
    mock_update_current = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "update_agent_current_version", mock_update_current)
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=mock_skills_draft))

    # Mock A2A agent already exists
    existing_a2a = {
        "agent_id": 99,
        "endpoint_id": "a2a_99_existing",
        "name": "Old Name",
        "description": "Old Description",
        "version": "0",
        "streaming": False,
    }
    a2a_agent_db_mock.get_server_agent_by_agent_id = MagicMock(return_value=existing_a2a)
    # Mock create_server_agent returns updated agent (existing endpoint_id preserved)
    a2a_agent_db_mock.create_server_agent = MagicMock(return_value={
        "agent_id": 99,
        "endpoint_id": "a2a_99_existing",
        "name": "Agent-99",  # Default name used
        "description": "Test Description",
        "version": "1",
        "streaming": False,
    })

    result = publish_version_impl(
        agent_id=99,
        tenant_id="tenant1",
        user_id="user1",
        publish_as_a2a=True,
    )

    assert result["version_no"] == 1
    assert result["a2a_agent"]["endpoint_id"] == "a2a_99_existing"
    assert result["a2a_agent"]["name"] == "Agent-99"
    assert result["a2a_agent_card"]["endpoint_id"] == "a2a_99_existing"

    # Verify get_server_agent_by_agent_id was called first
    a2a_agent_db_mock.get_server_agent_by_agent_id.assert_called_once_with(99, "tenant1")
    # Verify create_server_agent was called with default name
    a2a_agent_db_mock.create_server_agent.assert_called_once_with(
        agent_id=99,
        user_id="user1",
        tenant_id="tenant1",
        name="Agent-99",
        description="Test Description",
        version="1",
    )

    # Verify updated_by is set on all snapshot types
    agent_snapshot = mock_insert_agent.call_args[0][0]
    assert agent_snapshot["updated_by"] == "user1"
    for call in mock_insert_tool.call_args_list:
        assert call[0][0]["updated_by"] == "user1"
    assert mock_insert_relation.call_args[0][0]["updated_by"] == "user1"
    assert mock_insert_skill.call_args[0][0]["updated_by"] == "user1"


def test_publish_version_impl_with_a2a_empty_string_name(monkeypatch, mock_tools_draft, mock_relations_draft, mock_skills_draft):
    """Test publishing with A2A when agent name is empty string - uses default name"""
    agent_draft_empty_name = {
        "agent_id": 55,
        "tenant_id": "tenant1",
        "version_no": 0,
        "name": "",  # Empty string - falsy
        "description": "Test Description",
        "model_ids": [1],
        "business_logic_model_id": 0,
        "max_steps": 10,
        "duty_prompt": "Test prompt",
        "group_ids": "1,2",
        "runtime_framework": "smolagents",
    }

    mock_query_draft = MagicMock(return_value=(agent_draft_empty_name, mock_tools_draft, mock_relations_draft))
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)
    mock_get_next = MagicMock(return_value=1)
    monkeypatch.setattr(agent_version_service_module, "get_next_version_no", mock_get_next)
    mock_insert_agent = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_agent_snapshot", mock_insert_agent)
    mock_insert_tool = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_tool_snapshot", mock_insert_tool)
    mock_insert_relation = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_relation_snapshot", mock_insert_relation)
    mock_insert_skill = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_skill_snapshot", mock_insert_skill)
    mock_insert_version = MagicMock(return_value=100)
    monkeypatch.setattr(agent_version_service_module, "insert_version", mock_insert_version)
    mock_update_current = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "update_agent_current_version", mock_update_current)
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=mock_skills_draft))

    a2a_agent_db_mock.get_server_agent_by_agent_id = MagicMock(return_value=None)
    a2a_agent_db_mock.create_server_agent = MagicMock(return_value={
        "agent_id": 55,
        "endpoint_id": "a2a_55_xyz",
        "name": "Agent-55",  # Default name used
        "description": "Test Description",
        "version": "1",
        "streaming": False,
    })

    result = publish_version_impl(
        agent_id=55,
        tenant_id="tenant1",
        user_id="user1",
        publish_as_a2a=True,
    )

    # Verify empty string falls back to default name
    call_kwargs = a2a_agent_db_mock.create_server_agent.call_args[1]
    assert call_kwargs["name"] == "Agent-55"

    # Verify updated_by is set on all snapshot types
    agent_snapshot = mock_insert_agent.call_args[0][0]
    assert agent_snapshot["updated_by"] == "user1"
    for call in mock_insert_tool.call_args_list:
        assert call[0][0]["updated_by"] == "user1"
    assert mock_insert_relation.call_args[0][0]["updated_by"] == "user1"
    assert mock_insert_skill.call_args[0][0]["updated_by"] == "user1"


def test_publish_version_impl_with_a2a_missing_endpoint_id_in_response(monkeypatch, mock_agent_draft, mock_tools_draft, mock_relations_draft, mock_skills_draft):
    """Test A2A agent creation response without endpoint_id - card is still created with None endpoint_id"""
    mock_query_draft = MagicMock(return_value=(mock_agent_draft, mock_tools_draft, mock_relations_draft))
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)
    mock_get_next = MagicMock(return_value=1)
    monkeypatch.setattr(agent_version_service_module, "get_next_version_no", mock_get_next)
    mock_insert_agent = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_agent_snapshot", mock_insert_agent)
    mock_insert_tool = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_tool_snapshot", mock_insert_tool)
    mock_insert_relation = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_relation_snapshot", mock_insert_relation)
    mock_insert_skill = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_skill_snapshot", mock_insert_skill)
    mock_insert_version = MagicMock(return_value=100)
    monkeypatch.setattr(agent_version_service_module, "insert_version", mock_insert_version)
    mock_update_current = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "update_agent_current_version", mock_update_current)
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=mock_skills_draft))

    a2a_agent_db_mock.get_server_agent_by_agent_id = MagicMock(return_value=None)
    # create_server_agent returns dict without endpoint_id (edge case)
    a2a_agent_db_mock.create_server_agent = MagicMock(return_value={
        "agent_id": 1,
        "name": "Test Agent",
        "description": "Test Description",
        "version": "1",
        "streaming": False,
    })

    result = publish_version_impl(
        agent_id=1,
        tenant_id="tenant1",
        user_id="user1",
        publish_as_a2a=True,
    )

    # Should include a2a_agent
    assert "a2a_agent" in result
    assert result["a2a_agent"]["agent_id"] == 1
    # endpoint_id in result should be None
    assert result["a2a_agent"].get("endpoint_id") is None
    # a2a_agent_card is still created (with None endpoint_id in paths)
    assert "a2a_agent_card" in result
    assert result["a2a_agent_card"]["endpoint_id"] is None
    assert result["a2a_agent_card"]["agent_card_url"] == "/nb/a2a/None/.well-known/agent-card.json"


def test_publish_version_impl_with_a2a_existing_agent_keeps_endpoint_id(monkeypatch, mock_agent_draft, mock_tools_draft, mock_relations_draft, mock_skills_draft):
    """Test that existing A2A agent preserves its endpoint_id through create_server_agent"""
    mock_query_draft = MagicMock(return_value=(mock_agent_draft, mock_tools_draft, mock_relations_draft))
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)
    mock_get_next = MagicMock(return_value=5)
    monkeypatch.setattr(agent_version_service_module, "get_next_version_no", mock_get_next)
    mock_insert_agent = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_agent_snapshot", mock_insert_agent)
    mock_insert_tool = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_tool_snapshot", mock_insert_tool)
    mock_insert_relation = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_relation_snapshot", mock_insert_relation)
    mock_insert_skill = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_skill_snapshot", mock_insert_skill)
    mock_insert_version = MagicMock(return_value=105)
    monkeypatch.setattr(agent_version_service_module, "insert_version", mock_insert_version)
    mock_update_current = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "update_agent_current_version", mock_update_current)
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=mock_skills_draft))

    existing_a2a = {
        "agent_id": 1,
        "endpoint_id": "a2a_1_persistent",
        "name": "Existing Agent",
        "description": "Existing Description",
        "version": "3",
        "streaming": True,
    }
    a2a_agent_db_mock.get_server_agent_by_agent_id = MagicMock(return_value=existing_a2a)
    a2a_agent_db_mock.create_server_agent = MagicMock(return_value={
        "agent_id": 1,
        "endpoint_id": "a2a_1_persistent",  # Same endpoint_id preserved
        "name": "Existing Agent",
        "description": "Updated Description",
        "version": "5",
        "streaming": True,
    })

    result = publish_version_impl(
        agent_id=1,
        tenant_id="tenant1",
        user_id="user1",
        publish_as_a2a=True,
    )

    # endpoint_id should be consistent across agent and card
    assert result["a2a_agent"]["endpoint_id"] == "a2a_1_persistent"
    assert result["a2a_agent_card"]["endpoint_id"] == "a2a_1_persistent"
    # Agent card paths should use the same endpoint_id
    assert result["a2a_agent_card"]["agent_card_url"] == "/nb/a2a/a2a_1_persistent/.well-known/agent-card.json"
    assert result["a2a_agent_card"]["rest_endpoints"]["message_send"] == "/nb/a2a/a2a_1_persistent/message:send"

    # Verify updated_by is set on all snapshot types
    agent_snapshot = mock_insert_agent.call_args[0][0]
    assert agent_snapshot["updated_by"] == "user1"
    for call in mock_insert_tool.call_args_list:
        assert call[0][0]["updated_by"] == "user1"
    assert mock_insert_relation.call_args[0][0]["updated_by"] == "user1"
    assert mock_insert_skill.call_args[0][0]["updated_by"] == "user1"


def test_publish_version_impl_with_a2a_result_contains_both_keys(monkeypatch, mock_agent_draft, mock_tools_draft, mock_relations_draft, mock_skills_draft):
    """Test that publish_version_impl returns both a2a_agent and a2a_agent_card keys when publish_as_a2a=True"""
    mock_query_draft = MagicMock(return_value=(mock_agent_draft, mock_tools_draft, mock_relations_draft))
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)
    mock_get_next = MagicMock(return_value=1)
    monkeypatch.setattr(agent_version_service_module, "get_next_version_no", mock_get_next)
    mock_insert_agent = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_agent_snapshot", mock_insert_agent)
    mock_insert_tool = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_tool_snapshot", mock_insert_tool)
    mock_insert_relation = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_relation_snapshot", mock_insert_relation)
    mock_insert_skill = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_skill_snapshot", mock_insert_skill)
    mock_insert_version = MagicMock(return_value=100)
    monkeypatch.setattr(agent_version_service_module, "insert_version", mock_insert_version)
    mock_update_current = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "update_agent_current_version", mock_update_current)
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=mock_skills_draft))

    a2a_agent_db_mock.get_server_agent_by_agent_id = MagicMock(return_value=None)
    a2a_agent_db_mock.create_server_agent = MagicMock(return_value={
        "agent_id": 1,
        "endpoint_id": "a2a_1_complete",
        "name": "Test Agent",
        "description": "Test Description",
        "version": "1",
        "streaming": False,
    })

    result = publish_version_impl(
        agent_id=1,
        tenant_id="tenant1",
        user_id="user1",
        publish_as_a2a=True,
    )

    # Verify base result keys
    assert "id" in result
    assert "version_no" in result
    assert "message" in result
    # Verify A2A specific keys
    assert "a2a_agent" in result
    assert "a2a_agent_card" in result
    # Both should be non-empty dicts
    assert isinstance(result["a2a_agent"], dict)
    assert isinstance(result["a2a_agent_card"], dict)

    # Verify updated_by is set on all snapshot types
    agent_snapshot = mock_insert_agent.call_args[0][0]
    assert agent_snapshot["updated_by"] == "user1"
    for call in mock_insert_tool.call_args_list:
        assert call[0][0]["updated_by"] == "user1"
    assert mock_insert_relation.call_args[0][0]["updated_by"] == "user1"
    assert mock_insert_skill.call_args[0][0]["updated_by"] == "user1"


def test_publish_version_impl_with_a2a_description_none(monkeypatch, mock_agent_draft, mock_tools_draft, mock_relations_draft, mock_skills_draft):
    """Test A2A agent creation when agent draft has no description"""
    agent_draft_no_desc = mock_agent_draft.copy()
    agent_draft_no_desc["description"] = None

    mock_query_draft = MagicMock(return_value=(agent_draft_no_desc, mock_tools_draft, mock_relations_draft))
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)
    mock_get_next = MagicMock(return_value=1)
    monkeypatch.setattr(agent_version_service_module, "get_next_version_no", mock_get_next)
    mock_insert_agent = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_agent_snapshot", mock_insert_agent)
    mock_insert_tool = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_tool_snapshot", mock_insert_tool)
    mock_insert_relation = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_relation_snapshot", mock_insert_relation)
    mock_insert_skill = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_skill_snapshot", mock_insert_skill)
    mock_insert_version = MagicMock(return_value=100)
    monkeypatch.setattr(agent_version_service_module, "insert_version", mock_insert_version)
    mock_update_current = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "update_agent_current_version", mock_update_current)
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=mock_skills_draft))

    a2a_agent_db_mock.get_server_agent_by_agent_id = MagicMock(return_value=None)
    a2a_agent_db_mock.create_server_agent = MagicMock(return_value={
        "agent_id": 1,
        "endpoint_id": "a2a_1_nodec",
        "name": "Test Agent",
        "description": None,  # create_server_agent returns None for description
        "version": "1",
        "streaming": False,
    })

    result = publish_version_impl(
        agent_id=1,
        tenant_id="tenant1",
        user_id="user1",
        publish_as_a2a=True,
    )

    # Verify create_server_agent was called with None description
    call_kwargs = a2a_agent_db_mock.create_server_agent.call_args[1]
    assert call_kwargs["description"] is None
    # Agent card should reflect None description
    assert result["a2a_agent_card"]["description"] is None

    # Verify updated_by is set on all snapshot types
    agent_snapshot = mock_insert_agent.call_args[0][0]
    assert agent_snapshot["updated_by"] == "user1"
    for call in mock_insert_tool.call_args_list:
        assert call[0][0]["updated_by"] == "user1"
    assert mock_insert_relation.call_args[0][0]["updated_by"] == "user1"
    assert mock_insert_skill.call_args[0][0]["updated_by"] == "user1"


def test_publish_version_impl_with_a2a_existing_agent_description_update(monkeypatch, mock_agent_draft, mock_tools_draft, mock_relations_draft, mock_skills_draft):
    """Test that existing A2A agent updates its description from agent_draft"""
    mock_query_draft = MagicMock(return_value=(mock_agent_draft, mock_tools_draft, mock_relations_draft))
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)
    mock_get_next = MagicMock(return_value=2)
    monkeypatch.setattr(agent_version_service_module, "get_next_version_no", mock_get_next)
    mock_insert_agent = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_agent_snapshot", mock_insert_agent)
    mock_insert_tool = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_tool_snapshot", mock_insert_tool)
    mock_insert_relation = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_relation_snapshot", mock_insert_relation)
    mock_insert_skill = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_skill_snapshot", mock_insert_skill)
    mock_insert_version = MagicMock(return_value=200)
    monkeypatch.setattr(agent_version_service_module, "insert_version", mock_insert_version)
    mock_update_current = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "update_agent_current_version", mock_update_current)
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=mock_skills_draft))

    existing_a2a = {
        "agent_id": 1,
        "endpoint_id": "a2a_1_old",
        "name": "Old Name",
        "description": "Old Description",
        "version": "1",
        "streaming": False,
    }
    a2a_agent_db_mock.get_server_agent_by_agent_id = MagicMock(return_value=existing_a2a)
    a2a_agent_db_mock.create_server_agent = MagicMock(return_value={
        "agent_id": 1,
        "endpoint_id": "a2a_1_old",
        "name": "Test Agent",  # Updated from agent_draft
        "description": "Test Description",  # Updated from agent_draft
        "version": "2",
        "streaming": False,
    })

    result = publish_version_impl(
        agent_id=1,
        tenant_id="tenant1",
        user_id="user1",
        publish_as_a2a=True,
    )

    # Verify create_server_agent called with updated name and description from draft
    call_kwargs = a2a_agent_db_mock.create_server_agent.call_args[1]
    assert call_kwargs["name"] == "Test Agent"
    assert call_kwargs["description"] == "Test Description"
    # Agent card should reflect updated values
    assert result["a2a_agent_card"]["name"] == "Test Agent"
    assert result["a2a_agent_card"]["description"] == "Test Description"

    # Verify updated_by is set on all snapshot types
    agent_snapshot = mock_insert_agent.call_args[0][0]
    assert agent_snapshot["updated_by"] == "user1"
    for call in mock_insert_tool.call_args_list:
        assert call[0][0]["updated_by"] == "user1"
    assert mock_insert_relation.call_args[0][0]["updated_by"] == "user1"
    assert mock_insert_skill.call_args[0][0]["updated_by"] == "user1"


def test_publish_version_impl_with_a2a_agent_card_all_fields(monkeypatch, mock_agent_draft, mock_tools_draft, mock_relations_draft, mock_skills_draft):
    """Test A2A agent card contains all expected fields"""
    mock_query_draft = MagicMock(return_value=(mock_agent_draft, mock_tools_draft, mock_relations_draft))
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)
    mock_get_next = MagicMock(return_value=1)
    monkeypatch.setattr(agent_version_service_module, "get_next_version_no", mock_get_next)
    mock_insert_agent = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_agent_snapshot", mock_insert_agent)
    mock_insert_tool = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_tool_snapshot", mock_insert_tool)
    mock_insert_relation = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_relation_snapshot", mock_insert_relation)
    mock_insert_skill = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_skill_snapshot", mock_insert_skill)
    mock_insert_version = MagicMock(return_value=100)
    monkeypatch.setattr(agent_version_service_module, "insert_version", mock_insert_version)
    mock_update_current = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "update_agent_current_version", mock_update_current)
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=mock_skills_draft))

    endpoint_id = "a2a_1_full"
    a2a_agent_db_mock.get_server_agent_by_agent_id = MagicMock(return_value=None)
    a2a_agent_db_mock.create_server_agent = MagicMock(return_value={
        "agent_id": 1,
        "endpoint_id": endpoint_id,
        "name": "Full Agent",
        "description": "Full Description",
        "version": "1",
        "streaming": True,
    })

    result = publish_version_impl(
        agent_id=1,
        tenant_id="tenant1",
        user_id="user1",
        publish_as_a2a=True,
    )

    card = result["a2a_agent_card"]
    expected_base_path = f"/nb/a2a/{endpoint_id}"

    # Verify all fields are present
    assert card["endpoint_id"] == endpoint_id
    assert card["name"] == "Full Agent"
    assert card["description"] == "Full Description"
    assert card["version"] == "1"
    assert card["streaming"] is True
    assert card["agent_card_url"] == f"{expected_base_path}/.well-known/agent-card.json"

    # Verify rest_endpoints structure
    assert "rest_endpoints" in card
    rest = card["rest_endpoints"]
    assert rest["message_send"] == f"{expected_base_path}/message:send"
    assert rest["message_stream"] == f"{expected_base_path}/message:stream"
    assert rest["tasks_get"] == f"{expected_base_path}/tasks/{{task_id}}"

    # Verify jsonrpc structure
    assert card["jsonrpc_url"] == f"{expected_base_path}/v1"
    assert card["jsonrpc_methods"] == ["SendMessage", "SendStreamingMessage", "GetTask"]

    # Verify updated_by is set on all snapshot types
    agent_snapshot = mock_insert_agent.call_args[0][0]
    assert agent_snapshot["updated_by"] == "user1"
    for call in mock_insert_tool.call_args_list:
        assert call[0][0]["updated_by"] == "user1"
    assert mock_insert_relation.call_args[0][0]["updated_by"] == "user1"
    assert mock_insert_skill.call_args[0][0]["updated_by"] == "user1"


def test_publish_version_impl_a2a_logging_on_create(monkeypatch, mock_agent_draft, mock_tools_draft, mock_relations_draft, mock_skills_draft, caplog):
    """Test that appropriate log messages are emitted for A2A agent creation"""
    mock_query_draft = MagicMock(return_value=(mock_agent_draft, mock_tools_draft, mock_relations_draft))
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)
    mock_get_next = MagicMock(return_value=1)
    monkeypatch.setattr(agent_version_service_module, "get_next_version_no", mock_get_next)
    mock_insert_agent = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_agent_snapshot", mock_insert_agent)
    mock_insert_tool = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_tool_snapshot", mock_insert_tool)
    mock_insert_relation = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_relation_snapshot", mock_insert_relation)
    mock_insert_skill = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_skill_snapshot", mock_insert_skill)
    mock_insert_version = MagicMock(return_value=100)
    monkeypatch.setattr(agent_version_service_module, "insert_version", mock_insert_version)
    mock_update_current = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "update_agent_current_version", mock_update_current)
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=mock_skills_draft))

    a2a_agent_db_mock.get_server_agent_by_agent_id = MagicMock(return_value=None)
    a2a_agent_db_mock.create_server_agent = MagicMock(return_value={
        "agent_id": 1,
        "endpoint_id": "a2a_1_log",
        "name": "Test Agent",
        "description": "Test Description",
        "version": "1",
        "streaming": False,
    })

    with caplog.at_level("INFO"):
        publish_version_impl(
            agent_id=1,
            tenant_id="tenant1",
            user_id="user1",
            publish_as_a2a=True,
        )

    # Check log messages
    log_messages = [record.message for record in caplog.records]
    # Should contain log about creating A2A agent
    assert any("Creating/updating A2A Server agent" in msg for msg in log_messages)
    assert any("A2A Server agent created/updated with endpoint_id=a2a_1_log" in msg for msg in log_messages)

    # Verify updated_by is set on all snapshot types
    agent_snapshot = mock_insert_agent.call_args[0][0]
    assert agent_snapshot["updated_by"] == "user1"
    for call in mock_insert_tool.call_args_list:
        assert call[0][0]["updated_by"] == "user1"
    assert mock_insert_relation.call_args[0][0]["updated_by"] == "user1"
    assert mock_insert_skill.call_args[0][0]["updated_by"] == "user1"


def test_publish_version_impl_a2a_logging_on_update(monkeypatch, mock_agent_draft, mock_tools_draft, mock_relations_draft, mock_skills_draft, caplog):
    """Test that appropriate log messages are emitted for A2A agent update"""
    mock_query_draft = MagicMock(return_value=(mock_agent_draft, mock_tools_draft, mock_relations_draft))
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)
    mock_get_next = MagicMock(return_value=2)
    monkeypatch.setattr(agent_version_service_module, "get_next_version_no", mock_get_next)
    mock_insert_agent = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_agent_snapshot", mock_insert_agent)
    mock_insert_tool = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_tool_snapshot", mock_insert_tool)
    mock_insert_relation = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_relation_snapshot", mock_insert_relation)
    mock_insert_skill = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "insert_skill_snapshot", mock_insert_skill)
    mock_insert_version = MagicMock(return_value=100)
    monkeypatch.setattr(agent_version_service_module, "insert_version", mock_insert_version)
    mock_update_current = MagicMock()
    monkeypatch.setattr(agent_version_service_module, "update_agent_current_version", mock_update_current)
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=mock_skills_draft))

    existing_a2a = {
        "agent_id": 1,
        "endpoint_id": "a2a_1_existing",
        "name": "Existing",
        "description": "Existing",
        "version": "1",
        "streaming": False,
    }
    a2a_agent_db_mock.get_server_agent_by_agent_id = MagicMock(return_value=existing_a2a)
    a2a_agent_db_mock.create_server_agent = MagicMock(return_value={
        "agent_id": 1,
        "endpoint_id": "a2a_1_existing",
        "name": "Test Agent",
        "description": "Test Description",
        "version": "2",
        "streaming": False,
    })

    with caplog.at_level("INFO"):
        publish_version_impl(
            agent_id=1,
            tenant_id="tenant1",
            user_id="user1",
            publish_as_a2a=True,
        )

    log_messages = [record.message for record in caplog.records]
    # Should contain log about existing A2A agent
    assert any("A2A Server agent already exists" in msg for msg in log_messages)
    assert any("Creating/updating A2A Server agent" in msg for msg in log_messages)
    assert any("A2A Server agent created/updated with endpoint_id=a2a_1_existing" in msg for msg in log_messages)

    # Verify updated_by is set on all snapshot types
    agent_snapshot = mock_insert_agent.call_args[0][0]
    assert agent_snapshot["updated_by"] == "user1"
    for call in mock_insert_tool.call_args_list:
        assert call[0][0]["updated_by"] == "user1"
    assert mock_insert_relation.call_args[0][0]["updated_by"] == "user1"
    assert mock_insert_skill.call_args[0][0]["updated_by"] == "user1"


# =============================================================================
# Additional tests for model_ids handling (new code paths)
# =============================================================================

def test_get_version_detail_impl_multiple_models(monkeypatch):
    """Test getting version detail with multiple models in model_ids array"""
    mock_version = {
        "version_no": 1,
        "version_name": "v1.0",
        "status": "RELEASED",
        "release_note": "Test note",
        "source_type": "NORMAL",
        "source_version_no": None,
    }

    mock_agent_snapshot = {
        "agent_id": 1,
        "name": "Test Agent",
        "model_ids": [1, 2, 3],
        "business_logic_model_id": 4,
        "max_steps": 10,
        "description": "Test",
        "duty_prompt": "Test prompt",
        "group_ids": "1,2",
    }

    mock_tools_snapshot = [
        {"tool_id": 1, "enabled": True},
    ]

    mock_relations_snapshot = []

    mock_search = MagicMock(return_value=mock_version)
    monkeypatch.setattr(agent_version_service_module, "search_version_by_version_no", mock_search)
    mock_query_snapshot = MagicMock(
        return_value=(mock_agent_snapshot, mock_tools_snapshot, mock_relations_snapshot)
    )
    monkeypatch.setattr(agent_version_service_module, "query_agent_snapshot", mock_query_snapshot)

    def mock_get_model(model_id):
        return {"display_name": f"Model-{model_id}"}

    monkeypatch.setattr(agent_version_service_module, "get_model_by_model_id", mock_get_model)
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=[]))

    result = get_version_detail_impl(agent_id=1, tenant_id="tenant1", version_no=1)

    assert result["name"] == "Test Agent"
    assert result["model_ids"] == [1, 2, 3]
    assert result["model_names"] == ["Model-1", "Model-2", "Model-3"]
    assert result["model_name"] == "Model-1"
    assert result["business_logic_model_name"] == "Model-4"


def test_get_version_detail_impl_model_ids_none(monkeypatch):
    """Test getting version detail when model_ids is None"""
    mock_version = {
        "version_no": 1,
        "version_name": "v1.0",
        "status": "RELEASED",
        "release_note": "Test note",
        "source_type": "NORMAL",
        "source_version_no": None,
    }

    mock_agent_snapshot = {
        "agent_id": 1,
        "name": "Test Agent",
        "model_ids": None,
        "business_logic_model_id": None,
        "max_steps": 10,
        "description": "Test",
        "duty_prompt": "Test prompt",
        "group_ids": "1,2",
    }

    mock_tools_snapshot = []
    mock_relations_snapshot = []

    mock_search = MagicMock(return_value=mock_version)
    monkeypatch.setattr(agent_version_service_module, "search_version_by_version_no", mock_search)
    mock_query_snapshot = MagicMock(
        return_value=(mock_agent_snapshot, mock_tools_snapshot, mock_relations_snapshot)
    )
    monkeypatch.setattr(agent_version_service_module, "query_agent_snapshot", mock_query_snapshot)
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=[]))

    result = get_version_detail_impl(agent_id=1, tenant_id="tenant1", version_no=1)

    assert result["model_ids"] is None
    assert result["model_names"] == []
    assert result["model_name"] is None
    assert result["business_logic_model_name"] is None


def test_compare_versions_impl_model_ids_difference(monkeypatch):
    """Test comparing versions with different model_ids arrays"""
    version_a = {
        "name": "Agent A",
        "model_ids": [1, 2],
        "model_names": ["Model A1", "Model A2"],
        "model_name": "Model A1",
        "max_steps": 10,
        "description": "Desc A",
        "duty_prompt": "Prompt A",
        "tools": [],
        "sub_agent_id_list": [],
        "skills": [],
    }
    version_b = {
        "name": "Agent A",
        "model_ids": [1, 3],
        "model_names": ["Model A1", "Model B3"],
        "model_name": "Model A1",
        "max_steps": 10,
        "description": "Desc A",
        "duty_prompt": "Prompt A",
        "tools": [],
        "sub_agent_id_list": [],
        "skills": [],
    }

    with patch('backend.services.agent_version_service._get_version_detail_or_draft') as mock_get_detail:
        mock_get_detail.side_effect = [version_a, version_b]

        result = compare_versions_impl(
            agent_id=1,
            tenant_id="tenant1",
            version_no_a=1,
            version_no_b=2,
        )

        difference_fields = [d["field"] for d in result["differences"]]
        assert "model_ids" in difference_fields


def test_compare_versions_impl_model_ids_same(monkeypatch):
    """Test comparing versions with identical model_ids"""
    version_a = {
        "name": "Agent A",
        "model_ids": [1, 2],
        "model_names": ["Model A1", "Model A2"],
        "model_name": "Model A1",
        "max_steps": 10,
        "description": "Desc A",
        "duty_prompt": "Prompt A",
        "tools": [],
        "sub_agent_id_list": [],
        "skills": [],
    }
    version_b = {
        "name": "Agent B",
        "model_ids": [1, 2],
        "model_names": ["Model A1", "Model A2"],
        "model_name": "Model A1",
        "max_steps": 10,
        "description": "Desc B",
        "duty_prompt": "Prompt B",
        "tools": [],
        "sub_agent_id_list": [],
        "skills": [],
    }

    with patch('backend.services.agent_version_service._get_version_detail_or_draft') as mock_get_detail:
        mock_get_detail.side_effect = [version_a, version_b]

        result = compare_versions_impl(
            agent_id=1,
            tenant_id="tenant1",
            version_no_a=1,
            version_no_b=2,
        )

        difference_fields = [d["field"] for d in result["differences"]]
        assert "model_ids" not in difference_fields
        assert "name" in difference_fields


def test_compare_versions_impl_model_ids_order_difference(monkeypatch):
    """Test comparing versions with same models but different order"""
    version_a = {
        "name": "Agent A",
        "model_ids": [1, 2],
        "model_names": ["Model A1", "Model A2"],
        "model_name": "Model A1",
        "max_steps": 10,
        "description": "Desc A",
        "duty_prompt": "Prompt A",
        "tools": [],
        "sub_agent_id_list": [],
        "skills": [],
    }
    version_b = {
        "name": "Agent A",
        "model_ids": [2, 1],
        "model_names": ["Model A2", "Model A1"],
        "model_name": "Model A2",
        "max_steps": 10,
        "description": "Desc A",
        "duty_prompt": "Prompt A",
        "tools": [],
        "sub_agent_id_list": [],
        "skills": [],
    }

    with patch('backend.services.agent_version_service._get_version_detail_or_draft') as mock_get_detail:
        mock_get_detail.side_effect = [version_a, version_b]

        result = compare_versions_impl(
            agent_id=1,
            tenant_id="tenant1",
            version_no_a=1,
            version_no_b=2,
        )

        difference_fields = [d["field"] for d in result["differences"]]
        assert "model_ids" in difference_fields


def test_get_version_detail_or_draft_with_multiple_models(monkeypatch):
    """Test _get_version_detail_or_draft with multiple models"""
    mock_agent_draft = {
        "agent_id": 1,
        "name": "Draft Agent",
        "model_ids": [1, 2],
        "business_logic_model_id": 3,
        "group_ids": "1,2",
    }
    mock_tools_draft = []
    mock_relations_draft = []
    mock_skills_draft = []

    mock_query_draft = MagicMock(
        return_value=(mock_agent_draft, mock_tools_draft, mock_relations_draft)
    )
    monkeypatch.setattr(agent_version_service_module, "query_agent_draft", mock_query_draft)

    def mock_get_model(model_id):
        return {"display_name": f"Model-{model_id}"}

    monkeypatch.setattr(agent_version_service_module, "get_model_by_model_id", mock_get_model)
    monkeypatch.setattr(skill_db_mock, "query_skill_instances_by_agent_id", MagicMock(return_value=mock_skills_draft))

    result = _get_version_detail_or_draft(agent_id=1, tenant_id="tenant1", version_no=0)

    assert result["model_ids"] == [1, 2]
    assert result["model_names"] == ["Model-1", "Model-2"]
    assert result["model_name"] == "Model-1"
    assert result["business_logic_model_name"] == "Model-3"


def test_list_published_agents_impl_multiple_models(monkeypatch):
    """Test listing published agents with multiple models"""
    agent_db_mock.query_all_agent_info_by_tenant_id = MagicMock(
        return_value=[
            {
                "agent_id": 1,
                "enabled": True,
                "current_version_no": 1,
                "group_ids": "1,2",
                "created_by": "user1",
                "name": "Test Agent",
                "display_name": "Test Agent",
                "description": "Test",
                "author": "Author",
                "is_new": False,
            }
        ]
    )

    agent_service_mock.get_user_tenant_by_user_id = MagicMock(
        return_value={"user_role": "ADMIN"}
    )
    agent_service_mock.query_group_ids_by_user = MagicMock(return_value=[1, 2])

    agent_version_db_mock.query_agent_snapshot = MagicMock(
        return_value=(
            {
                "agent_id": 1,
                "name": "Test Agent",
                "model_ids": [1, 2],
                "description": "Test",
            },
            [{"tool_id": 1, "enabled": True}],
            [],
        )
    )

    agent_service_mock.check_agent_availability = MagicMock(
        return_value=(True, [])
    )
    agent_service_mock._apply_duplicate_name_availability_rules = MagicMock()

    def mock_get_model(model_id, tenant_id=None):
        return {"display_name": f"Model-{model_id}"}

    agent_service_mock.get_model_by_model_id = MagicMock(side_effect=mock_get_model)

    result = asyncio.run(list_published_agents_impl(tenant_id="tenant1", user_id="user1"))

    assert len(result) == 1
    assert result[0]["agent_id"] == 1
    assert result[0]["model_ids"] == [1, 2]
    assert result[0]["model_names"] == ["Model-1", "Model-2"]
    assert result[0]["model_name"] == "Model-1"


def test_list_published_agents_impl_model_ids_empty(monkeypatch):
    """Test listing published agents with empty model_ids"""
    agent_db_mock.query_all_agent_info_by_tenant_id = MagicMock(
        return_value=[
            {
                "agent_id": 1,
                "enabled": True,
                "current_version_no": 1,
                "group_ids": "1,2",
                "created_by": "user1",
                "name": "Test Agent",
                "display_name": "Test Agent",
                "description": "Test",
                "author": "Author",
                "is_new": False,
            }
        ]
    )

    agent_service_mock.get_user_tenant_by_user_id = MagicMock(
        return_value={"user_role": "ADMIN"}
    )
    agent_service_mock.query_group_ids_by_user = MagicMock(return_value=[1, 2])

    agent_version_db_mock.query_agent_snapshot = MagicMock(
        return_value=(
            {
                "agent_id": 1,
                "name": "Test Agent",
                "model_ids": [],
                "description": "Test",
            },
            [{"tool_id": 1, "enabled": True}],
            [],
        )
    )

    agent_service_mock.check_agent_availability = MagicMock(
        return_value=(False, ["model_not_configured"])
    )
    agent_service_mock._apply_duplicate_name_availability_rules = MagicMock()
    agent_service_mock.get_model_by_model_id = MagicMock(return_value=None)

    result = asyncio.run(list_published_agents_impl(tenant_id="tenant1", user_id="user1"))

    assert len(result) == 1
    assert result[0]["model_ids"] == []
    assert result[0]["model_names"] == []
    assert result[0]["model_name"] is None
    assert result[0]["is_available"] is False


# ============================================================================
# Tests for get_valid_model_ids integration in list_published_agents_impl
# ============================================================================


def test_list_published_agents_impl_filters_deleted_models(monkeypatch):
    """Test that list_published_agents_impl filters out deleted models from model_ids.

    This test verifies that:
    1. get_valid_model_ids is called to filter deleted models
    2. The filtered model_ids are used for availability check and model name resolution
    3. The returned model_ids only contain valid (non-deleted) models
    """
    agent_db_mock.query_all_agent_info_by_tenant_id = MagicMock(
        return_value=[
            {
                "agent_id": 1,
                "enabled": True,
                "current_version_no": 1,
                "group_ids": "1,2",
                "created_by": "user1",
                "name": "Test Agent",
                "display_name": "Test Agent",
                "description": "Test",
                "author": "Author",
                "is_new": False,
            }
        ]
    )

    agent_service_mock.get_user_tenant_by_user_id = MagicMock(
        return_value={"user_role": "ADMIN"}
    )
    agent_service_mock.query_group_ids_by_user = MagicMock(return_value=[1, 2])

    agent_version_db_mock.query_agent_snapshot = MagicMock(
        return_value=(
            {
                "agent_id": 1,
                "name": "Test Agent",
                "model_ids": [1, 2, 3],  # Original model_ids including deleted ones
                "description": "Test",
            },
            [{"tool_id": 1, "enabled": True}],
            [],
        )
    )

    # Mock get_valid_model_ids to filter out model_id=2 (deleted)
    agent_version_service_module.get_valid_model_ids = MagicMock(return_value=[1, 3])

    agent_service_mock.check_agent_availability = MagicMock(
        return_value=(True, [])
    )
    agent_service_mock._apply_duplicate_name_availability_rules = MagicMock()

    # Mock model info for valid models
    def get_model_side_effect(model_id, tenant_id=None):
        if model_id == 1:
            return {"display_name": "Model 1", "model_id": 1}
        elif model_id == 3:
            return {"display_name": "Model 3", "model_id": 3}
        return None
    agent_service_mock.get_model_by_model_id = MagicMock(side_effect=get_model_side_effect)

    result = asyncio.run(list_published_agents_impl(tenant_id="tenant1", user_id="user1"))

    # Verify get_valid_model_ids was called
    agent_version_service_module.get_valid_model_ids.assert_called_once_with([1, 2, 3], "tenant1")

    # Verify result contains only valid model_ids
    assert len(result) == 1
    assert result[0]["model_ids"] == [1, 3]
    assert result[0]["model_names"] == ["Model 1", "Model 3"]
    assert result[0]["model_name"] == "Model 1"


def test_list_published_agents_impl_all_models_deleted(monkeypatch):
    """Test that list_published_agents_impl handles when all models are deleted."""
    agent_db_mock.query_all_agent_info_by_tenant_id = MagicMock(
        return_value=[
            {
                "agent_id": 1,
                "enabled": True,
                "current_version_no": 1,
                "group_ids": "1,2",
                "created_by": "user1",
                "name": "Test Agent",
                "display_name": "Test Agent",
                "description": "Test",
            }
        ]
    )

    agent_service_mock.get_user_tenant_by_user_id = MagicMock(
        return_value={"user_role": "ADMIN"}
    )

    agent_version_db_mock.query_agent_snapshot = MagicMock(
        return_value=(
            {
                "agent_id": 1,
                "name": "Test Agent",
                "model_ids": [1, 2, 3],
                "description": "Test",
            },
            [],
            [],
        )
    )

    # All models were deleted
    agent_version_service_module.get_valid_model_ids = MagicMock(return_value=[])

    agent_service_mock.check_agent_availability = MagicMock(
        return_value=(True, [])
    )
    agent_service_mock._apply_duplicate_name_availability_rules = MagicMock()
    agent_service_mock.get_model_by_model_id = MagicMock(return_value=None)

    result = asyncio.run(list_published_agents_impl(tenant_id="tenant1", user_id="user1"))

    assert len(result) == 1
    assert result[0]["model_ids"] == []
    assert result[0]["model_names"] == []
    assert result[0]["model_name"] is None


def test_list_published_agents_impl_empty_model_ids(monkeypatch):
    """Test that list_published_agents_impl handles empty model_ids."""
    agent_db_mock.query_all_agent_info_by_tenant_id = MagicMock(
        return_value=[
            {
                "agent_id": 1,
                "enabled": True,
                "current_version_no": 1,
                "group_ids": "1,2",
                "created_by": "user1",
                "name": "Test Agent",
                "display_name": "Test Agent",
                "description": "Test",
            }
        ]
    )

    agent_service_mock.get_user_tenant_by_user_id = MagicMock(
        return_value={"user_role": "ADMIN"}
    )

    agent_version_db_mock.query_agent_snapshot = MagicMock(
        return_value=(
            {
                "agent_id": 1,
                "name": "Test Agent",
                "model_ids": [],  # Empty model_ids
                "description": "Test",
            },
            [],
            [],
        )
    )

    # get_valid_model_ids should be called with empty list
    agent_version_service_module.get_valid_model_ids = MagicMock(return_value=[])

    agent_service_mock.check_agent_availability = MagicMock(
        return_value=(True, [])
    )
    agent_service_mock._apply_duplicate_name_availability_rules = MagicMock()
    agent_service_mock.get_model_by_model_id = MagicMock(return_value=None)

    result = asyncio.run(list_published_agents_impl(tenant_id="tenant1", user_id="user1"))

    agent_version_service_module.get_valid_model_ids.assert_called_once_with([], "tenant1")
    assert result[0]["model_ids"] == []
    assert result[0]["model_names"] == []
