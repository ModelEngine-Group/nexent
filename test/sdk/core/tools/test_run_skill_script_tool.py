"""
Unit tests for nexent.core.tools.run_skill_script_tool module.

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
_mock_nexent_skills_skill_manager = types.ModuleType("nexent.skills.skill_manager")


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
    "nexent.skills.skill_manager": _mock_nexent_skills_skill_manager,
}
sys.modules.update(_MODULE_MOCKS)


# -- Mock SkillManager for nexent.skills.skill_manager -------------------------
class MockSkillNotFoundError(Exception):
    """Mock exception for skill not found."""
    def __init__(self, message=""):
        self.message = message
        super().__init__(self.message)


class MockSkillScriptNotFoundError(Exception):
    """Mock exception for script not found."""
    def __init__(self, message=""):
        self.message = message
        super().__init__(self.message)


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


_mock_nexent_skills_skill_manager.SkillManager = MockSkillManager
_mock_nexent_skills_skill_manager.SkillNotFoundError = MockSkillNotFoundError
_mock_nexent_skills_skill_manager.SkillScriptNotFoundError = MockSkillScriptNotFoundError

# Also set on nexent.skills for import compatibility
_mock_nexent_skills.SkillManager = MockSkillManager


# -- Now import the module under test ---------------------------------------
from sdk.nexent.core.tools.run_skill_script_tool import (
    RunSkillScriptTool,
    _uncached_run_skill_script_tool,
    _run_skill_script_without_context,
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
def skill_with_script(temp_skills_dir):
    """Create a sample skill with a Python script."""
    skill_name = "script-skill"
    skill_dir = os.path.join(temp_skills_dir, skill_name)
    scripts_dir = os.path.join(skill_dir, "scripts")
    os.makedirs(scripts_dir)

    # Create SKILL.md
    skill_content = """---
name: script-skill
description: A skill with scripts
---
# Content
"""
    with open(os.path.join(skill_dir, "SKILL.md"), 'w', encoding='utf-8') as f:
        f.write(skill_content)

    # Create a Python script
    script_content = '''"""Simple test script."""
import sys

def main():
    print("Hello from script")
    return 0

if __name__ == "__main__":
    sys.exit(main())
'''
    script_path = os.path.join(scripts_dir, "analyze.py")
    with open(script_path, 'w', encoding='utf-8') as f:
        f.write(script_content)

    return skill_dir, skill_name, "scripts/analyze.py"


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

class TestRunSkillScriptToolInit:
    """Test RunSkillScriptTool initialization."""

    def test_init_with_all_params(self):
        """Test initialization with all parameters."""
        tool = RunSkillScriptTool(
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
        tool = RunSkillScriptTool()
        assert tool.local_skills_dir is None
        assert tool.agent_id is None
        assert tool.tenant_id is None
        assert tool.version_no == 0
        assert tool.skill_manager is None


class TestGetSkillManager:
    """Test _get_skill_manager lazy loading."""

    def test_lazy_load_creates_manager(self, temp_skills_dir):
        """Test that _get_skill_manager creates manager on first call."""
        tool = RunSkillScriptTool(local_skills_dir=temp_skills_dir)
        assert tool.skill_manager is None
        manager = tool._get_skill_manager()
        assert manager is not None
        # Check that manager has the expected attributes instead of using isinstance
        assert hasattr(manager, 'resolve_skill_dir')
        assert hasattr(manager, 'run_skill_script')

    def test_lazy_load_reuses_manager(self, temp_skills_dir):
        """Test that _get_skill_manager reuses existing manager."""
        tool = RunSkillScriptTool(local_skills_dir=temp_skills_dir)
        manager1 = tool._get_skill_manager()
        manager2 = tool._get_skill_manager()
        assert manager1 is manager2


class TestExecute:
    """Test execute method."""

    def test_execute_calls_skill_manager(self, temp_skills_dir):
        """Test execute calls skill manager's run_skill_script."""
        tool = RunSkillScriptTool(local_skills_dir=temp_skills_dir)
        mock_manager = MagicMock()
        mock_manager.run_skill_script.return_value = "Script output"
        tool.skill_manager = mock_manager

        result = tool.execute("test-skill", "scripts/test.py")

        assert mock_manager.run_skill_script.called
        call_args = mock_manager.run_skill_script.call_args
        assert call_args[0][0] == "test-skill"
        assert call_args[0][1] == "scripts/test.py"

    def test_execute_with_params(self, temp_skills_dir):
        """Test execute passes parameters to skill manager."""
        tool = RunSkillScriptTool(
            local_skills_dir=temp_skills_dir,
            agent_id=1,
            tenant_id="test-tenant",
            version_no=0
        )
        mock_manager = MagicMock()
        mock_manager.run_skill_script.return_value = "Result"
        tool.skill_manager = mock_manager

        params = "--name test --count 5"
        result = tool.execute("test-skill", "script.py", params)

        call_args = mock_manager.run_skill_script.call_args
        assert call_args[0][2] == params

    def test_execute_handles_skill_not_found(self, temp_skills_dir):
        """Test execute handles SkillNotFoundError."""
        tool = RunSkillScriptTool(local_skills_dir=temp_skills_dir)
        mock_manager = MagicMock()
        mock_manager.run_skill_script.side_effect = MockSkillNotFoundError("Skill 'test-skill' not found.")
        tool.skill_manager = mock_manager

        result = tool.execute("test-skill", "script.py")

        assert "[SkillNotFoundError]" in result
        assert "test-skill" in result

    def test_execute_handles_script_not_found(self, temp_skills_dir):
        """Test execute handles SkillScriptNotFoundError."""
        tool = RunSkillScriptTool(local_skills_dir=temp_skills_dir)
        mock_manager = MagicMock()
        mock_manager.run_skill_script.side_effect = MockSkillScriptNotFoundError("Script 'script.py' not found.")
        tool.skill_manager = mock_manager

        result = tool.execute("test-skill", "script.py")

        assert "[ScriptNotFoundError]" in result
        assert "script.py" in result

    def test_execute_handles_file_not_found(self, temp_skills_dir):
        """Test execute handles FileNotFoundError."""
        tool = RunSkillScriptTool(local_skills_dir=temp_skills_dir)
        mock_manager = MagicMock()
        mock_manager.run_skill_script.side_effect = FileNotFoundError("File not found")
        tool.skill_manager = mock_manager

        result = tool.execute("test-skill", "script.py")

        assert "[FileNotFoundError]" in result
        assert "File not found" in result

    def test_execute_handles_timeout(self, temp_skills_dir):
        """Test execute handles TimeoutError."""
        tool = RunSkillScriptTool(local_skills_dir=temp_skills_dir)
        mock_manager = MagicMock()
        mock_manager.run_skill_script.side_effect = TimeoutError("Script timed out")
        tool.skill_manager = mock_manager

        result = tool.execute("test-skill", "script.py")

        assert "[TimeoutError]" in result
        assert "timed out" in result.lower()

    def test_execute_handles_unexpected_error(self, temp_skills_dir):
        """Test execute handles unexpected exceptions."""
        tool = RunSkillScriptTool(local_skills_dir=temp_skills_dir)
        mock_manager = MagicMock()
        mock_manager.run_skill_script.side_effect = RuntimeError("Unexpected error")
        tool.skill_manager = mock_manager

        result = tool.execute("test-skill", "script.py")

        assert "[UnexpectedError]" in result
        assert "RuntimeError" in result
        assert "Unexpected error" in result

    def test_execute_converts_result_to_string(self, temp_skills_dir):
        """Test execute converts non-string results to string."""
        tool = RunSkillScriptTool(local_skills_dir=temp_skills_dir)
        mock_manager = MagicMock()
        mock_manager.run_skill_script.return_value = {"status": "ok", "data": [1, 2, 3]}
        tool.skill_manager = mock_manager

        result = tool.execute("test-skill", "script.py")

        assert isinstance(result, str)
        assert "status" in result
        assert "ok" in result

    def test_execute_with_none_params(self, temp_skills_dir):
        """Test execute handles None params correctly."""
        tool = RunSkillScriptTool(local_skills_dir=temp_skills_dir)
        mock_manager = MagicMock()
        mock_manager.run_skill_script.return_value = "OK"
        tool.skill_manager = mock_manager

        result = tool.execute("test-skill", "script.py", None)

        call_args = mock_manager.run_skill_script.call_args
        assert call_args[0][2] is None


class TestModuleFunctions:
    """Test module-level tool functions."""

    def test_uncached_run_skill_script_tool_creates_instance(self):
        """Test _uncached_run_skill_script_tool creates instance."""
        tool = _uncached_run_skill_script_tool("/path/to/skills", agent_id=1, tenant_id="t1")
        assert tool is not None
        assert isinstance(tool, RunSkillScriptTool)
        assert tool.local_skills_dir == "/path/to/skills"
        assert tool.agent_id == 1
        assert tool.tenant_id == "t1"

    def test_run_skill_script_without_context(self, temp_skills_dir):
        """Test _run_skill_script_without_context creates tool and executes."""
        # The function creates a tool with default local_skills_dir=None
        # which means the script will fail to find the skill
        result = _run_skill_script_without_context("test-skill", "script.py")
        # Should handle the error gracefully
        assert isinstance(result, str)

    def test_forward_delegates_to_execute(self, temp_skills_dir):
        """Test forward method delegates to execute."""
        tool = RunSkillScriptTool(local_skills_dir=temp_skills_dir)
        mock_manager = MagicMock()
        mock_manager.run_skill_script.return_value = "OK"
        tool.skill_manager = mock_manager

        result = tool.forward("test-skill", "script.py")
        assert mock_manager.run_skill_script.called
