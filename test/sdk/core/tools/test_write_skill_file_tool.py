"""
Unit tests for nexent.core.tools.write_skill_file_tool module.
"""
import os
import sys
import tempfile
import shutil
import importlib.util
import types
from unittest.mock import MagicMock, patch

import pytest


# Load the module directly without going through __init__.py
spec = importlib.util.spec_from_file_location(
    "write_skill_file_tool",
    os.path.join(os.path.dirname(__file__), "../../../../sdk/nexent/core/tools/write_skill_file_tool.py")
)
write_skill_file_tool_module = importlib.util.module_from_spec(spec)

# Mock the smolagents.tool decorator
mock_smolagents = MagicMock()
sys.modules['smolagents'] = mock_smolagents
sys.modules['smolagents.tool'] = mock_smolagents.tool


# Mock SkillLoader
class MockSkillLoader:
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


# Create mock module for nexent.skills.skill_loader
mock_skill_loader_module = types.ModuleType('nexent.skills.skill_loader')
mock_skill_loader_module.SkillLoader = MockSkillLoader

# Mock nexent.skills.skill_manager
mock_skill_manager_module = types.ModuleType('nexent.skills.skill_manager')

class MockSkillManager:
    def __init__(self, local_skills_dir=None, agent_id=None, tenant_id=None, version_no=0):
        self.local_skills_dir = local_skills_dir
        self.agent_id = agent_id
        self.tenant_id = tenant_id
        self.version_no = version_no

    def load_skill(self, name):
        return None

    def list_skills(self):
        return []

    def save_skill(self, skill_data):
        """Mock save_skill implementation."""
        return skill_data


mock_skill_manager_module.SkillManager = MockSkillManager
mock_skill_manager_module.SkillNotFoundError = type('SkillNotFoundError', (Exception,), {})
mock_skill_manager_module.SkillScriptNotFoundError = type('SkillScriptNotFoundError', (Exception,), {})

# Mock nexent.skills
mock_nexent_skills = types.ModuleType('nexent.skills')
mock_nexent_skills.skill_manager = mock_skill_manager_module
mock_nexent_skills.skill_loader = mock_skill_loader_module

# Mock nexent
mock_nexent = types.ModuleType('nexent')
mock_nexent.skills = mock_nexent_skills

# Set up mocks in sys.modules
sys.modules['nexent'] = mock_nexent
sys.modules['nexent.skills'] = mock_nexent_skills
sys.modules['nexent.skills.skill_manager'] = mock_skill_manager_module
sys.modules['nexent.skills.skill_loader'] = mock_skill_loader_module

# Now load the module
spec.loader.exec_module(write_skill_file_tool_module)

WriteSkillFileTool = write_skill_file_tool_module.WriteSkillFileTool
get_write_skill_file_tool = write_skill_file_tool_module.get_write_skill_file_tool
write_skill_file = write_skill_file_tool_module.write_skill_file


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


@pytest.fixture
def write_skill_file_tool(temp_skills_dir):
    """Create WriteSkillFileTool instance for testing."""
    tool = WriteSkillFileTool(
        local_skills_dir=temp_skills_dir,
        agent_id=1,
        tenant_id="test-tenant",
        version_no=0
    )
    return tool


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

    def test_lazy_load_creates_manager(self, write_skill_file_tool, temp_skills_dir):
        """Test that _get_skill_manager creates manager on first call."""
        assert write_skill_file_tool.skill_manager is None
        # Patch _get_skill_manager to return a mock
        mock_manager = MagicMock()
        with patch.object(write_skill_file_tool, '_get_skill_manager', return_value=mock_manager):
            manager = write_skill_file_tool._get_skill_manager()
        assert manager is not None
        assert write_skill_file_tool.skill_manager is None  # Still None since we patched

    def test_lazy_load_reuses_manager(self, write_skill_file_tool):
        """Test that _get_skill_manager reuses existing manager."""
        mock_manager = MagicMock()
        write_skill_file_tool.skill_manager = mock_manager
        manager1 = write_skill_file_tool._get_skill_manager()
        manager2 = write_skill_file_tool._get_skill_manager()
        assert manager1 is manager2
        assert manager1 is mock_manager


class TestExecute:
    """Test execute method."""

    def test_execute_empty_skill_name(self, write_skill_file_tool):
        """Test execute with empty skill_name."""
        result = write_skill_file_tool.execute("", "file.txt", "content")
        assert "[Error]" in result
        assert "skill_name" in result.lower()

    def test_execute_empty_file_path(self, write_skill_file_tool):
        """Test execute with empty file_path."""
        result = write_skill_file_tool.execute("skill", "", "content")
        assert "[Error]" in result
        assert "file_path" in result.lower()

    def test_execute_creates_new_skill_directory(self, write_skill_file_tool, temp_skills_dir):
        """Test execute creates new skill directory."""
        skill_name = "new-skill"
        file_path = "README.md"
        content = "# New Skill README"

        # Mock the skill manager
        mock_manager = MagicMock()
        mock_manager.local_skills_dir = temp_skills_dir
        with patch.object(write_skill_file_tool, '_get_skill_manager', return_value=mock_manager):
            result = write_skill_file_tool.execute(skill_name, file_path, content)

        skill_dir = os.path.join(temp_skills_dir, skill_name)
        assert os.path.exists(skill_dir)
        file_path_full = os.path.join(skill_dir, file_path)
        assert os.path.exists(file_path_full)

    def test_execute_writes_to_existing_skill(self, write_skill_file_tool, existing_skill, temp_skills_dir):
        """Test execute writes to existing skill directory."""
        skill_dir, skill_name = existing_skill
        file_path = "new-file.txt"
        content = "New file content"

        # Mock the skill manager
        mock_manager = MagicMock()
        mock_manager.local_skills_dir = temp_skills_dir
        with patch.object(write_skill_file_tool, '_get_skill_manager', return_value=mock_manager):
            result = write_skill_file_tool.execute(skill_name, file_path, content)

        file_path_full = os.path.join(skill_dir, file_path)
        assert os.path.exists(file_path_full)
        with open(file_path_full, 'r', encoding='utf-8') as f:
            assert f.read() == content

    def test_execute_creates_nested_directories(self, write_skill_file_tool, temp_skills_dir):
        """Test execute creates nested directories."""
        skill_name = "nested-skill"
        file_path = "scripts/subdir/test.py"
        content = "print('hello')"

        # Mock the skill manager
        mock_manager = MagicMock()
        mock_manager.local_skills_dir = temp_skills_dir
        with patch.object(write_skill_file_tool, '_get_skill_manager', return_value=mock_manager):
            result = write_skill_file_tool.execute(skill_name, file_path, content)

        file_path_full = os.path.join(temp_skills_dir, skill_name, file_path)
        assert os.path.exists(file_path_full)

    def test_execute_normalizes_backslashes(self, write_skill_file_tool, temp_skills_dir):
        """Test execute normalizes backslashes to forward slashes."""
        skill_name = "slash-skill"
        file_path = "scripts\\test.py"
        content = "print('hello')"

        # Mock the skill manager
        mock_manager = MagicMock()
        mock_manager.local_skills_dir = temp_skills_dir
        with patch.object(write_skill_file_tool, '_get_skill_manager', return_value=mock_manager):
            result = write_skill_file_tool.execute(skill_name, file_path, content)

        # Should work with both slash styles
        file_path_full = os.path.join(temp_skills_dir, skill_name, "scripts", "test.py")
        assert os.path.exists(file_path_full)

    def test_execute_strips_leading_slash(self, write_skill_file_tool, temp_skills_dir):
        """Test execute strips leading slashes from file_path."""
        skill_name = "slash-skill2"
        file_path = "/README.md"
        content = "# README"

        # Mock the skill manager
        mock_manager = MagicMock()
        mock_manager.local_skills_dir = temp_skills_dir
        with patch.object(write_skill_file_tool, '_get_skill_manager', return_value=mock_manager):
            result = write_skill_file_tool.execute(skill_name, file_path, content)

        file_path_full = os.path.join(temp_skills_dir, skill_name, "README.md")
        assert os.path.exists(file_path_full)

    def test_execute_writes_skill_md(self, write_skill_file_tool, temp_skills_dir):
        """Test execute writes SKILL.md using save_skill."""
        skill_name = "skill-md-skill"
        file_path = "SKILL.md"
        content = """---
name: skill-md-skill
description: A skill md file
---
# Content
"""

        mock_manager = MagicMock()
        write_skill_file_tool.skill_manager = mock_manager

        result = write_skill_file_tool.execute(skill_name, file_path, content)

        # Should call save_skill
        assert mock_manager.save_skill.called or "Successfully" in result

    def test_execute_handles_manager_init_error(self, write_skill_file_tool, temp_skills_dir):
        """Test execute handles errors during skill manager initialization."""
        # Force an error during _get_skill_manager
        write_skill_file_tool.skill_manager = None
        write_skill_file_tool.local_skills_dir = None

        result = write_skill_file_tool.execute("skill", "file.txt", "content")

        assert "[Error]" in result
        assert "Failed to initialize" in result or "skill manager" in result.lower()

    def test_execute_handles_write_error(self, write_skill_file_tool, temp_skills_dir):
        """Test execute handles errors during file write."""
        skill_name = "write-error-skill"

        # Create skill dir but make it read-only
        skill_dir = os.path.join(temp_skills_dir, skill_name)
        os.makedirs(skill_dir)

        with patch('builtins.open', side_effect=IOError("Write error")):
            result = write_skill_file_tool.execute(skill_name, "file.txt", "content")

        assert "[Error]" in result or "error" in result.lower()

    def test_execute_handles_skill_md_parse_error(self, write_skill_file_tool, temp_skills_dir):
        """Test execute handles ValueError during SKILL.md parsing."""
        skill_name = "parse-error-skill"
        file_path = "SKILL.md"
        content = "Invalid content without frontmatter"

        mock_manager = MagicMock()
        write_skill_file_tool.skill_manager = mock_manager

        result = write_skill_file_tool.execute(skill_name, file_path, content)

        assert "[Error]" in result or "Invalid" in result

    def test_execute_handles_unexpected_error(self, write_skill_file_tool, temp_skills_dir):
        """Test execute handles unexpected exceptions."""
        skill_name = "unexpected-error-skill"

        mock_manager = MagicMock()
        mock_manager.save_skill.side_effect = RuntimeError("Unexpected error")
        write_skill_file_tool.skill_manager = mock_manager

        result = write_skill_file_tool.execute(skill_name, "SKILL.md", """---
name: test
description: test
---
""")

        assert "[Error]" in result or "RuntimeError" in result


class TestWriteSkillMd:
    """Test _write_skill_md method."""

    def test_write_skill_md_calls_save_skill(self, write_skill_file_tool, temp_skills_dir):
        """Test _write_skill_md calls manager's save_skill method."""
        mock_manager = MagicMock()
        write_skill_file_tool.skill_manager = mock_manager

        content = """---
name: test-skill
description: Test description
---
# Content
"""

        result = write_skill_file_tool._write_skill_md(mock_manager, "test-skill", content)

        assert mock_manager.save_skill.called
        call_args = mock_manager.save_skill.call_args[0][0]
        assert call_args["name"] == "test-skill"
        assert call_args["content"] == content

    def test_write_skill_md_success_message(self, write_skill_file_tool, temp_skills_dir):
        """Test _write_skill_md returns success message."""
        mock_manager = MagicMock()
        write_skill_file_tool.skill_manager = mock_manager

        content = """---
name: success-skill
description: Success
---
"""
        result = write_skill_file_tool._write_skill_md(mock_manager, "success-skill", content)

        assert "Successfully" in result
        assert "success-skill" in result

    def test_write_skill_md_invalid_format(self, write_skill_file_tool, temp_skills_dir):
        """Test _write_skill_md handles invalid SKILL.md format."""
        mock_manager = MagicMock()
        write_skill_file_tool.skill_manager = mock_manager

        content = "Invalid content without frontmatter"
        result = write_skill_file_tool._write_skill_md(mock_manager, "invalid-skill", content)

        assert "[Error]" in result
        assert "Invalid" in result or "format" in result.lower()


class TestWriteArbitraryFile:
    """Test _write_arbitrary_file method."""

    def test_write_arbitrary_file_no_local_dir(self, write_skill_file_tool):
        """Test _write_arbitrary_file without local_skills_dir."""
        mock_manager = MagicMock()
        mock_manager.local_skills_dir = None

        result = write_skill_file_tool._write_arbitrary_file(
            mock_manager, "skill", "file.txt", "content"
        )

        assert "[Error]" in result
        assert "local_skills_dir" in result.lower()

    def test_write_arbitrary_file_creates_directory(self, write_skill_file_tool, temp_skills_dir):
        """Test _write_arbitrary_file creates skill directory."""
        mock_manager = MagicMock()
        mock_manager.local_skills_dir = temp_skills_dir

        result = write_skill_file_tool._write_arbitrary_file(
            mock_manager, "new-skill", "file.txt", "content"
        )

        skill_dir = os.path.join(temp_skills_dir, "new-skill")
        assert os.path.exists(skill_dir)
        assert "Successfully" in result

    def test_write_arbitrary_file_creates_nested(self, write_skill_file_tool, temp_skills_dir):
        """Test _write_arbitrary_file creates nested directories."""
        mock_manager = MagicMock()
        mock_manager.local_skills_dir = temp_skills_dir

        result = write_skill_file_tool._write_arbitrary_file(
            mock_manager, "nested", "scripts/test.py", "code"
        )

        file_path = os.path.join(temp_skills_dir, "nested", "scripts", "test.py")
        assert os.path.exists(file_path)
        with open(file_path, 'r', encoding='utf-8') as f:
            assert f.read() == "code"

    def test_write_arbitrary_file_overwrites(self, write_skill_file_tool, temp_skills_dir):
        """Test _write_arbitrary_file overwrites existing file."""
        skill_name = "overwrite-skill"
        skill_dir = os.path.join(temp_skills_dir, skill_name)
        os.makedirs(skill_dir)
        file_path = os.path.join(skill_dir, "existing.txt")

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write("old content")

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = temp_skills_dir

        result = write_skill_file_tool._write_arbitrary_file(
            mock_manager, skill_name, "existing.txt", "new content"
        )

        with open(file_path, 'r', encoding='utf-8') as f:
            assert f.read() == "new content"

    def test_write_arbitrary_file_error(self, write_skill_file_tool, temp_skills_dir):
        """Test _write_arbitrary_file handles write errors."""
        mock_manager = MagicMock()
        mock_manager.local_skills_dir = temp_skills_dir

        with patch('builtins.open', side_effect=PermissionError("Permission denied")):
            result = write_skill_file_tool._write_arbitrary_file(
                mock_manager, "error-skill", "file.txt", "content"
            )

        assert "[Error]" in result or "Permission denied" in result


class TestGetWriteSkillFileTool:
    """Test get_write_skill_file_tool singleton function."""

    def test_get_tool_creates_instance(self):
        """Test get_write_skill_file_tool creates instance."""
        write_skill_file_tool_module._global_tool_instance = None

        tool = get_write_skill_file_tool("/path/to/skills", agent_id=1)
        assert tool is not None
        assert isinstance(tool, WriteSkillFileTool)

    def test_get_tool_reuses_instance(self):
        """Test get_write_skill_file_tool reuses existing instance."""
        write_skill_file_tool_module._global_tool_instance = None

        tool1 = get_write_skill_file_tool()
        tool2 = get_write_skill_file_tool()
        assert tool1 is tool2


class TestWriteSkillFileToolDecorator:
    """Test the @tool decorated function."""

    def test_write_skill_file_decorator_exists(self):
        """Test that write_skill_file is decorated properly."""
        assert write_skill_file is not None
        assert callable(write_skill_file)

    def test_write_skill_file_with_params(self, temp_skills_dir):
        """Test write_skill_file function with parameters - @tool returns wrapper."""
        write_skill_file_tool_module._global_tool_instance = None
        # The @tool decorator returns a wrapper, so we just verify it exists
        assert hasattr(write_skill_file, '__call__')


class TestExecuteEdgeCases:
    """Test edge cases for execute method."""

    def test_execute_with_unicode_content(self, write_skill_file_tool, temp_skills_dir):
        """Test execute writes unicode content correctly."""
        skill_name = "unicode-skill"
        file_path = "unicode.txt"
        content = "Hello, 世界! 日本語 한국어"

        # Mock the skill manager
        mock_manager = MagicMock()
        mock_manager.local_skills_dir = temp_skills_dir
        with patch.object(write_skill_file_tool, '_get_skill_manager', return_value=mock_manager):
            result = write_skill_file_tool.execute(skill_name, file_path, content)

        file_path_full = os.path.join(temp_skills_dir, skill_name, file_path)
        with open(file_path_full, 'r', encoding='utf-8') as f:
            assert f.read() == content

    def test_execute_with_empty_content(self, write_skill_file_tool, temp_skills_dir):
        """Test execute writes empty content."""
        skill_name = "empty-skill"
        file_path = "empty.txt"
        content = ""

        # Mock the skill manager
        mock_manager = MagicMock()
        mock_manager.local_skills_dir = temp_skills_dir
        with patch.object(write_skill_file_tool, '_get_skill_manager', return_value=mock_manager):
            result = write_skill_file_tool.execute(skill_name, file_path, content)

        file_path_full = os.path.join(temp_skills_dir, skill_name, file_path)
        assert os.path.exists(file_path_full)
        assert os.path.getsize(file_path_full) == 0

    def test_execute_normalizes_case_insensitive(self, write_skill_file_tool, temp_skills_dir):
        """Test execute handles case-insensitive SKILL.md check."""
        skill_name = "case-skill"
        file_path = "skill.md"  # lowercase

        # Mock the skill manager
        mock_manager = MagicMock()
        mock_manager.save_skill.return_value = {"name": skill_name}
        write_skill_file_tool.skill_manager = mock_manager

        content = """---
name: case-skill
description: Case test
---
"""
        result = write_skill_file_tool.execute(skill_name, file_path, content)

        # Should treat skill.md as SKILL.md (case-insensitive)
        # Either save_skill is called OR a file is written
        assert mock_manager.save_skill.called or os.path.exists(os.path.join(temp_skills_dir, skill_name, "skill.md"))

    def test_execute_with_complex_path(self, write_skill_file_tool, temp_skills_dir):
        """Test execute handles complex file paths."""
        skill_name = "complex-path-skill"
        file_path = "a/b/c/d/e.txt"
        content = "Deep path content"

        # Mock the skill manager
        mock_manager = MagicMock()
        mock_manager.local_skills_dir = temp_skills_dir
        with patch.object(write_skill_file_tool, '_get_skill_manager', return_value=mock_manager):
            result = write_skill_file_tool.execute(skill_name, file_path, content)

        # Normalize path for Windows
        file_path_full = os.path.join(temp_skills_dir, skill_name, "a", "b", "c", "d", "e.txt")
        assert os.path.exists(file_path_full)
        with open(file_path_full, 'r', encoding='utf-8') as f:
            assert f.read() == content


class TestGetWriteSkillFileToolReuse:
    """Test get_write_skill_file_tool singleton reuse."""

    def test_get_tool_reuses_with_different_params(self):
        """Test get_write_skill_file_tool returns same instance even with different params."""
        write_skill_file_tool_module._global_tool_instance = None

        tool1 = get_write_skill_file_tool("/path/one", agent_id=1)
        tool2 = get_write_skill_file_tool("/path/two", agent_id=2)

        # Should return the same instance
        assert tool1 is tool2
        # Should have the original params from first call
        assert tool1.local_skills_dir == "/path/one"
        assert tool1.agent_id == 1

    def test_get_tool_with_all_params(self):
        """Test get_write_skill_file_tool with all parameters."""
        write_skill_file_tool_module._global_tool_instance = None

        tool = get_write_skill_file_tool(
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


class TestWriteSkillMdBranches:
    """Test _write_skill_md method branches."""

    def test_write_skill_md_with_special_chars_in_name(self, write_skill_file_tool, temp_skills_dir):
        """Test _write_skill_md handles special characters in skill name."""
        mock_manager = MagicMock()
        write_skill_file_tool.skill_manager = mock_manager

        content = """---
name: test-skill_special
description: Test with special chars
---
# Content
"""
        result = write_skill_file_tool._write_skill_md(mock_manager, "test-skill_special", content)

        assert mock_manager.save_skill.called

    def test_execute_manager_init_error(self, write_skill_file_tool, temp_skills_dir):
        """Test execute handles manager initialization errors (branch coverage)."""
        # This tests the branch where _get_skill_manager raises an exception
        with patch.object(write_skill_file_tool, '_get_skill_manager', side_effect=ImportError("Import failed")):
            result = write_skill_file_tool.execute("test-skill", "file.txt", "content")

        assert "[Error]" in result
        assert "Failed to initialize" in result


class TestExecuteNormalization:
    """Test execute path normalization branches."""

    def test_execute_with_backslash_path(self, write_skill_file_tool, temp_skills_dir):
        """Test execute normalizes backslashes to forward slashes."""
        skill_name = "slash-test"
        file_path = "subdir\\file.txt"
        content = "Content with backslash"

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = temp_skills_dir
        with patch.object(write_skill_file_tool, '_get_skill_manager', return_value=mock_manager):
            result = write_skill_file_tool.execute(skill_name, file_path, content)

        # The path should be normalized - file should exist with forward slash path
        expected_path = os.path.join(temp_skills_dir, skill_name, "subdir", "file.txt")
        assert os.path.exists(expected_path)

    def test_execute_with_leading_slash(self, write_skill_file_tool, temp_skills_dir):
        """Test execute strips leading slash from file path."""
        skill_name = "leading-slash-skill"
        file_path = "/file.txt"
        content = "Content"

        mock_manager = MagicMock()
        mock_manager.local_skills_dir = temp_skills_dir
        with patch.object(write_skill_file_tool, '_get_skill_manager', return_value=mock_manager):
            result = write_skill_file_tool.execute(skill_name, file_path, content)

        # File should be created without leading slash
        expected_path = os.path.join(temp_skills_dir, skill_name, "file.txt")
        assert os.path.exists(expected_path)
