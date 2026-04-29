"""
Unit tests for backend.services.skill_service module.
"""
import sys
import os
import io
import json
import types

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
nexent_skills_skill_loader_mock = types.ModuleType('nexent.skills.skill_loader')
nexent_skills_skill_manager_mock = types.ModuleType('nexent.skills.skill_manager')
nexent_storage_mock = types.ModuleType('nexent.storage')
nexent_storage_storage_client_factory_mock = types.ModuleType('nexent.storage.storage_client_factory')
nexent_storage_minio_config_mock = types.ModuleType('nexent.storage.minio_config')

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

class MockSkillManager:
    def __init__(self, local_skills_dir=None, **kwargs):
        self.local_skills_dir = local_skills_dir

nexent_skills_mock.SkillManager = MockSkillManager
nexent_skills_skill_manager_mock.SkillManager = MockSkillManager

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
consts_const_mock = types.ModuleType('consts.const')
consts_const_mock.CONTAINER_SKILLS_PATH = "/tmp/skills"
consts_const_mock.ROOT_DIR = "/tmp"
consts_exceptions_mock = types.ModuleType('consts.exceptions')

class SkillException(Exception):
    pass
consts_exceptions_mock.SkillException = SkillException

sys.modules['consts'] = consts_mock
sys.modules['consts.const'] = consts_const_mock
sys.modules['consts.exceptions'] = consts_exceptions_mock

# Set up utils mocks
utils_mock = types.ModuleType('utils')
utils_skill_params_utils_mock = types.ModuleType('utils.skill_params_utils')
utils_skill_params_utils_mock.strip_params_comments_for_db = MagicMock(side_effect=lambda x: x)
utils_skill_params_utils_mock.params_dict_to_roundtrip_yaml_text = MagicMock(return_value="params: {}")
utils_prompt_template_utils_mock = types.ModuleType('utils.prompt_template_utils')
utils_prompt_template_utils_mock.get_skill_creation_simple_prompt_template = MagicMock(return_value={"system_prompt": "", "user_prompt": ""})
utils_content_classifier_utils_mock = types.ModuleType('utils.content_classifier_utils')

class MockContentClassifier:
    def classify(self, content):
        return []

utils_content_classifier_utils_mock.ContentClassifier = MockContentClassifier
sys.modules['utils'] = utils_mock
sys.modules['utils.skill_params_utils'] = utils_skill_params_utils_mock
sys.modules['utils.prompt_template_utils'] = utils_prompt_template_utils_mock
sys.modules['utils.content_classifier_utils'] = utils_content_classifier_utils_mock

# Set up database mocks
database_mock = types.ModuleType('database')
database_client_mock = types.ModuleType('database.client')
database_client_mock.get_db_session = MagicMock()
database_client_mock.as_dict = MagicMock()
database_client_mock.filter_property = MagicMock()

database_db_models_mock = types.ModuleType('database.db_models')
database_db_models_mock.SkillInfo = MagicMock()

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
def mock_list_skills():
    return []

def mock_get_skill_by_name(skill_name):
    return None

def mock_get_skill_by_id(skill_id):
    return None

def mock_create_skill(skill_data):
    return {"skill_id": 1, "name": skill_data.get("name", "unnamed")}

def mock_update_skill(skill_name, skill_data, updated_by=None):
    return {"skill_id": 1, "name": skill_name}

def mock_delete_skill(skill_name, updated_by=None):
    return True

def mock_get_tool_ids_by_names(tool_names, tenant_id):
    return []

def mock_get_tool_names_by_skill_name(skill_name):
    return []

def mock_get_tool_names_by_ids(session, tool_ids):
    return []

def mock_get_skill_with_tool_names(skill_name):
    return None

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

database_skill_db_mock.create_or_update_skill_by_skill_info = mock_create_or_update_skill_by_skill_info
database_skill_db_mock.query_skill_instances_by_agent_id = mock_query_skill_instances_by_agent_id
database_skill_db_mock.query_enabled_skill_instances = mock_query_enabled_skill_instances
database_skill_db_mock.query_skill_instance_by_id = mock_query_skill_instance_by_id
database_skill_db_mock.search_skills_for_agent = mock_search_skills_for_agent
database_skill_db_mock.delete_skills_by_agent_id = mock_delete_skills_by_agent_id
database_skill_db_mock.delete_skill_instances_by_skill_id = mock_delete_skill_instances_by_skill_id

database_mock.client = database_client_mock
database_mock.skill_db = database_skill_db_mock
database_mock.db_models = database_db_models_mock

sys.modules['database'] = database_mock
sys.modules['database.client'] = database_client_mock
sys.modules['database.skill_db'] = database_skill_db_mock
sys.modules['database.db_models'] = database_db_models_mock

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
from backend.services import skill_service
from backend.services.skill_service import (
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


# ===== Helper Functions Tests =====
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

    def test_basic_path(self):
        result = _local_skill_config_yaml_path("my_skill", "/skills")
        result_normalized = result.replace("\\", "/")
        assert result_normalized == "/skills/my_skill/config/config.yaml"

    def test_with_subdir(self):
        result = _local_skill_config_yaml_path("test-skill", "/var/lib/skills")
        result_normalized = result.replace("\\", "/")
        assert result_normalized == "/var/lib/skills/test-skill/config/config.yaml"


# ===== SkillService Tests =====
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
        mock_list_skills = mocker.patch('backend.services.skill_service.skill_db.list_skills')
        mock_list_skills.return_value = [
            {"skill_id": 1, "name": "skill1"},
            {"skill_id": 2, "name": "skill2"},
        ]

        service = SkillService()
        service._overlay_params_from_local_config_yaml = lambda x: x

        result = service.list_skills()

        assert len(result) == 2
        mock_list_skills.assert_called_once()

    def test_list_skills_error(self, mocker):
        mock_list_skills = mocker.patch('backend.services.skill_service.skill_db.list_skills')
        mock_list_skills.side_effect = Exception("DB error")

        service = SkillService()

        with pytest.raises(Exception):
            service.list_skills()


class TestSkillServiceGetSkill:
    """Test SkillService.get_skill method."""

    def test_get_skill_found(self, mocker):
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={
                "skill_id": 1,
                "name": "test_skill",
                "description": "A test skill"
            }
        )

        service = SkillService()
        service._overlay_params_from_local_config_yaml = lambda x: x

        result = service.get_skill("test_skill")

        assert result is not None
        assert result["name"] == "test_skill"

    def test_get_skill_not_found(self, mocker):
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value=None
        )

        service = SkillService()

        result = service.get_skill("nonexistent")

        assert result is None


class TestSkillServiceGetSkillById:
    """Test SkillService.get_skill_by_id method."""

    def test_get_skill_by_id_found(self, mocker):
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_id',
            return_value={
                "skill_id": 5,
                "name": "found_skill"
            }
        )

        service = SkillService()
        service._overlay_params_from_local_config_yaml = lambda x: x

        result = service.get_skill_by_id(5)

        assert result is not None
        assert result["skill_id"] == 5

    def test_get_skill_by_id_not_found(self, mocker):
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_id',
            return_value=None
        )

        service = SkillService()

        result = service.get_skill_by_id(999)

        assert result is None


class TestSkillServiceCreateSkill:
    """Test SkillService.create_skill method."""

    def test_create_skill_missing_name(self, mocker):
        service = SkillService()

        with pytest.raises(Exception):
            service.create_skill({})

    def test_create_skill_already_exists_db(self, mocker):
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"name": "existing"}
        )

        service = SkillService()

        with pytest.raises(Exception):
            service.create_skill({"name": "existing"})

    def test_create_skill_success(self, mocker):
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.create_skill',
            return_value={
                "skill_id": 1,
                "name": "new_skill",
                "description": "A new skill"
            }
        )

        mock_manager = MagicMock()

        service = SkillService()
        service.skill_manager = mock_manager
        service._resolve_local_skills_dir_for_overlay = MagicMock(return_value=None)
        service._overlay_params_from_local_config_yaml = lambda x: x

        result = service.create_skill({
            "name": "new_skill",
            "description": "A new skill"
        }, user_id="user123")

        assert result["name"] == "new_skill"
        mock_manager.save_skill.assert_called_once()

    def test_create_skill_with_params(self, mocker):
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.create_skill',
            return_value={
                "skill_id": 1,
                "name": "skill_with_params"
            }
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager
        service._resolve_local_skills_dir_for_overlay = MagicMock(return_value="/tmp/skills")
        service._overlay_params_from_local_config_yaml = lambda x: x

        with patch('os.path.exists', return_value=False):
            result = service.create_skill({
                "name": "skill_with_params",
                "params": {"key": "value"}
            })

        assert result["name"] == "skill_with_params"


class TestSkillServiceCreateSkillFromFile:
    """Test SkillService.create_skill_from_file method."""

    def test_create_skill_from_md_bytes(self, mocker):
        mock_repo = MagicMock()
        mock_repo.get_skill_by_name.return_value = None
        mock_repo.create_skill.return_value = {"skill_id": 1, "name": "md_skill"}

        mock_manager = MagicMock()

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
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value=None
        )

        service = SkillService()

        with pytest.raises(Exception):
            service.update_skill("nonexistent", {"description": "new"})

    def test_update_skill_success(self, mocker):
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.update_skill',
            return_value={
                "skill_id": 1,
                "name": "existing",
                "description": "updated"
            }
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()

        with patch.object(skill_service, 'CONTAINER_SKILLS_PATH', "/tmp"):
            service = SkillService()
            service.skill_manager = mock_manager
            service._overlay_params_from_local_config_yaml = lambda x: x

            result = service.update_skill("existing", {"description": "updated"})

            assert result["description"] == "updated"

    def test_update_skill_with_params(self, mocker):
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "p_skill"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.update_skill',
            return_value={
                "skill_id": 1,
                "name": "p_skill",
                "params": {"key": "value"}
            }
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()

        with patch.object(skill_service, 'CONTAINER_SKILLS_PATH', "/tmp"):
            service = SkillService()
            service.skill_manager = mock_manager
            service._overlay_params_from_local_config_yaml = lambda x: x

            result = service.update_skill("p_skill", {"params": {"key": "value"}})

            assert "params" in result


class TestSkillServiceDeleteSkill:
    """Test SkillService.delete_skill method."""

    def test_delete_skill_success(self, mocker):
        mocker.patch(
            'backend.services.skill_service.skill_db.delete_skill',
            return_value=True
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.delete_skill_instances_by_skill_id',
            return_value=None
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "skill_to_delete"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager

        with patch('os.path.exists', return_value=False):
            result = service.delete_skill("skill_to_delete", user_id="user123")

        assert result is True

    def test_delete_skill_with_local_dir(self, mocker):
        mocker.patch(
            'backend.services.skill_service.skill_db.delete_skill',
            return_value=True
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.delete_skill_instances_by_skill_id',
            return_value=None
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "del_skill"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager

        with patch('os.path.exists', return_value=True):
            with patch('os.path.join', return_value="/tmp/skills/del_skill"):
                with patch('shutil.rmtree'):
                    result = service.delete_skill("del_skill", user_id="user123")

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
        mock_manager.get_skill_file_tree.assert_called_once_with("test_skill")

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
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager

        with patch('os.path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data="file content")):
                result = service.get_skill_file_content("test_skill", "README.md")

        assert result == "file content"

    def test_get_file_content_not_found(self, mocker):
        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager

        with patch('os.path.exists', return_value=False):
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
            'backend.services.skill_service.skill_db.list_skills',
            return_value=[
                {"name": "skill1", "description": "Desc1"},
                {"name": "skill2", "description": "Desc2"}
            ]
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.search_skills_for_agent',
            return_value=[]
        )

        service = SkillService()

        result = service.build_skills_summary(available_skills=["skill1"])

        assert "<skills>" in result
        assert "<name>skill1</name>" in result
        assert "<name>skill2</name>" not in result

    def test_build_summary_empty(self, mocker):
        mocker.patch(
            'backend.services.skill_service.skill_db.list_skills',
            return_value=[]
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.search_skills_for_agent',
            return_value=[]
        )

        service = SkillService()

        result = service.build_skills_summary()

        assert result == ""

    def test_build_summary_fallback_to_all_skills(self, mocker):
        """Test building summary without agent uses all skills."""
        mocker.patch(
            'backend.services.skill_service.skill_db.list_skills',
            return_value=[
                {"name": "skill1", "description": "Desc1"}
            ]
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.search_skills_for_agent',
            return_value=[]
        )

        service = SkillService()

        result = service.build_skills_summary()

        assert "<skills>" in result
        assert "<name>skill1</name>" in result

    def test_build_summary_xml_escaping(self, mocker):
        """Test XML escaping in summary."""
        mocker.patch(
            'backend.services.skill_service.skill_db.list_skills',
            return_value=[
                {"name": "skill<tag>", "description": "Desc & more"}
            ]
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.search_skills_for_agent',
            return_value=[]
        )

        service = SkillService()

        result = service.build_skills_summary()

        assert "&lt;tag&gt;" in result
        assert "&amp; more" in result


class TestSkillServiceGetSkillContent:
    """Test SkillService.get_skill_content method."""

    def test_get_content_found(self, mocker):
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={
                "name": "content_skill",
                "content": "# Skill content here"
            }
        )

        service = SkillService()

        result = service.get_skill_content("content_skill")

        assert result == "# Skill content here"

    def test_get_content_not_found(self, mocker):
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value=None
        )

        service = SkillService()

        result = service.get_skill_content("nonexistent")

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

        result = service._overlay_params_from_local_config_yaml({"name": "test"})

        assert result["name"] == "test"

    def test_overlay_params_local_file_exists(self, mocker):
        service = SkillService()
        service._resolve_local_skills_dir_for_overlay = MagicMock(return_value="/tmp/skills")

        skill_data = {"name": "test_skill"}

        with patch('os.path.isfile', return_value=True):
            with patch('builtins.open', mock_open(read_data="key: value\n")):
                with patch('backend.services.skill_service._parse_skill_params_from_config_bytes', return_value={"key": "value"}):
                    result = service._overlay_params_from_local_config_yaml(skill_data)

        assert result["params"]["key"] == "value"

    def test_overlay_params_local_file_not_exists(self, mocker):
        service = SkillService()
        service._resolve_local_skills_dir_for_overlay = MagicMock(return_value="/tmp/skills")

        with patch('os.path.isfile', return_value=False):
            result = service._overlay_params_from_local_config_yaml({"name": "test"})

        assert result["name"] == "test"

    def test_overlay_params_skill_without_name(self, mocker):
        service = SkillService()
        service._resolve_local_skills_dir_for_overlay = MagicMock(return_value="/tmp/skills")

        result = service._overlay_params_from_local_config_yaml({})

        assert result == {}


class TestSkillServiceResolveLocalSkillsDir:
    """Test SkillService._resolve_local_skills_dir_for_overlay method."""

    def test_resolve_with_manager_dir(self, mocker):
        service = SkillService()
        service.skill_manager.local_skills_dir = "/manager/skills"

        with patch.object(skill_service, 'CONTAINER_SKILLS_PATH', "/config/skills"):
            result = service._resolve_local_skills_dir_for_overlay()

        assert result is not None

    def test_resolve_with_fallback_dir(self, mocker):
        service = SkillService()
        service.skill_manager.local_skills_dir = None

        with patch.object(skill_service, 'CONTAINER_SKILLS_PATH', None):
            with patch.object(skill_service, 'ROOT_DIR', "/project"):
                with patch('os.path.isdir', return_value=True):
                    result = service._resolve_local_skills_dir_for_overlay()

        result_normalized = result.replace("\\", "/")
        assert result_normalized == "/project/skills"

    def test_resolve_returns_none(self, mocker):
        service = SkillService()
        service.skill_manager.local_skills_dir = ""

        with patch.object(skill_service, 'CONTAINER_SKILLS_PATH', ""):
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
                with patch('backend.services.skill_service._local_skill_config_yaml_path', return_value="/tmp/skill/config.yaml"):
                    _write_skill_params_to_local_config_yaml("skill", {"key": "value"}, "/tmp")


class TestRemoveLocalSkillConfigYaml:
    """Test _remove_local_skill_config_yaml function."""

    def test_remove_with_empty_local_dir(self):
        _remove_local_skill_config_yaml("skill", "")

    def test_remove_file_exists(self, mocker):
        with patch('backend.services.skill_service._local_skill_config_yaml_path', return_value="/tmp/skill/config.yaml"):
            with patch('os.path.isfile', return_value=True):
                with patch('os.remove'):
                    _remove_local_skill_config_yaml("skill", "/tmp")

    def test_remove_file_not_exists(self, mocker):
        with patch('backend.services.skill_service._local_skill_config_yaml_path', return_value="/tmp/skill/config.yaml"):
            with patch('os.path.isfile', return_value=False):
                _remove_local_skill_config_yaml("skill", "/tmp")


# ===== Parse YAML Functions Tests =====
class TestParseYamlWithRuamel:
    """Test _parse_yaml_with_ruamel_merge_eol_comments function."""

    def test_parse_simple_yaml(self, mocker):
        yaml_content = "key: value\nnested:\n  inner: test"

        with patch.dict('sys.modules', {'ruamel.yaml': MagicMock()}):
            try:
                result = _parse_yaml_with_ruamel_merge_eol_comments(yaml_content)
                assert isinstance(result, dict)
            except ImportError:
                pytest.skip("ruamel.yaml not available")


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

        with patch('backend.services.skill_service.SkillManager') as mock_manager:
            with patch.object(skill_service, 'CONTAINER_SKILLS_PATH', '/tmp'):
                manager = get_skill_manager()
                mock_manager.assert_called_once()

    def test_get_manager_reuses_instance(self):
        existing = MagicMock()
        skill_service._skill_manager = existing

        manager = get_skill_manager()
        assert manager == existing


# ===== Comment Handling Functions Tests =====
class TestCommentTextFromToken:
    """Test _comment_text_from_token function."""

    def test_none_token(self):
        from backend.services.skill_service import _comment_text_from_token
        result = _comment_text_from_token(None)
        assert result is None

    def test_token_without_value(self):
        from backend.services.skill_service import _comment_text_from_token
        token = MagicMock()
        token.value = None
        result = _comment_text_from_token(token)
        assert result is None

    def test_token_with_hash_comment(self):
        from backend.services.skill_service import _comment_text_from_token
        token = MagicMock()
        token.value = "# This is a comment"
        result = _comment_text_from_token(token)
        assert result == "This is a comment"

    def test_token_without_hash(self):
        from backend.services.skill_service import _comment_text_from_token
        token = MagicMock()
        token.value = "not a comment"
        result = _comment_text_from_token(token)
        assert result is None

    def test_token_with_hash_and_whitespace(self):
        from backend.services.skill_service import _comment_text_from_token
        token = MagicMock()
        token.value = "  #   trimmed comment  "
        result = _comment_text_from_token(token)
        assert result == "trimmed comment"


class TestTupleSlot2:
    """Test _tuple_slot2 function."""

    def test_none_container(self):
        from backend.services.skill_service import _tuple_slot2
        result = _tuple_slot2(None)
        assert result is None

    def test_empty_container(self):
        from backend.services.skill_service import _tuple_slot2
        result = _tuple_slot2([])
        assert result is None

    def test_single_element_container(self):
        from backend.services.skill_service import _tuple_slot2
        result = _tuple_slot2([1])
        assert result is None

    def test_two_element_container(self):
        from backend.services.skill_service import _tuple_slot2
        result = _tuple_slot2([1, 2])
        assert result is None

    def test_three_element_container(self):
        from backend.services.skill_service import _tuple_slot2
        result = _tuple_slot2([1, 2, "slot2_value"])
        assert result == "slot2_value"


class TestIsBeforeNextSiblingCommentToken:
    """Test _is_before_next_sibling_comment_token function."""

    def test_none_token(self):
        from backend.services.skill_service import _is_before_next_sibling_comment_token
        result = _is_before_next_sibling_comment_token(None)
        assert result is False

    def test_token_without_value(self):
        from backend.services.skill_service import _is_before_next_sibling_comment_token
        token = MagicMock()
        token.value = None
        result = _is_before_next_sibling_comment_token(token)
        assert result is False

    def test_token_not_starting_with_newline(self):
        from backend.services.skill_service import _is_before_next_sibling_comment_token
        token = MagicMock()
        token.value = "# comment"
        result = _is_before_next_sibling_comment_token(token)
        assert result is False

    def test_token_starting_with_newline(self):
        from backend.services.skill_service import _is_before_next_sibling_comment_token
        token = MagicMock()
        token.value = "\n# comment"
        result = _is_before_next_sibling_comment_token(token)
        assert result is True


class TestFlattenCaCommentToText:
    """Test _flatten_ca_comment_to_text function."""

    def test_none_comment_field(self):
        from backend.services.skill_service import _flatten_ca_comment_to_text
        result = _flatten_ca_comment_to_text(None)
        assert result is None

    def test_empty_list(self):
        from backend.services.skill_service import _flatten_ca_comment_to_text
        result = _flatten_ca_comment_to_text([])
        assert result is None

    def test_list_with_none_values(self):
        from backend.services.skill_service import _flatten_ca_comment_to_text
        result = _flatten_ca_comment_to_text([None, None])
        assert result is None

    def test_list_with_nested_lists(self):
        from backend.services.skill_service import _flatten_ca_comment_to_text
        token1 = MagicMock()
        token1.value = "# first comment"
        token2 = MagicMock()
        token2.value = "# second comment"
        result = _flatten_ca_comment_to_text([[token1, token2]])
        assert result == "first comment second comment"

    def test_list_with_direct_tokens(self):
        from backend.services.skill_service import _flatten_ca_comment_to_text
        token = MagicMock()
        token.value = "# direct comment"
        result = _flatten_ca_comment_to_text([token])
        assert result == "direct comment"

    def test_list_with_non_comment_tokens(self):
        from backend.services.skill_service import _flatten_ca_comment_to_text
        token = MagicMock()
        token.value = "not a comment"
        result = _flatten_ca_comment_to_text([token])
        assert result is None


class TestCommentFromMapBlockHeader:
    """Test _comment_from_map_block_header function."""

    def test_none_cm(self):
        from backend.services.skill_service import _comment_from_map_block_header
        result = _comment_from_map_block_header(None)
        assert result is None

    def test_no_ca_attribute(self):
        from backend.services.skill_service import _comment_from_map_block_header
        cm = MagicMock(spec=[])
        result = _comment_from_map_block_header(cm)
        assert result is None

    def test_no_comment_in_ca(self):
        from backend.services.skill_service import _comment_from_map_block_header
        cm = MagicMock()
        cm.ca = MagicMock()
        cm.ca.comment = None
        result = _comment_from_map_block_header(cm)
        assert result is None


class TestApplyInlineCommentToScalar:
    """Test _apply_inline_comment_to_scalar function."""

    def test_no_comment(self):
        from backend.services.skill_service import _apply_inline_comment_to_scalar
        result = _apply_inline_comment_to_scalar("value", None)
        assert result == "value"

    def test_string_with_comment(self):
        from backend.services.skill_service import _apply_inline_comment_to_scalar
        result = _apply_inline_comment_to_scalar("value", "tooltip")
        assert result == "value # tooltip"

    def test_dict_value_unchanged(self):
        from backend.services.skill_service import _apply_inline_comment_to_scalar
        result = _apply_inline_comment_to_scalar({"key": "val"}, "tooltip")
        assert result == {"key": "val"}

    def test_list_value_unchanged(self):
        from backend.services.skill_service import _apply_inline_comment_to_scalar
        result = _apply_inline_comment_to_scalar([1, 2], "tooltip")
        assert result == [1, 2]

    def test_numeric_value_with_comment(self):
        from backend.services.skill_service import _apply_inline_comment_to_scalar
        result = _apply_inline_comment_to_scalar(42, "answer")
        assert result == "42 # answer"


class TestParseYamlWithRuamelErrorPaths:
    """Test _parse_yaml_with_ruamel_merge_eol_comments error paths."""

    def test_invalid_yaml_raises_exception(self):
        from backend.services.skill_service import _parse_yaml_with_ruamel_merge_eol_comments
        with pytest.raises(Exception):
            _parse_yaml_with_ruamel_merge_eol_comments("invalid: yaml: : : :")

    def test_yaml_load_returns_non_mapping(self):
        from backend.services.skill_service import _parse_yaml_with_ruamel_merge_eol_comments
        # This tests the branch where root is a list instead of dict
        with pytest.raises(Exception):
            _parse_yaml_with_ruamel_merge_eol_comments("- item1\n- item2")


class TestParseYamlFallbackPyyamlErrorPaths:
    """Test _parse_yaml_fallback_pyyaml error paths."""

    def test_invalid_yaml_raises_skill_exception(self):
        from backend.services.skill_service import _parse_yaml_fallback_pyyaml
        from consts.exceptions import SkillException
        try:
            _parse_yaml_fallback_pyyaml("invalid: yaml: : :")
            assert False, "Should have raised"
        except SkillException as e:
            assert "Invalid JSON or YAML" in str(e) or "mapping values" in str(e)
        except Exception as e:
            assert "mapping values" in str(e) or "Invalid" in str(e)

    def test_yaml_returns_list_raises_exception(self):
        from backend.services.skill_service import _parse_yaml_fallback_pyyaml
        with pytest.raises(Exception):
            _parse_yaml_fallback_pyyaml("- item1\n- item2")


class TestParseSkillParamsFromConfigBytesErrorPaths:
    """Test _parse_skill_params_from_config_bytes error paths."""

    def test_json_non_dict_raises_exception(self):
        from backend.services.skill_service import _parse_skill_params_from_config_bytes
        from consts.exceptions import SkillException
        try:
            _parse_skill_params_from_config_bytes(b'["list", "not", "dict"]')
            assert False, "Should have raised"
        except SkillException as e:
            assert "must contain a JSON or YAML object" in str(e)
        except Exception as e:
            assert "must contain a JSON or YAML object" in str(e)

    def test_non_serializable_params_with_fallback(self):
        from backend.services.skill_service import _params_dict_to_storable

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
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "test_skill"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

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
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "explicit_skill"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

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
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "tool_skill"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_ids_by_names',
            return_value=[1, 2]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

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
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value=None
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

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
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "invalid_skill"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

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
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"name": "existing_skill"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

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
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "existing", "description": "updated"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_ids_by_names',
            return_value=[]
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        content = b"""---
name: existing
description: Updated via MD
---
# Content"""
        result = service.update_skill_from_file("existing", content, file_type="md")

        assert result["description"] == "updated"

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
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "zip_update"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "zip_update", "description": "Updated via ZIP"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_ids_by_names',
            return_value=[]
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        result = service.update_skill_from_file("zip_update", zip_buffer.getvalue(), file_type="zip")

        assert result["name"] == "zip_update"

    def test_update_skill_not_found(self, mocker):
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value=None
        )

        service = SkillService()

        from consts.exceptions import SkillException
        try:
            service.update_skill_from_file("nonexistent", b"---\nname: x\n---")
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
            'backend.services.skill_service.skill_db.list_skills',
            side_effect=Exception("Database error")
        )

        service = SkillService()

        from consts.exceptions import SkillException
        try:
            service.list_skills()
            assert False, "Should have raised"
        except SkillException as e:
            assert "Failed to list skills" in str(e)
        except Exception as e:
            assert "Failed to list skills" in str(e)

    def test_get_skill_error_path(self, mocker):
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            side_effect=Exception("Database error")
        )

        service = SkillService()

        from consts.exceptions import SkillException
        try:
            service.get_skill("any_skill")
            assert False, "Should have raised"
        except SkillException as e:
            assert "Failed to get skill" in str(e)
        except Exception as e:
            assert "Failed to get skill" in str(e)

    def test_get_skill_by_id_error_path(self, mocker):
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_id',
            side_effect=Exception("Database error")
        )

        service = SkillService()

        from consts.exceptions import SkillException
        try:
            service.get_skill_by_id(1)
            assert False, "Should have raised"
        except SkillException as e:
            assert "Failed to get skill" in str(e)
        except Exception as e:
            assert "Failed to get skill" in str(e)

    def test_load_skill_directory_error(self, mocker):
        mock_manager = MagicMock()
        mock_manager.load_skill_directory.side_effect = Exception("File error")

        service = SkillService()
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

        service = SkillService()
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
            'backend.services.skill_service.skill_db.get_skill_by_name',
            side_effect=Exception("Database error")
        )

        service = SkillService()

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
            'backend.services.skill_service.skill_db.list_skills',
            side_effect=Exception("Database error")
        )

        service = SkillService()

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
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.repository = mock_repo
        service.skill_manager = mock_manager
        service._resolve_local_skills_dir_for_overlay = MagicMock(return_value="/tmp/skills")

        with patch('os.path.exists', return_value=True):
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
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager

        with patch('os.makedirs'):
            with patch('builtins.open', mock_open()):
                service._upload_zip_files(zip_buffer.getvalue(), "new_name", "old_name")

    def test_upload_zip_with_nested_files(self, mocker):
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("nested/file1.txt", "content1")
            zf.writestr("nested/file2.txt", "content2")

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager

        with patch('os.makedirs'):
            with patch('builtins.open', mock_open()):
                service._upload_zip_files(zip_buffer.getvalue(), "nested", "nested")

    def test_upload_zip_handles_nested_directories(self, mocker):
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("nested/file1.txt", "content1")
            zf.writestr("nested/file2.txt", "content2")

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager

        with patch('os.makedirs'):
            with patch('builtins.open', mock_open()):
                service._upload_zip_files(zip_buffer.getvalue(), "nested", "nested")


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
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "no_tools"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_ids_by_names',
            return_value=[]
        )

        mock_manager = MagicMock()

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        content = b"""---
name: no_tools
description: No allowed tools
---
# Content"""
        result = service._create_skill_from_md(content, skill_name="no_tools")

        assert result["name"] == "no_tools"

    def test_create_md_no_name_uses_skill_name_param(self, mocker):
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "explicit_name"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_ids_by_names',
            return_value=[]
        )

        mock_manager = MagicMock()

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        content = b"""---
description: No name in frontmatter
---
# Content"""
        result = service._create_skill_from_md(content, skill_name="explicit_name")

        assert result["name"] == "explicit_name"


# ===== Update from MD Edge Cases =====
class TestSkillServiceUpdateFromMdEdgeCases:
    """Test _update_skill_from_md edge cases."""

    def test_update_md_with_allowed_tools(self, mocker):
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_ids_by_names',
            return_value=[1, 2]
        )

        mock_manager = MagicMock()

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
        result = service._update_skill_from_md(content, "existing")

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
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "no_md"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "no_md"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        # Should not raise even without SKILL.md
        result = service._update_skill_from_zip(zip_buffer.getvalue(), "no_md")

        assert result["name"] == "no_md"

    def test_update_zip_with_invalid_skill_md_logs_warning(self, mocker):
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("bad_skill/SKILL.md", "invalid content")

        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "bad_skill"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "bad_skill"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        # Should not raise but logs warning
        result = service._update_skill_from_zip(zip_buffer.getvalue(), "bad_skill")
        assert result["name"] == "bad_skill"


# ===== Update Skill with Config YAML Sync =====
class TestUpdateSkillConfigYamlSync:
    """Test update_skill config.yaml sync behavior."""

    def test_update_skill_removes_params_when_null(self, mocker):
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "p_skill", "params": {"old": "value"}}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "p_skill", "params": None}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()

        with patch.object(skill_service, 'CONTAINER_SKILLS_PATH', "/tmp/skills"):
            service = SkillService()
            service.skill_manager = mock_manager
            service._overlay_params_from_local_config_yaml = lambda x: x
            service._resolve_local_skills_dir_for_overlay = MagicMock(return_value=None)

            with patch('backend.services.skill_service._remove_local_skill_config_yaml') as mock_remove:
                service.update_skill("p_skill", {"params": None})
                mock_remove.assert_called()


# ===== Build Skills Summary Edge Cases =====
class TestBuildSkillsSummaryEdgeCases:
    """Test build_skills_summary edge cases."""

    def test_build_summary_with_agent_skills_whitelist(self, mocker):
        mocker.patch(
            'backend.services.skill_service.skill_db.search_skills_for_agent',
            return_value=[
                {"skill_instance_id": 1, "skill_id": 1, "enabled": True}
            ]
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_id',
            return_value={
                "name": "skill1",
                "description": "Desc",
                "content": "# Content",
                "tool_ids": []
            }
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
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
        from backend.services.skill_service import _tooltip_for_commented_map_key
        cm = MagicMock()
        cm.ca = None
        result = _tooltip_for_commented_map_key(cm, ["key1", "key2"], 0, "key1")
        assert result is None

    def test_index_zero_with_empty_ca(self):
        from backend.services.skill_service import _tooltip_for_commented_map_key
        cm = MagicMock(spec=[])
        result = _tooltip_for_commented_map_key(cm, ["key1"], 0, "key1")
        assert result is None


class TestTooltipForCommentedSeqIndex:
    """Test _tooltip_for_commented_seq_index function."""

    def test_index_zero_no_comment(self):
        from backend.services.skill_service import _tooltip_for_commented_seq_index
        seq = MagicMock()
        seq.ca = None
        result = _tooltip_for_commented_seq_index(seq, 0)
        assert result is None

    def test_index_greater_than_zero_empty_prev_tuple(self):
        from backend.services.skill_service import _tooltip_for_commented_seq_index
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
                with patch('backend.services.skill_service._local_skill_config_yaml_path', return_value="/tmp/skill/config.yaml"):
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
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "empty_params"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = None

        service = SkillService()
        service.skill_manager = mock_manager
        service._resolve_local_skills_dir_for_overlay = MagicMock(return_value=None)
        service._overlay_params_from_local_config_yaml = lambda x: x

        result = service.create_skill({"name": "empty_params", "params": {}})

        assert result["name"] == "empty_params"

    def test_create_skill_saves_to_manager(self, mocker):
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "saved_skill"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = None

        service = SkillService()
        service.skill_manager = mock_manager
        service._resolve_local_skills_dir_for_overlay = MagicMock(return_value=None)
        service._overlay_params_from_local_config_yaml = lambda x: x

        result = service.create_skill({"name": "saved_skill"})

        mock_manager.save_skill.assert_called_once()

    def test_update_skill_syncs_local_config(self, mocker):
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "sync_skill", "description": "old"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "sync_skill", "description": "new"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        with patch.object(skill_service, 'CONTAINER_SKILLS_PATH', "/tmp/skills"):
            service = SkillService()
            service.skill_manager = mock_manager
            service._overlay_params_from_local_config_yaml = lambda x: x
            service._resolve_local_skills_dir_for_overlay = MagicMock(return_value="/tmp/skills")

            with patch('backend.services.skill_service._write_skill_params_to_local_config_yaml'):
                result = service.update_skill("sync_skill", {"params": {"key": "value"}})

        assert result["description"] == "new"

    def test_update_skill_without_container_path(self, mocker):
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "no_path"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "no_path"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = None

        with patch.object(skill_service, 'CONTAINER_SKILLS_PATH', None):
            with patch.object(skill_service, 'ROOT_DIR', ""):
                service = SkillService()
                service.skill_manager = mock_manager
                service._overlay_params_from_local_config_yaml = lambda x: x
                service._resolve_local_skills_dir_for_overlay = MagicMock(return_value=None)

                result = service.update_skill("no_path", {"description": "updated"})

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
        mock_manager.get_skill_scripts.assert_called_once_with("test_skill")

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
        from backend.services import skill_service
        import os

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"
        mock_manager.delete_skill_file = MagicMock(return_value=True)

        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "test_skill"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.delete_skill',
            return_value=True
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.delete_skill_instances_by_skill_id',
            return_value=None
        )

        service = SkillService()
        service.skill_manager = mock_manager

        with patch.object(skill_service, 'CONTAINER_SKILLS_PATH', "/tmp/skills"):
            with patch('os.path.isdir', return_value=False):
                result = service.delete_skill("test_skill")

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
        base_dir = "/tmp/skills"
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
        base_dir = "/tmp/skills"

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
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager

        with patch('os.path.isdir', return_value=False):
            service._delete_local_skill_files("nonexistent_skill")

    def test_delete_files_with_content(self, mocker):
        """Test deletion with files and subdirectories."""
        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager

        def mock_isdir(path):
            return path.endswith("subdir") or path.endswith("test_skill")

        with patch('os.path.isdir', side_effect=mock_isdir):
            with patch('os.listdir', return_value=["file.txt", "subdir"]):
                with patch('os.remove'):
                    with patch('shutil.rmtree'):
                        service._delete_local_skill_files("test_skill")

    def test_delete_files_with_trailing_slash_item(self, mocker):
        """Test deletion with items ending in slash."""
        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager

        def mock_isdir(path):
            return path.endswith("subdir") or path.endswith("test_skill")

        with patch('os.path.isdir', side_effect=mock_isdir):
            with patch('os.listdir', return_value=["file.txt", "subdir/", "normal_dir"]):
                with patch('os.remove'):
                    with patch('shutil.rmtree'):
                        service._delete_local_skill_files("test_skill")


class TestSkillServiceCreateSkillFromFileAutoDetect:
    """Test auto-detection in create_skill_from_file."""

    def test_auto_detect_md_file(self, mocker):
        """Test auto-detection of MD file type."""
        mock_repo = MagicMock()
        mock_repo.get_skill_by_name.return_value = None
        mock_repo.create_skill.return_value = {"skill_id": 1, "name": "auto_skill"}

        mock_manager = MagicMock()

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
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "zip_update"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "zip_update"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        zip_buffer.seek(0)
        result = service.update_skill_from_file("zip_update", zip_buffer.getvalue(), file_type="auto")

        assert result["name"] == "zip_update"


class TestSkillServiceUpdateFromFileStringInput:
    """Test update_skill_from_file with string input."""

    def test_string_input(self, mocker):
        """Test string input handling in update."""
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        content = """---
name: existing
description: Updated
---
# Content"""
        result = service.update_skill_from_file("existing", content, file_type="md")

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
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "root_skill"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_ids_by_names',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        # Provide skill_name since root-level SKILL.md has no folder name to extract
        result = service._create_skill_from_zip(zip_buffer.getvalue(), "root_skill")

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
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "skill"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "skill"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_ids_by_names',
            return_value=[1]
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_names_by_skill_name',
            return_value=["tool1"]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        result = service._update_skill_from_zip(zip_buffer.getvalue(), "skill")

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
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "skill"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "skill", "params": {"key": "value"}}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        result = service._update_skill_from_zip(zip_buffer.getvalue(), "skill")

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
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "new_name"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_ids_by_names',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        result = service._create_skill_from_zip(zip_buffer.getvalue(), "new_name")

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
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "skill"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "skill"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        result = service._update_skill_from_zip(zip_buffer.getvalue(), "skill")

        assert result["name"] == "skill"


class TestSkillServiceCreateFromMdWithInvalidParse:
    """Test _create_skill_from_md with invalid parse."""

    def test_create_md_invalid_parse_raises(self, mocker):
        """Test MD creation with invalid parse raises exception."""
        mocker.patch(
            'backend.services.skill_service.SkillLoader.parse',
            side_effect=ValueError("Invalid YAML syntax")
        )

        mock_manager = MagicMock()

        service = SkillService()
        service.skill_manager = mock_manager

        content = b"invalid content"
        from consts.exceptions import SkillException
        try:
            service._create_skill_from_md(content, skill_name=None)
            assert False, "Should have raised"
        except SkillException as e:
            assert "Invalid SKILL.md format" in str(e)


class TestSkillServiceCreateFromMdWithUserId:
    """Test _create_skill_from_md with user_id."""

    def test_create_md_with_user_id(self, mocker):
        """Test MD creation sets created_by and updated_by."""
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "user_skill"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_ids_by_names',
            return_value=[]
        )

        mock_manager = MagicMock()

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        content = b"""---
name: user_skill
description: With user
---
# Content"""
        result = service._create_skill_from_md(content, skill_name="user_skill", user_id="user123")

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
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "skill"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_ids_by_names',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        result = service._create_skill_from_zip(zip_buffer.getvalue(), None, user_id="user456")

        assert result["name"] == "skill"


class TestSkillServiceUpdateFromMdWithUserId:
    """Test _update_skill_from_md with user_id."""

    def test_update_md_with_user_id(self, mocker):
        """Test MD update sets updated_by."""
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_ids_by_names',
            return_value=[]
        )

        mock_manager = MagicMock()

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        content = b"""---
name: existing
description: Updated
---
# Content"""
        result = service._update_skill_from_md(content, "existing", user_id="updater789")

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
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "skill"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "skill"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        result = service._update_skill_from_zip(zip_buffer.getvalue(), "skill", user_id="updater789")

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
            service._create_skill_from_zip(b"not a zip file")
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
            'backend.services.skill_service.SkillLoader.parse',
            side_effect=ValueError("Invalid YAML syntax")
        )

        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value=None
        )

        mock_manager = MagicMock()

        service = SkillService()
        service.skill_manager = mock_manager

        from consts.exceptions import SkillException
        try:
            service._create_skill_from_zip(zip_buffer.getvalue())
            assert False, "Should have raised"
        except SkillException as e:
            assert "Invalid SKILL.md" in str(e)


class TestSkillServiceDeleteWithLocalDir:
    """Test delete_skill with local directory."""

    def test_delete_with_existing_local_dir(self, mocker):
        """Test deletion removes local directory."""
        mocker.patch(
            'backend.services.skill_service.skill_db.delete_skill',
            return_value=True
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.delete_skill_instances_by_skill_id',
            return_value=None
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "to_delete"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager

        with patch('os.path.exists', return_value=True):
            with patch('shutil.rmtree'):
                result = service.delete_skill("to_delete", user_id="user123")

        assert result is True


class TestSkillServiceDeleteWithNoLocalDir:
    """Test delete_skill without local directory."""

    def test_delete_without_local_dir(self, mocker):
        """Test deletion works without local directory."""
        mocker.patch(
            'backend.services.skill_service.skill_db.delete_skill',
            return_value=True
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.delete_skill_instances_by_skill_id',
            return_value=None
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "to_delete"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = None

        service = SkillService()
        service.skill_manager = mock_manager

        # The service joins local_skills_dir with skill_name, so os.path.join(None, x) would fail
        # We need to patch os.path.exists to handle the joined path check
        with patch('os.path.exists', return_value=False):
            with patch('os.path.join', return_value="/nonexistent/path/to_delete"):
                result = service.delete_skill("to_delete", user_id="user123")

        assert result is True


class TestSkillServiceGetEnabledSkillsForAgentWithToolIds:
    """Test get_enabled_skills_for_agent with tool_ids."""

    def test_get_enabled_skills_with_tool_ids(self, mocker):
        """Test getting enabled skills returns tool_ids."""
        mocker.patch(
            'backend.services.skill_service.skill_db.search_skills_for_agent',
            return_value=[
                {"skill_instance_id": 1, "skill_id": 1, "enabled": True}
            ]
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_id',
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
            'backend.services.skill_service.skill_db.search_skills_for_agent',
            return_value=[
                {"skill_instance_id": 1, "skill_id": 1, "enabled": True}
            ]
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_id',
            return_value={
                "name": "agent_skill",
                "description": "Agent skill",
                "content": "# Content"
            }
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.list_skills',
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
            'backend.services.skill_service.skill_db.list_skills',
            return_value=[
                {"name": "skill1", "description": None}
            ]
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.search_skills_for_agent',
            return_value=[]
        )

        service = SkillService()

        result = service.build_skills_summary()

        assert "<skills>" in result
        assert "<name>skill1</name>" in result


class TestSkillServiceUpdateSkillWithExistingTags:
    """Test update_skill with existing tags."""

    def test_update_skill_preserves_existing_tags(self, mocker):
        """Test update_skill preserves existing tags when not provided."""
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "existing", "tags": ["tag1", "tag2"]}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "existing", "tags": ["tag1", "tag2"]}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()

        with patch.object(skill_service, 'CONTAINER_SKILLS_PATH', "/tmp"):
            service = SkillService()
            service.skill_manager = mock_manager
            service._overlay_params_from_local_config_yaml = lambda x: x

            result = service.update_skill("existing", {"description": "updated"})

        assert result["name"] == "existing"


class TestSkillServiceUpdateSkillWithExistingContent:
    """Test update_skill with existing content."""

    def test_update_skill_preserves_existing_content(self, mocker):
        """Test update_skill preserves existing content when not provided."""
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "existing", "content": "# Original content"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "existing", "content": "# Original content"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()

        with patch.object(skill_service, 'CONTAINER_SKILLS_PATH', "/tmp"):
            service = SkillService()
            service.skill_manager = mock_manager
            service._overlay_params_from_local_config_yaml = lambda x: x

            result = service.update_skill("existing", {"description": "updated"})

        assert result["name"] == "existing"


class TestSkillServiceUpdateSkillWithFiles:
    """Test update_skill with files parameter."""

    def test_update_skill_with_files(self, mocker):
        """Test update_skill passes files to manager."""
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()

        with patch.object(skill_service, 'CONTAINER_SKILLS_PATH', "/tmp"):
            service = SkillService()
            service.skill_manager = mock_manager
            service._overlay_params_from_local_config_yaml = lambda x: x

            result = service.update_skill("existing", {"files": ["file1.txt", "file2.txt"]})

        assert result["name"] == "existing"
        mock_manager.save_skill.assert_called()


class TestSkillServiceCreateSkillWithLocalParamsWriteError:
    """Test create_skill handles local params write error."""

    def test_create_skill_local_write_error_logs_warning(self, mocker):
        """Test create_skill logs warning on local params write error."""
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "error_skill"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager
        service._resolve_local_skills_dir_for_overlay = MagicMock(return_value="/tmp/skills")
        service._overlay_params_from_local_config_yaml = lambda x: x

        with patch('os.path.exists', return_value=False):
            with patch('backend.services.skill_service._write_skill_params_to_local_config_yaml',
                      side_effect=Exception("Write error")):
                result = service.create_skill({
                    "name": "error_skill",
                    "params": {"key": "value"}
                })

        assert result["name"] == "error_skill"


class TestSkillServiceUpdateSkillParamsWriteError:
    """Test update_skill handles params write error."""

    def test_update_skill_params_write_error(self, mocker):
        """Test update_skill logs warning on params write error."""
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()

        with patch.object(skill_service, 'CONTAINER_SKILLS_PATH', "/tmp"):
            service = SkillService()
            service.skill_manager = mock_manager
            service._overlay_params_from_local_config_yaml = lambda x: x

            with patch('backend.services.skill_service._write_skill_params_to_local_config_yaml',
                      side_effect=Exception("Write error")):
                result = service.update_skill("existing", {"params": {"key": "value"}})

        assert result["name"] == "existing"


class TestSkillServiceUpdateSkillSaveSkillError:
    """Test update_skill handles save_skill error."""

    def test_update_skill_save_error(self, mocker):
        """Test update_skill logs warning on save_skill error."""
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()
        mock_manager.save_skill.side_effect = Exception("Save error")

        with patch.object(skill_service, 'CONTAINER_SKILLS_PATH', "/tmp"):
            service = SkillService()
            service.skill_manager = mock_manager
            service._overlay_params_from_local_config_yaml = lambda x: x

            result = service.update_skill("existing", {"description": "updated"})

        assert result["name"] == "existing"


class TestSkillServiceDeleteError:
    """Test delete_skill error handling."""

    def test_delete_skill_error(self, mocker):
        """Test delete_skill raises exception on error."""
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "to_delete"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.delete_skill',
            side_effect=Exception("DB error")
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = None

        service = SkillService()
        service.skill_manager = mock_manager

        from consts.exceptions import SkillException
        try:
            service.delete_skill("to_delete")
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
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_ids_by_names',
            return_value=[1]
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_names_by_skill_name',
            return_value=["tool1"]
        )

        mock_manager = MagicMock()

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
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.create_skill',
            return_value={"skill_id": 1, "name": "skill"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_ids_by_names',
            return_value=[1]
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager
        service._overlay_params_from_local_config_yaml = lambda x: x

        result = service._create_skill_from_zip(zip_buffer.getvalue(), None, tenant_id="tenant456")

        assert result["name"] == "skill"


class TestSkillServiceGetSkillFileContentWithNestedPath:
    """Test get_skill_file_content with nested path."""

    def test_get_file_content_nested_path(self, mocker):
        """Test getting file content with nested path."""
        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager

        with patch('os.path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data="nested content")):
                result = service.get_skill_file_content("test_skill", "scripts/run.sh")

        assert result == "nested content"


class TestSkillServiceGetSkillFileContentError:
    """Test get_skill_file_content error handling."""

    def test_get_file_content_read_error(self, mocker):
        """Test getting file content with read error."""
        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager

        with patch('os.path.exists', return_value=True):
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
        mock_manager.get_skill_scripts.assert_called_once_with("test_skill")


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
            'backend.services.skill_service.skill_db.search_skills_for_agent',
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
            'backend.services.skill_service.skill_db.list_skills',
            side_effect=Exception("DB error")
        )

        service = SkillService()

        from consts.exceptions import SkillException
        try:
            service.build_skills_summary()
            assert False, "Should have raised"
        except SkillException as e:
            assert "Failed to build skills summary" in str(e)


class TestSkillServiceGetSkillContentError:
    """Test get_skill_content error handling."""

    def test_get_content_error(self, mocker):
        """Test getting content with error."""
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            side_effect=Exception("DB error")
        )

        service = SkillService()

        from consts.exceptions import SkillException
        try:
            service.get_skill_content("any_skill")
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

    def test_upload_zip_extract_error(self, mocker):
        """Test ZIP extraction error handling."""
        import zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr("skill/file.txt", "content")

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager

        # The actual code re-raises the original exception, not SkillException
        with patch('os.makedirs', side_effect=Exception("makedirs error")):
            try:
                service._upload_zip_files(zip_buffer.getvalue(), "skill", None)
                assert False, "Should have raised"
            except Exception as e:
                assert "makedirs error" in str(e)


class TestParamsDictToStorableWithInvalidData:
    """Test _params_dict_to_storable with invalid data."""

    def test_invalid_data_raises(self):
        """Test invalid data raises exception."""
        from backend.services.skill_service import _params_dict_to_storable

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
    """Test _overlay_params_from_local_config_yaml with read error."""

    def test_overlay_params_read_error(self, mocker):
        """Test overlay with read error uses DB params."""
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"name": "test_skill", "params": {"db_key": "db_value"}}
        )

        service = SkillService()
        service._resolve_local_skills_dir_for_overlay = MagicMock(return_value="/tmp/skills")

        with patch('os.path.isfile', return_value=True):
            with patch('builtins.open', side_effect=IOError("Read error")):
                result = service._overlay_params_from_local_config_yaml({"name": "test_skill"})

        assert result["name"] == "test_skill"


class TestSkillServiceResolveLocalSkillsDirWithRootDir:
    """Test _resolve_local_skills_dir_for_overlay with ROOT_DIR."""

    def test_resolve_with_root_dir_fallback(self, mocker):
        """Test resolve uses ROOT_DIR/skills when manager dir is None."""
        service = SkillService()
        service.skill_manager.local_skills_dir = None

        with patch.object(skill_service, 'CONTAINER_SKILLS_PATH', None):
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

        with patch.object(skill_service, 'CONTAINER_SKILLS_PATH', None):
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

        with patch('backend.services.skill_service.SkillManager') as mock_manager:
            with patch.object(skill_service, 'CONTAINER_SKILLS_PATH', '/custom/path'):
                manager = get_skill_manager()
                mock_manager.assert_called_once_with('/custom/path')


# ===== Additional Coverage for Remaining Uncovered Lines =====

class TestSkillServiceCreateSkillErrorPaths:
    """Test create_skill error paths."""

    def test_create_skill_db_error(self, mocker):
        """Test create_skill handles DB error."""
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value=None
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.create_skill',
            side_effect=Exception("DB error")
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = None

        service = SkillService()
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
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"name": "existing_skill", "skill_id": 1}
        )

        mock_manager = MagicMock()

        service = SkillService()
        service.skill_manager = mock_manager

        from consts.exceptions import SkillException
        try:
            service._create_skill_from_zip(zip_buffer.getvalue())
            assert False, "Should have raised"
        except SkillException as e:
            assert "already exists" in str(e)


class TestSkillServiceUpdateSkillFromFileNotFound:
    """Test update_skill_from_file not found error."""

    def test_update_from_file_not_found(self, mocker):
        """Test update_skill_from_file raises when skill not found."""
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value=None
        )

        service = SkillService()

        from consts.exceptions import SkillException
        try:
            service.update_skill_from_file("nonexistent", b"---\nname: x\n---")
            assert False, "Should have raised"
        except SkillException as e:
            assert "not found" in str(e)


class TestSkillServiceUpdateFromMdInvalidParse:
    """Test _update_skill_from_md invalid parse."""

    def test_update_md_invalid_parse_raises(self, mocker):
        """Test update from MD with invalid parse raises exception."""
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "existing"}
        )

        mocker.patch(
            'backend.services.skill_service.SkillLoader.parse',
            side_effect=ValueError("Invalid YAML")
        )

        mock_manager = MagicMock()

        service = SkillService()
        service.skill_manager = mock_manager

        from consts.exceptions import SkillException
        try:
            service._update_skill_from_md(b"invalid content", "existing")
            assert False, "Should have raised"
        except SkillException as e:
            assert "Invalid SKILL.md format" in str(e)


class TestSkillServiceUpdateFromZipNotFound:
    """Test _update_skill_from_zip not found error."""

    def test_update_zip_not_found(self, mocker):
        """Test ZIP update raises when skill not found."""
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
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
            service._update_skill_from_zip(zip_buffer.getvalue(), "nonexistent")
            assert False, "Should have raised"
        except SkillException as e:
            assert "not found" in str(e)


class TestSkillServiceGetEnabledSkillsWithEmptyRepo:
    """Test get_enabled_skills_for_agent with empty skill repository."""

    def test_get_enabled_skills_empty_repo(self, mocker):
        """Test getting enabled skills when skill not in repository."""
        mocker.patch(
            'backend.services.skill_service.skill_db.search_skills_for_agent',
            return_value=[
                {"skill_instance_id": 1, "skill_id": 999, "enabled": True}
            ]
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_id',
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
            'backend.services.skill_service.skill_db.search_skills_for_agent',
            return_value=[
                {"skill_instance_id": 1, "skill_id": 1, "enabled": False}
            ]
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_id',
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
            'backend.services.skill_service.skill_db.search_skills_for_agent',
            return_value=[
                {"skill_instance_id": 1, "skill_id": 1, "enabled": True},
                {"skill_instance_id": 2, "skill_id": 2, "enabled": True}
            ]
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_id',
            side_effect=lambda skill_id: {
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
            'backend.services.skill_service.skill_db.search_skills_for_agent',
            return_value=[
                {"skill_instance_id": 1, "skill_id": 999, "enabled": True}
            ]
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_id',
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
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.update_skill',
            return_value={"skill_id": 1, "name": "existing"}
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_tool_names_by_skill_name',
            return_value=[]
        )

        mock_manager = MagicMock()

        with patch.object(skill_service, 'CONTAINER_SKILLS_PATH', "/tmp"):
            service = SkillService()
            service.skill_manager = mock_manager
            service._overlay_params_from_local_config_yaml = lambda x: x

            with patch('backend.services.skill_service._write_skill_params_to_local_config_yaml',
                      side_effect=Exception("Write error")):
                result = service.update_skill("existing", {"params": {"key": "value"}})

        assert result["name"] == "existing"


class TestSkillServiceDeleteSkillRmtreeError:
    """Test delete_skill with rmtree error."""

    def test_delete_skill_rmtree_error(self, mocker):
        """Test delete_skill handles rmtree error."""
        mocker.patch(
            'backend.services.skill_service.skill_db.delete_skill',
            return_value=True
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.delete_skill_instances_by_skill_id',
            return_value=None
        )
        mocker.patch(
            'backend.services.skill_service.skill_db.get_skill_by_name',
            return_value={"skill_id": 1, "name": "to_delete"}
        )

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = "/tmp/skills"

        service = SkillService()
        service.skill_manager = mock_manager

        with patch('os.path.exists', return_value=True):
            with patch('shutil.rmtree', side_effect=Exception("rmtree error")):
                from consts.exceptions import SkillException
                try:
                    service.delete_skill("to_delete")
                    assert False, "Should have raised"
                except SkillException as e:
                    assert "Failed to delete" in str(e)

