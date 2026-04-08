"""Skill markdown reading tool."""
import logging
import os
import re
from typing import Optional, Tuple
from smolagents import tool

logger = logging.getLogger(__name__)


class ReadSkillMdTool:
    """Tool for reading skill markdown files."""

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

    def _strip_frontmatter(self, content: str) -> str:
        """Strip YAML frontmatter from markdown content.

        Args:
            content: Raw file content

        Returns:
            Content with frontmatter removed
        """
        pattern = r'^---\s*\n.*?\n---\s*\n'
        return re.sub(pattern, '', content, count=1, flags=re.DOTALL)

    def _read_skill_file(self, skill_dir: str, file_path: str) -> Tuple[str, bool]:
        """Read a file from skill directory.

        Args:
            skill_dir: Root directory of the skill
            file_path: Relative path to the file

        Returns:
            Tuple of (file content, success flag)
        """
        # Handle file_path with or without .md extension
        possible_paths = [
            file_path,
            file_path + ".md",
            file_path.lstrip("/"),
            file_path.lstrip("/") + ".md"
        ]

        for path in possible_paths:
            full_path = os.path.join(skill_dir, path)
            if os.path.exists(full_path):
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    # Strip frontmatter if it's a markdown file
                    if full_path.endswith('.md'):
                        content = self._strip_frontmatter(content)
                    return content, True
                except Exception as e:
                    logger.warning(f"Failed to read file {path}: {e}")
                    continue

        return f"File not found: {file_path}", False

    def execute(self, skill_name: str, *additional_files: str) -> str:
        """Read skill markdown files.

        Args:
            skill_name: Name of the skill. If empty, reads directly from local_skills_dir.
            *additional_files: Optional additional files to read. If skill_name is empty,
                this is treated as the file path directly. If skill_name is non-empty:
                - If empty, reads SKILL.md by default.
                - If non-empty, only reads specified files (SKILL.md is NOT read by default
                unless explicitly included in the list).

        Returns:
            Combined markdown content
        """
        try:
            manager = self._get_skill_manager()

            # If skill_name is empty, read directly from local_skills_dir
            if not skill_name:
                return self._read_direct_file(additional_files)

            skill = manager.load_skill(skill_name)

            if not skill:
                return f"Skill not found: {skill_name}"

            # Get skill directory (local path)
            local_path = os.path.join(manager.local_skills_dir, skill_name)
            if not os.path.exists(local_path):
                return f"Skill directory not found: {skill_name}"

            result_parts = []

            # If no additional_files specified, read SKILL.md by default
            if not additional_files:
                skill_md_content, found = self._read_skill_file(local_path, "SKILL.md")
                if not found:
                    return f"SKILL.md not found in skill: {skill_name}\n{skill_md_content}"
                result_parts.append(skill_md_content)
            else:
                # Additional files provided - only read those files, not SKILL.md by default
                for file_path in additional_files:
                    file_content, found = self._read_skill_file(local_path, file_path)
                    if found:
                        result_parts.append(f"\n\n---\n\n## {file_path}\n\n")
                        result_parts.append(file_content)
                    else:
                        result_parts.append(f"\n\n[Warning: {file_path} not found]\n")

            return ''.join(result_parts)

        except Exception as e:
            logger.error(f"Failed to read skill markdown: {e}")
            return f"Error reading skill: {str(e)}"

    def _read_direct_file(self, path_parts: tuple) -> str:
        """Read a file directly from local_skills_dir.

        Args:
            path_parts: Tuple of path components. If empty, reads SKILL.md from root.

        Returns:
            File content or error message
        """
        if not self.local_skills_dir:
            return "[Error] local_skills_dir is not configured"

        if not path_parts:
            # No path specified, try to read SKILL.md from root
            file_path = "SKILL.md"
        else:
            file_path = "/".join(path_parts)

        full_path = os.path.join(self.local_skills_dir, file_path)
        if not os.path.exists(full_path):
            return f"File not found: {file_path}"

        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            # Strip frontmatter if it's a markdown file
            if full_path.endswith('.md'):
                content = self._strip_frontmatter(content)
            return content
        except Exception as e:
            logger.error(f"Failed to read file {full_path}: {e}")
            return f"[Error] Failed to read '{file_path}': {e}"


# Global instance for tool execution
_skill_md_tool = None


def get_read_skill_md_tool(
    local_skills_dir: Optional[str] = None,
    agent_id: Optional[int] = None,
    tenant_id: Optional[str] = None,
    version_no: int = 0,
) -> ReadSkillMdTool:
    """Get or create the skill md tool instance.

    Args:
        local_skills_dir: Path to local skills storage.
        agent_id: Agent ID for filtering available skills in error messages.
        tenant_id: Tenant ID for filtering available skills in error messages.
        version_no: Version number for filtering available skills.
    """
    global _skill_md_tool
    if _skill_md_tool is None:
        _skill_md_tool = ReadSkillMdTool(local_skills_dir, agent_id, tenant_id, version_no)
    return _skill_md_tool


@tool
def read_skill_md(skill_name: str, additional_files: Optional[list[str]] = None) -> str:
    """Read skill files for execution guidance.

    Reads skill files from the skill root directory. Behavior depends on whether
    additional_files is provided:

    - If skill_name is empty: reads directly from local_skills_dir root.
      additional_files is treated as the file path. If empty, reads SKILL.md from root.
    - If skill_name is non-empty and additional_files is empty: reads SKILL.md by default
    - If skill_name is non-empty and additional_files is provided: only reads the specified
      files (SKILL.md is NOT included by default unless explicitly listed)

    Use this tool to load the execution guide for a skill when you need to understand
    how to handle a specific task that matches the skill's purpose.

    Args:
        skill_name: Name of the skill (e.g., "code-reviewer"). If empty, reads directly
            from local_skills_dir root.
        additional_files: Optional list of specific files to read. When provided, only
            reads these files (SKILL.md is not automatically included). Examples:
            - ["examples.md"] - reads only examples.md
            - ["SKILL.md", "examples.md"] - reads both files
            - ["reference/api_doc"] - reads specific reference file

    Returns:
        Combined markdown content from the requested files

    Examples:
        # Default: reads SKILL.md
        read_skill_md("code-reviewer")

        # Only reads specified files (SKILL.md NOT included by default)
        read_skill_md("code-reviewer", ["examples.md"])
        read_skill_md("code-reviewer", ["SKILL.md", "examples.md"])

        # Read directly from local_skills_dir (skill_name is empty)
        read_skill_md("")  # reads SKILL.md from root
        read_skill_md("", ["my-file.txt"])  # reads my-file.txt from root
    """
    tool_instance = get_read_skill_md_tool()
    files = additional_files or []
    return tool_instance.execute(skill_name, *files)
