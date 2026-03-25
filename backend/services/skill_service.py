"""Skill management service."""

import io
import logging
import os
from typing import Any, Dict, List, Optional, Union

from nexent.skills import SkillManager
from nexent.skills.skill_loader import SkillLoader
from consts.const import CONTAINER_SKILLS_PATH
from consts.exceptions import SkillException
from services.skill_repository import SkillRepository
from database import skill_db
from database.db_models import SkillInfo

logger = logging.getLogger(__name__)

_skill_manager: Optional[SkillManager] = None


def get_skill_manager() -> SkillManager:
    """Get or create the global SkillManager instance."""
    global _skill_manager
    if _skill_manager is None:
        _skill_manager = SkillManager(CONTAINER_SKILLS_PATH)
    return _skill_manager


class SkillService:
    """Skill management service for backend operations."""

    def __init__(self, skill_manager: Optional[SkillManager] = None):
        """Initialize SkillService.

        Args:
            skill_manager: Optional SkillManager instance, uses global if not provided
        """
        self.skill_manager = skill_manager or get_skill_manager()
        self.repository = SkillRepository()

    def list_skills(self, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all skills for tenant.

        Args:
            tenant_id: Tenant ID (reserved for future multi-tenant support)

        Returns:
            List of skill info dicts
        """
        try:
            return self.repository.list_skills()
        except Exception as e:
            logger.error(f"Error listing skills: {e}")
            raise SkillException(f"Failed to list skills: {str(e)}") from e

    def get_skill(self, skill_name: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get a specific skill.

        Args:
            skill_name: Name of the skill
            tenant_id: Tenant ID (reserved for future multi-tenant support)

        Returns:
            Skill dict or None if not found
        """
        try:
            return self.repository.get_skill_by_name(skill_name)
        except Exception as e:
            logger.error(f"Error getting skill {skill_name}: {e}")
            raise SkillException(f"Failed to get skill: {str(e)}") from e

    def get_skill_by_id(self, skill_id: int) -> Optional[Dict[str, Any]]:
        """Get a specific skill by ID.

        Args:
            skill_id: ID of the skill

        Returns:
            Skill dict or None if not found
        """
        try:
            return self.repository.get_skill_by_id(skill_id)
        except Exception as e:
            logger.error(f"Error getting skill by ID {skill_id}: {e}")
            raise SkillException(f"Failed to get skill: {str(e)}") from e

    def create_skill(
        self,
        skill_data: Dict[str, Any],
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new skill.

        Args:
            skill_data: Skill data including name, description, content, etc.
            tenant_id: Tenant ID (reserved for future multi-tenant support)
            user_id: User ID of the creator

        Returns:
            Created skill dict

        Raises:
            SkillException: If skill already exists locally or in database (409)
        """
        skill_name = skill_data.get("name")
        if not skill_name:
            raise SkillException("Skill name is required")

        # Check if skill already exists in database
        existing = self.repository.get_skill_by_name(skill_name)
        if existing:
            raise SkillException(f"Skill '{skill_name}' already exists")

        # Check if skill directory already exists locally
        local_dir = os.path.join(self.skill_manager.local_skills_dir, skill_name)
        if os.path.exists(local_dir):
            raise SkillException(f"Skill '{skill_name}' already exists locally")

        # Set created_by and updated_by if user_id is provided
        if user_id:
            skill_data["created_by"] = user_id
            skill_data["updated_by"] = user_id

        try:
            # Create database record first
            result = self.repository.create_skill(skill_data)

            # Create local skill file (SKILL.md)
            self.skill_manager.save_skill(skill_data)

            logger.info(f"Created skill '{skill_name}' with local files")
            return result
        except SkillException:
            raise
        except Exception as e:
            logger.error(f"Error creating skill: {e}")
            raise SkillException(f"Failed to create skill: {str(e)}") from e

    def create_skill_from_file(
        self,
        file_content: Union[bytes, str, io.BytesIO],
        skill_name: Optional[str] = None,
        file_type: str = "auto",
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a skill from file content.

        Supports two formats:
        1. Single SKILL.md file - extracts metadata and saves directly
        2. ZIP archive - extracts SKILL.md and all other files/scripts

        Args:
            file_content: File content as bytes, string, or BytesIO
            skill_name: Optional skill name (extracted from ZIP if not provided)
            file_type: File type hint - "md", "zip", or "auto" (detect)
            tenant_id: Tenant ID (reserved for future multi-tenant support)
            user_id: User ID of the creator

        Returns:
            Created skill dict
        """
        content_bytes: bytes
        if isinstance(file_content, str):
            content_bytes = file_content.encode("utf-8")
        elif isinstance(file_content, io.BytesIO):
            content_bytes = file_content.getvalue()
        else:
            content_bytes = file_content

        if file_type == "auto":
            if content_bytes.startswith(b"PK"):
                file_type = "zip"
            else:
                file_type = "md"

        if file_type == "zip":
            return self._create_skill_from_zip(content_bytes, skill_name, user_id, tenant_id)
        else:
            return self._create_skill_from_md(content_bytes, skill_name, user_id, tenant_id)

    def _create_skill_from_md(
        self,
        content_bytes: bytes,
        skill_name: Optional[str] = None,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create skill from SKILL.md content."""
        content_str = content_bytes.decode("utf-8")

        try:
            skill_data = SkillLoader.parse(content_str)
        except ValueError as e:
            raise SkillException(f"Invalid SKILL.md format: {e}")

        name = skill_name or skill_data.get("name")
        if not name:
            raise SkillException("Skill name is required")

        # Check if skill already exists in database
        existing = self.repository.get_skill_by_name(name)
        if existing:
            raise SkillException(f"Skill '{name}' already exists")

        # Convert allowed_tools (from SKILL.md) to tool_ids for database
        allowed_tools = skill_data.get("allowed_tools", [])
        tool_ids = []
        if allowed_tools:
            tool_ids = self.repository.get_tool_ids_by_names(allowed_tools, tenant_id)

        skill_dict = {
            "name": name,
            "description": skill_data.get("description", ""),
            "content": skill_data.get("content", ""),
            "tags": skill_data.get("tags", []),
            "source": "custom",
            "tool_ids": tool_ids,
            "allowed-tools": allowed_tools,  # Preserve for local file sync
        }

        # Set created_by and updated_by if user_id is provided
        if user_id:
            skill_dict["created_by"] = user_id
            skill_dict["updated_by"] = user_id

        result = self.repository.create_skill(skill_dict)

        # Write SKILL.md to local storage
        self.skill_manager.save_skill(skill_dict)

        return result

    def _create_skill_from_zip(
        self,
        zip_bytes: bytes,
        skill_name: Optional[str] = None,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create skill from ZIP archive (for file storage, content extracted from SKILL.md).

        Priority for skill_name:
        1. Parameter skill_name
        2. Root directory SKILL.md (top-level skill_name field)
        3. Subdirectory name containing SKILL.md
        """
        import zipfile

        zip_stream = io.BytesIO(zip_bytes)

        try:
            with zipfile.ZipFile(zip_stream, "r") as zf:
                file_list = zf.namelist()
        except zipfile.BadZipFile:
            raise SkillException("Invalid ZIP archive")

        skill_md_path: Optional[str] = None
        detected_skill_name: Optional[str] = None

        # First: Check for SKILL.md at root level
        for file_path in file_list:
            if file_path.endswith("/"):
                continue
            normalized_path = file_path.replace("\\", "/")
            parts = normalized_path.split("/")
            # Root level SKILL.md (only 1 part)
            if len(parts) == 1 and parts[0].lower() == "skill.md":
                skill_md_path = file_path
                break

        # Second: If not found at root, check subdirectory
        if not skill_md_path:
            for file_path in file_list:
                if file_path.endswith("/"):
                    continue
                normalized_path = file_path.replace("\\", "/")
                parts = normalized_path.split("/")
                if len(parts) >= 2 and parts[-1].lower() == "skill.md":
                    skill_md_path = file_path
                    detected_skill_name = parts[0]
                    break

        if not skill_md_path:
            raise SkillException("SKILL.md not found in ZIP archive")

        name = skill_name or detected_skill_name
        if not name:
            raise SkillException("Skill name is required")

        # Check if skill already exists in database
        existing = self.repository.get_skill_by_name(name)
        if existing:
            raise SkillException(f"Skill '{name}' already exists")

        with zipfile.ZipFile(zip_stream, "r") as zf:
            skill_content = zf.read(skill_md_path).decode("utf-8")

        try:
            skill_data = SkillLoader.parse(skill_content)
        except ValueError as e:
            raise SkillException(f"Invalid SKILL.md in ZIP: {e}")

        # If still no name, try to get from SKILL.md parsed data
        if not name:
            name = skill_data.get("name")

        if not name:
            raise SkillException("Skill name is required")

        # Convert allowed_tools (from SKILL.md) to tool_ids for database
        allowed_tools = skill_data.get("allowed_tools", [])
        tool_ids = []
        if allowed_tools:
            tool_ids = self.repository.get_tool_ids_by_names(allowed_tools, tenant_id)

        skill_dict = {
            "name": name,
            "description": skill_data.get("description", ""),
            "content": skill_data.get("content", ""),
            "tags": skill_data.get("tags", []),
            "source": "custom",
            "tool_ids": tool_ids,
            "allowed-tools": allowed_tools,  # Preserve for local file sync
        }

        # Set created_by and updated_by if user_id is provided
        if user_id:
            skill_dict["created_by"] = user_id
            skill_dict["updated_by"] = user_id

        result = self.repository.create_skill(skill_dict)

        # Save SKILL.md to local storage
        self.skill_manager.save_skill(skill_dict)

        self._upload_zip_files(zip_bytes, name, detected_skill_name)

        return result

    def _upload_zip_files(
        self,
        zip_bytes: bytes,
        skill_name: str,
        original_folder_name: Optional[str] = None
    ) -> None:
        """Extract ZIP files to local storage only.

        Args:
            zip_bytes: ZIP archive content
            skill_name: Target skill name (for local directory)
            original_folder_name: Original folder name in ZIP (if different from skill_name)
        """
        import zipfile

        zip_stream = io.BytesIO(zip_bytes)

        # Determine if folder renaming is needed
        needs_rename = (
            original_folder_name is not None
            and original_folder_name != skill_name
        )

        try:
            with zipfile.ZipFile(zip_stream, "r") as zf:
                file_list = zf.namelist()

                for file_path in file_list:
                    if file_path.endswith("/"):
                        continue

                    normalized_path = file_path.replace("\\", "/")
                    parts = normalized_path.split("/")

                    # Calculate target relative path
                    if needs_rename and len(parts) >= 2 and parts[0] == original_folder_name:
                        # Replace original folder name with skill_name
                        relative_path = parts[0].replace(original_folder_name, skill_name) + "/" + "/".join(parts[1:])
                    elif len(parts) >= 2:
                        relative_path = "/".join(parts[1:])
                    else:
                        relative_path = normalized_path

                    if not relative_path:
                        continue

                    file_data = zf.read(file_path)

                    local_dir = os.path.join(self.skill_manager.local_skills_dir, skill_name)
                    local_path = os.path.join(local_dir, relative_path)
                    os.makedirs(os.path.dirname(local_path), exist_ok=True)
                    with open(local_path, "wb") as f:
                        f.write(file_data)

            logger.info(f"Extracted skill files '{skill_name}' to local storage")
        except Exception as e:
            logger.warning(f"Failed to extract ZIP files: {e}")

    def update_skill_from_file(
        self,
        skill_name: str,
        file_content: Union[bytes, str, io.BytesIO],
        file_type: str = "auto",
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Update an existing skill from file content.

        Args:
            skill_name: Name of the skill to update
            file_content: File content as bytes, string, or BytesIO
            file_type: File type hint - "md", "zip", or "auto" (detect)
            tenant_id: Tenant ID (reserved for future multi-tenant support)
            user_id: User ID of the updater

        Returns:
            Updated skill dict
        """
        existing = self.repository.get_skill_by_name(skill_name)
        if not existing:
            raise SkillException(f"Skill not found: {skill_name}")

        content_bytes: bytes
        if isinstance(file_content, str):
            content_bytes = file_content.encode("utf-8")
        elif isinstance(file_content, io.BytesIO):
            content_bytes = file_content.getvalue()
        else:
            content_bytes = file_content

        if file_type == "auto":
            if content_bytes.startswith(b"PK"):
                file_type = "zip"
            else:
                file_type = "md"

        if file_type == "zip":
            return self._update_skill_from_zip(content_bytes, skill_name, user_id, tenant_id)
        else:
            return self._update_skill_from_md(content_bytes, skill_name, user_id, tenant_id)

    def _update_skill_from_md(
        self,
        content_bytes: bytes,
        skill_name: str,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Update skill from SKILL.md content."""
        content_str = content_bytes.decode("utf-8")

        try:
            skill_data = SkillLoader.parse(content_str)
        except ValueError as e:
            raise SkillException(f"Invalid SKILL.md format: {e}")

        # Get allowed-tools from parsed content and try to map to tool_ids
        allowed_tools = skill_data.get("allowed_tools", [])
        tool_ids = []
        if allowed_tools:
            tool_ids = self.repository.get_tool_ids_by_names(allowed_tools, tenant_id)

        skill_dict = {
            "description": skill_data.get("description", ""),
            "content": skill_data.get("content", ""),
            "tags": skill_data.get("tags", []),
            "tool_ids": tool_ids,
        }

        # Set updated_by if user_id is provided
        if user_id:
            skill_dict["updated_by"] = user_id

        result = self.repository.update_skill(skill_name, skill_dict)

        # Update local storage with new SKILL.md (preserve allowed-tools)
        skill_dict["name"] = skill_name
        skill_dict["allowed-tools"] = allowed_tools
        self.skill_manager.save_skill(skill_dict)

        return result

    def _update_skill_from_zip(
        self,
        zip_bytes: bytes,
        skill_name: str,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update skill from ZIP archive."""
        existing = self.repository.get_skill_by_name(skill_name)
        if not existing:
            raise SkillException(f"Skill not found: {skill_name}")

        import zipfile

        zip_stream = io.BytesIO(zip_bytes)

        skill_md_path = None
        original_folder_name = None

        with zipfile.ZipFile(zip_stream, "r") as zf:
            file_list = zf.namelist()

            for file_path in file_list:
                normalized_path = file_path.replace("\\", "/")
                if normalized_path.lower().endswith("skill.md"):
                    parts = normalized_path.split("/")
                    if len(parts) >= 2:
                        skill_md_path = file_path
                        original_folder_name = parts[0]
                        break

            skill_content = None
            if skill_md_path:
                skill_content = zf.read(skill_md_path).decode("utf-8")

        skill_dict = {}
        allowed_tools = []
        if skill_content:
            try:
                skill_data = SkillLoader.parse(skill_content)
                allowed_tools = skill_data.get("allowed_tools", [])
                # Try to map allowed_tools to tool_ids for database
                tool_ids = []
                if allowed_tools:
                    tool_ids = self.repository.get_tool_ids_by_names(allowed_tools, tenant_id)
                skill_dict = {
                    "description": skill_data.get("description", ""),
                    "content": skill_data.get("content", ""),
                    "tags": skill_data.get("tags", []),
                    "tool_ids": tool_ids,
                }
            except ValueError as e:
                logger.warning(f"Could not parse SKILL.md from ZIP: {e}")

        # Set updated_by if user_id is provided
        if user_id:
            skill_dict["updated_by"] = user_id

        result = self.repository.update_skill(skill_name, skill_dict)

        # Update SKILL.md in local storage (preserve allowed-tools)
        skill_dict["name"] = skill_name
        skill_dict["allowed-tools"] = allowed_tools
        self.skill_manager.save_skill(skill_dict)

        # Update other files in local storage
        self._upload_zip_files(zip_bytes, skill_name, original_folder_name)

        return result

    def update_skill(
        self,
        skill_name: str,
        skill_data: Dict[str, Any],
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Update an existing skill.

        Args:
            skill_name: Name of the skill to update
            skill_data: Updated skill data
            tenant_id: Tenant ID (reserved for future multi-tenant support)
            user_id: User ID of the updater

        Returns:
            Updated skill dict
        """
        # Set updated_by if user_id is provided
        if user_id:
            skill_data["updated_by"] = user_id

        try:
            existing = self.repository.get_skill_by_name(skill_name)
            if not existing:
                raise SkillException(f"Skill not found: {skill_name}")

            result = self.repository.update_skill(skill_name, skill_data)

            # Get tool names for SKILL.md allowed-tools field
            # Get tool names based on the updated skill (uses new tool_ids if provided)
            allowed_tools = self.repository.get_tool_names_by_skill_name(skill_name)

            # Update local storage with new skill data
            local_skill_dict = {
                "name": skill_name,
                "description": skill_data.get("description", existing.get("description", "")),
                "content": skill_data.get("content", existing.get("content", "")),
                "tags": skill_data.get("tags", existing.get("tags", [])),
                "allowed-tools": allowed_tools,
            }
            self.skill_manager.save_skill(local_skill_dict)

            return result
        except SkillException:
            raise
        except Exception as e:
            logger.error(f"Error updating skill {skill_name}: {e}")
            raise SkillException(f"Failed to update skill: {str(e)}") from e

    def delete_skill(
        self,
        skill_name: str,
        user_id: Optional[str] = None
    ) -> bool:
        """Delete a skill.

        Args:
            skill_name: Name of the skill to delete
            tenant_id: Tenant ID (reserved for future multi-tenant support)
            user_id: User ID of the user performing the delete

        Returns:
            True if deleted successfully
        """
        try:
            # Delete local skill files from filesystem
            skill_dir = os.path.join(self.skill_manager.local_skills_dir, skill_name)
            if os.path.exists(skill_dir):
                import shutil
                shutil.rmtree(skill_dir)
                logger.info(f"Deleted skill directory: {skill_dir}")

            # Delete from database (soft delete with updated_by)
            return self.repository.delete_skill(skill_name, updated_by=user_id)
        except Exception as e:
            logger.error(f"Error deleting skill {skill_name}: {e}")
            raise SkillException(f"Failed to delete skill: {str(e)}") from e


    def get_enabled_skills_for_agent(
        self,
        agent_id: int,
        tenant_id: str,
        version_no: int = 0
    ) -> List[Dict[str, Any]]:
        """Get enabled skills for a specific agent from SkillInstance table.

        Args:
            agent_id: Agent ID
            tenant_id: Tenant ID
            version_no: Version number for fetching skill instances

        Returns:
            List of enabled skill dicts
        """
        try:
            enabled_skills = skill_db.search_skills_for_agent(
                agent_id=agent_id,
                tenant_id=tenant_id,
                version_no=version_no
            )

            result = []
            for skill_instance in enabled_skills:
                skill_id = skill_instance.get("skill_id")
                skill = self.repository.get_skill_by_id(skill_id)
                if skill:
                    # Get skill info from ag_skill_info_t (repository returns keys: name, description, content)
                    merged = {
                        "skill_id": skill_id,
                        "name": skill.get("name"),
                        "description": skill.get("description", ""),
                        "content": skill.get("content", ""),
                        "enabled": skill_instance.get("enabled", True),
                        "tool_ids": skill.get("tool_ids", []),
                    }
                    result.append(merged)

            return result
        except Exception as e:
            logger.error(f"Error getting enabled skills for agent: {e}")
            raise SkillException(f"Failed to get enabled skills: {str(e)}") from e

    def load_skill_directory(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """Load entire skill directory including scripts.

        Args:
            skill_name: Name of the skill

        Returns:
            Dict with skill metadata and local directory path, or None if not found
        """
        try:
            return self.skill_manager.load_skill_directory(skill_name)
        except Exception as e:
            logger.error(f"Error loading skill directory {skill_name}: {e}")
            raise SkillException(f"Failed to load skill directory: {str(e)}") from e

    def get_skill_scripts(self, skill_name: str) -> List[str]:
        """Get list of executable scripts in skill.

        Args:
            skill_name: Name of the skill

        Returns:
            List of script file paths
        """
        try:
            return self.skill_manager.get_skill_scripts(skill_name)
        except Exception as e:
            logger.error(f"Error getting skill scripts {skill_name}: {e}")
            raise SkillException(f"Failed to get skill scripts: {str(e)}") from e

    def build_skills_summary(
        self,
        available_skills: Optional[List[str]] = None,
        agent_id: Optional[int] = None,
        tenant_id: Optional[str] = None,
        version_no: int = 0
    ) -> str:
        """Build skills summary with whitelist filter for prompt injection.

        Args:
            available_skills: Optional whitelist of skill names to include.
                             If provided, only skills in this list will be included.
            agent_id: Agent ID for fetching skill instances
            tenant_id: Tenant ID for fetching skill instances
            version_no: Version number for fetching skill instances

        Returns:
            XML-formatted skills summary
        """
        try:
            skills_to_include = []

            if agent_id and tenant_id:
                # Get skills from SkillInstance table
                agent_skills = skill_db.search_skills_for_agent(
                    agent_id=agent_id,
                    tenant_id=tenant_id,
                    version_no=version_no
                )

                for skill_instance in agent_skills:
                    skill_id = skill_instance.get("skill_id")
                    skill = self.repository.get_skill_by_id(skill_id)
                    if skill:
                        if available_skills is not None and skill.get("name") not in available_skills:
                            continue
                        # Get skill info from ag_skill_info_t (repository returns keys: name, description)
                        skills_to_include.append({
                            "name": skill.get("name"),
                            "description": skill.get("description", ""),
                        })
            else:
                # Fallback: use all skills
                all_skills = self.repository.list_skills()
                skills_to_include = all_skills
                if available_skills is not None:
                    available_set = set(available_skills)
                    skills_to_include = [s for s in all_skills if s.get("name") in available_set]

            if not skills_to_include:
                return ""

            def escape_xml(s: str) -> str:
                if s is None:
                    return ""
                return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

            lines = ["<skills>"]
            for skill in skills_to_include:
                name = escape_xml(skill.get("name", ""))
                description = escape_xml(skill.get("description", ""))

                lines.append(f'  <skill>')
                lines.append(f'    <name>{name}</name>')
                lines.append(f'    <description>{description}</description>')
                lines.append(f'  </skill>')

            lines.append("</skills>")

            return "\n".join(lines)
        except Exception as e:
            logger.error(f"Error building skills summary: {e}")
            raise SkillException(f"Failed to build skills summary: {str(e)}") from e

    def get_skill_content(self, skill_name: str, tenant_id: Optional[str] = None) -> str:
        """Get skill content for runtime loading.

        Args:
            skill_name: Name of the skill to load
            tenant_id: Tenant ID (reserved for future multi-tenant support)

        Returns:
            Skill content in markdown format
        """
        try:
            skill = self.repository.get_skill_by_name(skill_name)
            return skill.get("content", "") if skill else ""
        except Exception as e:
            logger.error(f"Error getting skill content {skill_name}: {e}")
            raise SkillException(f"Failed to get skill content: {str(e)}") from e

    def get_skill_file_tree(
        self,
        skill_name: str,
        tenant_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Get file tree structure of a skill.

        Args:
            skill_name: Name of the skill
            tenant_id: Tenant ID (reserved for future multi-tenant support)

        Returns:
            Dict with file tree structure, or None if not found
        """
        try:
            return self.skill_manager.get_skill_file_tree(skill_name)
        except Exception as e:
            logger.error(f"Error getting skill file tree: {e}")
            raise SkillException(f"Failed to get skill file tree: {str(e)}") from e

    def get_skill_file_content(
        self,
        skill_name: str,
        file_path: str,
        tenant_id: Optional[str] = None
    ) -> Optional[str]:
        """Get content of a specific file within a skill.

        Args:
            skill_name: Name of the skill
            file_path: Relative path to the file within the skill directory
            tenant_id: Tenant ID (reserved for future multi-tenant support)

        Returns:
            File content as string, or None if file not found
        """
        try:
            local_dir = os.path.join(self.skill_manager.local_skills_dir, skill_name)
            full_path = os.path.join(local_dir, file_path)

            if not os.path.exists(full_path):
                logger.warning(f"File not found: {full_path}")
                return None

            with open(full_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error reading skill file {skill_name}/{file_path}: {e}")
            raise SkillException(f"Failed to read skill file: {str(e)}") from e

    # ============== Skill Instance Methods ==============

    def create_or_update_skill_instance(
        self,
        skill_info,
        tenant_id: str,
        user_id: str,
        version_no: int = 0
    ):
        """Create or update a skill instance for an agent.

        Args:
            skill_info: Skill instance information (SkillInstanceInfoRequest or dict)
            tenant_id: Tenant ID
            user_id: User ID (will be set as created_by/updated_by)
            version_no: Version number (default 0 for draft)

        Returns:
            Created or updated skill instance dict
        """
        from database import skill_db as skill_db_module
        return skill_db_module.create_or_update_skill_by_skill_info(
            skill_info=skill_info,
            tenant_id=tenant_id,
            user_id=user_id,
            version_no=version_no
        )

    def list_skill_instances(
        self,
        agent_id: int,
        tenant_id: str,
        version_no: int = 0
    ) -> List[Dict[str, Any]]:
        """List all skill instances for an agent.

        Args:
            agent_id: Agent ID
            tenant_id: Tenant ID
            version_no: Version number (default 0 for draft)

        Returns:
            List of skill instance dicts
        """
        from database import skill_db as skill_db_module
        return skill_db_module.query_skill_instances_by_agent_id(
            agent_id=agent_id,
            tenant_id=tenant_id,
            version_no=version_no
        )

    def get_skill_instance(
        self,
        agent_id: int,
        skill_id: int,
        tenant_id: str,
        version_no: int = 0
    ) -> Optional[Dict[str, Any]]:
        """Get a specific skill instance for an agent.

        Args:
            agent_id: Agent ID
            skill_id: Skill ID
            tenant_id: Tenant ID
            version_no: Version number (default 0 for draft)

        Returns:
            Skill instance dict or None if not found
        """
        from database import skill_db as skill_db_module
        return skill_db_module.query_skill_instance_by_id(
            agent_id=agent_id,
            skill_id=skill_id,
            tenant_id=tenant_id,
            version_no=version_no
        )
