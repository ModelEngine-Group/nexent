"""Fixed predeployed OpenJiuwen AIO sandbox integration."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import os
import re
import shlex
import shutil
import stat
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from nexent.skills.script_executor import (
    SkillScriptExecutionRequest,
)

from adapters.openjiuwen_compat import (
    OpenJiuwenSandboxAPI,
    load_openjiuwen_sandbox_api,
)

from .config import OpenJiuwenSandboxSettings


logger = logging.getLogger(__name__)


DEFAULT_MAX_STAGED_FILES = 512
DEFAULT_MAX_STAGED_FILE_BYTES = 100 * 1024 * 1024
DEFAULT_MAX_OUTPUT_FILES = 50
DEFAULT_MAX_OUTPUT_FILE_BYTES = 100 * 1024 * 1024
DEFAULT_MAX_OUTPUT_TOTAL_BYTES = 500 * 1024 * 1024


class OpenJiuwenSandboxError(RuntimeError):
    """Base error for the fixed OpenJiuwen sandbox integration."""

    def __init__(self, message: str, *, stage: str = "sandbox"):
        self.stage = stage
        super().__init__(message)


class OpenJiuwenSandboxUnavailableError(OpenJiuwenSandboxError):
    """Raised when the fixed sandbox cannot be initialized or reached."""


class OpenJiuwenSandboxValidationError(OpenJiuwenSandboxError):
    """Raised when a Skill or argument cannot be staged safely."""


class OpenJiuwenSandboxExecutionError(OpenJiuwenSandboxError):
    """Raised when a sandbox operation or command fails."""


class OpenJiuwenDevSandboxService:
    """Process-scoped SysOperation connected to one shared AIO endpoint."""

    SYS_OPERATION_ID = "openjiuwen_dev_sandbox"

    def __init__(
        self,
        settings: OpenJiuwenSandboxSettings,
        *,
        api: OpenJiuwenSandboxAPI
        | Callable[[], OpenJiuwenSandboxAPI]
        | None = None,
    ):
        self.settings = settings
        self._api = api
        self._resolved_api: OpenJiuwenSandboxAPI | None = None
        self._sys_operation: Any | None = None
        self._started = False
        self._healthy = False

    @property
    def enabled(self) -> bool:
        """Return whether this deployment enabled fixed sandbox execution."""
        return self.settings.enabled

    @property
    def healthy(self) -> bool:
        """Return whether registration and the latest health check succeeded."""
        return self.enabled and self._started and self._healthy

    @property
    def sys_operation(self) -> Any:
        """Return the registered process-local SysOperation instance."""
        if not self.healthy or self._sys_operation is None:
            raise OpenJiuwenSandboxUnavailableError(
                "OpenJiuwen sandbox is not ready.",
                stage="health",
            )
        return self._sys_operation

    def validate_installation(self) -> None:
        """Validate config and optional SDK dependencies without endpoint I/O."""
        if not self.enabled:
            return
        self.settings.validate()
        self._resolve_api()

    async def start(self) -> None:
        """Register the process-local SYSTEM SysOperation and probe the endpoint."""
        if not self.enabled or self.healthy:
            return
        self.settings.validate()
        api = self._resolve_api()
        resource_mgr = api.Runner.resource_mgr
        card = api.SysOperationCard(
            id=self.SYS_OPERATION_ID,
            name="nexent_openjiuwen_fixed_sandbox",
            description="Fixed predeployed AIO sandbox for Nexent Skill scripts.",
            mode=api.OperationMode.SANDBOX,
            gateway_config=api.SandboxGatewayConfig(
                isolation=api.SandboxIsolationConfig(
                    container_scope=api.ContainerScope.SYSTEM,
                    prefix="nexent-dev",
                ),
                launcher_config=api.PreDeployLauncherConfig(
                    base_url=self.settings.base_url,
                    sandbox_type=self.settings.provider,
                    on_stop="keep",
                ),
                timeout_seconds=self.settings.request_timeout_seconds,
            ),
        )
        try:
            add_result = resource_mgr.add_sys_operation(card)
            if not _resource_result_ok(add_result):
                raise OpenJiuwenSandboxUnavailableError(
                    "OpenJiuwen sandbox registration failed.",
                    stage="startup",
                )
            self._sys_operation = resource_mgr.get_sys_operation(
                self.SYS_OPERATION_ID
            )
            if self._sys_operation is None:
                raise OpenJiuwenSandboxUnavailableError(
                    "OpenJiuwen sandbox registration produced no resource.",
                    stage="startup",
                )
            self._started = True
            await self.health_check()
        except Exception as exc:
            self._healthy = False
            await self.stop()
            if isinstance(exc, OpenJiuwenSandboxError):
                raise
            raise OpenJiuwenSandboxUnavailableError(
                "OpenJiuwen sandbox startup failed.",
                stage="startup",
            ) from exc
        logger.info(
            "OpenJiuwen fixed sandbox started, sys_operation_id=%s, endpoint_host_hash=%s",
            self.SYS_OPERATION_ID,
            _endpoint_host_hash(self.settings.base_url),
        )

    async def health_check(self) -> None:
        """Verify FS and Shell calls using a unique probe workspace."""
        if self._sys_operation is None:
            raise OpenJiuwenSandboxUnavailableError(
                "OpenJiuwen sandbox is not registered.",
                stage="health",
            )
        probe_root = _join_posix(
            self.settings.workspace_root,
            ".probe",
            uuid.uuid4().hex,
        )
        shell = self._sys_operation.shell()
        fs = self._sys_operation.fs()
        try:
            await _require_shell_command_success(
                shell.execute_cmd(
                    shlex.join(["mkdir", "-p", probe_root]),
                    timeout=self.settings.request_timeout_seconds,
                ),
                "health_mkdir",
            )
            probe_file = _join_posix(probe_root, "health.txt")
            await _require_operation_success(
                fs.write_file(
                    probe_file,
                    "ok",
                    prepend_newline=False,
                    append_newline=False,
                ),
                "health_write",
            )
            list_result = await _require_operation_success(
                fs.list_files(probe_root, recursive=False),
                "health_list",
            )
            listed_names = {
                str(getattr(item, "name", ""))
                for item in _operation_list_items(list_result)
            }
            if "health.txt" not in listed_names:
                raise OpenJiuwenSandboxUnavailableError(
                    "OpenJiuwen sandbox health check returned incomplete data.",
                    stage="health",
                )
        except Exception as exc:
            self._healthy = False
            if isinstance(exc, OpenJiuwenSandboxError):
                raise
            raise OpenJiuwenSandboxUnavailableError(
                "OpenJiuwen sandbox health check failed.",
                stage="health",
            ) from exc
        finally:
            try:
                await _require_shell_command_success(
                    shell.execute_cmd(
                        shlex.join(["rm", "-rf", probe_root]),
                        timeout=self.settings.request_timeout_seconds,
                    ),
                    "health_cleanup",
                )
            except Exception:
                logger.warning(
                    "OpenJiuwen sandbox probe cleanup failed, probe_hash=%s",
                    hashlib.sha256(probe_root.encode("utf-8")).hexdigest()[:12],
                )
        self._healthy = True

    async def stop(self) -> None:
        """Remove this process's SysOperation without stopping the container."""
        api = self._resolved_api
        was_started = self._started
        self._healthy = False
        self._started = False
        self._sys_operation = None
        if api is None or not was_started:
            return
        try:
            result = api.Runner.resource_mgr.remove_sys_operation(
                self.SYS_OPERATION_ID
            )
            if not _resource_result_ok(result):
                logger.warning(
                    "OpenJiuwen sandbox SysOperation cleanup returned failure, sys_operation_id=%s",
                    self.SYS_OPERATION_ID,
                )
        except Exception:
            logger.warning(
                "OpenJiuwen sandbox SysOperation cleanup failed, sys_operation_id=%s",
                self.SYS_OPERATION_ID,
                exc_info=True,
            )

    def _resolve_api(self) -> OpenJiuwenSandboxAPI:
        if self._resolved_api is not None:
            return self._resolved_api
        if isinstance(self._api, OpenJiuwenSandboxAPI):
            self._resolved_api = self._api
        elif callable(self._api):
            self._resolved_api = self._api()
        else:
            self._resolved_api = load_openjiuwen_sandbox_api()
        return self._resolved_api


class SandboxSkillScriptExecutor:
    """Execute authorized Skill scripts in the shared fixed sandbox."""

    def __init__(
        self,
        *,
        service: OpenJiuwenDevSandboxService,
        request_id: str,
        tenant_id: str,
        run_control: Any | None = None,
        attachments: Mapping[str, str] | None = None,
        host_staging_dirs: list[str] | None = None,
        diagnostics: list[dict[str, str]] | None = None,
        host_staging_root: str | None = None,
        execution_timeout_seconds: int | None = None,
        max_staged_files: int = DEFAULT_MAX_STAGED_FILES,
        max_staged_file_bytes: int = DEFAULT_MAX_STAGED_FILE_BYTES,
        max_output_files: int = DEFAULT_MAX_OUTPUT_FILES,
        max_output_file_bytes: int = DEFAULT_MAX_OUTPUT_FILE_BYTES,
        max_output_total_bytes: int = DEFAULT_MAX_OUTPUT_TOTAL_BYTES,
    ):
        self.service = service
        self.request_id = request_id
        self.tenant_id = tenant_id
        self.run_control = run_control
        self.attachments = {
            os.path.abspath(path): name
            for path, name in dict(attachments or {}).items()
        }
        self.host_staging_dirs = host_staging_dirs if host_staging_dirs is not None else []
        self.diagnostics = diagnostics if diagnostics is not None else []
        self.host_staging_root = host_staging_root or os.path.join(
            tempfile.gettempdir(), "nexent-sandbox"
        )
        self.execution_timeout_seconds = execution_timeout_seconds
        self.max_staged_files = max_staged_files
        self.max_staged_file_bytes = max_staged_file_bytes
        self.max_output_files = max_output_files
        self.max_output_file_bytes = max_output_file_bytes
        self.max_output_total_bytes = max_output_total_bytes
        self._active_executions: dict[str, dict[str, str]] = {}
        self._cancelled = False

    async def execute(self, request: SkillScriptExecutionRequest) -> str:
        """Stage, execute and collect one authorized Skill script."""
        await self.service.start()
        self._raise_if_cancelled()
        started_at = time.monotonic()
        execution_id = uuid.uuid4().hex
        request_hash = hashlib.sha256(
            f"{self.tenant_id}:{self.request_id}:{execution_id}".encode("utf-8")
        ).hexdigest()[:24]
        workspace_root = _join_posix(
            self.service.settings.workspace_root,
            request_hash,
        )
        process_marker = f"nexent-sandbox-{request_hash}"
        context = {
            "workspace_root": workspace_root,
            "process_marker": process_marker,
        }
        self._active_executions[execution_id] = context
        logger.info(
            "OpenJiuwen sandbox Skill execution started, request_id=%s, "
            "skill_name=%s, attachment_count=%d",
            self.request_id,
            request.skill_name,
            len(self.attachments),
        )
        try:
            _validate_skill_name(request.skill_name)
            effective_request = request
            if self.execution_timeout_seconds is not None:
                effective_request = request.model_copy(
                    update={
                        "timeout_seconds": min(
                            request.timeout_seconds,
                            self.execution_timeout_seconds,
                        )
                    }
                )
            result = await self._execute_in_workspace(
                effective_request,
                request_hash,
                context,
            )
            logger.info(
                "OpenJiuwen sandbox Skill execution finished, request_id=%s, "
                "skill_name=%s, status=completed, duration_ms=%d",
                self.request_id,
                request.skill_name,
                _elapsed_ms(started_at),
            )
            return result
        except asyncio.CancelledError:
            self._discard_host_staging(request_hash)
            self._record_diagnostic("cancel", "cancelled")
            logger.info(
                "OpenJiuwen sandbox Skill execution finished, request_id=%s, "
                "skill_name=%s, status=cancelled, duration_ms=%d",
                self.request_id,
                request.skill_name,
                _elapsed_ms(started_at),
            )
            raise
        except OpenJiuwenSandboxError as exc:
            self._discard_host_staging(request_hash)
            self._record_diagnostic(exc.stage, "error")
            logger.warning(
                "OpenJiuwen sandbox Skill execution failed, request_id=%s, "
                "skill_name=%s, sandbox_stage=%s, error_type=%s, duration_ms=%d",
                self.request_id,
                request.skill_name,
                exc.stage,
                type(exc).__name__,
                _elapsed_ms(started_at),
            )
            raise
        except Exception:
            self._discard_host_staging(request_hash)
            self._record_diagnostic("sandbox", "error")
            logger.exception(
                "OpenJiuwen sandbox Skill execution failed, request_id=%s, "
                "skill_name=%s, sandbox_stage=sandbox, duration_ms=%d",
                self.request_id,
                request.skill_name,
                _elapsed_ms(started_at),
            )
            raise
        finally:
            await self._cleanup_workspace(context)
            self._active_executions.pop(execution_id, None)

    async def cancel(self) -> None:
        """Best-effort terminate only process groups owned by this request."""
        self._cancelled = True
        for context in list(self._active_executions.values()):
            await self._terminate_execution(context)

    async def _execute_in_workspace(
        self,
        request: SkillScriptExecutionRequest,
        request_hash: str,
        context: Mapping[str, str],
    ) -> str:
        sys_operation = self.service.sys_operation
        fs = sys_operation.fs()
        shell = sys_operation.shell()
        workspace_root = context["workspace_root"]
        input_root = _join_posix(workspace_root, "input")
        skill_root = _join_posix(workspace_root, "skills", request.skill_name)
        output_root = _join_posix(workspace_root, "output")
        tmp_root = _join_posix(workspace_root, "tmp")
        directories = [input_root, skill_root, output_root, tmp_root]
        await _require_shell_command_success(
            shell.execute_cmd(
                shlex.join(["rm", "-rf", workspace_root]),
                timeout=self.service.settings.request_timeout_seconds,
            ),
            "workspace_cleanup_before",
        )
        await _require_shell_command_success(
            shell.execute_cmd(
                shlex.join(["mkdir", "-p", *directories]),
                timeout=self.service.settings.request_timeout_seconds,
            ),
            "workspace_create",
        )
        self._raise_if_cancelled()

        await self._stage_skill(fs, request, skill_root)
        attachment_mapping = await self._stage_attachments(fs, input_root)
        self._raise_if_cancelled()

        relative_script = os.path.relpath(request.script_path, request.skill_root)
        if ".." in Path(relative_script).parts or os.path.isabs(relative_script):
            raise OpenJiuwenSandboxValidationError(
                "Skill script escapes the authorized Skill root.",
                stage="validation",
            )
        remote_script = _join_posix(skill_root, *Path(relative_script).parts)
        argv = self._map_params(request.params, attachment_mapping)
        interpreter = "python3" if remote_script.endswith(".py") else "bash"
        command = shlex.join([interpreter, remote_script, *argv])
        marked_command = (
            f"exec -a {shlex.quote(context['process_marker'])} "
            f"{command}"
        )
        command_result = await _require_operation_success(
            shell.execute_cmd(
                marked_command,
                cwd=skill_root,
                timeout=request.timeout_seconds,
                environment={
                    "NEXENT_REQUEST_MARKER": context["process_marker"],
                    "NEXENT_OUTPUT_DIR": output_root,
                    "TMPDIR": tmp_root,
                },
            ),
            "execute",
        )
        self._raise_if_cancelled()
        command_data = getattr(command_result, "data", None)
        stdout = str(getattr(command_data, "stdout", "") or "")
        stderr = str(getattr(command_data, "stderr", "") or "")
        exit_code = getattr(command_data, "exit_code", 0)
        if exit_code not in (None, 0):
            return json.dumps({"error": stderr, "output": stdout})

        artifact_payloads = await self._download_artifacts(
            fs,
            output_root=output_root,
            request_hash=request_hash,
        )
        output_parts = [stdout] if stdout else []
        output_parts.extend(
            json.dumps(payload, ensure_ascii=False) for payload in artifact_payloads
        )
        return "\n".join(output_parts)

    async def _stage_skill(
        self,
        fs: Any,
        request: SkillScriptExecutionRequest,
        remote_skill_root: str,
    ) -> None:
        unresolved_skill_root = Path(request.skill_root)
        if unresolved_skill_root.is_symlink():
            raise OpenJiuwenSandboxValidationError(
                "Skill staging rejected a symbolic-link root.",
                stage="validation",
            )
        skill_root = unresolved_skill_root.resolve()
        if not skill_root.is_dir():
            raise OpenJiuwenSandboxValidationError(
                "Authorized Skill directory is unavailable.",
                stage="validation",
            )
        staged_files = 0
        for directory, dir_names, file_names in os.walk(skill_root, followlinks=False):
            directory_path = Path(directory)
            for dir_name in dir_names:
                child = directory_path / dir_name
                if child.is_symlink():
                    raise OpenJiuwenSandboxValidationError(
                        "Skill staging rejected a symbolic link.",
                        stage="validation",
                    )
            for file_name in file_names:
                path = directory_path / file_name
                self._validate_staged_file(path, skill_root)
                staged_files += 1
                if staged_files > self.max_staged_files:
                    raise OpenJiuwenSandboxValidationError(
                        "Skill staging exceeded the file-count limit.",
                        stage="validation",
                    )
                relative_path = path.relative_to(skill_root)
                remote_path = _join_posix(
                    remote_skill_root,
                    *relative_path.parts,
                )
                await _require_operation_success(
                    fs.upload_file(
                        str(path),
                        remote_path,
                        overwrite=True,
                        create_parent_dirs=True,
                    ),
                    "skill_upload",
                )

    async def _stage_attachments(
        self,
        fs: Any,
        input_root: str,
    ) -> dict[str, str]:
        mapping: dict[str, str] = {}
        used_names: set[str] = set()
        if len(self.attachments) > self.max_staged_files:
            raise OpenJiuwenSandboxValidationError(
                "Attachment staging exceeded the file-count limit.",
                stage="validation",
            )
        for index, (host_path, preferred_name) in enumerate(
            sorted(self.attachments.items())
        ):
            path = Path(host_path)
            self._validate_staged_file(path, path.parent)
            safe_name = _safe_file_name(preferred_name or path.name, index, used_names)
            remote_path = _join_posix(input_root, safe_name)
            await _require_operation_success(
                fs.upload_file(
                    str(path),
                    remote_path,
                    overwrite=True,
                    create_parent_dirs=True,
                ),
                "attachment_upload",
            )
            mapping[os.path.abspath(host_path)] = remote_path
        return mapping

    def _validate_staged_file(self, path: Path, allowed_root: Path) -> None:
        try:
            file_stat = path.lstat()
            resolved = path.resolve(strict=True)
            root_resolved = allowed_root.resolve(strict=True)
        except (FileNotFoundError, OSError) as exc:
            raise OpenJiuwenSandboxValidationError(
                "Sandbox staging source is unavailable.",
                stage="validation",
            ) from exc
        if path.is_symlink() or not stat.S_ISREG(file_stat.st_mode):
            raise OpenJiuwenSandboxValidationError(
                "Sandbox staging accepts regular files only.",
                stage="validation",
            )
        if resolved != root_resolved and root_resolved not in resolved.parents:
            raise OpenJiuwenSandboxValidationError(
                "Sandbox staging source escapes its authorized root.",
                stage="validation",
            )
        if file_stat.st_size > self.max_staged_file_bytes:
            raise OpenJiuwenSandboxValidationError(
                "Sandbox staging source exceeded the file-size limit.",
                stage="validation",
            )

    def _map_params(
        self,
        params: str | None,
        attachment_mapping: Mapping[str, str],
    ) -> list[str]:
        if not params:
            return []
        if "\x00" in params:
            raise OpenJiuwenSandboxValidationError(
                "Skill parameters contain a NUL byte.",
                stage="validation",
            )
        try:
            argv = shlex.split(params)
        except ValueError as exc:
            raise OpenJiuwenSandboxValidationError(
                "Skill parameters could not be parsed.",
                stage="validation",
            ) from exc
        mapped: list[str] = []
        for argument in argv:
            if os.path.isabs(argument):
                mapped.append(self._map_authorized_path(argument, attachment_mapping))
                continue
            if argument.startswith("--") and "=" in argument:
                key, value = argument.split("=", 1)
                if os.path.isabs(value):
                    value = self._map_authorized_path(value, attachment_mapping)
                mapped.append(f"{key}={value}")
                continue
            if ".." in PurePosixPath(argument).parts:
                raise OpenJiuwenSandboxValidationError(
                    "Skill parameters contain a path traversal segment.",
                    stage="validation",
                )
            mapped.append(argument)
        return mapped

    @staticmethod
    def _map_authorized_path(
        path: str,
        attachment_mapping: Mapping[str, str],
    ) -> str:
        mapped = attachment_mapping.get(os.path.abspath(path))
        if mapped is None:
            raise OpenJiuwenSandboxValidationError(
                "Skill parameters reference an unauthorized absolute path.",
                stage="validation",
            )
        return mapped

    async def _download_artifacts(
        self,
        fs: Any,
        *,
        output_root: str,
        request_hash: str,
    ) -> list[dict[str, Any]]:
        list_result = await _require_operation_success(
            fs.list_files(output_root, recursive=True),
            "output_list",
        )
        items = [
            item
            for item in _operation_list_items(list_result)
            if not bool(getattr(item, "is_directory", False))
        ]
        if len(items) > self.max_output_files:
            raise OpenJiuwenSandboxExecutionError(
                "Sandbox output exceeded the file-count limit.",
                stage="artifact",
            )
        total_size = 0
        host_output_root = os.path.join(
            self.host_staging_root,
            request_hash,
            "output",
        )
        request_staging_root = os.path.dirname(host_output_root)
        if items and request_staging_root not in self.host_staging_dirs:
            self.host_staging_dirs.append(request_staging_root)
        payloads: list[dict[str, Any]] = []
        downloaded_total_size = 0
        for item in items:
            source_path = str(getattr(item, "path", "") or "")
            relative_path = _relative_sandbox_output_path(source_path, output_root)
            file_size = int(getattr(item, "size", 0) or 0)
            if file_size > self.max_output_file_bytes:
                raise OpenJiuwenSandboxExecutionError(
                    "Sandbox output exceeded the per-file size limit.",
                    stage="artifact",
                )
            total_size += file_size
            if total_size > self.max_output_total_bytes:
                raise OpenJiuwenSandboxExecutionError(
                    "Sandbox output exceeded the total size limit.",
                    stage="artifact",
                )
            local_path = os.path.abspath(
                os.path.join(host_output_root, *relative_path.parts)
            )
            allowed_root = os.path.abspath(host_output_root)
            if local_path != allowed_root and not local_path.startswith(
                allowed_root + os.sep
            ):
                raise OpenJiuwenSandboxExecutionError(
                    "Sandbox output path escaped the host staging root.",
                    stage="artifact",
                )
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            await _require_operation_success(
                fs.download_file(
                    source_path,
                    local_path,
                    overwrite=True,
                    create_parent_dirs=True,
                ),
                "output_download",
            )
            actual_size = os.path.getsize(local_path)
            if actual_size > self.max_output_file_bytes:
                raise OpenJiuwenSandboxExecutionError(
                    "Downloaded sandbox output exceeded the per-file size limit.",
                    stage="artifact",
                )
            downloaded_total_size += actual_size
            if downloaded_total_size > self.max_output_total_bytes:
                raise OpenJiuwenSandboxExecutionError(
                    "Downloaded sandbox output exceeded the total size limit.",
                    stage="artifact",
                )
            payloads.append(
                {
                    "absolute_path": local_path,
                    "file_name": relative_path.name,
                }
            )
        return payloads

    async def _terminate_execution(self, context: Mapping[str, str]) -> None:
        try:
            shell = self.service.sys_operation.shell()
        except OpenJiuwenSandboxError:
            return
        marker = context["process_marker"]
        marker_pattern = f"^{re.escape(marker)}( |$)"
        for signal_name in ("TERM", "KILL"):
            try:
                await shell.execute_cmd(
                    shlex.join(
                        ["pkill", f"-{signal_name}", "-f", marker_pattern]
                    ),
                    timeout=5,
                )
            except Exception:
                logger.warning(
                    "OpenJiuwen sandbox process termination failed, request_id=%s, signal=%s",
                    self.request_id,
                    signal_name,
                )
            if signal_name == "TERM":
                await asyncio.sleep(0)

    async def _cleanup_workspace(self, context: Mapping[str, str]) -> None:
        try:
            shell = self.service.sys_operation.shell()
            await _require_shell_command_success(
                shell.execute_cmd(
                    shlex.join(["rm", "-rf", context["workspace_root"]]),
                    timeout=self.service.settings.request_timeout_seconds,
                ),
                "workspace_cleanup",
            )
        except Exception:
            self._record_diagnostic("cleanup", "warning")
            logger.warning(
                "OpenJiuwen sandbox request workspace cleanup failed, request_id=%s, workspace_hash=%s",
                self.request_id,
                hashlib.sha256(
                    context["workspace_root"].encode("utf-8")
                ).hexdigest()[:12],
            )

    def _raise_if_cancelled(self) -> None:
        if self._cancelled or bool(
            self.run_control is not None and self.run_control.is_cancelled()
        ):
            raise asyncio.CancelledError

    def _discard_host_staging(self, request_hash: str) -> None:
        request_staging_root = os.path.abspath(
            os.path.join(self.host_staging_root, request_hash)
        )
        try:
            shutil.rmtree(request_staging_root)
        except FileNotFoundError:
            pass
        except Exception:
            self._record_diagnostic("cleanup", "warning")
            logger.warning(
                "OpenJiuwen sandbox host staging cleanup failed, request_id=%s, "
                "staging_hash=%s",
                self.request_id,
                hashlib.sha256(request_staging_root.encode("utf-8")).hexdigest()[:12],
            )
        self.host_staging_dirs[:] = [
            path
            for path in self.host_staging_dirs
            if os.path.abspath(path) != request_staging_root
        ]

    def _record_diagnostic(self, sandbox_stage: str, status: str) -> None:
        diagnostic = {
            "sandbox_stage": sandbox_stage,
            "status": status,
        }
        if diagnostic not in self.diagnostics:
            self.diagnostics.append(diagnostic)


def cleanup_sandbox_host_staging(paths: list[str]) -> list[str]:
    """Delete request-scoped host staging directories and return failures."""
    failures: list[str] = []
    for path in list(dict.fromkeys(paths)):
        try:
            shutil.rmtree(path, ignore_errors=False)
        except FileNotFoundError:
            continue
        except Exception:
            failures.append(path)
    paths.clear()
    return failures


async def _require_operation_success(result: Any, stage: str) -> Any:
    resolved = await result if inspect.isawaitable(result) else result
    code = getattr(resolved, "code", 0)
    if code not in (None, 0):
        failure_stage = _operation_failure_stage(resolved, stage)
        logger.warning(
            "OpenJiuwen sandbox operation failed, stage=%s, result_code=%s",
            failure_stage,
            code,
        )
        raise OpenJiuwenSandboxExecutionError(
            f"OpenJiuwen sandbox {stage} operation failed.",
            stage=failure_stage,
        )
    return resolved


async def _require_shell_command_success(result: Any, stage: str) -> Any:
    """Require both a successful operation result and a zero shell exit code."""
    resolved = await _require_operation_success(result, stage)
    data = getattr(resolved, "data", None)
    exit_code = getattr(data, "exit_code", None)
    if exit_code not in (None, 0):
        logger.warning(
            "OpenJiuwen sandbox shell command failed, stage=%s, exit_code=%s",
            stage,
            exit_code,
        )
        raise OpenJiuwenSandboxExecutionError(
            f"OpenJiuwen sandbox {stage} command failed.",
            stage=stage,
        )
    return resolved


def _resource_result_ok(result: Any) -> bool:
    if result is None:
        return True
    is_ok = getattr(result, "is_ok", None)
    return bool(is_ok()) if callable(is_ok) else bool(result)


def _operation_list_items(result: Any) -> list[Any]:
    data = getattr(result, "data", None)
    items = getattr(data, "list_items", None)
    return list(items or [])


def _relative_sandbox_output_path(path: str, output_root: str) -> PurePosixPath:
    source = PurePosixPath(path)
    root = PurePosixPath(output_root)
    try:
        relative = source.relative_to(root)
    except ValueError as exc:
        raise OpenJiuwenSandboxExecutionError(
            "Sandbox output escaped the request output directory.",
            stage="artifact",
        ) from exc
    if not relative.parts or ".." in relative.parts:
        raise OpenJiuwenSandboxExecutionError(
            "Sandbox output path is invalid.",
            stage="artifact",
        )
    return relative


def _safe_file_name(name: str, index: int, used_names: set[str]) -> str:
    base_name = os.path.basename(name).strip()
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", base_name) or f"file-{index}"
    stem, extension = os.path.splitext(normalized)
    candidate = normalized
    suffix = 1
    while candidate in used_names:
        candidate = f"{stem}-{suffix}{extension}"
        suffix += 1
    used_names.add(candidate)
    return candidate


def _join_posix(root: str, *parts: str) -> str:
    return str(PurePosixPath(root).joinpath(*parts))


def _validate_skill_name(skill_name: str) -> None:
    if (
        not skill_name
        or skill_name in {".", ".."}
        or "\x00" in skill_name
        or "/" in skill_name
        or "\\" in skill_name
    ):
        raise OpenJiuwenSandboxValidationError(
            "Skill name is not safe for sandbox staging.",
            stage="validation",
        )


def _operation_failure_stage(result: Any, default: str) -> str:
    message = str(getattr(result, "message", "") or "").lower()
    if "timeout" in message or "timed out" in message:
        return "timeout"
    resource_markers = (
        "no space",
        "resource",
        "out of memory",
        "memory limit",
        "too many processes",
        "pid limit",
    )
    if any(marker in message for marker in resource_markers):
        return "resource"
    return default


def _endpoint_host_hash(base_url: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(base_url)
    host = parsed.netloc or parsed.path
    return hashlib.sha256(host.encode("utf-8")).hexdigest()[:12]


def _elapsed_ms(started_at: float) -> int:
    return int((time.monotonic() - started_at) * 1000)
