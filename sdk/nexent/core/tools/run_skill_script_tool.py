"""Skill script execution tool."""
import json
import logging
import os
from enum import Enum
from typing import Any, Dict, List, Optional

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
        observer: Optional[Any] = None,
    ):
        """Initialize the tool with local skills directory and agent context.
        Args:
            local_skills_dir: Path to local skills storage.
            agent_id: Agent ID for filtering available skills in error messages.
            tenant_id: Tenant ID for filtering available skills in error messages.
            version_no: Version number for filtering available skills.
            observer: Message observer used to publish structured skill artifacts.
        """
        super().__init__()
        self.skill_manager = None
        self.local_skills_dir = local_skills_dir
        self.agent_id = agent_id
        self.tenant_id = tenant_id
        self.version_no = version_no
        self.observer = observer

    def _get_skill_manager(self):
        """Lazy load skill manager."""
        if self.skill_manager is None:
            from nexent.skills import SkillManager
            self.skill_manager = SkillManager(self.local_skills_dir)
        return self.skill_manager

    @staticmethod
    def _parse_result_payload(result: Any) -> Optional[Dict[str, Any]]:
        """Parse a skill script result into a JSON object when possible."""
        if isinstance(result, dict):
            return result
        if not isinstance(result, str):
            return None
        try:
            payload = json.loads(result)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _normalize_script_path(script_path: str) -> str:
        """Normalize a skill-relative script path for output declaration lookup."""
        normalized_path = (script_path or "").strip().strip("\"'")
        while normalized_path.startswith(("./", ".\\")):
            normalized_path = normalized_path[2:]
        return normalized_path.lstrip("/\\").replace("\\", "/")

    def _extract_file_artifacts(
        self,
        manager: Any,
        skill_name: str,
        script_path: str,
        result: Any,
    ) -> List[Dict[str, Any]]:
        """Extract artifacts only from a script declared as file-producing."""
        skill = manager.load_skill(skill_name, tenant_id=self.tenant_id)
        if not isinstance(skill, dict):
            return []
        script_outputs = skill.get("script_outputs") or {}
        script_output = script_outputs.get(self._normalize_script_path(script_path))
        if not isinstance(script_output, dict) or script_output.get("kind") != "file":
            return []
        payload = self._parse_result_payload(result)
        if not payload or payload.get("status") != "success":
            return []
        raw_artifacts = payload.get("artifacts")
        if not isinstance(raw_artifacts, list):
            return []
        declared_mime_types = set(script_output.get("mime_types") or [])
        artifacts: List[Dict[str, Any]] = []
        for raw_artifact in raw_artifacts:
            if not isinstance(raw_artifact, dict) or raw_artifact.get("kind") != "file":
                continue
            absolute_path = raw_artifact.get("absolute_path")
            file_name = raw_artifact.get("file_name")
            mime_type = raw_artifact.get("mime_type")
            file_size_bytes = raw_artifact.get("file_size_bytes")
            if not all(isinstance(value, str) and value.strip() for value in (absolute_path, file_name, mime_type)):
                continue
            if isinstance(file_size_bytes, bool) or not isinstance(file_size_bytes, int) or file_size_bytes < 0:
                continue
            if not os.path.isfile(absolute_path):
                continue
            if os.path.getsize(absolute_path) != file_size_bytes:
                logger.warning(
                    "Ignoring skill artifact with mismatched file size skill=%s path=%s",
                    skill_name,
                    absolute_path,
                )
                continue
            if declared_mime_types and mime_type not in declared_mime_types:
                logger.warning(
                    "Ignoring undeclared skill artifact MIME type skill=%s mime_type=%s",
                    skill_name,
                    mime_type,
                )
                continue
            artifacts.append(raw_artifact)
        return artifacts

    def _publish_artifacts(
        self,
        skill_name: str,
        script_path: str,
        artifacts: List[Dict[str, Any]],
    ) -> None:
        """Publish structured artifacts independently from model-visible output."""
        if not artifacts or self.observer is None:
            return
        content = {
            "skill_name": skill_name,
            "script_path": script_path,
            "artifacts": artifacts,
        }
        try:
            from ..utils.observer import ProcessType
        except ImportError:
            try:
                from sdk.nexent.core.utils.observer import ProcessType
            except ImportError:
                class ProcessType(Enum):
                    SKILL_ARTIFACT = "skill_artifact"
        self.observer.add_message("", ProcessType.SKILL_ARTIFACT, content)
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
            artifacts = self._extract_file_artifacts(manager, skill_name, script_path, result)
            self._publish_artifacts(skill_name, script_path, artifacts)
            return str(result)
        except SkillNotFoundError as e:
            message = getattr(e, "message", str(e))
            logger.error(f"Skill not found: {skill_name} - {message}")
            return f"[SkillNotFoundError] {message}"
        except SkillScriptNotFoundError as e:
            message = getattr(e, "message", str(e))
            logger.error(f"Script not found in skill '{skill_name}': {script_path} - {message}")
            return f"[SkillScriptNotFoundError] {message}"
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
    observer: Optional[Any] = None,
) -> RunSkillScriptTool:
    """Construct an uncached tool for internal use and isolated tests."""
    return RunSkillScriptTool(
        local_skills_dir,
        agent_id,
        tenant_id,
        version_no,
        observer,
    )