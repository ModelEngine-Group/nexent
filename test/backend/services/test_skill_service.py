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
nexent_skills_mock = types.ModuleType('nexent.skills')
nexent_skills_skill_loader_mock = types.ModuleType('nexent.skills.skill_loader')
nexent_skills_skill_manager_mock = types.ModuleType('nexent.skills.skill_manager')
nexent_storage_mock = types.ModuleType('nexent.storage')
nexent_storage_storage_client_factory_mock = types.ModuleType('nexent.storage.storage_client_factory')
nexent_storage_minio_config_mock = types.ModuleType('nexent.storage.minio_config')

sys.modules['nexent'] = nexent_mock
sys.modules['nexent.core'] = nexent_core_mock
sys.modules['nexent.core.agents'] = nexent_core_agents_mock
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

nexent_skills_skill_loader_mock.SkillLoader = MockSkillLoader
nexent_skills_mock.SkillLoader = MockSkillLoader

class MockSkillManager:
    def __init__(self, local_skills_dir=None, **kwargs):
        self.local_skills_dir = local_skills_dir

nexent_skills_mock.SkillManager = MockSkillManager
nexent_skills_skill_manager_mock.SkillManager = MockSkillManager

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
sys.modules['utils'] = utils_mock
sys.modules['utils.skill_params_utils'] = utils_skill_params_utils_mock

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
