"""
Unit tests for nexent.core.tools.read_skill_config_tool module.
"""
import os
import sys
import tempfile
import shutil
import importlib.util
from unittest.mock import MagicMock, patch

import pytest
import yaml


# Load the module directly without going through __init__.py
spec = importlib.util.spec_from_file_location(
    "read_skill_config_tool",
    os.path.join(os.path.dirname(__file__), "../../../../sdk/nexent/core/tools/read_skill_config_tool.py")
)
read_skill_config_tool_module = importlib.util.module_from_spec(spec)

# Mock the smolagents.tool decorator and nexent.skills dependencies before loading
mock_smolagents = MagicMock()
sys.modules['smolagents'] = mock_smolagents
sys.modules['smolagents.tool'] = mock_smolagents.tool

# Mock nexent.skills before loading
mock_nexent = MagicMock()
mock_nexent.skills = MagicMock()
sys.modules['nexent'] = mock_nexent
sys.modules['nexent.skills'] = mock_nexent.skills

# Now load the module
spec.loader.exec_module(read_skill_config_tool_module)

ReadSkillConfigTool = read_skill_config_tool_module.ReadSkillConfigTool
get_read_skill_config_tool = read_skill_config_tool_module.get_read_skill_config_tool
read_skill_config = read_skill_config_tool_module.read_skill_config


@pytest.fixture
def temp_skills_dir():
    """Create a temporary directory for skills storage."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def skill_with_config(temp_skills_dir):
    """Create a sample skill with config.yaml file."""
    skill_name = "test-config-skill"
    skill_dir = os.path.join(temp_skills_dir, skill_name)
    os.makedirs(skill_dir)

    config_content = {
        "path": {
            "temp_skill": "/mnt/nexent/skills/tmp/"
        },
        "options": {
            "max_retries": 3,
            "timeout": 60
        }
    }
    config_file = os.path.join(skill_dir, "config.yaml")
    with open(config_file, 'w', encoding='utf-8') as f:
        yaml.dump(config_content, f)

    return skill_dir, skill_name, config_content


@pytest.fixture
def skill_with_empty_config(temp_skills_dir):
    """Create a sample skill with empty config.yaml file."""
    skill_name = "empty-config-skill"
    skill_dir = os.path.join(temp_skills_dir, skill_name)
    os.makedirs(skill_dir)

    config_file = os.path.join(skill_dir, "config.yaml")
    with open(config_file, 'w', encoding='utf-8') as f:
        f.write("")

    return skill_dir, skill_name


@pytest.fixture
def skill_without_config(temp_skills_dir):
    """Create a sample skill without config.yaml file."""
    skill_name = "no-config-skill"
    skill_dir = os.path.join(temp_skills_dir, skill_name)
    os.makedirs(skill_dir)

    # Create just SKILL.md to make it a valid skill
    skill_md = os.path.join(skill_dir, "SKILL.md")
    with open(skill_md, 'w', encoding='utf-8') as f:
        f.write("---\nname: no-config-skill\ndescription: No config skill\n---\n# Content")

    return skill_dir, skill_name


@pytest.fixture
def skill_with_invalid_yaml(temp_skills_dir):
    """Create a sample skill with invalid config.yaml file."""
    skill_name = "invalid-config-skill"
    skill_dir = os.path.join(temp_skills_dir, skill_name)
    os.makedirs(skill_dir)

    config_file = os.path.join(skill_dir, "config.yaml")
    with open(config_file, 'w', encoding='utf-8') as f:
        f.write("invalid: yaml: content: [not proper")

    return skill_dir, skill_name


@pytest.fixture
def skill_with_list_yaml(temp_skills_dir):
    """Create a sample skill with config.yaml that is a list instead of dict."""
    skill_name = "list-config-skill"
    skill_dir = os.path.join(temp_skills_dir, skill_name)
    os.makedirs(skill_dir)

    config_file = os.path.join(skill_dir, "config.yaml")
    with open(config_file, 'w', encoding='utf-8') as f:
        yaml.dump(["item1", "item2"], f)

    return skill_dir, skill_name


@pytest.fixture
def read_skill_config_tool(temp_skills_dir):
    """Create ReadSkillConfigTool instance for testing."""
    tool = ReadSkillConfigTool(
        local_skills_dir=temp_skills_dir,
        agent_id=1,
        tenant_id="test-tenant",
        version_no=0
    )
    return tool


class TestReadSkillConfigToolInit:
    """Test ReadSkillConfigTool initialization."""

    def test_init_with_all_params(self):
        """Test initialization with all parameters."""
        tool = ReadSkillConfigTool(
            local_skills_dir="/path/to/skills",
            agent_id=42,
            tenant_id="tenant-123",
            version_no=5
        )
        assert tool.local_skills_dir == "/path/to/skills"
        assert tool.agent_id == 42
        assert tool.tenant_id == "tenant-123"
        assert tool.version_no == 5

    def test_init_with_minimal_params(self):
        """Test initialization with minimal parameters."""
        tool = ReadSkillConfigTool()
        assert tool.local_skills_dir is None
        assert tool.agent_id is None
        assert tool.tenant_id is None
        assert tool.version_no == 0


class TestExecute:
    """Test execute method."""

    def test_execute_empty_skill_name(self, read_skill_config_tool):
        """Test execute with empty skill_name."""
        result = read_skill_config_tool.execute("")
        assert "[Error]" in result
        assert "skill_name" in result.lower()

    def test_execute_none_skill_name(self, read_skill_config_tool):
        """Test execute with None skill_name."""
        result = read_skill_config_tool.execute(None)
        assert "[Error]" in result
        assert "skill_name" in result.lower()

    def test_execute_no_local_skills_dir(self):
        """Test execute without local_skills_dir configured."""
        tool = ReadSkillConfigTool()
        result = tool.execute("some-skill")
        assert "[Error]" in result
        assert "local_skills_dir" in result.lower()

    def test_execute_skill_not_found(self, read_skill_config_tool, temp_skills_dir):
        """Test execute with non-existent skill."""
        result = read_skill_config_tool.execute("nonexistent-skill")
        assert "[Error]" in result
        assert "not found" in result.lower()

    def test_execute_config_not_found(self, read_skill_config_tool, skill_without_config):
        """Test execute when skill exists but config.yaml is missing."""
        skill_dir, skill_name = skill_without_config
        result = read_skill_config_tool.execute(skill_name)
        assert "[Error]" in result
        assert "config.yaml" in result.lower()
        assert "not found" in result.lower()

    def test_execute_success(self, read_skill_config_tool, skill_with_config):
        """Test successful config reading."""
        skill_dir, skill_name, expected_config = skill_with_config
        result = read_skill_config_tool.execute(skill_name)

        assert "[Error]" not in result
        assert "path" in result
        assert "temp_skill" in result
        assert "/mnt/nexent/skills/tmp/" in result

    def test_execute_empty_config(self, read_skill_config_tool, skill_with_empty_config):
        """Test execute with empty config.yaml file."""
        skill_dir, skill_name = skill_with_empty_config
        result = read_skill_config_tool.execute(skill_name)

        # Empty YAML should return "{}"
        assert result == "{}"

    def test_execute_invalid_yaml(self, read_skill_config_tool, skill_with_invalid_yaml):
        """Test execute with invalid YAML content."""
        skill_dir, skill_name = skill_with_invalid_yaml
        result = read_skill_config_tool.execute(skill_name)

        assert "[Error]" in result
        assert "Failed to parse" in result or "yaml" in result.lower()

    def test_execute_yaml_list_instead_of_dict(self, read_skill_config_tool, skill_with_list_yaml):
        """Test execute when config.yaml contains a list instead of dict."""
        skill_dir, skill_name = skill_with_list_yaml
        result = read_skill_config_tool.execute(skill_name)

        assert "[Error]" in result
        assert "YAML dictionary" in result or "must contain" in result.lower()


class TestExecuteEdgeCases:
    """Test edge cases for execute method."""

    def test_execute_config_with_special_chars(self, temp_skills_dir):
        """Test reading config with special characters."""
        skill_name = "special-chars-skill"
        skill_dir = os.path.join(temp_skills_dir, skill_name)
        os.makedirs(skill_dir)

        config_content = {
            "description": "Config with special chars: : {} [] # | >",
            "nested": {
                "key": "value with 'quotes' and \"double quotes\""
            }
        }
        config_file = os.path.join(skill_dir, "config.yaml")
        with open(config_file, 'w', encoding='utf-8') as f:
            yaml.dump(config_content, f)

        tool = ReadSkillConfigTool(local_skills_dir=temp_skills_dir)
        result = tool.execute(skill_name)

        assert "[Error]" not in result
        assert "special chars" in result

    def test_execute_config_with_unicode(self, temp_skills_dir):
        """Test reading config with unicode characters."""
        skill_name = "unicode-skill"
        skill_dir = os.path.join(temp_skills_dir, skill_name)
        os.makedirs(skill_dir)

        config_content = {
            "name": "Test Skill",
            "description": "Description with unicode: 中文 日本語 한국어"
        }
        config_file = os.path.join(skill_dir, "config.yaml")
        with open(config_file, 'w', encoding='utf-8') as f:
            yaml.dump(config_content, f, allow_unicode=True)

        tool = ReadSkillConfigTool(local_skills_dir=temp_skills_dir)
        result = tool.execute(skill_name)

        assert "[Error]" not in result
        # Unicode characters should be preserved
        assert "unicode" in result.lower() or "中文" in result

    def test_execute_config_with_multiline(self, temp_skills_dir):
        """Test reading config with multiline strings."""
        skill_name = "multiline-skill"
        skill_dir = os.path.join(temp_skills_dir, skill_name)
        os.makedirs(skill_dir)

        config_content = {
            "script_content": "Line 1\nLine 2\nLine 3",
            "multiline_desc": """
This is a
multiline
description
"""
        }
        config_file = os.path.join(skill_dir, "config.yaml")
        with open(config_file, 'w', encoding='utf-8') as f:
            yaml.dump(config_content, f)

        tool = ReadSkillConfigTool(local_skills_dir=temp_skills_dir)
        result = tool.execute(skill_name)

        assert "[Error]" not in result

    def test_execute_skill_directory_is_file(self, temp_skills_dir):
        """Test execute when skill_name matches a file instead of directory."""
        skill_name = "file-as-skill"
        skill_file = os.path.join(temp_skills_dir, skill_name)
        with open(skill_file, 'w', encoding='utf-8') as f:
            f.write("This is a file, not a directory")

        tool = ReadSkillConfigTool(local_skills_dir=temp_skills_dir)
        result = tool.execute(skill_name)

        assert "[Error]" in result
        assert "not found" in result.lower() or "directory" in result.lower()

    def test_execute_config_file_is_directory(self, temp_skills_dir):
        """Test execute when config.yaml is actually a directory."""
        skill_name = "config-is-dir-skill"
        skill_dir = os.path.join(temp_skills_dir, skill_name)
        os.makedirs(skill_dir)
        config_dir = os.path.join(skill_dir, "config.yaml")
        os.makedirs(config_dir)

        tool = ReadSkillConfigTool(local_skills_dir=temp_skills_dir)
        result = tool.execute(skill_name)

        assert "[Error]" in result
        assert "config.yaml" in result.lower()


class TestGetReadSkillConfigTool:
    """Test get_read_skill_config_tool singleton function."""

    def test_get_tool_creates_instance(self):
        """Test get_read_skill_config_tool creates instance."""
        read_skill_config_tool_module._global_tool_instance = None

        tool = get_read_skill_config_tool("/path/to/skills", agent_id=1)
        assert tool is not None
        assert isinstance(tool, ReadSkillConfigTool)

    def test_get_tool_reuses_instance(self):
        """Test get_read_skill_config_tool reuses existing instance."""
        read_skill_config_tool_module._global_tool_instance = None

        tool1 = get_read_skill_config_tool()
        tool2 = get_read_skill_config_tool()
        assert tool1 is tool2


class TestReadSkillConfigToolDecorator:
    """Test the @tool decorated function."""

    def test_read_skill_config_decorator_exists(self):
        """Test that read_skill_config is decorated properly."""
        assert read_skill_config is not None
        assert callable(read_skill_config)

    def test_read_skill_config_with_skill_name(self, temp_skills_dir):
        """Test read_skill_config function with skill name - @tool returns wrapper."""
        read_skill_config_tool_module._global_tool_instance = None
        # The @tool decorator returns a wrapper, so we just verify it exists
        assert hasattr(read_skill_config, '__call__')


class TestGetSkillConfigToolReuse:
    """Test get_read_skill_config_tool singleton reuse."""

    def test_get_tool_reuses_with_different_params(self):
        """Test get_read_skill_config_tool returns same instance even with different params."""
        read_skill_config_tool_module._global_tool_instance = None

        tool1 = get_read_skill_config_tool("/path/one", agent_id=1)
        tool2 = get_read_skill_config_tool("/path/two", agent_id=2)

        # Should return the same instance
        assert tool1 is tool2
        # Should have the original params from first call
        assert tool1.local_skills_dir == "/path/one"
        assert tool1.agent_id == 1

    def test_get_tool_with_all_params(self):
        """Test get_read_skill_config_tool with all parameters."""
        read_skill_config_tool_module._global_tool_instance = None

        tool = get_read_skill_config_tool(
            local_skills_dir="/skills",
            agent_id=42,
            tenant_id="test-tenant",
            version_no=5
        )

        assert tool is not None
        assert tool.local_skills_dir == "/skills"
        assert tool.agent_id == 42
        assert tool.tenant_id == "test-tenant"
        assert tool.version_no == 5
