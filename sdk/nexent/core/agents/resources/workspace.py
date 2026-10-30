# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Run workspace mapping, file synchronization and executor resource ownership."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import shutil
import tarfile
from concurrent.futures import CancelledError
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Dict, List, Optional

from nexent.core.agents.prompt.user_context import render_user_context
from nexent.core.agents.resources.compatibility.smolagents_tools import deferred_executor_type
from nexent.core.utils.observer import ProcessType


logger = logging.getLogger(__name__)


def validate_container_root(value: str) -> PurePosixPath:
    """Reject host paths and traversal before constructing a container path."""
    path = PurePosixPath(value)
    if not path.is_absolute() or path == PurePosixPath('/') or '\\' in value or ':' in value or '..' in path.parts:
        raise ValueError('container workspace must be a non-root POSIX absolute path')
    return path


@dataclass(frozen=True)
class SandboxWorkspace:
    host_root: Path
    container_root: PurePosixPath

    def __post_init__(self):
        object.__setattr__(self, 'host_root', Path(self.host_root).resolve())
        object.__setattr__(self, 'container_root', validate_container_root(str(self.container_root)))

    def to_container(self, path: str | Path) -> PurePosixPath:
        relative = Path(path).resolve().relative_to(self.host_root)
        return self.container_root.joinpath(*relative.parts)

    def to_host(self, value: str) -> Path:
        """Translate an absolute kernel path and enforce the resolved host boundary."""
        path = validate_container_root(value)
        relative = path.relative_to(self.container_root)
        # Reject Windows-special components, including alternate data streams.
        if any(PureWindowsPath(part).is_reserved() for part in relative.parts):
            raise ValueError('Reserved host filename')
        target = self.host_root.joinpath(*relative.parts).resolve()
        target.relative_to(self.host_root)
        return target

    def resolve_file(self, value: str, base: str | Path) -> Path:
        """Resolve a tool path without changing that tool's relative-path convention."""
        base_path = Path(base).resolve()
        base_path.relative_to(self.host_root)
        if value.startswith('/'):
            target = self.to_host(value)
        else:
            if '..' in PureWindowsPath(value).parts:
                raise ValueError('Workspace traversal is not allowed')
            target = (base_path / value).resolve()
        target.relative_to(base_path)
        return target

    def for_run(self, host_run: str | Path) -> 'SandboxWorkspace':
        return SandboxWorkspace(Path(host_run), self.to_container(host_run))

    @property
    def mount_id(self) -> str:
        payload = json.dumps([os.path.normcase(str(self.host_root)), str(self.container_root)])
        return hashlib.sha256(payload.encode()).hexdigest()

    def matches_mount(self, mount: dict) -> bool:
        """Compare Desktop's Linux view of drive paths with the configured source."""
        source = str(mount.get('Source', '')).replace('\\', '/')
        expected = str(self.host_root).replace('\\', '/')
        if self.host_root.drive:
            for prefix in ('/run/desktop/mnt/host/', '/host_mnt/'):
                if source.startswith(prefix):
                    tail = source[len(prefix):]
                    if len(tail) >= 2 and tail[1] == '/':
                        source = tail[0] + ':' + tail[1:]
                    break
            source, expected = source.casefold(), expected.casefold()
        return (
            mount.get('Type') == 'bind' and mount.get('RW') is True
            and mount.get('Destination') == str(self.container_root)
            and source.rstrip('/') == expected.rstrip('/')
        )


def probe_workspace(container, workspace: PurePosixPath) -> None:
    """Verify traversal and real read/write access as the container's configured user."""
    code = (
        'import os,tempfile; from pathlib import Path; '
        f'p=Path({str(workspace)!r}); '
        'os.chdir(p.parent); os.chdir(p.name); '
        '[(f.open("rb").read(1)) for f in (p/"inputs").rglob("*") if f.is_file()]; '
        't=tempfile.TemporaryDirectory(prefix=".nexent-probe-",dir=p/"outputs"); '
        'f=Path(t.name)/"nested"/"file.txt"; f.parent.mkdir(); '
        'f.write_text("probe",encoding="utf-8"); '
        'assert f.read_text(encoding="utf-8")=="probe"; t.cleanup()'
    )
    result = container.exec_run(['python', '-c', code])
    if result.exit_code != 0:
        raise RuntimeError(f'Sandbox workspace access failed: {result.output!r}')


def cleanup_run_workspace(
    workspace_path: str | None,
    workspace_run_id: str | None,
    logger_: logging.Logger | None = None,
) -> bool:
    """Delete one exact run workspace and its empty user directory."""
    if not workspace_path or not workspace_run_id:
        return False

    cleanup_logger = logger_ or logger
    workspace = Path(workspace_path).resolve()
    if workspace.name != workspace_run_id:
        cleanup_logger.error(
            "Refusing to clean workspace whose final component does not match run id: %s",
            workspace,
        )
        return False

    try:
        removed = workspace.exists()
        if removed:
            shutil.rmtree(workspace)
        try:
            workspace.parent.rmdir()
        except OSError:
            pass
        return removed
    except Exception as exc:
        cleanup_logger.error("Failed to clean run workspace %s: %s", workspace, exc)
        return False

_WORKSPACE_UPLOAD_EXCLUDED_DIRS = {
    ".skill_snapshot",
    ".cache",
    ".npm",
    ".parcel-cache",
    ".pnpm-store",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
}


class WorkspaceResources:
    """Own workspace and executor cleanup for one run."""

    def _check_sandbox_cancelled(self) -> None:
        """Stop initialization and retries after the owning run is cancelled."""
        if self.stop_event.is_set() is True:
            raise CancelledError("Sandbox initialization cancelled")


    def _record_workspace_upload(self, upload: Dict[str, Any]) -> None:
        """Collect one upload result for the frontend artifact event."""
        object_name = str(upload.get("object_name") or "")
        if object_name and any(item.get("object_name") == object_name for item in self._workspace_uploads):
            return
        self._workspace_uploads.append(upload)


    def _prepare_file_workspace(self, query: str) -> str:
        """Create the run workspace and download current-request attachments."""
        if not self.workspace_path:
            return query

        workspace = Path(self.workspace_path)
        (workspace / "inputs").mkdir(parents=True, exist_ok=True)
        (workspace / "outputs").mkdir(parents=True, exist_ok=True)
        download_tool = (getattr(self.agent, "tools", {}) or {}).get("download_from_s3")
        downloaded: List[Dict[str, str]] = []
        if self.minio_files and download_tool is None:
            raise RuntimeError("Uploaded files are present but download_from_s3 is unavailable")

        for index, item in enumerate(self.minio_files):
            if not isinstance(item, dict):
                continue
            object_name = str(item.get("object_name") or "").strip().lstrip("/")
            source_url = str(item.get("url") or "").strip()
            if object_name:
                bucket = getattr(getattr(download_tool, "minio_client", None), "default_bucket", None) or "nexent"
                source_url = f"s3://{bucket}/{object_name}"
            if not source_url:
                continue
            filename = os.path.basename(str(item.get("name") or object_name or f"file_{index}"))
            local_filename = f"inputs/{index:03d}_{filename}"
            result = json.loads(download_tool.forward(source_url, local_filename))
            downloaded.append({"name": filename, "path": result["local_path"]})

        language = getattr(self.observer, "lang", "en")
        mapping = getattr(self, "workspace_mapping", None)
        display_workspace = mapping.container_root if mapping is not None else workspace
        workspace_note = render_user_context(language, "workspace_note", {
            "workspace": display_workspace,
        })
        self._push_file_workspace_to_sandbox()
        self._initialize_sandbox_workspaces()
        return query + workspace_note


    def _sandbox_container(self) -> Any:
        """Return the active Docker container when the executor exposes one."""
        containers = self._sandbox_containers()
        return containers[0] if containers else None


    def _sandbox_containers(self) -> List[Any]:
        """Return every distinct Docker container used by this agent tree."""
        executors = list(self._sandbox_executors)
        root_executor = getattr(self.agent, "python_executor", None)
        if root_executor is not None and all(
            executor is not root_executor for executor in executors
        ):
            executors.append(root_executor)

        containers: List[Any] = []
        seen_keys = set()
        for executor in executors:
            container = getattr(executor, "container", None)
            if container is None:
                continue
            container_id = getattr(container, "id", None)
            key = container_id if isinstance(container_id, str) and container_id else id(container)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            containers.append(container)
        return containers


    def _uses_shared_file_workspace(self) -> bool:
        """Return whether the runtime and sandbox use the same workspace volume."""
        if getattr(self, "workspace_mapping", None) is not None:
            return True
        extra_kwargs = getattr(self.sandbox_config, "extra_kwargs", {}) or {}
        return bool(
            extra_kwargs.get("shared_workspace")
            and extra_kwargs.get("workspace_volume_name")
        )


    def _push_file_workspace_to_sandbox(self, containers: Optional[List[Any]] = None) -> None:
        """Copy the prepared host workspace into every Docker sandbox."""
        if containers is None:
            containers = self._sandbox_containers()
        if not containers or not self.workspace_path:
            return
        workspace = Path(self.workspace_path).resolve()
        mapping = getattr(self, "workspace_mapping", None)
        if mapping is not None:
            self._verify_bind_workspace_access(containers, workspace, mapping)
            return
        if not workspace.exists() or workspace.drive:
            return
        shared_workspace = self._uses_shared_file_workspace()
        archive_bytes = None
        if not shared_workspace:
            archive = io.BytesIO()
            with tarfile.open(fileobj=archive, mode="w") as tar:
                tar.add(workspace, arcname=str(workspace).lstrip("/"), recursive=True)
            archive_bytes = archive.getvalue()

        for container in containers:
            if archive_bytes is not None and not container.put_archive("/", archive_bytes):
                raise RuntimeError("Failed to copy run workspace into the sandbox")
            self._grant_sandbox_output_access(container, workspace)


    def _verify_bind_workspace_access(self, containers, workspace: Path, mapping: SandboxWorkspace) -> None:
        """Probe the mounted run directory without copying or changing Windows ACLs."""
        for container in containers:
            try:
                if not workspace.drive:
                    self._grant_sandbox_output_access(container, mapping.container_root)
                probe_workspace(container, mapping.container_root)
            except Exception:
                logger.exception(
                    "Sandbox FAILED phase=workspace_access run_id=%s container_id=%s",
                    self.workspace_run_id, getattr(container, "id", None),
                )
                raise


    def _initialize_sandbox_workspaces(self, executors: Optional[List[Any]] = None) -> None:
        """Set every Docker kernel's cwd and workspace environment for this run."""
        if not self.workspace_path:
            return
        workspace = Path(self.workspace_path).resolve()
        mapping = getattr(self, "workspace_mapping", None)
        if mapping is not None:
            workspace = mapping.container_root
        output_dir = workspace / "outputs"
        bootstrap_code = (
            "import os as _nexent_os\n"
            f"_nexent_workspace = {json.dumps(str(workspace))}\n"
            f"_nexent_output_dir = {json.dumps(str(output_dir))}\n"
            "_nexent_os.environ['NEXENT_WORKSPACE'] = _nexent_workspace\n"
            "_nexent_os.environ['NEXENT_OUTPUT_DIR'] = _nexent_output_dir\n"
            "_nexent_os.chdir(_nexent_output_dir)\n"
            "[_nexent_workspace, _nexent_output_dir]"
        )
        seen_executor_ids = set()
        for executor in self._sandbox_executors if executors is None else executors:
            self._check_sandbox_cancelled()
            executor_id = id(executor)
            if executor_id in seen_executor_ids:
                continue
            seen_executor_ids.add(executor_id)
            backend = getattr(executor, "_nexent_backend", None)
            if backend == "local":
                continue
            if backend != "docker" and getattr(executor, "container", None) is None:
                continue
            register_bootstrap = None
            if (
                getattr(executor, "_nexent_kernel_recovery_supported", False)
                is True
                and callable(
                    getattr(type(executor), "register_kernel_bootstrap_code", None)
                )
            ):
                register_bootstrap = executor.register_kernel_bootstrap_code
            execute_bootstrap = (
                register_bootstrap if callable(register_bootstrap) else executor
            )
            try:
                execute_bootstrap(bootstrap_code)
                self._check_sandbox_cancelled()
                logger.info(
                    "Sandbox READY run_id=%s actual_backend=docker scope=%s container_id=%s kernel_id=%s "
                    "host_workspace=%s container_workspace=%s",
                    self.workspace_run_id, getattr(getattr(self.sandbox_config, "scope", None), "value", None),
                    getattr(getattr(executor, "container", None), "id", None),
                    getattr(executor, "kernel_id", None), self.workspace_path, workspace,
                )
            except CancelledError:
                raise
            except Exception as exc:
                self._check_sandbox_cancelled()
                # Workspace initialization is idempotent. If the kernel channel
                # failed and marked this lease unhealthy, retry the bootstrap in
                # the same run so the lease can replace its kernel immediately.
                # Do not apply this retry to arbitrary generated code because a
                # lost terminal message does not prove that code had no effects.
                if (
                    getattr(executor, "_nexent_kernel_recovery_supported", False)
                    and getattr(executor, "_unhealthy", False)
                    # Registered bootstraps already own their bounded recovery.
                    and not callable(register_bootstrap)
                ):
                    logger.warning(
                        "Retrying sandbox workspace initialization with a replacement kernel: %s",
                        exc,
                        exc_info=True,
                    )
                    try:
                        execute_bootstrap(bootstrap_code)
                        self._check_sandbox_cancelled()
                        continue
                    except CancelledError:
                        raise
                    except Exception as retry_exc:
                        self._check_sandbox_cancelled()
                        exc = retry_exc
                logger.exception(
                    "Sandbox FAILED phase=workspace run_id=%s: %s", self.workspace_run_id, exc,
                    exc_info=(type(exc), exc, exc.__traceback__),
                )
                raise RuntimeError(
                    f"Failed to initialize sandbox workspace '{workspace}': {exc}"
                ) from exc


    @staticmethod
    def _grant_sandbox_output_access(container: Any, workspace: Path) -> None:
        """Allow sandbox traversal of the user directory and writes in the run workspace."""
        gid_result = container.exec_run(["id", "-g"])
        gid_exit_code = getattr(gid_result, "exit_code", None)
        gid_output = getattr(gid_result, "output", b"")
        if gid_exit_code != 0:
            raise RuntimeError("Failed to determine the sandbox user's group")

        if isinstance(gid_output, bytes):
            gid_output = gid_output.decode("utf-8", errors="replace")
        sandbox_gid = str(gid_output).strip()
        if not sandbox_gid.isdigit():
            raise RuntimeError("Sandbox user returned an invalid group ID")

        workspace_dir = str(workspace)
        workspace_parent_dir = str(workspace.parent)
        commands = (
            ["chgrp", sandbox_gid, workspace_parent_dir],
            ["chmod", "g+xs", workspace_parent_dir],
            ["chgrp", "-R", sandbox_gid, workspace_dir],
            ["chmod", "-R", "g+rwX", workspace_dir],
            ["find", workspace_dir, "-type", "d", "-exec", "chmod", "g+s", "{}", "+"],
        )
        for command in commands:
            result = container.exec_run(command, user="0")
            if getattr(result, "exit_code", None) != 0:
                output = getattr(result, "output", b"")
                if isinstance(output, bytes):
                    output = output.decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"Failed to grant sandbox output access: {str(output).strip()}"
                )


    def _pull_file_workspace_from_sandbox(self) -> None:
        """Copy outputs from every Docker sandbox back to the host workspace."""
        containers = self._sandbox_containers()
        if not containers or not self.workspace_path:
            return
        if self._uses_shared_file_workspace():
            return
        workspace = Path(self.workspace_path).resolve()
        if workspace.drive:
            return
        for container in containers:
            try:
                chunks, _ = container.get_archive(str(workspace))
                archive = io.BytesIO(b"".join(chunks))
                with tarfile.open(fileobj=archive, mode="r:*") as tar:
                    members = []
                    extraction_root = workspace.parent.resolve()
                    for member in tar.getmembers():
                        if not (member.isfile() or member.isdir()):
                            raise RuntimeError("Sandbox workspace archive contains an unsupported entry")
                        target = (extraction_root / member.name).resolve()
                        try:
                            target.relative_to(extraction_root)
                        except ValueError as exc:
                            raise RuntimeError("Sandbox workspace archive escapes the run root") from exc
                        members.append(member)
                    tar.extractall(extraction_root, members=members)
            except Exception as exc:
                logger.warning("Failed to copy sandbox workspace back to host: %s", exc)


    def _finalize_file_workspace(self) -> None:
        """Upload all workspace outputs that were not already uploaded explicitly."""
        if not self.workspace_path:
            return
        self._pull_file_workspace_from_sandbox()
        workspace = Path(self.workspace_path)
        upload_tool = (getattr(self.agent, "tools", {}) or {}).get("upload_to_s3")
        if upload_tool is None:
            logger.error("Run workspace exists but upload_to_s3 is unavailable")
            return

        uploaded_paths = getattr(upload_tool, "uploaded_paths", set())
        for path in workspace.rglob("*") if workspace.exists() else ():
            if not path.is_file():
                continue
            relative = path.relative_to(workspace)
            if relative.parts and relative.parts[0] in {"inputs", "skills"}:
                continue
            if any(part in _WORKSPACE_UPLOAD_EXCLUDED_DIRS for part in relative.parts[:-1]):
                continue
            normalized = os.path.normcase(os.path.abspath(str(path)))
            if normalized in uploaded_paths:
                continue
            try:
                upload_tool.forward(str(path), relative.as_posix())
            except Exception as exc:
                logger.error("Failed to upload workspace output %s: %s", path, exc)
                self.observer.add_message(
                    "",
                    ProcessType.WARNING,
                    f"Failed to upload output file {relative}: {exc}",
                )

        if self._workspace_uploads:
            self.observer.add_message(
                "",
                ProcessType.FILE_ARTIFACT,
                {"artifacts": list(self._workspace_uploads)},
            )


    def _cleanup_file_workspace(self) -> None:
        """Delete only the exact run-scoped workspace after upload finalization."""
        if not self.workspace_path or not self.workspace_run_id:
            return
        workspace = Path(self.workspace_path).resolve()
        if workspace.name != self.workspace_run_id:
            return
        try:
            containers = [] if getattr(self, "workspace_mapping", None) is not None else self._sandbox_containers()
            for container in containers:
                try:
                    result = container.exec_run(
                        ["rm", "-rf", "--", str(workspace)],
                        user="0",
                    )
                    if getattr(result, "exit_code", None) != 0:
                        output = getattr(result, "output", b"")
                        if isinstance(output, bytes):
                            output = output.decode("utf-8", errors="replace")
                        logger.warning(
                            "Failed to clean sandbox run workspace %s: %s",
                            workspace,
                            str(output).strip(),
                        )
                except Exception as exc:
                    logger.warning("Failed to clean sandbox run workspace %s: %s", workspace, exc)
            cleanup_run_workspace(
                self.workspace_path,
                self.workspace_run_id,
                logger,
            )
        except Exception as exc:
            logger.error("Failed to clean run workspace %s: %s", workspace, exc)


    def _release_deferred_executor(self, executor: Any) -> None:
        """Release a deferred executor through its original lifecycle owner."""
        self._sandbox_executors[:] = [item for item in self._sandbox_executors if item is not executor]
        if getattr(self, "_sandbox_scope", None) == "system":
            from nexent.core.agents.sandbox.execution import release_python_executor

            release_python_executor(executor, logger)
        else:
            from nexent.core.agents.sandbox.execution import cleanup_executor

            cleanup_executor(executor, logger, timeout=5.0)


    def _cleanup_sandbox(self) -> None:
        """
        Clean up the sandbox executor after an agent run.

        For ``scope=session``: the executor is immediately destroyed.
        For ``scope=system``: the executor is returned to the warm pool for reuse.

        Must run AFTER any output-sync logic, because the container filesystem
        is inaccessible after the executor is released / destroyed.
        """

        DeferredToolExecutor = deferred_executor_type()
        wrappers = list(self._tool_fastpath_executors)
        root_executor = getattr(self.agent, "python_executor", None)
        executors = list(self._sandbox_executors)
        if root_executor is not None and not isinstance(root_executor, DeferredToolExecutor) and all(
            item is not root_executor for item in executors
        ):
            executors.append(root_executor)
        if not executors and not wrappers:
            return

        scope = getattr(self, "_sandbox_scope", None)

        skill_owner = getattr(self, "_sandbox_skill_cleanup_owner", self)
        if skill_owner is self:
            for runner in self._sandbox_skill_runners:
                runner.cleanup()
        else:
            # Shared skills remain available until the root drains every child.
            with skill_owner._subagent_invocations_lock:
                skill_owner._sandbox_skill_runners.extend(self._sandbox_skill_runners)
        self._sandbox_skill_runners.clear()

        # Sync outputs to MinIO before destroying the container.
        if (
            executors
            and not self.workspace_path
            and self.sandbox_config is not None
            and self.sandbox_config.auto_sync_outputs
            and self.minio_client is not None
        ):
            from nexent.core.agents.sandbox.execution import _sync_outputs_to_minio
            agent_run_id = getattr(self.agent, "agent_run_id", None) or "unknown"
            try:
                uploaded = _sync_outputs_to_minio(
                    output_dir=self.sandbox_config.output_dir,
                    agent_run_id=agent_run_id,
                    minio_client=self.minio_client,
                    bucket="nexent-artifacts",
                    logger_=logger,
                )
                if uploaded:
                    logger.info(
                        "Synced %d output file(s) to MinIO for run %s",
                        len(uploaded),
                        agent_run_id,
                    )
            except Exception as exc:
                logger.error("Output sync to MinIO failed: %s", exc)

        # Release or destroy the executor.
        wrapped_executor_ids = {id(wrapper.remote) for wrapper in wrappers if wrapper.remote is not None}
        seen_executor_ids = set()
        for executor in reversed(executors):
            executor_id = id(executor)
            if executor_id in seen_executor_ids or executor_id in wrapped_executor_ids:
                continue
            seen_executor_ids.add(executor_id)
            if scope == "system":
                # Return every kernel lease to the shared system sandbox.
                from nexent.core.agents.sandbox.execution import release_python_executor
                release_python_executor(executor, logger)
            else:
                # Session kernel leases are released independently; their
                # agent-tree container is deleted after the final lease closes.
                from nexent.core.agents.sandbox.execution import cleanup_executor
                cleanup_executor(executor, logger, timeout=5.0)

        for wrapper in reversed(wrappers):
            wrapper.cleanup()
        self._tool_fastpath_executors.clear()

        # Clear the reference so GC can collect the wrapper objects.
        if self.agent is not None:
            self.agent.python_executor = None
        self._sandbox_executors.clear()
