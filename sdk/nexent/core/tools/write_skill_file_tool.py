"""Skill file writing tool."""
import logging
import os
from typing import Optional

from smolagents.tools import Tool

logger = logging.getLogger(__name__)


class WriteSkillFileTool(Tool):
    """Tool for writing skill files to local storage."""

    name = "write_skill_file"
    description = "Write content to a file within a tenant-scoped skill directory."
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

        normalized_path = file_path.replace("\\", "/")
        if "/" in normalized_path or normalized_path != file_path.lstrip("/"):
            pass
        normalized_path = normalized_path.lstrip("/")

        # If skill_name is empty, write directly to local_skills_dir
        if not skill_name:
            return self._write_direct_file(normalized_path, content)

        try:
            manager = self._get_skill_manager()
        except Exception as e:
            return f"[Error] Failed to initialize skill manager: {e}"

        try:
            if normalized_path.lower() == "skill.md":
                return self._write_skill_md(manager, skill_name, content)
            else:
                return self._write_arbitrary_file(manager, skill_name, normalized_path, content)
        except Exception as e:
            logger.error(f"Failed to write skill file: {e}")
            return f"[Error] Failed to write file: {type(e).__name__}: {str(e)}"

    def forward(self, skill_name: str, file_path: str, content: str) -> str:
        """Write a tenant-scoped skill file."""
        return self.execute(skill_name, file_path, content)

    def _write_direct_file(self, relative_path: str, content: str) -> str:
        """Write a file directly to local_skills_dir.

        Args:
            relative_path: Path relative to local_skills_dir
            content: File content

        Returns:
            Success or error message
        """
        manager = self._get_skill_manager()
        file_path = os.path.join(
            manager.resolve_tenant_dir(tenant_id=self.tenant_id),
            *relative_path.split("/"),
        )
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully wrote '{relative_path}' to local_skills_dir"
        except Exception as e:
            return f"[Error] Failed to write '{relative_path}': {e}"

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
        """Write an arbitrary file to the skill directory.

        Args:
            manager: SkillManager instance
            skill_name: Name of the skill
            relative_path: Path relative to skill root
            content: File content

        Returns:
            Success or error message
        """
        skill_dir = manager.resolve_skill_dir(skill_name, tenant_id=self.tenant_id)
        os.makedirs(skill_dir, exist_ok=True)

        file_path = os.path.join(skill_dir, *relative_path.split("/"))
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully wrote '{relative_path}' for skill '{skill_name}'"
        except Exception as e:
            return f"[Error] Failed to write '{relative_path}': {e}"


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
    """Write a file to a skill directory in local storage.

    Use this tool when you need to create or update skill files (SKILL.md,
    scripts, examples, etc.). The skill root directory is determined by the
    agent's local_skills_dir configuration.

    Args:
        skill_name: Name of the skill (e.g., "code-reviewer", "my-new-skill").
            If empty, writes directly to local_skills_dir.
        file_path: Relative path within the skill directory. Use forward slashes.
            - "SKILL.md" for the main skill file
            - "scripts/analyze.py" for Python scripts
            - "scripts/run.sh" for shell scripts
            - "examples.md", "reference.md" for supporting documentation
        content: The full file content to write

    Returns:
        Success or error message

    Examples:
        # Write the main SKILL.md
        write_skill_file("code-reviewer", "SKILL.md", "---\\nname: code-reviewer\\n...")

        # Write a Python script
        write_skill_file("code-reviewer", "scripts/analyze.py", "import sys\\n...")

        # Write supporting documentation
        write_skill_file("code-reviewer", "examples.md", "# Examples\\n...")

        # Write directly to local_skills_dir (when skill_name is empty)
        write_skill_file("", "my-file.txt", "file content")
    """
    tool_instance = _uncached_write_skill_file_tool()
    return tool_instance.execute(skill_name, file_path, content)
