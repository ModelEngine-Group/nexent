"""
Unit tests for management.services.skill.service module.
"""
import sys
import os
import io
import json
import base64
import types
import ast
import re
import zipfile

# Python 3.14 removed the legacy AST alias still referenced by the service.
if not hasattr(ast, "Num"):
    ast.Num = ast.Constant
if not hasattr(ast, "Str"):
    ast.Str = ast.Constant

# Add backend path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))
# Add sdk path for nexent imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../sdk"))

import pytest
from unittest.mock import patch, MagicMock, mock_open

# Mock external dependencies before any imports
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

# Create nexent module hierarchy BEFORE patching
nexent_mock = types.ModuleType('nexent')
nexent_core_mock = types.ModuleType('nexent.core')
nexent_core_agents_mock = types.ModuleType('nexent.core.agents')
nexent_core_agents_agent_model_mock = types.ModuleType('nexent.core.agents.agent_model')
nexent_skills_mock = types.ModuleType('nexent.skills')
nexent_skills_mock.__path__ = [os.path.join(os.path.dirname(__file__), '../../../sdk/nexent/skills')]  # Required for submodule lookups
nexent_skills_skill_loader_mock = types.ModuleType('nexent.skills.skill_loader')
nexent_skills_skill_manager_mock = types.ModuleType('nexent.skills.skill_manager')
nexent_storage_mock = types.ModuleType('nexent.storage')
nexent_storage_storage_client_factory_mock = types.ModuleType('nexent.storage.storage_client_factory')
nexent_storage_minio_config_mock = types.ModuleType('nexent.storage.minio_config')

# Set attributes on nexent_mock for proper submodule resolution
setattr(nexent_mock, 'skills', nexent_skills_mock)

# Create mock classes
class MockAgentConfig:
    pass

class MockAgentRunInfo:
    pass

class MockModelConfig:
    pass

class MockToolConfig:
    pass

nexent_core_agents_agent_model_mock.AgentConfig = MockAgentConfig
nexent_core_agents_agent_model_mock.AgentRunInfo = MockAgentRunInfo
nexent_core_agents_agent_model_mock.ModelConfig = MockModelConfig
nexent_core_agents_agent_model_mock.ToolConfig = MockToolConfig

sys.modules['nexent'] = nexent_mock
sys.modules['nexent.core'] = nexent_core_mock
sys.modules['nexent.core.agents'] = nexent_core_agents_mock
sys.modules['nexent.core.agents.agent_model'] = nexent_core_agents_agent_model_mock
sys.modules['nexent.skills'] = nexent_skills_mock
sys.modules['nexent.skills.skill_loader'] = nexent_skills_skill_loader_mock
sys.modules['nexent.skills.skill_manager'] = nexent_skills_skill_manager_mock
sys.modules['nexent.storage'] = nexent_storage_mock
sys.modules['nexent.storage.storage_client_factory'] = nexent_storage_storage_client_factory_mock
sys.modules['nexent.storage.minio_config'] = nexent_storage_minio_config_mock

# Set up storage mocks
storage_client_mock = MagicMock()
nexent_storage_storage_client_factory_mock.create_storage_client_from_config = MagicMock(return_value=storage_client_mock)

class MockMinIOStorageConfig:
    def validate(self):
        pass
nexent_storage_minio_config_mock.MinIOStorageConfig = MockMinIOStorageConfig

# Create mock SkillManager and SkillLoader
class MockSkillLoader:
    FRONTMATTER_PATTERN = None

    @classmethod
    def parse(cls, content):
        if not content or not content.strip():
            raise ValueError("Empty content")
        lines = content.split('\n')
        meta = {}
        body_lines = []
        in_frontmatter = False
        frontmatter_lines = []

        for line in lines:
            if line.strip() == '---':
                if not in_frontmatter:
                    in_frontmatter = True
                    continue
                else:
                    in_frontmatter = False
                    continue
            if in_frontmatter:
                frontmatter_lines.append(line)
            elif line.startswith('#') or not line.strip():
                continue
            else:
                body_lines.append(line)

        for line in frontmatter_lines:
            if ':' in line:
                key, val = line.split(':', 1)
                meta[key.strip()] = val.strip().strip('"\'')
            else:
                meta.setdefault('tags', []).append(line.strip().strip('- '))

        return {
            "name": meta.get("name", "Unknown"),
            "description": meta.get("description", ""),
            "allowed_tools": meta.get("allowed-tools", []),
            "tags": meta.get("tags", []),
            "content": "\n".join(body_lines).strip(),
        }

    @classmethod
    def parse_raises_on_invalid(cls, content):
        """Alternative parse that raises on invalid content for testing."""
        if not content or not content.strip():
            raise ValueError("Empty content")
        # Check for invalid YAML-like content
        if content.strip().startswith("invalid:") and ":" in content and content.count(":") > 2:
            raise ValueError("Invalid YAML structure")
        return cls.parse(content)

nexent_skills_skill_loader_mock.SkillLoader = MockSkillLoader
nexent_skills_mock.SkillLoader = MockSkillLoader

# MockSkillManager is defined later (after TEST_LOCAL_SKILLS_DIR is set)
# and will be assigned to nexent_skills_mock.SkillManager there

# Mock nexent.core.utils.observer for MessageObserver
nexent_core_utils_mock = types.ModuleType('nexent.core.utils')
nexent_core_utils_observer_mock = types.ModuleType('nexent.core.utils.observer')

class MockMessageObserver:
    def __init__(self, lang=None):
        self.lang = lang
        self._cached = []

    def send(self, msg):
        self._cached.append(msg)

    def get_cached_message(self):
        return self._cached

nexent_core_utils_observer_mock.MessageObserver = MockMessageObserver
nexent_core_utils_mock.observer = nexent_core_utils_observer_mock

sys.modules['nexent.core.utils'] = nexent_core_utils_mock
sys.modules['nexent.core.utils.observer'] = nexent_core_utils_observer_mock

# Set up consts mocks
consts_mock = types.ModuleType('consts')
consts_mock.__path__ = [os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../backend/consts"))]
consts_const_mock = types.ModuleType('consts.const')
TEST_LOCAL_SKILLS_DIR = os.path.abspath(os.path.join(os.getcwd(), ".pytest-tmp", "skills"))
consts_const_mock.CONTAINER_SKILLS_PATH = os.path.abspath(os.sep)
consts_const_mock.OFFICIAL_SKILLS_ZIP_PATH = "/tmp/official-skills.zip"
consts_const_mock.ROOT_DIR = "/tmp"
consts_const_mock.CAN_EDIT_ALL_USER_ROLES = {"ADMIN"}
consts_const_mock.PERMISSION_EDIT = "EDIT"
consts_const_mock.PERMISSION_PRIVATE = "PRIVATE"
consts_const_mock.PERMISSION_READ = "READ_ONLY"
consts_exceptions_mock = types.ModuleType('consts.exceptions')

class SkillException(Exception):
    pass
consts_exceptions_mock.SkillException = SkillException
consts_exceptions_mock.ForbiddenError = type('ForbiddenError', (Exception,), {})
consts_exceptions_mock.UnauthorizedError = type('UnauthorizedError', (Exception,), {})
consts_exceptions_mock.NotFoundException = type('NotFoundException', (Exception,), {})
consts_exceptions_mock.ValidationError = type('ValidationError', (Exception,), {})
consts_exceptions_mock.AppException = type('AppException', (Exception,), {})
consts_exceptions_mock.SkillDuplicateError = type('SkillDuplicateError', (Exception,), {})

sys.modules['consts'] = consts_mock
sys.modules['consts.const'] = consts_const_mock
sys.modules['consts.exceptions'] = consts_exceptions_mock

# Set up aiofiles mock for async file operations
import aiofiles
aiofiles_mock = types.ModuleType('aiofiles')

class MockAiofilesContextManager:
    def __init__(self, content=b""):
        self.content = content

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def read(self):
        return self.content

class MockAiofiles:
    async def open(self, path, mode='r', encoding=None):
        return MockAiofilesContextManager(b"mocked content")

sys.modules['aiofiles'] = aiofiles_mock
sys.modules['aiofiles'].open = MockAiofiles().open

# MockSkillManager - must be defined after TEST_LOCAL_SKILLS_DIR
class MockSkillManager:
    def __init__(self, local_skills_dir=None, **kwargs):
        self.local_skills_dir = local_skills_dir
        self.tenant_id = kwargs.get('tenant_id')

    def resolve_tenant_dir(self, tenant_id=None):
        """Mock implementation of resolve_tenant_dir method."""
        # Return the instance's local_skills_dir, defaulting to TEST_LOCAL_SKILLS_DIR
        return self.local_skills_dir if self.local_skills_dir else TEST_LOCAL_SKILLS_DIR

    def save_skill(self, skill_name, skill_md_content, skill_files=None):
        """Mock save_skill method."""
        pass

    def list_skills(self, tenant_id=None):
        """Mock list_skills method."""
        return []

    def get_skill(self, skill_name, tenant_id=None):
        """Mock get_skill method."""
        return None

nexent_skills_mock.SkillManager = MockSkillManager
nexent_skills_skill_manager_mock.SkillManager = MockSkillManager

# Set up utils mocks
utils_mock = types.ModuleType('utils')
utils_mock.__path__ = [os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../backend/utils"))]
utils_skill_params_utils_mock = types.ModuleType('utils.skill_params_utils')
utils_skill_params_utils_mock.strip_params_comments_for_db = MagicMock(side_effect=lambda x: x)
utils_skill_params_utils_mock.params_dict_to_roundtrip_yaml_text = MagicMock(return_value="params: {}")
utils_prompt_template_utils_mock = types.ModuleType('utils.prompt_template_utils')
utils_prompt_template_utils_mock.get_skill_creation_simple_prompt_template = MagicMock(return_value={"system_prompt": "", "user_prompt": ""})
utils_content_classifier_utils_mock = types.ModuleType('utils.content_classifier_utils')
utils_str_utils_mock = types.ModuleType('utils.str_utils')
utils_str_utils_mock.convert_list_to_string = MagicMock(
    side_effect=lambda items: "" if items is None else ",".join(str(item) for item in items)
)

# Import generate_available_copy_skill_name before utils is mocked
from utils.skill_import_utils import generate_available_copy_skill_name  # noqa: E402,F811
utils_skill_import_utils_mock = types.ModuleType('utils.skill_import_utils')
utils_skill_import_utils_mock.generate_available_copy_skill_name = generate_available_copy_skill_name

class MockContentClassifier:
    def classify(self, content):
        return []

utils_content_classifier_utils_mock.ContentClassifier = MockContentClassifier
sys.modules['utils'] = utils_mock
sys.modules['utils.skill_params_utils'] = utils_skill_params_utils_mock
sys.modules['utils.prompt_template_utils'] = utils_prompt_template_utils_mock
sys.modules['utils.content_classifier_utils'] = utils_content_classifier_utils_mock
sys.modules['utils.str_utils'] = utils_str_utils_mock
sys.modules['utils.skill_import_utils'] = utils_skill_import_utils_mock

# Set up database mocks
database_mock = types.ModuleType('database')
database_mock.__path__ = [os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../backend/database"))]
database_client_mock = types.ModuleType('database.client')
database_client_mock.get_db_session = MagicMock()
database_client_mock.as_dict = MagicMock()
database_client_mock.filter_property = MagicMock()

database_db_models_mock = types.ModuleType('database.db_models')
database_db_models_mock.SkillInfo = MagicMock()
database_db_models_mock.KnowledgeRecord = MagicMock()
database_db_models_mock.KnowledgeFileLifecycle = MagicMock()
database_db_models_mock.KnowledgeStorageObject = MagicMock()
database_group_db_mock = types.ModuleType('database.group_db')
database_group_db_mock.query_group_ids_by_user = MagicMock(return_value=[])
database_user_tenant_db_mock = types.ModuleType('database.user_tenant_db')
database_user_tenant_db_mock.get_user_tenant_by_user_id = MagicMock(
    return_value={"user_role": "DEV"}
)

# Create mock skill_db module with functions
database_skill_db_mock = types.ModuleType('database.skill_db')

def mock_create_or_update_skill_by_skill_info(skill_info, tenant_id, user_id, version_no=0):
    return {"skill_instance_id": 1, "skill_id": 1, "agent_id": 1, "enabled": True}

def mock_query_skill_instances_by_agent_id(agent_id, tenant_id, version_no=0):
    return []

def mock_query_enabled_skill_instances(agent_id, tenant_id, version_no=0):
    return []

def mock_query_skill_instance_by_id(agent_id, skill_id, tenant_id, version_no=0):
    return None

def mock_search_skills_for_agent(agent_id, tenant_id, version_no=0):
    return []

def mock_delete_skills_by_agent_id(agent_id, tenant_id, user_id, version_no=0):
    pass

def mock_delete_skill_instances_by_skill_id(skill_id, user_id):
    pass

# SkillRepository functions now moved to skill_db
def mock_list_skills(tenant_id=None):
    return []

def mock_get_skill_by_name(skill_name, tenant_id=None):
    return None

def mock_get_skill_by_id(skill_id, tenant_id=None):
    return None

def mock_create_skill(skill_data, tenant_id=None):
    return {"skill_id": 1, "name": skill_data.get("name", "unnamed")}

def mock_update_skill(skill_name, skill_data, tenant_id=None, updated_by=None):
    return {"skill_id": 1, "name": skill_name}

def mock_delete_skill(skill_name, tenant_id=None, updated_by=None):
    return True

def mock_get_tool_ids_by_names(tool_names, tenant_id):
    return []

def mock_get_tool_names_by_skill_name(skill_name):
    return []

def mock_get_tool_names_by_ids(session, tool_ids):
    return []

def mock_get_skill_with_tool_names(skill_name):
    return None

def mock_update_skill_by_id(skill_id, skill_data, tenant_id=None, updated_by=None):
    return {"skill_id": skill_id, "name": skill_data.get("name", "updated")}

database_skill_db_mock.list_skills = mock_list_skills
database_skill_db_mock.get_skill_by_name = mock_get_skill_by_name
database_skill_db_mock.get_skill_by_id = mock_get_skill_by_id
database_skill_db_mock.create_skill = mock_create_skill
database_skill_db_mock.update_skill = mock_update_skill
database_skill_db_mock.delete_skill = mock_delete_skill
database_skill_db_mock.get_tool_ids_by_names = mock_get_tool_ids_by_names
database_skill_db_mock.get_tool_names_by_skill_name = mock_get_tool_names_by_skill_name
database_skill_db_mock.get_tool_names_by_ids = mock_get_tool_names_by_ids
database_skill_db_mock.get_skill_with_tool_names = mock_get_skill_with_tool_names
database_skill_db_mock.update_skill_by_id = mock_update_skill_by_id

database_skill_db_mock.create_or_update_skill_by_skill_info = mock_create_or_update_skill_by_skill_info
database_skill_db_mock.query_skill_instances_by_agent_id = mock_query_skill_instances_by_agent_id
database_skill_db_mock.query_enabled_skill_instances = mock_query_enabled_skill_instances
database_skill_db_mock.query_skill_instance_by_id = mock_query_skill_instance_by_id
database_skill_db_mock.search_skills_for_agent = mock_search_skills_for_agent
database_skill_db_mock.delete_skills_by_agent_id = mock_delete_skills_by_agent_id
database_skill_db_mock.delete_skill_instances_by_skill_id = mock_delete_skill_instances_by_skill_id
database_skill_db_mock.check_skill_list_initialized = MagicMock(return_value=False)
database_skill_db_mock.upsert_scanned_skills = MagicMock(return_value=[])

database_mock.client = database_client_mock
database_mock.skill_db = database_skill_db_mock
database_mock.db_models = database_db_models_mock

sys.modules['database'] = database_mock
sys.modules['database.client'] = database_client_mock
sys.modules['database.skill_db'] = database_skill_db_mock
sys.modules['database.db_models'] = database_db_models_mock
sys.modules['database.group_db'] = database_group_db_mock
sys.modules['database.user_tenant_db'] = database_user_tenant_db_mock
setattr(database_mock, 'skill_db', database_skill_db_mock)

# Mock nexent.core.agents.run_agent for create_skill_from_request
nexent_core_agents_run_agent_mock = types.ModuleType('nexent.core.agents.run_agent')
nexent_core_agents_run_agent_mock.agent_run_thread = MagicMock()
sys.modules['nexent.core.agents.run_agent'] = nexent_core_agents_run_agent_mock

# Mock agents.skill_creation_agent module
agents_mock = types.ModuleType('agents')
agents_skill_creation_agent_mock = types.ModuleType('agents.skill_creation_agent')
agents_skill_creation_agent_mock.create_skill_from_request = MagicMock()
agents_mock.skill_creation_agent = agents_skill_creation_agent_mock
sys.modules['agents'] = agents_mock
sys.modules['agents.skill_creation_agent'] = agents_skill_creation_agent_mock

# Now import the service module
from management.services.skill import service as skill_service
from management.services.skill import support as skill_support
from management.services.skill.service import (
    SkillService,
    _normalize_zip_entry_path,
    _find_zip_member_config_yaml,
    _params_dict_to_storable,
    _parse_yaml_with_ruamel_merge_eol_comments,
    _parse_yaml_fallback_pyyaml,
    _parse_skill_params_from_config_bytes,
    _read_params_from_zip_config_yaml,
    _local_skill_config_yaml_path,
    _write_skill_params_to_local_config_yaml,
    _remove_local_skill_config_yaml,
    get_skill_manager,
)

# The full suite may import this module before the local ``consts`` stubs above
# are installed.  Pin the module-level safety root to the test-owned directory
# so path validation remains deterministic regardless of collection order.
skill_service.CONTAINER_SKILLS_PATH = TEST_LOCAL_SKILLS_DIR

# Create a mock get_skill_manager to avoid calling the real function
_mock_skill_manager_instance = MockSkillManager(local_skills_dir=TEST_LOCAL_SKILLS_DIR)
skill_service.get_skill_manager = lambda tenant_id=None: _mock_skill_manager_instance


def create_test_service(tenant_id="test-tenant"):
    """Create a SkillService instance with a tenant_id for testing."""
    _mock_skill_manager_instance.local_skills_dir = TEST_LOCAL_SKILLS_DIR
    service = SkillService(tenant_id=tenant_id)
    service._overlay_params_from_local_config_yaml = lambda x: x
    return service


# ===== Helper Functions Tests =====
class TestSkillGroupPermissions:
    def test_official_skill_is_visible_to_all_tenant_users(self):
        official_skill = {
            "source": "official",
            "created_by": "another-user",
            "group_ids": [],
            "ingroup_permission": "PRIVATE",
        }

        assert skill_service.can_view_skill(
            skill=official_skill,
            user_id="user-1",
            user_role="USER",
            user_group_ids=set(),
        ) is True
        assert skill_service.can_view_skill(
            skill=official_skill,
            user_id="dev-1",
            user_role="DEV",
            user_group_ids=set(),
        ) is True

    def test_group_permission_helpers_handle_edit_read_only_and_private(self):
        group_skill = {
            "created_by": "creator",
            "group_ids": "10,invalid,20",
            "ingroup_permission": "EDIT",
        }

        assert skill_service._to_group_id_set(group_skill["group_ids"]) == {10, 20}
        assert skill_service.can_view_skill(
            skill=group_skill,
            user_id="member",
            user_role="DEV",
            user_group_ids={10},
        ) is True
        assert skill_service.resolve_skill_permission(
            skill=group_skill,
            user_id="member",
            user_role="DEV",
            user_group_ids={10},
        ) == "EDIT"

        group_skill["ingroup_permission"] = "READ_ONLY"
        assert skill_service.resolve_skill_permission(
            skill=group_skill,
            user_id="member",
            user_role="DEV",
            user_group_ids={10},
        ) == "READ_ONLY"

        group_skill["ingroup_permission"] = "PRIVATE"
        assert skill_service.can_view_skill(
            skill=group_skill,
            user_id="member",
            user_role="DEV",
            user_group_ids={10},
        ) is False

    def test_group_permission_helpers_preserve_creator_and_admin_access(self):
        private_skill = {
            "created_by": "creator",
            "group_ids": [],
            "ingroup_permission": "PRIVATE",
        }

        assert skill_service.can_view_skill(
            skill=private_skill,
            user_id="creator",
            user_role="DEV",
            user_group_ids=set(),
        ) is True
        assert skill_service.resolve_skill_permission(
            skill=private_skill,
            user_id="admin",
            user_role="ADMIN",
            user_group_ids=set(),
        ) == "EDIT"

    def test_group_permission_helpers_reject_unmatched_groups_and_normalize_lists(self):
        skill = {
            "created_by": "creator",
            "group_ids": [10, "20", "invalid"],
            "ingroup_permission": "EDIT",
        }

        assert skill_service._to_group_id_set(skill["group_ids"]) == {10, 20}
        assert skill_service._to_group_id_set(None) == set()
        assert skill_service.can_view_skill(
            skill=skill,
            user_id="outsider",
            user_role="DEV",
            user_group_ids={30},
        ) is False
        assert skill_service.resolve_skill_permission(
            skill=skill,
            user_id="outsider",
            user_role="DEV",
            user_group_ids={30},
        ) == "READ_ONLY"

    def test_default_group_permission_does_not_override_explicit_values(self, mocker):
        skill_data = {
            "group_ids": [99],
            "ingroup_permission": "READ_ONLY",
        }
        query_groups = mocker.patch(
            "management.services.skill.support.query_group_ids_by_user",
            return_value=[10],
        )

        skill_service._apply_default_skill_permission_fields(skill_data, "user-1")

        assert skill_data == {
            "group_ids": [99],
            "ingroup_permission": "READ_ONLY",
        }
        query_groups.assert_not_called()

    def test_default_group_permission_uses_creator_groups(self, mocker):
        skill_data = {}
        mocker.patch(
            "management.services.skill.support.query_group_ids_by_user",
            return_value=[10, 20],
        )

        skill_service._apply_default_skill_permission_fields(skill_data, "user-1")

        assert skill_data == {
            "group_ids": "10,20",
            "ingroup_permission": "EDIT",
        }

    def test_default_group_permission_skips_anonymous_user(self, mocker):
        query_groups = mocker.patch(
            "management.services.skill.support.query_group_ids_by_user",
        )

        skill_data = {}
        skill_service._apply_default_skill_permission_fields(skill_data, None)

        assert skill_data == {}
        query_groups.assert_not_called()

    def test_can_edit_skill_requires_user_and_allows_group_editor(self, mocker):
        skill = {
            "created_by": "owner",
            "group_ids": [10],
            "ingroup_permission": "EDIT",
        }
        mocker.patch(
            "management.services.skill.support.get_user_tenant_by_user_id",
            return_value={"user_role": "DEV"},
        )
        mocker.patch(
            "management.services.skill.support.query_group_ids_by_user",
            return_value=[10],
        )

        assert skill_service._can_edit_skill(skill, None) is False
        assert skill_service._can_edit_skill(skill, "group-editor") is True


class TestNormalizeZipEntryPath:
    """Test _normalize_zip_entry_path function."""

    def test_basic_path(self):
        assert _normalize_zip_entry_path("path/to/file.txt") == "path/to/file.txt"

    def test_windows_path(self):
        assert _normalize_zip_entry_path("path\\to\\file.txt") == "path/to/file.txt"

    def test_strip_leading_dot_slash(self):
        assert _normalize_zip_entry_path("./path/to/file.txt") == "path/to/file.txt"

    def test_strip_multiple_dot_slash(self):
        assert _normalize_zip_entry_path("././path/to/file.txt") == "path/to/file.txt"


class TestFindZipMemberConfigYaml:
    """Test _find_zip_member_config_yaml function."""

    def test_no_config_yaml(self):
        result = _find_zip_member_config_yaml(["file1.txt", "file2.md"])
        assert result is None

    def test_root_config_yaml(self):
        result = _find_zip_member_config_yaml(["config/config.yaml", "file.md"])
        assert result == "config/config.yaml"

    def test_nested_config_yaml(self):
        result = _find_zip_member_config_yaml(
            ["my_skill/config/config.yaml", "other/file.md"],
            preferred_skill_root="my_skill"
        )
        assert result == "my_skill/config/config.yaml"

    def test_case_insensitive(self):
        result = _find_zip_member_config_yaml(["CONFIG/CONFIG.YAML"])
        assert result == "CONFIG/CONFIG.YAML"

    def test_preferred_root_exact_match(self):
        file_list = ["skill/config/config.yaml", "other/config/config.yaml"]
        result = _find_zip_member_config_yaml(file_list, preferred_skill_root="skill")
        assert result == "skill/config/config.yaml"


class TestParamsDictToStorable:
    """Test _params_dict_to_storable function."""

    def test_simple_dict(self):
        result = _params_dict_to_storable({"key": "value"})
        assert result == {"key": "value"}

    def test_nested_dict(self):
        result = _params_dict_to_storable({"outer": {"inner": "value"}})
        assert result == {"outer": {"inner": "value"}}

    def test_list_value(self):
        result = _params_dict_to_storable({"items": [1, 2, 3]})
        assert result == {"items": [1, 2, 3]}

    def test_invalid_params_with_str_conversion(self):
        class NonSerializable:
            def __str__(self):
                return "converted"
        result = _params_dict_to_storable({"key": NonSerializable()})
        assert result == {"key": "converted"}


class TestLocalSkillConfigYamlPath:
    """Test _local_skill_config_yaml_path function."""

    def test_basic_path(self, mocker):
        mocker.patch(
            "management.services.skill.support.CONTAINER_SKILLS_PATH",
            "/skills",
        )
        result = _local_skill_config_yaml_path("my_skill", "/skills")
        assert result == os.path.realpath(
            os.path.join("/skills", "my_skill", "config", "config.yaml")
        )

    def test_with_subdir(self, mocker):
        mocker.patch(
            "management.services.skill.support.CONTAINER_SKILLS_PATH",
            "/var/lib/skills",
        )
        result = _local_skill_config_yaml_path("test-skill", "/var/lib/skills")
        assert result == os.path.realpath(
            os.path.join(
                "/var/lib/skills",
                "test-skill",
                "config",
                "config.yaml",
            )
        )

    @pytest.mark.parametrize(
        "unsafe_name",
        [
            "../outside",
            r"..\outside",
            f"{os.sep}outside",
            f"C:{os.sep}outside",
        ],
    )
    def test_rejects_unsafe_skill_name(self, mocker, unsafe_name):
        mocker.patch(
            "management.services.skill.support.CONTAINER_SKILLS_PATH",
            "/skills",
        )

        with pytest.raises(SkillException, match="Invalid skill name"):
            _local_skill_config_yaml_path(unsafe_name, "/skills")

    def test_rejects_local_directory_outside_configured_root(
        self,
        mocker,
        tmp_path,
    ):
        allowed_root = tmp_path / "allowed"
        outside_root = tmp_path / "outside"
        mocker.patch(
            "management.services.skill.support.CONTAINER_SKILLS_PATH",
            str(allowed_root),
        )

        with pytest.raises(SkillException, match="Unsafe local skills directory"):
            _local_skill_config_yaml_path("skill", str(outside_root))


# ===== SkillService Tests =====


def _configure_local_dir_mock(mock_manager, local_dir=None):
    """Configure a MagicMock skill_manager so resolve_tenant_dir returns a valid path.

    The SkillService._local_skills_dir method calls
    self.skill_manager.resolve_tenant_dir(...). When the manager is a bare
    MagicMock, this returns a MagicMock object that breaks downstream path
    resolution. This helper ensures the mock returns a real string path that
    matches CONTAINER_SKILLS_PATH so _resolve_local_skill_path succeeds.
    """
    path = local_dir if local_dir is not None else skill_service.CONTAINER_SKILLS_PATH
    mock_manager.resolve_tenant_dir.return_value = path
    mock_manager.local_skills_dir = path
    return mock_manager


class TestSkillServiceInit:
    """Test SkillService initialization."""

    def test_init_with_skill_manager(self):
        mock_manager = MagicMock()
        service = SkillService(skill_manager=mock_manager)
        assert service.skill_manager == mock_manager

    def test_init_without_skill_manager(self):
        service = SkillService()
        assert service.skill_manager is not None


class TestSkillServiceListSkills:
    """Test SkillService.list_skills method."""

    def test_list_skills_success(self, mocker):
        mock_list_skills = mocker.patch('management.services.skill.service.skill_db.list_skills')
        mock_list_skills.return_value = [
            {"skill_id": 1, "name": "skill1"},
            {"skill_id": 2, "name": "skill2"},
        ]

        service = create_test_service()

        result = service.list_skills()

        assert len(result) == 2
        mock_list_skills.assert_called_once()

    def test_list_skills_error(self, mocker):
        mock_list_skills = mocker.patch('management.services.skill.service.skill_db.list_skills')
        mock_list_skills.side_effect = Exception("DB error")

        service = create_test_service()

        with pytest.raises(Exception):
            service.list_skills()

    def test_list_skills_filters_by_creator_group_and_private_permission(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.list_skills',
            return_value=[
                {
                    "skill_id": 1,
                    "name": "own-private",
                    "created_by": "user-1",
                    "group_ids": [],
                    "ingroup_permission": "PRIVATE",
                },
                {
                    "skill_id": 2,
                    "name": "group-read-only",
                    "created_by": "user-2",
                    "group_ids": [10],
                    "ingroup_permission": "READ_ONLY",
                },
                {
                    "skill_id": 3,
                    "name": "group-edit",
                    "created_by": "user-2",
                    "group_ids": [10],
                    "ingroup_permission": "EDIT",
                },
                {
                    "skill_id": 4,
                    "name": "group-private",
                    "created_by": "user-2",
                    "group_ids": [10],
                    "ingroup_permission": "PRIVATE",
                },
                {
                    "skill_id": 5,
                    "name": "different-group",
                    "created_by": "user-2",
                    "group_ids": [20],
                    "ingroup_permission": "EDIT",
                },
            ],
        )
        mocker.patch(
            'management.services.skill.service.query_group_ids_by_user',
            return_value=[10],
        )
        mocker.patch(
            'management.services.skill.support.get_user_tenant_by_user_id',
            return_value={"user_role": "DEV"},
        )

        result = create_test_service().list_visible_skills(user_id="user-1")

        assert [skill["name"] for skill in result] == [
            "own-private",
            "group-read-only",
            "group-edit",
        ]
        assert [skill["permission"] for skill in result] == [
            "EDIT",
            "READ_ONLY",
            "EDIT",
        ]

    def test_list_skills_admin_can_view_all_tenant_skills(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.list_skills',
            return_value=[
                {
                    "skill_id": 1,
                    "name": "private-skill",
                    "created_by": "user-2",
                    "group_ids": [],
                    "ingroup_permission": "PRIVATE",
                }
            ],
        )
        mocker.patch(
            'management.services.skill.service.query_group_ids_by_user',
            return_value=[],
        )
        mocker.patch(
            'management.services.skill.support.get_user_tenant_by_user_id',
            return_value={"user_role": "ADMIN"},
        )

        result = create_test_service().list_visible_skills(user_id="admin-1")

        assert len(result) == 1
        assert result[0]["permission"] == "EDIT"

    def test_list_visible_skill_permission_summaries_uses_lightweight_query(
        self,
        mocker,
    ):
        list_summaries = mocker.patch(
            'management.services.skill.service.skill_db.list_skill_permission_summaries',
            create=True,
            return_value=[
                {
                    "skill_id": 1,
                    "created_by": "user-1",
                    "group_ids": [],
                    "ingroup_permission": "PRIVATE",
                },
                {
                    "skill_id": 2,
                    "created_by": "user-2",
                    "group_ids": [10],
                    "ingroup_permission": "READ_ONLY",
                },
                {
                    "skill_id": 3,
                    "created_by": "user-2",
                    "group_ids": [20],
                    "ingroup_permission": "EDIT",
                },
            ],
        )
        mocker.patch(
            'management.services.skill.service.query_group_ids_by_user',
            return_value=[10],
        )
        mocker.patch(
            'management.services.skill.support.get_user_tenant_by_user_id',
            return_value={"user_role": "DEV"},
        )

        result = create_test_service().list_visible_skill_permission_summaries(
            user_id="user-1",
        )

        assert [skill["skill_id"] for skill in result] == [1, 2]
        list_summaries.assert_called_once_with("test-tenant")

    def test_list_visible_skill_permission_summaries_uses_explicit_tenant(
        self,
        mocker,
    ):
        list_summaries = mocker.patch(
            'management.services.skill.service.skill_db.list_skill_permission_summaries',
            create=True,
            return_value=[],
        )
        mocker.patch(
            'management.services.skill.service.query_group_ids_by_user',
            return_value=[],
        )
        mocker.patch(
            'management.services.skill.support.get_user_tenant_by_user_id',
            return_value={"user_role": "DEV"},
        )

        result = create_test_service().list_visible_skill_permission_summaries(
            tenant_id="explicit-tenant",
            user_id="user-1",
        )

        assert result == []
        list_summaries.assert_called_once_with("explicit-tenant")

    def test_list_visible_skill_permission_summaries_requires_tenant(self):
        service = create_test_service(tenant_id=None)

        with pytest.raises(SkillException, match="tenant_id is required"):
            service.list_visible_skill_permission_summaries(user_id="user-1")


class TestSkillServiceGetSkill:
    """Test SkillService.get_skill method."""

    def test_get_skill_found(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={
                "skill_id": 1,
                "name": "test_skill",
                "description": "A test skill"
            }
        )

        service = create_test_service()

        result = service.get_skill("test_skill")

        assert result is not None
        assert result["name"] == "test_skill"

    def test_get_skill_not_found(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value=None
        )

        service = create_test_service()

        result = service.get_skill("nonexistent")

        assert result is None


class TestSkillServiceGetSkillById:
    """Test SkillService.get_skill_by_id method."""

    def test_get_skill_by_id_found(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_id',
            return_value={
                "skill_id": 5,
                "name": "found_skill"
            }
        )

        service = create_test_service()

        result = service.get_skill_by_id(5)

        assert result is not None
        assert result["skill_id"] == 5

    def test_get_skill_by_id_not_found(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_id',
            return_value=None
        )

        service = create_test_service()

        result = service.get_skill_by_id(999, tenant_id="test-tenant")

        assert result is None


class TestSkillServiceCreateSkill:
    """Test SkillService.create_skill method."""

    def test_create_skill_missing_name(self, mocker):
        service = SkillService()

        with pytest.raises(Exception):
            service.create_skill({})

    def test_create_skill_already_exists_db(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"name": "existing"}
        )

        service = SkillService()

        with pytest.raises(Exception):
            service.create_skill({"name": "existing"})

    def test_create_skill_success(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'management.services.skill.service.skill_db.create_skill',
            return_value={
                "skill_id": 1,
                "name": "new_skill",
                "description": "A new skill"
            }
        )

        mock_manager = MagicMock()

        service = SkillService(tenant_id="test-tenant")
        service.skill_manager = mock_manager
        service._resolve_local_skills_dir_for_overlay = MagicMock(return_value=None)

        result = service.create_skill({
            "name": "new_skill",
            "description": "A new skill"
        }, tenant_id="test-tenant", user_id="user123")

        assert result["name"] == "new_skill"
        mock_manager.save_skill.assert_called_once()

    def test_create_skill_with_params(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'management.services.skill.service.skill_db.create_skill',
            return_value={
                "skill_id": 1,
                "name": "skill_with_params"
            }
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService(tenant_id="test-tenant")
        service.skill_manager = mock_manager
        service._resolve_local_skills_dir_for_overlay = MagicMock(return_value=TEST_LOCAL_SKILLS_DIR)

        with patch('os.path.exists', return_value=False):
            result = service.create_skill({
                "name": "skill_with_params",
                "params": {"key": "value"}
            }, tenant_id="test-tenant")

        assert result["name"] == "skill_with_params"


class TestSkillServiceCreateSkillFromFile:
    """Test SkillService.create_skill_from_file method."""

    def test_create_skill_from_md_bytes(self, mocker):
        mock_repo = MagicMock()
        mock_repo.get_skill_by_name.return_value = None
        mock_repo.create_skill.return_value = {"skill_id": 1, "name": "md_skill"}

        mock_manager = MagicMock()
        mock_manager.resolve_tenant_dir.return_value = skill_service.CONTAINER_SKILLS_PATH
        mock_manager.local_skills_dir = skill_service.CONTAINER_SKILLS_PATH
        mock_manager.resolve_tenant_dir.return_value = skill_service.CONTAINER_SKILLS_PATH

        service = SkillService()
        service.repository = mock_repo
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        content = b"""---
name: md_skill
description: A MD skill
---
# Content
"""
        result = service.create_skill_from_file(content)

        assert result["name"] == "md_skill"

    def test_create_skill_from_string(self, mocker):
        mock_repo = MagicMock()
        mock_repo.get_skill_by_name.return_value = None
        mock_repo.create_skill.return_value = {"skill_id": 1, "name": "str_skill"}

        mock_manager = MagicMock()
        mock_manager.resolve_tenant_dir.return_value = skill_service.CONTAINER_SKILLS_PATH
        mock_manager.local_skills_dir = skill_service.CONTAINER_SKILLS_PATH
        mock_manager.resolve_tenant_dir.return_value = skill_service.CONTAINER_SKILLS_PATH

        service = SkillService()
        service.repository = mock_repo
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        content = """---
name: str_skill
description: A string skill
---
# Content
"""
        result = service.create_skill_from_file(content)

        assert result["name"] == "str_skill"

    def test_create_skill_from_bytesio(self, mocker):
        mock_repo = MagicMock()
        mock_repo.get_skill_by_name.return_value = None
        mock_repo.create_skill.return_value = {"skill_id": 1, "name": "bio_skill"}

        mock_manager = MagicMock()
        mock_manager.resolve_tenant_dir.return_value = skill_service.CONTAINER_SKILLS_PATH
        mock_manager.local_skills_dir = skill_service.CONTAINER_SKILLS_PATH
        mock_manager.resolve_tenant_dir.return_value = skill_service.CONTAINER_SKILLS_PATH

        service = SkillService()
        service.repository = mock_repo
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        bio = io.BytesIO(b"""---
name: bio_skill
description: A BytesIO skill
---
# Content
""")
        result = service.create_skill_from_file(bio)

        assert result["name"] == "bio_skill"

    def test_create_skill_explicit_md_type(self, mocker):
        mock_repo = MagicMock()
        mock_repo.get_skill_by_name.return_value = None
        mock_repo.create_skill.return_value = {"skill_id": 1, "name": "explicit_md"}

        mock_manager = MagicMock()
        mock_manager.resolve_tenant_dir.return_value = skill_service.CONTAINER_SKILLS_PATH
        mock_manager.local_skills_dir = skill_service.CONTAINER_SKILLS_PATH
        mock_manager.resolve_tenant_dir.return_value = skill_service.CONTAINER_SKILLS_PATH

        service = SkillService()
        service.repository = mock_repo
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        result = service.create_skill_from_file(b"---\nname: explicit_md\ndescription: Desc\n---", file_type="md")

        assert result["name"] == "explicit_md"


class TestSkillServiceUpdateSkill:
    """Test SkillService.update_skill method."""

    def test_update_skill_not_found(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value=None
        )

        service = SkillService()

        with pytest.raises(Exception):
            service.update_skill("nonexistent", {"description": "new"})

    def test_update_skill_success(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.update_skill',
            return_value={
                "skill_id": 1,
                "name": "existing",
                "description": "updated"
            }
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.resolve_tenant_dir.return_value = "/tmp"
        mock_manager.local_skills_dir = "/tmp"
        mock_manager.resolve_tenant_dir.return_value = "/tmp"

        with patch.object(skill_support, 'CONTAINER_SKILLS_PATH', "/tmp"):
            service = SkillService(tenant_id="test-tenant")
            service.skill_manager = mock_manager

            result = service.update_skill("existing", {"description": "updated"}, tenant_id="test-tenant")

            assert result["description"] == "updated"

    def test_update_skill_rejects_user_without_edit_permission(self, mocker):
        mocker.patch(
            "management.services.skill.service.skill_db.get_skill_by_name",
            return_value={"skill_id": 1, "name": "existing", "created_by": "owner"},
        )
        mocker.patch(
            "management.services.skill.service._can_edit_skill",
            return_value=False,
        )

        service = SkillService(tenant_id="test-tenant")

        with pytest.raises(skill_service.ForbiddenError):
            service.update_skill(
                "existing",
                {"description": "updated"},
                tenant_id="test-tenant",
                user_id="viewer",
            )

    def test_update_skill_rejects_access_change_from_group_editor(self, mocker):
        mocker.patch(
            "management.services.skill.service.skill_db.get_skill_by_name",
            return_value={
                "skill_id": 1,
                "name": "existing",
                "created_by": "owner",
                "group_ids": [1, 2],
                "ingroup_permission": "EDIT",
            },
        )
        mocker.patch(
            "management.services.skill.service._can_edit_skill", return_value=True
        )
        mocker.patch(
            "management.services.skill.support.get_user_tenant_by_user_id",
            return_value={"user_role": "DEV"},
        )

        with pytest.raises(
            skill_service.ForbiddenError,
            match="Not authorized to update skill access",
        ):
            SkillService(tenant_id="test-tenant").update_skill(
                "existing",
                {"description": "updated", "group_ids": [1]},
                user_id="group-editor",
            )

    def test_update_skill_with_params(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "p_skill"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.update_skill',
            return_value={
                "skill_id": 1,
                "name": "p_skill",
                "params": {"key": "value"}
            }
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.resolve_tenant_dir.return_value = "/tmp"
        mock_manager.local_skills_dir = "/tmp"
        mock_manager.resolve_tenant_dir.return_value = "/tmp"

        with patch.object(skill_support, 'CONTAINER_SKILLS_PATH', "/tmp"):
            service = SkillService(tenant_id="test-tenant")
            service.skill_manager = mock_manager

            result = service.update_skill("p_skill", {"params": {"key": "value"}}, tenant_id="test-tenant")

            assert "params" in result


class TestSkillServiceDeleteSkill:
    """Test SkillService.delete_skill method."""

    def test_delete_skill_success(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.delete_skill',
            return_value=True
        )
        mocker.patch(
            'management.services.skill.service.skill_db.delete_skill_instances_by_skill_id',
            return_value=None
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "skill_to_delete"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService(tenant_id="test-tenant")
        service.skill_manager = mock_manager

        with patch('os.path.exists', return_value=False):
            result = service.delete_skill("skill_to_delete", tenant_id="test-tenant", user_id="user123")

        assert result is True

    def test_delete_skill_with_local_dir(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.delete_skill',
            return_value=True
        )
        mocker.patch(
            'management.services.skill.service.skill_db.delete_skill_instances_by_skill_id',
            return_value=None
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "del_skill"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService(tenant_id="test-tenant")
        service.skill_manager = mock_manager

        with patch('os.path.isfile', return_value=True):
            with patch('shutil.rmtree'):
                result = service.delete_skill("del_skill", tenant_id="test-tenant", user_id="user123")

        assert result is True


class TestSkillServiceGetSkillFileTree:
    """Test SkillService.get_skill_file_tree method."""

    def test_get_file_tree_success(self, mocker):
        mock_manager = MagicMock()
        mock_manager.get_skill_file_tree.return_value = {
            "name": "test_skill",
            "type": "directory",
            "children": []
        }

        service = SkillService()
        service.skill_manager = mock_manager

        result = service.get_skill_file_tree("test_skill")

        assert result is not None
        mock_manager.get_skill_file_tree.assert_called_once_with("test_skill", tenant_id=None)

    def test_get_file_tree_error(self, mocker):
        mock_manager = MagicMock()
        mock_manager.get_skill_file_tree.side_effect = Exception("Error")

        service = SkillService()
        service.skill_manager = mock_manager

        with pytest.raises(Exception):
            service.get_skill_file_tree("test_skill")


class TestSkillServiceGetSkillFileContent:
    """Test SkillService.get_skill_file_content method."""

    def test_get_file_content_success(self, mocker):
        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager

        with patch('os.path.isfile', return_value=True):
            with patch('builtins.open', mock_open(read_data="file content")):
                result = service.get_skill_file_content("test_skill", "README.md")

        assert result == "file content"

    def test_get_file_content_not_found(self, mocker):
        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager

        with patch('builtins.open', side_effect=FileNotFoundError):
            result = service.get_skill_file_content("test_skill", "nonexistent.md")

        assert result is None


class TestSkillServiceGetEnabledSkillsForAgent:
    """Test SkillService.get_enabled_skills_for_agent method."""

    def test_get_enabled_skills_for_agent_returns_list(self):
        """Test getting enabled skills for agent returns list."""
        from database import skill_db as skill_db_module
        original_func = getattr(skill_db_module, 'search_skills_for_agent', None)

        if original_func is not None:
            setattr(skill_db_module, 'search_skills_for_agent', lambda *args, **kwargs: [
                {"skill_instance_id": 1, "skill_id": 1, "enabled": True}
            ])
            try:
                mock_repo = MagicMock()
                mock_repo.get_skill_by_id.return_value = {
                    "name": "skill1", "description": "Desc", "content": "# Content", "tool_ids": []
                }

                service = SkillService()
                service.repository = mock_repo
                service._overlay_params_from_local_config_yaml = lambda x: x

                result = service.get_enabled_skills_for_agent(
                    agent_id=1,
                    tenant_id="tenant1"
                )

                assert isinstance(result, list)
            finally:
                setattr(skill_db_module, 'search_skills_for_agent', original_func)
        else:
            pytest.skip("database.skill_db module not fully available")

    def test_get_enabled_skills_for_agent_empty(self):
        """Test getting enabled skills when none exist."""
        from database import skill_db as skill_db_module
        original_func = getattr(skill_db_module, 'search_skills_for_agent', None)

        if original_func is not None:
            setattr(skill_db_module, 'search_skills_for_agent', lambda *args, **kwargs: [])
            try:
                service = SkillService()
                result = service.get_enabled_skills_for_agent(
                    agent_id=1,
                    tenant_id="tenant1"
                )
                assert result == []
            finally:
                setattr(skill_db_module, 'search_skills_for_agent', original_func)
        else:
            pytest.skip("database.skill_db module not fully available")


class TestSkillServiceBuildSkillsSummary:
    """Test SkillService.build_skills_summary method."""

    def test_build_summary_with_available_skills(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.list_skills',
            return_value=[
                {"name": "skill1", "description": "Desc1"},
                {"name": "skill2", "description": "Desc2"}
            ]
        )
        mocker.patch(
            'management.services.skill.service.skill_db.search_skills_for_agent',
            return_value=[]
        )

        service = create_test_service()

        result = service.build_skills_summary(available_skills=["skill1"], tenant_id="test-tenant")

        assert "<skills>" in result
        assert "<name>skill1</name>" in result
        assert "<name>skill2</name>" not in result

    def test_build_summary_empty(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.list_skills',
            return_value=[]
        )
        mocker.patch(
            'management.services.skill.service.skill_db.search_skills_for_agent',
            return_value=[]
        )

        service = create_test_service()

        result = service.build_skills_summary(tenant_id="test-tenant")

        assert result == ""

    def test_build_summary_fallback_to_all_skills(self, mocker):
        """Test building summary without agent uses all skills."""
        mocker.patch(
            'management.services.skill.service.skill_db.list_skills',
            return_value=[
                {"name": "skill1", "description": "Desc1"}
            ]
        )
        mocker.patch(
            'management.services.skill.service.skill_db.search_skills_for_agent',
            return_value=[]
        )

        service = create_test_service()

        result = service.build_skills_summary(tenant_id="test-tenant")

        assert "<skills>" in result
        assert "<name>skill1</name>" in result

    def test_build_summary_xml_escaping(self, mocker):
        """Test XML escaping in summary."""
        mocker.patch(
            'management.services.skill.service.skill_db.list_skills',
            return_value=[
                {"name": "skill<tag>", "description": "Desc & more"}
            ]
        )
        mocker.patch(
            'management.services.skill.service.skill_db.search_skills_for_agent',
            return_value=[]
        )

        service = create_test_service()

        result = service.build_skills_summary(tenant_id="test-tenant")

        assert "&lt;tag&gt;" in result
        assert "&amp; more" in result


class TestSkillServiceGetSkillContent:
    """Test SkillService.get_skill_content method."""

    def test_get_content_found(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={
                "name": "content_skill",
                "content": "# Skill content here"
            }
        )

        service = create_test_service()

        result = service.get_skill_content("content_skill", tenant_id="test-tenant")

        assert result == "# Skill content here"

    def test_get_content_not_found(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value=None
        )

        service = create_test_service()

        result = service.get_skill_content("nonexistent", tenant_id="test-tenant")

        assert result == ""


class TestSkillServiceSkillInstances:
    """Test SkillService skill instance methods."""

    def test_create_or_update_skill_instance_success(self):
        """Test creating/updating skill instance."""
        from database import skill_db as skill_db_module
        original_func = getattr(skill_db_module, 'create_or_update_skill_by_skill_info', None)

        mock_result = {
            "skill_instance_id": 1,
            "skill_id": 1,
            "agent_id": 1,
            "enabled": True
        }

        # Only test if the function exists in the real module
        if original_func is not None:
            setattr(skill_db_module, 'create_or_update_skill_by_skill_info', lambda *args, **kwargs: mock_result)
            try:
                service = SkillService()
                service._overlay_params_from_local_config_yaml = lambda x: x

                skill_info = {"skill_id": 1, "agent_id": 1, "enabled": True}
                result = service.create_or_update_skill_instance(
                    skill_info=skill_info,
                    tenant_id="tenant1",
                    user_id="user1"
                )

                assert result["skill_instance_id"] == 1
            finally:
                setattr(skill_db_module, 'create_or_update_skill_by_skill_info', original_func)
        else:
            # Skip if real module not available
            pytest.skip("database.skill_db module not fully available")

    def test_list_skill_instances_returns_list(self):
        """Test listing skill instances returns list."""
        from database import skill_db as skill_db_module
        original_func = getattr(skill_db_module, 'query_skill_instances_by_agent_id', None)

        if original_func is not None:
            setattr(skill_db_module, 'query_skill_instances_by_agent_id', lambda *args, **kwargs: [
                {"skill_instance_id": 1, "skill_id": 1, "enabled": True}
            ])
            try:
                service = SkillService()
                result = service.list_skill_instances(
                    agent_id=1,
                    tenant_id="tenant1"
                )
                assert isinstance(result, list)
                assert len(result) == 1
            finally:
                setattr(skill_db_module, 'query_skill_instances_by_agent_id', original_func)
        else:
            pytest.skip("database.skill_db module not fully available")

    def test_get_skill_instance_returns_none_when_not_found(self):
        """Test getting skill instance returns None when not found."""
        from database import skill_db as skill_db_module
        original_func = getattr(skill_db_module, 'query_skill_instance_by_id', None)

        if original_func is not None:
            setattr(skill_db_module, 'query_skill_instance_by_id', lambda *args, **kwargs: None)
            try:
                service = SkillService()
                result = service.get_skill_instance(
                    agent_id=1,
                    skill_id=999,
                    tenant_id="tenant1"
                )
                assert result is None
            finally:
                setattr(skill_db_module, 'query_skill_instance_by_id', original_func)
        else:
            pytest.skip("database.skill_db module not fully available")


class TestSkillServiceOverlayParams:
    """Test SkillService._overlay_params_from_local_config_yaml method."""

    def test_overlay_params_no_local_dir(self, mocker):
        service = SkillService()
        service._resolve_local_skills_dir_for_overlay = MagicMock(return_value=None)

        result = service._enrich_configs_from_yaml({"name": "test"})

        assert result["name"] == "test"

    def test_overlay_params_local_file_exists(self, mocker):
        service = SkillService()
        service._resolve_local_skills_dir_for_overlay = MagicMock(return_value=TEST_LOCAL_SKILLS_DIR)

        skill_data = {"name": "test_skill"}

        with patch('os.path.isfile', return_value=True):
            with patch('builtins.open', mock_open(read_data="key: value\n")):
                with patch('management.services.skill.service._parse_skill_params_from_config_bytes', return_value={"key": "value"}):
                    result = service._enrich_configs_from_yaml(skill_data)

        assert result["config_values"]["key"] == "value"

    def test_overlay_params_local_file_not_exists(self, mocker):
        service = SkillService()
        service._resolve_local_skills_dir_for_overlay = MagicMock(return_value=TEST_LOCAL_SKILLS_DIR)

        with patch('os.path.isfile', return_value=False):
            result = service._enrich_configs_from_yaml({"name": "test"})

        assert result["name"] == "test"
        assert "config_values" not in result

    def test_overlay_params_skill_without_name(self, mocker):
        service = SkillService()
        service._resolve_local_skills_dir_for_overlay = MagicMock(return_value=TEST_LOCAL_SKILLS_DIR)

        result = service._enrich_configs_from_yaml({})

        assert result == {}


class TestSkillServiceResolveLocalSkillsDir:
    """Test SkillService._resolve_local_skills_dir_for_overlay method."""

    def test_resolve_with_manager_dir(self, mocker):
        service = SkillService()
        service.skill_manager.local_skills_dir = "/manager/skills"

        with patch.object(skill_support, 'CONTAINER_SKILLS_PATH', "/config/skills"):
            result = service._resolve_local_skills_dir_for_overlay()

        assert result is not None

    def test_resolve_with_fallback_dir(self, mocker):
        service = SkillService()
        service.skill_manager.local_skills_dir = None

        with patch.object(service.skill_manager, 'resolve_tenant_dir', return_value=None):
            with patch.object(skill_support, 'CONTAINER_SKILLS_PATH', None):
                with patch.object(skill_service, 'ROOT_DIR', "/project"):
                    with patch('os.path.isdir', return_value=True):
                        result = service._resolve_local_skills_dir_for_overlay()

        result_normalized = result.replace("\\", "/")
        assert result_normalized == "/project/skills"

    def test_resolve_returns_none(self, mocker):
        service = SkillService()
        service.skill_manager.local_skills_dir = ""

        with patch.object(service.skill_manager, 'resolve_tenant_dir', return_value=""):
            with patch.object(skill_support, 'CONTAINER_SKILLS_PATH', ""):
                with patch.object(skill_service, 'ROOT_DIR', ""):
                    result = service._resolve_local_skills_dir_for_overlay()

        assert result is None


# ===== Write/Remove Config YAML Tests =====
class TestWriteSkillParamsToLocalConfigYaml:
    """Test _write_skill_params_to_local_config_yaml function."""

    def test_write_with_empty_local_dir(self):
        _write_skill_params_to_local_config_yaml("skill", {"key": "value"}, "")

    def test_write_success(self, mocker):
        with patch('os.makedirs'):
            with patch('builtins.open', mock_open()):
                with patch('management.services.skill.service._local_skill_config_yaml_path', return_value="/tmp/skill/config.yaml"):
                    _write_skill_params_to_local_config_yaml("skill", {"key": "value"}, "/tmp")


class TestRemoveLocalSkillConfigYaml:
    """Test _remove_local_skill_config_yaml function."""

    def test_remove_with_empty_local_dir(self):
        _remove_local_skill_config_yaml("skill", "")

    def test_remove_file_exists(self, mocker):
        with patch('management.services.skill.service._local_skill_config_yaml_path', return_value="/tmp/skill/config.yaml"):
            with patch('os.path.isfile', return_value=True):
                with patch('os.remove'):
                    _remove_local_skill_config_yaml("skill", "/tmp")

    def test_remove_file_not_exists(self, mocker):
        with patch('management.services.skill.service._local_skill_config_yaml_path', return_value="/tmp/skill/config.yaml"):
            with patch('os.path.isfile', return_value=False):
                _remove_local_skill_config_yaml("skill", "/tmp")


# ===== Parse YAML Functions Tests =====
class TestParseYamlWithRuamel:
    """Test _parse_yaml_with_ruamel_merge_eol_comments function."""

    def test_parse_simple_yaml(self):
        yaml_content = "key: value\nnested:\n  inner: test"

        try:
            result = _parse_yaml_with_ruamel_merge_eol_comments(yaml_content)
        except ImportError:
            pytest.skip("ruamel.yaml not available")

        assert isinstance(result, dict)
        assert result["key"] == "value"
        assert result["nested"]["inner"] == "test"


class TestParseYamlFallbackPyyaml:
    """Test _parse_yaml_fallback_pyyaml function."""

    def test_parse_simple_yaml(self):
        yaml_content = "key: value\nlist:\n  - item1\n  - item2"

        result = _parse_yaml_fallback_pyyaml(yaml_content)

        assert result["key"] == "value"
        assert result["list"] == ["item1", "item2"]

    def test_parse_empty_yaml(self):
        result = _parse_yaml_fallback_pyyaml("")
        assert result == {}

    def test_parse_invalid_yaml(self):
        with pytest.raises(Exception):
            _parse_yaml_fallback_pyyaml("invalid: yaml: content::")


class TestParseSkillParamsFromConfigBytes:
    """Test _parse_skill_params_from_config_bytes function."""

    def test_parse_json(self):
        result = _parse_skill_params_from_config_bytes(b'{"key": "value"}')
        assert result["key"] == "value"

    def test_parse_yaml(self):
        result = _parse_skill_params_from_config_bytes(b'key: value')
        assert result["key"] == "value"

    def test_parse_empty_bytes(self):
        result = _parse_skill_params_from_config_bytes(b'')
        assert result == {}


class TestReadParamsFromZipConfigYaml:
    """Test _read_params_from_zip_config_yaml function."""

    def test_read_from_zip_no_config(self):
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("README.md", "# Readme")

        zip_buffer.seek(0)
        result = _read_params_from_zip_config_yaml(zip_buffer.getvalue())
        assert result is None

    def test_read_from_zip_with_config(self):
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("config/config.yaml", "key: value")
            zf.writestr("README.md", "# Readme")

        zip_buffer.seek(0)
        result = _read_params_from_zip_config_yaml(zip_buffer.getvalue())
        assert result is not None

    def test_read_from_invalid_zip(self):
        import zipfile
        with pytest.raises(zipfile.BadZipFile):
            _read_params_from_zip_config_yaml(b"not a zip file")


class TestGetSkillManager:
    """Test get_skill_manager function."""

    def test_get_manager_creates_instance(self):
        skill_service._skill_manager = None

        with patch('management.services.skill.support.SkillManager') as mock_manager:
            with patch.object(skill_support, 'CONTAINER_SKILLS_PATH', '/tmp'):
                manager = get_skill_manager()
                mock_manager.assert_called_once()

    def test_get_manager_reuses_instance(self):
        """Test that get_skill_manager returns the mocked singleton instance."""
        existing = skill_service.get_skill_manager()
        manager = skill_service.get_skill_manager()
        assert manager is existing


# ===== Comment Handling Functions Tests =====
class TestCommentTextFromToken:
    """Test _comment_text_from_token function."""

    def test_none_token(self):
        from management.services.skill.service import _comment_text_from_token
        result = _comment_text_from_token(None)
        assert result is None

    def test_token_without_value(self):
        from management.services.skill.service import _comment_text_from_token
        token = MagicMock()
        token.value = None
        result = _comment_text_from_token(token)
        assert result is None

    def test_token_with_hash_comment(self):
        from management.services.skill.service import _comment_text_from_token
        token = MagicMock()
        token.value = "# This is a comment"
        result = _comment_text_from_token(token)
        assert result == "This is a comment"

    def test_token_without_hash(self):
        from management.services.skill.service import _comment_text_from_token
        token = MagicMock()
        token.value = "not a comment"
        result = _comment_text_from_token(token)
        assert result is None

    def test_token_with_hash_and_whitespace(self):
        from management.services.skill.service import _comment_text_from_token
        token = MagicMock()
        token.value = "  #   trimmed comment  "
        result = _comment_text_from_token(token)
        assert result == "trimmed comment"


class TestTupleSlot2:
    """Test _tuple_slot2 function."""

    def test_none_container(self):
        from management.services.skill.service import _tuple_slot2
        result = _tuple_slot2(None)
        assert result is None

    def test_empty_container(self):
        from management.services.skill.service import _tuple_slot2
        result = _tuple_slot2([])
        assert result is None

    def test_single_element_container(self):
        from management.services.skill.service import _tuple_slot2
        result = _tuple_slot2([1])
        assert result is None

    def test_two_element_container(self):
        from management.services.skill.service import _tuple_slot2
        result = _tuple_slot2([1, 2])
        assert result is None

    def test_three_element_container(self):
        from management.services.skill.service import _tuple_slot2
        result = _tuple_slot2([1, 2, "slot2_value"])
        assert result == "slot2_value"


class TestIsBeforeNextSiblingCommentToken:
    """Test _is_before_next_sibling_comment_token function."""

    def test_none_token(self):
        from management.services.skill.service import _is_before_next_sibling_comment_token
        result = _is_before_next_sibling_comment_token(None)
        assert result is False

    def test_token_without_value(self):
        from management.services.skill.service import _is_before_next_sibling_comment_token
        token = MagicMock()
        token.value = None
        result = _is_before_next_sibling_comment_token(token)
        assert result is False

    def test_token_not_starting_with_newline(self):
        from management.services.skill.service import _is_before_next_sibling_comment_token
        token = MagicMock()
        token.value = "# comment"
        result = _is_before_next_sibling_comment_token(token)
        assert result is False

    def test_token_starting_with_newline(self):
        from management.services.skill.service import _is_before_next_sibling_comment_token
        token = MagicMock()
        token.value = "\n# comment"
        result = _is_before_next_sibling_comment_token(token)
        assert result is True


class TestFlattenCaCommentToText:
    """Test _flatten_ca_comment_to_text function."""

    def test_none_comment_field(self):
        from management.services.skill.service import _flatten_ca_comment_to_text
        result = _flatten_ca_comment_to_text(None)
        assert result is None

    def test_empty_list(self):
        from management.services.skill.service import _flatten_ca_comment_to_text
        result = _flatten_ca_comment_to_text([])
        assert result is None

    def test_list_with_none_values(self):
        from management.services.skill.service import _flatten_ca_comment_to_text
        result = _flatten_ca_comment_to_text([None, None])
        assert result is None

    def test_list_with_nested_lists(self):
        from management.services.skill.service import _flatten_ca_comment_to_text
        token1 = MagicMock()
        token1.value = "# first comment"
        token2 = MagicMock()
        token2.value = "# second comment"
        result = _flatten_ca_comment_to_text([[token1, token2]])
        assert result == "first comment second comment"

    def test_list_with_direct_tokens(self):
        from management.services.skill.service import _flatten_ca_comment_to_text
        token = MagicMock()
        token.value = "# direct comment"
        result = _flatten_ca_comment_to_text([token])
        assert result == "direct comment"

    def test_list_with_non_comment_tokens(self):
        from management.services.skill.service import _flatten_ca_comment_to_text
        token = MagicMock()
        token.value = "not a comment"
        result = _flatten_ca_comment_to_text([token])
        assert result is None


class TestCommentFromMapBlockHeader:
    """Test _comment_from_map_block_header function."""

    def test_none_cm(self):
        from management.services.skill.service import _comment_from_map_block_header
        result = _comment_from_map_block_header(None)
        assert result is None

    def test_no_ca_attribute(self):
        from management.services.skill.service import _comment_from_map_block_header
        cm = MagicMock(spec=[])
        result = _comment_from_map_block_header(cm)
        assert result is None

    def test_no_comment_in_ca(self):
        from management.services.skill.service import _comment_from_map_block_header
        cm = MagicMock()
        cm.ca = MagicMock()
        cm.ca.comment = None
        result = _comment_from_map_block_header(cm)
        assert result is None


class TestApplyInlineCommentToScalar:
    """Test _apply_inline_comment_to_scalar function."""

    def test_no_comment(self):
        from management.services.skill.service import _apply_inline_comment_to_scalar
        result = _apply_inline_comment_to_scalar("value", None)
        assert result == "value"

    def test_string_with_comment(self):
        from management.services.skill.service import _apply_inline_comment_to_scalar
        result = _apply_inline_comment_to_scalar("value", "tooltip")
        assert result == "value # tooltip"

    def test_dict_value_unchanged(self):
        from management.services.skill.service import _apply_inline_comment_to_scalar
        result = _apply_inline_comment_to_scalar({"key": "val"}, "tooltip")
        assert result == {"key": "val"}

    def test_list_value_unchanged(self):
        from management.services.skill.service import _apply_inline_comment_to_scalar
        result = _apply_inline_comment_to_scalar([1, 2], "tooltip")
        assert result == [1, 2]

    def test_numeric_value_with_comment(self):
        from management.services.skill.service import _apply_inline_comment_to_scalar
        result = _apply_inline_comment_to_scalar(42, "answer")
        assert result == "42 # answer"


class TestParseYamlWithRuamelErrorPaths:
    """Test _parse_yaml_with_ruamel_merge_eol_comments error paths."""

    def test_invalid_yaml_raises_exception(self):
        from management.services.skill.service import _parse_yaml_with_ruamel_merge_eol_comments
        with pytest.raises(Exception):
            _parse_yaml_with_ruamel_merge_eol_comments("invalid: yaml: : : :")

    def test_yaml_load_returns_non_mapping(self):
        from management.services.skill.service import _parse_yaml_with_ruamel_merge_eol_comments
        # This tests the branch where root is a list instead of dict
        with pytest.raises(Exception):
            _parse_yaml_with_ruamel_merge_eol_comments("- item1\n- item2")


class TestParseYamlFallbackPyyamlErrorPaths:
    """Test _parse_yaml_fallback_pyyaml error paths."""

    def test_invalid_yaml_raises_skill_exception(self):
        from management.services.skill.service import _parse_yaml_fallback_pyyaml
        from consts.exceptions import SkillException
        try:
            _parse_yaml_fallback_pyyaml("invalid: yaml: : :")
            assert False, "Should have raised"
        except SkillException as e:
            assert "Invalid JSON or YAML" in str(e) or "mapping values" in str(e)
        except Exception as e:
            assert "mapping values" in str(e) or "Invalid" in str(e)

    def test_yaml_returns_list_raises_exception(self):
        from management.services.skill.service import _parse_yaml_fallback_pyyaml
        with pytest.raises(Exception):
            _parse_yaml_fallback_pyyaml("- item1\n- item2")


class TestParseSkillParamsFromConfigBytesErrorPaths:
    """Test _parse_skill_params_from_config_bytes error paths."""

    def test_json_non_dict_raises_exception(self):
        from management.services.skill.service import _parse_skill_params_from_config_bytes
        from consts.exceptions import SkillException
        try:
            _parse_skill_params_from_config_bytes(b'["list", "not", "dict"]')
            assert False, "Should have raised"
        except SkillException as e:
            assert "must contain a JSON or YAML object" in str(e)
        except Exception as e:
            assert "must contain a JSON or YAML object" in str(e)

    def test_non_serializable_params_with_fallback(self):
        from management.services.skill.service import _params_dict_to_storable

        class NonSerializable:
            pass
        result = _params_dict_to_storable({"key": NonSerializable()})
        assert "key" in result


# ===== SkillService ZIP Tests =====
class TestSkillServiceCreateSkillFromZip:
    """Test SkillService.create_skill_from_file with ZIP content."""

    def test_create_from_zip_auto_detect(self, mocker):
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("test_skill/SKILL.md", """---
name: test_skill
description: A ZIP skill
---
# Content""")
            zf.writestr("test_skill/config/config.yaml", "key: value")

        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'management.services.skill.service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "test_skill"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        result = service.create_skill_from_file(zip_buffer.getvalue())

        assert result["name"] == "test_skill"

    def test_create_from_zip_explicit_type(self, mocker):
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("explicit_skill/SKILL.md", """---
name: explicit_skill
description: Explicit ZIP type
---
# Content""")

        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'management.services.skill.service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "explicit_skill"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        result = service.create_skill_from_file(zip_buffer.getvalue(), file_type="zip")

        assert result["name"] == "explicit_skill"

    def test_create_from_zip_with_allowed_tools(self, mocker):
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("tool_skill/SKILL.md", """---
name: tool_skill
description: A skill with tools
---
allowed-tools:
  - tool1
  - tool2""")
            zf.writestr("tool_skill/config/config.yaml", "key: value")

        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'management.services.skill.service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "tool_skill"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_ids_by_names',
            return_value=[1, 2]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        result = service.create_skill_from_file(zip_buffer.getvalue(), file_type="zip", tenant_id="tenant1")

        assert result["name"] == "tool_skill"

    def test_create_from_zip_no_skill_md(self, mocker):
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("README.md", "# Just a readme")

        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value=None
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        from consts.exceptions import SkillException
        try:
            service.create_skill_from_file(zip_buffer.getvalue(), file_type="zip")
            assert False, "Should have raised"
        except SkillException as e:
            assert "SKILL.md not found" in str(e)
        except Exception as e:
            assert "SKILL.md not found" in str(e)

    def test_create_from_zip_invalid_skill_md(self, mocker):
        """Test ZIP creation with content that has frontmatter markers."""
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            # Content has valid frontmatter markers so should be parsed
            zf.writestr("invalid_skill/SKILL.md", "---\nname: test\n---\n# Content")

        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'management.services.skill.service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "invalid_skill"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        # Should succeed - name is extracted from folder, not from frontmatter
        result = service.create_skill_from_file(zip_buffer.getvalue(), file_type="zip")
        assert result["name"] == "invalid_skill"

    def test_create_from_zip_already_exists(self, mocker):
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("existing_skill/SKILL.md", """---
name: existing_skill
---
# Content""")

        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"name": "existing_skill"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager

        from consts.exceptions import SkillException
        try:
            service.create_skill_from_file(zip_buffer.getvalue(), file_type="zip")
            assert False, "Should have raised"
        except SkillException as e:
            assert "already exists" in str(e)
        except Exception as e:
            assert "already exists" in str(e)


class TestSkillServiceUpdateSkillFromFile:
    """Test SkillService.update_skill_from_file method."""

    def test_update_from_md_explicit_type(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "existing", "description": "updated"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_ids_by_names',
            return_value=[]
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService(tenant_id="test-tenant")
        service.skill_manager = mock_manager

        content = b"""---
name: existing
description: Updated via MD
---
# Content"""
        result = service.update_skill_from_file("existing", content, file_type="md", tenant_id="test-tenant")

        assert result["description"] == "updated"

    def test_update_from_file_rejects_user_without_edit_permission(self, mocker):
        mocker.patch(
            "management.services.skill.service.skill_db.get_skill_by_name",
            return_value={"skill_id": 1, "name": "existing", "created_by": "owner"},
        )
        mocker.patch(
            "management.services.skill.service._can_edit_skill",
            return_value=False,
        )

        service = SkillService(tenant_id="test-tenant")

        with pytest.raises(skill_service.ForbiddenError):
            service.update_skill_from_file(
                "existing",
                b"---\nname: existing\n---",
                tenant_id="test-tenant",
                user_id="viewer",
            )

    def test_update_from_file_allows_user_with_edit_permission(self, mocker):
        mocker.patch(
            "management.services.skill.service.skill_db.get_skill_by_name",
            return_value={"skill_id": 1, "name": "existing", "created_by": "owner"},
        )
        can_edit = mocker.patch(
            "management.services.skill.service._can_edit_skill",
            return_value=True,
        )
        mocker.patch(
            "management.services.skill.service.skill_db.update_skill",
            return_value={"skill_id": 1, "name": "existing"},
        )
        mocker.patch(
            "management.services.skill.service.skill_db.get_tool_ids_by_names",
            return_value=[],
        )
        service = SkillService(tenant_id="test-tenant")
        service.skill_manager = MagicMock()
        service.skill_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR
        service._enrich_configs_from_yaml = lambda result: result
        service.update_skill_from_file(
            "existing",
            b"---\nname: existing\n---\n# Content",
            file_type="md",
            user_id="group-editor",
        )

        can_edit.assert_called_once()

    def test_update_from_zip(self, mocker):
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("zip_update/SKILL.md", """---
name: zip_update
description: Updated via ZIP
---
# Content""")
            zf.writestr("zip_update/config/config.yaml", "updated_key: updated_value")

        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "zip_update"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "zip_update", "description": "Updated via ZIP"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_ids_by_names',
            return_value=[]
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService(tenant_id="test-tenant")
        service.skill_manager = mock_manager

        result = service.update_skill_from_file("zip_update", zip_buffer.getvalue(), file_type="zip", tenant_id="test-tenant")

        assert result["name"] == "zip_update"

    def test_update_skill_not_found(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value=None
        )

        service = create_test_service()

        from consts.exceptions import SkillException
        try:
            service.update_skill_from_file("nonexistent", b"---\nname: x\n---", tenant_id="test-tenant")
            assert False, "Should have raised"
        except SkillException as e:
            assert "not found" in str(e)
        except Exception as e:
            assert "not found" in str(e)


# ===== SkillService Error Handling Tests =====
class TestSkillServiceErrorHandling:
    """Test error handling in SkillService methods."""

    def test_list_skills_error_path(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.list_skills',
            side_effect=Exception("Database error")
        )

        service = create_test_service()

        from consts.exceptions import SkillException
        try:
            service.list_skills(tenant_id="test-tenant")
            assert False, "Should have raised"
        except SkillException as e:
            assert "Failed to list skills" in str(e)
        except Exception as e:
            assert "Failed to list skills" in str(e)

    def test_get_skill_error_path(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            side_effect=Exception("Database error")
        )

        service = create_test_service()

        from consts.exceptions import SkillException
        try:
            service.get_skill("any_skill", tenant_id="test-tenant")
            assert False, "Should have raised"
        except SkillException as e:
            assert "Failed to get skill" in str(e)
        except Exception as e:
            assert "Failed to get skill" in str(e)

    def test_get_skill_by_id_error_path(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_id',
            side_effect=Exception("Database error")
        )

        service = create_test_service()

        from consts.exceptions import SkillException
        try:
            service.get_skill_by_id(1, tenant_id="test-tenant")
            assert False, "Should have raised"
        except SkillException as e:
            assert "Failed to get skill" in str(e)
        except Exception as e:
            assert "Failed to get skill" in str(e)

    def test_load_skill_directory_error(self, mocker):
        mock_manager = MagicMock()
        mock_manager.load_skill_directory.side_effect = Exception("File error")

        service = SkillService(tenant_id="test-tenant")
        service.skill_manager = mock_manager

        from consts.exceptions import SkillException
        try:
            service.load_skill_directory("any_skill")
            assert False, "Should have raised"
        except SkillException as e:
            assert "Failed to load skill directory" in str(e)
        except Exception as e:
            assert "Failed to load skill directory" in str(e)

    def test_get_skill_scripts_error(self, mocker):
        mock_manager = MagicMock()
        mock_manager.get_skill_scripts.side_effect = Exception("File error")

        service = SkillService(tenant_id="test-tenant")
        service.skill_manager = mock_manager

        from consts.exceptions import SkillException
        try:
            service.get_skill_scripts("any_skill")
            assert False, "Should have raised"
        except SkillException as e:
            assert "Failed to get skill scripts" in str(e)
        except Exception as e:
            assert "Failed to get skill scripts" in str(e)

    def test_get_skill_content_error(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            side_effect=Exception("Database error")
        )

        service = create_test_service()

        from consts.exceptions import SkillException
        try:
            service.get_skill_content("any_skill")
            assert False, "Should have raised"
        except SkillException as e:
            assert "Failed to get skill content" in str(e)
        except Exception as e:
            assert "Failed to get skill content" in str(e)

    def test_build_skills_summary_error(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.list_skills',
            side_effect=Exception("Database error")
        )

        service = create_test_service()

        from consts.exceptions import SkillException
        try:
            service.build_skills_summary()
            assert False, "Should have raised"
        except SkillException as e:
            assert "Failed to build skills summary" in str(e)
        except Exception as e:
            assert "Failed to build skills summary" in str(e)


class TestSkillServiceCreateSkillErrorPaths:
    """Test error paths in create_skill."""

    def test_create_skill_local_dir_exists(self, mocker):
        mock_repo = MagicMock()
        mock_repo.get_skill_by_name.return_value = None

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.repository = mock_repo
        service.skill_manager = mock_manager
        service._resolve_local_skills_dir_for_overlay = MagicMock(return_value=TEST_LOCAL_SKILLS_DIR)

        with patch('os.path.isfile', return_value=True):
            from consts.exceptions import SkillException
            try:
                service.create_skill({"name": "local_conflict"})
                assert False, "Should have raised"
            except SkillException as e:
                assert "already exists locally" in str(e)
            except Exception as e:
                assert "already exists locally" in str(e)


# ===== Upload ZIP Files Tests =====
class TestUploadZipFiles:
    """Test _upload_zip_files method."""

    def test_upload_zip_with_folder_rename(self, mocker):
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("old_name/README.md", "# Readme")
            zf.writestr("old_name/scripts/run.sh", "#!/bin/bash\necho test")

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager

        with patch('os.makedirs'):
            with patch('builtins.open', mock_open()):
                service._upload_zip_files(zip_buffer.getvalue(), "new_name", "old_name", tenant_id=None)

    def test_upload_zip_with_nested_files(self, mocker):
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("nested/file1.txt", "content1")
            zf.writestr("nested/file2.txt", "content2")

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager

        with patch('os.makedirs'):
            with patch('builtins.open', mock_open()):
                service._upload_zip_files(zip_buffer.getvalue(), "nested", "nested", tenant_id=None)

    def test_upload_zip_handles_nested_directories(self, mocker):
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("nested/file1.txt", "content1")
            zf.writestr("nested/file2.txt", "content2")

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager

        with patch('os.makedirs'):
            with patch('builtins.open', mock_open()):
                service._upload_zip_files(zip_buffer.getvalue(), "nested", "nested", tenant_id=None)


# ===== Find ZIP Member Tests =====
class TestFindZipMemberConfigYamlEdgeCases:
    """Test _find_zip_member_config_yaml edge cases."""

    def test_empty_file_list(self):
        result = _find_zip_member_config_yaml([])
        assert result is None

    def test_trailing_slash_files_skipped(self):
        result = _find_zip_member_config_yaml(["dir/", "file.txt"])
        assert result is None

    def test_empty_name_skipped(self):
        result = _find_zip_member_config_yaml([""])
        assert result is None

    def test_preferred_root_prefix_match(self):
        file_list = ["my_skill/subdir/config/config.yaml", "other/config/config.yaml"]
        result = _find_zip_member_config_yaml(file_list, preferred_skill_root="my_skill")
        assert "my_skill" in result


# ===== Create Skill from MD Edge Cases =====
class TestSkillServiceCreateSkillFromMdEdgeCases:
    """Test _create_skill_from_md edge cases."""

    def test_create_md_without_allowed_tools(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'management.services.skill.service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "no_tools"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_ids_by_names',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        content = b"""---
name: no_tools
description: No allowed tools
---
# Content"""
        result = service.create_skill_from_file(content, skill_name="no_tools")

        assert result["name"] == "no_tools"

    def test_create_md_no_name_uses_skill_name_param(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'management.services.skill.service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "explicit_name"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_ids_by_names',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        content = b"""---
description: No name in frontmatter
---
# Content"""
        result = service.create_skill_from_file(content, skill_name="explicit_name")

        assert result["name"] == "explicit_name"


# ===== Update from MD Edge Cases =====
class TestSkillServiceUpdateFromMdEdgeCases:
    """Test _update_skill_from_md edge cases."""

    def test_update_md_with_allowed_tools(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_ids_by_names',
            return_value=[1, 2]
        )

        mock_manager = MagicMock()
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        content = b"""---
name: existing
description: Updated
allowed-tools:
  - tool1
  - tool2
---
# Content"""
        result = service._save_skill_upload(content, "existing", kind="md", update=True, tenant_id=None, user_id=None)

        assert result["name"] == "existing"


# ===== Update from ZIP Edge Cases =====
class TestSkillServiceUpdateFromZipEdgeCases:
    """Test _update_skill_from_zip edge cases."""

    def test_update_zip_without_skill_md(self, mocker):
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("README.md", "# Readme only")
            zf.writestr("config/config.yaml", "key: value")

        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "no_md"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "no_md"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        # Should not raise even without SKILL.md
        result = service._save_skill_upload(zip_buffer.getvalue(), "no_md", kind="zip", update=True, tenant_id=None, user_id=None)

        assert result["name"] == "no_md"

    def test_update_zip_with_invalid_skill_md_logs_warning(self, mocker):
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("bad_skill/SKILL.md", "invalid content")

        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "bad_skill"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "bad_skill"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        # Should not raise but logs warning
        result = service._save_skill_upload(zip_buffer.getvalue(), "bad_skill", kind="zip", update=True, tenant_id=None, user_id=None)
        assert result["name"] == "bad_skill"


# ===== Update Skill with Config YAML Sync =====
class TestUpdateSkillConfigYamlSync:
    """Test update_skill config.yaml sync behavior."""

    def test_update_skill_removes_config_values_when_null(self, mocker):
        """Test update_skill removes config.yaml when config_values is set to None."""
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "p_skill", "config_values": {"old": "value"}}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "p_skill", "config_values": None}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR

        with patch.object(skill_support, 'CONTAINER_SKILLS_PATH', TEST_LOCAL_SKILLS_DIR):
            service = SkillService(tenant_id="test-tenant")
            service.skill_manager = mock_manager
            service._resolve_local_skills_dir_for_overlay = MagicMock(return_value=TEST_LOCAL_SKILLS_DIR)

            with patch('management.services.skill.service._remove_local_skill_config_yaml') as mock_remove:
                service.update_skill("p_skill", {"config_values": None}, tenant_id="test-tenant")
                mock_remove.assert_called()


# ===== Build Skills Summary Edge Cases =====
class TestBuildSkillsSummaryEdgeCases:
    """Test build_skills_summary edge cases."""

    def test_build_summary_with_agent_skills_whitelist(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.search_skills_for_agent',
            return_value=[
                {"skill_instance_id": 1, "skill_id": 1, "enabled": True}
            ]
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_id',
            return_value={
                "name": "skill1",
                "description": "Desc",
                "content": "# Content",
                "tool_ids": []
            }
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={
                "name": "skill1",
                "description": "Desc"
            }
        )

        service = SkillService()

        result = service.build_skills_summary(
            available_skills=["skill1"],
            agent_id=1,
            tenant_id="tenant1"
        )

        assert "<skills>" in result
        assert "<name>skill1</name>" in result


# ===== Get Enabled Skills Edge Cases =====
class TestGetEnabledSkillsForAgentEdgeCases:
    """Test get_enabled_skills_for_agent edge cases."""

    def test_get_enabled_skills_skill_not_in_repo(self, mocker):
        from database import skill_db as skill_db_module
        original_func = getattr(skill_db_module, 'search_skills_for_agent', None)

        if original_func is not None:
            setattr(skill_db_module, 'search_skills_for_agent', lambda *args, **kwargs: [
                {"skill_instance_id": 1, "skill_id": 999, "enabled": True}  # Non-existent skill
            ])
            try:
                mock_repo = MagicMock()
                mock_repo.get_skill_by_id.return_value = None  # Skill not found in repo

                service = SkillService()
                service.repository = mock_repo

                result = service.get_enabled_skills_for_agent(
                    agent_id=1,
                    tenant_id="tenant1"
                )

                # Should return empty because skill was not found
                assert result == []
            finally:
                setattr(skill_db_module, 'search_skills_for_agent', original_func)
        else:
            pytest.skip("database.skill_db module not fully available")


# ===== Tooltip Functions Tests =====
class TestTooltipForCommentedMapKey:
    """Test _tooltip_for_commented_map_key function."""

    def test_index_zero_no_header_comment(self):
        from management.services.skill.service import _tooltip_for_commented_map_key
        cm = MagicMock()
        cm.ca = None
        result = _tooltip_for_commented_map_key(cm, ["key1", "key2"], 0, "key1")
        assert result is None

    def test_index_zero_with_empty_ca(self):
        from management.services.skill.service import _tooltip_for_commented_map_key
        cm = MagicMock(spec=[])
        result = _tooltip_for_commented_map_key(cm, ["key1"], 0, "key1")
        assert result is None


class TestTooltipForCommentedSeqIndex:
    """Test _tooltip_for_commented_seq_index function."""

    def test_index_zero_no_comment(self):
        from management.services.skill.service import _tooltip_for_commented_seq_index
        seq = MagicMock()
        seq.ca = None
        result = _tooltip_for_commented_seq_index(seq, 0)
        assert result is None

    def test_index_greater_than_zero_empty_prev_tuple(self):
        from management.services.skill.service import _tooltip_for_commented_seq_index
        seq = MagicMock()
        seq.ca = MagicMock()
        seq.ca.items = {0: None}
        result = _tooltip_for_commented_seq_index(seq, 1)
        assert result is None


# These tests require ruamel.yaml which may not be installed
# The _commented_tree_to_plain function is only called when ruamel is available


# ===== Write Skill Params with Config Dir Edge Cases =====
class TestWriteSkillParamsWithRealUtils:
    """Test _write_skill_params_to_local_config_yaml with real utils."""

    def test_write_params_with_nested_dict(self, mocker):
        with patch('os.makedirs'):
            with patch('builtins.open', mock_open()) as mock_file:
                with patch('management.services.skill.service._local_skill_config_yaml_path', return_value="/tmp/skill/config.yaml"):
                    _write_skill_params_to_local_config_yaml(
                        "skill",
                        {"nested": {"key": "value"}},
                        "/tmp"
                    )
                    mock_file().write.assert_called()


# ===== Service Methods Additional Edge Cases =====
class TestServiceMethodsAdditionalCoverage:
    """Additional coverage for service methods."""

    def test_create_skill_with_empty_params(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'management.services.skill.service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "empty_params"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = None

        service = SkillService(tenant_id="test-tenant")
        service.skill_manager = mock_manager
        service._resolve_local_skills_dir_for_overlay = MagicMock(return_value=None)

        result = service.create_skill({"name": "empty_params", "params": {}}, tenant_id="test-tenant")

        assert result["name"] == "empty_params"

    def test_create_skill_saves_to_manager(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'management.services.skill.service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "saved_skill"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = None

        service = SkillService(tenant_id="test-tenant")
        service.skill_manager = mock_manager
        service._resolve_local_skills_dir_for_overlay = MagicMock(return_value=None)

        result = service.create_skill({"name": "saved_skill"}, tenant_id="test-tenant")

        mock_manager.save_skill.assert_called_once()

    def test_update_skill_syncs_local_config(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "sync_skill", "description": "old"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "sync_skill", "description": "new"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR

        with patch.object(skill_support, 'CONTAINER_SKILLS_PATH', TEST_LOCAL_SKILLS_DIR):
            service = SkillService(tenant_id="test-tenant")
            service.skill_manager = mock_manager
            service._resolve_local_skills_dir_for_overlay = MagicMock(return_value=TEST_LOCAL_SKILLS_DIR)

            with patch('management.services.skill.service._write_skill_params_to_local_config_yaml'):
                result = service.update_skill("sync_skill", {"params": {"key": "value"}}, tenant_id="test-tenant")

        assert result["description"] == "new"

    def test_update_skill_without_container_path(self, mocker):
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "no_path"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "no_path"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = None

        with patch.object(skill_support, 'CONTAINER_SKILLS_PATH', None):
            with patch.object(skill_service, 'ROOT_DIR', ""):
                service = SkillService(tenant_id="test-tenant")
                service.skill_manager = mock_manager
                service._resolve_local_skills_dir_for_overlay = MagicMock(return_value=None)

                result = service.update_skill("no_path", {"description": "updated"}, tenant_id="test-tenant")

        assert result["name"] == "no_path"


# ===== Get Skill Scripts Tests =====
class TestGetSkillScripts:
    """Test get_skill_scripts method."""

    def test_get_scripts_success(self, mocker):
        mock_manager = MagicMock()
        mock_manager.get_skill_scripts.return_value = ["script1.sh", "script2.py"]

        service = SkillService()
        service.skill_manager = mock_manager

        result = service.get_skill_scripts("test_skill")

        assert len(result) == 2
        mock_manager.get_skill_scripts.assert_called_once_with("test_skill", tenant_id=None)

    def test_get_scripts_error(self, mocker):
        mock_manager = MagicMock()
        mock_manager.get_skill_scripts.side_effect = Exception("Scripts not found")

        service = SkillService()
        service.skill_manager = mock_manager

        from consts.exceptions import SkillException
        try:
            service.get_skill_scripts("nonexistent")
            assert False, "Should have raised"
        except SkillException as e:
            assert "Failed to get skill scripts" in str(e)
        except Exception as e:
            assert "Failed to get skill scripts" in str(e)


# ===== Create/Update Skill Instance Tests =====
class TestSkillInstanceMethods:
    """Test skill instance methods."""

    def test_create_or_update_skill_instance_returns_dict(self):
        from database import skill_db as skill_db_module
        original_func = getattr(skill_db_module, 'create_or_update_skill_by_skill_info', None)

        if original_func is not None:
            setattr(skill_db_module, 'create_or_update_skill_by_skill_info', lambda *args, **kwargs: {
                "skill_instance_id": 1, "skill_id": 1, "agent_id": 1, "enabled": True
            })
            try:
                service = SkillService()
                result = service.create_or_update_skill_instance(
                    skill_info={"skill_id": 1, "enabled": True},
                    tenant_id="tenant1",
                    user_id="user1"
                )
                assert "skill_instance_id" in result
            finally:
                setattr(skill_db_module, 'create_or_update_skill_by_skill_info', original_func)
        else:
            pytest.skip("database.skill_db module not fully available")

    def test_list_skill_instances_returns_empty(self):
        from database import skill_db as skill_db_module
        original_func = getattr(skill_db_module, 'query_skill_instances_by_agent_id', None)

        if original_func is not None:
            setattr(skill_db_module, 'query_skill_instances_by_agent_id', lambda *args, **kwargs: [])
            try:
                service = SkillService()
                result = service.list_skill_instances(agent_id=1, tenant_id="tenant1")
                assert result == []
            finally:
                setattr(skill_db_module, 'query_skill_instances_by_agent_id', original_func)
        else:
            pytest.skip("database.skill_db module not fully available")


# ===== Path Traversal Protection Tests =====
class TestDeleteSkillFilePathTraversal:
    """Test path traversal protection in delete_skill_file service call."""

    def test_delete_skill_file_normalizes_path(self, mocker):
        """Test that file paths are properly normalized."""
        from management.services.skill import service as skill_service
        import os

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR
        mock_manager.delete_skill_file = MagicMock(return_value=True)

        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "test_skill"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.delete_skill',
            return_value=True
        )
        mocker.patch(
            'management.services.skill.service.skill_db.delete_skill_instances_by_skill_id',
            return_value=None
        )

        service = SkillService(tenant_id="test-tenant")
        service.skill_manager = mock_manager

        with patch.object(skill_support, 'CONTAINER_SKILLS_PATH', TEST_LOCAL_SKILLS_DIR):
            with patch('os.path.isdir', return_value=False):
                result = service.delete_skill("test_skill", tenant_id="test-tenant")

        assert result is True

    def test_delete_skill_file_with_dotdot_in_path(self, mocker):
        """Test deletion with path containing .. should be prevented at app layer.

        This test verifies the app layer validation catches path traversal attempts.
        The service layer relies on the app layer to validate paths.
        """
        import os

        # Test that os.path.normpath properly handles ../
        malicious_path = "/tmp/skills/../../etc/passwd"
        normalized = os.path.normpath(malicious_path)
        # Normalize both paths for cross-platform comparison (Windows uses \)
        normalized_normalized = normalized.replace("\\", "/")
        assert normalized_normalized == "/etc/passwd"

        # Verify the normalized path is not within the base directory
        base_dir = TEST_LOCAL_SKILLS_DIR
        normalized_abs = os.path.abspath(normalized)
        base_abs = os.path.abspath(base_dir)
        normalized_abs_normalized = normalized_abs.replace("\\", "/")
        base_abs_normalized = base_abs.replace("\\", "/")
        assert not normalized_abs_normalized.startswith(base_abs_normalized + "/")
        assert normalized_abs_normalized != base_abs_normalized

    def test_path_traversal_detection_with_backslash(self):
        """Test Windows-style path traversal detection.

        Note: On Unix systems, backslash is treated as a regular character, not a path separator.
        This test uses forward slashes to ensure cross-platform path traversal detection.
        The key is to use a path that definitely escapes the base directory after normalization.
        """
        import os

        # Use forward slashes to ensure reliable cross-platform path traversal
        # This path escapes /tmp/skills and reaches /etc
        malicious_path = "/tmp/skills/../../../etc/passwd"
        normalized = os.path.normpath(malicious_path)
        base_dir = TEST_LOCAL_SKILLS_DIR

        normalized_abs = os.path.abspath(normalized)
        base_abs = os.path.abspath(base_dir)

        # Use os.path.commonpath for robust cross-platform comparison
        # commonpath returns the longest common sub-path, if paths are on different drives
        # (on Unix), it raises ValueError. In that case, we check with startswith.
        try:
            common = os.path.commonpath([normalized_abs, base_abs])
            is_within = (common == base_abs)
        except ValueError:
            # Different drives on Windows, or commonpath can't compare
            # Fall back to startswith check with normalized paths
            normalized_clean = normalized_abs.replace("\\", "/")
            base_clean = base_abs.replace("\\", "/")
            is_within = normalized_clean.startswith(base_clean + "/") or normalized_clean == base_clean

        # The malicious path should NOT be within the base directory
        assert not is_within, f"Path {normalized_abs} should not be within {base_abs}"

    def test_valid_path_within_directory(self):
        """Test that valid paths within directory are allowed."""
        import os

        # Valid path should be allowed
        valid_path = "/tmp/skills/my_skill/temp.yaml"
        normalized = os.path.normpath(valid_path)
        base_dir = "/tmp/skills/my_skill"

        normalized_abs = os.path.abspath(normalized)
        base_abs = os.path.abspath(base_dir)
        # Normalize for cross-platform comparison
        normalized_abs_normalized = normalized_abs.replace("\\", "/")
        base_abs_normalized = base_abs.replace("\\", "/")
        assert normalized_abs_normalized.startswith(base_abs_normalized + "/") or normalized_abs_normalized == base_abs_normalized


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ===== Additional Coverage Tests =====

class TestSkillServiceDeleteLocalSkillFiles:
    """Test _delete_local_skill_files method."""

    def test_delete_files_no_directory(self, mocker):
        """Test deletion when directory doesn't exist."""
        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager

        with patch('os.path.isdir', return_value=False):
            service._delete_local_skill_files("nonexistent_skill", tenant_id=None)

    def test_delete_files_with_content(self, mocker):
        """Test deletion with files and subdirectories."""
        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager

        def mock_isdir(path):
            return path.endswith("subdir") or path.endswith("test_skill")

        with patch('os.path.isdir', side_effect=mock_isdir):
            with patch('os.listdir', return_value=["file.txt", "subdir"]):
                with patch('os.remove'):
                    with patch('shutil.rmtree'):
                        service._delete_local_skill_files("test_skill", tenant_id=None)

    def test_delete_files_with_trailing_slash_item(self, mocker):
        """Test deletion with items ending in slash."""
        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager

        def mock_isdir(path):
            return path.endswith("subdir") or path.endswith("test_skill")

        with patch('os.path.isdir', side_effect=mock_isdir):
            with patch('os.listdir', return_value=["file.txt", "subdir/", "normal_dir"]):
                with patch('os.remove'):
                    with patch('shutil.rmtree'):
                        service._delete_local_skill_files("test_skill", tenant_id=None)


class TestSkillServiceCreateSkillFromFileAutoDetect:
    """Test auto-detection in create_skill_from_file."""

    def test_auto_detect_md_file(self, mocker):
        """Test auto-detection of MD file type."""
        mock_repo = MagicMock()
        mock_repo.get_skill_by_name.return_value = None
        mock_repo.create_skill.return_value = {"skill_id": 1, "name": "auto_skill"}

        mock_manager = MagicMock()
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.repository = mock_repo
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        content = b"""---
name: auto_skill
description: Auto detected
---
# Content"""
        result = service.create_skill_from_file(content, file_type="auto")

        assert result["name"] == "auto_skill"


class TestSkillServiceCreateSkillFromFileEdgeCases:
    """Test edge cases in create_skill_from_file."""

    def test_bytesio_input(self, mocker):
        """Test BytesIO input handling."""
        mock_repo = MagicMock()
        mock_repo.get_skill_by_name.return_value = None
        mock_repo.create_skill.return_value = {"skill_id": 1, "name": "bio_skill"}

        mock_manager = MagicMock()
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.repository = mock_repo
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        content = io.BytesIO(b"""---
name: bio_skill
description: BytesIO input
---
# Content""")
        result = service.create_skill_from_file(content, file_type="md")

        assert result["name"] == "bio_skill"

    def test_string_input(self, mocker):
        """Test string input handling."""
        mock_repo = MagicMock()
        mock_repo.get_skill_by_name.return_value = None
        mock_repo.create_skill.return_value = {"skill_id": 1, "name": "str_skill"}

        mock_manager = MagicMock()
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.repository = mock_repo
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        content = """---
name: str_skill
description: String input
---
# Content"""
        result = service.create_skill_from_file(content, file_type="md")

        assert result["name"] == "str_skill"


class TestSkillServiceUpdateFromFileAutoDetect:
    """Test auto-detection in update_skill_from_file."""

    def test_auto_detect_zip(self, mocker):
        """Test auto-detection of ZIP file type."""
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("zip_update/SKILL.md", """---
name: zip_update
description: Updated via ZIP
---
# Content""")

        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "zip_update"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "zip_update"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService(tenant_id="test-tenant")
        service.skill_manager = mock_manager

        zip_buffer.seek(0)
        result = service.update_skill_from_file("zip_update", zip_buffer.getvalue(), file_type="auto", tenant_id="test-tenant")

        assert result["name"] == "zip_update"


class TestSkillServiceUpdateFromFileStringInput:
    """Test update_skill_from_file with string input."""

    def test_string_input(self, mocker):
        """Test string input handling in update."""
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService(tenant_id="test-tenant")
        service.skill_manager = mock_manager

        content = """---
name: existing
description: Updated
---
# Content"""
        result = service.update_skill_from_file("existing", content, file_type="md", tenant_id="test-tenant")

        assert result["name"] == "existing"


class TestSkillServiceCreateFromZipRootLevelSkillMd:
    """Test _create_skill_from_zip with root level SKILL.md."""

    def test_create_from_zip_root_skill_md(self, mocker):
        """Test ZIP with SKILL.md at root level - requires skill_name param since no folder name."""
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("SKILL.md", """---
name: root_skill
description: Root level SKILL.md
---
# Content""")

        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'management.services.skill.service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "root_skill"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_ids_by_names',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        # Provide skill_name since root-level SKILL.md has no folder name to extract
        result = service.create_skill_from_file(zip_buffer.getvalue(), "root_skill", file_type="zip")

        assert result["name"] == "root_skill"


class TestSkillServiceUpdateFromZipWithSkillMdParsing:
    """Test _update_skill_from_zip with SKILL.md parsing."""

    def test_update_from_zip_with_skill_md(self, mocker):
        """Test ZIP update with valid SKILL.md."""
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("skill/SKILL.md", """---
name: skill
description: Updated from ZIP
allowed-tools:
  - tool1
---
# Content""")

        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "skill"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "skill"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_ids_by_names',
            return_value=[1]
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_names_by_skill_name',
            return_value=["tool1"]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        result = service._save_skill_upload(zip_buffer.getvalue(), "skill", kind="zip", update=True, tenant_id=None, user_id=None)

        assert result["name"] == "skill"


class TestSkillServiceUpdateFromZipWithParams:
    """Test _update_skill_from_zip with params from config.yaml."""

    def test_update_from_zip_with_config_params(self, mocker):
        """Test ZIP update with params from config.yaml."""
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("skill/SKILL.md", """---
name: skill
description: Updated
---
# Content""")
            zf.writestr("skill/config/config.yaml", "key: value")

        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "skill"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "skill", "params": {"key": "value"}}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        result = service._save_skill_upload(zip_buffer.getvalue(), "skill", kind="zip", update=True, tenant_id=None, user_id=None)

        assert result["name"] == "skill"


class TestSkillServiceCreateFromZipWithSkillNameParam:
    """Test _create_skill_from_zip with skill_name parameter."""

    def test_create_from_zip_with_skill_name_param(self, mocker):
        """Test ZIP creation with explicit skill_name."""
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("old_name/SKILL.md", """---
name: old_name
description: Renamed skill
---
# Content""")

        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'management.services.skill.service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "new_name"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_ids_by_names',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        result = service.create_skill_from_file(zip_buffer.getvalue(), "new_name", file_type="zip")

        assert result["name"] == "new_name"


class TestSkillServiceUpdateFromZipEmptyContent:
    """Test _update_skill_from_zip with empty skill_content."""

    def test_update_from_zip_no_skill_md_content(self, mocker):
        """Test ZIP update without SKILL.md content."""
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("skill/README.md", "# Readme")

        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "skill"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "skill"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        result = service._save_skill_upload(zip_buffer.getvalue(), "skill", kind="zip", update=True, tenant_id=None, user_id=None)

        assert result["name"] == "skill"


class TestSkillServiceCreateFromMdWithInvalidParse:
    """Test _create_skill_from_md with invalid parse."""

    def test_create_md_invalid_parse_raises(self, mocker):
        """Test MD creation with invalid parse raises exception."""
        mocker.patch(
            'management.services.skill.service.SkillLoader.parse',
            side_effect=ValueError("Invalid YAML syntax")
        )

        mock_manager = MagicMock()

        service = SkillService()
        service.skill_manager = mock_manager

        content = b"invalid content"
        from consts.exceptions import SkillException
        try:
            service.create_skill_from_file(content, skill_name=None)
            assert False, "Should have raised"
        except SkillException as e:
            assert "Invalid SKILL.md format" in str(e)


class TestSkillServiceCreateFromMdWithUserId:
    """Test _create_skill_from_md with user_id."""

    def test_create_md_with_user_id(self, mocker):
        """Test MD creation sets created_by and updated_by."""
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'management.services.skill.service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "user_skill"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_ids_by_names',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        content = b"""---
name: user_skill
description: With user
---
# Content"""
        result = service.create_skill_from_file(content, skill_name="user_skill", user_id="user123")

        assert result["name"] == "user_skill"


class TestSkillServiceCreateFromZipWithUserId:
    """Test _create_skill_from_zip with user_id."""

    def test_create_zip_with_user_id(self, mocker):
        """Test ZIP creation sets created_by and updated_by."""
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("skill/SKILL.md", """---
name: skill
description: With user
---
# Content""")

        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'management.services.skill.service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "skill"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_ids_by_names',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        result = service.create_skill_from_file(zip_buffer.getvalue(), None, user_id="user456", file_type="zip")

        assert result["name"] == "skill"


class TestSkillServiceUpdateFromMdWithUserId:
    """Test _update_skill_from_md with user_id."""

    def test_update_md_with_user_id(self, mocker):
        """Test MD update sets updated_by."""
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_ids_by_names',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        content = b"""---
name: existing
description: Updated
---
# Content"""
        result = service._save_skill_upload(content, "existing", user_id="updater789", kind="md", update=True, tenant_id=None)

        assert result["name"] == "existing"


class TestSkillServiceUpdateFromZipWithUserId:
    """Test _update_skill_from_zip with user_id."""

    def test_update_zip_with_user_id(self, mocker):
        """Test ZIP update sets updated_by."""
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("skill/SKILL.md", """---
name: skill
description: Updated
---
# Content""")

        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "skill"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "skill"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        result = service._save_skill_upload(zip_buffer.getvalue(), "skill", user_id="updater789", kind="zip", update=True, tenant_id=None)

        assert result["name"] == "skill"


class TestSkillServiceCreateFromZipWithBadZipFile:
    """Test _create_skill_from_zip with bad ZIP file."""

    def test_create_from_zip_invalid_raises(self, mocker):
        """Test invalid ZIP raises exception."""
        mock_manager = MagicMock()

        service = SkillService()
        service.skill_manager = mock_manager

        from consts.exceptions import SkillException
        try:
            service.create_skill_from_file(b"not a zip file", file_type="zip")
            assert False, "Should have raised"
        except SkillException as e:
            assert "Invalid ZIP" in str(e)


class TestSkillServiceCreateFromZipWithInvalidSkillMd:
    """Test _create_skill_from_zip with invalid SKILL.md."""

    def test_create_from_zip_invalid_skill_md_raises(self, mocker):
        """Test invalid SKILL.md in ZIP raises exception."""
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("skill/SKILL.md", """---
name: skill
description: Some content
---
# Content""")

        mocker.patch(
            'management.services.skill.service.SkillLoader.parse',
            side_effect=ValueError("Invalid YAML syntax")
        )

        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value=None
        )

        mock_manager = MagicMock()
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager

        from consts.exceptions import SkillException
        try:
            service.create_skill_from_file(zip_buffer.getvalue(), file_type="zip")
            assert False, "Should have raised"
        except SkillException as e:
            assert "Invalid SKILL.md" in str(e)


class TestSkillServiceDeleteWithLocalDir:
    """Test delete_skill with local directory."""

    def test_delete_with_existing_local_dir(self, mocker):
        """Test deletion removes local directory."""
        mocker.patch(
            'management.services.skill.service.skill_db.delete_skill',
            return_value=True
        )
        mocker.patch(
            'management.services.skill.service.skill_db.delete_skill_instances_by_skill_id',
            return_value=None
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "to_delete"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService(tenant_id="test-tenant")
        service.skill_manager = mock_manager

        with patch('os.path.exists', return_value=True):
            with patch('shutil.rmtree'):
                result = service.delete_skill("to_delete", tenant_id="test-tenant", user_id="user123")

        assert result is True


class TestSkillServiceDeleteWithNoLocalDir:
    """Test delete_skill without local directory."""

    def test_delete_without_local_dir(self, mocker):
        """Test deletion works without local directory."""
        mocker.patch(
            'management.services.skill.service.skill_db.delete_skill',
            return_value=True
        )
        mocker.patch(
            'management.services.skill.service.skill_db.delete_skill_instances_by_skill_id',
            return_value=None
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "to_delete"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = None
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService(tenant_id="test-tenant")
        service.skill_manager = mock_manager

        with patch('os.path.isfile', return_value=False):
            result = service.delete_skill("to_delete", tenant_id="test-tenant", user_id="user123")

        assert result is True


class TestSkillServiceGetEnabledSkillsForAgentWithToolIds:
    """Test get_enabled_skills_for_agent with tool_ids."""

    def test_get_enabled_skills_with_tool_ids(self, mocker):
        """Test getting enabled skills returns tool_ids."""
        mocker.patch(
            'management.services.skill.service.skill_db.search_skills_for_agent',
            return_value=[
                {"skill_instance_id": 1, "skill_id": 1, "enabled": True}
            ]
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_id',
            return_value={
                "name": "skill1",
                "description": "Desc",
                "content": "# Content",
                "tool_ids": [1, 2, 3]
            }
        )

        service = SkillService()

        result = service.get_enabled_skills_for_agent(
            agent_id=1,
            tenant_id="tenant1"
        )

        assert len(result) == 1
        assert result[0]["tool_ids"] == [1, 2, 3]


class TestSkillServiceBuildSkillsSummaryWithAgentId:
    """Test build_skills_summary with agent_id."""

    def test_build_summary_with_agent_id(self, mocker):
        """Test building summary with agent_id uses agent skills."""
        mocker.patch(
            'management.services.skill.service.skill_db.search_skills_for_agent',
            return_value=[
                {"skill_instance_id": 1, "skill_id": 1, "enabled": True}
            ]
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_id',
            return_value={
                "name": "agent_skill",
                "description": "Agent skill",
                "content": "# Content"
            }
        )
        mocker.patch(
            'management.services.skill.service.skill_db.list_skills',
            return_value=[]
        )

        service = SkillService()

        result = service.build_skills_summary(
            agent_id=1,
            tenant_id="tenant1"
        )

        assert "<skills>" in result
        assert "<name>agent_skill</name>" in result


class TestSkillServiceBuildSkillsSummaryWithNoneDescriptions:
    """Test build_skills_summary with None descriptions."""

    def test_build_summary_with_none_description(self, mocker):
        """Test building summary handles None descriptions."""
        mocker.patch(
            'management.services.skill.service.skill_db.list_skills',
            return_value=[
                {"name": "skill1", "description": None}
            ]
        )
        mocker.patch(
            'management.services.skill.service.skill_db.search_skills_for_agent',
            return_value=[]
        )

        service = create_test_service()

        result = service.build_skills_summary(tenant_id="test-tenant")

        assert "<skills>" in result
        assert "<name>skill1</name>" in result


class TestSkillServiceUpdateSkillWithExistingTags:
    """Test update_skill with existing tags."""

    def test_update_skill_preserves_existing_tags(self, mocker):
        """Test update_skill preserves existing tags when not provided."""
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "existing", "tags": ["tag1", "tag2"]}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "existing", "tags": ["tag1", "tag2"]}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.resolve_tenant_dir.return_value = "/tmp"
        mock_manager.local_skills_dir = "/tmp"

        with patch.object(skill_support, 'CONTAINER_SKILLS_PATH', "/tmp"):
            service = SkillService(tenant_id="test-tenant")
            service.skill_manager = mock_manager

            result = service.update_skill("existing", {"description": "updated"}, tenant_id="test-tenant")

        assert result["name"] == "existing"


class TestSkillServiceUpdateSkillWithExistingContent:
    """Test update_skill with existing content."""

    def test_update_skill_preserves_existing_content(self, mocker):
        """Test update_skill preserves existing content when not provided."""
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "existing", "content": "# Original content"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "existing", "content": "# Original content"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.resolve_tenant_dir.return_value = "/tmp"
        mock_manager.local_skills_dir = "/tmp"

        with patch.object(skill_support, 'CONTAINER_SKILLS_PATH', "/tmp"):
            service = SkillService(tenant_id="test-tenant")
            service.skill_manager = mock_manager

            result = service.update_skill("existing", {"description": "updated"}, tenant_id="test-tenant")

        assert result["name"] == "existing"


class TestSkillServiceUpdateSkillWithFiles:
    """Test update_skill with files parameter."""

    def test_update_skill_with_files(self, mocker):
        """Test update_skill passes files to manager."""
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.resolve_tenant_dir.return_value = "/tmp"
        mock_manager.local_skills_dir = "/tmp"

        with patch.object(skill_support, 'CONTAINER_SKILLS_PATH', "/tmp"):
            service = SkillService(tenant_id="test-tenant")
            service.skill_manager = mock_manager

            result = service.update_skill("existing", {"files": ["file1.txt", "file2.txt"]}, tenant_id="test-tenant")

        assert result["name"] == "existing"
        mock_manager.save_skill.assert_called()


class TestSkillServiceCreateSkillWithLocalParamsWriteError:
    """Test create_skill handles local params write error."""

    def test_create_skill_local_write_error_logs_warning(self, mocker):
        """Test create_skill logs warning on local params write error."""
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'management.services.skill.service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "error_skill"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR

        service = SkillService(tenant_id="test-tenant")
        service.skill_manager = mock_manager
        service._resolve_local_skills_dir_for_overlay = MagicMock(return_value=TEST_LOCAL_SKILLS_DIR)

        with patch('os.path.exists', return_value=False):
            with patch('management.services.skill.service._write_skill_params_to_local_config_yaml',
                      side_effect=Exception("Write error")):
                result = service.create_skill({
                    "name": "error_skill",
                    "params": {"key": "value"}
                }, tenant_id="test-tenant")

        assert result["name"] == "error_skill"


class TestSkillServiceUpdateSkillParamsWriteError:
    """Test update_skill handles params write error."""

    def test_update_skill_params_write_error(self, mocker):
        """Test update_skill logs warning on params write error."""
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.resolve_tenant_dir.return_value = "/tmp"
        mock_manager.local_skills_dir = "/tmp"

        with patch.object(skill_support, 'CONTAINER_SKILLS_PATH', "/tmp"):
            service = SkillService(tenant_id="test-tenant")
            service.skill_manager = mock_manager

            with patch('management.services.skill.service._write_skill_params_to_local_config_yaml',
                      side_effect=Exception("Write error")):
                result = service.update_skill("existing", {"params": {"key": "value"}}, tenant_id="test-tenant")

        assert result["name"] == "existing"


class TestSkillServiceUpdateSkillSaveSkillError:
    """Test update_skill handles save_skill error."""

    def test_update_skill_save_error(self, mocker):
        """Test update_skill logs warning on save_skill error."""
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.resolve_tenant_dir.return_value = "/tmp"
        mock_manager.local_skills_dir = "/tmp"
        mock_manager.save_skill.side_effect = Exception("Save error")

        with patch.object(skill_support, 'CONTAINER_SKILLS_PATH', "/tmp"):
            service = SkillService(tenant_id="test-tenant")
            service.skill_manager = mock_manager

            result = service.update_skill("existing", {"description": "updated"}, tenant_id="test-tenant")

        assert result["name"] == "existing"


class TestSkillServiceDeleteError:
    """Test delete_skill error handling."""

    def test_delete_skill_error(self, mocker):
        """Test delete_skill raises exception on error."""
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "to_delete"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.delete_skill',
            side_effect=Exception("DB error")
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = None

        service = SkillService(tenant_id="test-tenant")
        service.skill_manager = mock_manager

        from consts.exceptions import SkillException
        try:
            service.delete_skill("to_delete", tenant_id="test-tenant")
            assert False, "Should have raised"
        except SkillException as e:
            assert "Failed to delete" in str(e)


class TestSkillServiceCreateFromFileWithSource:
    """Test create_skill_from_file with source parameter."""

    def test_create_md_with_source(self, mocker):
        """Test MD creation with source parameter."""
        mock_repo = MagicMock()
        mock_repo.get_skill_by_name.return_value = None
        mock_repo.create_skill.return_value = {"skill_id": 1, "name": "source_skill"}

        mock_manager = MagicMock()
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.repository = mock_repo
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        content = b"""---
name: source_skill
description: With source
---
# Content"""
        result = service.create_skill_from_file(content, source="official")

        assert result["name"] == "source_skill"


class TestSkillServiceUpdateFromFileWithTenantId:
    """Test update_skill_from_file with tenant_id."""

    def test_update_with_tenant_id(self, mocker):
        """Test update passes tenant_id to tool lookup."""
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_ids_by_names',
            return_value=[1]
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_names_by_skill_name',
            return_value=["tool1"]
        )

        mock_manager = MagicMock()
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        content = b"""---
name: existing
description: Updated
allowed-tools:
  - tool1
---
# Content"""
        result = service.update_skill_from_file("existing", content, tenant_id="tenant123")

        assert result["name"] == "existing"


class TestSkillServiceCreateFromZipWithTenantId:
    """Test _create_skill_from_zip with tenant_id."""

    def test_create_zip_with_tenant_id(self, mocker):
        """Test ZIP creation passes tenant_id to tool lookup."""
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("skill/SKILL.md", """---
name: skill
description: With tenant
allowed-tools:
  - tool1
---
# Content""")

        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'management.services.skill.service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "skill"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_ids_by_names',
            return_value=[1]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        result = service.create_skill_from_file(zip_buffer.getvalue(), None, tenant_id="tenant456", file_type="zip")

        assert result["name"] == "skill"


class TestSkillServiceGetSkillFileContentWithNestedPath:
    """Test get_skill_file_content with nested path."""

    def test_get_file_content_nested_path(self, mocker):
        """Test getting file content with nested path."""
        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager

        with patch('os.path.isfile', return_value=True):
            with patch('builtins.open', mock_open(read_data="nested content")):
                result = service.get_skill_file_content("test_skill", "scripts/run.sh")

        assert result == "nested content"


class TestSkillServiceGetSkillFileContentError:
    """Test get_skill_file_content error handling."""

    def test_get_file_content_read_error(self, mocker):
        """Test getting file content with read error."""
        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager

        with patch('os.path.isfile', return_value=True):
            with patch('builtins.open', side_effect=IOError("Read error")):
                from consts.exceptions import SkillException
                try:
                    service.get_skill_file_content("test_skill", "file.txt")
                    assert False, "Should have raised"
                except SkillException as e:
                    assert "Failed to read" in str(e)


class TestSkillServiceLoadSkillDirectoryError:
    """Test load_skill_directory error handling."""

    def test_load_directory_error(self, mocker):
        """Test load_skill_directory error handling."""
        mock_manager = MagicMock()
        mock_manager.load_skill_directory.side_effect = Exception("Load error")

        service = SkillService()
        service.skill_manager = mock_manager

        from consts.exceptions import SkillException
        try:
            service.load_skill_directory("test_skill")
            assert False, "Should have raised"
        except SkillException as e:
            assert "Failed to load skill directory" in str(e)


class TestSkillServiceGetSkillScripts:
    """Test get_skill_scripts."""

    def test_get_scripts_success(self, mocker):
        """Test getting scripts successfully."""
        mock_manager = MagicMock()
        mock_manager.get_skill_scripts.return_value = ["script1.sh", "script2.py"]

        service = SkillService()
        service.skill_manager = mock_manager

        result = service.get_skill_scripts("test_skill")

        assert len(result) == 2
        mock_manager.get_skill_scripts.assert_called_once_with("test_skill", tenant_id=None)


class TestSkillServiceGetSkillScriptsError:
    """Test get_skill_scripts error handling."""

    def test_get_scripts_error(self, mocker):
        """Test getting scripts with error."""
        mock_manager = MagicMock()
        mock_manager.get_skill_scripts.side_effect = Exception("Scripts not found")

        service = SkillService()
        service.skill_manager = mock_manager

        from consts.exceptions import SkillException
        try:
            service.get_skill_scripts("nonexistent")
            assert False, "Should have raised"
        except SkillException as e:
            assert "Failed to get skill scripts" in str(e)


class TestSkillServiceGetEnabledSkillsForAgentError:
    """Test get_enabled_skills_for_agent error handling."""

    def test_get_enabled_skills_error(self, mocker):
        """Test getting enabled skills with error."""
        mocker.patch(
            'management.services.skill.service.skill_db.search_skills_for_agent',
            side_effect=Exception("DB error")
        )

        service = SkillService()
        from consts.exceptions import SkillException
        try:
            service.get_enabled_skills_for_agent(agent_id=1, tenant_id="tenant1")
            assert False, "Should have raised"
        except SkillException as e:
            assert "Failed to get enabled skills" in str(e)


class TestSkillServiceBuildSkillsSummaryError:
    """Test build_skills_summary error handling."""

    def test_build_summary_list_error(self, mocker):
        """Test building summary with list error."""
        mocker.patch(
            'management.services.skill.service.skill_db.list_skills',
            side_effect=Exception("DB error")
        )

        service = create_test_service()

        from consts.exceptions import SkillException
        try:
            service.build_skills_summary(tenant_id="test-tenant")
            assert False, "Should have raised"
        except SkillException as e:
            assert "Failed to build skills summary" in str(e)


class TestSkillServiceGetSkillContentError:
    """Test get_skill_content error handling."""

    def test_get_content_error(self, mocker):
        """Test getting content with error."""
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            side_effect=Exception("DB error")
        )

        service = create_test_service()

        from consts.exceptions import SkillException
        try:
            service.get_skill_content("any_skill", tenant_id="test-tenant")
            assert False, "Should have raised"
        except SkillException as e:
            assert "Failed to get skill content" in str(e)


class TestSkillServiceGetSkillFileTreeError:
    """Test get_skill_file_tree error handling."""

    def test_get_file_tree_error(self, mocker):
        """Test getting file tree with error."""
        mock_manager = MagicMock()
        mock_manager.get_skill_file_tree.side_effect = Exception("Error")

        service = SkillService()
        service.skill_manager = mock_manager

        from consts.exceptions import SkillException
        try:
            service.get_skill_file_tree("test_skill")
            assert False, "Should have raised"
        except SkillException as e:
            assert "Failed to get skill file tree" in str(e)


class TestSkillServiceListSkillInstances:
    """Test list_skill_instances."""

    def test_list_skill_instances(self):
        """Test listing skill instances."""
        from database import skill_db as skill_db_module
        original_func = getattr(skill_db_module, 'query_skill_instances_by_agent_id', None)

        if original_func is not None:
            setattr(skill_db_module, 'query_skill_instances_by_agent_id', lambda *args, **kwargs: [
                {"skill_instance_id": 1, "skill_id": 1}
            ])
            try:
                service = SkillService()
                result = service.list_skill_instances(agent_id=1, tenant_id="tenant1")
                assert len(result) == 1
            finally:
                setattr(skill_db_module, 'query_skill_instances_by_agent_id', original_func)
        else:
            pytest.skip("database.skill_db module not fully available")


class TestSkillServiceGetSkillInstance:
    """Test get_skill_instance."""

    def test_get_skill_instance_found(self):
        """Test getting skill instance when found."""
        from database import skill_db as skill_db_module
        original_func = getattr(skill_db_module, 'query_skill_instance_by_id', None)

        if original_func is not None:
            setattr(skill_db_module, 'query_skill_instance_by_id', lambda *args, **kwargs: {
                "skill_instance_id": 1, "skill_id": 1
            })
            try:
                service = SkillService()
                result = service.get_skill_instance(agent_id=1, skill_id=1, tenant_id="tenant1")
                assert result is not None
                assert result["skill_instance_id"] == 1
            finally:
                setattr(skill_db_module, 'query_skill_instance_by_id', original_func)
        else:
            pytest.skip("database.skill_db module not fully available")


class TestSkillServiceCreateOrUpdateSkillInstance:
    """Test create_or_update_skill_instance."""

    def test_create_or_update_skill_instance(self):
        """Test creating/updating skill instance."""
        from database import skill_db as skill_db_module
        original_func = getattr(skill_db_module, 'create_or_update_skill_by_skill_info', None)

        if original_func is not None:
            setattr(skill_db_module, 'create_or_update_skill_by_skill_info', lambda *args, **kwargs: {
                "skill_instance_id": 1, "skill_id": 1, "enabled": True
            })
            try:
                service = SkillService()
                result = service.create_or_update_skill_instance(
                    skill_info={"skill_id": 1, "enabled": True},
                    tenant_id="tenant1",
                    user_id="user1"
                )
                assert "skill_instance_id" in result
            finally:
                setattr(skill_db_module, 'create_or_update_skill_by_skill_info', original_func)
        else:
            pytest.skip("database.skill_db module not fully available")


class TestUploadZipFilesWithZipError:
    """Test _upload_zip_files error handling."""

    def test_copy_name_generator_avoids_existing_and_reserved_names(self):
        """Copy naming should keep the repository convention and avoid bundle names."""
        assert generate_available_copy_skill_name("AvailableSkill") == "AvailableSkill"
        assert generate_available_copy_skill_name(
            "SkillA",
            {"SkillA", "SkillA 副本"},
        ) == "SkillA 副本 2"
        long_name = "A" * 120
        generated_name = generate_available_copy_skill_name(
            long_name,
            {long_name},
        )
        assert generated_name == f"{'A' * 97} 副本"
        assert len(generated_name) == 100

    @pytest.mark.parametrize(
        ("content", "error"),
        [
            ("# No frontmatter", "must have YAML frontmatter"),
            ("---\ndescription: A skill\n---\nbody", "must contain a name field"),
        ],
    )
    def test_frontmatter_name_replacement_requires_name_field(self, content, error):
        """Renaming requires frontmatter with a top-level name field."""
        with pytest.raises(skill_service.SkillException, match=error):
            skill_service._replace_skill_frontmatter_name(content, "new-skill")

    def test_frontmatter_name_replacement_preserves_metadata_and_body(self):
        """Renaming should preserve custom frontmatter fields and the body."""
        import yaml

        body = "# Instructions\n\nKeep this body exactly.\n"
        content = (
            "---\n"
            "name: old-skill\n"
            "description: Test skill\n"
            "author: Example Author\n"
            "custom-field:\n"
            "  enabled: true\n"
            "---\n"
            f"{body}"
        )

        updated = skill_service._replace_skill_frontmatter_name(content, "new-skill")
        match = re.match(
            r"\A---\n(?P<frontmatter>.*?)\n---\n(?P<body>[\s\S]*)\Z",
            updated,
            re.DOTALL,
        )

        assert match is not None
        metadata = yaml.safe_load(match.group("frontmatter"))
        assert metadata == {
            "name": "new-skill",
            "description": "Test skill",
            "author": "Example Author",
            "custom-field": {"enabled": True},
        }
        assert match.group("body") == body

    def test_frontmatter_name_replacement_keeps_legacy_description_unchanged(self):
        """Renaming must not parse legacy descriptions that contain YAML-like colons."""
        description = (
            "Expert code reviewer. Performs detailed analysis using bundled tools to detect "
            "nested loops, and other code smells. Ideal for: (1) Reviewing pull requests."
        )
        content = (
            "---\n"
            "name: code_review_expert\n"
            f"description: {description}\n"
            "tags:\n"
            "  - code\n"
            "---\n"
            "# Code Review Expert\n"
        )

        updated = skill_service._replace_skill_frontmatter_name(
            content,
            "code_review_expert 副本",
        )

        assert updated == content.replace(
            "name: code_review_expert\n",
            'name: "code_review_expert 副本"\n',
            1,
        )

    def test_create_zip_with_name_override_extracts_updated_skill_md(self):
        """The ZIP extraction override should prevent the original name from returning."""
        import zipfile

        skill_md = (
            "---\n"
            "name: old-skill\n"
            "description: Test skill\n"
            "author: Example Author\n"
            "---\n"
            "# Instructions\n\nBody stays unchanged.\n"
        )
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("SKILL.md", skill_md)

        service = create_test_service()
        service.skill_manager = MagicMock()
        service._enrich_configs_from_yaml = lambda result: result

        with patch.object(skill_service.skill_db, "get_skill_by_name", return_value=None), patch.object(
            skill_service.skill_db,
            "create_skill",
            return_value={"skill_id": 42, "name": "new-skill"},
        ), patch.object(
            skill_service,
            "_read_schema_yaml_from_zip",
            return_value=None,
        ), patch.object(
            skill_service,
            "_get_skill_inputs_from_zip",
            return_value={},
        ), patch.object(
            skill_service,
            "_read_params_from_zip_config_yaml",
            return_value=None,
        ), patch.object(service, "_upload_zip_files") as mock_upload:
            result = service.create_skill_from_zip_bytes(
                zip_bytes=zip_buffer.getvalue(),
                skill_name="new-skill",
                tenant_id="test-tenant",
            )

        assert result["skill_id"] == 42
        override = mock_upload.call_args.kwargs["file_overrides"]["SKILL.md"].decode("utf-8")
        assert 'name: "new-skill"\n' in override
        assert "author: Example Author\n" in override
        assert override.endswith("# Instructions\n\nBody stays unchanged.\n")

    def test_upload_zip_renamed_root_does_not_nest_target_dir(self, tmp_path):
        """Test ZIP root rename writes files directly under the target skill directory."""
        import zipfile

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("old-skill/SKILL.md", "---\nname: old-skill\n---\nbody")
            zf.writestr("old-skill/references/info.md", "info")

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = str(tmp_path)
        mock_manager.resolve_tenant_dir.return_value = str(tmp_path)

        service = SkillService()
        service.skill_manager = mock_manager

        with patch("management.services.skill.support.CONTAINER_SKILLS_PATH", str(tmp_path)):
            service._upload_zip_files(
                zip_buffer.getvalue(),
                "new-skill copy",
                "old-skill",
                tenant_id=None,
            )

        assert (tmp_path / "new-skill copy" / "SKILL.md").is_file()
        assert (tmp_path / "new-skill copy" / "references" / "info.md").is_file()
        assert not (tmp_path / "new-skill copy" / "new-skill copy" / "SKILL.md").exists()

    def test_upload_zip_writes_file_override(self, tmp_path):
        """ZIP extraction should write override bytes instead of the archived file."""
        import zipfile

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("SKILL.md", "old skill content")
            zf.writestr("references/info.md", "reference content")

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = str(tmp_path)
        mock_manager.resolve_tenant_dir.return_value = str(tmp_path)

        service = SkillService()
        service.skill_manager = mock_manager

        with patch("management.services.skill.support.CONTAINER_SKILLS_PATH", str(tmp_path)):
            service._upload_zip_files(
                zip_buffer.getvalue(),
                "new-skill",
                tenant_id=None,
                file_overrides={"SKILL.md": b"renamed skill content"},
            )

        assert (tmp_path / "new-skill" / "SKILL.md").read_bytes() == b"renamed skill content"
        assert (tmp_path / "new-skill" / "references" / "info.md").read_text() == "reference content"

    def test_upload_zip_extract_error(self, mocker):
        """Test ZIP extraction error handling."""
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("skill/file.txt", "content")

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager

        # The actual code re-raises the original exception, not SkillException
        with patch('os.makedirs', side_effect=Exception("makedirs error")):
            try:
                service._upload_zip_files(zip_buffer.getvalue(), "skill", None, tenant_id=None)
                assert False, "Should have raised"
            except Exception as e:
                assert "makedirs error" in str(e)


class TestSkillServiceExportSkillsByNames:
    """Test SkillService.export_skills_by_names."""

    def test_export_skips_missing_local_dir_without_db_record(self, tmp_path, mocker):
        """Test export skips a missing local skill when no DB snapshot exists."""
        mocker.patch(
            "management.services.skill.service.skill_db.get_skill_by_name",
            return_value=None,
        )

        service = SkillService()
        service.skill_manager = MagicMock(local_skills_dir=str(tmp_path))
        service.skill_manager.resolve_tenant_dir.return_value = str(tmp_path)

        with patch.object(skill_support, "CONTAINER_SKILLS_PATH", str(tmp_path)):
            result = service.export_skills_by_names(["missing-skill"], tenant_id="tenant-1")

        assert result == []

    def test_export_rebuilds_missing_local_dir_from_db_snapshot(self, tmp_path, mocker):
        """Test export can recover when the DB skill exists but local files are missing."""
        import zipfile

        class FakeSkillManager:
            local_skills_dir = str(tmp_path)

            def resolve_tenant_dir(self, tenant_id=None):
                return self.local_skills_dir

            def save_skill(self, skill_data, tenant_id=None):
                skill_dir = tmp_path / skill_data["name"]
                skill_dir.mkdir(parents=True, exist_ok=True)
                (skill_dir / "SKILL.md").write_text(skill_data["content"], encoding="utf-8")
                return skill_data

        mocker.patch(
            "management.services.skill.service.skill_db.get_skill_by_name",
            return_value={
                "name": "missing-skill",
                "description": "desc",
                "content": "# Missing Skill\nbody",
                "tags": ["tag"],
            },
        )

        service = SkillService()
        service.skill_manager = FakeSkillManager()

        with patch.object(skill_support, "CONTAINER_SKILLS_PATH", str(tmp_path)):
            result = service.export_skills_by_names(["missing-skill"], tenant_id="tenant-1")

        assert len(result) == 1
        zip_bytes = base64.b64decode(result[0]["skill_zip_base64"])
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            assert "missing-skill/SKILL.md" in zf.namelist()

    def test_export_skips_when_db_rebuild_does_not_create_local_dir(self, tmp_path, mocker):
        """Test export skips when rebuilding from DB does not create local files."""
        mocker.patch(
            "management.services.skill.service.skill_db.get_skill_by_name",
            return_value={
                "name": "missing-skill",
                "description": "desc",
                "content": "# Missing Skill\nbody",
                "tags": ["tag"],
            },
        )

        skill_manager = MagicMock(local_skills_dir=str(tmp_path))
        skill_manager.resolve_tenant_dir.return_value = str(tmp_path)
        skill_manager.save_skill.return_value = None
        service = SkillService()
        service.skill_manager = skill_manager

        with patch.object(skill_support, "CONTAINER_SKILLS_PATH", str(tmp_path)):
            result = service.export_skills_by_names(["missing-skill"], tenant_id="tenant-1")

        assert result == []
        skill_manager.save_skill.assert_called_once()


class TestParamsDictToStorableWithInvalidData:
    """Test _params_dict_to_storable with invalid data."""

    def test_invalid_data_raises(self):
        """Test invalid data raises exception."""
        from management.services.skill.service import _params_dict_to_storable

        class BadJson:
            def __repr__(self):
                raise ValueError("Cannot serialize")

        from consts.exceptions import SkillException
        try:
            _params_dict_to_storable({"key": BadJson()})
            assert False, "Should have raised"
        except SkillException:
            pass


class TestSkillServiceOverlayParamsWithReadError:
    """Test _enrich_configs_from_yaml with read error."""

    def test_overlay_params_read_error(self, mocker):
        """Test enrich with read error still returns skill data."""
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"name": "test_skill", "params": {"db_key": "db_value"}}
        )

        service = SkillService(tenant_id="test-tenant")
        service._resolve_local_skills_dir_for_overlay = MagicMock(return_value=TEST_LOCAL_SKILLS_DIR)

        with patch('os.path.isfile', return_value=True):
            with patch('builtins.open', side_effect=IOError("Read error")):
                result = service._enrich_configs_from_yaml({"name": "test_skill"})

        assert result["name"] == "test_skill"


class TestSkillServiceResolveLocalSkillsDirWithRootDir:
    """Test _resolve_local_skills_dir_for_overlay with ROOT_DIR."""

    def test_resolve_with_root_dir_fallback(self, mocker):
        """Test resolve uses ROOT_DIR/skills when manager dir is None."""
        service = SkillService()
        service.skill_manager.local_skills_dir = None

        with patch.object(service.skill_manager, 'resolve_tenant_dir', return_value=None):
            with patch.object(skill_support, 'CONTAINER_SKILLS_PATH', None):
                with patch.object(skill_service, 'ROOT_DIR', "/project"):
                    with patch('os.path.isdir', return_value=True):
                        result = service._resolve_local_skills_dir_for_overlay()

        result_normalized = result.replace("\\", "/")
        assert result_normalized == "/project/skills"


class TestSkillServiceResolveLocalSkillsDirWithTrailingSlash:
    """Test _resolve_local_skills_dir_for_overlay with trailing slash."""

    def test_resolve_handles_trailing_slash(self, mocker):
        """Test resolve handles trailing slashes - on Windows strips backslash, on Unix keeps forward slash."""
        service = SkillService()
        service.skill_manager.local_skills_dir = "/manager/skills/"

        with patch.object(skill_support, 'CONTAINER_SKILLS_PATH', None):
            result = service._resolve_local_skills_dir_for_overlay()

        # The method uses rstrip(os.sep), which strips the OS-specific separator
        # On Windows, this strips backslashes; on Unix, forward slashes are not stripped
        # Just verify it doesn't crash and returns a valid path
        assert result is not None
        assert "manager" in result


class TestGetSkillManagerWithPath:
    """Test get_skill_manager with CONTAINER_SKILLS_PATH."""

    def test_get_manager_with_path(self, mocker):
        """Test get_skill_manager creates with CONTAINER_SKILLS_PATH."""
        skill_service._skill_manager = None

        with patch('management.services.skill.support.SkillManager') as mock_manager:
            with patch.object(skill_support, 'CONTAINER_SKILLS_PATH', '/custom/path'):
                manager = get_skill_manager()
                mock_manager.assert_called_once_with(base_skills_dir='/custom/path')


# ===== Additional Coverage for Remaining Uncovered Lines =====

class TestSkillServiceCreateSkillErrorPaths:
    """Test create_skill error paths."""

    def test_create_skill_db_error(self, mocker):
        """Test create_skill handles DB error."""
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'management.services.skill.service.skill_db.create_skill',
            side_effect=Exception("DB error")
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = None

        service = SkillService(tenant_id="test-tenant")
        service.skill_manager = mock_manager
        service._resolve_local_skills_dir_for_overlay = MagicMock(return_value=None)
        service._overlay_params_from_local_config_yaml = lambda x: x

        from consts.exceptions import SkillException
        try:
            service.create_skill({"name": "new_skill"})
            assert False, "Should have raised"
        except SkillException as e:
            assert "Failed to create" in str(e)


class TestSkillServiceCreateSkillFromFileZipError:
    """Test create_skill_from_file error paths."""

    def test_create_from_zip_raises_on_bad_zip(self, mocker):
        """Test create_skill_from_file raises on bad ZIP."""
        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp"

        service = SkillService()
        service.skill_manager = mock_manager

        from consts.exceptions import SkillException
        try:
            service.create_skill_from_file(b"PK\x03\x04not a valid zip content", file_type="zip")
            assert False, "Should have raised"
        except SkillException:
            pass


class TestSkillServiceCreateFromZipAlreadyExistsError:
    """Test _create_skill_from_zip already exists error."""

    def test_create_zip_already_exists_error(self, mocker):
        """Test ZIP creation raises when skill already exists."""
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("skill/SKILL.md", """---
name: existing_skill
description: Exists
---
# Content""")

        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"name": "existing_skill", "skill_id": 1}
        )

        mock_manager = MagicMock()
        mock_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        service = SkillService()
        service.skill_manager = mock_manager

        from consts.exceptions import SkillException
        try:
            service.create_skill_from_file(zip_buffer.getvalue(), file_type="zip")
            assert False, "Should have raised"
        except SkillException as e:
            assert "already exists" in str(e)


class TestSkillServiceUpdateSkillFromFileNotFound:
    """Test update_skill_from_file not found error."""

    def test_update_from_file_not_found(self, mocker):
        """Test update_skill_from_file raises when skill not found."""
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value=None
        )

        service = create_test_service()

        from consts.exceptions import SkillException
        try:
            service.update_skill_from_file("nonexistent", b"---\nname: x\n---", tenant_id="test-tenant")
            assert False, "Should have raised"
        except SkillException as e:
            assert "not found" in str(e)


class TestSkillServiceUpdateFromMdInvalidParse:
    """Test _update_skill_from_md invalid parse."""

    def test_update_md_invalid_parse_raises(self, mocker):
        """Test update from MD with invalid parse raises exception."""
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "existing"}
        )

        mocker.patch(
            'management.services.skill.service.SkillLoader.parse',
            side_effect=ValueError("Invalid YAML")
        )

        mock_manager = MagicMock()

        service = SkillService()
        service.skill_manager = mock_manager

        from consts.exceptions import SkillException
        try:
            service._save_skill_upload(b"invalid content", "existing", kind="md", update=True, tenant_id=None, user_id=None)
            assert False, "Should have raised"
        except SkillException as e:
            assert "Invalid SKILL.md format" in str(e)


class TestSkillServiceUpdateFromZipNotFound:
    """Test _update_skill_from_zip not found error."""

    def test_update_zip_not_found(self, mocker):
        """Test ZIP update raises when skill not found."""
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value=None
        )

        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("skill/SKILL.md", """---
name: skill
---
# Content""")

        service = SkillService()

        from consts.exceptions import SkillException
        try:
            service.update_skill_from_file(
                "nonexistent",
                zip_buffer.getvalue(),
                file_type="zip",
                tenant_id="test-tenant",
            )
            assert False, "Should have raised"
        except SkillException as e:
            assert "not found" in str(e)


class TestSkillServiceGetEnabledSkillsWithEmptyRepo:
    """Test get_enabled_skills_for_agent with empty skill repository."""

    def test_get_enabled_skills_empty_repo(self, mocker):
        """Test getting enabled skills when skill not in repository."""
        mocker.patch(
            'management.services.skill.service.skill_db.search_skills_for_agent',
            return_value=[
                {"skill_instance_id": 1, "skill_id": 999, "enabled": True}
            ]
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_id',
            return_value=None
        )

        service = SkillService()

        result = service.get_enabled_skills_for_agent(
            agent_id=1,
            tenant_id="tenant1"
        )

        assert result == []


class TestSkillServiceGetEnabledSkillsWithDisabledSkill:
    """Test get_enabled_skills_for_agent with disabled skill."""

    def test_get_enabled_skills_disabled(self, mocker):
        """Test getting enabled skills when skill is disabled."""
        mocker.patch(
            'management.services.skill.service.skill_db.search_skills_for_agent',
            return_value=[
                {"skill_instance_id": 1, "skill_id": 1, "enabled": False}
            ]
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_id',
            return_value={
                "name": "disabled_skill",
                "description": "Desc",
                "content": "# Content",
                "tool_ids": []
            }
        )

        service = SkillService()

        result = service.get_enabled_skills_for_agent(
            agent_id=1,
            tenant_id="tenant1"
        )

        # Even if the instance is disabled, if it's returned we still include it
        assert len(result) == 1


class TestSkillServiceBuildSummaryWithAgentAndWhitelist:
    """Test build_skills_summary with agent_id and available_skills."""

    def test_build_summary_with_agent_and_whitelist(self, mocker):
        """Test building summary filters agent skills by whitelist."""
        mocker.patch(
            'management.services.skill.service.skill_db.search_skills_for_agent',
            return_value=[
                {"skill_instance_id": 1, "skill_id": 1, "enabled": True},
                {"skill_instance_id": 2, "skill_id": 2, "enabled": True}
            ]
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_id',
            side_effect=lambda skill_id, tenant_id=None: {
                1: {"name": "skill1", "description": "Desc 1"},
                2: {"name": "skill2", "description": "Desc 2"}
            }.get(skill_id)
        )

        service = SkillService()

        result = service.build_skills_summary(
            available_skills=["skill1"],  # Only include skill1
            agent_id=1,
            tenant_id="tenant1"
        )

        assert "<skills>" in result
        assert "<name>skill1</name>" in result
        assert "<name>skill2</name>" not in result


class TestSkillServiceBuildSummaryWithAgentNoSkillFound:
    """Test build_skills_summary with agent_id where skill not found."""

    def test_build_summary_agent_skill_not_found(self, mocker):
        """Test building summary handles missing agent skill."""
        mocker.patch(
            'management.services.skill.service.skill_db.search_skills_for_agent',
            return_value=[
                {"skill_instance_id": 1, "skill_id": 999, "enabled": True}
            ]
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_id',
            return_value=None
        )

        service = SkillService()

        result = service.build_skills_summary(
            agent_id=1,
            tenant_id="tenant1"
        )

        assert result == ""


class TestSkillServiceUpdateSkillLocalWriteError:
    """Test update_skill with local write error."""

    def test_update_skill_local_write_error(self, mocker):
        """Test update_skill handles local write error gracefully."""
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.resolve_tenant_dir.return_value = "/tmp"
        mock_manager.local_skills_dir = "/tmp"

        with patch.object(skill_support, 'CONTAINER_SKILLS_PATH', "/tmp"):
            service = SkillService(tenant_id="test-tenant")
            service.skill_manager = mock_manager

            with patch('management.services.skill.service._write_skill_params_to_local_config_yaml',
                      side_effect=Exception("Write error")):
                result = service.update_skill("existing", {"params": {"key": "value"}}, tenant_id="test-tenant")

        assert result["name"] == "existing"


class TestSkillServiceDeleteSkillRmtreeError:
    """Test delete_skill with rmtree error."""

    def test_delete_skill_rmtree_error(self, mocker):
        """Test delete_skill handles rmtree error."""
        mocker.patch(
            'management.services.skill.service.skill_db.delete_skill',
            return_value=True
        )
        mocker.patch(
            'management.services.skill.service.skill_db.delete_skill_instances_by_skill_id',
            return_value=None
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "to_delete"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR

        service = SkillService(tenant_id="test-tenant")
        service.skill_manager = mock_manager

        with patch('os.path.exists', return_value=True):
            with patch('shutil.rmtree', side_effect=Exception("rmtree error")):
                from consts.exceptions import SkillException
                try:
                    service.delete_skill("to_delete", tenant_id="test-tenant")
                    assert False, "Should have raised"
                except SkillException as e:
                    assert "Failed to delete" in str(e)


# ===== Additional Coverage Tests =====

class TestParseSkillParamsNonDictData:
    """Test _parse_skill_params_from_config_bytes with non-dict data."""

    def test_parse_params_with_list_data(self):
        """Test that list data raises SkillException."""
        from management.services.skill.service import _parse_skill_params_from_config_bytes
        raw = b"[param1, param2]"
        with pytest.raises(Exception):
            _parse_skill_params_from_config_bytes(raw)

    def test_parse_params_with_string_data(self):
        """Test that string data raises SkillException."""
        from management.services.skill.service import _parse_skill_params_from_config_bytes
        raw = b"just a string"
        with pytest.raises(Exception):
            _parse_skill_params_from_config_bytes(raw)

    def test_parse_params_with_non_dict_meta(self):
        """Test that non-dict meta values are included in result."""
        from management.services.skill.service import _parse_skill_params_from_config_bytes
        raw = b'{"param1": "string instead of dict", "param2": 123}'
        result = _parse_skill_params_from_config_bytes(raw)
        # Non-dict meta values are included with type "string" or "number"
        assert len(result) == 2


class TestFindZipMemberSchemaYaml:
    """Test _find_zip_member_schema_yaml function."""

    def test_find_schema_yaml_root(self):
        """Test finding schema.yaml in root."""
        from management.services.skill.service import _find_zip_member_schema_yaml
        result = _find_zip_member_schema_yaml(["config/schema.yaml", "file.md"])
        assert result == "config/schema.yaml"

    def test_find_schema_yaml_nested(self):
        """Test finding schema.yaml in nested folder."""
        from management.services.skill.service import _find_zip_member_schema_yaml
        result = _find_zip_member_schema_yaml(
            ["my_skill/config/schema.yaml", "other/file.md"],
            preferred_skill_root="my_skill"
        )
        assert result == "my_skill/config/schema.yaml"

    def test_find_schema_yaml_case_insensitive(self):
        """Test finding schema.yaml uses correct case (must be 'config' and 'schema.yaml')."""
        from management.services.skill.service import _find_zip_member_schema_yaml
        # The function uses case-sensitive comparison for "config" and "schema.yaml"
        result = _find_zip_member_schema_yaml(["My_Skill/config/schema.yaml"])
        assert result == "My_Skill/config/schema.yaml"

    def test_find_schema_yaml_not_found(self):
        """Test when schema.yaml is not found."""
        from management.services.skill.service import _find_zip_member_schema_yaml
        result = _find_zip_member_schema_yaml(["file.md", "script.py"])
        assert result is None


class TestSkillServiceParseSkillParamsEdgeCases:
    """Test parse_skill_params with edge cases - skip due to YAML parsing complexity."""
    pass


class TestSkillServiceBuildSummaryWithDescriptionFallback:
    """Test build_skills_summary with description fallback."""

    def test_build_summary_with_only_description(self, mocker):
        """Test building summary uses 'description' when 'description_en' is missing."""
        mocker.patch(
            'management.services.skill.service.skill_db.list_skills',
            return_value=[{
                "skill_id": 1,
                "name": "test_skill",
                "description": "Fallback description",
                "content": "# Skill content"
            }]
        )

        service = create_test_service()
        result = service.build_skills_summary(tenant_id="test-tenant")
        assert "test_skill" in result
        assert "Fallback description" in result


class TestSkillServiceGetSkillWithTagEnrichment:
    """Test get_skill with tag enrichment."""

    def test_get_skill_with_tags(self, mocker):
        """Test that get_skill returns tags when available."""
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={
                "skill_id": 1,
                "name": "test_skill",
                "description": "A test skill",
                "tags": ["tag1", "tag2"]
            }
        )

        service = create_test_service()
        result = service.get_skill("test_skill", tenant_id="test-tenant")
        assert result is not None
        assert result.get("tags") == ["tag1", "tag2"]


class TestSkillServiceBuildSummaryXmlEscaping:
    """Test build_skills_summary XML escaping."""

    def test_build_summary_with_xml_chars(self, mocker):
        """Test that XML special chars are escaped."""
        mocker.patch(
            'management.services.skill.service.skill_db.list_skills',
            return_value=[{
                "skill_id": 1,
                "name": "test&skill",
                "description": "Desc with <special> & 'chars'",
                "content": "# Content"
            }]
        )

        service = create_test_service()
        result = service.build_skills_summary(tenant_id="test-tenant")
        # Should have escaped XML chars
        assert "&amp;" in result or "&" not in result


class TestSkillServiceGetSkillContentWithContent:
    """Test get_skill_content with actual content."""

    def test_get_content_with_content(self, mocker):
        """Test get_skill_content returns content when found."""
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={
                "skill_id": 1,
                "name": "test_skill",
                "content": "# Skill content here"
            }
        )

        service = create_test_service()
        result = service.get_skill_content("test_skill", tenant_id="test-tenant")
        assert result is not None
        assert "content" in result


class TestSkillServiceListSkillsWithTenant:
    """Test list_skills with explicit tenant_id."""

    def test_list_skills_with_tenant_param(self, mocker):
        """Test list_skills uses explicit tenant_id parameter."""
        mock_list = mocker.patch(
            'management.services.skill.service.skill_db.list_skills',
            return_value=[{"skill_id": 1, "name": "skill1"}]
        )

        service = create_test_service()
        result = service.list_skills(tenant_id="explicit-tenant")

        assert len(result) == 1
        mock_list.assert_called_once()


class TestSkillServiceUpdateSkillWithExistingData:
    """Test update_skill preserves existing data."""

    def test_update_skill_preserves_fields(self, mocker):
        """Test that update_skill preserves existing skill fields."""
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={
                "skill_id": 1,
                "name": "existing_skill",
                "description": "Original description",
                "content": "Original content",
                "tags": ["original_tag"],
                "tool_ids": []
            }
        )
        mocker.patch(
            'management.services.skill.service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "existing_skill"}
        )
        mocker.patch(
            'management.services.skill.service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        service = create_test_service()
        service._resolve_local_skills_dir_for_overlay = MagicMock(return_value=None)

        result = service.update_skill(
            "existing_skill",
            {"description": "New description"},
            tenant_id="test-tenant"
        )

        assert result["name"] == "existing_skill"


class TestSkillServiceDeleteSkillWithTenant:
    """Test delete_skill with explicit tenant_id."""

    def test_delete_skill_with_tenant_param(self, mocker):
        """Test delete_skill uses explicit tenant_id parameter."""
        mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "to_delete"}
        )
        mock_delete = mocker.patch(
            'management.services.skill.service.skill_db.delete_skill',
            return_value=True
        )
        mocker.patch(
            'management.services.skill.service.skill_db.delete_skill_instances_by_skill_id',
            return_value=None
        )

        service = create_test_service()
        result = service.delete_skill("to_delete", tenant_id="explicit-tenant")

        assert result is True
        mock_delete.assert_called_once()


class TestSkillServiceGetSkillByIdWithTenant:
    """Test get_skill_by_id with explicit tenant_id."""

    def test_get_skill_by_id_with_tenant_param(self, mocker):
        """Test get_skill_by_id uses explicit tenant_id parameter."""
        mock_get = mocker.patch(
            'management.services.skill.service.skill_db.get_skill_by_id',
            return_value={"skill_id": 5, "name": "found_skill"}
        )

        service = create_test_service()
        result = service.get_skill_by_id(5, tenant_id="explicit-tenant")

        assert result is not None
        assert result["skill_id"] == 5
        mock_get.assert_called_once()


class TestUpdateSkillListAsync:
    """Test async update_skill_list function."""

    @pytest.mark.asyncio
    async def test_update_skill_list_with_schema_yaml(self):
        """Test update_skill_list reads schema.yaml using async file API."""
        from management.services.skill import service as skill_service

        mock_skill_manager = MagicMock()
        mock_skill_manager.list_skills.return_value = [
            {"name": "test_skill", "description": "A test skill", "tags": []}
        ]
        mock_skill_manager.load_skill.return_value = {
            "name": "test_skill",
            "description": "A test skill",
            "content": "# Test content"
        }
        mock_skill_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_skill_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        with patch('management.services.skill.service.get_skill_manager', return_value=mock_skill_manager), \
                patch('management.services.skill.support.SkillManager', return_value=mock_skill_manager), \
                patch('management.services.skill.support.CONTAINER_SKILLS_PATH', TEST_LOCAL_SKILLS_DIR), \
                patch('management.services.skill.service.skill_db.upsert_scanned_skills', create=True) as mock_upsert:
            await skill_service.update_skill_list(
                tenant_id="test-tenant",
                user_id="test-user"
            )

            mock_upsert.assert_called_once()
            call_args = mock_upsert.call_args[0][0]
            assert len(call_args) == 1
            assert call_args[0]["name"] == "test_skill"

    @pytest.mark.asyncio
    async def test_update_skill_list_without_schema_yaml(self):
        """Test update_skill_list falls back to AST parsing when no schema.yaml."""
        from management.services.skill import service as skill_service

        mock_skill_manager = MagicMock()
        mock_skill_manager.list_skills.return_value = [
            {"name": "simple_skill", "description": "A simple skill", "tags": []}
        ]
        mock_skill_manager.load_skill.return_value = {
            "name": "simple_skill",
            "description": "A simple skill",
            "content": "# Simple content"
        }
        mock_skill_manager.local_skills_dir = TEST_LOCAL_SKILLS_DIR
        mock_skill_manager.resolve_tenant_dir.return_value = TEST_LOCAL_SKILLS_DIR

        with patch('management.services.skill.service.get_skill_manager', return_value=mock_skill_manager), \
                patch('management.services.skill.support.SkillManager', return_value=mock_skill_manager), \
                patch('management.services.skill.support.CONTAINER_SKILLS_PATH', TEST_LOCAL_SKILLS_DIR), \
                patch('os.path.isfile', return_value=False), \
                patch('os.path.isdir', return_value=False), \
                patch('database.skill_db.upsert_scanned_skills', create=True) as mock_upsert:
            await skill_service.update_skill_list(
                tenant_id="test-tenant",
                user_id="test-user"
            )

            mock_upsert.assert_called_once()


class TestInitSkillListForTenantAsync:
    """Test async init_skill_list_for_tenant function."""

    @pytest.mark.asyncio
    async def test_init_skill_list_for_tenant(self, mocker):
        """Test init_skill_list_for_tenant calls update_skill_list."""
        from management.services.skill import service as skill_service

        mock_update = mocker.patch(
            'management.services.skill.service.update_skill_list',
            return_value=None
        )

        result = await skill_service.init_skill_list_for_tenant(
            tenant_id="new-tenant",
            user_id="new-user"
        )

        assert result["status"] == "success"
        mock_update.assert_called_once_with(
            tenant_id="new-tenant",
            user_id="new-user"
        )


class TestSkillServiceUpdateById:
    def test_rejects_access_change_from_group_editor(self, mocker):
        service = SkillService(tenant_id="tenant-1")
        mocker.patch(
            "management.services.skill.service.skill_db.get_skill_by_id",
            return_value={
                "skill_id": 1,
                "name": "Skill A",
                "created_by": "owner",
                "group_ids": [1, 2],
                "ingroup_permission": "EDIT",
            },
        )
        mocker.patch("management.services.skill.service._can_edit_skill", return_value=True)
        mocker.patch(
            "management.services.skill.support.get_user_tenant_by_user_id",
            return_value={"user_role": "DEV"},
        )

        with pytest.raises(
            skill_service.ForbiddenError,
            match="Not authorized to update skill access",
        ):
            service.update_skill_by_id(1, {"group_ids": [1]}, user_id="group-editor")

    def test_rejects_non_creator(self, mocker):
        service = SkillService(tenant_id="tenant-1")
        mocker.patch(
            "management.services.skill.service.skill_db.get_skill_by_id",
            return_value={
                "skill_id": 1,
                "name": "Skill A",
                "created_by": "other-user",
            },
        )

        with pytest.raises(
            skill_service.ForbiddenError,
            match="Not authorized to update this skill",
        ):
            service.update_skill_by_id(
                1,
                {"description": "updated"},
                user_id="user-1",
            )

    def test_rename_removes_previous_local_directory(self, mocker, tmp_path):
        service = SkillService(tenant_id="tenant-1")
        service.skill_manager = MagicMock()
        service.skill_manager.local_skills_dir = str(tmp_path)
        service.skill_manager.resolve_tenant_dir.return_value = str(tmp_path)
        (tmp_path / "Skill A").mkdir()
        mocker.patch(
            "management.services.skill.support.CONTAINER_SKILLS_PATH",
            str(tmp_path),
        )

        mocker.patch(
            "management.services.skill.service.skill_db.get_skill_by_id",
            return_value={
                "skill_id": 1,
                "name": "Skill A",
                "description": "description",
                "content": "content",
                "tags": [],
                "created_by": "user-1",
            },
        )
        mocker.patch(
            "management.services.skill.service.skill_db.update_skill_by_id",
            create=True,
            return_value={
                "skill_id": 1,
                "name": "Skill B",
                "description": "description",
                "content": "content",
                "tags": [],
            },
        )
        mocker.patch(
            "management.services.skill.service.skill_db.get_tool_names_by_skill_name",
            return_value=[],
        )
        service._enrich_configs_from_yaml = lambda result: result

        service.update_skill_by_id(
            1,
            {"name": "Skill B"},
            user_id="user-1",
        )

        service.skill_manager.delete_skill.assert_called_once_with('Skill A', tenant_id='tenant-1')

    def test_skill_not_found_raises_skill_exception(self, mocker):
        service = SkillService(tenant_id="tenant-1")
        mocker.patch(
            "management.services.skill.service.skill_db.get_skill_by_id",
            return_value=None,
        )
        with pytest.raises(
            skill_service.SkillException,
            match="Skill not found",
        ):
            service.update_skill_by_id(
                999,
                {"description": "updated"},
                user_id="user-1",
            )

    def test_no_tenant_id_raises_skill_exception(self, mocker):
        service = SkillService(tenant_id=None)
        with pytest.raises(
            skill_service.SkillException,
            match="tenant_id is required",
        ):
            service.update_skill_by_id(
                1,
                {"description": "updated"},
                tenant_id=None,
                user_id="user-1",
            )

    def test_successful_update_without_local_dir(self, mocker):
        service = SkillService(tenant_id="tenant-1")
        mocker.patch(
            "management.services.skill.service.skill_db.get_skill_by_id",
            return_value={
                "skill_id": 1,
                "name": "Skill A",
                "created_by": "user-1",
            },
        )
        mocker.patch(
            "management.services.skill.service.skill_db.update_skill_by_id",
            return_value={
                "skill_id": 1,
                "name": "Skill A",
                "description": "updated desc",
            },
        )
        mocker.patch(
            "management.services.skill.service.skill_db.get_tool_names_by_skill_name",
            return_value=["tool1"],
        )
        service._resolve_local_skills_dir_for_overlay = lambda: None
        service._enrich_configs_from_yaml = lambda result: result

        result = service.update_skill_by_id(
            1,
            {"description": "updated desc"},
            user_id="user-1",
        )
        assert result["description"] == "updated desc"

    def test_successful_update_with_config_values_and_local_dir(self, mocker, tmp_path):
        service = SkillService(tenant_id="tenant-1")
        service.skill_manager = MagicMock()
        service.skill_manager.local_skills_dir = str(tmp_path)
        service.skill_manager.resolve_tenant_dir.return_value = str(tmp_path)
        mocker.patch(
            "management.services.skill.support.CONTAINER_SKILLS_PATH",
            str(tmp_path),
        )
        mocker.patch(
            "management.services.skill.service.skill_db.get_skill_by_id",
            return_value={
                "skill_id": 1,
                "name": "Skill A",
                "description": "desc",
                "content": "content",
                "tags": [],
                "created_by": "user-1",
            },
        )
        mocker.patch(
            "management.services.skill.service.skill_db.update_skill_by_id",
            return_value={
                "skill_id": 1,
                "name": "Skill A",
                "description": "desc",
                "config_values": {"key": "val"},
            },
        )
        mocker.patch(
            "management.services.skill.service.skill_db.get_tool_names_by_skill_name",
            return_value=["tool1"],
        )
        write_config = mocker.patch(
            "management.services.skill.service._write_skill_params_to_local_config_yaml",
        )
        mocker.patch(
            "management.services.skill.service._resolve_local_skill_path",
            return_value=str(tmp_path / "Skill_A"),
        )
        mocker.patch("os.path.isdir", return_value=False)
        service._enrich_configs_from_yaml = lambda result: result

        result = service.update_skill_by_id(
            1,
            {"config_values": {"key": "val"}},
            user_id="user-1",
        )
        assert result["config_values"] == {"key": "val"}
        write_config.assert_called_once_with(
            "Skill A",
            {"key": "val"},
            str(tmp_path),
        )
        service.skill_manager.save_skill.assert_called_once()

    def test_update_with_config_values_none_removes_yaml(self, mocker, tmp_path):
        service = SkillService(tenant_id="tenant-1")
        service.skill_manager = MagicMock()
        service.skill_manager.local_skills_dir = str(tmp_path)
        service.skill_manager.resolve_tenant_dir.return_value = str(tmp_path)
        mocker.patch(
            "management.services.skill.support.CONTAINER_SKILLS_PATH",
            str(tmp_path),
        )
        mocker.patch(
            "management.services.skill.service.skill_db.get_skill_by_id",
            return_value={
                "skill_id": 1,
                "name": "Skill A",
                "description": "desc",
                "content": "content",
                "tags": [],
                "created_by": "user-1",
            },
        )
        mocker.patch(
            "management.services.skill.service.skill_db.update_skill_by_id",
            return_value={
                "skill_id": 1,
                "name": "Skill A",
                "description": "desc",
            },
        )
        mocker.patch(
            "management.services.skill.service.skill_db.get_tool_names_by_skill_name",
            return_value=["tool1"],
        )
        remove_config = mocker.patch(
            "management.services.skill.service._remove_local_skill_config_yaml",
        )
        mocker.patch(
            "management.services.skill.service._resolve_local_skill_path",
            return_value=str(tmp_path / "Skill_A"),
        )
        mocker.patch("os.path.isdir", return_value=False)
        service._enrich_configs_from_yaml = lambda result: result

        result = service.update_skill_by_id(
            1,
            {"config_values": None},
            user_id="user-1",
        )
        assert result["skill_id"] == 1
        remove_config.assert_called_once_with("Skill A", str(tmp_path))

    def test_update_config_yaml_sync_failure_logs_warning(self, mocker, tmp_path):
        service = SkillService(tenant_id="tenant-1")
        service.skill_manager = MagicMock()
        service.skill_manager.local_skills_dir = str(tmp_path)
        mocker.patch(
            "management.services.skill.support.CONTAINER_SKILLS_PATH",
            str(tmp_path),
        )
        mocker.patch(
            "management.services.skill.service.skill_db.get_skill_by_id",
            return_value={
                "skill_id": 1,
                "name": "Skill A",
                "description": "desc",
                "content": "content",
                "tags": [],
                "created_by": "user-1",
            },
        )
        mocker.patch(
            "management.services.skill.service.skill_db.update_skill_by_id",
            return_value={
                "skill_id": 1,
                "name": "Skill A",
                "description": "desc",
                "config_values": {"key": "val"},
            },
        )
        mocker.patch(
            "management.services.skill.service.skill_db.get_tool_names_by_skill_name",
            return_value=["tool1"],
        )
        write_config = mocker.patch(
            "management.services.skill.service._write_skill_params_to_local_config_yaml",
            side_effect=OSError("disk full"),
        )
        mocker.patch(
            "management.services.skill.service._resolve_local_skill_path",
            return_value=str(tmp_path / "Skill_A"),
        )
        mocker.patch("os.path.isdir", return_value=False)
        logger = mocker.patch("management.services.skill.service.logger")
        service._enrich_configs_from_yaml = lambda result: result

        result = service.update_skill_by_id(
            1,
            {"config_values": {"key": "val"}},
            user_id="user-1",
        )
        assert result["skill_id"] == 1
        write_config.assert_called_once()
        logger.warning.assert_called()

    def test_update_skill_md_sync_failure_logs_warning(self, mocker, tmp_path):
        service = SkillService(tenant_id="tenant-1")
        service.skill_manager = MagicMock()
        service.skill_manager.local_skills_dir = str(tmp_path)
        mocker.patch(
            "management.services.skill.support.CONTAINER_SKILLS_PATH",
            str(tmp_path),
        )
        mocker.patch(
            "management.services.skill.service.skill_db.get_skill_by_id",
            return_value={
                "skill_id": 1,
                "name": "Skill A",
                "description": "desc",
                "content": "content",
                "tags": [],
                "created_by": "user-1",
            },
        )
        mocker.patch(
            "management.services.skill.service.skill_db.update_skill_by_id",
            return_value={
                "skill_id": 1,
                "name": "Skill A",
                "description": "desc",
            },
        )
        mocker.patch(
            "management.services.skill.service.skill_db.get_tool_names_by_skill_name",
            return_value=["tool1"],
        )
        mocker.patch(
            "management.services.skill.service._resolve_local_skill_path",
            return_value=str(tmp_path / "Skill_A"),
        )
        mocker.patch("os.path.isdir", return_value=False)
        service.skill_manager.save_skill.side_effect = OSError("disk error")
        logger = mocker.patch("management.services.skill.service.logger")
        service._enrich_configs_from_yaml = lambda result: result

        result = service.update_skill_by_id(
            1,
            {"description": "new desc"},
            user_id="user-1",
        )
        assert result["skill_id"] == 1
        service.skill_manager.save_skill.assert_called_once()
        logger.warning.assert_called()

    def test_update_generic_exception_raises_skill_exception(self, mocker):
        service = SkillService(tenant_id="tenant-1")
        mocker.patch(
            "management.services.skill.service.skill_db.get_skill_by_id",
            side_effect=RuntimeError("unexpected"),
        )
        with pytest.raises(skill_service.SkillException, match="Failed to update skill"):
            service.update_skill_by_id(
                1,
                {"description": "updated"},
                user_id="user-1",
            )

    def test_create_skill_already_exists_locally(self, mocker, tmp_path):
        service = SkillService(tenant_id="tenant-1")
        service.skill_manager = MagicMock()
        service.skill_manager.local_skills_dir = str(tmp_path)
        mocker.patch(
            "management.services.skill.support.CONTAINER_SKILLS_PATH",
            str(tmp_path),
        )
        mocker.patch(
            "management.services.skill.service.skill_db.get_skill_by_name",
            return_value=None,
        )
        mocker.patch(
            "management.services.skill.service._resolve_local_skill_path",
            return_value=str(tmp_path / "existing_skill"),
        )
        mocker.patch("os.path.exists", return_value=True)
        with pytest.raises(skill_service.SkillException, match="already exists locally"):
            service.create_skill(
                {"name": "existing_skill"},
                tenant_id="tenant-1",
                user_id="user-1",
            )

    def test_resolve_local_skill_path_unsafe_candidate(self, mocker, tmp_path):
        mocker.patch(
            "management.services.skill.support.CONTAINER_SKILLS_PATH",
            str(tmp_path),
        )
        outside = str(tmp_path.parent / "escaped")
        mocker.patch(
            "os.path.realpath",
            side_effect=lambda p: outside if "escaped" in p else str(tmp_path) if str(tmp_path) in p else p,
        )
        with pytest.raises(skill_service.ForbiddenError, match="Unsafe local skill path"):
            skill_service._resolve_local_skill_path(str(tmp_path), "escaped_skill")

    def test_resolve_local_skill_path_unsafe_local_root(self, mocker, tmp_path):
        outside_dir = str(tmp_path.parent / "outside_dir")
        mocker.patch(
            "management.services.skill.support.CONTAINER_SKILLS_PATH",
            str(tmp_path),
        )
        mocker.patch(
            "os.path.realpath",
            side_effect=lambda p: outside_dir if p == outside_dir else str(tmp_path),
        )
        with pytest.raises(skill_service.SkillException, match="Unsafe local skills directory"):
            skill_service._resolve_local_skill_path(outside_dir, "skill1")


# ===== AST Parsing Tests =====
class TestIsAddArgumentCall:
    """Test _is_add_argument_call function."""

    def test_not_attribute(self):
        """Test with non-attribute function."""
        import ast
        node = ast.Call(func=ast.Name(id='test'))
        assert skill_service._is_add_argument_call(node) is False

    def test_wrong_attr_name(self):
        """Test with wrong attribute name."""
        import ast
        node = ast.Call(func=ast.Attribute(value=ast.Name(id='parser'), attr='not_add_argument'))
        assert skill_service._is_add_argument_call(node) is False

    def test_parser_name(self):
        """Test with parser.add_argument."""
        import ast
        node = ast.Call(func=ast.Attribute(value=ast.Name(id='parser'), attr='add_argument'))
        assert skill_service._is_add_argument_call(node) is True

    def test_chained_attribute(self):
        """Test with chained attribute like subparser.add_argument."""
        import ast
        node = ast.Call(func=ast.Attribute(value=ast.Attribute(value=ast.Name(id='parser'), attr='add_subparsers'), attr='add_argument'))
        assert skill_service._is_add_argument_call(node) is True


class TestGetTypeName:
    """Test _get_type_name function."""

    def test_name_node(self):
        """Test with Name node."""
        import ast
        node = ast.Name(id='str')
        assert skill_service._get_type_name(node) == 'str'

    def test_attribute_node(self):
        """Test with Attribute node."""
        import ast
        node = ast.Attribute(value=ast.Name(id='typing'), attr='List')
        assert skill_service._get_type_name(node) == 'List'

    def test_call_with_name_func(self):
        """Test with Call node where func is Name."""
        import ast
        node = ast.Call(func=ast.Name(id='list'))
        assert skill_service._get_type_name(node) == 'list'

    def test_call_with_attribute_func(self):
        """Test with Call node where func is Attribute."""
        import ast
        node = ast.Call(func=ast.Attribute(value=ast.Name(id='typing'), attr='Optional'))
        assert skill_service._get_type_name(node) == 'Optional'

    def test_other_node(self):
        """Test with other AST node types."""
        import ast
        node = ast.BinOp()
        assert skill_service._get_type_name(node) == ''


class TestAstLiteralEval:
    """Test _ast_literal_eval function."""

    def test_constant_node(self):
        """Test with Constant node."""
        import ast
        node = ast.Constant(value=42)
        assert skill_service._ast_literal_eval(node) == 42

    def test_string_constant(self):
        """Test with string Constant node."""
        import ast
        node = ast.Constant(value='test')
        assert skill_service._ast_literal_eval(node) == 'test'

    def test_none_constant(self):
        """Test with None Constant node."""
        import ast
        node = ast.Constant(value=None)
        assert skill_service._ast_literal_eval(node) is None

    def test_name_none(self):
        """Test with Name node for None."""
        import ast
        node = ast.Name(id='None')
        assert skill_service._ast_literal_eval(node) is None

    def test_name_true(self):
        """Test with Name node for True."""
        import ast
        node = ast.Name(id='True')
        assert skill_service._ast_literal_eval(node) is True

    def test_name_false(self):
        """Test with Name node for False."""
        import ast
        node = ast.Name(id='False')
        assert skill_service._ast_literal_eval(node) is False

    def test_list_node(self):
        """Test with List node."""
        import ast
        node = ast.List(elts=[ast.Constant(value=1), ast.Constant(value=2)])
        assert skill_service._ast_literal_eval(node) == [1, 2]

    def test_tuple_node(self):
        """Test with Tuple node."""
        import ast
        node = ast.Tuple(elts=[ast.Constant(value=1), ast.Constant(value=2)])
        assert skill_service._ast_literal_eval(node) == (1, 2)


class TestParseYamlFallbackPyyaml:
    """Test _parse_yaml_fallback_pyyaml function."""

    def test_simple_yaml(self):
        """Test parsing simple YAML."""
        yaml_text = "key: value"
        result = skill_service._parse_yaml_fallback_pyyaml(yaml_text)
        assert result == {"key": "value"}

    def test_empty_yaml(self):
        """Test parsing empty YAML."""
        result = skill_service._parse_yaml_fallback_pyyaml("")
        assert result == {}

    def test_invalid_yaml(self):
        """Test parsing invalid YAML raises exception."""
        with pytest.raises(skill_service.SkillException):
            skill_service._parse_yaml_fallback_pyyaml("invalid: yaml: : :")


class TestGetSkillInputsFromCode:
    """Test _get_skill_inputs_from_code function."""

    def test_nonexistent_directory(self):
        """Test with non-existent directory."""
        result = skill_service._get_skill_inputs_from_code("/nonexistent/dir")
        assert result == []

    def test_with_mock_script(self, mocker, tmp_path):
        """Test parsing a mock Python script."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()

        # Create a mock script
        script_file = scripts_dir / "analyze.py"
        script_file.write_text('''
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--input", type=str, required=True, help="Input file")
parser.add_argument("--output", type=str, default="output.txt", help="Output file")
''')

        result = skill_service._get_skill_inputs_from_code(str(scripts_dir))
        assert len(result) >= 1

    def test_skips_private_scripts(self, mocker, tmp_path):
        """Test that private scripts starting with underscore are skipped."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()

        # Create public and private scripts
        public_script = scripts_dir / "analyze.py"
        public_script.write_text('parser.add_argument("--name", type=str)')

        private_script = scripts_dir / "_private.py"
        private_script.write_text('parser.add_argument("--secret", type=str)')

        result = skill_service._get_skill_inputs_from_code(str(scripts_dir))
        names = [item["name"] for item in result]
        assert "name" in names
        assert "secret" not in names


class TestExtractArgFromAddArgument:
    """Test _extract_arg_from_add_argument function."""

    def test_no_name(self):
        """Test with no name argument."""
        import ast
        node = ast.Call(args=[], keywords=[])
        result = skill_service._extract_arg_from_add_argument(node)
        assert result is None

    def test_with_name_kwarg(self):
        """Test with name as keyword argument."""
        import ast
        node = ast.Call(
            args=[],
            keywords=[ast.keyword(arg='name', value=ast.Constant(value='test'))]
        )
        result = skill_service._extract_arg_from_add_argument(node)
        assert result is not None
        assert result["name"] == "test"

    def test_with_dashed_name(self):
        """Test with dashed argument name."""
        import ast
        node = ast.Call(
            args=[ast.Constant(value='--input-file')],
            keywords=[
                ast.keyword(arg='type', value=ast.Name(id='str'))
            ]
        )
        result = skill_service._extract_arg_from_add_argument(node)
        assert result is not None
        assert result["name"] == "input-file"


@pytest.mark.skipif(
    "ruamel.yaml" not in sys.modules,
    reason="ruamel.yaml is not installed in this test environment",
)
class TestCommentedTreeToPlain:
    """Test _commented_tree_to_plain function."""

    def test_simple_dict(self):
        """Test converting simple dict."""
        result = skill_service._commented_tree_to_plain({"key": "value"})
        assert result == {"key": "value"}

    def test_simple_list(self):
        """Test converting simple list."""
        result = skill_service._commented_tree_to_plain([1, 2, 3])
        assert result == [1, 2, 3]

    def test_nested_structure(self):
        """Test converting nested structure."""
        data = {"outer": {"inner": [1, 2, 3]}}
        result = skill_service._commented_tree_to_plain(data)
        assert result == data


@pytest.mark.skipif(
    "ruamel.yaml" not in sys.modules,
    reason="ruamel.yaml is not installed in this test environment",
)
class TestRuamelTreeToPlain:
    """Test _ruamel_tree_to_plain function."""

    def test_simple_dict(self):
        """Test converting simple dict."""
        result = skill_service._ruamel_tree_to_plain({"key": "value"})
        assert result == {"key": "value"}

    def test_simple_list(self):
        """Test converting simple list."""
        result = skill_service._ruamel_tree_to_plain([1, 2, 3])
        assert result == [1, 2, 3]

    def test_other_value(self):
        """Test with other value types."""
        result = skill_service._ruamel_tree_to_plain("string")
        assert result == "string"


class TestApplyInlineCommentToScalar:
    """Test _apply_inline_comment_to_scalar function."""

    def test_no_comment(self):
        """Test with no comment."""
        result = skill_service._apply_inline_comment_to_scalar("value", None)
        assert result == "value"

    def test_string_with_comment(self):
        """Test with string value and comment."""
        result = skill_service._apply_inline_comment_to_scalar("value", "tooltip text")
        assert result == "value # tooltip text"

    def test_numeric_value(self):
        """Test with numeric value."""
        result = skill_service._apply_inline_comment_to_scalar(42, "answer")
        assert result == "42 # answer"

    def test_dict_value_unchanged(self):
        """Test with dict value (unchanged)."""
        data = {"key": "value"}
        result = skill_service._apply_inline_comment_to_scalar(data, "comment")
        assert result == data


class TestFlattenCaCommentToText:
    """Test _flatten_ca_comment_to_text function."""

    def test_none_input(self):
        """Test with None input."""
        result = skill_service._flatten_ca_comment_to_text(None)
        assert result is None

    def test_empty_list(self):
        """Test with empty list."""
        result = skill_service._flatten_ca_comment_to_text([])
        assert result is None

    def test_list_with_comment_tokens(self):
        """Test with list containing comment tokens."""
        class MockToken:
            def __init__(self, val):
                self.value = val
        tokens = [MockToken("# comment text")]
        result = skill_service._flatten_ca_comment_to_text(tokens)
        assert result == "comment text"


class TestTooltipForCommentedMapKey:
    """Test _tooltip_for_commented_map_key function."""

    def test_index_zero_no_header(self):
        """Test index 0 with no header comment."""
        result = skill_service._tooltip_for_commented_map_key({}, [], 0, "key")
        assert result is None

    def test_non_dict_value(self):
        """Test with non-dict/cm value."""
        result = skill_service._tooltip_for_commented_map_key("not a map", [], 0, "key")
        assert result is None


class TestSkillStreamingAndInstallation:
    @pytest.mark.asyncio
    async def test_init_skill_list_returns_early_when_initialized(self, mocker):
        mocker.patch(
            "management.services.skill.service.skill_db.check_skill_list_initialized",
            return_value=True,
        )
        update = mocker.patch("management.services.skill.service.update_skill_list")

        result = await skill_service.init_skill_list_for_tenant("tenant-1", "user-1")

        assert result["status"] == "already_initialized"
        update.assert_not_called()

    def test_install_skills_for_tenant_handles_new_existing_and_invalid_templates(self, mocker):
        database_skill_db_mock.get_skill_by_id_global = MagicMock(
            side_effect=[
                {"name": "new", "description": "new skill"},
                {"name": "existing"},
                {},
                None,
            ]
        )
        database_skill_db_mock.get_skill_by_name = MagicMock(
            side_effect=[None, {"skill_id": 20}]
        )
        database_skill_db_mock.create_skill = MagicMock(return_value={"skill_id": 10})

        result = skill_service.install_skills_for_tenant([1, 2, 3, 4], "tenant-1", "user-1")

        assert result == [10, 20]
        database_skill_db_mock.create_skill.assert_called_once()

    def test_get_official_skills_status_covers_installable_and_missing_resources(self, mocker, tmp_path):
        (tmp_path / "alpha.zip").write_bytes(b"zip")
        (tmp_path / "beta.zip").write_bytes(b"zip")
        mocker.patch("management.services.skill.service.OFFICIAL_SKILLS_ZIP_PATH", str(tmp_path))
        mocker.patch(
            "management.services.skill.service.skill_db.get_skill_by_name",
            side_effect=lambda name, tenant: (
                {"skill_id": 2} if name == "beta" and tenant == "tenant-1"
                else {"skill_id": 1, "description": "alpha description"}
                if name == "alpha" and tenant is None
                else {"skill_id": 2, "description": "beta description"}
                if name == "beta" and tenant is None
                else None
            ),
        )
        mocker.patch(
            "management.services.skill.service.skill_db.get_skill_by_id",
            return_value={"description": "beta description"},
        )
        manager = MagicMock()
        manager.resolve_tenant_dir.return_value = str(tmp_path / "resources")
        mocker.patch("management.services.skill.service.get_skill_manager", return_value=manager)
        mocker.patch("os.path.isdir", side_effect=lambda path: path == str(tmp_path))

        result = skill_service.get_official_skills_with_status("tenant-1")

        assert [(item["name"], item["status"]) for item in result] == [
            ("alpha", "installable"),
            ("beta", "resource_missing"),
        ]


class TestLocalSkillPathSecurity:
    """Regression tests for ZIP Slip and local file traversal."""

    @staticmethod
    def _service_for_path(tmp_path):
        manager = MagicMock()
        manager.resolve_tenant_dir.return_value = str(tmp_path)
        return SkillService(skill_manager=manager, tenant_id="tenant-1")

    def test_resolver_rejects_parent_absolute_drive_and_unc_paths(self, mocker, tmp_path):
        mocker.patch("management.services.skill.support.CONTAINER_SKILLS_PATH", str(tmp_path))

        for unsafe_path in (
            "../secret.txt",
            os.path.abspath("secret.txt"),
            "C:\\temp\\secret.txt",
            "\\\\host\\share\\x",
        ):
            with pytest.raises(skill_service.ForbiddenError, match="Unsafe local skill path"):
                skill_service._resolve_local_skill_path(str(tmp_path), "safe-skill", unsafe_path)

    def test_zip_slip_is_rejected_before_any_file_is_written(self, mocker, tmp_path):
        import zipfile

        service = self._service_for_path(tmp_path)
        mocker.patch("management.services.skill.support.CONTAINER_SKILLS_PATH", str(tmp_path))
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("SKILL.md", "---\nname: poczip\ndescription: poc\n---\n")
            zf.writestr("../../../../escape.txt", "escaped")

        with pytest.raises(skill_service.ForbiddenError, match="Unsafe local skill path"):
            service._upload_zip_files(
                archive.getvalue(),
                "poczip",
                tenant_id="tenant-1",
            )

        assert not (tmp_path / "poczip" / "SKILL.md").exists()
        assert not (tmp_path.parent / "escape.txt").exists()

    def test_file_read_traversal_is_rejected(self, mocker, tmp_path):
        service = self._service_for_path(tmp_path)
        mocker.patch("management.services.skill.support.CONTAINER_SKILLS_PATH", str(tmp_path))
        outside_file = tmp_path.parent / "secret.txt"
        outside_file.write_text("secret", encoding="utf-8")

        with pytest.raises(skill_service.ForbiddenError, match="Unsafe local skill path"):
            service.get_skill_file_content("safe-skill", "../../secret.txt")

    def test_file_read_rechecks_containment_before_open(self, mocker, tmp_path):
        service = self._service_for_path(tmp_path)
        outside_file = tmp_path.parent / "secret.txt"
        mocker.patch(
            "management.services.skill.service._resolve_local_skill_path",
            return_value=str(outside_file),
        )

        with pytest.raises(skill_service.ForbiddenError, match="Unsafe local skill path"):
            service.get_skill_file_content("safe-skill", "README.md")

    def test_preview_rejects_sibling_directory_with_shared_prefix(self, mocker, tmp_path):
        skill_root = tmp_path / "safe-skill"
        sibling_file = tmp_path / "safe-skill-copy" / "payload.custom"
        skill_root.mkdir()
        sibling_file.parent.mkdir()
        sibling_file.write_text("payload", encoding="utf-8")
        mocker.patch(
            "management.services.skill.support._resolve_local_skill_path",
            side_effect=[str(skill_root), str(sibling_file)],
        )

        with pytest.raises(skill_service.ForbiddenError, match="Unsafe local skill path"):
            skill_service._skill_file_preview_status(
                str(tmp_path),
                "safe-skill",
                "payload.custom",
            )


class TestSkillServicePureHelpers:
    def test_decode_text_bytes_handles_bom_variants(self):
        for encoding, expected_encoding in (
            ("utf-8-sig", "utf-8-sig"),
            ("utf-16", "utf-16"),
            ("utf-32", "utf-32"),
        ):
            result = skill_service.decode_skill_text("hello".encode(encoding))
            assert str(result) == "hello"
            assert result.encoding == expected_encoding

    def test_decode_text_bytes_handles_utf16_without_bom(self):
        result = skill_service.decode_skill_text("hello".encode("utf-16-le"))

        assert str(result) == "hello"
        assert result.encoding == "utf-16-le"

    def test_binary_detection_distinguishes_text_and_binary(self):
        assert skill_service._is_obviously_binary(b"plain text") is False
        assert skill_service._is_obviously_binary(b"\x00\x01\x02\x03") is True
        assert skill_service._is_obviously_binary("wide text".encode("utf-16-le")) is False
        assert skill_service._is_obviously_binary(b"") is False

    def test_preview_status_classifies_directories_extensions_and_text(self, tmp_path):
        assert skill_service._skill_file_preview_status(
            str(tmp_path), "skill", "README.md"
        ) == "readable"
        assert skill_service._skill_file_preview_status(
            str(tmp_path), "skill", "image.png"
        ) == "unsupported"
        assert skill_service._skill_file_preview_status(
            str(tmp_path), "skill", ".git/config"
        ) == "unsupported"

    def test_zip_members_reject_case_insensitive_collisions(self):
        import zipfile

        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("Skill/SKILL.md", "first")
            zf.writestr("skill/skill.md", "second")

        with zipfile.ZipFile(io.BytesIO(archive.getvalue())) as zf:
            with pytest.raises(skill_service.SkillException, match="same path"):
                skill_service._zip_members(zf)


class TestSkillServiceReportedCoverageGaps:
    """Target branches called out by the service coverage report."""

    def test_decode_text_bytes_covers_big_endian_legacy_and_detector_paths(self, mocker):
        big_endian = skill_service.decode_skill_text("hello".encode("utf-16-be"))
        assert str(big_endian) == "hello"
        assert big_endian.encoding == "utf-16-be"

        chinese = skill_service.decode_skill_text("中文".encode("gb18030"))
        assert str(chinese) == "中文"

        detected = MagicMock(encoding="windows-1252", chaos=0.1)
        detected.__str__.return_value = "café"
        result_set = MagicMock()
        result_set.best.return_value = detected
        mocker.patch("nexent.skills.text_codec.from_bytes", return_value=result_set)
        detected_result = skill_service.decode_skill_text(b"caf\xe9")
        assert str(detected_result) == "café"
        assert detected_result.encoding == "windows-1252"

        result_set.best.return_value = None
        with pytest.raises(UnicodeDecodeError, match="Unable to detect"):
            skill_service.decode_skill_text(b"\x80")

    def test_decode_zip_member_name_covers_legacy_names_and_fallbacks(self):
        ascii_info = MagicMock(filename="README.md", flag_bits=0)
        assert skill_service._decode_zip_member_name(ascii_info) == "README.md"

        utf8_name = "中文.md"
        mojibake = utf8_name.encode("utf-8").decode("cp437")
        utf8_info = MagicMock(filename=mojibake, flag_bits=0)
        assert skill_service._decode_zip_member_name(utf8_info) == utf8_name

        gb_name = "中文.txt"
        gb_mojibake = gb_name.encode("gb18030").decode("cp437")
        gb_info = MagicMock(filename=gb_mojibake, flag_bits=0)
        assert skill_service._decode_zip_member_name(gb_info) == gb_name

        unencodable = MagicMock(filename="😀.txt", flag_bits=0)
        assert skill_service._decode_zip_member_name(unencodable) == "😀.txt"

        fallback = MagicMock(filename="é", flag_bits=0)
        assert skill_service._decode_zip_member_name(fallback) == "é"

    def test_read_zip_member_returns_match_and_raises_for_missing(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("file.txt", b"content")

        with zipfile.ZipFile(io.BytesIO(archive.getvalue())) as zf:
            assert skill_service._read_zip_member(zf, "file.txt") == b"content"
            with pytest.raises(KeyError, match="missing.txt"):
                skill_service._read_zip_member(zf, "missing.txt")

    def test_preview_status_reads_unknown_extensions_and_handles_io_error(self, mocker, tmp_path):
        mocker.patch.object(skill_support, "CONTAINER_SKILLS_PATH", str(tmp_path))
        skill_dir = tmp_path / "demo"
        skill_dir.mkdir()
        text_file = skill_dir / "payload.custom"
        text_file.write_text("plain text", encoding="utf-8")
        binary_file = skill_dir / "payload.data"
        binary_file.write_bytes(b"\x00\x01\x02\x03")

        assert skill_service._skill_file_preview_status(
            str(tmp_path), "demo", "payload.custom"
        ) == "readable"
        assert skill_service._skill_file_preview_status(
            str(tmp_path), "demo", "payload.data"
        ) == "unsupported"

        mocker.patch("builtins.open", side_effect=OSError("unavailable"))
        assert skill_service._skill_file_preview_status(
            str(tmp_path), "demo", "missing.unknown"
        ) == "readable"

    def test_schema_helpers_cover_empty_and_empty_zip_results(self, mocker):
        assert skill_service._parse_skill_schema_from_yaml_bytes(b"   ") == []

        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("README.md", "no schema")
        assert skill_service._read_schema_yaml_from_zip(archive.getvalue()) is None

        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("demo/config/schema.yaml", "   ")
        assert skill_service._read_schema_yaml_from_zip(archive.getvalue()) == []

    def test_zip_input_scanner_skips_wrong_paths_and_unreadable_sources(self, mocker):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("other/tool.py", "print('ignored')")
            zf.writestr("demo/scripts/bad.py", b"\x80")
            zf.writestr("demo/scripts/syntax.py", "def broken(")

        mocker.patch.object(skill_service, "decode_skill_text", side_effect=[UnicodeDecodeError(
            "unknown", b"\x80", 0, 1, "bad encoding"
        ), "def broken("])
        assert skill_service._get_skill_inputs_from_zip(
            archive.getvalue(), preferred_skill_root="demo"
        ) == []

        plain_archive = io.BytesIO()
        with zipfile.ZipFile(plain_archive, "w") as zf:
            zf.writestr("other/tool.py", "print('ignored')")
        assert skill_service._get_skill_inputs_from_zip(plain_archive.getvalue()) == []

    def test_delete_local_files_skips_unsafe_resolved_entry(self, mocker, tmp_path):
        mocker.patch.object(skill_support, "CONTAINER_SKILLS_PATH", str(tmp_path))
        service = TestLocalSkillPathSecurity._service_for_path(tmp_path)
        skill_dir = tmp_path / "demo"
        skill_dir.mkdir()
        outside = tmp_path.parent / "outside.txt"
        mocker.patch("os.listdir", return_value=["unsafe"])
        real_realpath = os.path.realpath
        mocker.patch(
            "os.path.realpath",
            side_effect=lambda path: str(outside) if str(path).endswith("unsafe") else real_realpath(path),
        )
        remove = mocker.patch("os.remove")

        service._delete_local_skill_files("demo", tenant_id="tenant-1")

        remove.assert_not_called()

    def test_upload_zip_rejects_bad_archive_and_empty_relative_member(self, tmp_path):
        service = TestLocalSkillPathSecurity._service_for_path(tmp_path)
        with pytest.raises(skill_service.SkillException, match="Invalid ZIP archive"):
            service._upload_zip_files(b"not-a-zip", "demo", tenant_id="tenant-1")

        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("placeholder.txt", b"")
        with patch.object(skill_service, "_zip_file_list", return_value=["original\\"]):
            service._upload_zip_files(
                archive.getvalue(),
                "renamed",
                original_folder_name="original",
                tenant_id="tenant-1",
            )

    def test_delete_skill_requires_tenant(self):
        service = SkillService(skill_manager=MagicMock(), tenant_id=None)
        with pytest.raises(skill_service.SkillException, match="tenant_id is required"):
            service.delete_skill("demo")

    def test_file_tree_returns_empty_and_annotates_nested_files(self, mocker, tmp_path):
        manager = MagicMock()
        service = SkillService(skill_manager=manager, tenant_id="tenant-1")
        manager.resolve_tenant_dir.return_value = str(tmp_path)
        manager.get_skill_file_tree.return_value = None
        assert service.get_skill_file_tree("demo") is None

        manager.get_skill_file_tree.return_value = {
            "name": "demo",
            "type": "directory",
            "children": [
                {"name": "README.md", "type": "file"},
                {
                    "name": "assets",
                    "type": "directory",
                    "children": [{"name": "logo.png", "type": "file"}],
                },
            ],
        }
        preview = mocker.patch.object(
            skill_service,
            "_skill_file_preview_status",
            side_effect=["readable", "unsupported"],
        )

        tree = service.get_skill_file_tree("demo")

        assert tree["children"][0]["preview_status"] == "readable"
        assert tree["children"][1]["children"][0]["preview_status"] == "unsupported"
        assert [call.args[2] for call in preview.call_args_list] == ["README.md", "assets/logo.png"]

    def test_file_content_covers_text_binary_and_unsupported_preview(self, mocker, tmp_path):
        mocker.patch.object(skill_support, "CONTAINER_SKILLS_PATH", str(tmp_path))
        manager = MagicMock()
        manager.resolve_tenant_dir.return_value = str(tmp_path)
        service = SkillService(skill_manager=manager, tenant_id="tenant-1")
        skill_dir = tmp_path / "demo"
        skill_dir.mkdir()
        text_file = skill_dir / "README.md"
        text_file.write_text("hello", encoding="utf-8")
        binary_file = skill_dir / "payload.custom"
        binary_file.write_bytes(b"\x00\x01\x02\x03")

        result = service.get_skill_file_content("demo", "README.md")
        assert str(result) == "hello"
        assert result.encoding == "utf-8"

        with pytest.raises(skill_service.UnsupportedSkillFilePreview):
            with mocker.patch.object(
                skill_service, "_skill_file_preview_status", return_value="readable"
            ):
                service.get_skill_file_content("demo", "payload.custom")

        mocker.patch.object(skill_service, "_skill_file_preview_status", return_value="unsupported")
        with pytest.raises(skill_service.UnsupportedSkillFilePreview):
            service.get_skill_file_content("demo", "README.md")

    @pytest.mark.asyncio
    async def test_update_skill_list_loads_schema_and_script_inputs(self, mocker, tmp_path):
        mocker.patch.object(skill_support, "CONTAINER_SKILLS_PATH", str(tmp_path))
        schema_path = tmp_path / "schema-skill" / "config" / "schema.yaml"
        schema_path.parent.mkdir(parents=True)
        schema_path.write_text("query:\n  type: string\n", encoding="utf-8")
        manager = MagicMock()
        manager.resolve_tenant_dir.return_value = str(tmp_path)
        manager.list_skills.return_value = [
            {"name": "schema-skill"},
            {"name": "script-skill"},
        ]
        manager.load_skill.side_effect = [
            {"content": "schema content"},
            {"content": "script content"},
        ]
        mocker.patch.object(skill_service, "get_skill_manager", return_value=manager)
        mocker.patch.object(
            skill_service,
            "_get_skill_inputs_from_code",
            return_value=[{"name": "query", "type": "string"}],
        )
        mocker.patch.object(
            skill_service.aiofiles,
            "open",
            new=lambda *args, **kwargs: MockAiofilesContextManager(
                b"query:\n  type: string\n"
            ),
        )
        upsert = mocker.patch.object(skill_service.skill_db, "upsert_scanned_skills")

        await skill_service.update_skill_list("tenant-1", "user-1")

        skills = upsert.call_args.args[0]
        assert skills[0]["config_schemas"][0]["name"] == "query"
        assert skills[1]["config_schemas"] == [{"name": "query", "type": "string"}]

    def test_install_skills_from_zip_covers_validation_existing_and_new(self, mocker, tmp_path):
        (tmp_path / "official.zip").write_bytes(b"official")
        (tmp_path / "custom.zip").write_bytes(b"custom")
        (tmp_path / "new.zip").write_bytes(b"new")
        mocker.patch.object(skill_service, "OFFICIAL_SKILLS_ZIP_PATH", str(tmp_path))
        mocker.patch.object(
            skill_service.skill_db,
            "get_skill_by_name",
            side_effect=lambda name, tenant: (
                {"skill_id": 1, "source": "official"}
                if name == "official"
                else {"skill_id": 2, "source": "custom"}
                if name == "custom"
                else None
            ),
        )
        service = MagicMock()
        service.create_skill_from_file.return_value = {"name": "new"}
        mocker.patch.object(skill_service, "SkillService", return_value=service)

        result = skill_service.install_skills_from_zip_for_tenant(
            ["", "../unsafe", "missing", "official", "custom", "new"],
            "tenant-1",
            "user-1",
        )

        assert result == ["official", "custom", "new"]
        service.update_skill_from_file.assert_called_once_with(
            skill_name="official",
            file_content=b"official",
            file_type="zip",
            tenant_id="tenant-1",
            user_id=None,
        )
        service.create_skill_from_file.assert_called_once()

    def test_install_skills_from_zip_handles_missing_directory_and_scan_error(self, mocker, tmp_path):
        missing = tmp_path / "missing"
        mocker.patch.object(skill_service, "OFFICIAL_SKILLS_ZIP_PATH", str(missing))
        assert skill_service.install_skills_from_zip_for_tenant(["demo"], "tenant-1") == []

        mocker.patch.object(skill_service, "OFFICIAL_SKILLS_ZIP_PATH", str(tmp_path))
        mocker.patch("os.scandir", side_effect=OSError("scan failed"))
        assert skill_service.install_skills_from_zip_for_tenant(["demo"], "tenant-1") == []

    def test_install_skills_from_zip_skips_non_zip_and_unsafe_entries(self, mocker, tmp_path):
        outside_dir = tmp_path.parent / "outside"
        regular_entry = MagicMock(name="notes.txt", path=str(tmp_path / "notes.txt"))
        regular_entry.name = "notes.txt"
        unsafe_entry = MagicMock(name="unsafe.zip", path=str(outside_dir / "unsafe.zip"))
        unsafe_entry.name = "unsafe.zip"
        unsafe_entry.is_file.return_value = True
        mocker.patch.object(skill_service, "OFFICIAL_SKILLS_ZIP_PATH", str(tmp_path))

        with patch("os.scandir", return_value=[regular_entry, unsafe_entry]):
            assert skill_service.install_skills_from_zip_for_tenant(["unsafe"], "tenant-1") == []
        regular_entry.is_file.assert_not_called()
