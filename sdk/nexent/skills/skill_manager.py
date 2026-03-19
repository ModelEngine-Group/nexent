"""Skill manager for loading and managing skills from local storage."""

import io
import json
import logging
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .constants import SKILL_FILE_NAME
from .skill_loader import SkillLoader

logger = logging.getLogger(__name__)


class SkillNotFoundError(Exception):
    """Raised when the requested skill does not exist in local storage."""

    def __init__(self, message: str = ""):
        self.message = message
        super().__init__(self.message)


class SkillScriptNotFoundError(Exception):
    """Raised when the requested script does not exist within a skill."""

    def __init__(self, message: str = ""):
        self.message = message
        super().__init__(self.message)


class SkillManager:
    """Manages skill loading and storage from local directory."""

    def __init__(
        self,
        local_skills_dir: Optional[str] = None,
        agent_id: Optional[int] = None,
        tenant_id: Optional[str] = None,
        version_no: int = 0,
    ):
        """Initialize SkillManager with local directory.

        Args:
            local_skills_dir: Local directory for skills storage
            agent_id: Agent ID for filtering skills during error messages
            tenant_id: Tenant ID for filtering skills during error messages
            version_no: Version number for filtering skills (default 0 = draft)
        """
        self.local_skills_dir = local_skills_dir
        self.agent_id = agent_id
        self.tenant_id = tenant_id
        self.version_no = version_no

    def list_skills(self) -> List[Dict[str, str]]:
        """List all available skills from local storage.

        Returns:
            List of skill info dicts with name and description
        """
        skills = []

        if not os.path.exists(self.local_skills_dir):
            return skills

        try:
            for skill_name in os.listdir(self.local_skills_dir):
                skill_path = os.path.join(self.local_skills_dir, skill_name)
                if os.path.isdir(skill_path):
                    skill_file = os.path.join(skill_path, SKILL_FILE_NAME)
                    if os.path.exists(skill_file):
                        skill = self._get_skill_metadata(skill_name)
                        if skill:
                            skills.append(skill)
        except Exception as e:
            logger.error(f"Error listing skills: {e}")

        return skills

    def _get_skill_metadata(self, skill_name: str) -> Optional[Dict[str, str]]:
        """Get skill metadata without loading full content."""
        try:
            skill = self.load_skill(skill_name)
            if skill:
                return {
                    "name": skill.get("name", skill_name),
                    "description": skill.get("description", ""),
                    "tags": skill.get("tags", []),
                }
        except Exception as e:
            logger.warning(f"Could not load skill {skill_name}: {e}")
        return None

    def load_skill(self, name: str) -> Optional[Dict[str, Any]]:
        """Load a skill by name from local storage.

        Args:
            name: Skill name

        Returns:
            Skill dict with metadata and content, or None if not found
        """
        if self.local_skills_dir is None:
            return None

        local_path = os.path.join(self.local_skills_dir, name, SKILL_FILE_NAME)
        try:
            if os.path.exists(local_path):
                return SkillLoader.load(local_path)
        except Exception as e:
            logger.error(f"Error loading skill from local: {e}")

        return None

    def load_skill_content(self, name: str) -> Optional[str]:
        """Load only the content body of a skill.

        Args:
            name: Skill name

        Returns:
            Skill content as string, or None if not found
        """
        skill = self.load_skill(name)
        return skill.get("content") if skill else None

    def save_skill(self, skill_data: Dict[str, Any]) -> Dict[str, Any]:
        """Save a skill to local storage only.

        Args:
            skill_data: Skill dict with name, description, content, etc.

        Returns:
            Saved skill dict
        """
        name = skill_data.get("name")
        if not name:
            raise ValueError("Skill name is required")

        content = SkillLoader.to_skill_md(skill_data)

        local_dir = os.path.join(self.local_skills_dir, name)
        os.makedirs(local_dir, exist_ok=True)
        local_path = os.path.join(local_dir, SKILL_FILE_NAME)
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"Saved skill '{name}' to local storage")
        return self.load_skill(name)

    def upload_skill_from_file(
        self,
        file_content: Union[bytes, str, io.BytesIO],
        skill_name: Optional[str] = None,
        file_type: str = "auto"
    ) -> Dict[str, Any]:
        """Upload a skill from file content (SKILL.md or ZIP).

        Supports two formats:
        1. Single SKILL.md file - extracts metadata and saves directly
        2. ZIP archive - extracts SKILL.md and all other files/scripts

        Args:
            file_content: File content as bytes, string, or BytesIO
            skill_name: Optional skill name (extracted from ZIP if not provided)
            file_type: File type hint - "md", "zip", or "auto" (detect)

        Returns:
            Created skill dict

        Raises:
            ValueError: If file format is invalid or SKILL.md not found
        """
        content_bytes: bytes
        if isinstance(file_content, str):
            content_bytes = file_content.encode("utf-8")
        elif isinstance(file_content, io.BytesIO):
            content_bytes = file_content.getvalue()
        else:
            content_bytes = file_content

        if file_type == "auto":
            if skill_name and skill_name.endswith(".zip"):
                file_type = "zip"
            elif content_bytes.startswith(b"PK"):  # ZIP magic bytes
                file_type = "zip"
            else:
                file_type = "md"

        if file_type == "zip":
            return self._upload_skill_from_zip(content_bytes, skill_name)
        else:
            return self._upload_skill_from_md(content_bytes, skill_name)

    def _upload_skill_from_md(
        self,
        content_bytes: bytes,
        skill_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Upload skill from SKILL.md content.

        Args:
            content_bytes: SKILL.md file content
            skill_name: Optional skill name override

        Returns:
            Created skill dict
        """
        content_str = content_bytes.decode("utf-8")

        try:
            skill_data = SkillLoader.parse(content_str)
        except ValueError as e:
            raise ValueError(f"Invalid SKILL.md format: {e}")

        name = skill_name or skill_data.get("name")
        if not name:
            raise ValueError("Skill name is required (provide in filename or SKILL.md frontmatter)")

        skill_data["name"] = name
        return self.save_skill(skill_data)

    def _upload_skill_from_zip(
        self,
        zip_bytes: bytes,
        skill_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Upload skill from ZIP archive containing SKILL.md and files.

        Expected structure:
            skill_name/
                SKILL.md
                scripts/
                    ...
                assets/
                    ...

        Args:
            zip_bytes: ZIP archive content
            skill_name: Optional skill name (folder name in ZIP if not provided)

        Returns:
            Created skill dict
        """
        zip_stream = io.BytesIO(zip_bytes)

        try:
            with zipfile.ZipFile(zip_stream, "r") as zf:
                file_list = zf.namelist()
        except zipfile.BadZipFile:
            raise ValueError("Invalid ZIP archive")

        skill_md_path: Optional[str] = None
        detected_skill_name: Optional[str] = None
        skill_files: List[tuple] = []

        for file_path in file_list:
            if file_path.endswith("/"):
                continue

            normalized_path = file_path.replace("\\", "/")
            parts = normalized_path.split("/")

            if len(parts) == 2 and parts[1].lower() == SKILL_FILE_NAME.lower():
                skill_md_path = file_path
                detected_skill_name = parts[0]
                break
            elif len(parts) >= 2 and parts[1].lower() == SKILL_FILE_NAME.lower():
                skill_md_path = file_path
                detected_skill_name = parts[0]
                break

        if not skill_md_path:
            for file_path in file_list:
                if file_path.lower().endswith("skill.md"):
                    parts = file_path.replace("\\", "/").split("/")
                    skill_md_path = file_path
                    detected_skill_name = parts[0] if len(parts) > 1 else "unknown"
                    break

        if not skill_md_path:
            raise ValueError("SKILL.md not found in ZIP archive")

        name = skill_name or detected_skill_name
        if not name or name == "unknown":
            raise ValueError("Skill name is required (provide in folder name or skill_name param)")

        skill_data: Dict[str, Any] = {}

        try:
            with zipfile.ZipFile(zip_stream, "r") as zf:
                skill_content = zf.read(skill_md_path).decode("utf-8")
                skill_data = SkillLoader.parse(skill_content)
                skill_data["name"] = name
        except Exception as e:
            raise ValueError(f"Failed to parse SKILL.md from ZIP: {e}")

        self.save_skill(skill_data)

        with zipfile.ZipFile(zip_stream, "r") as zf:
            for file_path in file_list:
                if file_path == skill_md_path:
                    continue

                normalized_path = file_path.replace("\\", "/")
                if normalized_path.startswith(f"{name}/"):
                    relative_path = normalized_path[len(name)+1:]
                else:
                    relative_path = normalized_path

                if not relative_path:
                    continue

                file_data = zf.read(file_path)

                local_dir = os.path.join(self.local_skills_dir, name)
                local_path = os.path.join(local_dir, relative_path)
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                with open(local_path, "wb") as f:
                    f.write(file_data)

        logger.info(f"Extracted skill '{name}' from ZIP with {len(file_list)} files")
        return self.load_skill(name)

    def update_skill_from_file(
        self,
        file_content: Union[bytes, str, io.BytesIO],
        skill_name: str,
        file_type: str = "auto"
    ) -> Dict[str, Any]:
        """Update an existing skill from file content.

        Supports both SKILL.md and ZIP formats. For ZIP, only updates files
        that are present in the archive.

        Args:
            file_content: File content as bytes, string, or BytesIO
            skill_name: Name of the skill to update
            file_type: File type hint - "md", "zip", or "auto" (detect)

        Returns:
            Updated skill dict
        """
        existing = self.load_skill(skill_name)
        if not existing:
            raise ValueError(f"Skill not found: {skill_name}")

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
            return self._update_skill_from_zip(content_bytes, skill_name)
        else:
            return self._update_skill_from_md(content_bytes, skill_name)

    def _update_skill_from_md(
        self,
        content_bytes: bytes,
        skill_name: str
    ) -> Dict[str, Any]:
        """Update skill from SKILL.md content.

        Args:
            content_bytes: SKILL.md file content
            skill_name: Name of the skill to update

        Returns:
            Updated skill dict
        """
        content_str = content_bytes.decode("utf-8")
        skill_data = SkillLoader.parse(content_str)
        skill_data["name"] = skill_name
        return self.save_skill(skill_data)

    def _update_skill_from_zip(
        self,
        zip_bytes: bytes,
        skill_name: str
    ) -> Dict[str, Any]:
        """Update skill from ZIP archive.

        Updates SKILL.md and adds/updates additional files.
        Does not delete existing files not in the archive.

        Args:
            zip_bytes: ZIP archive content
            skill_name: Name of the skill to update

        Returns:
            Updated skill dict
        """
        existing = self.load_skill(skill_name)
        if not existing:
            raise ValueError(f"Skill not found: {skill_name}")

        zip_stream = io.BytesIO(zip_bytes)

        with zipfile.ZipFile(zip_stream, "r") as zf:
            file_list = zf.namelist()

            skill_md_path = None
            for file_path in file_list:
                normalized_path = file_path.replace("\\", "/")
                if normalized_path.lower().endswith("skill.md"):
                    parts = normalized_path.split("/")
                    if len(parts) >= 2:
                        skill_md_path = file_path
                        break

            if skill_md_path:
                skill_content = zf.read(skill_md_path).decode("utf-8")
                skill_data = SkillLoader.parse(skill_content)
                skill_data["name"] = skill_name
                self.save_skill(skill_data)

            for file_path in file_list:
                if file_path == skill_md_path:
                    continue

                normalized_path = file_path.replace("\\", "/")
                parts = normalized_path.split("/")

                if len(parts) >= 2 and parts[0] != skill_name:
                    relative_path = "/".join(parts[1:])
                else:
                    relative_path = normalized_path

                if not relative_path:
                    continue

                file_data = zf.read(file_path)

                local_dir = os.path.join(self.local_skills_dir, skill_name)
                local_path = os.path.join(local_dir, relative_path)
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                with open(local_path, "wb") as f:
                    f.write(file_data)

        logger.info(f"Updated skill '{skill_name}' from ZIP")
        return self.load_skill(skill_name)

    def get_skill_file_tree(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """Get file tree structure of a skill.

        Args:
            skill_name: Name of the skill

        Returns:
            Dict with file tree structure, or None if skill not found
        """
        skill = self.load_skill(skill_name)
        if not skill:
            return None

        tree = {
            "name": skill_name,
            "type": "directory",
            "children": []
        }

        local_dir = os.path.join(self.local_skills_dir, skill_name)
        if os.path.exists(local_dir):
            for root, dirs, files in os.walk(local_dir):
                rel_root = os.path.relpath(root, local_dir)
                if rel_root == ".":
                    continue
                parts = rel_root.split(os.sep)
                self._add_to_tree(tree, parts)
                for f in files:
                    if f != SKILL_FILE_NAME:
                        self._add_to_tree(tree, parts + [f])

        return tree

    def _add_to_tree(self, node: Dict, parts: List[str]) -> None:
        """Add a path to the tree structure.

        Args:
            node: Current tree node
            parts: Path parts to add
        """
        if not parts:
            return

        name = parts[0]

        if len(parts) == 1:
            for child in node.get("children", []):
                if child.get("name") == name and child.get("type") == "file":
                    return
            node.setdefault("children", []).append({
                "name": name,
                "type": "file"
            })
        else:
            found = None
            for child in node.get("children", []):
                if child.get("name") == name and child.get("type") == "directory":
                    found = child
                    break

            if not found:
                found = {"name": name, "type": "directory", "children": []}
                node.setdefault("children", []).append(found)

            self._add_to_tree(found, parts[1:])

    def delete_skill(self, name: str) -> bool:
        """Delete a skill from local storage.

        Args:
            name: Skill name

        Returns:
            True if deleted successfully
        """
        local_dir = os.path.join(self.local_skills_dir, name)
        if os.path.exists(local_dir):
            try:
                shutil.rmtree(local_dir)
            except Exception as e:
                logger.error(f"Error deleting skill from local: {e}")

        logger.info(f"Deleted skill '{name}' from local storage")
        return True

    def _get_available_skills_for_error(
        self,
        agent_id: Optional[int] = None,
        tenant_id: Optional[str] = None,
        version_no: int = 0,
    ) -> List[Dict[str, str]]:
        """Get available skills for error messages.

        If agent_id and tenant_id are provided, queries the database for enabled
        skills for that agent. Otherwise falls back to local filesystem listing.

        Returns:
            List of skill dicts with name, description, and tags
        """
        if agent_id is not None and tenant_id is not None:
            try:
                from backend.database import skill_db as skill_db_module
                from backend.services.skill_repository import SkillRepository
                enabled_instances = skill_db_module.search_skills_for_agent(
                    agent_id=agent_id,
                    tenant_id=tenant_id,
                    version_no=version_no,
                )
                repo = SkillRepository()
                result = []
                for inst in enabled_instances:
                    skill = repo.get_skill_by_id(inst.get("skill_id"))
                    if skill:
                        result.append({
                            "name": skill.get("name"),
                            "description": skill.get("description", ""),
                            "tags": skill.get("tags", []),
                        })
                return result
            except Exception:
                pass
        return self.list_skills()

    def build_skills_summary(self, available_skills: Optional[List[str]] = None) -> str:
        """Build XML-formatted summary of available skills.

        Args:
            available_skills: Optional whitelist of skill names. If provided,
                             only skills in this list will be included in summary.

        Returns:
            XML-formatted skills summary with name and description.
        """
        all_skills = self.list_skills()

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
    

    def load_skill_directory(self, name: str) -> Optional[Dict[str, Any]]:
        """Load entire skill directory including scripts.

        This copies the skill directory from local storage to a temp directory
        for execution.

        Args:
            name: Skill name

        Returns:
            Dict with skill metadata and local directory path
        """
        skill = self.load_skill(name)
        if not skill:
            return None

        temp_dir = tempfile.mkdtemp(prefix=f"skill_{name}_")

        local_path = os.path.join(self.local_skills_dir, name)
        if os.path.exists(local_path):
            import shutil as sh
            sh.copytree(local_path, temp_dir, dirs_exist_ok=True)

        skill["directory"] = temp_dir
        return skill

    def get_skill_scripts(self, name: str) -> List[str]:
        """Get list of executable scripts in skill.

        Args:
            name: Skill name

        Returns:
            List of script file paths within the skill directory
        """
        skill_dir = self.load_skill_directory(name)
        if not skill_dir:
            return []

        scripts_dir = os.path.join(skill_dir["directory"], "scripts")
        if not os.path.exists(scripts_dir):
            return []

        scripts = []
        for root, _, files in os.walk(scripts_dir):
            for file in files:
                if file.endswith((".py", ".sh")):
                    scripts.append(os.path.join(root, file))

        return scripts

    def cleanup_skill_directory(self, name: str) -> None:
        """Clean up temporary skill directory.

        Args:
            name: Skill name
        """
        temp_dir = tempfile.gettempdir()
        for item in os.listdir(temp_dir):
            if item.startswith(f"skill_{name}_"):
                path = os.path.join(temp_dir, item)
                try:
                    if os.path.isdir(path):
                        shutil.rmtree(path)
                    else:
                        os.remove(path)
                except Exception as e:
                    logger.warning(f"Could not cleanup temp dir {path}: {e}")

    def run_skill_script(
        self,
        skill_name: str,
        script_path: str,
        params: Optional[Dict[str, Any]] = None,
        agent_id: Optional[int] = None,
        tenant_id: Optional[str] = None,
        version_no: int = 0,
    ) -> Any:
        """Execute a skill script with given parameters.

        Args:
            skill_name: Name of the skill containing the script
            script_path: Path to script relative to skill directory (e.g., "scripts/analyze.py")
            params: Parameters to pass to the script
            agent_id: Agent ID for DB-based available skills lookup
            tenant_id: Tenant ID for DB-based available skills lookup
            version_no: Version number for DB-based available skills lookup

        Returns:
            Script execution result as string or parsed JSON

        Raises:
            SkillNotFoundError: When the skill directory does not exist in local storage
            SkillScriptNotFoundError: When the specified script path does not exist within the skill
        """
        local_skill_dir = os.path.join(self.local_skills_dir, skill_name)
        if not os.path.isdir(local_skill_dir):
            raise SkillNotFoundError(
                f"Skill '{skill_name}' not found. Available skills: "
                f"{self._get_available_skills_for_error(agent_id, tenant_id, version_no)}"
            )

        full_path = os.path.join(local_skill_dir, script_path)
        if not os.path.isfile(full_path):
            # List available scripts directly from local directory (no temp needed)
            available = []
            scripts_dir = os.path.join(local_skill_dir, "scripts")
            if os.path.isdir(scripts_dir):
                for root, _, files in os.walk(scripts_dir):
                    for f in files:
                        if f.endswith((".py", ".sh")):
                            rel = os.path.relpath(os.path.join(root, f), local_skill_dir)
                            available.append(rel)
            raise SkillScriptNotFoundError(
                f"Script '{script_path}' not found in skill '{skill_name}'. "
                f"Available scripts: {available if available else 'none'}"
            )

        params = params or {}

        if script_path.endswith(".py"):
            return self._run_python_script(full_path, params)
        elif script_path.endswith(".sh"):
            return self._run_shell_script(full_path, params)
        else:
            raise ValueError(f"Unsupported script type: {script_path}")

    def _run_python_script(self, script_path: str, params: Dict[str, Any]) -> str:
        """Run a Python script with parameters.

        Args:
            script_path: Full path to the Python script
            params: Parameters to pass as environment variables

        Returns:
            Script output as string
        """
        env = os.environ.copy()
        for key, value in params.items():
            env[key.upper()] = str(value)

        try:
            result = subprocess.run(
                ["python", script_path],
                capture_output=True,
                text=True,
                timeout=300,
                env=env
            )
            if result.returncode != 0:
                logger.error(f"Script error: {result.stderr}")
                return json.dumps({"error": result.stderr, "output": result.stdout})
            return result.stdout
        except subprocess.TimeoutExpired:
            raise TimeoutError(f"Script execution timed out: {script_path}")
        except Exception as e:
            logger.error(f"Failed to run script: {e}")
            raise

    def _run_shell_script(self, script_path: str, params: Dict[str, Any]) -> str:
        """Run a shell script with parameters.

        Args:
            script_path: Full path to the shell script
            params: Parameters to pass as environment variables

        Returns:
            Script output as string
        """
        env = os.environ.copy()
        for key, value in params.items():
            env[key.upper()] = str(value)

        try:
            result = subprocess.run(
                ["bash", script_path],
                capture_output=True,
                text=True,
                timeout=300,
                env=env
            )
            if result.returncode != 0:
                logger.error(f"Script error: {result.stderr}")
                return json.dumps({"error": result.stderr, "output": result.stdout})
            return result.stdout
        except subprocess.TimeoutExpired:
            raise TimeoutError(f"Script execution timed out: {script_path}")
        except Exception as e:
            logger.error(f"Failed to run script: {e}")
            raise
