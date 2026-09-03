"""Skill script execution tool."""
import json
import logging
import os
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

from smolagents.tools import Tool

logger = logging.getLogger(__name__)


class SkillScriptExecutionError(RuntimeError):
    """Raised when a sandboxed skill script exits unsuccessfully."""


class RunSkillScriptTool(Tool):
    """Tool for executing skill scripts."""
    name = "run_skill_script"
    description = (
        "Execute a script for an enabled skill inside the configured Docker sandbox. "
        "Use source='skill' for scripts bundled with the skill and source='workspace' "
        "only for Python or Node.js scripts generated in the current run workspace. "
        "For source='workspace', script_path is workspace-root-relative: a script written "
        "as bare 'build.js' by the code executor is located at 'outputs/build.js'. "
        "Scripts run with the current run's outputs directory as CWD, so bare output "
        "filenames are created where artifact upload expects them. A failed script raises "
        "an execution error; repair the script and rerun it before validating or uploading. "
        "Do not use subprocess, os.system, or shell calls from ordinary agent code for system "
        "commands; use a skill-bundled wrapper or a shell-free language API."
    )
    inputs = {
        "skill_name": {"type": "string", "description": "Name of the skill containing the script."},
        "script_path": {
            "type": "string",
            "description": (
                "For source='skill', path relative to the skill root. For "
                "source='workspace', path relative to the current run workspace; use "
                "'outputs/name.py' or 'outputs/name.js' for scripts written as bare "
                "filenames by the code executor."
            ),
        },
        "params": {
            "type": "string",
            "description": "Optional raw command-line arguments for the script.",
            "nullable": True,
        },
        "source": {
            "type": "string",
            "description": "Script source: 'skill' (default) or 'workspace'.",
            "default": "skill",
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
        workspace_path: Optional[str] = None,
        on_complete: Optional[Any] = None,
        execution_backend: Optional[Any] = None,
        authorized_skill_names: Optional[Sequence[str]] = None,
    ):
        """Initialize the tool with local skills directory and agent context.
        Args:
            local_skills_dir: Path to local skills storage.
            agent_id: Agent ID for filtering available skills in error messages.
            tenant_id: Tenant ID for filtering available skills in error messages.
            version_no: Version number for filtering available skills.
            observer: Message observer used to publish structured skill artifacts.
            workspace_path: Optional run-scoped working directory for script files.
            on_complete: Optional callback invoked after the script finishes successfully.
            execution_backend: Optional isolated execution callable. It receives
                the manager, skill identity, script path, params and working
                directory. When omitted, execution remains process-local.
        """
        super().__init__()
        self.skill_manager = None
        self.local_skills_dir = local_skills_dir
        self.agent_id = agent_id
        self.tenant_id = tenant_id
        self.version_no = version_no
        self.observer = observer
        self.workspace_path = workspace_path
        self.on_complete = on_complete
        self.execution_backend = execution_backend
        self.authorized_skill_names = (
            frozenset(name for name in (authorized_skill_names or []) if name)
            if authorized_skill_names is not None
            else None
        )

    def bind_execution_backend(
        self,
        execution_backend: Any,
        *,
        on_complete: Optional[Any] = None,
    ) -> None:
        """Bind this host-side control tool to an isolated execution backend."""
        self.execution_backend = execution_backend
        if on_complete is not None:
            self.on_complete = on_complete

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
        source: str = "skill",
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
            normalized_source = (source or "skill").strip().lower()
            if normalized_source not in {"skill", "workspace"}:
                raise ValueError("source must be either 'skill' or 'workspace'")
            if self.authorized_skill_names is not None and skill_name not in self.authorized_skill_names:
                raise PermissionError(
                    f"Skill '{skill_name}' is not enabled for agent {self.agent_id}"
                )
            manager = self._get_skill_manager()
            if self.execution_backend is not None:
                backend_kwargs = dict(
                    manager=manager,
                    skill_name=skill_name,
                    script_path=script_path,
                    params=params,
                    tenant_id=self.tenant_id,
                    working_directory=self.workspace_path,
                )
                if normalized_source != "skill":
                    backend_kwargs["source"] = normalized_source
                result = self.execution_backend(**backend_kwargs)
                if isinstance(result, str):
                    try:
                        result_data = json.loads(result)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        result_data = None
                    if isinstance(result_data, dict) and result_data.get("error"):
                        raise SkillScriptExecutionError(
                            "Sandbox script failed. Repair the script and rerun "
                            f"run_skill_script before continuing: {result_data['error']}"
                        )
            else:
                if normalized_source == "workspace":
                    raise RuntimeError(
                        "Workspace scripts require an available Docker sandbox execution backend"
                    )
                run_kwargs = {"tenant_id": self.tenant_id}
                if self.workspace_path:
                    run_kwargs["working_directory"] = self.workspace_path
                result = manager.run_skill_script(
                    skill_name,
                    script_path,
                    params,
                    **run_kwargs,
                )
            if self.on_complete is not None:
                self.on_complete(result)
            artifacts = (
                self._extract_file_artifacts(manager, skill_name, script_path, result)
                if normalized_source == "skill"
                else []
            )
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
        except SkillScriptExecutionError:
            raise
        except Exception as e:
            logger.error(f"Failed to execute skill script: {e}")
            return f"[UnexpectedError] Failed to execute skill script: {type(e).__name__}: {str(e)}"
    def forward(
        self,
        skill_name: str,
        script_path: str,
        params: Optional[str] = None,
        source: str = "skill",
    ) -> str:
        """Execute a tenant-scoped skill script."""
        return self.execute(skill_name, script_path, params, source)

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
