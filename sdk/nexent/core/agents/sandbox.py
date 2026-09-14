"""
Sandbox executor factory and lifecycle management.

This module provides:
- ``SandboxLevel``: isolation level (local / docker / wasm)
- ``SandboxScope``: container lifecycle scope (session / system)
- ``SandboxConfig``: configuration dataclass
- ``SandboxPoolManager``: singleton pool for system-scoped containers
- ``build_python_executor()``: factory function
- ``cleanup_executor()``: three-layer guaranteed cleanup

All environment variables are read by the backend service layer and passed
in via ``SandboxConfig`` — this module never calls ``os.getenv()`` directly.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import hmac
import io
import ipaddress
import json
import logging
import mimetypes
import re
import secrets
import shlex
import socket
import tarfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from contextlib import closing
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional


logger = logging.getLogger(__name__)


_TOOL_BRIDGE_VALUE_MARKER = "__nexent_tool_bridge_value__"


class SandboxSkillScriptRunner:
    """Copy a validated skill into Docker and execute its script there.

    The runtime remains the control plane: it resolves tenant-scoped skills
    and validates that the requested path cannot escape the skill root.  The
    script process itself, its interpreter and dependencies live exclusively
    in the sandbox container.
    """

    def __init__(
        self,
        executor: Any,
        timeout_seconds: int = 300,
        workspace_path: Optional[str] = None,
        network_enabled: bool = False,
    ) -> None:
        self._executor = executor
        self._container = getattr(executor, "container", None)
        self._timeout_seconds = max(1, int(timeout_seconds))
        self._workspace_path = (workspace_path or "").rstrip("/")
        self._network_enabled = bool(network_enabled)
        self._pnpm_store_path = ""
        self._pnpm_store_seeded = False
        self._root = (
            f"{self._workspace_path}/skills"
            if self._workspace_path
            else ""
        )
        self._staged_skills: dict[str, str] = {}
        self._staged_script_fingerprints: dict[tuple[str, str], tuple[int, int]] = {}
        self._stage_lock = threading.Lock()

    @property
    def available(self) -> bool:
        """Return whether this runner has a real Docker execution target."""
        return self._container is not None and getattr(self._executor, "_nexent_backend", None) == "docker"

    @staticmethod
    def _output_text(output: Any) -> str:
        if isinstance(output, bytes):
            return output.decode("utf-8", errors="replace")
        return str(output or "")

    def _run_container_command(self, command: list[str], **kwargs: Any) -> Any:
        result = self._container.exec_run(command, **kwargs)
        exit_code = getattr(result, "exit_code", None)
        if exit_code != 0:
            output = self._output_text(getattr(result, "output", b""))
            raise RuntimeError(
                f"Sandbox preparation command failed (exit={exit_code}): {output.strip()}"
            )
        return result

    def _resolve_skills_root(self, working_directory: Optional[str]) -> str:
        """Return the run-scoped skills directory and reject workspace drift."""
        workspace_path = (working_directory or self._workspace_path).rstrip("/")
        if not workspace_path:
            raise RuntimeError("Skill scripts require a run-scoped workspace")
        skills_root = f"{workspace_path}/skills"
        if self._root and skills_root != self._root:
            raise RuntimeError("Skill script workspace does not match the sandbox runner workspace")
        self._root = skills_root
        return skills_root

    def _resolve_workspace_script(
        self,
        script_path: str,
        working_directory: Optional[str],
    ) -> tuple[str, str]:
        """Resolve one run-workspace script without following an escaping link."""
        workspace_path = (working_directory or self._workspace_path).rstrip("/")
        if not workspace_path:
            raise RuntimeError("Workspace scripts require a run-scoped workspace")
        if self._workspace_path and workspace_path != self._workspace_path:
            raise RuntimeError("Workspace script path does not match the sandbox runner workspace")

        normalized = (script_path or "").strip().strip("\"'").replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        path_parts = normalized.split("/")
        if not normalized or normalized.startswith("/") or ".." in path_parts:
            raise ValueError("Workspace script path must be a safe relative path")
        suffix = Path(normalized).suffix.lower()
        if suffix not in {".py", ".js", ".mjs"}:
            raise ValueError("Workspace scripts must use a .py, .js, or .mjs extension")

        candidate = f"{workspace_path}/{normalized}"
        resolved_result = self._container.exec_run(
            ["realpath", "-e", "--", candidate],
            user="sandbox",
        )
        if getattr(resolved_result, "exit_code", None) != 0:
            raise FileNotFoundError(f"Workspace script not found: {normalized}")
        resolved = self._output_text(getattr(resolved_result, "output", b"")).strip()
        if resolved == workspace_path or not resolved.startswith(f"{workspace_path}/"):
            raise PermissionError("Workspace script resolves outside the current run workspace")
        file_result = self._container.exec_run(
            ["test", "-f", resolved],
            user="sandbox",
        )
        if getattr(file_result, "exit_code", None) != 0:
            raise ValueError("Workspace script must resolve to a regular file")
        return resolved, normalized

    def _validate_workspace_python(self, script_path: str) -> None:
        """Apply the existing Python shell-call guard to a workspace script."""
        result = self._container.exec_run(
            ["cat", "--", script_path],
            user="sandbox",
        )
        if getattr(result, "exit_code", None) != 0:
            raise RuntimeError("Failed to read workspace Python script for validation")
        source = self._output_text(getattr(result, "output", b""))
        if len(source.encode("utf-8")) > 1024 * 1024:
            raise ValueError("Workspace Python scripts cannot exceed 1 MiB")
        violations = _scan_shell_calls(
            source,
            allow_package_installs=self._network_enabled,
        )
        if violations:
            raise PermissionError(
                "Workspace Python script contains blocked shell calls: "
                + ", ".join(violations)
            )

    def _ensure_output_directory(self, output_dir: str) -> None:
        """Create the run output directory and keep it writable by the sandbox user."""
        self._run_container_command(["mkdir", "-p", "--", output_dir], user="0")
        self._run_container_command(
            ["chown", "sandbox:sandbox", "--", output_dir],
            user="0",
        )

    def _stage_skill(
        self,
        manager: Any,
        skill_name: str,
        script_path: str,
        tenant_id: Optional[str],
        skills_root: str,
    ) -> tuple[str, str]:
        """Copy one validated skill into the run workspace once and make it read-only."""
        local_skill_dir, local_script, normalized_script = manager.resolve_skill_script(
            skill_name,
            script_path,
            tenant_id=tenant_id,
        )
        local_skill_root = str(Path(local_skill_dir).resolve())
        relative_script = Path(local_script).resolve().relative_to(Path(local_skill_root))
        script_key = (local_skill_root, relative_script.as_posix())
        script_stat = Path(local_script).stat()
        script_fingerprint = (script_stat.st_mtime_ns, script_stat.st_size)

        with self._stage_lock:
            staged_dir = self._staged_skills.get(local_skill_root)
            staged_fingerprint = self._staged_script_fingerprints.get(script_key)
            if staged_dir and staged_fingerprint != script_fingerprint:
                self._run_container_command(["rm", "-rf", "--", staged_dir], user="0")
                self._staged_skills.pop(local_skill_root, None)
                self._staged_script_fingerprints = {
                    key: value
                    for key, value in self._staged_script_fingerprints.items()
                    if key[0] != local_skill_root
                }

        sandbox_skill_dir = self._stage_skill_directory(
            local_skill_dir,
            skill_name,
            skills_root,
        )
        self._staged_script_fingerprints[script_key] = script_fingerprint
        return f"{sandbox_skill_dir}/{relative_script.as_posix()}", normalized_script

    def _stage_skill_directory(
        self,
        local_skill_dir: str,
        skill_name: str,
        skills_root: str,
    ) -> str:
        """Copy one resolved tenant skill directory into the run workspace."""
        local_skill_root = str(Path(local_skill_dir).resolve())

        with self._stage_lock:
            sandbox_skill_dir = self._staged_skills.get(local_skill_root)
            if sandbox_skill_dir is None:
                safe_skill_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", skill_name).strip("._") or "skill"
                skill_digest = hashlib.sha256(local_skill_root.encode("utf-8")).hexdigest()[:16]
                skill_key = f"{safe_skill_name}-{skill_digest}"
                sandbox_skill_dir = f"{skills_root}/{skill_key}"

                self._run_container_command(["mkdir", "-p", skills_root], user="0")
                archive = io.BytesIO()
                with tarfile.open(fileobj=archive, mode="w") as tar:
                    tar.add(local_skill_dir, arcname=skill_key, recursive=True)
                if not self._container.put_archive(skills_root, archive.getvalue()):
                    raise RuntimeError("Failed to copy the skill directory into the sandbox workspace")
                self._run_container_command(
                    ["chmod", "-R", "a+rX", sandbox_skill_dir],
                    user="0",
                )
                self._run_container_command(
                    ["chmod", "-R", "a-w", sandbox_skill_dir],
                    user="0",
                )
                self._staged_skills[local_skill_root] = sandbox_skill_dir

        return sandbox_skill_dir

    def __call__(
        self,
        *,
        manager: Any,
        skill_name: str,
        script_path: str,
        params: Optional[str],
        tenant_id: Optional[str],
        working_directory: Optional[str],
        source: str = "skill",
    ) -> str:
        if not self.available:
            raise RuntimeError(
                "Skill scripts require a Docker sandbox, but the configured sandbox executor is unavailable"
            )

        normalized_source = (source or "skill").strip().lower()
        skill_python_path = ""
        if normalized_source == "skill":
            skills_root = self._resolve_skills_root(working_directory)
            sandbox_script, normalized_script = self._stage_skill(
                manager,
                skill_name,
                script_path,
                tenant_id,
                skills_root,
            )
            skill_python_path = sandbox_script[: -(len(normalized_script) + 1)]
            if normalized_script.endswith(".sh"):
                # Some third-party skill archives store shell scripts with
                # CRLF line endings. Preserve the uploaded source and only
                # normalize the run-scoped, read-only staging copy.
                self._run_container_command(
                    ["sed", "-i", "s/\\r$//", sandbox_script],
                    user="0",
                )
            interpreter_args = [
                "python" if normalized_script.endswith(".py") else "bash",
                sandbox_script,
            ]
        elif normalized_source == "workspace":
            sandbox_script, normalized_script = self._resolve_workspace_script(
                script_path,
                working_directory,
            )
            if normalized_script.endswith(".py"):
                self._validate_workspace_python(sandbox_script)
                skills_root = self._resolve_skills_root(working_directory)
                local_skill_dir = manager.resolve_skill_dir(
                    skill_name,
                    tenant_id=tenant_id,
                )
                if not Path(local_skill_dir).is_dir():
                    raise FileNotFoundError(f"Skill not found: {skill_name}")
                skill_python_path = self._stage_skill_directory(
                    local_skill_dir,
                    skill_name,
                    skills_root,
                )
                interpreter_args = ["python", sandbox_script]
            else:
                workspace_path = (working_directory or self._workspace_path).rstrip("/")
                interpreter_args = [
                    "node",
                    "--experimental-permission",
                    "--allow-addons",
                    f"--allow-fs-read={workspace_path}",
                    "--allow-fs-read=/opt/nexent/node_modules",
                    "--allow-fs-read=/usr/local/lib/node_modules",
                    f"--allow-fs-write={workspace_path}",
                    sandbox_script,
                ]
        else:
            raise ValueError("source must be either 'skill' or 'workspace'")

        command = [
            "timeout",
            "--signal=KILL",
            str(self._timeout_seconds),
            *interpreter_args,
            *shlex.split(params or ""),
        ]
        if working_directory:
            workspace_dir = working_directory.rstrip("/")
            output_dir = f"{workspace_dir}/outputs"
        elif self._workspace_path:
            workspace_dir = self._workspace_path
            output_dir = f"{workspace_dir}/outputs"
        else:
            workspace_dir = "/home/sandbox/workdir"
            output_dir = "/home/sandbox/workdir/output"
        self._ensure_output_directory(output_dir)
        execution_environment = {
            "NEXENT_WORKSPACE": workspace_dir,
            "NEXENT_OUTPUT_DIR": output_dir,
            "NODE_PATH": "/opt/nexent/node_modules:/usr/local/lib/node_modules",
            "PNPM_CONFIG_OFFLINE": "false" if self._network_enabled else "true",
            "npm_config_offline": "false" if self._network_enabled else "true",
            "COREPACK_ENABLE_NETWORK": "1" if self._network_enabled else "0",
            "PNPM_CONFIG_STORE_DIR": (
                self._resolve_network_pnpm_store(workspace_dir)
                if self._network_enabled
                else SANDBOX_PNPM_STORE_PATH
            ),
            # pnpm follows npm's environment-variable convention for this
            # option. Keep the uppercase key for compatibility, but use the
            # npm_config spelling to make the per-run store effective.
            "npm_config_store_dir": (
                self._resolve_network_pnpm_store(workspace_dir)
                if self._network_enabled
                else SANDBOX_PNPM_STORE_PATH
            ),
            "PIP_USER": "1",
            "PYTHONPATH": ":".join(
                path
                for path in (
                    skill_python_path,
                    "/home/sandbox/.local/lib/python3.11/site-packages",
                )
                if path
            ),
        }
        if self._network_enabled and interpreter_args[0] == "bash":
            self._ensure_network_pnpm_store(workspace_dir)
        result = self._container.exec_run(
            command,
            user="sandbox",
            workdir=output_dir,
            environment=execution_environment,
            demux=True,
        )
        exit_code = getattr(result, "exit_code", None)
        raw_output = getattr(result, "output", b"")
        if isinstance(raw_output, tuple):
            stdout, stderr = raw_output
        else:
            stdout, stderr = raw_output, b""
        output = self._output_text(stdout)
        error_output = self._output_text(stderr)
        if exit_code == 124 or exit_code == 137:
            raise TimeoutError(f"Script execution timed out: {normalized_script}")
        if exit_code != 0:
            failure_message = error_output or output
            logger.error(
                "Sandbox skill script failed skill=%s script=%s exit=%s output=%s",
                skill_name,
                normalized_script,
                exit_code,
                failure_message,
            )
            return json.dumps({
                "error": failure_message,
                "output": output if error_output else "",
            })
        logger.info(
            "Sandbox skill script completed source=%s skill=%s script=%s interpreter=%s exit=%s",
            normalized_source,
            skill_name,
            normalized_script,
            interpreter_args[0],
            exit_code,
        )
        return output

    def _resolve_network_pnpm_store(self, workspace_dir: str) -> str:
        """Return a writable, container-private pnpm store for one agent run."""
        store_key = hashlib.sha256(workspace_dir.encode("utf-8")).hexdigest()[:24]
        expected_path = f"/tmp/nexent-pnpm-stores/{store_key}"
        if self._pnpm_store_path and self._pnpm_store_path != expected_path:
            raise RuntimeError("pnpm store path does not match the sandbox runner workspace")
        self._pnpm_store_path = expected_path
        return expected_path

    def _ensure_network_pnpm_store(self, workspace_dir: str) -> None:
        """Seed a run-private writable pnpm store from the full image cache."""
        store_path = self._resolve_network_pnpm_store(workspace_dir)
        if self._pnpm_store_seeded:
            return
        self._run_container_command(
            ["mkdir", "-p", "/tmp/nexent-pnpm-stores"],
            user="0",
        )
        source_check = self._container.exec_run(
            ["test", "-d", f"{SANDBOX_PNPM_STORE_SOURCE}/v3"],
            user="0",
        )
        if getattr(source_check, "exit_code", None) == 0:
            self._run_container_command(
                [
                    "cp",
                    "-a",
                    "--reflink=auto",
                    f"{SANDBOX_PNPM_STORE_SOURCE}/.",
                    store_path,
                ],
                user="0",
            )
        else:
            self._run_container_command(["mkdir", "-p", store_path], user="0")
        self._run_container_command(
            ["chown", "-R", "sandbox:sandbox", store_path],
            user="0",
        )
        self._pnpm_store_seeded = True

    def cleanup(self) -> None:
        """Remove this run's private skill copy from a shared container."""
        if not self.available:
            return
        if not self._root:
            return
        try:
            # Docker archive extraction may preserve root ownership on nested
            # skill directories. Cleanup is a control-plane operation against
            # an exact runner-generated path, so use root and verify the result
            # instead of silently leaving data in a system-scoped container.
            result = self._container.exec_run(
                ["rm", "-rf", "--", self._root],
                user="0",
            )
            exit_code = getattr(result, "exit_code", None)
            if exit_code != 0:
                output = self._output_text(getattr(result, "output", b""))
                logger.warning(
                    "Failed to remove sandbox skill directory %s (exit=%s): %s",
                    self._root,
                    exit_code,
                    output.strip(),
                )
        except Exception as exc:
            logger.warning("Failed to remove sandbox skill directory %s: %s", self._root, exc)
        if self._pnpm_store_path:
            try:
                result = self._container.exec_run(
                    ["rm", "-rf", "--", self._pnpm_store_path],
                    user="0",
                )
                if getattr(result, "exit_code", None) != 0:
                    logger.warning(
                        "Failed to remove sandbox pnpm store %s (exit=%s)",
                        self._pnpm_store_path,
                        getattr(result, "exit_code", None),
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to remove sandbox pnpm store %s: %s",
                    self._pnpm_store_path,
                    exc,
                )


def _serialize_tool_bridge_value(value: Any) -> Any:
    """Convert host-tool results into a lossless JSON-compatible value."""
    try:
        from smolagents.agent_types import AgentAudio, AgentImage
    except ImportError:  # pragma: no cover - smolagents is a runtime dependency
        AgentAudio = AgentImage = ()

    if AgentImage and isinstance(value, AgentImage):
        value = value.to_raw()

    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow is a smolagents dependency
        Image = None

    if Image is not None and isinstance(value, Image.Image):
        buffer = io.BytesIO()
        value.save(buffer, format="PNG")
        return {
            _TOOL_BRIDGE_VALUE_MARKER: 1,
            "kind": "image",
            "mime_type": "image/png",
            "encoding": "base64",
            "data": base64.b64encode(buffer.getvalue()).decode("ascii"),
        }

    # AgentAudio inherits from str, so it must be handled before primitive strings.
    if AgentAudio and isinstance(value, AgentAudio):
        audio_location = str(value.to_string())
        audio_path = Path(audio_location)
        if audio_path.is_file():
            mime_type = mimetypes.guess_type(audio_path.name)[0] or "audio/wav"
            return {
                _TOOL_BRIDGE_VALUE_MARKER: 1,
                "kind": "audio",
                "mime_type": mime_type,
                "encoding": "base64",
                "data": base64.b64encode(audio_path.read_bytes()).decode("ascii"),
            }
        return audio_location

    if isinstance(value, (bytes, bytearray, memoryview)):
        return {
            _TOOL_BRIDGE_VALUE_MARKER: 1,
            "kind": "binary",
            "mime_type": "application/octet-stream",
            "encoding": "base64",
            "data": base64.b64encode(bytes(value)).decode("ascii"),
        }
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _serialize_tool_bridge_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_tool_bridge_value(item) for item in value]

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _serialize_tool_bridge_value(model_dump(mode="json"))

    raise TypeError(
        f"Host tool returned unsupported result type: {type(value).__module__}.{type(value).__name__}"
    )


def _deserialize_tool_bridge_value(value: Any, tools: dict[str, Any]) -> Any:
    """Restore bridge-owned references in arguments received from a sandbox."""
    if (
        isinstance(value, dict)
        and value.get(_TOOL_BRIDGE_VALUE_MARKER) == 1
        and value.get("kind") == "tool_reference"
    ):
        tool_name = value.get("name")
        if not isinstance(tool_name, str) or tool_name not in tools:
            raise ValueError(f"Unknown local tool reference: {tool_name}")
        return tools[tool_name]
    if isinstance(value, dict):
        return {
            key: _deserialize_tool_bridge_value(item, tools)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_deserialize_tool_bridge_value(item, tools) for item in value]
    return value


# ----------------------------------------------------------------------
# smolagents logger compatibility adapter
# ----------------------------------------------------------------------


class _LogLevel(IntEnum):
    """Minimal LogLevel enum compatible with smolagents.monitoring.LogLevel."""

    OFF = -1
    ERROR = 0
    INFO = 1
    DEBUG = 2


class _AgentLoggerAdapter:
    """
    Thin adapter that satisfies ``smolagents.AgentLogger``'s ``.log(*args, level=...)``
    call signature while routing output through the standard ``logging.Logger``.

    ``DockerExecutor`` (and other remote executors) call::

        self.logger.log("message", level=LogLevel.INFO)

    Standard ``logging.Logger`` uses::

        logger.log(level, "message")   # positional: (int, str)

    This adapter bridges the two by accepting the smolagents signature and
    forwarding to the underlying logger with the correct argument order.
    """

    def __init__(self, delegate: logging.Logger) -> None:
        self._delegate = delegate
        self._level_map = {
            _LogLevel.OFF: logging.CRITICAL + 1,
            _LogLevel.ERROR: logging.ERROR,
            _LogLevel.INFO: logging.INFO,
            _LogLevel.DEBUG: logging.DEBUG,
        }

    def log(self, *args: Any, level: int | str | _LogLevel = _LogLevel.INFO, **kwargs: Any) -> None:
        """smolagents-compatible log(): first positional arg is the message."""
        if isinstance(level, str):
            level = _LogLevel[level.upper()]
        numeric = self._level_map.get(_LogLevel(int(level)), logging.INFO)
        if self._delegate.isEnabledFor(numeric):
            # ``*args`` contains the message(s) from smolagents AgentLogger;
            # ``self._delegate.log`` expects (level, msg) — swap argument order.
            self._delegate.log(numeric, " ".join(str(a) for a in args), **kwargs)

    def log_error(self, message: str) -> None:
        self._delegate.error(message)


def _make_smolagents_logger(logger_: logging.Logger) -> _AgentLoggerAdapter:
    """Wrap a standard Logger into an AgentLogger-compatible adapter."""
    return _AgentLoggerAdapter(logger_)


# ----------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------


class SandboxLevel(str, Enum):
    """Sandbox isolation level, ordered by increasing security."""

    LOCAL = "local"
    DOCKER = "docker"
    WASM = "wasm"


class SandboxScope(str, Enum):
    """
    Container lifecycle scope — controls when a sandbox container is created
    and destroyed.

    - SESSION (default): one container per agent_run, destroyed when the run ends.
      Provides strict multi-tenant isolation between concurrent runs.

    - SYSTEM: a persistent Docker container shared by all agent runs system-wide.
      Each run receives a dedicated Jupyter kernel in that container, so kernel
      state is isolated between concurrent runs while container cold-start is
      avoided. The container remains until application shutdown or failure.
    """

    SESSION = "session"
    SYSTEM = "system"


class ShellPolicy(str, Enum):
    """
    Shell command execution policy inside the sandbox container.

    - DISABLED (recommended default): blocks ``subprocess`` and ``os`` shell
      invocations at AST-parse time before they reach the container.

    - RESTRICTED: V2 — allows only an explicit command allowlist.

    - BOXED: no interception; container filesystem isolation is the only
      guard.  NOT recommended for multi-tenant deployments.
    """

    DISABLED = "disabled"
    RESTRICTED = "restricted"
    BOXED = "boxed"


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------


@dataclass
class SandboxConfig:
    """
    Sandbox execution configuration, injected by the backend service layer.

    Every field is optional; defaults match the existing process-local behaviour
    so that an all-None / all-default config is equivalent to leaving sandboxing
    disabled.
    """

    level: SandboxLevel = SandboxLevel.LOCAL
    scope: SandboxScope = SandboxScope.SESSION
    docker_image: str = "nexent/nexent-sandbox:latest"
    memory_limit_mb: int = 2048
    cpu_quota: float = 1.0
    network_disabled: bool = True
    timeout_seconds: int = 120
    host_tool_timeout_seconds: Optional[float] = None
    shell_policy: ShellPolicy = ShellPolicy.DISABLED
    output_dir: str = "/home/sandbox/workdir/output"
    auto_sync_outputs: bool = True
    extra_kwargs: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[dict[str, Any]]) -> "SandboxConfig":
        """Build a SandboxConfig from a plain dict (e.g. from AgentConfig.sandbox_policy)."""
        if not data:
            return cls()
        host_tool_timeout_raw = data.get("host_tool_timeout_seconds")
        host_tool_timeout_seconds = None
        if host_tool_timeout_raw not in (None, ""):
            parsed_timeout = float(host_tool_timeout_raw)
            if parsed_timeout > 0:
                host_tool_timeout_seconds = parsed_timeout
        return cls(
            level=SandboxLevel(data.get("level", "local")),
            scope=SandboxScope(data.get("scope", "session")),
            docker_image=data.get("docker_image", "nexent/nexent-sandbox:latest"),
            memory_limit_mb=int(data.get("memory_limit_mb", 2048)),
            cpu_quota=float(data.get("cpu_quota", 1.0)),
            network_disabled=bool(data.get("network_disabled", True)),
            timeout_seconds=int(data.get("timeout_seconds", 120)),
            host_tool_timeout_seconds=host_tool_timeout_seconds,
            shell_policy=ShellPolicy(data.get("shell_policy", "disabled")),
            output_dir=data.get("output_dir", "/home/sandbox/workdir/output"),
            auto_sync_outputs=bool(data.get("auto_sync_outputs", True)),
            extra_kwargs=data.get("extra_kwargs", {}),
        )


# ----------------------------------------------------------------------
# Shell-call interceptor (§6.B)
# ----------------------------------------------------------------------

_FORBIDDEN_SHELL_CALLS = {
    "subprocess": {
        "run", "call", "check_call", "check_output",
        "Popen", "getoutput", "getstatusoutput",
    },
    "os": {
        "system", "popen", "execv", "execve", "execvp",
        "spawnl", "spawnv", "spawnlp", "spawnvp",
    },
}


def _is_allowed_pip_install_call(node: ast.Call) -> bool:
    """Return whether a subprocess call is a shell-free pip install argv."""
    if not node.args or not isinstance(node.args[0], (ast.List, ast.Tuple)):
        return False
    for keyword in node.keywords:
        if keyword.arg in {"cwd", "env", "executable", "preexec_fn"}:
            return False
        if keyword.arg == "shell" and not (
            isinstance(keyword.value, ast.Constant) and keyword.value.value is False
        ):
            return False

    argv_nodes = list(node.args[0].elts)
    if not argv_nodes:
        return False
    argv: list[str] = []
    for index, value in enumerate(argv_nodes):
        if (
            index == 0
            and isinstance(value, ast.Attribute)
            and isinstance(value.value, ast.Name)
            and value.value.id == "sys"
            and value.attr == "executable"
        ):
            argv.append("<python>")
        elif isinstance(value, ast.Constant) and isinstance(value.value, str):
            argv.append(value.value)
        else:
            return False

    normalized = [value.lower() for value in argv]
    if normalized[0] == "<python>":
        return len(normalized) >= 5 and normalized[1:4] == ["-m", "pip", "install"]
    executable = normalized[0].replace("\\", "/").rsplit("/", 1)[-1]
    if executable in {"pip", "pip3"}:
        return len(normalized) >= 3 and normalized[1] == "install"
    if executable.startswith("python"):
        return len(normalized) >= 5 and normalized[1:4] == ["-m", "pip", "install"]
    return False


def _scan_shell_calls(
    code: str,
    *,
    allow_package_installs: bool = False,
) -> list[str]:
    """AST static scan for forbidden subprocess / os shell invocations."""
    stripped_lines = [line.strip() for line in code.splitlines() if line.strip()]
    magic_violations = []
    for line in stripped_lines:
        if line.startswith("!"):
            magic_violations.append("IPython shell escape (!...)")
        elif re.match(r"^%(?:system|sx|sc)\b", line, flags=re.IGNORECASE):
            magic_violations.append("IPython shell magic")
        elif re.match(r"^%%(?:bash|sh|script)\b", line, flags=re.IGNORECASE):
            magic_violations.append("IPython shell cell magic")

    try:
        tree = ast.parse(code)
    except SyntaxError:
        # IPython magics such as `%pip install` are not valid Python AST. They
        # remain available for dependency installation, while explicit shell
        # escapes are rejected above.
        return magic_violations

    violations = list(magic_violations)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            attr = func.attr
            if isinstance(func.value, ast.Name):
                module = func.value.id
                if module in _FORBIDDEN_SHELL_CALLS and attr in _FORBIDDEN_SHELL_CALLS[module]:
                    if (
                        allow_package_installs
                        and module == "subprocess"
                        and attr in {"run", "check_call", "check_output"}
                        and _is_allowed_pip_install_call(node)
                    ):
                        continue
                    violations.append(f"{module}.{attr}(...)")
            if (
                isinstance(func.value, ast.Call)
                and isinstance(func.value.func, ast.Name)
                and func.value.func.id == "get_ipython"
                and attr in {"system", "getoutput"}
            ):
                violations.append(f"get_ipython().{attr}(...)")
    return violations


def _install_shell_guard(
    executor: Any,
    policy: ShellPolicy,
    logger_: logging.Logger,
    *,
    allow_package_installs: bool = False,
) -> Any:
    """
    Install an AST-based guard that intercepts subprocess / os shell calls
    before they reach the sandbox container.

    This runs in the host process, scanning the code string BEFORE it is
    sent over the wire to the container. Combined with a non-root UID and the
    configured container network policy, defence-in-depth is achieved.
    """
    if getattr(executor, "_nexent_shell_guard_installed", False):
        return executor
    if policy == ShellPolicy.BOXED:
        return executor  # BOXED means no interception

    original_call = executor.__call__

    def wrapped_call(code: str) -> Any:
        violations = _scan_shell_calls(
            code,
            allow_package_installs=allow_package_installs,
        )
        if violations:
            logger_.warning(
                "Sandbox shell guard blocked %d call(s): %s",
                len(violations),
                violations,
            )
            message = (
                "SecurityError: this shell command is not permitted by the sandbox policy.\n"
                "Detected: " + ", ".join(violations) + "\n"
                "Suggestion: when network access is enabled, install Python packages with a "
                "shell-free `subprocess` pip-install argv or `%pip install`; otherwise use an "
                "approved Nexent tool or pure Python.\n"
                "To enable shell access, configure sandbox_policy.shell_policy='restricted' "
                "and supply an explicit command allowlist."
            )
            return _make_code_output(message)
        return original_call(code)

    executor.__call__ = wrapped_call
    executor._nexent_shell_guard_installed = True
    return executor


def _make_code_output(logs: str) -> Any:
    """Return the executor result shape expected by the agent runtime."""
    try:
        from smolagents.remote_executors import CodeOutput

        return CodeOutput(output=None, logs=logs, is_final_answer=False)
    except ImportError:
        return SimpleNamespace(output=None, logs=logs, is_final_answer=False)


_ONLINE_USER_SITE_BOOTSTRAP = (
    "import importlib as _nexent_importlib, site as _nexent_site, sys as _nexent_sys\n"
    "_nexent_user_site = _nexent_site.getusersitepackages()\n"
    "(_nexent_sys.path.insert(0, _nexent_user_site) "
    "if _nexent_user_site not in _nexent_sys.path else None)\n"
    "_nexent_sys.path_importer_cache.pop(_nexent_user_site, None)\n"
    "_nexent_importlib.invalidate_caches()\n"
)


def _install_online_user_site(executor: Any) -> Any:
    """Keep runtime-installed user packages importable in the active kernel."""
    if getattr(executor, "_nexent_online_user_site_installed", False):
        return executor

    original_call = executor.__call__

    def wrapped_call(code: str) -> Any:
        return original_call(_ONLINE_USER_SITE_BOOTSTRAP + code)

    executor.__call__ = wrapped_call
    executor._nexent_online_user_site_installed = True
    return executor


# ----------------------------------------------------------------------
# Host tool bridge for remote code executors
# ----------------------------------------------------------------------


def _is_host_tool(tool: Any) -> bool:
    """Return whether a tool must execute in the Nexent host process."""
    return bool(getattr(tool, "_nexent_execute_on_host", False))


class _ToolBridge:
    """Token-authenticated HTTP bridge from a sandbox to live host tools."""

    def __init__(
        self,
        logger_: logging.Logger,
        request_timeout_seconds: Optional[float] = None,
    ) -> None:
        self._logger = logger_
        if isinstance(request_timeout_seconds, bool):
            raise ValueError("Host tool timeout must be a positive number or None")
        if request_timeout_seconds is not None:
            request_timeout_seconds = float(request_timeout_seconds)
            if request_timeout_seconds <= 0:
                raise ValueError("Host tool timeout must be a positive number or None")
        self._request_timeout_seconds = request_timeout_seconds
        self._token = secrets.token_urlsafe(32)
        self._tools: dict[str, Any] = {}
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                if self.path != "/invoke" or not hmac.compare_digest(
                    self.headers.get("Authorization", ""),
                    f"Bearer {bridge._token}",
                ):
                    self.send_error(403)
                    return
                try:
                    content_length = int(self.headers.get("Content-Length", "0"))
                    if content_length <= 0 or content_length > 1024 * 1024:
                        raise ValueError("Invalid request size")
                    payload = json.loads(self.rfile.read(content_length))
                    tool_name = payload.get("tool")
                    tool = bridge._tools.get(tool_name)
                    if tool is None:
                        raise ValueError(f"Unknown local tool: {tool_name}")
                    args = _deserialize_tool_bridge_value(
                        payload.get("args", []), bridge._tools
                    )
                    kwargs = _deserialize_tool_bridge_value(
                        payload.get("kwargs", {}), bridge._tools
                    )
                    result = tool(*args, **kwargs)
                    serialized_result = _serialize_tool_bridge_value(result)
                    body = json.dumps({"result": serialized_result}, ensure_ascii=False).encode("utf-8")
                    self.send_response(200)
                except Exception as exc:
                    bridge._logger.exception("Local tool bridge invocation failed")
                    body = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
                    self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                bridge._logger.debug("Tool bridge: " + format, *args)

        self._server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
        self.port = self._server.server_port
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="NexentToolBridge",
        )
        self._thread.start()

    def register(self, tools: dict[str, Any]) -> None:
        self._tools = dict(tools)

    def _bridge_host(self) -> str:
        """Return the runtime address reachable from the sandbox container."""
        return "nexent-runtime" if _is_containerized_runtime() else "host.docker.internal"

    def proxy_code(self, tools: dict[str, Any], bridge_host: Optional[str] = None) -> str:
        definitions = []
        for name in tools:
            definitions.append(
                f"def {name}(*args, **kwargs):\n"
                f"    return _nexent_call_host_tool({name!r}, args, kwargs)\n"
                f"{name}._nexent_tool_bridge_name = {name!r}"
            )
        host = bridge_host or self._bridge_host()
        return (
            "import base64 as _nexent_base64\n"
            "import io as _nexent_io\n"
            "import json as _nexent_json\n"
            "import urllib.request as _nexent_urllib\n"
            "import urllib.error as _nexent_urllib_error\n"
            "class _NexentBridgedMedia:\n"
            "    def __init__(self, data, mime_type):\n"
            "        self.data = data\n"
            "        self.mime_type = mime_type\n"
            "    def save(self, destination, *args, **kwargs):\n"
            "        if hasattr(destination, 'write'):\n"
            "            destination.write(self.data)\n"
            "        else:\n"
            "            with open(destination, 'wb') as output_file:\n"
            "                output_file.write(self.data)\n"
            "    def to_bytes(self):\n"
            "        return self.data\n"
            "def _nexent_decode_tool_bridge_value(value):\n"
            f"    if isinstance(value, dict) and value.get({_TOOL_BRIDGE_VALUE_MARKER!r}) == 1:\n"
            "        raw = _nexent_base64.b64decode(value['data'])\n"
            "        kind = value.get('kind')\n"
            "        if kind == 'image':\n"
            "            try:\n"
            "                from PIL import Image as _nexent_pil_image\n"
            "                image = _nexent_pil_image.open(_nexent_io.BytesIO(raw))\n"
            "                image.load()\n"
            "                return image\n"
            "            except ImportError:\n"
            "                return _NexentBridgedMedia(raw, value.get('mime_type'))\n"
            "        if kind == 'binary':\n"
            "            return raw\n"
            "        return _NexentBridgedMedia(raw, value.get('mime_type'))\n"
            "    if isinstance(value, dict):\n"
            "        return {key: _nexent_decode_tool_bridge_value(item) for key, item in value.items()}\n"
            "    if isinstance(value, list):\n"
            "        return [_nexent_decode_tool_bridge_value(item) for item in value]\n"
            "    return value\n"
            "def _nexent_encode_tool_bridge_value(value):\n"
            "    tool_name = getattr(value, '_nexent_tool_bridge_name', None)\n"
            "    if isinstance(tool_name, str):\n"
            f"        return {{{_TOOL_BRIDGE_VALUE_MARKER!r}: 1, 'kind': 'tool_reference', 'name': tool_name}}\n"
            "    raise TypeError(\n"
            "        'Object of type ' + type(value).__name__ + ' is not JSON serializable'\n"
            "    )\n"
            f"_NEXENT_TOOL_BRIDGE_URL = 'http://{host}:{self.port}/invoke'\n"
            f"_NEXENT_TOOL_BRIDGE_TOKEN = {self._token!r}\n"
            f"_NEXENT_TOOL_BRIDGE_TIMEOUT = {self._request_timeout_seconds!r}\n"
            "def _nexent_call_host_tool(name, args, kwargs):\n"
            "    payload = _nexent_json.dumps(\n"
            "        {'tool': name, 'args': args, 'kwargs': kwargs},\n"
            "        default=_nexent_encode_tool_bridge_value,\n"
            "    ).encode('utf-8')\n"
            "    request = _nexent_urllib.Request(_NEXENT_TOOL_BRIDGE_URL, data=payload, headers={\n"
            "        'Authorization': 'Bearer ' + _NEXENT_TOOL_BRIDGE_TOKEN,\n"
            "        'Content-Type': 'application/json',\n"
            "    })\n"
            "    try:\n"
            "        with _nexent_urllib.urlopen(request, timeout=_NEXENT_TOOL_BRIDGE_TIMEOUT) as response:\n"
            "            result = _nexent_json.loads(response.read().decode('utf-8'))\n"
            "    except _nexent_urllib_error.HTTPError as exc:\n"
            "        try:\n"
            "            error_result = _nexent_json.loads(exc.read().decode('utf-8'))\n"
            "            error_message = error_result.get('error') or str(exc)\n"
            "        except Exception:\n"
            "            error_message = str(exc)\n"
            "        raise RuntimeError('Local tool bridge request failed: ' + error_message) from exc\n"
            "    except Exception as exc:\n"
            "        raise RuntimeError('Local tool bridge request failed: ' + str(exc)) from exc\n"
            "    if 'error' in result:\n"
            "        raise RuntimeError(result['error'])\n"
            "    return _nexent_decode_tool_bridge_value(result.get('result'))\n\n"
            + "\n\n".join(definitions)
        )

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def _install_host_tool_bridge(
    executor: Any,
    logger_: logging.Logger,
    request_timeout_seconds: Optional[float] = None,
) -> Any:
    """Keep Nexent tools local while code runs in a remote executor."""
    if getattr(executor, "_nexent_tool_bridge_installed", False):
        return executor

    bridge = _ToolBridge(logger_, request_timeout_seconds=request_timeout_seconds)
    original_send_tools = executor.send_tools
    original_cleanup = getattr(executor, "cleanup", None)

    def send_tools(tools: dict[str, Any]) -> None:
        host_tools = {name: tool for name, tool in tools.items() if _is_host_tool(tool)}
        remote_tools = {name: tool for name, tool in tools.items() if name not in host_tools}
        original_send_tools(remote_tools)
        if host_tools:
            bridge.register(host_tools)
            bridge_host = (
                bridge._bridge_host()
                if getattr(executor, "container", None) is not None
                else "127.0.0.1"
            )
            proxy_code = bridge.proxy_code(host_tools, bridge_host)
            register_bootstrap = (
                getattr(executor, "register_kernel_bootstrap_code", None)
                if getattr(executor, "_nexent_kernel_recovery_supported", False)
                else None
            )
            if callable(register_bootstrap):
                output = register_bootstrap(proxy_code)
            else:
                output = executor.run_code_raise_errors(proxy_code)
            logger_.debug("Registered %d host tool proxy/proxies: %s", len(host_tools), sorted(host_tools))
            if getattr(output, "logs", None):
                logger_.debug("Host tool proxy registration output: %s", output.logs)

    def cleanup() -> None:
        try:
            bridge.close()
        finally:
            if callable(original_cleanup):
                original_cleanup()

    executor.send_tools = send_tools
    executor.cleanup = cleanup
    executor._nexent_tool_bridge = bridge
    executor._nexent_tool_bridge_installed = True
    return executor


# ----------------------------------------------------------------------
# ModuleNotFoundError friendly diagnostic (§6.5)
# ----------------------------------------------------------------------

_MISSING_PKG_RE = re.compile(r"No module named ['\"]([^'\"]+)['\"]")

_PACKAGE_LIST_NOTE = (
    "Nexent sandbox image provides the standard packages listed at:\n"
    "  doc/docs/zh/backend/sandbox-design.md#64\n"
    "Please try: (1) use a pre-installed package; "
    "(2) when sandbox network access is enabled, install a Python dependency "
    "with `%pip install --user <package>` and retry; "
    "(3) implement the logic with Python stdlib; "
    "(4) call a Nexent tool instead of a raw import."
)


def _wrap_with_diagnostics(executor: Any, logger_: logging.Logger) -> Any:
    """
    Wrap ``executor.__call__`` so that ``ModuleNotFoundError`` is converted
    into an LLM-friendly diagnostic message that guides the model towards
    an alternative approach.
    """
    if getattr(executor, "_nexent_diagnostics_wrapped", False):
        return executor

    original_call = executor.__call__

    def wrapped_call(code: str) -> Any:
        try:
            return original_call(code)
        except ModuleNotFoundError as e:
            missing = _MISSING_PKG_RE.search(str(e))
            pkg = missing.group(1) if missing else "unknown"
            logger_.info(
                "Sandbox execution hit missing package '%s'. "
                "Returning dependency-install guidance to the LLM.",
                pkg,
            )
            return (
                f"ModuleNotFoundError: {pkg}\n" + _PACKAGE_LIST_NOTE
            )

    executor.__call__ = wrapped_call
    executor._nexent_diagnostics_wrapped = True
    return executor


# ----------------------------------------------------------------------
# Output file sync to MinIO (§6.A.3)
# ----------------------------------------------------------------------

_MAX_OUTPUT_FILE_BYTES = 100 * 1024 * 1024  # 100 MB


def _sync_outputs_to_minio(
    output_dir: str,
    agent_run_id: str,
    minio_client: Any,
    bucket: str,
    logger_: logging.Logger,
) -> list[dict]:
    """
    Scan ``output_dir`` inside the sandbox container and upload every file to MinIO.

    Must be called BEFORE ``cleanup_executor`` because the container filesystem
    is inaccessible after the container is destroyed.

    Args:
        output_dir: absolute path inside the sandbox container.
        agent_run_id: unique ID of this agent run.
        minio_client: object that exposes ``put_object(bucket, key, data, length)``.
        bucket: MinIO bucket name.
        logger_: logger instance.

    Returns:
        List of uploaded file descriptors (name / size / sha256 / minio_key).
    """
    out_path = Path(output_dir)
    if not out_path.exists():
        return []

    uploaded = []
    prefix = f"agent-runs/{agent_run_id}/output"

    for path in out_path.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(out_path)
        size = path.stat().st_size
        if size == 0 or size > _MAX_OUTPUT_FILE_BYTES:
            logger_.warning(
                "Skipping output file (size=%d): %s",
                size,
                rel,
            )
            continue

        with open(path, "rb") as f:
            data = f.read()
        digest = hashlib.sha256(data).hexdigest()
        object_key = f"{prefix}/{rel}"

        try:
            minio_client.put_object(
                bucket=bucket,
                key=object_key,
                data=data,
                length=len(data),
            )
            uploaded.append({
                "name": str(rel),
                "size": size,
                "sha256": digest,
                "minio_key": object_key,
            })
            logger_.info(
                "Output synced to MinIO: %s (%d bytes)",
                object_key,
                size,
            )
        except Exception as exc:
            logger_.error("MinIO upload failed for %s: %s", rel, exc)

    return uploaded


# ----------------------------------------------------------------------
# Three-layer cleanup (§12)
# ----------------------------------------------------------------------


def cleanup_executor(executor: Any, logger_: logging.Logger, timeout: float = 5.0) -> None:
    """
    Guaranteed-safe sandbox executor cleanup (three layers).

    1. Graceful ``executor.cleanup()`` with a 5-second timeout.
    2. Force-kill the underlying Docker container (if present).
    3. GC fallback.
    """
    if executor is None:
        return

    cleanup_fn = getattr(executor, "cleanup", None)
    if not callable(cleanup_fn):
        return

    try:
        with ThreadPoolExecutor(max_workers=1) as tp:
            future = tp.submit(cleanup_fn)
            future.result(timeout=timeout)
        logger_.debug("Sandbox cleanup succeeded (graceful)")
        return
    except FuturesTimeoutError:
        logger_.warning(
            "Sandbox cleanup timed out (>%.1fs), forcing close",
            timeout,
        )
    except Exception as exc:
        logger_.warning("Sandbox cleanup failed: %s", exc)

    # Layer 2: force-kill Docker container
    try:
        container_attr = getattr(executor, "container", None)
        if container_attr is not None:
            kill_fn = getattr(container_attr, "kill", None)
            if callable(kill_fn):
                kill_fn()
                logger_.info("Sandbox container force-killed")
    except Exception:
        pass

    # Layer 3: GC fallback
    logger_.debug("Sandbox cleanup: GC fallback after force-kill")


# ----------------------------------------------------------------------
# SandboxPoolManager — system-scoped container pool
# ----------------------------------------------------------------------


SANDBOX_CONTAINER_NAME = "nexent-runtime-sandbox"
SANDBOX_NETWORK_NAME = "nexent_sandbox_control"
SANDBOX_JUPYTER_PORT = 8888
SANDBOX_SESSION_CONTAINER_PREFIX = "nexent-runtime-sandbox-session"
SANDBOX_PNPM_STORE_SOURCE = "/opt/nexent/pnpm-store"
SANDBOX_PNPM_STORE_PATH = "/mnt/nexent/workdir/.pnpm-store"
_DOCKER_CLONE3_SECCOMP_MIN_VERSION = (20, 10, 10)
_ONLINE_PACKAGE_ENV = {
    "PNPM_CONFIG_OFFLINE": "false",
    "npm_config_offline": "false",
    "COREPACK_ENABLE_NETWORK": "1",
    "PIP_USER": "1",
    "PYTHONPATH": "/home/sandbox/.local/lib/python3.11/site-packages",
    "PATH": (
        "/home/sandbox/.local/bin:/usr/local/bin:/usr/local/sbin:"
        "/usr/sbin:/usr/bin:/sbin:/bin"
    ),
}


def _is_containerized_runtime() -> bool:
    """Return whether the current runtime is running inside a Docker container."""
    return Path("/.dockerenv").exists()


def _docker_bridge_gateway(client: Any) -> str:
    """Return the Docker host IPv4 address without requiring ``host-gateway``.

    Docker Engine versions before 20.10 do not understand the special
    ``host-gateway`` value in ``ExtraHosts``. The default bridge gateway is the
    equivalent concrete host address and is supported by older daemons.
    """
    network = client.networks.get("bridge")
    network.reload()
    ipam_configs = ((network.attrs or {}).get("IPAM") or {}).get("Config") or []
    for config in ipam_configs:
        gateway = config.get("Gateway")
        if not gateway:
            continue
        try:
            if ipaddress.ip_address(gateway).version == 4:
                return gateway
        except ValueError:
            continue
    raise RuntimeError("Docker bridge network does not expose an IPv4 gateway")


def _apply_legacy_docker_seccomp_compatibility(
    client: Any,
    container_run_kwargs: dict[str, Any],
    logger_: logging.Logger,
) -> None:
    """Disable seccomp only for Docker versions whose default profile blocks clone3."""
    try:
        server_version = str(client.version()["Version"])
        version_match = re.match(r"^(\d+)\.(\d+)\.(\d+)", server_version)
        if version_match is None:
            raise ValueError(f"unrecognized Docker server version: {server_version}")
        parsed_version = tuple(int(part) for part in version_match.groups())
    except Exception as exc:
        logger_.warning(
            "Could not determine Docker server version; preserving the default seccomp profile: %s",
            exc,
        )
        return

    if parsed_version < _DOCKER_CLONE3_SECCOMP_MIN_VERSION:
        container_run_kwargs["security_opt"] = ["seccomp=unconfined"]
        logger_.warning(
            "Docker server %s predates clone3 support in the default seccomp profile; "
            "starting the sandbox with seccomp=unconfined for compatibility",
            server_version,
        )


def _ensure_sandbox_control_network(client: Any) -> Any:
    """Return an internal control network shared only with the runtime."""
    import docker

    try:
        network = client.networks.get(SANDBOX_NETWORK_NAME)
    except docker.errors.NotFound:
        network = client.networks.create(
            SANDBOX_NETWORK_NAME,
            driver="bridge",
            internal=True,
        )
    network.reload()
    if not bool((network.attrs or {}).get("Internal")):
        raise RuntimeError(
            f"Sandbox control network {SANDBOX_NETWORK_NAME} must be internal"
        )

    if _is_containerized_runtime():
        runtime_container = client.containers.get(socket.gethostname())
        connected = (network.attrs or {}).get("Containers") or {}
        if runtime_container.id not in connected:
            network.connect(runtime_container)
            network.reload()
    return network


def _attach_sandbox_to_control_network(
    client: Any,
    container: Any,
    *,
    alias: str,
) -> Any:
    """Attach an egress-enabled sandbox to the internal runtime control plane."""
    network = _ensure_sandbox_control_network(client)
    container.reload()
    connected = (network.attrs or {}).get("Containers") or {}
    if container.id not in connected:
        network.connect(container, aliases=[alias])
        network.reload()
    return network


def _seed_pnpm_offline_store(container: Any) -> None:
    """Seed a read-only pnpm store on the workspace filesystem when available."""
    source_check = container.exec_run(
        ["test", "-d", f"{SANDBOX_PNPM_STORE_SOURCE}/v3"],
        user="root",
    )
    if getattr(source_check, "exit_code", None) != 0:
        return

    target_check = container.exec_run(
        ["test", "-d", f"{SANDBOX_PNPM_STORE_PATH}/v3"],
        user="root",
    )
    if getattr(target_check, "exit_code", None) == 0:
        return

    commands = [
        ["mkdir", "-p", SANDBOX_PNPM_STORE_PATH],
        ["cp", "-a", f"{SANDBOX_PNPM_STORE_SOURCE}/.", SANDBOX_PNPM_STORE_PATH],
        ["chmod", "-R", "a-w", SANDBOX_PNPM_STORE_PATH],
    ]
    for command in commands:
        result = container.exec_run(command, user="root")
        if getattr(result, "exit_code", None) != 0:
            raise RuntimeError(
                f"Failed to prepare pnpm offline store with {command[0]}"
            )


def _kernel_gateway_command() -> list[str]:
    """Return the Kernel Gateway command required by Nexent's health checks."""
    return [
        "jupyter",
        "kernelgateway",
        "--KernelGatewayApp.ip=0.0.0.0",
        f"--KernelGatewayApp.port={SANDBOX_JUPYTER_PORT}",
        "--KernelGatewayApp.allow_origin=*",
        "--ServerApp.allow_remote_access=True",
        "--JupyterWebsocketPersonality.list_kernels=True",
    ]


def _sandbox_connection_hosts(container: Any) -> list[str]:
    """Return Jupyter connection hosts in preferred order for this runtime."""
    if _is_containerized_runtime():
        return [SANDBOX_CONTAINER_NAME]

    hosts = ["127.0.0.1"]
    networks = (container.attrs.get("NetworkSettings") or {}).get("Networks") or {}
    network_ip = (networks.get(SANDBOX_NETWORK_NAME) or {}).get("IPAddress")
    if network_ip:
        hosts.append(network_ip)
    return hosts

class _RecoveredDockerExecutor:
    """Minimal Docker executor facade for a container owned by another runtime."""

    def __init__(
        self,
        container: Any,
        logger_: logging.Logger,
        host: str,
        additional_imports: Optional[list[str]] = None,
        port: int = SANDBOX_JUPYTER_PORT,
    ) -> None:
        self.container = container
        self.client = container.client
        self.logger = _make_smolagents_logger(logger_)
        self._logger = logger_
        self.host = host
        self.port = port
        self.base_url = f"http://{self.host}:{self.port}"
        self.additional_imports = additional_imports or []
        self.installed_packages = []
        self._nexent_backend = "docker"

    def cleanup(self) -> None:
        """Stop and remove the recovered container when the pool is shut down."""
        try:
            self.container.remove(force=True)
        except Exception as exc:
            self._logger.warning("Failed to remove recovered sandbox container: %s", exc)


class _DockerKernelLease:
    """Expose one isolated Jupyter kernel backed by a shared Docker container."""

    _nexent_kernel_lease = True

    def __init__(
        self,
        container_executor: Any,
        logger_: logging.Logger,
        receive_timeout_seconds: float = 30,
    ) -> None:
        import requests
        from smolagents.remote_executors import _create_kernel_http

        self._container_executor = container_executor
        self.logger = container_executor.logger
        self.additional_imports = getattr(container_executor, "additional_imports", [])
        self.installed_packages = list(getattr(container_executor, "installed_packages", []))
        self._nexent_backend = getattr(container_executor, "_nexent_backend", "docker")
        self._logger = logger_
        self.base_url = container_executor.base_url
        self.host = container_executor.host
        self.port = container_executor.port
        self.kernel_id = _create_kernel_http(f"{self.base_url}/api/kernels", self.logger)
        self._channel_session_id = secrets.token_hex(16)
        self.ws_url = self._build_channels_url(self.kernel_id)
        self._receive_timeout_seconds = float(receive_timeout_seconds)
        if self._receive_timeout_seconds <= 0:
            raise ValueError("Sandbox WebSocket receive timeout must be positive")
        self._closed = False
        self._unhealthy = False
        self._nexent_kernel_recovery_supported = True
        self._requests = requests
        self._cached_variables: Optional[dict[str, Any]] = None
        self._cached_tools: Optional[dict[str, Any]] = None
        self._kernel_bootstrap_code: list[str] = []

    def _build_channels_url(self, kernel_id: str) -> str:
        """Build a Kernel Gateway channel URL with a stable client session."""
        session_id = getattr(self, "_channel_session_id", None)
        if not session_id:
            session_id = secrets.token_hex(16)
            self._channel_session_id = session_id
        return (
            f"ws://{self.host}:{self.port}/api/kernels/{kernel_id}/channels"
            f"?session_id={session_id}"
        )

    @property
    def container(self) -> Any:
        """Return the shared Docker container for health checks and diagnostics."""
        return self._container_executor.container

    def run_code_raise_errors(self, code: str) -> Any:
        import base64
        import json
        import pickle

        from smolagents.remote_executors import (
            AgentError,
            CodeOutput,
            RemotePythonExecutor,
            _websocket_send_execute_request,
        )
        from websocket import (
            ABNF,
            WebSocketConnectionClosedException,
            WebSocketTimeoutException,
            create_connection,
        )

        if self._closed:
            raise RuntimeError("Sandbox kernel lease is already closed")
        if self._unhealthy:
            self._replace_unhealthy_kernel()

        with closing(
            create_connection(self.ws_url, timeout=self._receive_timeout_seconds)
        ) as ws:
            msg_id = _websocket_send_execute_request(code, ws)
            outputs = []
            result = None
            is_final_answer = False
            status_deadline = time.monotonic() + self._receive_timeout_seconds

            while True:
                now = time.monotonic()
                if now >= status_deadline:
                    self._check_kernel_channel_health(
                        "the terminal execution message was not received before the watchdog deadline"
                    )
                    status_deadline = time.monotonic() + self._receive_timeout_seconds
                    now = time.monotonic()

                ws.settimeout(max(status_deadline - now, 0.001))
                raw_message = None
                try:
                    opcode, raw_message = ws.recv_data(control_frame=True)
                except WebSocketTimeoutException as exc:
                    try:
                        self._check_kernel_channel_health(
                            "no WebSocket messages were received before the watchdog deadline"
                        )
                    except RuntimeError as health_error:
                        raise health_error from exc
                    status_deadline = time.monotonic() + self._receive_timeout_seconds
                    continue
                except WebSocketConnectionClosedException as exc:
                    try:
                        self._check_kernel_channel_health(
                            "the Jupyter WebSocket connection closed unexpectedly",
                            allow_busy=False,
                        )
                    except RuntimeError as health_error:
                        raise health_error from exc

                if opcode in (ABNF.OPCODE_PING, ABNF.OPCODE_PONG):
                    continue
                if opcode == ABNF.OPCODE_CLOSE:
                    self._check_kernel_channel_health(
                        "the Jupyter WebSocket connection sent a close frame",
                        allow_busy=False,
                    )
                if not raw_message:
                    self._check_kernel_channel_health(
                        "the Jupyter WebSocket connection returned an empty frame",
                        allow_busy=False,
                    )
                if isinstance(raw_message, bytes):
                    raw_message = raw_message.decode("utf-8")

                message = json.loads(raw_message)
                parent_msg_id = message.get("parent_header", {}).get("msg_id")
                if parent_msg_id != msg_id:
                    continue

                msg_type = message.get("msg_type", "")
                content = message.get("content", {})
                if msg_type == "stream":
                    outputs.append(content["text"])
                    status_deadline = time.monotonic() + self._receive_timeout_seconds
                elif msg_type == "execute_result":
                    result = content["data"].get("text/plain")
                    status_deadline = time.monotonic() + self._receive_timeout_seconds
                elif msg_type == "error":
                    if content.get("ename", "") == RemotePythonExecutor.FINAL_ANSWER_EXCEPTION:
                        result = pickle.loads(base64.b64decode(content.get("evalue", "")))
                        is_final_answer = True
                    else:
                        raise AgentError("\n".join(content.get("traceback", [])), self.logger)
                elif msg_type == "status" and content.get("execution_state") == "idle":
                    break

            return CodeOutput(
                output=result,
                logs="".join(outputs),
                is_final_answer=is_final_answer,
            )

    def _check_kernel_channel_health(
        self,
        reason: str,
        *,
        allow_busy: bool = True,
    ) -> None:
        """Fail a lost kernel channel while allowing a genuinely busy kernel to continue."""
        state = self._get_kernel_execution_state()
        if allow_busy and state == "busy":
            self._logger.debug(
                "Sandbox kernel %s remains busy after %.1fs: %s",
                self.kernel_id,
                self._receive_timeout_seconds,
                reason,
            )
            return

        self._unhealthy = True
        message = (
            f"Sandbox kernel channel failed: {reason}; state={state!r}; "
            "the kernel lease was marked unhealthy and will be replaced before the next execution"
        )
        self._logger.warning(message)
        raise RuntimeError(message)

    def _get_kernel_execution_state(self) -> Optional[str]:
        """Return the live Jupyter kernel state after a WebSocket receive timeout."""
        try:
            response = self._requests.get(
                f"{self.base_url}/api/kernels/{self.kernel_id}",
                timeout=self._receive_timeout_seconds,
            )
            response.raise_for_status()
            return response.json().get("execution_state")
        except Exception as exc:
            self._logger.warning(
                "Failed to query sandbox kernel %s after WebSocket timeout: %s",
                self.kernel_id,
                exc,
            )
            return None

    def _replace_unhealthy_kernel(self) -> None:
        """Replace a failed kernel and restore framework-managed execution state."""
        from smolagents.remote_executors import (
            RemotePythonExecutor,
            _create_kernel_http,
        )

        previous_kernel_id = self.kernel_id
        try:
            response = self._requests.delete(
                f"{self.base_url}/api/kernels/{previous_kernel_id}",
                timeout=5,
            )
            if response.status_code not in (204, 404):
                self._logger.warning(
                    "Failed to delete unhealthy sandbox kernel %s before replacement: status=%s",
                    previous_kernel_id,
                    response.status_code,
                )
        except Exception as exc:
            self._logger.warning(
                "Failed to delete unhealthy sandbox kernel %s before replacement: %s",
                previous_kernel_id,
                exc,
            )

        self._logger.warning(
            "Replacing unhealthy sandbox kernel %s for the current agent run",
            previous_kernel_id,
        )
        try:
            kernel_id = _create_kernel_http(f"{self.base_url}/api/kernels", self.logger)
            self.kernel_id = kernel_id
            self._channel_session_id = secrets.token_hex(16)
            self.ws_url = self._build_channels_url(kernel_id)
            self._unhealthy = False

            if self._cached_variables is not None:
                RemotePythonExecutor.send_variables(self, self._cached_variables)
            if self._cached_tools is not None:
                RemotePythonExecutor.send_tools(self, self._cached_tools)
            for code in self._kernel_bootstrap_code:
                self.run_code_raise_errors(code)
        except Exception as exc:
            self._unhealthy = True
            self._logger.exception(
                "Failed to replace unhealthy sandbox kernel %s",
                previous_kernel_id,
            )
            raise RuntimeError(
                f"Failed to replace unhealthy sandbox kernel {previous_kernel_id}"
            ) from exc

        self._logger.info(
            "Replaced unhealthy sandbox kernel %s with %s",
            previous_kernel_id,
            self.kernel_id,
        )

    def __call__(self, code_action: str) -> Any:
        shell_policy = getattr(self, "_nexent_shell_policy", ShellPolicy.BOXED)
        if shell_policy != ShellPolicy.BOXED:
            violations = _scan_shell_calls(
                code_action,
                allow_package_installs=getattr(
                    self,
                    "_nexent_allow_package_installs",
                    False,
                ),
            )
            if violations:
                self._logger.warning(
                    "Sandbox shell guard blocked %d call(s): %s",
                    len(violations),
                    violations,
                )
                message = (
                    "SecurityError: this shell command is not permitted by the sandbox policy.\n"
                    "Detected: " + ", ".join(violations) + "\n"
                    "Suggestion: when network access is enabled, install Python packages with a "
                    "shell-free `subprocess` pip-install argv or `%pip install`; otherwise use an "
                    "approved Nexent tool or pure Python."
                )
                return _make_code_output(message)
        if getattr(self, "_nexent_online_user_site", False):
            code_action = _ONLINE_USER_SITE_BOOTSTRAP + code_action
        return self.run_code_raise_errors(code_action)

    def send_variables(self, variables: dict[str, Any]) -> None:
        from smolagents.remote_executors import RemotePythonExecutor
        self._cached_variables = dict(variables)
        try:
            RemotePythonExecutor.send_variables(self, variables)
        except Exception as exc:
            if not self._unhealthy:
                raise
            self._logger.warning(
                "Retrying sandbox variable registration with a replacement kernel: %s",
                exc,
            )
            # Kernel replacement replays _cached_variables together with all
            # other framework-managed state, so a second explicit send would
            # only duplicate the registration.
            self._replace_unhealthy_kernel()

    def install_packages(self, additional_imports: list[str]) -> list[str]:
        from smolagents.remote_executors import RemotePythonExecutor
        return RemotePythonExecutor.install_packages(self, additional_imports)

    def _patch_final_answer_with_exception(self, final_answer_tool: Any) -> None:
        """Patch final_answer while preserving its class-defined implementation."""
        import inspect

        if getattr(final_answer_tool, "_nexent_final_answer_patched", False):
            return

        instance_forward = final_answer_tool.forward
        original_forward = getattr(instance_forward, "__func__", None)
        wrapped_instance_forward = original_forward is None
        if wrapped_instance_forward:
            original_forward = getattr(type(final_answer_tool), "forward", None)
        if not callable(original_forward):
            raise TypeError("final_answer tool must define a callable forward method")

        class _FinalAnswerTool(final_answer_tool.__class__):
            pass

        def forward(self, *args, **kwargs) -> Any:
            import base64
            import pickle

            class FinalAnswerException(Exception):
                def __init__(self, value):
                    self.value = value

            raise FinalAnswerException(base64.b64encode(pickle.dumps(self._forward(*args, **kwargs))).decode())

        _FinalAnswerTool.forward = forward
        _FinalAnswerTool._forward = original_forward
        _FinalAnswerTool._forward.__source__ = inspect.getsource(original_forward).replace(
            "def forward(", "def _forward("
        )
        if wrapped_instance_forward:
            del final_answer_tool.forward
        final_answer_tool.__class__ = _FinalAnswerTool
        final_answer_tool._nexent_final_answer_patched = True

    def send_tools(self, tools: dict[str, Any]) -> None:
        from smolagents.remote_executors import RemotePythonExecutor
        self._cached_tools = dict(tools)
        try:
            RemotePythonExecutor.send_tools(self, tools)
        except Exception as exc:
            if not self._unhealthy:
                raise
            self._logger.warning(
                "Retrying sandbox tool registration with a replacement kernel: %s",
                exc,
            )
            # _replace_unhealthy_kernel replays the cached tools, variables,
            # host-tool proxies, and run-workspace bootstrap in one pass.
            self._replace_unhealthy_kernel()

    def register_kernel_bootstrap_code(self, code: str) -> Any:
        """Execute and retain framework bootstrap code for future kernel replacement."""
        try:
            output = self.run_code_raise_errors(code)
        except Exception as exc:
            if not self._unhealthy:
                raise
            self._logger.warning(
                "Retrying sandbox bootstrap registration with a replacement kernel: %s",
                exc,
            )
            self._replace_unhealthy_kernel()
            output = self.run_code_raise_errors(code)
        if code not in self._kernel_bootstrap_code:
            self._kernel_bootstrap_code.append(code)
        return output

    def cleanup(self) -> None:
        """Delete this kernel while leaving the shared container running."""
        if self._closed:
            return
        try:
            response = self._requests.delete(f"{self.base_url}/api/kernels/{self.kernel_id}", timeout=5)
            if response.status_code not in (204, 404):
                self._logger.warning(
                    "Failed to delete sandbox kernel %s: status=%s",
                    self.kernel_id,
                    response.status_code,
                )
        finally:
            self._closed = True


class _SessionDockerContainerGroup:
    """Reference-count the kernel leases that share one session container."""

    def __init__(self, container_executor: Any) -> None:
        self.container_executor = container_executor
        self._lease_count = 0
        self._closed = False
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("Session sandbox container group is already closed")
            self._lease_count += 1

    def release(self) -> None:
        should_cleanup = False
        with self._lock:
            if self._lease_count <= 0:
                return
            self._lease_count -= 1
            if self._lease_count == 0 and not self._closed:
                self._closed = True
                should_cleanup = True
        if should_cleanup:
            self.container_executor.cleanup()

    def close_if_unused(self) -> None:
        """Remove the container when construction failed before a lease attached."""
        should_cleanup = False
        with self._lock:
            if self._lease_count == 0 and not self._closed:
                self._closed = True
                should_cleanup = True
        if should_cleanup:
            self.container_executor.cleanup()


class _SessionDockerExecutor(_DockerKernelLease):
    """A dedicated kernel lease in an agent-tree-shared session container."""

    def __init__(
        self,
        container_group: _SessionDockerContainerGroup,
        logger_: logging.Logger,
        receive_timeout_seconds: float = 30,
    ) -> None:
        self._session_container_group = container_group
        self._session_lease_released = False
        super().__init__(
            container_group.container_executor,
            logger_,
            receive_timeout_seconds,
        )
        container_group.acquire()

    def cleanup(self) -> None:
        """Delete this kernel and release its shared container reference once."""
        if self._session_lease_released:
            return
        try:
            super().cleanup()
        finally:
            self._session_lease_released = True
            self._session_container_group.release()


class SandboxPoolManager:
    """
    Singleton pool manager for ``container_scope=system`` sandboxes.

    Maintains one pre-warmed DockerExecutor per system pool key and creates a
    dedicated Jupyter kernel lease for each agent run. Kernel leases are removed
    when a run ends; shared containers are destroyed only during shutdown or
    unrecoverable container failure.

    Thread-safety: all public methods acquire ``_lock`` before touching shared
    state.

    Legacy non-Docker pool entries may be evicted after ``idle_ttl_seconds``.
    System-scoped Docker containers are intentionally excluded and remain warm
    until application shutdown or an explicit failure cleanup.

    Usage::

        pool = SandboxPoolManager.get_instance()
        executor = pool.acquire(config, logger_)
        # ... use executor across multiple agent runs ...
        pool.release(executor)   # or pool.release_immediate(executor)
    """

    _instance: Optional["SandboxPoolManager"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._pools: dict[str, list[Any]] = {}          # image → list of idle executors
        self._in_use: dict[int, str] = {}               # executor id → pool key
        self._executors: dict[int, Any] = {}            # active executor id → executor
        self._last_touch: dict[int, float] = {}         # executor id → last access timestamp
        self._system_containers: dict[str, Any] = {}    # pool key → shared DockerExecutor
        self._lease_owners: dict[int, Any] = {}         # kernel lease id → shared container
        self._lock = threading.Lock()
        self._container_build_lock = threading.Lock()
        self._idle_ttl_seconds: float = 300.0            # legacy pool setting
        self._evict_thread: Optional[threading.Thread] = None
        self._stop_evict = threading.Event()

    @classmethod
    def get_instance(cls) -> "SandboxPoolManager":
        """Get or create the global SandboxPoolManager singleton."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
                    cls._instance._start_evictor()
        return cls._instance

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def acquire(
        self,
        config: SandboxConfig,
        logger_: logging.Logger,
        host_tools_exist: bool = False,
        session_container_group: Optional[_SessionDockerContainerGroup] = None,
    ) -> Any:
        """
        Acquire a warm executor from the pool, or create a new one if the pool
        is empty or scope is SESSION.

        For ``scope=SESSION`` this always creates a fresh executor.
        For ``scope=SYSTEM`` this tries to pop from the pool first.
        """
        if config.scope == SandboxScope.SESSION:
            return self._build_executor(
                config,
                logger_,
                host_tools_exist,
                session_container_group=session_container_group,
            )

        if config.level == SandboxLevel.DOCKER:
            return self._acquire_shared_docker_kernel(config, logger_, host_tools_exist)

        pool_key = (
            f"{config.docker_image}|host_tools=true"
            if host_tools_exist
            else config.docker_image
        )
        with self._lock:
            pool = self._pools.get(pool_key, [])
            while pool:
                ex = pool.pop()
                if self._is_alive(ex):
                    ex_id = id(ex)
                    self._in_use[ex_id] = pool_key
                    self._executors[ex_id] = ex
                    self._last_touch[ex_id] = _now()
                    logger_.debug("Reused pooled sandbox container (key=%s)", pool_key)
                    return ex
                self._destroy_executor(ex, logger_)
            self._pools.setdefault(pool_key, [])

        ex = self._build_executor(config, logger_, host_tools_exist)
        with self._lock:
            ex_id = id(ex)
            self._in_use[ex_id] = pool_key
            self._executors[ex_id] = ex
            self._last_touch[ex_id] = _now()
        logger_.info(
            "Created new system-scoped sandbox (image=%s, memory=%dMB, network=%s)",
            config.docker_image,
            config.memory_limit_mb,
            "host bridge" if host_tools_exist else ("disabled" if config.network_disabled else "bridge"),
        )
        return ex

    def _acquire_shared_docker_kernel(
        self,
        config: SandboxConfig,
        logger_: logging.Logger,
        host_tools_exist: bool,
    ) -> Any:
        """Create one Docker container per system pool and lease one kernel per run."""
        # A system sandbox has one fixed Docker container and network regardless
        # of whether an individual lease exposes Runtime-hosted tools. Host-tool
        # bridges are installed per kernel lease below, so splitting the owner by
        # host_tools_exist would let two pool owners manage and remove the same
        # named container.
        pool_key = config.docker_image

        def discard_owner(owner: Any) -> None:
            removed = False
            with self._lock:
                if self._system_containers.get(pool_key) is owner:
                    self._system_containers.pop(pool_key, None)
                    removed = True
            if removed:
                self._destroy_executor(owner, logger_)

        def get_or_create_owner() -> Any:
            with self._lock:
                owner = self._system_containers.get(pool_key)
            if owner is not None and self._is_alive(owner):
                return owner
            if owner is not None:
                discard_owner(owner)

            with self._container_build_lock:
                with self._lock:
                    owner = self._system_containers.get(pool_key)
                if owner is not None and self._is_alive(owner):
                    return owner
                if owner is not None:
                    discard_owner(owner)

                owner = self._recover_docker_container(
                    config,
                    logger_,
                    host_tools_exist,
                )
                if owner is None:
                    self._remove_stale_docker_containers(config, logger_)
                    owner = self._build_executor(config, logger_, host_tools_exist)
                if not hasattr(owner, "base_url") or not hasattr(owner, "container"):
                    return owner
                with self._lock:
                    existing = self._system_containers.setdefault(pool_key, owner)
                if existing is not owner:
                    self._destroy_executor(owner, logger_)
                    owner = existing
                return owner

        container_executor = None
        lease = None
        for attempt in range(2):
            container_executor = get_or_create_owner()
            if not hasattr(container_executor, "base_url") or not hasattr(
                container_executor,
                "container",
            ):
                return container_executor
            try:
                # Revalidate immediately before creating the kernel. This closes
                # the restart window between owner lookup and the Kernel Gateway
                # request, while the one retry rebuilds stale recovered owners.
                if not self._is_alive(container_executor):
                    raise RuntimeError("Shared sandbox container stopped before kernel lease creation")
                lease = _DockerKernelLease(
                    container_executor,
                    logger_,
                    receive_timeout_seconds=config.timeout_seconds,
                )
                break
            except Exception as exc:
                discard_owner(container_executor)
                if attempt == 0:
                    logger_.warning(
                        "Shared sandbox lease creation failed; rebuilding owner once: %s",
                        exc,
                    )
                    continue
                raise RuntimeError(
                    "Failed to create a kernel lease after rebuilding the shared sandbox"
                ) from exc

        if lease is None:  # pragma: no cover - loop either assigns or raises
            raise RuntimeError("Failed to create a shared sandbox kernel lease")
        if host_tools_exist:
            lease = _install_host_tool_bridge(
                lease,
                logger_,
                request_timeout_seconds=config.host_tool_timeout_seconds,
            )
        lease = _wrap_executor(lease, config, logger_)
        lease._nexent_sandbox_config = config
        lease._nexent_pool_key = pool_key
        with self._lock:
            self._in_use[id(lease)] = pool_key
            self._lease_owners[id(lease)] = container_executor
            self._executors[id(lease)] = lease
            self._last_touch[id(lease)] = _now()
        logger_.debug(
            "Leased dedicated Jupyter kernel %s from shared sandbox (key=%s)",
            lease.kernel_id,
            pool_key,
        )
        return lease

    def release(self, executor: Any, logger_: logging.Logger) -> None:
        """
        Return an executor to the pool for reuse.

        For ``scope=SESSION`` this immediately destroys the container.
        For ``scope=SYSTEM`` this returns it to the idle pool.
        """
        if executor is None:
            return

        ex_id = id(executor)
        with self._lock:
            shared_container = self._lease_owners.pop(ex_id, None)
            pool_key = self._in_use.pop(ex_id, None)
            self._executors.pop(ex_id, None)
            self._last_touch.pop(ex_id, None)

        if shared_container is not None:
            self._destroy_executor(executor, logger_)
            logger_.debug("Released Jupyter kernel lease; shared container remains running")
            return

        if pool_key is None:
            self._destroy_executor(executor, logger_)
            return

        config = getattr(executor, "_nexent_sandbox_config", None)
        if config and config.scope == SandboxScope.SESSION:
            self._destroy_executor(executor, logger_)
            return

        with self._lock:
            self._pools.setdefault(pool_key, []).append(executor)
            self._last_touch[ex_id] = _now()
        logger_.debug("Returned sandbox to pool (key=%s)", pool_key)

    def release_immediate(self, executor: Any, logger_: logging.Logger) -> None:
        """
        Immediately destroy an executor without returning it to the pool.

        Use this in error paths where reuse is unsafe (e.g. execution error
        may have left malicious state in the container).
        """
        ex_id = id(executor)
        with self._lock:
            shared_container = self._lease_owners.pop(ex_id, None)
            pool_key = self._in_use.pop(ex_id, None)
            self._executors.pop(ex_id, None)
            self._last_touch.pop(ex_id, None)
        self._destroy_executor(executor, logger_)
        if shared_container is not None:
            with self._lock:
                if self._system_containers.get(pool_key) is shared_container:
                    self._system_containers.pop(pool_key, None)
            self._destroy_executor(shared_container, logger_)

    def shutdown(self, logger_: logging.Logger) -> None:
        """
        Permanently shut down the pool manager and destroy all pooled containers.

        Call this during application shutdown.
        """
        self._stop_evict.set()
        if self._evict_thread:
            self._evict_thread.join(timeout=10)

        with self._lock:
            all_executors: list[Any] = []
            for pool in self._pools.values():
                all_executors.extend(pool)
            self._pools.clear()
            all_executors.extend(self._executors.values())
            all_executors.extend(self._system_containers.values())
            self._pools.clear()
            self._system_containers.clear()
            self._in_use.clear()
            self._lease_owners.clear()
            self._executors.clear()
            self._last_touch.clear()

        for ex in {id(ex): ex for ex in all_executors}.values():
            self._destroy_executor(ex, logger_)
        logger_.info("SandboxPoolManager shut down")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_executor(
        self,
        config: SandboxConfig,
        logger_: logging.Logger,
        host_tools_exist: bool = False,
        session_container_group: Optional[_SessionDockerContainerGroup] = None,
    ) -> Any:
        """Construct and (for docker) eagerly start a container."""
        level = config.level

        if level == SandboxLevel.LOCAL:
            imports = config.extra_kwargs.get("additional_authorized_imports", [])
            return _wrap_executor(
                _make_local_executor(imports),
                config,
                logger_,
            )

        if level == SandboxLevel.DOCKER:
            return self._build_docker_executor(
                config,
                logger_,
                host_tools_exist,
                session_container_group=session_container_group,
            )

        if level == SandboxLevel.WASM:
            if host_tools_exist:
                raise RuntimeError(
                    "WASM sandbox does not support host tool callbacks; use Docker or LOCAL"
                )
            return self._build_wasm_executor(config, logger_)

        raise ValueError(f"Unsupported SandboxLevel: {config.level}")

    def _recover_docker_container(
        self,
        config: SandboxConfig,
        logger_: logging.Logger,
        host_tools_exist: bool,
    ) -> Optional[Any]:
        """Recover a healthy Docker sandbox left by a previous runtime process."""
        try:
            import docker
            import requests

            client = docker.from_env()
            containers = [
                item for item in client.containers.list(all=True)
                if item.name == SANDBOX_CONTAINER_NAME
            ]
            if not containers:
                logger_.debug("No persisted sandbox container named %s found", SANDBOX_CONTAINER_NAME)
                return None

            container = containers[0]
            container.reload()
            labels = container.labels or {}
            if labels.get("com.nexent.sandbox") != "runtime":
                logger_.warning("Ignoring unrelated container named %s", SANDBOX_CONTAINER_NAME)
                return None
            if container.status != "running":
                logger_.warning("Persisted sandbox container is not running (status=%s)", container.status)
                return None

            workspace_volume_name = config.extra_kwargs.get("workspace_volume_name")
            workspace_root = config.extra_kwargs.get("workspace_root")
            if workspace_volume_name and workspace_root:
                expected_destination = str(Path(workspace_root).resolve())
                mounts = container.attrs.get("Mounts") or []
                has_expected_mount = any(
                    mount.get("Type") == "volume"
                    and mount.get("Name") == workspace_volume_name
                    and mount.get("Destination") == expected_destination
                    and mount.get("RW") is not False
                    for mount in mounts
                )
                if not has_expected_mount:
                    logger_.warning(
                        "Persisted sandbox container does not use workspace volume %s at %s",
                        workspace_volume_name,
                        expected_destination,
                    )
                    return None

            networks = (container.attrs.get("NetworkSettings") or {}).get("Networks") or {}
            if SANDBOX_NETWORK_NAME not in networks:
                logger_.warning("Persisted sandbox container is not attached to network %s", SANDBOX_NETWORK_NAME)
                return None

            if not _is_containerized_runtime():
                ports = (container.attrs.get("NetworkSettings") or {}).get("Ports") or {}
                bindings = ports.get(f"{SANDBOX_JUPYTER_PORT}/tcp") or []
                if not any(str(binding.get("HostPort")) == str(SANDBOX_JUPYTER_PORT) for binding in bindings):
                    logger_.warning("Persisted sandbox container does not expose host port %s", SANDBOX_JUPYTER_PORT)
                    return None

            selected_host = None
            kernels = None
            for candidate_host in _sandbox_connection_hosts(container):
                base_url = f"http://{candidate_host}:{SANDBOX_JUPYTER_PORT}"
                try:
                    response = requests.get(f"{base_url}/api/kernels", timeout=3)
                    response.raise_for_status()
                    candidate_kernels = response.json()
                    if isinstance(candidate_kernels, list):
                        selected_host = candidate_host
                        kernels = candidate_kernels
                        break
                except Exception:
                    continue
            if selected_host is None or kernels is None:
                raise RuntimeError("Jupyter kernel API is unavailable on host or nexent network address")
            recovered = _RecoveredDockerExecutor(
                container,
                logger_,
                selected_host,
                config.extra_kwargs.get("additional_imports", []),
            )
            recovered._nexent_sandbox_config = config
            recovered._nexent_kernel_count = len(kernels)
            logger_.info(
                "Recovered persisted Docker sandbox container %s (url=%s, active_kernels=%d)",
                container.short_id,
                recovered.base_url,
                len(kernels),
            )
            return recovered
        except Exception as exc:
            logger_.warning("Persisted Docker sandbox recovery failed: %s", exc)
            return None

    def _remove_stale_docker_containers(self, config: SandboxConfig, logger_: logging.Logger) -> None:
        """Remove stale containers that would conflict with the stable sandbox name or port."""
        try:
            import docker

            client = docker.from_env()
            containers = []
            for container in client.containers.list(all=True):
                container.reload()
                if container.name == SANDBOX_CONTAINER_NAME:
                    containers.append(container)
                    continue
                if container.image.tags and config.docker_image in container.image.tags:
                    ports = (container.attrs.get("NetworkSettings") or {}).get("Ports") or {}
                    bindings = ports.get(f"{SANDBOX_JUPYTER_PORT}/tcp") or []
                    if any(str(binding.get("HostPort")) == str(SANDBOX_JUPYTER_PORT) for binding in bindings):
                        containers.append(container)
            for container in containers:
                try:
                    container.remove(force=True)
                    logger_.info("Removed stale persisted sandbox container %s", container.short_id)
                except Exception as exc:
                    logger_.warning("Failed to remove stale sandbox container: %s", exc)
        except Exception as exc:
            logger_.debug("Could not inspect stale sandbox containers: %s", exc)

    def _build_session_docker_executor(
        self,
        config: SandboxConfig,
        logger_: logging.Logger,
        container_run_kwargs: dict[str, Any],
    ) -> Any:
        """Create a per-session container without a fixed host-port binding."""
        import docker
        import requests

        client = docker.from_env()
        run_kwargs = dict(container_run_kwargs)
        _apply_legacy_docker_seccomp_compatibility(client, run_kwargs, logger_)
        container_name = f"{SANDBOX_SESSION_CONTAINER_PREFIX}-{secrets.token_hex(8)}"
        run_kwargs.update({
            "name": container_name,
            "labels": {"com.nexent.sandbox": "session"},
            "command": _kernel_gateway_command(),
            "detach": True,
            # Kernel Gateway needs a network namespace for its HTTP/WebSocket
            # control plane. Its published endpoint remains constrained to host
            # loopback or to the Nexent Docker network.
            "network_disabled": False,
        })
        if config.network_disabled:
            logger_.warning(
                "Docker NetworkDisabled cannot be used for the Jupyter control plane; "
                "the session sandbox is reachable only through its local control endpoint. "
                "Enforce outbound restrictions with the deployment network or firewall."
            )

        if _is_containerized_runtime():
            # The runtime's 127.0.0.1 is not the Docker host. Connect directly
            # over the shared Docker network using this container's unique DNS
            # name and do not publish a host port.
            _ensure_sandbox_control_network(client)
            run_kwargs.pop("ports", None)
            if config.network_disabled:
                run_kwargs["network"] = SANDBOX_NETWORK_NAME
            else:
                # Docker's default bridge supplies outbound access. The
                # container is attached to the internal control network after
                # creation so the runtime can still reach Jupyter by DNS name.
                run_kwargs.pop("network", None)
            connection_host = container_name
            connection_port = SANDBOX_JUPYTER_PORT
        else:
            # Let Docker allocate an available host port atomically. Selecting a
            # port in Python before container creation would retain a TOCTOU race.
            run_kwargs["ports"] = {
                f"{SANDBOX_JUPYTER_PORT}/tcp": ("127.0.0.1", None)
            }
            connection_host = "127.0.0.1"
            connection_port = 0

        container = client.containers.run(config.docker_image, **run_kwargs)
        if _is_containerized_runtime() and not config.network_disabled:
            _attach_sandbox_to_control_network(
                client,
                container,
                alias=container_name,
            )
        _seed_pnpm_offline_store(container)
        owner = None
        container_group = None
        executor = None
        try:
            container.reload()
            if not _is_containerized_runtime():
                ports = (container.attrs.get("NetworkSettings") or {}).get("Ports") or {}
                bindings = ports.get(f"{SANDBOX_JUPYTER_PORT}/tcp") or []
                if not bindings or not bindings[0].get("HostPort"):
                    raise RuntimeError("Docker did not allocate a Jupyter host port")
                connection_port = int(bindings[0]["HostPort"])

            deadline = time.monotonic() + max(10, config.timeout_seconds)
            base_url = f"http://{connection_host}:{connection_port}"
            while time.monotonic() < deadline:
                container.reload()
                if container.status not in (None, "created", "running"):
                    raise RuntimeError(
                        f"Session sandbox container stopped before Jupyter was ready "
                        f"(status={container.status})"
                    )
                try:
                    response = requests.get(f"{base_url}/api/kernels", timeout=1)
                    response.raise_for_status()
                    if isinstance(response.json(), list):
                        break
                except Exception:
                    pass
                time.sleep(0.5)
            else:
                raise RuntimeError(f"Jupyter kernel API did not become ready at {base_url}")

            owner = _RecoveredDockerExecutor(
                container,
                logger_,
                connection_host,
                config.extra_kwargs.get("additional_imports", []),
                port=connection_port,
            )
            container_group = _SessionDockerContainerGroup(owner)
            executor = self._lease_session_docker_kernel(
                config,
                logger_,
                container_group,
            )
            logger_.info(
                "Created session Docker sandbox %s (url=%s)",
                container.short_id,
                executor.base_url,
            )
            return executor
        except Exception:
            if executor is not None:
                executor.cleanup()
            if container_group is not None:
                container_group.close_if_unused()
            elif owner is not None:
                owner.cleanup()
            else:
                try:
                    container.remove(force=True)
                except Exception:
                    pass
            raise

    def _lease_session_docker_kernel(
        self,
        config: SandboxConfig,
        logger_: logging.Logger,
        container_group: _SessionDockerContainerGroup,
    ) -> Any:
        """Lease an isolated kernel from an agent-tree session container."""
        if not self._is_alive(container_group.container_executor):
            raise RuntimeError("Shared session sandbox container is not running")
        executor = _SessionDockerExecutor(
            container_group,
            logger_,
            receive_timeout_seconds=config.timeout_seconds,
        )
        try:
            executor.installed_packages = executor.install_packages(
                executor.additional_imports
            )
        except Exception:
            executor.cleanup()
            raise
        executor._nexent_session_container_group = container_group
        return executor

    def _build_system_docker_executor(
        self,
        config: SandboxConfig,
        logger_: logging.Logger,
        container_run_kwargs: dict[str, Any],
    ) -> Any:
        """Create a shared Docker sandbox and connect over host or container networking."""
        import docker
        import requests

        client = docker.from_env()
        run_kwargs = dict(container_run_kwargs)
        _apply_legacy_docker_seccomp_compatibility(client, run_kwargs, logger_)
        if _is_containerized_runtime():
            run_kwargs.pop("ports", None)
        else:
            run_kwargs["ports"] = {
                f"{SANDBOX_JUPYTER_PORT}/tcp": ("127.0.0.1", SANDBOX_JUPYTER_PORT)
            }
        run_kwargs["detach"] = True
        container = client.containers.run(config.docker_image, **run_kwargs)
        if _is_containerized_runtime() and not config.network_disabled:
            _attach_sandbox_to_control_network(
                client,
                container,
                alias=SANDBOX_CONTAINER_NAME,
            )
        _seed_pnpm_offline_store(container)
        try:
            container.reload()
            deadline = time.monotonic() + max(10, config.timeout_seconds)
            selected_host = None
            while time.monotonic() < deadline:
                container.reload()
                for candidate_host in _sandbox_connection_hosts(container):
                    base_url = f"http://{candidate_host}:{SANDBOX_JUPYTER_PORT}"
                    try:
                        response = requests.get(f"{base_url}/api/kernels", timeout=1)
                        response.raise_for_status()
                        if isinstance(response.json(), list):
                            selected_host = candidate_host
                            break
                    except Exception:
                        continue
                if selected_host is not None:
                    break
                time.sleep(0.5)
            if selected_host is None:
                raise RuntimeError("Jupyter kernel API did not become ready")
            executor = _RecoveredDockerExecutor(
                container,
                logger_,
                selected_host,
                config.extra_kwargs.get("additional_imports", []),
            )
            executor._nexent_sandbox_config = config
            logger_.info(
                "Created shared Docker sandbox %s (url=%s, network=%s)",
                container.short_id,
                executor.base_url,
                SANDBOX_NETWORK_NAME,
            )
            return executor
        except Exception:
            try:
                container.remove(force=True)
            except Exception:
                pass
            raise

    def _build_docker_executor(
        self,
        config: SandboxConfig,
        logger_: logging.Logger,
        host_tools_exist: bool = False,
        session_container_group: Optional[_SessionDockerContainerGroup] = None,
    ) -> Any:
        """Construct a Docker executor with Nexent hardening."""
        try:
            from smolagents.remote_executors import DockerExecutor

            if DockerExecutor is None:
                raise ImportError("DockerExecutor is unavailable")
        except ImportError:
            logger_.error(
                "DockerExecutor requires smolagents[docker]. "
                "Install it with: pip install 'smolagents[docker]'. "
                "Falling back to LocalPythonExecutor."
            )
            return _wrap_executor(
                _make_local_executor(config.extra_kwargs.get("additional_authorized_imports", [])),
                config,
                logger_,
            )

        network_mode = "host bridge" if host_tools_exist else ("none" if config.network_disabled else "bridge")
        container_run_kwargs = {
            "mem_limit": f"{config.memory_limit_mb}m",
            "cpu_period": 100000,
            "cpu_quota": int(config.cpu_quota * 100000),
            "network_disabled": (
                config.network_disabled and not host_tools_exist
                if config.scope != SandboxScope.SYSTEM
                else False
            ),
        }
        if host_tools_exist and not _is_containerized_runtime():
            import docker

            docker_client = docker.from_env()
            container_run_kwargs["extra_hosts"] = {
                "host.docker.internal": _docker_bridge_gateway(docker_client)
            }
        if not config.network_disabled:
            container_environment = dict(container_run_kwargs.get("environment") or {})
            container_environment.update(_ONLINE_PACKAGE_ENV)
            container_run_kwargs["environment"] = container_environment
        workspace_root = config.extra_kwargs.get("workspace_root")
        if workspace_root:
            resolved_workspace_root = str(Path(workspace_root).resolve())
            workspace_volume_name = config.extra_kwargs.get("workspace_volume_name")
            if not workspace_volume_name:
                Path(resolved_workspace_root).mkdir(parents=True, exist_ok=True)
            container_run_kwargs["volumes"] = {
                (workspace_volume_name or resolved_workspace_root): {
                    "bind": resolved_workspace_root,
                    "mode": "rw",
                }
            }
        if config.scope == SandboxScope.SYSTEM:
            try:
                import docker

                docker_client = docker.from_env()
                _ensure_sandbox_control_network(docker_client)
                container_run_kwargs.update({
                    "name": SANDBOX_CONTAINER_NAME,
                    "labels": {"com.nexent.sandbox": "runtime"},
                    "command": _kernel_gateway_command(),
                })
                if config.network_disabled:
                    container_run_kwargs["network"] = SANDBOX_NETWORK_NAME
                else:
                    container_run_kwargs.pop("network", None)
                logger_.debug("Using Docker network %s for system sandbox", SANDBOX_NETWORK_NAME)
            except Exception as exc:
                logger_.warning("Could not prepare Docker network %s: %s", SANDBOX_NETWORK_NAME, exc)

        if host_tools_exist and config.network_disabled:
            logger_.warning(
                "Docker network isolation is relaxed to bridge mode so sandbox code can call "
                "token-authenticated Nexent host tools"
            )

        try:
            if config.scope == SandboxScope.SYSTEM:
                executor = self._build_system_docker_executor(
                    config,
                    logger_,
                    container_run_kwargs,
                )
            else:
                if session_container_group is None:
                    executor = self._build_session_docker_executor(
                        config,
                        logger_,
                        container_run_kwargs,
                    )
                else:
                    executor = self._lease_session_docker_kernel(
                        config,
                        logger_,
                        session_container_group,
                    )
            executor._nexent_sandbox_config = config  # store for pool bookkeeping
            executor._nexent_backend = "docker"
            logger_.debug(
                "DockerExecutor created (image=%s, mem=%dm, network=%s)",
                config.docker_image,
                config.memory_limit_mb,
                network_mode,
            )
        except Exception as exc:
            logger_.error(
                "DockerExecutor construction failed: %s. "
                "Falling back to LocalPythonExecutor.",
                exc,
            )
            return _wrap_executor(
                _make_local_executor(config.extra_kwargs.get("additional_authorized_imports", [])),
                config,
                logger_,
            )

        if config.scope == SandboxScope.SYSTEM:
            return executor
        if host_tools_exist:
            executor = _install_host_tool_bridge(
                executor,
                logger_,
                request_timeout_seconds=config.host_tool_timeout_seconds,
            )
        return _wrap_executor(executor, config, logger_)

    def _build_wasm_executor(
        self, config: SandboxConfig, logger_: logging.Logger
    ) -> Any:
        """Construct a smolagents WasmExecutor."""
        try:
            from smolagents.remote_executors import WasmExecutor
        except ImportError as exc:
            logger_.error(
                "WasmExecutor requires smolagents[wasm]. "
                "Install it with: pip install 'smolagents[wasm]'. "
                "Falling back to LocalPythonExecutor."
            )
            return _wrap_executor(
                _make_local_executor(config.extra_kwargs.get("additional_authorized_imports", [])),
                config,
                logger_,
            )

        try:
            executor = WasmExecutor(
                additional_imports=config.extra_kwargs.get("additional_imports", []),
                logger=_make_smolagents_logger(logger_),
                timeout=config.timeout_seconds,
            )
            executor._nexent_sandbox_config = config
            executor._nexent_backend = "wasm"
        except Exception as exc:
            logger_.error(
                "WasmExecutor construction failed: %s. "
                "Falling back to LocalPythonExecutor.",
                exc,
            )
            return _wrap_executor(
                _make_local_executor(config.extra_kwargs.get("additional_authorized_imports", [])),
                config,
                logger_,
            )

        return _wrap_executor(executor, config, logger_)

    def _is_alive(self, executor: Any) -> bool:
        """Return True if the underlying container is still running."""
        container = getattr(executor, "container", None)
        if container is None:
            return True  # Local executor — always "alive"
        try:
            container.reload()
            return container.status == "running"
        except Exception:
            return False

    def _destroy_executor(self, executor: Any, logger_: logging.Logger) -> None:
        """Synchronously destroy a single executor."""
        cleanup_executor(executor, logger_, timeout=10.0)

    def _start_evictor(self) -> None:
        """Launch the background idle-eviction thread."""
        def _evict_loop() -> None:
            while not self._stop_evict.wait(timeout=self._idle_ttl_seconds / 2):
                self._evict_idle(logger)
                self._clean_stale(logger)

        self._evict_thread = threading.Thread(target=_evict_loop, daemon=True, name="SandboxPoolEvictor")
        self._evict_thread.start()

    def _evict_idle(self, logger_: logging.Logger) -> None:
        """Remove containers idle for longer than idle_ttl_seconds."""
        deadline = _now() - self._idle_ttl_seconds
        with self._lock:
            for image, pool in list(self._pools.items()):
                survivors = []
                for ex in pool:
                    if self._last_touch.get(id(ex), 0) < deadline:
                        self._destroy_executor(ex, logger_)
                        logger_.debug("Evicted idle sandbox (image=%s)", image)
                    else:
                        survivors.append(ex)
                self._pools[image] = survivors

    def _clean_stale(self, logger_: logging.Logger) -> None:
        """Remove dead containers from all pools."""
        with self._lock:
            for image, pool in list(self._pools.items()):
                survivors = []
                for ex in pool:
                    if self._is_alive(ex):
                        survivors.append(ex)
                    else:
                        self._destroy_executor(ex, logger_)
                        logger_.debug("Removed stale sandbox from pool (image=%s)", image)
                self._pools[image] = survivors


def _wrap_executor(executor: Any, config: SandboxConfig, logger_: logging.Logger) -> Any:
    """Apply shell guard and diagnostic wrapper to an executor (except LOCAL)."""
    if config.level == SandboxLevel.LOCAL:
        return executor
    if getattr(type(executor), "_nexent_kernel_lease", False):
        executor._nexent_shell_policy = config.shell_policy
        executor._nexent_allow_package_installs = not config.network_disabled
        executor._nexent_online_user_site = not config.network_disabled
        return executor
    executor = _install_shell_guard(
        executor,
        config.shell_policy,
        logger_,
        allow_package_installs=not config.network_disabled,
    )
    if config.level == SandboxLevel.DOCKER and not config.network_disabled:
        executor = _install_online_user_site(executor)
    executor = _wrap_with_diagnostics(executor, logger_)
    return executor


def _make_local_executor(additional_imports: list[str]) -> Any:
    """Build a LocalPythonExecutor with the standard safe-import list."""
    from smolagents.local_python_executor import LocalPythonExecutor
    executor = LocalPythonExecutor(additional_imports)
    executor._nexent_backend = "local"
    return executor


def _now() -> float:
    import time
    return time.time()


# ----------------------------------------------------------------------
# Legacy factory (backwards-compatible entry point from sandbox-design.md §7)
# ----------------------------------------------------------------------


def build_python_executor(
    config: SandboxConfig,
    logger_: logging.Logger,
    managed_agents_exist: bool = False,
    host_tools_exist: bool = False,
    session_container_group: Optional[_SessionDockerContainerGroup] = None,
) -> Any:
    """
    Factory function: build a python_executor from ``SandboxConfig``.

    This is the canonical entry point used by ``NexentAgent.create_single_agent``.
    It delegates to ``SandboxPoolManager`` for system-scoped executors and builds
    a fresh per-run executor for session-scoped requests.

    Args:
        config: sandbox configuration.
        logger_: logger instance.
        managed_agents_exist: Deprecated compatibility flag. Managed-agent
            orchestration is proxied to the Runtime process, so it no longer
            requires disabling the configured sandbox.
        session_container_group: Internal agent-tree container group. When set,
            a session-scoped Docker executor leases a new isolated kernel from
            the existing container instead of starting another container.

    Returns:
        A wrapped python_executor.  Never raises — always returns a usable
        executor (falls back to LocalPythonExecutor on any error).
    """
    pool = SandboxPoolManager.get_instance()

    if config.scope == SandboxScope.SESSION:
        # Per-run fresh executor — pool manager still calls _build_executor
        # but we immediately destroy it when release() is called.
        if session_container_group is None:
            executor = pool.acquire(config, logger_, host_tools_exist)
        else:
            executor = pool.acquire(
                config,
                logger_,
                host_tools_exist,
                session_container_group=session_container_group,
            )
        return executor

    # SYSTEM scope — pool manager handles lifecycle.
    return pool.acquire(config, logger_, host_tools_exist)


def release_python_executor(executor: Any, logger_: logging.Logger) -> None:
    """
    Return an executor to its pool (or destroy it for SESSION scope).

    Call this in the ``finally`` block of ``agent_run_with_observer``::

        finally:
            from .sandbox import release_python_executor, _sync_outputs_to_minio
            executor = getattr(self.agent, "python_executor", None)
            scope = getattr(self, "_sandbox_scope", None)

            if executor is not None and scope is not None and scope != "session":
                # sync outputs before destroying
                ...

            release_python_executor(executor, self.logger)
            if hasattr(self.agent, "python_executor"):
                self.agent.python_executor = None
    """
    if executor is None:
        return
    pool = SandboxPoolManager.get_instance()
    pool.release(executor, logger_)
