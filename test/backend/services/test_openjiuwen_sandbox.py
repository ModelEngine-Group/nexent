"""Tests for the fixed shared OpenJiuwen sandbox integration."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

backend_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../backend")
)
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from adapters.openjiuwen_compat import OpenJiuwenSandboxAPI  # noqa: E402
from services.agent_runtime.config import OpenJiuwenSandboxSettings  # noqa: E402
from services.agent_runtime.openjiuwen_sandbox import (  # noqa: E402
    OpenJiuwenDevSandboxService,
    OpenJiuwenSandboxExecutionError,
    OpenJiuwenSandboxUnavailableError,
    OpenJiuwenSandboxValidationError,
    SandboxSkillScriptExecutor,
)
from services.agent_runtime.models import RunControl  # noqa: E402
from nexent.skills.script_executor import SkillScriptExecutionRequest  # noqa: E402


def _result(data: Any = None, *, code: int = 0):
    return SimpleNamespace(code=code, message="ok" if code == 0 else "failed", data=data)


class _Config:
    def __init__(self, **kwargs: Any):
        for key, value in kwargs.items():
            setattr(self, key, value)


class _ResourceResult:
    def __init__(self, ok: bool = True):
        self.ok = ok

    def is_ok(self) -> bool:
        return self.ok


class _FakeFS:
    def __init__(self, container_root: Path):
        self.container_root = container_root

    def host_path(self, sandbox_path: str) -> Path:
        return self.container_root / sandbox_path.lstrip("/")

    async def write_file(self, path: str, content: str, **kwargs: Any):
        _ = kwargs
        host_path = self.host_path(path)
        host_path.parent.mkdir(parents=True, exist_ok=True)
        host_path.write_text(content, encoding="utf-8")
        return _result(SimpleNamespace(path=path, size=len(content)))

    async def upload_file(self, local_path: str, target_path: str, **kwargs: Any):
        _ = kwargs
        host_path = self.host_path(target_path)
        host_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_path, host_path)
        return _result(SimpleNamespace(target_path=target_path, size=host_path.stat().st_size))

    async def list_files(self, path: str, *, recursive: bool = False, **kwargs: Any):
        _ = kwargs
        root = self.host_path(path)
        iterator = root.rglob("*") if recursive else root.glob("*")
        items = []
        if root.exists():
            for item in iterator:
                if item.is_file():
                    relative = item.relative_to(root)
                    items.append(
                        SimpleNamespace(
                            name=item.name,
                            path=str(Path(path) / relative).replace(os.sep, "/"),
                            size=item.stat().st_size,
                            is_directory=False,
                        )
                    )
        return _result(SimpleNamespace(list_items=items))

    async def download_file(self, source_path: str, local_path: str, **kwargs: Any):
        _ = kwargs
        source = self.host_path(source_path)
        target = Path(local_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return _result(SimpleNamespace(local_path=local_path, size=target.stat().st_size))


class _FakeShell:
    def __init__(self, fs: _FakeFS):
        self.fs = fs
        self.execution_commands: list[dict[str, Any]] = []
        self.active_count = 0
        self.max_active_count = 0

    async def execute_cmd(
        self,
        command: str,
        *,
        cwd: str | None = None,
        timeout: int | None = None,
        environment: dict[str, str] | None = None,
        **kwargs: Any,
    ):
        _ = (timeout, kwargs)
        parts = shlex.split(command)
        if parts[:2] == ["mkdir", "-p"]:
            for path in parts[2:]:
                self.fs.host_path(path).mkdir(parents=True, exist_ok=True)
            return _result(SimpleNamespace(stdout="", stderr="", exit_code=0))
        if parts[:2] == ["rm", "-rf"]:
            shutil.rmtree(self.fs.host_path(parts[2]), ignore_errors=True)
            return _result(SimpleNamespace(stdout="", stderr="", exit_code=0))
        if parts and parts[0] == "pkill":
            self.execution_commands.append({"command": command, "termination": True})
            return _result(SimpleNamespace(stdout="", stderr="", exit_code=0))

        record = {
            "command": command,
            "cwd": cwd,
            "timeout": timeout,
            "environment": dict(environment or {}),
        }
        self.execution_commands.append(record)
        self.active_count += 1
        self.max_active_count = max(self.max_active_count, self.active_count)
        try:
            await asyncio.sleep(0.02)
            output_dir = (environment or {}).get("NEXENT_OUTPUT_DIR")
            if output_dir:
                artifact = self.fs.host_path(output_dir) / "report.txt"
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_text("artifact", encoding="utf-8")
            return _result(
                SimpleNamespace(stdout="script output", stderr="", exit_code=0)
            )
        finally:
            self.active_count -= 1


class _BlockingShell(_FakeShell):
    def __init__(self, fs: _FakeFS):
        super().__init__(fs)
        self.all_started = asyncio.Event()
        self.release_by_marker: dict[str, asyncio.Event] = {}
        self.running_markers: set[str] = set()

    async def execute_cmd(
        self,
        command: str,
        *,
        cwd: str | None = None,
        timeout: int | None = None,
        environment: dict[str, str] | None = None,
        **kwargs: Any,
    ):
        parts = shlex.split(command)
        if parts and parts[0] in {"mkdir", "rm"}:
            return await super().execute_cmd(
                command,
                cwd=cwd,
                timeout=timeout,
                environment=environment,
                **kwargs,
            )
        if parts and parts[0] == "pkill":
            self.execution_commands.append({"command": command, "termination": True})
            marker = (
                parts[-1]
                .removeprefix("^")
                .split("(", 1)[0]
                .replace("\\", "")
            )
            release = self.release_by_marker.get(marker)
            if release is not None:
                release.set()
            return _result(SimpleNamespace(stdout="", stderr="", exit_code=0))

        marker = parts[2]
        release = self.release_by_marker.setdefault(marker, asyncio.Event())
        self.running_markers.add(marker)
        self.execution_commands.append(
            {
                "command": command,
                "cwd": cwd,
                "timeout": timeout,
                "environment": dict(environment or {}),
            }
        )
        self.active_count += 1
        self.max_active_count = max(self.max_active_count, self.active_count)
        if len(self.running_markers) >= 2:
            self.all_started.set()
        try:
            await release.wait()
            output_dir = (environment or {}).get("NEXENT_OUTPUT_DIR")
            if output_dir:
                artifact = self.fs.host_path(output_dir) / "report.txt"
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_text("artifact", encoding="utf-8")
            return _result(
                SimpleNamespace(stdout="script output", stderr="", exit_code=0)
            )
        finally:
            self.running_markers.discard(marker)
            self.active_count -= 1


class _FakeSysOperation:
    def __init__(self, container_root: Path):
        self._fs = _FakeFS(container_root)
        self._shell = _FakeShell(self._fs)

    def fs(self):
        return self._fs

    def shell(self):
        return self._shell


class _ResourceManager:
    def __init__(self, container_root: Path):
        self.container_root = container_root
        self.cards: dict[str, Any] = {}
        self.operations: dict[str, _FakeSysOperation] = {}
        self.removed: list[str] = []
        self.add_ok = True

    def add_sys_operation(self, card: Any):
        if not self.add_ok:
            return _ResourceResult(False)
        self.cards[card.id] = card
        self.operations[card.id] = _FakeSysOperation(self.container_root)
        return _ResourceResult()

    def get_sys_operation(self, sys_operation_id: str):
        return self.operations.get(sys_operation_id)

    def remove_sys_operation(self, sys_operation_id: str):
        self.removed.append(sys_operation_id)
        self.operations.pop(sys_operation_id, None)
        return _ResourceResult()


def _sandbox_api(container_root: Path) -> tuple[OpenJiuwenSandboxAPI, _ResourceManager]:
    resource_mgr = _ResourceManager(container_root)
    runner = SimpleNamespace(resource_mgr=resource_mgr)
    return (
        OpenJiuwenSandboxAPI(
            SysOperationCard=_Config,
            OperationMode=SimpleNamespace(SANDBOX="sandbox"),
            SandboxGatewayConfig=_Config,
            SandboxIsolationConfig=_Config,
            PreDeployLauncherConfig=_Config,
            ContainerScope=SimpleNamespace(SYSTEM="system"),
            SandboxRegistry=object(),
            Runner=runner,
        ),
        resource_mgr,
    )


def _settings() -> OpenJiuwenSandboxSettings:
    return OpenJiuwenSandboxSettings(
        enabled=True,
        base_url="http://sandbox.internal:8080",
        provider="aio",
        execution_timeout_seconds=60,
        request_timeout_seconds=10,
        workspace_root="/workspace/nexent",
    )


@pytest.mark.asyncio
async def test_disabled_service_does_not_load_sdk_or_contact_endpoint():
    settings = OpenJiuwenSandboxSettings(
        enabled=False,
        base_url="",
        provider="aio",
        execution_timeout_seconds=60,
        request_timeout_seconds=10,
        workspace_root="/workspace/nexent",
    )

    def fail_if_loaded():
        raise AssertionError("sandbox SDK should not be loaded")

    service = OpenJiuwenDevSandboxService(settings, api=fail_if_loaded)

    service.validate_installation()
    await service.start()

    assert service.healthy is False


@pytest.mark.asyncio
async def test_service_registers_system_predeploy_and_removes_only_local_resource(tmp_path):
    api, resource_mgr = _sandbox_api(tmp_path / "container")
    service = OpenJiuwenDevSandboxService(_settings(), api=api)

    await service.start()

    assert service.healthy is True
    card = resource_mgr.cards[service.SYS_OPERATION_ID]
    assert card.mode == "sandbox"
    assert card.gateway_config.isolation.container_scope == "system"
    assert card.gateway_config.launcher_config.base_url == "http://sandbox.internal:8080"
    assert card.gateway_config.launcher_config.on_stop == "keep"

    await service.stop()

    assert service.SYS_OPERATION_ID in resource_mgr.removed
    assert service.healthy is False


@pytest.mark.asyncio
async def test_health_check_rejects_nonzero_shell_exit_code(tmp_path):
    api, _ = _sandbox_api(tmp_path / "container")
    service = OpenJiuwenDevSandboxService(_settings(), api=api)
    await service.start()
    shell = service.sys_operation.shell()
    original_execute_cmd = shell.execute_cmd

    async def fail_probe_mkdir(command: str, **kwargs: Any):
        parts = shlex.split(command)
        if parts[:2] == ["mkdir", "-p"]:
            return _result(
                SimpleNamespace(
                    stdout="",
                    stderr="permission denied",
                    exit_code=1,
                )
            )
        return await original_execute_cmd(command, **kwargs)

    shell.execute_cmd = fail_probe_mkdir

    with pytest.raises(OpenJiuwenSandboxExecutionError) as exc_info:
        await service.health_check()

    assert exc_info.value.stage == "health_mkdir"
    assert service.healthy is False


@pytest.mark.asyncio
async def test_two_process_scoped_services_can_start_against_same_container(tmp_path):
    shared_container = tmp_path / "container"
    first_api, _ = _sandbox_api(shared_container)
    second_api, _ = _sandbox_api(shared_container)
    first = OpenJiuwenDevSandboxService(_settings(), api=first_api)
    second = OpenJiuwenDevSandboxService(_settings(), api=second_api)

    await asyncio.gather(first.start(), second.start())

    assert first.healthy is True
    assert second.healthy is True
    assert not any(
        name in vars(first)
        for name in ("request_id", "workspace_root", "process_marker", "artifacts")
    )
    probe_root = shared_container / "workspace" / "nexent" / ".probe"
    assert not probe_root.exists() or not list(probe_root.iterdir())


@pytest.mark.asyncio
async def test_service_registration_failure_is_fail_closed(tmp_path):
    api, resource_mgr = _sandbox_api(tmp_path / "container")
    resource_mgr.add_ok = False
    service = OpenJiuwenDevSandboxService(_settings(), api=api)

    with pytest.raises(OpenJiuwenSandboxUnavailableError, match="registration failed"):
        await service.start()

    assert service.healthy is False


@pytest.mark.asyncio
async def test_executor_stages_authorized_files_maps_params_and_downloads_artifact(tmp_path):
    api, _ = _sandbox_api(tmp_path / "container")
    service = OpenJiuwenDevSandboxService(_settings(), api=api)
    await service.start()
    skill_root = tmp_path / "skills" / "csv-data-analyzer"
    script = skill_root / "scripts" / "analyze.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('ok')", encoding="utf-8")
    (skill_root / "SKILL.md").write_text("# Skill", encoding="utf-8")
    attachment = tmp_path / "input.csv"
    attachment.write_text("a,b\n1,2\n", encoding="utf-8")
    staging_dirs: list[str] = []
    executor = SandboxSkillScriptExecutor(
        service=service,
        request_id="request-1",
        tenant_id="tenant-1",
        run_control=RunControl(request_id="request-1", user_id="user-1"),
        attachments={str(attachment): "uploaded.csv"},
        host_staging_dirs=staging_dirs,
        host_staging_root=str(tmp_path / "host-staging"),
        execution_timeout_seconds=7,
    )

    result = await executor.execute(
        SkillScriptExecutionRequest(
            skill_name="csv-data-analyzer",
            skill_root=str(skill_root),
            script_path=str(script),
            params=(
                f'--input {shlex.quote(str(attachment))} '
                '--label "a;b|$(touch /tmp/not-executed)"'
            ),
            timeout_seconds=30,
        )
    )

    shell = service.sys_operation.shell()
    execution = next(
        item for item in shell.execution_commands if not item.get("termination")
    )
    assert str(attachment) not in execution["command"]
    assert execution["timeout"] == 7
    assert "/workspace/nexent/" in execution["command"]
    assert "uploaded.csv" in execution["command"]
    command_args = shlex.split(execution["command"])
    assert "a;b|$(touch /tmp/not-executed)" in command_args
    assert "touch" not in command_args
    payload = next(
        json.loads(line)
        for line in result.splitlines()
        if line.startswith("{")
    )
    assert Path(payload["absolute_path"]).read_text(encoding="utf-8") == "artifact"
    assert staging_dirs == [str(Path(payload["absolute_path"]).parents[1])]
    workspace_root = execution["environment"]["NEXENT_OUTPUT_DIR"].rsplit("/", 1)[0]
    assert not service.sys_operation.fs().host_path(workspace_root).exists()


@pytest.mark.asyncio
async def test_executor_rejects_unknown_absolute_path_before_command(tmp_path):
    api, _ = _sandbox_api(tmp_path / "container")
    service = OpenJiuwenDevSandboxService(_settings(), api=api)
    await service.start()
    skill_root = tmp_path / "skills" / "demo"
    script = skill_root / "run.py"
    skill_root.mkdir(parents=True)
    script.write_text("print('ok')", encoding="utf-8")
    executor = SandboxSkillScriptExecutor(
        service=service,
        request_id="request-1",
        tenant_id="tenant-1",
    )

    with pytest.raises(
        OpenJiuwenSandboxValidationError,
        match="unauthorized absolute path",
    ):
        await executor.execute(
            SkillScriptExecutionRequest(
                skill_name="demo",
                skill_root=str(skill_root),
                script_path=str(script),
                params="--input /etc/passwd",
            )
        )

    assert service.sys_operation.shell().execution_commands == []


@pytest.mark.asyncio
async def test_two_executors_run_concurrently_without_global_lock(tmp_path):
    api, _ = _sandbox_api(tmp_path / "container")
    service = OpenJiuwenDevSandboxService(_settings(), api=api)
    await service.start()
    skill_root = tmp_path / "skills" / "demo"
    script = skill_root / "run.py"
    skill_root.mkdir(parents=True)
    script.write_text("print('ok')", encoding="utf-8")
    request = SkillScriptExecutionRequest(
        skill_name="demo",
        skill_root=str(skill_root),
        script_path=str(script),
    )
    first = SandboxSkillScriptExecutor(
        service=service,
        request_id="request-1",
        tenant_id="tenant-1",
        host_staging_root=str(tmp_path / "host-staging"),
    )
    second = SandboxSkillScriptExecutor(
        service=service,
        request_id="request-2",
        tenant_id="tenant-2",
        host_staging_root=str(tmp_path / "host-staging"),
    )

    await asyncio.gather(first.execute(request), second.execute(request))

    shell = service.sys_operation.shell()
    assert shell.max_active_count == 2
    output_dirs = {
        item["environment"]["NEXENT_OUTPUT_DIR"]
        for item in shell.execution_commands
        if not item.get("termination")
    }
    assert len(output_dirs) == 2


@pytest.mark.asyncio
async def test_executor_rejects_symlink_skill_root_and_special_files(tmp_path):
    api, _ = _sandbox_api(tmp_path / "container")
    service = OpenJiuwenDevSandboxService(_settings(), api=api)
    await service.start()
    real_skill_root = tmp_path / "skills" / "demo-real"
    real_skill_root.mkdir(parents=True)
    script = real_skill_root / "run.py"
    script.write_text("print('ok')", encoding="utf-8")
    linked_skill_root = tmp_path / "skills" / "demo-link"
    linked_skill_root.symlink_to(real_skill_root, target_is_directory=True)
    executor = SandboxSkillScriptExecutor(
        service=service,
        request_id="request-symlink",
        tenant_id="tenant-1",
    )

    with pytest.raises(OpenJiuwenSandboxValidationError, match="symbolic-link root"):
        await executor.execute(
            SkillScriptExecutionRequest(
                skill_name="demo-link",
                skill_root=str(linked_skill_root),
                script_path=str(linked_skill_root / "run.py"),
            )
        )

    fifo_skill_root = tmp_path / "skills" / "demo-fifo"
    fifo_skill_root.mkdir()
    fifo_script = fifo_skill_root / "run.py"
    fifo_script.write_text("print('ok')", encoding="utf-8")
    os.mkfifo(fifo_skill_root / "named-pipe")

    with pytest.raises(OpenJiuwenSandboxValidationError, match="regular files only"):
        await executor.execute(
            SkillScriptExecutionRequest(
                skill_name="demo-fifo",
                skill_root=str(fifo_skill_root),
                script_path=str(fifo_script),
            )
        )

    assert service.sys_operation.shell().execution_commands == []


@pytest.mark.asyncio
async def test_executor_cleans_partial_host_staging_when_actual_output_exceeds_limit(
    tmp_path,
):
    api, _ = _sandbox_api(tmp_path / "container")
    service = OpenJiuwenDevSandboxService(_settings(), api=api)
    await service.start()
    fs = service.sys_operation.fs()
    original_list_files = fs.list_files

    async def underreported_list_files(*args: Any, **kwargs: Any):
        result = await original_list_files(*args, **kwargs)
        for item in result.data.list_items:
            item.size = 1
        return result

    fs.list_files = underreported_list_files
    skill_root = tmp_path / "skills" / "demo"
    skill_root.mkdir(parents=True)
    script = skill_root / "run.py"
    script.write_text("print('ok')", encoding="utf-8")
    staging_dirs: list[str] = []
    staging_root = tmp_path / "host-staging"
    executor = SandboxSkillScriptExecutor(
        service=service,
        request_id="request-output-limit",
        tenant_id="tenant-1",
        host_staging_dirs=staging_dirs,
        host_staging_root=str(staging_root),
        max_output_total_bytes=4,
    )

    with pytest.raises(OpenJiuwenSandboxExecutionError) as exc_info:
        await executor.execute(
            SkillScriptExecutionRequest(
                skill_name="demo",
                skill_root=str(skill_root),
                script_path=str(script),
            )
        )

    assert exc_info.value.stage == "artifact"
    assert staging_dirs == []
    assert not staging_root.exists() or not list(staging_root.iterdir())


@pytest.mark.asyncio
async def test_executor_preserves_nonzero_stdout_stderr_result_shape(tmp_path):
    api, _ = _sandbox_api(tmp_path / "container")
    service = OpenJiuwenDevSandboxService(_settings(), api=api)
    await service.start()
    shell = service.sys_operation.shell()
    original_execute_cmd = shell.execute_cmd

    async def nonzero_execute_cmd(command: str, **kwargs: Any):
        if shlex.split(command)[0] == "exec":
            return _result(
                SimpleNamespace(
                    stdout="partial output",
                    stderr="script failed",
                    exit_code=2,
                )
            )
        return await original_execute_cmd(command, **kwargs)

    shell.execute_cmd = nonzero_execute_cmd
    skill_root = tmp_path / "skills" / "demo"
    skill_root.mkdir(parents=True)
    script = skill_root / "run.py"
    script.write_text("raise SystemExit(2)", encoding="utf-8")
    executor = SandboxSkillScriptExecutor(
        service=service,
        request_id="request-nonzero",
        tenant_id="tenant-1",
    )

    result = await executor.execute(
        SkillScriptExecutionRequest(
            skill_name="demo",
            skill_root=str(skill_root),
            script_path=str(script),
        )
    )

    assert json.loads(result) == {
        "error": "script failed",
        "output": "partial output",
    }


@pytest.mark.asyncio
async def test_executor_rejects_output_file_count_limit_and_cleans_staging(tmp_path):
    api, _ = _sandbox_api(tmp_path / "container")
    service = OpenJiuwenDevSandboxService(_settings(), api=api)
    await service.start()
    shell = service.sys_operation.shell()
    original_execute_cmd = shell.execute_cmd

    async def create_two_outputs(command: str, **kwargs: Any):
        result = await original_execute_cmd(command, **kwargs)
        if shlex.split(command)[0] == "exec":
            output_root = service.sys_operation.fs().host_path(
                kwargs["environment"]["NEXENT_OUTPUT_DIR"]
            )
            (output_root / "second.txt").write_text("second", encoding="utf-8")
        return result

    shell.execute_cmd = create_two_outputs
    skill_root = tmp_path / "skills" / "demo"
    skill_root.mkdir(parents=True)
    script = skill_root / "run.py"
    script.write_text("print('ok')", encoding="utf-8")
    staging_dirs: list[str] = []
    staging_root = tmp_path / "host-staging"
    executor = SandboxSkillScriptExecutor(
        service=service,
        request_id="request-output-count",
        tenant_id="tenant-1",
        host_staging_dirs=staging_dirs,
        host_staging_root=str(staging_root),
        max_output_files=1,
    )

    with pytest.raises(OpenJiuwenSandboxExecutionError) as exc_info:
        await executor.execute(
            SkillScriptExecutionRequest(
                skill_name="demo",
                skill_root=str(skill_root),
                script_path=str(script),
            )
        )

    assert exc_info.value.stage == "artifact"
    assert staging_dirs == []
    assert not staging_root.exists() or not list(staging_root.iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "expected_stage"),
    [
        ("execution timeout after 1 seconds", "timeout"),
        ("out of memory", "resource"),
    ],
)
async def test_executor_maps_timeout_and_resource_failures(
    tmp_path,
    message,
    expected_stage,
):
    api, _ = _sandbox_api(tmp_path / "container")
    service = OpenJiuwenDevSandboxService(_settings(), api=api)
    await service.start()
    shell = service.sys_operation.shell()
    original_execute_cmd = shell.execute_cmd

    async def failing_execute_cmd(command: str, **kwargs: Any):
        if shlex.split(command)[0] == "exec":
            return SimpleNamespace(code=1, message=message, data=None)
        return await original_execute_cmd(command, **kwargs)

    shell.execute_cmd = failing_execute_cmd
    skill_root = tmp_path / "skills" / "demo"
    skill_root.mkdir(parents=True)
    script = skill_root / "run.py"
    script.write_text("print('ok')", encoding="utf-8")
    diagnostics: list[dict[str, str]] = []
    executor = SandboxSkillScriptExecutor(
        service=service,
        request_id=f"request-{expected_stage}",
        tenant_id="tenant-1",
        diagnostics=diagnostics,
    )

    with pytest.raises(OpenJiuwenSandboxExecutionError) as exc_info:
        await executor.execute(
            SkillScriptExecutionRequest(
                skill_name="demo",
                skill_root=str(skill_root),
                script_path=str(script),
            )
        )

    assert exc_info.value.stage == expected_stage
    assert diagnostics == [
        {"sandbox_stage": expected_stage, "status": "error"}
    ]


@pytest.mark.asyncio
async def test_cancelling_one_executor_does_not_stop_another_request(tmp_path):
    api, _ = _sandbox_api(tmp_path / "container")
    service = OpenJiuwenDevSandboxService(_settings(), api=api)
    await service.start()
    blocking_shell = _BlockingShell(service.sys_operation.fs())
    service.sys_operation._shell = blocking_shell
    skill_root = tmp_path / "skills" / "demo"
    skill_root.mkdir(parents=True)
    script = skill_root / "run.py"
    script.write_text("print('ok')", encoding="utf-8")
    request = SkillScriptExecutionRequest(
        skill_name="demo",
        skill_root=str(skill_root),
        script_path=str(script),
    )
    first = SandboxSkillScriptExecutor(
        service=service,
        request_id="request-1",
        tenant_id="tenant-1",
        host_staging_root=str(tmp_path / "host-staging"),
    )
    second = SandboxSkillScriptExecutor(
        service=service,
        request_id="request-2",
        tenant_id="tenant-2",
        host_staging_root=str(tmp_path / "host-staging"),
    )
    first_task = asyncio.create_task(first.execute(request))
    second_task = asyncio.create_task(second.execute(request))
    await asyncio.wait_for(blocking_shell.all_started.wait(), timeout=2)
    first_marker = next(iter(first._active_executions.values()))["process_marker"]
    second_marker = next(iter(second._active_executions.values()))["process_marker"]

    await first.cancel()

    with pytest.raises(asyncio.CancelledError):
        await first_task
    assert second_task.done() is False
    termination_commands = [
        item["command"]
        for item in blocking_shell.execution_commands
        if item.get("termination")
    ]
    for marker, release in blocking_shell.release_by_marker.items():
        if marker != first_marker:
            release.set()
    await asyncio.wait_for(second_task, timeout=2)
    assert termination_commands
    termination_patterns = [
        shlex.split(command)[-1].replace("\\", "")
        for command in termination_commands
    ]
    assert any(first_marker in pattern for pattern in termination_patterns)
    assert all(second_marker not in pattern for pattern in termination_patterns)


@pytest.mark.asyncio
async def test_executor_precleans_only_its_deterministic_stale_workspace(
    tmp_path,
    monkeypatch,
):
    api, _ = _sandbox_api(tmp_path / "container")
    service = OpenJiuwenDevSandboxService(_settings(), api=api)
    await service.start()
    execution_id = "a" * 32
    monkeypatch.setattr(
        "services.agent_runtime.openjiuwen_sandbox.uuid.uuid4",
        lambda: SimpleNamespace(hex=execution_id),
    )
    request_hash = __import__("hashlib").sha256(
        f"tenant-1:request-stale:{execution_id}".encode("utf-8")
    ).hexdigest()[:24]
    fs = service.sys_operation.fs()
    stale_root = fs.host_path(f"/workspace/nexent/{request_hash}")
    stale_root.mkdir(parents=True)
    (stale_root / "stale.txt").write_text("stale", encoding="utf-8")
    other_root = fs.host_path("/workspace/nexent/other-request")
    other_root.mkdir(parents=True)
    (other_root / "keep.txt").write_text("keep", encoding="utf-8")
    skill_root = tmp_path / "skills" / "demo"
    skill_root.mkdir(parents=True)
    script = skill_root / "run.py"
    script.write_text("print('ok')", encoding="utf-8")
    executor = SandboxSkillScriptExecutor(
        service=service,
        request_id="request-stale",
        tenant_id="tenant-1",
        host_staging_root=str(tmp_path / "host-staging"),
    )

    await executor.execute(
        SkillScriptExecutionRequest(
            skill_name="demo",
            skill_root=str(skill_root),
            script_path=str(script),
        )
    )

    assert not stale_root.exists()
    assert (other_root / "keep.txt").read_text(encoding="utf-8") == "keep"


@pytest.mark.asyncio
async def test_workspace_cleanup_failure_records_safe_diagnostic(tmp_path):
    api, _ = _sandbox_api(tmp_path / "container")
    service = OpenJiuwenDevSandboxService(_settings(), api=api)
    await service.start()
    shell = service.sys_operation.shell()
    original_execute_cmd = shell.execute_cmd
    execution_completed = False

    async def fail_final_cleanup(command: str, **kwargs: Any):
        nonlocal execution_completed
        parts = shlex.split(command)
        if parts and parts[0] == "exec":
            result = await original_execute_cmd(command, **kwargs)
            execution_completed = True
            return result
        if execution_completed and parts[:2] == ["rm", "-rf"]:
            return SimpleNamespace(code=1, message="cleanup failed", data=None)
        return await original_execute_cmd(command, **kwargs)

    shell.execute_cmd = fail_final_cleanup
    skill_root = tmp_path / "skills" / "demo"
    skill_root.mkdir(parents=True)
    script = skill_root / "run.py"
    script.write_text("print('ok')", encoding="utf-8")
    diagnostics: list[dict[str, str]] = []
    executor = SandboxSkillScriptExecutor(
        service=service,
        request_id="request-cleanup",
        tenant_id="tenant-1",
        diagnostics=diagnostics,
        host_staging_root=str(tmp_path / "host-staging"),
    )

    await executor.execute(
        SkillScriptExecutionRequest(
            skill_name="demo",
            skill_root=str(skill_root),
            script_path=str(script),
        )
    )

    assert diagnostics == [{"sandbox_stage": "cleanup", "status": "warning"}]
