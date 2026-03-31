"""Skill script execution tool."""
import logging
from typing import Any, Dict, Optional
from smolagents import tool

logger = logging.getLogger(__name__)


class RunSkillScriptTool:
    """Tool for executing skill scripts."""

    def __init__(
        self,
        local_skills_dir: Optional[str] = None,
        agent_id: Optional[int] = None,
        tenant_id: Optional[str] = None,
        version_no: int = 0,
    ):
        """Initialize the tool with local skills directory and agent context.

        Args:
            local_skills_dir: Path to local skills storage.
            agent_id: Agent ID for filtering available skills in error messages.
            tenant_id: Tenant ID for filtering available skills in error messages.
            version_no: Version number for filtering available skills.
        """
        self.skill_manager = None
        self.local_skills_dir = local_skills_dir
        self.agent_id = agent_id
        self.tenant_id = tenant_id
        self.version_no = version_no

    def _get_skill_manager(self):
        """Lazy load skill manager."""
        if self.skill_manager is None:
            from nexent.skills import SkillManager
            self.skill_manager = SkillManager(
                self.local_skills_dir,
                agent_id=self.agent_id,
                tenant_id=self.tenant_id,
                version_no=self.version_no,
            )
        return self.skill_manager

    def execute(
        self,
        skill_name: str,
        script_path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Execute a skill script with given parameters.

        Args:
            skill_name: Name of the skill containing the script
            script_path: Path to script relative to skill directory (e.g., "scripts/analyze.py")
            params: Parameters to pass to the script

        Returns:
            Script execution result as string
        """
        from nexent.skills.skill_manager import SkillNotFoundError, SkillScriptNotFoundError

        try:
            manager = self._get_skill_manager()
            result = manager.run_skill_script(
                skill_name,
                script_path,
                params or {},
                agent_id=self.agent_id,
                tenant_id=self.tenant_id,
                version_no=self.version_no,
            )
            return str(result)
        except SkillNotFoundError as e:
            logger.error(f"Skill not found: {skill_name} - {e.message}")
            return f"[SkillNotFoundError] {e.message}"
        except SkillScriptNotFoundError as e:
            logger.error(f"Script not found in skill '{skill_name}': {script_path} - {e.message}")
            return f"[ScriptNotFoundError] {e.message}"
        except FileNotFoundError as e:
            logger.error(f"Script file not found: {e}")
            return f"[FileNotFoundError] Script file not found: {e}"
        except TimeoutError as e:
            logger.error(f"Script execution timed out: {e}")
            return f"[TimeoutError] Script execution timed out: {e}"
        except Exception as e:
            logger.error(f"Failed to execute skill script: {e}")
            return f"[UnexpectedError] Failed to execute skill script: {type(e).__name__}: {str(e)}"


# Global instance for tool execution
_skill_script_tool = None


def get_run_skill_script_tool(
    local_skills_dir: Optional[str] = None,
    agent_id: Optional[int] = None,
    tenant_id: Optional[str] = None,
    version_no: int = 0,
) -> RunSkillScriptTool:
    """Get or create the skill script tool instance.

    Args:
        local_skills_dir: Path to local skills storage.
        agent_id: Agent ID for filtering available skills in error messages.
        tenant_id: Tenant ID for filtering available skills in error messages.
        version_no: Version number for filtering available skills.
    """
    global _skill_script_tool
    if _skill_script_tool is None:
        _skill_script_tool = RunSkillScriptTool(local_skills_dir, agent_id, tenant_id, version_no)
    return _skill_script_tool


@tool
def run_skill_script(skill_name: str, script_path: str, params: Optional[Dict[str, Any]] = None) -> str:
    """Execute a skill script with given parameters.

    This tool runs Python or shell scripts that are part of a skill.
    Scripts must be declared in the skill content using <use_script path="..." /> tags.

    Args:
        skill_name: Name of the skill containing the script (e.g., "code-reviewer")
        script_path: Path to the script relative to skill directory (e.g., "scripts/analyze.py")
        params: Optional dictionary of parameters to pass to the script as command-line arguments.
            Examples:
            - {"--name": "test", "--wait": True} -> passes --name test --wait
            - {"--flag": True} -> passes --flag (boolean flags)
            - {"--names": ["vm1", "vm2"]} -> passes --names vm1 vm2
            - {"--cpu": 4} -> passes --cpu 4

    Returns:
        Script execution result as string
    """
    tool_instance = get_run_skill_script_tool()
    return tool_instance.execute(skill_name, script_path, params)
