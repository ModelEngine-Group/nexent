"""Skill config reading tool."""
import logging
import os
from typing import Any, Dict, Optional

import yaml
from smolagents import tool

logger = logging.getLogger(__name__)


class ReadSkillConfigTool:
    """Tool for reading the config.yaml file of a skill directory."""

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
        self.local_skills_dir = local_skills_dir
        self.agent_id = agent_id
        self.tenant_id = tenant_id
        self.version_no = version_no

    def execute(self, skill_name: str) -> str:
        """Read the config.yaml file from a skill directory.

        Args:
            skill_name: Name of the skill (e.g., "simple-skill-creator")

        Returns:
            JSON-serialized dict of the config file, or an error message.
        """
        if not skill_name:
            return "[Error] skill_name is required"

        if self.local_skills_dir is None:
            return "[Error] local_skills_dir is not configured"

        skill_dir = os.path.join(self.local_skills_dir, skill_name)
        if not os.path.isdir(skill_dir):
            return f"[Error] Skill directory not found: {skill_name}"

        config_path = os.path.join(skill_dir, "config.yaml")
        if not os.path.isfile(config_path):
            return f"[Error] config.yaml not found in skill: {skill_name}"

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                raw_config: Any = yaml.safe_load(f)

            if raw_config is None:
                return "{}"

            if not isinstance(raw_config, dict):
                return f"[Error] config.yaml must contain a YAML dictionary, got {type(raw_config).__name__}"

            import json
            return json.dumps(raw_config, ensure_ascii=False, indent=2)
        except yaml.YAMLError as e:
            return f"[Error] Failed to parse config.yaml: {e}"
        except Exception as e:
            return f"[Error] Failed to read config.yaml: {e}"


_global_tool_instance: Optional[ReadSkillConfigTool] = None


def get_read_skill_config_tool(
    local_skills_dir: Optional[str] = None,
    agent_id: Optional[int] = None,
    tenant_id: Optional[str] = None,
    version_no: int = 0,
) -> ReadSkillConfigTool:
    """Get or create the read skill config tool instance.

    Args:
        local_skills_dir: Path to local skills storage.
        agent_id: Agent ID for filtering available skills in error messages.
        tenant_id: Tenant ID for filtering available skills in error messages.
        version_no: Version number for filtering available skills.
    """
    global _global_tool_instance
    if _global_tool_instance is None:
        _global_tool_instance = ReadSkillConfigTool(
            local_skills_dir,
            agent_id=agent_id,
            tenant_id=tenant_id,
            version_no=version_no,
        )
    return _global_tool_instance


@tool
def read_skill_config(skill_name: str) -> str:
    """Read the config.yaml file from a skill directory.

    Use this tool to read configuration variables (such as temporary file paths)
    needed for skill creation workflows.

    Args:
        skill_name: Name of the skill whose config.yaml to read (e.g., "simple-skill-creator")

    Returns:
        JSON string containing the parsed config.yaml contents as a dictionary.

    Examples:
        # Read the config for simple-skill-creator to get temp_skill path
        read_skill_config("simple-skill-creator")
        # Returns: {"path": {"temp_skill": "/mnt/nexent/skills/tmp/"}}
    """
    tool_instance = get_read_skill_config_tool()
    return tool_instance.execute(skill_name)
