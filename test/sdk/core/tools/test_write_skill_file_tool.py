"""
Unit tests for nexent.core.tools.write_skill_file_tool module.

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
_mock_nexent_skills_skill_loader = types.ModuleType("nexent.skills.skill_loader")


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
    "nexent.skills.skill_loader": _mock_nexent_skills_skill_loader,
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

    def save_skill(self, skill_data, tenant_id=None):
        """Mock save_skill that does nothing."""
        return skill_data


_mock_nexent_skills.SkillManager = MockSkillManager


# -- Mock SkillLoader for nexent.skills.skill_loader --------------------------
class MockSkillLoader:
    """Mock SkillLoader for testing."""
    @staticmethod
    def parse(content):
        """Mock parse that simulates parsing SKILL.md content."""
        if not content.startswith("---"):
            raise ValueError("YAML frontmatter is required")
        if "name:" not in content:
            raise ValueError("'name' field is required")
        if "description:" not in content:
            raise ValueError("'description' field is required")
        return {
            "name": "parsed-skill",
            "description": "parsed description",
            "content": content
        }


_mock_nexent_skills_skill_loader.SkillLoader = MockSkillLoader


# -- Now import the module under test ---------------------------------------
from sdk.nexent.core.tools.write_skill_file_tool import (
    WriteSkillFileTool,
    _uncached_write_skill_file_tool,
    _write_skill_file_without_context,
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
def existing_skill(temp_skills_dir):
    """Create an existing skill directory."""
    skill_name = "existing-skill"
    skill_dir = os.path.join(temp_skills_dir, skill_name)
    os.makedirs(skill_dir)

    # Create SKILL.md
    skill_md = """---
name: existing-skill
description: An existing skill
---
# Content
"""
    with open(os.path.join(skill_dir, "SKILL.md"), 'w', encoding='utf-8') as f:
        f.write(skill_md)

    return skill_dir, skill_name


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

class TestWriteSkillFileToolInit:
    """Test WriteSkillFileTool initialization."""

    def test_init_with_all_params(self):
        """Test initialization with all parameters."""
        tool = WriteSkillFileTool(
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
        tool = WriteSkillFileTool()
        assert tool.local_skills_dir is None
        assert tool.agent_id is None
        assert tool.tenant_id is None
        assert tool.version_no == 0
        assert tool.skill_manager is None


class TestGetSkillManager:
    """Test _get_skill_manager lazy loading."""

    def test_lazy_load_creates_manager(self, temp_skills_dir):
        """Test that _get_skill_manager creates manager on first call."""
        tool = WriteSkillFileTool(local_skills_dir=temp_skills_dir)
        assert tool.skill_manager is None
        manager = tool._get_skill_manager()
        assert manager is not None
        # Check that manager has the expected attributes instead of using isinstance
        assert hasattr(manager, 'resolve_skill_dir')
        assert hasattr(manager, 'save_skill')

    def test_lazy_load_reuses_manager(self, temp_skills_dir):
        """Test that _get_skill_manager reuses existing manager."""
        tool = WriteSkillFileTool(local_skills_dir=temp_skills_dir)
        manager1 = tool._get_skill_manager()
        manager2 = tool._get_skill_manager()
        assert manager1 is manager2


class TestExecute:
    """Test execute method."""

    def test_execute_empty_file_path(self, temp_skills_dir):
        """Test execute with empty file_path."""
        tool = WriteSkillFileTool(local_skills_dir=temp_skills_dir)
        result = tool.execute("skill", "", "content")
        assert "[Error]" in result
        assert "file_path" in result.lower()

    def test_execute_creates_new_skill_directory(self, temp_skills_dir):
        """Test execute creates new skill directory."""
        skill_name = "new-skill"
        file_path = "README.md"
        content = "# New Skill README"

        tool = WriteSkillFileTool(local_skills_dir=temp_skills_dir)
        result = tool.execute(skill_name, file_path, content)

        skill_dir = os.path.join(temp_skills_dir, skill_name)
        assert os.path.exists(skill_dir)
        file_path_full = os.path.join(skill_dir, file_path)
        assert os.path.exists(file_path_full)

    def test_execute_writes_to_existing_skill(self, existing_skill, temp_skills_dir):
        """Test execute writes to existing skill directory."""
        skill_dir, skill_name = existing_skill
        file_path = "new-file.txt"
        content = "New file content"

        tool = WriteSkillFileTool(local_skills_dir=temp_skills_dir)
        result = tool.execute(skill_name, file_path, content)

        file_path_full = os.path.join(skill_dir, file_path)
        assert os.path.exists(file_path_full)
        with open(file_path_full, 'r', encoding='utf-8') as f:
            assert f.read() == content

    def test_execute_creates_nested_directories(self, temp_skills_dir):
        """Test execute creates nested directories."""
        skill_name = "nested-skill"
        file_path = "scripts/subdir/test.py"
        content = "print('hello')"

        tool = WriteSkillFileTool(local_skills_dir=temp_skills_dir)
        result = tool.execute(skill_name, file_path, content)

        file_path_full = os.path.join(temp_skills_dir, skill_name, file_path)
        assert os.path.exists(file_path_full)

    def test_execute_normalizes_backslashes(self, temp_skills_dir):
        """Test execute normalizes backslashes to forward slashes."""
        skill_name = "slash-skill"
        file_path = "scripts\\test.py"
        content = "print('hello')"

        tool = WriteSkillFileTool(local_skills_dir=temp_skills_dir)
        result = tool.execute(skill_name, file_path, content)

        # Should work with both slash styles
        file_path_full = os.path.join(temp_skills_dir, skill_name, "scripts", "test.py")
        assert os.path.exists(file_path_full)

    def test_execute_strips_leading_slash(self, temp_skills_dir):
        """Test execute strips leading slashes from file_path."""
        skill_name = "slash-skill2"
        file_path = "/README.md"
        content = "# README"

        tool = WriteSkillFileTool(local_skills_dir=temp_skills_dir)
        result = tool.execute(skill_name, file_path, content)

        file_path_full = os.path.join(temp_skills_dir, skill_name, "README.md")
        assert os.path.exists(file_path_full)

    def test_execute_writes_skill_md(self, temp_skills_dir):
        """Test execute writes SKILL.md using save_skill."""
        skill_name = "skill-md-skill"
        file_path = "SKILL.md"
        content = """---
name: skill-md-skill
description: A skill md file
---
# Content
"""

        tool = WriteSkillFileTool(local_skills_dir=temp_skills_dir)
        result = tool.execute(skill_name, file_path, content)

        assert "Successfully" in result


class TestWriteSkillMd:
    """Test _write_skill_md method."""

    def test_write_skill_md_calls_save_skill(self, temp_skills_dir):
        """Test _write_skill_md calls manager's save_skill method."""
        tool = WriteSkillFileTool(local_skills_dir=temp_skills_dir)
        mock_manager = MagicMock()
        tool.skill_manager = mock_manager

        content = """---
name: test-skill
description: Test description
---
# Content
"""

        result = tool._write_skill_md(mock_manager, "test-skill", content)

        assert mock_manager.save_skill.called

    def test_write_skill_md_success_message(self, temp_skills_dir):
        """Test _write_skill_md returns success message."""
        tool = WriteSkillFileTool(local_skills_dir=temp_skills_dir)
        mock_manager = MagicMock()
        tool.skill_manager = mock_manager

        content = """---
name: success-skill
description: Success
---
"""
        result = tool._write_skill_md(mock_manager, "success-skill", content)

        assert "Successfully" in result
        assert "success-skill" in result

    def test_write_skill_md_invalid_format(self, temp_skills_dir):
        """Test _write_skill_md handles invalid SKILL.md format."""
        tool = WriteSkillFileTool(local_skills_dir=temp_skills_dir)
        mock_manager = MagicMock()
        tool.skill_manager = mock_manager

        content = "Invalid content without frontmatter"
        result = tool._write_skill_md(mock_manager, "invalid-skill", content)

        assert "[Error]" in result
        assert "Invalid" in result or "format" in result.lower()


class TestWriteArbitraryFile:
    """Test _write_arbitrary_file method."""

    def test_write_arbitrary_file_creates_directory(self, temp_skills_dir):
        """Test _write_arbitrary_file creates skill directory."""
        tool = WriteSkillFileTool(local_skills_dir=temp_skills_dir)
        mock_manager = MockSkillManager(local_skills_dir=temp_skills_dir)

        result = tool._write_arbitrary_file(
            mock_manager, "new-skill", "file.txt", "content"
        )

        skill_dir = os.path.join(temp_skills_dir, "new-skill")
        assert os.path.exists(skill_dir)
        assert "Successfully" in result

    def test_write_arbitrary_file_creates_nested(self, temp_skills_dir):
        """Test _write_arbitrary_file creates nested directories."""
        tool = WriteSkillFileTool(local_skills_dir=temp_skills_dir)
        mock_manager = MockSkillManager(local_skills_dir=temp_skills_dir)

        result = tool._write_arbitrary_file(
            mock_manager, "nested", "scripts/test.py", "code"
        )

        file_path = os.path.join(temp_skills_dir, "nested", "scripts", "test.py")
        assert os.path.exists(file_path)
        with open(file_path, 'r', encoding='utf-8') as f:
            assert f.read() == "code"

    def test_write_arbitrary_file_overwrites(self, temp_skills_dir):
        """Test _write_arbitrary_file overwrites existing file."""
        skill_name = "overwrite-skill"
        skill_dir = os.path.join(temp_skills_dir, skill_name)
        os.makedirs(skill_dir)
        file_path = os.path.join(skill_dir, "existing.txt")

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write("old content")

        tool = WriteSkillFileTool(local_skills_dir=temp_skills_dir)
        mock_manager = MockSkillManager(local_skills_dir=temp_skills_dir)

        result = tool._write_arbitrary_file(
            mock_manager, skill_name, "existing.txt", "new content"
        )

        with open(file_path, 'r', encoding='utf-8') as f:
            assert f.read() == "new content"


class TestWriteDirectFile:
    """Test _write_direct_file method for empty skill_name."""

    def test_write_direct_file_creates_file(self, temp_skills_dir):
        """Test _write_direct_file creates file directly in local_skills_dir."""
        tool = WriteSkillFileTool(local_skills_dir=temp_skills_dir)
        tool.skill_manager = MockSkillManager(temp_skills_dir)

        result = tool._write_direct_file("direct-file.txt", "direct content")

        assert "Successfully" in result
        file_path = os.path.join(temp_skills_dir, "direct-file.txt")
        assert os.path.exists(file_path)
        with open(file_path, 'r', encoding='utf-8') as f:
            assert f.read() == "direct content"

    def test_write_direct_file_nested_path(self, temp_skills_dir):
        """Test _write_direct_file creates nested directories."""
        tool = WriteSkillFileTool(local_skills_dir=temp_skills_dir)
        tool.skill_manager = MockSkillManager(temp_skills_dir)

        result = tool._write_direct_file("subdir/nested/file.py", "print('hello')")

        assert "Successfully" in result
        file_path = os.path.join(temp_skills_dir, "subdir", "nested", "file.py")
        assert os.path.exists(file_path)


class TestExecuteEmptySkillName:
    """Test execute with empty skill_name (writes directly to local_skills_dir)."""

    def test_execute_empty_skill_name_direct_write(self, temp_skills_dir):
        """Test execute with empty skill_name writes directly to local_skills_dir."""
        tool = WriteSkillFileTool(local_skills_dir=temp_skills_dir)
        tool.skill_manager = MockSkillManager(temp_skills_dir)

        result = tool.execute("", "root-file.txt", "root content")

        assert "Successfully" in result
        file_path = os.path.join(temp_skills_dir, "root-file.txt")
        assert os.path.exists(file_path)
        with open(file_path, 'r', encoding='utf-8') as f:
            assert f.read() == "root content"


class TestModuleFunctions:
    """Test module-level tool functions."""

    def test_uncached_write_skill_file_tool_creates_instance(self):
        """Test _uncached_write_skill_file_tool creates instance."""
        tool = _uncached_write_skill_file_tool("/path/to/skills", agent_id=1, tenant_id="t1")
        assert tool is not None
        assert isinstance(tool, WriteSkillFileTool)
        assert tool.local_skills_dir == "/path/to/skills"
        assert tool.agent_id == 1
        assert tool.tenant_id == "t1"

    def test_forward_delegates_to_execute(self, temp_skills_dir):
        """Test forward method delegates to execute."""
        tool = WriteSkillFileTool(local_skills_dir=temp_skills_dir)
        result1 = tool.execute("test-skill", "file.txt", "content")
        result2 = tool.forward("test-skill", "file.txt", "content")
        # Both should succeed
        assert "Successfully" in result1
        assert "Successfully" in result2
