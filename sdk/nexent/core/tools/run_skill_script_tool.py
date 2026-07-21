"""Skill script execution tool."""
import logging
from typing import Optional

from smolagents.tools import Tool

logger = logging.getLogger(__name__)


class RunSkillScriptTool(Tool):
    """Tool for executing skill scripts."""

    name = "run_skill_script"
    description = "Execute a Python or shell script that belongs to an enabled skill."
    inputs = {
        "skill_name": {"type": "string", "description": "Name of the skill containing the script."},
        "script_path": {"type": "string", "description": "Path to the script relative to the skill root."},
        "params": {
            "type": "string",
            "description": "Optional raw command-line arguments for the script.",
            "nullable": True,
        },
    }
    output_type = "string"

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
        super().__init__()
        self.skill_manager = None
        self.local_skills_dir = local_skills_dir
        self.agent_id = agent_id
        self.tenant_id = tenant_id
        self.version_no = version_no

    def _get_skill_manager(self):
        """Lazy load skill manager."""
        if self.skill_manager is None:
            from nexent.skills import SkillManager
            self.skill_manager = SkillManager(self.local_skills_dir)
        return self.skill_manager

    def execute(
        self,
        skill_name: str,
        script_path: str,
        params: Optional[str] = None,
    ) -> str:
        """Execute a skill script with given parameters.

        ``script_path`` is always resolved relative to the skill's root
        directory (``<local_skills_dir>/<skill_name>``), regardless of the
        caller's working directory. The path may be supplied in any of the
        forms an LLM might emit after reading a SKILL.md body - bare
        relative paths (``scripts/analyze.py``), ``./`` prefixed paths, or
        values extracted from inline backticks/fenced code blocks (with or
        without surrounding quotes). If the script cannot be located the
        returned error message lists the available scripts under the skill
        to help diagnose the mistake.

        Args:
            skill_name: Name of the skill containing the script
            script_path: Path to script relative to skill directory
                (e.g. ``scripts/analyze.py``).
            params: Parameters to pass to the script as a raw string.
                The string is appended directly to the command line.

        Returns:
            Script execution result as string
        """
        from nexent.skills.skill_manager import SkillNotFoundError, SkillScriptNotFoundError

        try:
            manager = self._get_skill_manager()
            result = manager.run_skill_script(
                skill_name,
                script_path,
                params,
                tenant_id=self.tenant_id,
            )
            return str(result)
        except SkillNotFoundError as e:
            message = getattr(e, "message", str(e))
            logger.error(f"Skill not found: {skill_name} - {message}")
            return f"[SkillNotFoundError] {message}"
        except SkillScriptNotFoundError as e:
            message = getattr(e, "message", str(e))
            logger.error(f"Script not found in skill '{skill_name}': {script_path} - {message}")
            return f"[ScriptNotFoundError] {message}"
        except FileNotFoundError as e:
            logger.error(f"Script file not found: {e}")
            return f"[FileNotFoundError] Script file not found: {e}"
        except TimeoutError as e:
            logger.error(f"Script execution timed out: {e}")
            return f"[TimeoutError] Script execution timed out: {e}"
        except Exception as e:
            logger.error(f"Failed to execute skill script: {e}")
            return f"[UnexpectedError] Failed to execute skill script: {type(e).__name__}: {str(e)}"

    def forward(
        self,
        skill_name: str,
        script_path: str,
        params: Optional[str] = None,
    ) -> str:
        """Execute a tenant-scoped skill script."""
        return self.execute(skill_name, script_path, params)


def _uncached_run_skill_script_tool(
    local_skills_dir: Optional[str] = None,
    agent_id: Optional[int] = None,
    tenant_id: Optional[str] = None,
    version_no: int = 0,
) -> RunSkillScriptTool:
    """Construct an uncached tool for internal use and isolated tests."""
    return RunSkillScriptTool(local_skills_dir, agent_id, tenant_id, version_no)


def _run_skill_script_without_context(
    skill_name: str, script_path: str, params: Optional[str] = None
) -> str:
    """Legacy internal wrapper; tenant-aware agents instantiate the class directly."""
    return _uncached_run_skill_script_tool().execute(skill_name, script_path, params)
