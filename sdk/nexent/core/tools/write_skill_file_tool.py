"""Skill file writing tool."""
import logging
import os
from typing import Optional

from smolagents.tools import Tool

logger = logging.getLogger(__name__)


class WriteSkillFileTool(Tool):
    """Tool for writing skill files to local storage."""

    name = "write_skill_file"
    description = (
        "Edit an installed tenant-scoped skill file. This does not write to the current "
        "run workspace or outputs directory."
    )
    inputs = {
        "skill_name": {"type": "string", "description": "Name of the target skill."},
        "file_path": {"type": "string", "description": "Path relative to the skill root."},
        "content": {"type": "string", "description": "Content to write."},
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
        file_path: str,
        content: str,
    ) -> str:
        """Write a file to a skill directory in local storage.

        Args:
            skill_name: Name of the skill (e.g., "code-reviewer").
                If empty, writes directly to local_skills_dir.
            file_path: Relative path within the skill directory. Use forward slashes.
                Examples: "SKILL.md", "scripts/analyze.py", "examples.md"
            content: File content to write

        Returns:
            Success or error message
        """
        if not file_path:
            return "[Error] file_path is required"

        if not skill_name or not isinstance(skill_name, str) or not skill_name.strip():
            return "[Error] skill_name is required"

        normalized_path = file_path.replace("\\", "/").lstrip("/")

        try:
            manager = self._get_skill_manager()
        except Exception as e:
            return f"[Error] Failed to initialize skill manager: {e}"

        try:
            if normalized_path.lower() == "skill.md":
                return self._write_skill_md(manager, skill_name, content)
            return self._write_arbitrary_file(manager, skill_name, normalized_path, content)
        except Exception as e:
            logger.error(f"Failed to write skill file: {e}")
            return f"[Error] Failed to write file: {type(e).__name__}: {str(e)}"

    def forward(self, skill_name: str, file_path: str, content: str) -> str:
        """Write a tenant-scoped skill file."""
        return self.execute(skill_name, file_path, content)

    def _write_skill_md(self, manager, skill_name: str, content: str) -> str:
        """Write SKILL.md using SkillManager.save_skill().

        Args:
            manager: SkillManager instance
            skill_name: Name of the skill
            content: SKILL.md content

        Returns:
            Success or error message
        """
        try:
            from nexent.skills.skill_loader import SkillLoader
            skill_data = SkillLoader.parse(content)
            skill_data["name"] = skill_name
            skill_data["content"] = content
            manager.save_skill(skill_data, tenant_id=self.tenant_id)
            return f"Successfully wrote SKILL.md for skill '{skill_name}'"
        except ValueError as e:
            return f"[Error] Invalid SKILL.md format: {e}"
        except Exception as e:
            return f"[Error] Failed to write SKILL.md: {e}"

    def _write_arbitrary_file(
        self,
        manager,
        skill_name: str,
        relative_path: str,
        content: str,
    ) -> str:
        """Write an arbitrary file through SkillManager's validated API."""
        manager.write_skill_file(
            skill_name,
            relative_path,
            content,
            tenant_id=self.tenant_id,
        )
        return f"Successfully wrote '{relative_path}' for skill '{skill_name}'"


def _uncached_write_skill_file_tool(
    local_skills_dir: Optional[str] = None,
    agent_id: Optional[int] = None,
    tenant_id: Optional[str] = None,
    version_no: int = 0,
) -> WriteSkillFileTool:
    """Get or create the write skill file tool instance.

    Args:
        local_skills_dir: Path to local skills storage.
        agent_id: Agent ID for filtering available skills in error messages.
        tenant_id: Tenant ID for filtering available skills in error messages.
        version_no: Version number for filtering available skills.

    Returns:
        Tool instance cached by tenant_id for tenant isolation.
    """
    return WriteSkillFileTool(local_skills_dir, agent_id, tenant_id, version_no)


def _write_skill_file_without_context(skill_name: str, file_path: str, content: str) -> str:
    """Write a file to a tenant-scoped skill directory."""
    tool_instance = _uncached_write_skill_file_tool()
    return tool_instance.execute(skill_name, file_path, content)
