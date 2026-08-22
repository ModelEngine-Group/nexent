"""
Unit tests for nexent.core.tools.read_skill_md_tool module.

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

    def resolve_tenant_dir(self, tenant_id=None):
        return self.local_skills_dir or ""

    def load_skill(self, name, tenant_id=None):
        return {"name": name}

    def save_skill(self, skill_data, tenant_id=None):
        """Mock save_skill that does nothing."""
        return skill_data

    def run_skill_script(self, skill_name, script_path, params, agent_id=None, tenant_id=None, version_no=0):
        """Mock run_skill_script that returns success by default."""
        return "Script executed successfully"


_mock_nexent_skills.SkillManager = MockSkillManager


# -- Now import the module under test ---------------------------------------
from sdk.nexent.core.tools.read_skill_md_tool import (
    ReadSkillMdTool,
    _uncached_read_skill_md_tool,
    _read_skill_md_without_context,
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
def sample_skill(temp_skills_dir):
    """Create a sample skill with SKILL.md file."""
    skill_name = "test-skill"
    skill_dir = os.path.join(temp_skills_dir, skill_name)
    os.makedirs(skill_dir)

    skill_content = """---
name: test-skill
description: A test skill for unit testing
allowed-tools:
  - tool1
  - tool2
tags:
  - test
  - sample
---
# Skill Content
This is the skill body content.
"""
    skill_file = os.path.join(skill_dir, "SKILL.md")
    with open(skill_file, 'w', encoding='utf-8') as f:
        f.write(skill_content)

    return skill_dir, skill_name, skill_content


@pytest.fixture
def sample_skill_with_frontmatter(temp_skills_dir):
    """Create a sample skill with frontmatter that needs stripping."""
    skill_name = "frontmatter-skill"
    skill_dir = os.path.join(temp_skills_dir, skill_name)
    os.makedirs(skill_dir)

    skill_content = """---
name: frontmatter-skill
description: A skill with frontmatter
---
# Actual Content
This is the actual content after frontmatter.
"""
    skill_file = os.path.join(skill_dir, "SKILL.md")
    with open(skill_file, 'w', encoding='utf-8') as f:
        f.write(skill_content)

    return skill_dir, skill_name


@pytest.fixture
def sample_skill_with_files(temp_skills_dir):
    """Create a sample skill with multiple files."""
    skill_name = "multi-file-skill"
    skill_dir = os.path.join(temp_skills_dir, skill_name)
    os.makedirs(skill_dir)

    # Create SKILL.md
    skill_md = """---
name: multi-file-skill
description: A skill with multiple files
---
# Main Content
"""
    with open(os.path.join(skill_dir, "SKILL.md"), 'w', encoding='utf-8') as f:
        f.write(skill_md)

    # Create examples.md
    examples_content = "# Examples\nHere are examples."
    with open(os.path.join(skill_dir, "examples.md"), 'w', encoding='utf-8') as f:
        f.write(examples_content)

    # Create a nested file
    os.makedirs(os.path.join(skill_dir, "references"))
    ref_content = "# References\nReference content."
    with open(os.path.join(skill_dir, "references", "api.md"), 'w', encoding='utf-8') as f:
        f.write(ref_content)

    return skill_dir, skill_name


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

class TestReadSkillMdToolInit:
    """Test ReadSkillMdTool initialization."""

    def test_init_with_all_params(self):
        """Test initialization with all parameters."""
        tool = ReadSkillMdTool(
            local_skills_dir="/path/to/skills",
            agent_id=42,
            tenant_id="tenant-123",
            version_no=5
        )
        assert tool.local_skills_dir == "/path/to/skills"
        assert tool.agent_id == 42
        assert tool.tenant_id == "tenant-123"
        assert tool.version_no == 5
        assert tool.skill_manager is None

    def test_init_with_minimal_params(self):
        """Test initialization with minimal parameters."""
        tool = ReadSkillMdTool()
        assert tool.local_skills_dir is None
        assert tool.agent_id is None
        assert tool.tenant_id is None
        assert tool.version_no == 0
        assert tool.skill_manager is None


class TestStripFrontmatter:
    """Test _strip_frontmatter method."""

    def test_strip_frontmatter_simple(self):
        """Test stripping simple frontmatter."""
        tool = ReadSkillMdTool()
        content = """---
name: test
description: Test description
---
# Body Content
"""
        result = tool._strip_frontmatter(content)
        assert result.strip() == "# Body Content"

    def test_strip_frontmatter_no_frontmatter(self):
        """Test content without frontmatter is unchanged."""
        tool = ReadSkillMdTool()
        content = "# Just content\nNo frontmatter here."
        result = tool._strip_frontmatter(content)
        assert result == content

    def test_strip_frontmatter_multiline_values(self):
        """Test stripping frontmatter with multiline values."""
        tool = ReadSkillMdTool()
        content = """---
name: test
description: >
  Multi line
  description
---
# Body
"""
        result = tool._strip_frontmatter(content)
        assert "# Body" in result


class TestReadSkillFile:
    """Test _read_skill_file method."""

    def test_read_existing_file(self, sample_skill):
        """Test reading an existing file."""
        tool = ReadSkillMdTool()
        skill_dir, skill_name, _ = sample_skill
        content, found = tool._read_skill_file(skill_dir, "SKILL.md")
        assert found is True
        assert "Skill Content" in content

    def test_read_file_with_extension(self, sample_skill):
        """Test reading a file with .md extension when not provided."""
        tool = ReadSkillMdTool()
        skill_dir, skill_name, _ = sample_skill
        content, found = tool._read_skill_file(skill_dir, "SKILL")
        assert found is True
        assert "Skill Content" in content

    def test_read_nonexistent_file(self, temp_skills_dir):
        """Test reading a file that doesn't exist."""
        tool = ReadSkillMdTool()
        skill_dir = os.path.join(temp_skills_dir, "nonexistent")
        os.makedirs(skill_dir)
        content, found = tool._read_skill_file(skill_dir, "missing.txt")
        assert found is False
        assert "not found" in content.lower() or "missing.txt" in content

    def test_read_file_with_slash_prefix(self, sample_skill):
        """Test reading a file with leading slash."""
        tool = ReadSkillMdTool()
        skill_dir, skill_name, _ = sample_skill
        content, found = tool._read_skill_file(skill_dir, "/SKILL.md")
        assert found is True

    def test_read_file_strips_frontmatter(self, sample_skill_with_frontmatter):
        """Test that reading .md file strips frontmatter."""
        tool = ReadSkillMdTool()
        skill_dir, skill_name = sample_skill_with_frontmatter
        content, found = tool._read_skill_file(skill_dir, "SKILL.md")
        assert found is True
        assert "name:" not in content
        assert "description:" not in content
        assert "# Actual Content" in content

    def test_read_non_md_file_no_strip(self, temp_skills_dir):
        """Test that non-md files don't get frontmatter stripped."""
        tool = ReadSkillMdTool()
        skill_dir = os.path.join(temp_skills_dir, "test")
        os.makedirs(skill_dir)
        txt_file = os.path.join(skill_dir, "data.txt")
        with open(txt_file, 'w') as f:
            f.write("Plain text content")
        content, found = tool._read_skill_file(skill_dir, "data.txt")
        assert found is True
        assert "Plain text content" in content


class TestGetSkillManager:
    """Test _get_skill_manager lazy loading."""

    def test_lazy_load_creates_manager(self, temp_skills_dir):
        """Test that _get_skill_manager creates manager on first call."""
        tool = ReadSkillMdTool(local_skills_dir=temp_skills_dir)
        assert tool.skill_manager is None
        manager = tool._get_skill_manager()
        assert manager is not None
        # Check that manager has the expected attributes instead of using isinstance
        assert hasattr(manager, 'resolve_skill_dir')
        assert hasattr(manager, 'load_skill')

    def test_lazy_load_reuses_manager(self, temp_skills_dir):
        """Test that _get_skill_manager reuses existing manager."""
        tool = ReadSkillMdTool(local_skills_dir=temp_skills_dir)
        manager1 = tool._get_skill_manager()
        manager2 = tool._get_skill_manager()
        assert manager1 is manager2


class TestExecute:
    """Test execute method."""

    def test_execute_skill_not_found(self, temp_skills_dir):
        """Test execute with non-existent skill."""
        tool = ReadSkillMdTool(local_skills_dir=temp_skills_dir)
        tool.skill_manager = MockSkillManager(temp_skills_dir)
        result = tool.execute("nonexistent-skill")
        assert "not found" in result.lower()

    def test_execute_reads_default_skill_md(self, sample_skill, temp_skills_dir):
        """Test execute reads SKILL.md by default."""
        skill_dir, skill_name, expected_content = sample_skill

        tool = ReadSkillMdTool(local_skills_dir=temp_skills_dir)
        tool.skill_manager = MockSkillManager(temp_skills_dir)

        result = tool.execute(skill_name)
        assert "test-skill" in result.lower() or "Skill Content" in result

    def test_execute_reads_additional_files(self, sample_skill_with_files, temp_skills_dir):
        """Test execute reads specified additional files."""
        skill_dir, skill_name = sample_skill_with_files

        tool = ReadSkillMdTool(local_skills_dir=temp_skills_dir)
        tool.skill_manager = MockSkillManager(temp_skills_dir)

        result = tool.execute(skill_name, "examples.md")
        assert "examples.md" in result or "Examples" in result

    def test_execute_additional_files_not_found_warning(self, sample_skill, temp_skills_dir):
        """Test execute includes warning for missing additional files."""
        skill_dir, skill_name, _ = sample_skill

        tool = ReadSkillMdTool(local_skills_dir=temp_skills_dir)
        tool.skill_manager = MockSkillManager(temp_skills_dir)

        result = tool.execute(skill_name, "missing.md")
        assert "missing.md" in result
        assert "not found" in result.lower() or "warning" in result.lower()

    def test_execute_handles_exception(self, temp_skills_dir):
        """Test execute handles exceptions gracefully."""
        tool = ReadSkillMdTool(local_skills_dir=temp_skills_dir)
        mock_manager = MagicMock()
        mock_manager.load_skill.side_effect = RuntimeError("Test error")
        tool.skill_manager = mock_manager

        result = tool.execute("test-skill")
        assert "error" in result.lower() or "test error" in result.lower()

    def test_execute_empty_skill_name_reads_root(self, temp_skills_dir):
        """Test execute with empty skill_name reads from local_skills_dir root."""
        tool = ReadSkillMdTool(local_skills_dir=temp_skills_dir)
        tool.skill_manager = MockSkillManager(temp_skills_dir)

        # Create SKILL.md in root
        skill_md = """---
name: root
description: Root skill
---
# Root Skill Content
"""
        with open(os.path.join(temp_skills_dir, "SKILL.md"), 'w', encoding='utf-8') as f:
            f.write(skill_md)

        result = tool.execute("")
        assert "Root Skill Content" in result


class TestReadDirectFile:
    """Test _read_direct_file method for empty skill_name."""

    def test_read_direct_file_default_skill_md(self, temp_skills_dir):
        """Test _read_direct_file reads SKILL.md when no path specified."""
        tool = ReadSkillMdTool(local_skills_dir=temp_skills_dir)
        tool.skill_manager = MockSkillManager(temp_skills_dir)

        # Create SKILL.md in root
        skill_md = """---
name: root-skill
description: Root skill
---
# Root Content
"""
        with open(os.path.join(temp_skills_dir, "SKILL.md"), 'w', encoding='utf-8') as f:
            f.write(skill_md)

        result = tool._read_direct_file(())
        assert "Root Content" in result
        assert "name:" not in result

    def test_read_direct_file_with_path(self, temp_skills_dir):
        """Test _read_direct_file reads specified file."""
        tool = ReadSkillMdTool(local_skills_dir=temp_skills_dir)
        tool.skill_manager = MockSkillManager(temp_skills_dir)

        # Create a file in root
        test_file = os.path.join(temp_skills_dir, "test-file.txt")
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("test content")

        result = tool._read_direct_file(("test-file.txt",))
        assert "test content" in result

    def test_read_direct_file_not_found(self, temp_skills_dir):
        """Test _read_direct_file returns error for missing file."""
        tool = ReadSkillMdTool(local_skills_dir=temp_skills_dir)
        tool.skill_manager = MockSkillManager(temp_skills_dir)

        result = tool._read_direct_file(("missing.txt",))
        assert "not found" in result.lower()


class TestModuleFunctions:
    """Test module-level tool functions."""

    def test_uncached_read_skill_md_tool_creates_instance(self):
        """Test _uncached_read_skill_md_tool creates instance."""
        tool = _uncached_read_skill_md_tool("/path/to/skills", agent_id=1, tenant_id="t1")
        assert tool is not None
        assert isinstance(tool, ReadSkillMdTool)
        assert tool.local_skills_dir == "/path/to/skills"
        assert tool.agent_id == 1
        assert tool.tenant_id == "t1"

    def test_read_skill_md_without_context(self, temp_skills_dir):
        """Test _read_skill_md_without_context reads from temp dir."""
        result = _read_skill_md_without_context("test-skill")
        assert "not found" in result.lower() or "error" in result.lower()

    def test_forward_delegates_to_execute(self, temp_skills_dir):
        """Test forward method delegates to execute."""
        tool = ReadSkillMdTool(local_skills_dir=temp_skills_dir)
        tool.skill_manager = MockSkillManager(temp_skills_dir)
        result = tool.forward("test-skill")
        assert "not found" in result.lower() or "error" in result.lower()
