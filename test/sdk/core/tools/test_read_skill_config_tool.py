"""
Unit tests for nexent.core.tools.read_skill_config_tool module.

This test module follows the pattern from test_ragflow_search_tool.py with proper mocking.
"""
import os
import sys
import types
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


# ---------------------------------------------------------------------------
# Prepare mocks for external dependencies BEFORE any SDK imports.
# ---------------------------------------------------------------------------

# -- smolagents ---------------------------------------------------------------
class _MockTool:
    """A proper class that Tool can inherit from."""
    def __init__(self, *args, **kwargs):
        pass


_mock_smolagents = MagicMock()
_mock_smolagents_tools = types.ModuleType("smolagents.tools")
_mock_smolagents_tools.Tool = _MockTool
_mock_smolagents.tools = _mock_smolagents_tools

# -- namespace package stubs --------------------------------------------------
SDK_SOURCE_ROOT = Path(__file__).resolve().parents[4] / "sdk"

_mock_sdk = types.ModuleType("sdk")
_mock_sdk.__path__ = [str(SDK_SOURCE_ROOT)]

_mock_sdk_nexent = types.ModuleType("sdk.nexent")
_mock_sdk_nexent.__path__ = [str(SDK_SOURCE_ROOT / "nexent")]

_mock_sdk_nexent_core = types.ModuleType("sdk.nexent.core")
_mock_sdk_nexent_core.__path__ = [str(SDK_SOURCE_ROOT / "nexent" / "core")]

_mock_sdk_nexent_core_tools = types.ModuleType("sdk.nexent.core.tools")
_mock_sdk_nexent_core_tools.__path__ = [str(SDK_SOURCE_ROOT / "nexent" / "core" / "tools")]

_mock_nexent = types.ModuleType("nexent")
_mock_nexent_skills = types.ModuleType("nexent.skills")


# -- Register all mocks in sys.modules ----------------------------------------
_MODULE_MOCKS = {
    "smolagents": _mock_smolagents,
    "smolagents.tools": _mock_smolagents_tools,
    "sdk": _mock_sdk,
    "sdk.nexent": _mock_sdk_nexent,
    "sdk.nexent.core": _mock_sdk_nexent_core,
    "sdk.nexent.core.tools": _mock_sdk_nexent_core_tools,
    "nexent": _mock_nexent,
    "nexent.skills": _mock_nexent_skills,
}
sys.modules.update(_MODULE_MOCKS)


# -- Mock SkillManager for nexent.skills ------------------------------------
class MockSkillManager:
    """Mock SkillManager for testing."""
    def __init__(self, local_skills_dir=None, agent_id=None, tenant_id=None, version_no=0):
        self.local_skills_dir = local_skills_dir
        self.agent_id = agent_id
        self.tenant_id = tenant_id
        self.version_no = version_no

    def resolve_skill_dir(self, skill_name, tenant_id=None):
        if self.local_skills_dir:
            return os.path.join(self.local_skills_dir, skill_name)
        return skill_name

    def load_skill(self, name, tenant_id=None):
        return {"name": name}


_mock_nexent_skills.SkillManager = MockSkillManager


# -- Now import the module under test ---------------------------------------
from sdk.nexent.core.tools.read_skill_config_tool import (
    ReadSkillConfigTool,
    _uncached_read_skill_config_tool,
    _read_skill_config_without_context,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

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

    def test_execute_empty_skill_name(self, temp_skills_dir):
        """Test execute with empty skill_name."""
        tool = ReadSkillConfigTool(local_skills_dir=temp_skills_dir)
        result = tool.execute("")
        assert "[Error]" in result
        assert "skill_name" in result.lower()

    def test_execute_none_skill_name(self, temp_skills_dir):
        """Test execute with None skill_name."""
        tool = ReadSkillConfigTool(local_skills_dir=temp_skills_dir)
        result = tool.execute(None)
        assert "[Error]" in result
        assert "skill_name" in result.lower()

    def test_execute_no_local_skills_dir(self):
        """Test execute without local_skills_dir configured."""
        tool = ReadSkillConfigTool()
        result = tool.execute("some-skill")
        assert "[Error]" in result
        assert "not found" in result.lower()

    def test_execute_skill_not_found(self, temp_skills_dir):
        """Test execute with non-existent skill."""
        tool = ReadSkillConfigTool(local_skills_dir=temp_skills_dir)
        result = tool.execute("nonexistent-skill")
        assert "[Error]" in result
        assert "not found" in result.lower()

    def test_execute_config_not_found(self, skill_without_config, temp_skills_dir):
        """Test execute when skill exists but config.yaml is missing."""
        skill_dir, skill_name = skill_without_config
        tool = ReadSkillConfigTool(local_skills_dir=temp_skills_dir)
        result = tool.execute(skill_name)
        assert "[Error]" in result
        assert "config.yaml" in result.lower()
        assert "not found" in result.lower()

    def test_execute_success(self, skill_with_config, temp_skills_dir):
        """Test successful config reading."""
        skill_dir, skill_name, expected_config = skill_with_config
        tool = ReadSkillConfigTool(local_skills_dir=temp_skills_dir)
        result = tool.execute(skill_name)

        assert "[Error]" not in result
        assert "path" in result
        assert "temp_skill" in result
        assert "/mnt/nexent/skills/tmp/" in result

    def test_execute_empty_config(self, skill_with_empty_config, temp_skills_dir):
        """Test execute with empty config.yaml file."""
        skill_dir, skill_name = skill_with_empty_config
        tool = ReadSkillConfigTool(local_skills_dir=temp_skills_dir)
        result = tool.execute(skill_name)
        assert result == "{}"

    def test_execute_invalid_yaml(self, skill_with_invalid_yaml, temp_skills_dir):
        """Test execute with invalid YAML content."""
        skill_dir, skill_name = skill_with_invalid_yaml
        tool = ReadSkillConfigTool(local_skills_dir=temp_skills_dir)
        result = tool.execute(skill_name)
        assert "[Error]" in result
        assert "Failed to parse" in result or "yaml" in result.lower()

    def test_execute_yaml_list_instead_of_dict(self, skill_with_list_yaml, temp_skills_dir):
        """Test execute when config.yaml contains a list instead of dict."""
        skill_dir, skill_name = skill_with_list_yaml
        tool = ReadSkillConfigTool(local_skills_dir=temp_skills_dir)
        result = tool.execute(skill_name)
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
            yaml.dump(config_content, f)

        tool = ReadSkillConfigTool(local_skills_dir=temp_skills_dir)
        result = tool.execute(skill_name)

        assert "[Error]" not in result
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


class TestModuleFunctions:
    """Test module-level tool functions."""

    def test_uncached_read_skill_config_tool_creates_instance(self):
        """Test _uncached_read_skill_config_tool creates instance."""
        tool = _uncached_read_skill_config_tool(
            "/path/to/skills", agent_id=1, tenant_id="t1"
        )
        assert tool is not None
        assert isinstance(tool, ReadSkillConfigTool)
        assert tool.local_skills_dir == "/path/to/skills"
        assert tool.agent_id == 1
        assert tool.tenant_id == "t1"

    def test_read_skill_config_without_context(self, temp_skills_dir):
        """Test _read_skill_config_without_context reads from temp dir."""
        result = _read_skill_config_without_context("test-skill")
        assert "[Error]" in result
        assert "not found" in result.lower()

    def test_uncached_tool_with_all_params(self):
        """Test _uncached_read_skill_config_tool with all parameters."""
        tool = _uncached_read_skill_config_tool(
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

    def test_forward_delegates_to_execute(self, temp_skills_dir):
        """Test forward method delegates to execute."""
        tool = ReadSkillConfigTool(local_skills_dir=temp_skills_dir)
        result = tool.forward("test-skill")
        assert result == tool.execute("test-skill")
