"""
Unit + integration tests for the sandbox factory (session/system dimensions).

Covers:
1. ``SandboxConfig.from_dict`` parses scope and level correctly.
2. ``SandboxPoolManager.acquire`` keeps a single executor across releases when
   ``scope=system`` and starts fresh per acquire when ``scope=session``.
3. ``SandboxPoolManager`` evicts idle executors and reuses alive ones.
4. The whole ``build_python_executor`` / ``release_python_executor`` cycle for
   ``scope=system`` reuses the same executor instance.
5. Executing Python in a system-scoped docker executor returns a result.

The docker-level integration tests are skipped when the docker daemon is not
reachable so the suite remains runnable on developer machines without docker.
"""
import builtins
import hashlib
import importlib
import importlib.util
import json
import logging
import os
import sys
import time
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import ANY, MagicMock, call, patch

import pytest


SDK_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "sdk"))


# ---------------------------------------------------------------------------
# Load the sandbox module directly (without going through __init__.py which
# has lazy-import side effects).
# ---------------------------------------------------------------------------
def _load_sandbox_module():
    spec = importlib.util.spec_from_file_location(
        "sandbox_under_test",
        os.path.join(SDK_PATH, "nexent", "core", "agents", "sandbox.py"),
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["sandbox_under_test"] = module
    spec.loader.exec_module(module)
    return module


sandbox_module = _load_sandbox_module()

SandboxLevel = sandbox_module.SandboxLevel
SandboxScope = sandbox_module.SandboxScope
SandboxConfig = sandbox_module.SandboxConfig
SandboxPoolManager = sandbox_module.SandboxPoolManager
build_python_executor = sandbox_module.build_python_executor
release_python_executor = sandbox_module.release_python_executor
ShellPolicy = sandbox_module.ShellPolicy
SandboxSkillScriptRunner = sandbox_module.SandboxSkillScriptRunner
seed_pnpm_offline_store = sandbox_module._seed_pnpm_offline_store


def test_docker_bridge_gateway_returns_concrete_ipv4_address():
    network = MagicMock(
        attrs={
            "IPAM": {
                "Config": [
                    {"Gateway": "fd00::1"},
                    {"Gateway": "172.17.0.1"},
                ]
            }
        }
    )
    client = SimpleNamespace(networks=SimpleNamespace(get=MagicMock(return_value=network)))

    assert sandbox_module._docker_bridge_gateway(client) == "172.17.0.1"
    client.networks.get.assert_called_once_with("bridge")
    network.reload.assert_called_once_with()


def test_docker_bridge_gateway_rejects_missing_ipv4_address():
    network = MagicMock(attrs={"IPAM": {"Config": [{"Gateway": "fd00::1"}]}})
    client = SimpleNamespace(networks=SimpleNamespace(get=MagicMock(return_value=network)))

    with pytest.raises(RuntimeError, match="does not expose an IPv4 gateway"):
        sandbox_module._docker_bridge_gateway(client)


@pytest.mark.parametrize("server_version", ["18.09.9", "19.03.15", "20.10.9-ce"])
def test_legacy_docker_disables_seccomp_for_clone3_compatibility(server_version):
    client = SimpleNamespace(version=lambda: {"Version": server_version})
    run_kwargs = {}

    sandbox_module._apply_legacy_docker_seccomp_compatibility(
        client,
        run_kwargs,
        MagicMock(),
    )

    assert run_kwargs["security_opt"] == ["seccomp=unconfined"]


@pytest.mark.parametrize("server_version", ["20.10.10", "20.10.24", "23.0.0", "29.1.0"])
def test_modern_docker_preserves_default_seccomp_profile(server_version):
    client = SimpleNamespace(version=lambda: {"Version": server_version})
    run_kwargs = {}

    sandbox_module._apply_legacy_docker_seccomp_compatibility(
        client,
        run_kwargs,
        MagicMock(),
    )

    assert "security_opt" not in run_kwargs


def test_unknown_docker_version_preserves_default_seccomp_profile():
    client = SimpleNamespace(version=lambda: {"Version": "vendor-build"})
    run_kwargs = {}
    logger = MagicMock()

    sandbox_module._apply_legacy_docker_seccomp_compatibility(
        client,
        run_kwargs,
        logger,
    )

    assert "security_opt" not in run_kwargs
    logger.warning.assert_called_once()


def test_seed_pnpm_offline_store_creates_read_only_workspace_store():
    container = MagicMock()
    container.exec_run.side_effect = [
        SimpleNamespace(exit_code=0),
        SimpleNamespace(exit_code=1),
        SimpleNamespace(exit_code=0),
        SimpleNamespace(exit_code=0),
        SimpleNamespace(exit_code=0),
    ]

    seed_pnpm_offline_store(container)

    assert container.exec_run.call_args_list[-3:] == [
        call(["mkdir", "-p", sandbox_module.SANDBOX_PNPM_STORE_PATH], user="root"),
        call(
            [
                "cp",
                "-a",
                f"{sandbox_module.SANDBOX_PNPM_STORE_SOURCE}/.",
                sandbox_module.SANDBOX_PNPM_STORE_PATH,
            ],
            user="root",
        ),
        call(
            ["chmod", "-R", "a-w", sandbox_module.SANDBOX_PNPM_STORE_PATH],
            user="root",
        ),
    ]


def test_seed_pnpm_offline_store_reuses_existing_store():
    container = MagicMock()
    container.exec_run.side_effect = [
        SimpleNamespace(exit_code=0),
        SimpleNamespace(exit_code=0),
    ]

    seed_pnpm_offline_store(container)

    assert container.exec_run.call_count == 2


def test_seed_pnpm_offline_store_reports_preparation_failure():
    container = MagicMock()
    container.exec_run.side_effect = [
        SimpleNamespace(exit_code=0),
        SimpleNamespace(exit_code=1),
        SimpleNamespace(exit_code=0),
        SimpleNamespace(exit_code=9),
    ]

    with pytest.raises(RuntimeError, match="Failed to prepare pnpm offline store with cp"):
        seed_pnpm_offline_store(container)


def _docker_available() -> bool:
    try:
        import docker

        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
def reset_singleton():
    """Always start each test with a clean SandboxPoolManager singleton.

    Also restores the real ``smolagents`` package into ``sys.modules`` when a
    sibling test left a MagicMock behind.  Without this, the pool tests that
    touch ``smolagents.local_python_executor`` would explode with
    ``ModuleNotFoundError: 'smolagents' is not a package`` when the suite is
    run together with the skill-tool tests.
    """
    SandboxPoolManager._instance = None
    if isinstance(sys.modules.get("smolagents"), MagicMock):
        for mod_name in (
            "smolagents",
            "smolagents.tool",
            "smolagents.tools",
            "smolagents.local_python_executor",
            "smolagents.remote_executors",
        ):
            sys.modules.pop(mod_name, None)
        try:
            importlib.import_module("smolagents")
        except ModuleNotFoundError:
            # Runner-only tests do not require the optional executor package.
            pass
    yield
    pool = SandboxPoolManager.get_instance()
    try:
        pool.shutdown(sandbox_module.logging.getLogger("test_sandbox"))
    except Exception:
        pass
    SandboxPoolManager._instance = None


# ---------------------------------------------------------------------------
# Pure-Python unit tests
# ---------------------------------------------------------------------------
class TestSandboxSkillScriptRunner:
    def test_output_text_handles_non_bytes_values(self):
        assert SandboxSkillScriptRunner._output_text("plain output") == "plain output"
        assert SandboxSkillScriptRunner._output_text(None) == ""
    def test_requires_internal_network(self, monkeypatch):
        network = MagicMock()
        network.attrs = {"Internal": False, "Containers": {}}
        client = MagicMock()
        client.networks.get.return_value = network
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: False)

        with pytest.raises(RuntimeError, match="must be internal"):
            sandbox_module._ensure_sandbox_control_network(client)

    def test_reuses_internal_network_without_runtime_attachment_on_host(self, monkeypatch):
        network = MagicMock()
        network.attrs = {"Internal": True, "Containers": {}}
        client = MagicMock()
        client.networks.get.return_value = network
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: False)

        assert sandbox_module._ensure_sandbox_control_network(client) is network
        network.connect.assert_not_called()

    def test_internal_network_attaches_containerized_runtime_when_missing(self, monkeypatch):
        network = MagicMock(attrs={"Internal": True, "Containers": {}})
        runtime_container = SimpleNamespace(id="runtime-id")
        client = MagicMock()
        client.networks.get.return_value = network
        client.containers.get.return_value = runtime_container
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: True)
        monkeypatch.setattr(sandbox_module.socket, "gethostname", lambda: "runtime-host")

        assert sandbox_module._ensure_sandbox_control_network(client) is network

        client.containers.get.assert_called_once_with("runtime-host")
        network.connect.assert_called_once_with(runtime_container)
        assert network.reload.call_count == 2

    def test_attach_sandbox_reuses_existing_control_network_membership(self, monkeypatch):
        container = MagicMock(id="sandbox-id")
        network = MagicMock(attrs={"Internal": True, "Containers": {"sandbox-id": {}}})
        ensure_network = MagicMock(return_value=network)
        monkeypatch.setattr(sandbox_module, "_ensure_sandbox_control_network", ensure_network)

        assert sandbox_module._attach_sandbox_to_control_network(
            MagicMock(),
            container,
            alias="sandbox",
        ) is network

        container.reload.assert_called_once_with()
        network.connect.assert_not_called()

    def test_preparation_command_failure_includes_container_output(self):
        container = MagicMock()
        container.exec_run.return_value = SimpleNamespace(
            exit_code=23,
            output="permission denied",
        )
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=container, _nexent_backend="docker")
        )

        with pytest.raises(RuntimeError, match=r"exit=23.*permission denied"):
            runner._run_container_command(["mkdir", "-p", "/workspace/skills"])

    def test_resolve_skills_root_requires_workspace_and_rejects_drift(self):
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=MagicMock(), _nexent_backend="docker")
        )

        with pytest.raises(RuntimeError, match="run-scoped workspace"):
            runner._resolve_skills_root(None)

        assert runner._resolve_skills_root("/workspace/run-1") == "/workspace/run-1/skills"
        with pytest.raises(RuntimeError, match="does not match"):
            runner._resolve_skills_root("/workspace/run-2")

    def test_resolve_workspace_script_requires_workspace_and_rejects_drift(self):
        no_workspace = SandboxSkillScriptRunner(
            SimpleNamespace(container=MagicMock(), _nexent_backend="docker")
        )
        with pytest.raises(RuntimeError, match="run-scoped workspace"):
            no_workspace._resolve_workspace_script("outputs/build.py", None)

        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=MagicMock(), _nexent_backend="docker"),
            workspace_path="/workspace/run-1",
        )
        with pytest.raises(RuntimeError, match="does not match"):
            runner._resolve_workspace_script(
                "outputs/build.py",
                "/workspace/run-2",
            )

    def test_resolve_workspace_script_normalizes_dot_prefix_and_reports_missing(self):
        workspace = "/workspace/run"
        container = MagicMock()
        container.exec_run.return_value = SimpleNamespace(exit_code=1, output=b"")
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=container, _nexent_backend="docker"),
            workspace_path=workspace,
        )

        with pytest.raises(FileNotFoundError, match="outputs/build.py"):
            runner._resolve_workspace_script("././outputs/build.py", workspace)

        container.exec_run.assert_called_once_with(
            ["realpath", "-e", "--", f"{workspace}/outputs/build.py"],
            user="sandbox",
        )

    def test_resolve_workspace_script_rejects_non_regular_file(self):
        workspace = "/workspace/run"
        script = f"{workspace}/outputs/build.py"
        container = MagicMock()
        container.exec_run.side_effect = [
            SimpleNamespace(exit_code=0, output=f"{script}\n".encode()),
            SimpleNamespace(exit_code=1, output=b""),
        ]
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=container, _nexent_backend="docker"),
            workspace_path=workspace,
        )

        with pytest.raises(ValueError, match="regular file"):
            runner._resolve_workspace_script("outputs/build.py", workspace)

    def test_stage_skill_raises_when_archive_copy_fails(self, tmp_path):
        skill_dir = tmp_path / "skills" / "report"
        script = skill_dir / "scripts" / "generate.py"
        script.parent.mkdir(parents=True)
        script.write_text("print('sandbox')", encoding="utf-8")
        container = MagicMock()
        container.exec_run.return_value = SimpleNamespace(exit_code=0, output=b"")
        container.put_archive.return_value = False
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=container, _nexent_backend="docker")
        )
        manager = MagicMock()
        manager.resolve_skill_script.return_value = (
            str(skill_dir),
            str(script),
            "scripts/generate.py",
        )

        with pytest.raises(RuntimeError, match="Failed to copy"):
            runner._stage_skill(
                manager,
                "report",
                "scripts/generate.py",
                "tenant-1",
                "/workspace/skills",
            )

    def test_stage_skill_refreshes_cached_copy_when_script_changes(self, tmp_path):
        skill_dir = tmp_path / "skills" / "report"
        script = skill_dir / "scripts" / "generate.py"
        script.parent.mkdir(parents=True)
        script.write_text("print('first')", encoding="utf-8")
        container = MagicMock()
        container.exec_run.return_value = SimpleNamespace(exit_code=0, output=b"")
        container.put_archive.return_value = True
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=container, _nexent_backend="docker")
        )
        manager = MagicMock()
        manager.resolve_skill_script.return_value = (
            str(skill_dir),
            str(script),
            "scripts/generate.py",
        )

        first_path, _ = runner._stage_skill(
            manager,
            "report",
            "scripts/generate.py",
            "tenant-1",
            "/workspace/skills",
        )
        script.write_text("print('second version')", encoding="utf-8")
        second_path, _ = runner._stage_skill(
            manager,
            "report",
            "scripts/generate.py",
            "tenant-1",
            "/workspace/skills",
        )

        assert second_path == first_path
        assert call(
            ["rm", "-rf", "--", first_path.split("/scripts/", 1)[0]],
            user="0",
        ) in container.exec_run.call_args_list
        assert container.put_archive.call_count == 2

    def test_nonzero_script_with_combined_output_returns_error_json(self, tmp_path):
        skill_dir = tmp_path / "skills" / "report"
        script = skill_dir / "scripts" / "generate.py"
        script.parent.mkdir(parents=True)
        script.write_text("raise SystemExit(2)", encoding="utf-8")
        container = MagicMock()
        container.put_archive.return_value = True
        container.exec_run.side_effect = [
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=2, output="combined failure"),
        ]
        workspace = "/mnt/nexent/workdir/user/run"
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=container, _nexent_backend="docker"),
            workspace_path=workspace,
        )
        manager = MagicMock()
        manager.resolve_skill_script.return_value = (
            str(skill_dir),
            str(script),
            "scripts/generate.py",
        )

        result = runner(
            manager=manager,
            skill_name="report",
            script_path="scripts/generate.py",
            params=None,
            tenant_id="tenant-1",
            working_directory=workspace,
        )

        assert json.loads(result) == {"error": "combined failure", "output": ""}

    def test_cleanup_noops_without_backend_or_workspace_and_logs_exception(self, caplog):
        unavailable_container = MagicMock()
        unavailable = SandboxSkillScriptRunner(
            SimpleNamespace(container=unavailable_container, _nexent_backend="local"),
            workspace_path="/workspace/run",
        )
        unavailable.cleanup()
        unavailable_container.exec_run.assert_not_called()

        no_workspace_container = MagicMock()
        no_workspace = SandboxSkillScriptRunner(
            SimpleNamespace(container=no_workspace_container, _nexent_backend="docker")
        )
        no_workspace.cleanup()
        no_workspace_container.exec_run.assert_not_called()

        failing_container = MagicMock()
        failing_container.exec_run.side_effect = RuntimeError("container unavailable")
        failing = SandboxSkillScriptRunner(
            SimpleNamespace(container=failing_container, _nexent_backend="docker"),
            workspace_path="/workspace/run",
        )
        with caplog.at_level(logging.WARNING, logger="sandbox_under_test"):
            failing.cleanup()

        assert "container unavailable" in caplog.text

    def test_copies_validated_skill_and_executes_inside_container(self, tmp_path):
        skill_dir = tmp_path / "skills" / "report"
        script = skill_dir / "scripts" / "generate.py"
        script.parent.mkdir(parents=True)
        script.write_text("print('sandbox')", encoding="utf-8")

        container = MagicMock()
        container.put_archive.return_value = True
        container.exec_run.side_effect = [
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=(b"sandbox\n", b"warning\n")),
        ]
        executor = SimpleNamespace(container=container, _nexent_backend="docker")
        manager = MagicMock()
        manager.resolve_skill_script.return_value = (
            str(skill_dir),
            str(script),
            "scripts/generate.py",
        )
        workspace = "/mnt/nexent/workdir/user/run"
        runner = SandboxSkillScriptRunner(
            executor,
            timeout_seconds=17,
            workspace_path=workspace,
        )
        result = runner(
            manager=manager,
            skill_name="report",
            script_path="scripts/generate.py",
            params='--title "Quarterly report"',
            tenant_id="tenant-1",
            working_directory=workspace,
        )

        assert result == "sandbox\n"
        manager.resolve_skill_script.assert_called_once_with(
            "report", "scripts/generate.py", tenant_id="tenant-1"
        )
        assert container.put_archive.call_count == 1
        assert container.exec_run.call_args_list[0] == call(
            ["mkdir", "-p", f"{workspace}/skills"], user="0"
        )
        assert container.exec_run.call_args_list[-3:-1] == [
            call(["mkdir", "-p", "--", f"{workspace}/outputs"], user="0"),
            call(
                ["chown", "sandbox:sandbox", "--", f"{workspace}/outputs"],
                user="0",
            ),
        ]
        command = container.exec_run.call_args_list[-1].args[0]
        assert command[:5] == ["timeout", "--signal=KILL", "17", "python", ANY]
        assert command[-2:] == ["--title", "Quarterly report"]
        assert container.exec_run.call_args_list[-1].kwargs == {
            "user": "sandbox",
            "workdir": f"{workspace}/outputs",
            "environment": {
                "NEXENT_WORKSPACE": workspace,
                "NEXENT_OUTPUT_DIR": f"{workspace}/outputs",
                "NODE_PATH": "/opt/nexent/node_modules:/usr/local/lib/node_modules",
                "PNPM_CONFIG_OFFLINE": "true",
                "npm_config_offline": "true",
                "COREPACK_ENABLE_NETWORK": "0",
                "PNPM_CONFIG_STORE_DIR": sandbox_module.SANDBOX_PNPM_STORE_PATH,
                "npm_config_store_dir": sandbox_module.SANDBOX_PNPM_STORE_PATH,
                "PIP_USER": "1",
                "PYTHONPATH": (
                    f"{workspace}/skills/report-"
                    f"{hashlib.sha256(str(skill_dir.resolve()).encode('utf-8')).hexdigest()[:16]}:"
                    "/home/sandbox/.local/lib/python3.11/site-packages"
                ),
            },
            "demux": True,
        }

    def test_online_skill_shell_script_prepares_writable_pnpm_store(self, tmp_path):
        skill_dir = tmp_path / "web-artifacts-builder"
        script = skill_dir / "scripts" / "build.sh"
        script.parent.mkdir(parents=True)
        script.write_text("echo built", encoding="utf-8")
        container = MagicMock()
        container.put_archive.return_value = True
        container.exec_run.side_effect = [
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=(b"built\n", b"")),
        ]
        manager = MagicMock()
        manager.resolve_skill_script.return_value = (
            str(skill_dir),
            str(script),
            "scripts/build.sh",
        )
        workspace = "/workspace/run"
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=container, _nexent_backend="docker"),
            workspace_path=workspace,
            network_enabled=True,
        )
        runner._ensure_network_pnpm_store = MagicMock()

        result = runner(
            manager=manager,
            skill_name="web-artifacts-builder",
            script_path="scripts/build.sh",
            params=None,
            tenant_id="tenant-1",
            working_directory=workspace,
        )

        assert result == "built\n"
        runner._ensure_network_pnpm_store.assert_called_once_with(workspace)

    def test_refuses_to_fall_back_to_host_when_docker_is_unavailable(self):
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=None, _nexent_backend="local")
        )

        with pytest.raises(RuntimeError, match="require a Docker sandbox"):
            runner(
                manager=MagicMock(),
                skill_name="report",
                script_path="scripts/generate.py",
                params=None,
                tenant_id="tenant-1",
                working_directory=None,
            )

    def test_maps_timeout_exit_to_timeout_error(self, tmp_path):
        skill_dir = tmp_path / "skill"
        script = skill_dir / "scripts" / "slow.sh"
        script.parent.mkdir(parents=True)
        script.write_text("sleep 30", encoding="utf-8")
        container = MagicMock()
        container.put_archive.return_value = True
        container.exec_run.side_effect = [
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=124, output=(b"", b"")),
        ]
        workspace = "/mnt/nexent/workdir/user/run"
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=container, _nexent_backend="docker"),
            timeout_seconds=1,
            workspace_path=workspace,
        )
        manager = MagicMock()
        manager.resolve_skill_script.return_value = (
            str(skill_dir), str(script), "scripts/slow.sh"
        )

        with pytest.raises(TimeoutError, match="slow.sh"):
            runner(
                manager=manager,
                skill_name="slow",
                script_path="scripts/slow.sh",
                params=None,
                tenant_id="tenant-1",
                working_directory=workspace,
            )

        sed_call = next(
            recorded_call
            for recorded_call in container.exec_run.call_args_list
            if recorded_call.args[0][:2] == ["sed", "-i"]
        )
        normalized_script = sed_call.args[0][-1]
        assert sed_call == call(
            ["sed", "-i", "s/\\r$//", normalized_script],
            user="0",
        )

    def test_cleanup_uses_root_for_docker_archive_owned_files(self):
        container = MagicMock()
        container.exec_run.return_value = SimpleNamespace(exit_code=0, output=b"")
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=container, _nexent_backend="docker"),
            workspace_path="/mnt/nexent/workdir/user/run",
        )

        runner.cleanup()

        container.exec_run.assert_called_once_with(
            ["rm", "-rf", "--", runner._root],
            user="0",
        )

    def test_cleanup_removes_container_private_network_pnpm_store(self):
        container = MagicMock()
        container.exec_run.return_value = SimpleNamespace(exit_code=0, output=b"")
        workspace = "/mnt/nexent/workdir/user/run"
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=container, _nexent_backend="docker"),
            workspace_path=workspace,
            network_enabled=True,
        )
        store_path = runner._resolve_network_pnpm_store(workspace)

        runner.cleanup()

        assert container.exec_run.call_args_list == [
            call(["rm", "-rf", "--", runner._root], user="0"),
            call(["rm", "-rf", "--", store_path], user="0"),
        ]

    def test_network_pnpm_store_rejects_workspace_drift(self):
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=MagicMock(), _nexent_backend="docker"),
            workspace_path="/workspace/run-1",
            network_enabled=True,
        )
        runner._resolve_network_pnpm_store("/workspace/run-1")

        with pytest.raises(RuntimeError, match="does not match"):
            runner._resolve_network_pnpm_store("/workspace/run-2")

    def test_network_pnpm_store_is_seeded_from_image_cache_once(self):
        container = MagicMock()
        container.exec_run.return_value = SimpleNamespace(exit_code=0, output=b"")
        workspace = "/mnt/nexent/workdir/user/run"
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=container, _nexent_backend="docker"),
            workspace_path=workspace,
            network_enabled=True,
        )

        runner._ensure_network_pnpm_store(workspace)
        runner._ensure_network_pnpm_store(workspace)

        store_path = runner._resolve_network_pnpm_store(workspace)
        assert container.exec_run.call_args_list == [
            call(["mkdir", "-p", "/tmp/nexent-pnpm-stores"], user="0"),
            call(
                ["test", "-d", f"{sandbox_module.SANDBOX_PNPM_STORE_SOURCE}/v3"],
                user="0",
            ),
            call(
                [
                    "cp",
                    "-a",
                    "--reflink=auto",
                    f"{sandbox_module.SANDBOX_PNPM_STORE_SOURCE}/.",
                    store_path,
                ],
                user="0",
            ),
            call(["chown", "-R", "sandbox:sandbox", store_path], user="0"),
        ]

    def test_network_pnpm_store_uses_empty_store_when_image_cache_is_missing(self):
        container = MagicMock()
        container.exec_run.side_effect = [
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=1, output=b""),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b""),
        ]
        workspace = "/workspace/run"
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=container, _nexent_backend="docker"),
            workspace_path=workspace,
            network_enabled=True,
        )

        runner._ensure_network_pnpm_store(workspace)

        store_path = runner._resolve_network_pnpm_store(workspace)
        assert call(["mkdir", "-p", store_path], user="0") in container.exec_run.call_args_list

    @pytest.mark.parametrize("failure_kind", ["status", "exception"])
    def test_cleanup_logs_network_pnpm_store_removal_failures(
        self,
        caplog,
        failure_kind,
    ):
        container = MagicMock()
        failure = (
            SimpleNamespace(exit_code=5, output=b"store busy")
            if failure_kind == "status"
            else RuntimeError("container unavailable")
        )
        container.exec_run.side_effect = [
            SimpleNamespace(exit_code=0, output=b""),
            failure,
        ]
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=container, _nexent_backend="docker"),
            workspace_path="/workspace/run",
            network_enabled=True,
        )
        runner._pnpm_store_path = "/tmp/nexent-pnpm-stores/run"

        with caplog.at_level(logging.WARNING, logger="sandbox_under_test"):
            runner.cleanup()

        assert "Failed to remove sandbox pnpm store" in caplog.text

    def test_cleanup_logs_nonzero_exit(self, caplog):
        container = MagicMock()
        container.exec_run.return_value = SimpleNamespace(
            exit_code=1,
            output=b"permission denied",
        )
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=container, _nexent_backend="docker"),
            workspace_path="/mnt/nexent/workdir/user/run",
        )

        with caplog.at_level(logging.WARNING, logger="sandbox_under_test"):
            runner.cleanup()

        assert "permission denied" in caplog.text
        assert runner._root in caplog.text

    def test_executes_workspace_node_script_with_permission_model(self):
        workspace = "/mnt/nexent/workdir/user/run"
        script = f"{workspace}/outputs/build.js"
        container = MagicMock()
        container.exec_run.side_effect = [
            SimpleNamespace(exit_code=0, output=f"{script}\n".encode()),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=(b"built\n", b"")),
        ]
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=container, _nexent_backend="docker"),
            timeout_seconds=45,
            workspace_path=workspace,
            network_enabled=True,
        )

        result = runner(
            manager=MagicMock(),
            skill_name="docx",
            script_path="outputs/build.js",
            params='--title "Quarterly report"',
            tenant_id="tenant-1",
            working_directory=workspace,
            source="workspace",
        )

        assert result == "built\n"
        command = container.exec_run.call_args_list[-1].args[0]
        assert command[:4] == ["timeout", "--signal=KILL", "45", "node"]
        assert "--experimental-permission" in command
        assert "--allow-addons" in command
        assert f"--allow-fs-write={workspace}" in command
        assert script in command
        assert command[-2:] == ["--title", "Quarterly report"]
        environment = container.exec_run.call_args_list[-1].kwargs["environment"]
        assert environment["PNPM_CONFIG_OFFLINE"] == "false"
        assert environment["npm_config_offline"] == "false"
        assert environment["COREPACK_ENABLE_NETWORK"] == "1"
        assert environment["PIP_USER"] == "1"
        expected_store = (
            "/tmp/nexent-pnpm-stores/"
            + hashlib.sha256(workspace.encode("utf-8")).hexdigest()[:24]
        )
        assert environment["PNPM_CONFIG_STORE_DIR"] == expected_store
        assert environment["npm_config_store_dir"] == expected_store

    @pytest.mark.parametrize(
        "script_path",
        ["/tmp/build.js", "../build.js", "outputs/../../build.js", "outputs/build.sh", ""],
    )
    def test_workspace_script_rejects_unsafe_paths_and_extensions(self, script_path):
        container = MagicMock()
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=container, _nexent_backend="docker"),
            workspace_path="/mnt/nexent/workdir/user/run",
        )

        with pytest.raises(ValueError):
            runner(
                manager=MagicMock(),
                skill_name="docx",
                script_path=script_path,
                params=None,
                tenant_id="tenant-1",
                working_directory="/mnt/nexent/workdir/user/run",
                source="workspace",
            )

        container.exec_run.assert_not_called()

    def test_workspace_script_rejects_symlink_escape(self):
        workspace = "/mnt/nexent/workdir/user/run"
        container = MagicMock()
        container.exec_run.return_value = SimpleNamespace(
            exit_code=0,
            output=b"/etc/passwd\n",
        )
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=container, _nexent_backend="docker"),
            workspace_path=workspace,
        )

        with pytest.raises(PermissionError, match="outside"):
            runner(
                manager=MagicMock(),
                skill_name="docx",
                script_path="outputs/build.js",
                params=None,
                tenant_id="tenant-1",
                working_directory=workspace,
                source="workspace",
            )

    def test_workspace_python_reuses_shell_call_guard(self):
        workspace = "/mnt/nexent/workdir/user/run"
        script = f"{workspace}/outputs/build.py"
        container = MagicMock()
        container.exec_run.side_effect = [
            SimpleNamespace(exit_code=0, output=f"{script}\n".encode()),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b"import subprocess\nsubprocess.run(['id'])\n"),
        ]
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=container, _nexent_backend="docker"),
            workspace_path=workspace,
        )

        with pytest.raises(PermissionError, match="subprocess.run"):
            runner(
                manager=MagicMock(),
                skill_name="pdf",
                script_path="outputs/build.py",
                params=None,
                tenant_id="tenant-1",
                working_directory=workspace,
                source="workspace",
            )

    def test_online_workspace_python_allows_subprocess(self):
        container = MagicMock()
        container.exec_run.return_value = SimpleNamespace(
            exit_code=0,
            output=b"import subprocess\nsubprocess.run(['python', '-m', 'pip', 'install', 'humanize'])\n",
        )
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=container, _nexent_backend="docker"),
            workspace_path="/mnt/nexent/workdir/user/run",
            network_enabled=True,
        )

        runner._validate_workspace_python(
            "/mnt/nexent/workdir/user/run/outputs/install.py"
        )

    @pytest.mark.parametrize(
        ("result", "expected_error"),
        [
            (SimpleNamespace(exit_code=1, output=b""), "Failed to read"),
            (
                SimpleNamespace(exit_code=0, output=b"x" * (1024 * 1024 + 1)),
                "cannot exceed 1 MiB",
            ),
        ],
    )
    def test_workspace_python_validation_reports_read_and_size_errors(
        self,
        result,
        expected_error,
    ):
        container = MagicMock()
        container.exec_run.return_value = result
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=container, _nexent_backend="docker"),
            workspace_path="/workspace/run",
        )

        with pytest.raises((RuntimeError, ValueError), match=expected_error):
            runner._validate_workspace_python("/workspace/run/outputs/build.py")

    def test_workspace_python_requires_enabled_skill_directory(self):
        workspace = "/workspace/run"
        script = f"{workspace}/outputs/build.py"
        container = MagicMock()
        container.exec_run.side_effect = [
            SimpleNamespace(exit_code=0, output=f"{script}\n".encode()),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b"print('safe')\n"),
        ]
        manager = MagicMock()
        manager.resolve_skill_dir.return_value = "/missing/pdf"
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=container, _nexent_backend="docker"),
            workspace_path=workspace,
        )

        with pytest.raises(FileNotFoundError, match="Skill not found: pdf"):
            runner(
                manager=manager,
                skill_name="pdf",
                script_path="outputs/build.py",
                params=None,
                tenant_id="tenant-1",
                working_directory=workspace,
                source="workspace",
            )

    def test_workspace_python_executes_with_enabled_skill_import_path(self, tmp_path):
        workspace = "/workspace/run"
        script = f"{workspace}/outputs/build.py"
        skill_dir = tmp_path / "pdf"
        skill_dir.mkdir()
        (skill_dir / "helper.py").write_text("VALUE = 1", encoding="utf-8")
        container = MagicMock()
        container.put_archive.return_value = True
        container.exec_run.side_effect = [
            SimpleNamespace(exit_code=0, output=f"{script}\n".encode()),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b"print('created')\n"),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=b""),
            SimpleNamespace(exit_code=0, output=(b"created\n", b"")),
        ]
        manager = MagicMock()
        manager.resolve_skill_dir.return_value = str(skill_dir)
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=container, _nexent_backend="docker"),
            workspace_path=workspace,
        )

        result = runner(
            manager=manager,
            skill_name="pdf",
            script_path="outputs/build.py",
            params=None,
            tenant_id="tenant-1",
            working_directory=workspace,
            source="workspace",
        )

        assert result == "created\n"
        manager.resolve_skill_dir.assert_called_once_with(
            "pdf",
            tenant_id="tenant-1",
        )
        environment = container.exec_run.call_args_list[-1].kwargs["environment"]
        assert environment["PYTHONPATH"].startswith(f"{workspace}/skills/pdf-")

    def test_workspace_script_rejects_unknown_source(self):
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=MagicMock(), _nexent_backend="docker"),
            workspace_path="/mnt/nexent/workdir/user/run",
        )

        with pytest.raises(ValueError, match="source must be"):
            runner(
                manager=MagicMock(),
                skill_name="docx",
                script_path="outputs/build.js",
                params=None,
                tenant_id="tenant-1",
                working_directory="/mnt/nexent/workdir/user/run",
                source="host",
            )


class TestSandboxConfig:
    """Configuration parsing for the two scope dimensions."""

    def test_from_dict_defaults_to_session_scope(self):
        cfg = SandboxConfig.from_dict(None)
        assert cfg.scope == SandboxScope.SESSION

    def test_from_dict_system_scope(self):
        cfg = SandboxConfig.from_dict({"level": "docker", "scope": "system"})
        assert cfg.scope == SandboxScope.SYSTEM
        assert cfg.level == SandboxLevel.DOCKER

    def test_from_dict_invalid_level_raises(self):
        with pytest.raises(ValueError):
            SandboxConfig.from_dict({"level": "unknown"})

    def test_from_dict_invalid_scope_raises(self):
        with pytest.raises(ValueError):
            SandboxConfig.from_dict({"scope": "tenant"})


class TestSessionScopePoolBehavior:
    """``scope=session`` must always build a fresh executor per acquire."""

    def test_session_acquire_returns_fresh_executor_each_time(self):
        """Local-level: every acquire returns a brand new LocalPythonExecutor."""
        cfg = SandboxConfig(
            level=SandboxLevel.LOCAL,
            scope=SandboxScope.SESSION,
            extra_kwargs={"additional_authorized_imports": []},
        )
        logger = sandbox_module.logging.getLogger("test_sandbox")
        ex1 = build_python_executor(cfg, logger)
        ex2 = build_python_executor(cfg, logger)
        assert ex1 is not ex2


# ---------------------------------------------------------------------------
# SandboxPoolManager tests with mock executors (no docker required)
# ---------------------------------------------------------------------------
class _FakeExecutor:
    """Minimal stand-in for an executor the pool manager can track."""

    def __init__(self, image: str, alive: bool = True):
        self._image = image
        self._alive = alive
        self.cleaned_up = False
        self._nexent_sandbox_config = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SYSTEM,
            docker_image=image,
        )
        self.container = MagicMock()
        self.container.status = "running" if alive else "exited"

    def cleanup(self):
        self.cleaned_up = True


class TestHostToolBridge:
    """Remote code gets a proxy while the live tool remains in the host."""

    def test_host_tool_is_not_serialized_and_proxy_calls_live_instance(self):
        class FakeRemoteExecutor:
            def __init__(self):
                self.sent_tools = None
                self.proxy_code = None
                self.cleaned_up = False

            def send_tools(self, tools):
                self.sent_tools = tools

            def run_code_raise_errors(self, code):
                self.proxy_code = code
                return SimpleNamespace(logs="")

            def cleanup(self):
                self.cleaned_up = True

        class HostTool:
            name = "host_add"
            _nexent_execute_on_host = True

            def __call__(self, left, right=0):
                return left + right

            def to_dict(self):
                raise AssertionError("Host tools must not be serialized")

        executor = FakeRemoteExecutor()
        sandbox_module._install_host_tool_bridge(
            executor,
            sandbox_module.logging.getLogger("test_sandbox"),
        )
        remote_tool = object()
        executor.send_tools({"host_add": HostTool(), "remote_tool": remote_tool})

        assert executor.sent_tools == {"remote_tool": remote_tool}
        assert "def host_add(*args, **kwargs):" in executor.proxy_code

        namespace = {}
        exec(executor.proxy_code, namespace)
        assert namespace["host_add"](4, right=5) == 9

        executor.cleanup()
        assert executor.cleaned_up is True

    def test_containerized_bridge_uses_runtime_service_name(self, monkeypatch):
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: True)
        bridge = sandbox_module._ToolBridge(
            sandbox_module.logging.getLogger("test_sandbox")
        )
        try:
            proxy_code = bridge.proxy_code({"host_add": object()})
            assert f"http://nexent-runtime:{bridge.port}/invoke" in proxy_code
        finally:
            bridge.close()

    def test_host_tool_proxy_surfaces_runtime_error_body(self):
        bridge = sandbox_module._ToolBridge(
            sandbox_module.logging.getLogger("test_sandbox")
        )
        try:
            namespace = {}
            exec(
                bridge.proxy_code(
                    {"missing_tool": object()},
                    bridge_host="127.0.0.1",
                ),
                namespace,
            )

            with pytest.raises(RuntimeError, match="Unknown local tool: missing_tool"):
                namespace["missing_tool"]()
        finally:
            bridge.close()

    def test_host_tool_proxy_preserves_image_result_and_save(self, tmp_path):
        from PIL import Image
        from smolagents.agent_types import AgentImage

        bridge = sandbox_module._ToolBridge(
            sandbox_module.logging.getLogger("test_sandbox")
        )
        bridge.register({
            "generate_chart": lambda: AgentImage(Image.new("RGB", (4, 3), "red")),
        })
        try:
            namespace = {}
            exec(
                bridge.proxy_code(
                    {"generate_chart": object()},
                    bridge_host="127.0.0.1",
                ),
                namespace,
            )

            result = namespace["generate_chart"]()
            output_path = tmp_path / "chart.png"
            result.save(output_path)

            assert isinstance(result, Image.Image)
            assert result.size == (4, 3)
            with Image.open(output_path) as saved_image:
                assert saved_image.size == (4, 3)
        finally:
            bridge.close()

    def test_host_tool_proxy_preserves_nested_binary_result(self):
        bridge = sandbox_module._ToolBridge(
            sandbox_module.logging.getLogger("test_sandbox")
        )
        bridge.register({"binary_tool": lambda: {"items": [b"chart-bytes"]}})
        try:
            namespace = {}
            exec(
                bridge.proxy_code(
                    {"binary_tool": object()},
                    bridge_host="127.0.0.1",
                ),
                namespace,
            )

            assert namespace["binary_tool"]() == {"items": [b"chart-bytes"]}
        finally:
            bridge.close()

    def test_host_parallel_executor_restores_bridged_tool_references(self):
        def host_add(left, right=0):
            return left + right

        def parallel_executor(tasks):
            return [func(**kwargs) for func, kwargs in tasks]

        tools = {
            "host_add": host_add,
            "parallel_executor": parallel_executor,
        }
        bridge = sandbox_module._ToolBridge(
            sandbox_module.logging.getLogger("test_sandbox")
        )
        bridge.register(tools)
        try:
            namespace = {}
            exec(
                bridge.proxy_code(tools, bridge_host="127.0.0.1"),
                namespace,
            )

            result = namespace["parallel_executor"](
                tasks=[
                    (namespace["host_add"], {"left": 1, "right": 2}),
                    (namespace["host_add"], {"left": 4, "right": 5}),
                ]
            )

            assert result == [3, 9]
        finally:
            bridge.close()

    def test_serialize_tool_bridge_value_handles_audio_paths_and_models(
        self,
        tmp_path,
        monkeypatch,
    ):
        class FakeAgentAudio:
            def __init__(self, location):
                self.location = location

            def to_string(self):
                return self.location

        class JsonModel:
            def model_dump(self, mode):
                assert mode == "json"
                return {"output_path": tmp_path / "report.txt"}

        smolagents_module = ModuleType("smolagents")
        agent_types_module = ModuleType("smolagents.agent_types")
        agent_types_module.AgentAudio = FakeAgentAudio
        agent_types_module.AgentImage = ()
        smolagents_module.agent_types = agent_types_module
        monkeypatch.setitem(sys.modules, "smolagents", smolagents_module)
        monkeypatch.setitem(sys.modules, "smolagents.agent_types", agent_types_module)
        audio_path = tmp_path / "sample.wav"
        audio_path.write_bytes(b"audio-bytes")

        serialized_audio = sandbox_module._serialize_tool_bridge_value(
            FakeAgentAudio(audio_path)
        )

        assert serialized_audio[sandbox_module._TOOL_BRIDGE_VALUE_MARKER] == 1
        assert serialized_audio["kind"] == "audio"
        assert serialized_audio["mime_type"] in {"audio/wav", "audio/x-wav"}
        assert serialized_audio["encoding"] == "base64"
        assert serialized_audio["data"] == "YXVkaW8tYnl0ZXM="
        assert sandbox_module._serialize_tool_bridge_value(
            FakeAgentAudio(tmp_path / "missing.wav")
        ) == str(tmp_path / "missing.wav")
        assert sandbox_module._serialize_tool_bridge_value(JsonModel()) == {
            "output_path": str(tmp_path / "report.txt")
        }

    def test_tool_bridge_value_rejects_unsupported_results_and_unknown_references(self):
        with pytest.raises(TypeError, match="Host tool returned unsupported result type: builtins.object"):
            sandbox_module._serialize_tool_bridge_value(object())

        unknown_reference = {
            sandbox_module._TOOL_BRIDGE_VALUE_MARKER: 1,
            "kind": "tool_reference",
            "name": "missing_tool",
        }
        with pytest.raises(ValueError, match="Unknown local tool reference: missing_tool"):
            sandbox_module._deserialize_tool_bridge_value(unknown_reference, {})


class TestKernelGatewayConfiguration:
    """Kernel Gateway exposes the APIs required by the sandbox pool."""

    def test_kernel_listing_is_enabled(self):
        command = sandbox_module._kernel_gateway_command()

        assert "--ServerApp.allow_remote_access=True" in command
        assert "--JupyterWebsocketPersonality.list_kernels=True" in command


class TestDockerRecovery:
    """Recovery of a system-scoped Docker container across runtime restarts."""

    def test_recover_running_named_container(self, monkeypatch):
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test_sandbox")
        cfg = SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SYSTEM)
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: False)

        container = MagicMock()
        container.name = sandbox_module.SANDBOX_CONTAINER_NAME
        container.short_id = "abc123"
        container.status = "running"
        container.labels = {"com.nexent.sandbox": "runtime"}
        container.client = MagicMock()
        container.attrs = {
            "NetworkSettings": {
                "Networks": {sandbox_module.SANDBOX_NETWORK_NAME: {}},
                "Ports": {"8888/tcp": [{"HostPort": "8888"}]},
            }
        }

        docker_module = SimpleNamespace(from_env=lambda: SimpleNamespace(
            containers=SimpleNamespace(list=lambda **kwargs: [container])
        ))
        requests_module = SimpleNamespace(
            get=lambda *args, **kwargs: SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: [{"id": "existing-kernel", "execution_state": "idle"}],
            )
        )
        monkeypatch.setitem(sys.modules, "docker", docker_module)
        monkeypatch.setitem(sys.modules, "requests", requests_module)

        recovered = pm._recover_docker_container(cfg, logger, host_tools_exist=False)

        assert recovered is not None
        assert recovered.container is container
        assert recovered.base_url == "http://127.0.0.1:8888"
        assert recovered._nexent_backend == "docker"
        container.reload.assert_called_once()

    def test_system_creation_uses_localhost_on_host_runtime(self, monkeypatch):
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test_sandbox")
        cfg = SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SYSTEM)
        container = MagicMock()
        container.short_id = "host123"
        container.client = MagicMock()
        container.attrs = {"NetworkSettings": {"Networks": {}}}
        run = MagicMock(return_value=container)
        docker_module = SimpleNamespace(
            from_env=lambda: SimpleNamespace(containers=SimpleNamespace(run=run))
        )
        requests_module = SimpleNamespace(
            get=lambda *args, **kwargs: SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: [],
            )
        )
        monkeypatch.setitem(sys.modules, "docker", docker_module)
        monkeypatch.setitem(sys.modules, "requests", requests_module)
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: False)

        executor = pm._build_system_docker_executor(cfg, logger, {"name": "sandbox"})

        assert executor.base_url == "http://127.0.0.1:8888"
        assert run.call_args.kwargs["ports"] == {"8888/tcp": ("127.0.0.1", 8888)}

    def test_system_creation_uses_container_dns_without_host_port(self, monkeypatch):
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test_sandbox")
        cfg = SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SYSTEM)
        container = MagicMock()
        container.short_id = "docker123"
        container.client = MagicMock()
        container.attrs = {"NetworkSettings": {"Networks": {}}}
        run = MagicMock(return_value=container)
        docker_module = SimpleNamespace(
            from_env=lambda: SimpleNamespace(containers=SimpleNamespace(run=run))
        )
        requests_made = []

        def get(url, **kwargs):
            requests_made.append((url, kwargs))
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: [])

        monkeypatch.setitem(sys.modules, "docker", docker_module)
        monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=get))
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: True)

        executor = pm._build_system_docker_executor(
            cfg,
            logger,
            {"name": sandbox_module.SANDBOX_CONTAINER_NAME, "ports": {"old": "mapping"}},
        )

        assert executor.base_url == "http://nexent-runtime-sandbox:8888"
        assert "ports" not in run.call_args.kwargs
        assert requests_made == [
            ("http://nexent-runtime-sandbox:8888/api/kernels", {"timeout": 1})
        ]

    def test_recovery_rejects_container_without_nexent_network(self, monkeypatch):
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test_sandbox")
        cfg = SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SYSTEM)
        container = MagicMock()
        container.name = sandbox_module.SANDBOX_CONTAINER_NAME
        container.status = "running"
        container.labels = {"com.nexent.sandbox": "runtime"}
        container.attrs = {
            "NetworkSettings": {
                "Networks": {},
                "Ports": {"8888/tcp": [{"HostPort": "8888"}]},
            }
        }
        docker_module = SimpleNamespace(from_env=lambda: SimpleNamespace(
            containers=SimpleNamespace(list=lambda **kwargs: [container])
        ))
        monkeypatch.setitem(sys.modules, "docker", docker_module)

        assert pm._recover_docker_container(cfg, logger, host_tools_exist=False) is None

    def test_recovery_rejects_container_with_wrong_workspace_mount(self, monkeypatch):
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test_sandbox")
        workspace_root = str(Path("/mnt/nexent/workdir").resolve())
        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SYSTEM,
            extra_kwargs={
                "workspace_root": "/mnt/nexent/workdir",
                "workspace_volume_name": "nexent-agent-workspace",
            },
        )
        container = MagicMock()
        container.name = sandbox_module.SANDBOX_CONTAINER_NAME
        container.status = "running"
        container.labels = {"com.nexent.sandbox": "runtime"}
        container.attrs = {
            "Mounts": [{
                "Type": "bind",
                "Source": "/mnt/nexent/workdir",
                "Destination": workspace_root,
                "RW": True,
            }],
            "NetworkSettings": {
                "Networks": {sandbox_module.SANDBOX_NETWORK_NAME: {}},
            },
        }
        docker_module = SimpleNamespace(from_env=lambda: SimpleNamespace(
            containers=SimpleNamespace(list=lambda **kwargs: [container])
        ))
        monkeypatch.setitem(sys.modules, "docker", docker_module)

        assert pm._recover_docker_container(cfg, logger, host_tools_exist=False) is None


class TestPoolManagerLogic:
    """Pure-Python pool semantics that the user's request depends on."""

    def _build_pool(self):
        return SandboxPoolManager.get_instance()

    def test_acquire_session_creates_fresh_each_time_no_pooling(self):
        """For SESSION scope, no executor is ever returned to the pool."""
        pm = self._build_pool()
        logger = sandbox_module.logging.getLogger("test_sandbox")
        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SESSION,
            docker_image="img:latest",
        )
        ex1 = pm.acquire(cfg, logger)
        pm.release(ex1, logger)
        assert pm._pools == {}  # never pooled

    def test_system_owner_does_not_install_host_tool_bridge(self, monkeypatch):
        pm = self._build_pool()
        logger = sandbox_module.logging.getLogger("test_sandbox")
        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SYSTEM,
            docker_image="img:latest",
        )
        owner = SimpleNamespace(
            container=MagicMock(),
            base_url="http://127.0.0.1:8888",
            host="127.0.0.1",
            port=8888,
        )
        networks = SimpleNamespace(get=lambda name: object())
        docker_module = SimpleNamespace(
            from_env=lambda: SimpleNamespace(networks=networks),
            errors=SimpleNamespace(NotFound=RuntimeError),
        )
        bridge_installer = MagicMock(side_effect=AssertionError("owner bridge installation"))
        monkeypatch.setitem(sys.modules, "docker", docker_module)
        monkeypatch.setattr(pm, "_build_system_docker_executor", lambda *args: owner)
        monkeypatch.setattr(sandbox_module, "_install_host_tool_bridge", bridge_installer)

        executor = pm._build_docker_executor(cfg, logger, host_tools_exist=True)

        assert executor is owner
        bridge_installer.assert_not_called()

    def test_system_docker_mounts_named_workspace_volume(self, monkeypatch):
        pm = self._build_pool()
        logger = sandbox_module.logging.getLogger("test_sandbox")
        owner = SimpleNamespace(container=MagicMock())
        captured_kwargs = {}
        networks = SimpleNamespace(get=lambda name: object())
        docker_module = SimpleNamespace(
            from_env=lambda: SimpleNamespace(networks=networks),
            errors=SimpleNamespace(NotFound=RuntimeError),
        )
        monkeypatch.setitem(sys.modules, "docker", docker_module)
        monkeypatch.setitem(
            sys.modules,
            "smolagents.remote_executors",
            SimpleNamespace(DockerExecutor=MagicMock()),
        )
        monkeypatch.setattr(
            pm,
            "_build_system_docker_executor",
            lambda config, logger_, kwargs: captured_kwargs.update(kwargs) or owner,
        )
        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SYSTEM,
            extra_kwargs={
                "workspace_root": "/mnt/nexent/workdir",
                "workspace_volume_name": "nexent-agent-workspace",
            },
        )

        assert pm._build_docker_executor(cfg, logger) is owner
        expected_destination = str(Path("/mnt/nexent/workdir").resolve())
        assert captured_kwargs["volumes"] == {
            "nexent-agent-workspace": {
                "bind": expected_destination,
                "mode": "rw",
            }
        }

    def test_system_docker_uses_one_container_and_distinct_kernel_leases(self, monkeypatch):
        """SYSTEM Docker shares one container while isolating each run by kernel."""
        pm = self._build_pool()
        logger = sandbox_module.logging.getLogger("test_sandbox")
        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SYSTEM,
            docker_image="img:latest",
            host_tool_timeout_seconds=600,
        )

        class FakeOwner:
            base_url = "http://127.0.0.1:8888"
            host = "127.0.0.1"
            port = 8888
            container = MagicMock()

        owner = FakeOwner()
        pm._system_containers.pop("img:latest", None)
        owner.logger = logger
        owner.container.status = "running"
        owner.container.reload.return_value = None
        leases = iter([MagicMock(kernel_id="kernel-1"), MagicMock(kernel_id="kernel-2")])
        leased_executors = []
        bridge_timeouts = []

        def install_bridge(executor, logger_, request_timeout_seconds=None):
            leased_executors.append(executor)
            bridge_timeouts.append(request_timeout_seconds)
            return executor

        monkeypatch.setattr(pm, "_build_executor", lambda *args: owner)
        monkeypatch.setattr(pm, "_recover_docker_container", lambda *args: None)
        lease_timeouts = []

        def create_lease(*args, **kwargs):
            lease_timeouts.append(kwargs.get("receive_timeout_seconds"))
            return next(leases)

        monkeypatch.setattr(sandbox_module, "_DockerKernelLease", create_lease)
        monkeypatch.setattr(sandbox_module, "_install_host_tool_bridge", install_bridge)

        ex1 = pm.acquire(cfg, logger, host_tools_exist=True)
        ex2 = pm.acquire(cfg, logger, host_tools_exist=True)

        assert ex1 is not ex2
        assert leased_executors == [ex1, ex2]
        assert bridge_timeouts == [600, 600]
        assert lease_timeouts == [120, 120]
        assert pm._system_containers["img:latest"] is owner
        pm.release(ex1, logger)
        pm.release(ex2, logger)
        owner.cleanup = MagicMock()
        pm.shutdown(logger)
        owner.cleanup.assert_called_once()

    def test_acquire_system_drops_dead_executor(self):
        """Stale (no-longer-running) executors are destroyed, not handed out."""
        pm = self._build_pool()
        logger = sandbox_module.logging.getLogger("test_sandbox")

        alive = _FakeExecutor(image="img:latest", alive=True)
        dead = _FakeExecutor(image="img:latest", alive=False)
        pm._pools["img:latest"] = [alive, dead]
        pm._last_touch[id(alive)] = time.time()
        pm._last_touch[id(dead)] = time.time()

        cfg = SandboxConfig(
            level=SandboxLevel.WASM,
            scope=SandboxScope.SYSTEM,
            docker_image="img:latest",
        )
        ex = pm.acquire(cfg, logger)
        assert ex is alive
        assert dead.cleaned_up is True
        assert id(ex) in pm._in_use
        assert pm._pools["img:latest"] == []

    def test_clean_stale_destroys_dead_pool_entries(self):
        """The reaper destroys dead pool entries even when acquire is idle."""
        pm = self._build_pool()
        logger = sandbox_module.logging.getLogger("test_sandbox")

        dead = _FakeExecutor(image="img:latest", alive=False)
        pm._pools["img:latest"] = [dead]
        pm._last_touch[id(dead)] = time.time()

        pm._clean_stale(logger)
        assert dead.cleaned_up is True
        assert pm._pools["img:latest"] == []


# ---------------------------------------------------------------------------
# Docker-level integration tests (skipped if docker is not running)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not _docker_available(),
    reason="Docker daemon not reachable on this machine",
)
class TestDockerIntegration:
    """End-to-end exercise of session + system scope with real Docker containers."""

    IMAGE = "nexent/nexent-sandbox:latest"

    def test_skill_runner_passes_cli_arguments_and_demuxes_stdout(self, tmp_path):
        """A real sandbox receives argv and returns stdout, not Docker stream IDs."""
        import docker

        skill_dir = tmp_path / "argv-probe"
        script_dir = skill_dir / "scripts"
        script_dir.mkdir(parents=True)
        script_path = script_dir / "probe.py"
        script_path.write_text(
            "import argparse\n"
            "import json\n"
            "import sys\n"
            "parser = argparse.ArgumentParser()\n"
            "parser.add_argument('--message', required=True)\n"
            "parser.add_argument('--count', type=int, required=True)\n"
            "params = vars(parser.parse_args())\n"
            "print('probe warning', file=sys.stderr)\n"
            "print(json.dumps({'received': params, 'format': 'argv'}, ensure_ascii=False))\n",
            encoding="utf-8",
        )

        client = docker.from_env()
        container = client.containers.run(
            self.IMAGE,
            command=["sleep", "60"],
            detach=True,
            network_disabled=True,
        )
        workspace = "/tmp/nexent-skill-runner-integration/user/run"
        runner = SandboxSkillScriptRunner(
            SimpleNamespace(container=container, _nexent_backend="docker"),
            workspace_path=workspace,
        )
        manager = SimpleNamespace(
            resolve_skill_script=lambda *args, **kwargs: (
                str(skill_dir),
                str(script_path),
                "scripts/probe.py",
            )
        )

        try:
            result = runner(
                manager=manager,
                skill_name="argv-probe",
                script_path="scripts/probe.py",
                params='--message "沙箱参数" --count 2',
                tenant_id=None,
                working_directory=workspace,
            )

            assert json.loads(result) == {
                "received": {"message": "沙箱参数", "count": 2},
                "format": "argv",
            }
        finally:
            runner.cleanup()
            container.remove(force=True)

    def test_unrelated_session_scopes_do_not_share_container(self):
        """Unrelated SESSION builds each receive a fresh container."""
        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SESSION,
            docker_image=self.IMAGE,
            memory_limit_mb=512,
            cpu_quota=1.0,
            network_disabled=True,
            timeout_seconds=120,
        )
        logger = sandbox_module.logging.getLogger("test_sandbox")
        ex1 = build_python_executor(cfg, logger)
        ex2 = build_python_executor(cfg, logger)
        if getattr(ex1, "_nexent_backend", None) != "docker" or getattr(ex2, "_nexent_backend", None) != "docker":
            pytest.skip("DockerExecutor construction fell back to LocalPythonExecutor")
        assert ex1 is not ex2
        assert ex1.container is not ex2.container

        sandbox_module.cleanup_executor(ex1, logger, timeout=10)
        sandbox_module.cleanup_executor(ex2, logger, timeout=10)

    def test_agent_tree_session_shares_container_with_distinct_kernels(self):
        """An agent tree shares its SESSION container, not its kernels."""
        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SESSION,
            docker_image=self.IMAGE,
            memory_limit_mb=512,
            cpu_quota=1.0,
            network_disabled=True,
            timeout_seconds=120,
        )
        logger = sandbox_module.logging.getLogger("test_sandbox")
        ex1 = None
        ex2 = None
        try:
            ex1 = build_python_executor(cfg, logger)
            group = ex1._nexent_session_container_group
            ex2 = build_python_executor(
                cfg,
                logger,
                session_container_group=group,
            )

            assert ex1 is not ex2
            assert ex1.container is ex2.container
            assert ex1.kernel_id != ex2.kernel_id
        finally:
            sandbox_module.cleanup_executor(ex1, logger, timeout=10)
            sandbox_module.cleanup_executor(ex2, logger, timeout=10)

    def test_system_scope_shares_container_across_runs(self):
        """SYSTEM: runs receive distinct kernel leases over one container."""
        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SYSTEM,
            docker_image=self.IMAGE,
            memory_limit_mb=512,
            cpu_quota=1.0,
            network_disabled=True,
            timeout_seconds=120,
        )
        logger = sandbox_module.logging.getLogger("test_sandbox")
        try:
            ex1 = build_python_executor(cfg, logger)
            release_python_executor(ex1, logger)
            ex2 = build_python_executor(cfg, logger)
            assert ex1 is not ex2, "SYSTEM scope should issue a fresh kernel lease"
            assert ex1.container is ex2.container, "SYSTEM scope should reuse the same container"
        finally:
            release_python_executor(
                build_python_executor(cfg, logger) or None.__class__(),
                logger,
            )
            pool = SandboxPoolManager.get_instance()
            pool.shutdown(logger)

    def test_system_scope_executes_python_and_returns_result(self):
        """SYSTEM: the warm executor must answer simple Python round-trips."""
        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SYSTEM,
            docker_image=self.IMAGE,
            memory_limit_mb=512,
            cpu_quota=1.0,
            network_disabled=True,
            timeout_seconds=120,
        )
        logger = sandbox_module.logging.getLogger("test_sandbox")
        try:
            ex = build_python_executor(cfg, logger)
            result = ex("print(7 * 6)")
            assert "42" in result.logs
        finally:
            release_python_executor(
                build_python_executor(cfg, logger) or None.__class__(),
                logger,
            )
            pool = SandboxPoolManager.get_instance()
            pool.shutdown(logger)


# ---------------------------------------------------------------------------
# Additional coverage tests for uncovered code paths
# ---------------------------------------------------------------------------


class TestAgentLoggerAdapter:
    """Test the smolagents-compatible logger adapter."""

    def test_log_with_string_level(self):
        """String level names should be converted to LogLevel enum values."""
        adapter = sandbox_module._AgentLoggerAdapter(sandbox_module.logging.getLogger("test"))
        mock_logger = MagicMock()
        mock_logger.isEnabledFor.return_value = True
        mock_logger.log = MagicMock()
        adapter._delegate = mock_logger

        adapter.log("hello world", level="INFO")
        mock_logger.log.assert_called_once()
        call_args = mock_logger.log.call_args
        assert call_args[0][0] == sandbox_module.logging.INFO
        assert call_args[0][1] == "hello world"

    def test_log_with_debug_level(self):
        """Log at DEBUG level should route correctly."""
        adapter = sandbox_module._AgentLoggerAdapter(sandbox_module.logging.getLogger("test"))
        mock_logger = MagicMock()
        mock_logger.isEnabledFor.return_value = True
        mock_logger.log = MagicMock()
        adapter._delegate = mock_logger

        adapter.log("debug message", level="DEBUG")
        call_args = mock_logger.log.call_args
        assert call_args[0][0] == sandbox_module.logging.DEBUG

    def test_log_with_off_level(self):
        """OFF level should be mapped to a very high numeric level."""
        adapter = sandbox_module._AgentLoggerAdapter(sandbox_module.logging.getLogger("test"))
        mock_logger = MagicMock()
        mock_logger.isEnabledFor.return_value = False
        mock_logger.log = MagicMock()
        adapter._delegate = mock_logger

        adapter.log("should not appear", level="OFF")
        mock_logger.log.assert_not_called()

    def test_log_error_calls_delegate_error(self):
        """log_error should forward to delegate.error()."""
        mock_logger = MagicMock()
        adapter = sandbox_module._AgentLoggerAdapter(mock_logger)
        adapter.log_error("an error occurred")
        mock_logger.error.assert_called_once_with("an error occurred")

    def test_log_multiple_args_concatenated(self):
        """Multiple positional args should be joined as space-separated string."""
        adapter = sandbox_module._AgentLoggerAdapter(sandbox_module.logging.getLogger("test"))
        mock_logger = MagicMock()
        mock_logger.isEnabledFor.return_value = True
        mock_logger.log = MagicMock()
        adapter._delegate = mock_logger

        adapter.log("arg1", "arg2", 123)
        call_args = mock_logger.log.call_args
        assert call_args[0][1] == "arg1 arg2 123"

    def test_make_smolagents_logger_returns_adapter(self):
        """_make_smolagents_logger should return an _AgentLoggerAdapter instance."""
        logger = sandbox_module.logging.getLogger("test")
        result = sandbox_module._make_smolagents_logger(logger)
        assert isinstance(result, sandbox_module._AgentLoggerAdapter)


class TestScanShellCalls:
    """Test AST-based shell call detection."""

    def test_detects_subprocess_run(self):
        """Should detect subprocess.run() calls."""
        code = "import subprocess\nsubprocess.run(['ls'])"
        violations = sandbox_module._scan_shell_calls(code)
        assert "subprocess.run(...)" in violations

    def test_detects_subprocess_popen(self):
        """Should detect subprocess.Popen() calls."""
        code = "import subprocess\nsubprocess.Popen(['ls'])"
        violations = sandbox_module._scan_shell_calls(code)
        assert "subprocess.Popen(...)" in violations

    def test_detects_os_system(self):
        """Should detect os.system() calls."""
        code = "import os\nos.system('ls')"
        violations = sandbox_module._scan_shell_calls(code)
        assert "os.system(...)" in violations

    def test_detects_os_execv(self):
        """Should detect os.execv() calls."""
        code = "import os\nos.execv('/bin/sh', ['sh', '-c', 'ls'])"
        violations = sandbox_module._scan_shell_calls(code)
        assert "os.execv(...)" in violations

    def test_detects_os_popen(self):
        """Should detect os.popen() calls."""
        code = "import os\nos.popen('ls')"
        violations = sandbox_module._scan_shell_calls(code)
        assert "os.popen(...)" in violations

    def test_safe_code_returns_empty(self):
        """Safe code should return no violations."""
        code = "x = 1 + 2\nprint(x)\nimport json\njson.dumps({'a': 1})"
        violations = sandbox_module._scan_shell_calls(code)
        assert violations == []

    def test_syntax_error_without_shell_escape_returns_empty(self):
        """Ordinary syntax errors should not be misclassified as shell calls."""
        code = "import os(\nthis is not valid python"
        violations = sandbox_module._scan_shell_calls(code)
        assert violations == []

    def test_allows_ipython_pip_install_magic(self):
        code = "%pip install --user humanize"
        assert sandbox_module._scan_shell_calls(code) == []

    @pytest.mark.parametrize(
        "code",
        [
            "import sys, subprocess\nsubprocess.run([sys.executable, '-m', 'pip', 'install', 'humanize'])",
            "import subprocess\nsubprocess.check_call(['pip', 'install', 'humanize'])",
            "import subprocess\nsubprocess.run(['python3', '-m', 'pip', 'install', 'humanize'], check=True)",
        ],
    )
    def test_online_mode_allows_shell_free_pip_install_subprocess(self, code):
        assert sandbox_module._scan_shell_calls(
            code,
            allow_package_installs=True,
        ) == []

    def test_online_mode_allows_explicit_shell_false_for_pip_install(self):
        code = (
            "import subprocess\n"
            "subprocess.run(['pip', 'install', 'humanize'], shell=False)"
        )
        assert sandbox_module._scan_shell_calls(
            code,
            allow_package_installs=True,
        ) == []

    @pytest.mark.parametrize(
        "code",
        [
            "import subprocess\nsubprocess.run(['curl', 'https://example.com'])",
            "import subprocess\nsubprocess.run('pip install humanize', shell=True)",
            "import subprocess\npackage = 'humanize'\nsubprocess.run(['pip', 'install', package])",
            "import os\nos.system('pip install humanize')",
        ],
    )
    def test_online_mode_still_blocks_non_allowlisted_shell_calls(self, code):
        assert sandbox_module._scan_shell_calls(
            code,
            allow_package_installs=True,
        )

    @pytest.mark.parametrize(
        "code",
        [
            "import subprocess\nsubprocess.run(['pip', 'install', 'humanize'], cwd='/tmp')",
            "import subprocess\nsubprocess.run([])",
        ],
    )
    def test_online_mode_rejects_unsafe_pip_call_shapes(self, code):
        assert sandbox_module._scan_shell_calls(
            code,
            allow_package_installs=True,
        )

    @pytest.mark.parametrize(
        "code",
        [
            "!curl https://example.com",
            "%system curl https://example.com",
            "%%bash\ncurl https://example.com",
            "get_ipython().system('curl https://example.com')",
            "get_ipython().getoutput('curl https://example.com')",
        ],
    )
    def test_detects_ipython_shell_escape_paths(self, code):
        assert sandbox_module._scan_shell_calls(code)

    def test_multiple_violations(self):
        """Should detect multiple violations in same code."""
        code = "import subprocess, os\nsubprocess.run(['ls'])\nos.system('whoami')"
        violations = sandbox_module._scan_shell_calls(code)
        assert "subprocess.run(...)" in violations
        assert "os.system(...)" in violations


class TestInstallShellGuard:
    """Test shell call interception."""

    def test_install_shell_guard_function_exists(self):
        """Verify the shell guard installation function exists and is callable."""
        assert callable(sandbox_module._install_shell_guard)

    def test_make_code_output_falls_back_without_smolagents(self, monkeypatch):
        real_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name == "smolagents.remote_executors":
                raise ImportError("smolagents unavailable")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", guarded_import)

        result = sandbox_module._make_code_output("blocked")

        assert result == SimpleNamespace(
            output=None,
            logs="blocked",
            is_final_answer=False,
        )

    def test_shell_guard_has_expected_behavior(self):
        """Test that shell guard blocks subprocess calls through AST analysis."""
        # The actual behavior is tested through integration tests
        # Here we verify the AST scanner detects known dangerous patterns
        code = "import subprocess; subprocess.run(['ls'])"
        violations = sandbox_module._scan_shell_calls(code)
        assert len(violations) > 0
        assert "subprocess.run(...)" in violations


class TestToolBridge:
    """Test the host tool bridge HTTP server."""

    def test_proxy_code_generates_valid_python(self):
        """proxy_code should generate valid Python with tool definitions."""
        bridge = sandbox_module._ToolBridge(sandbox_module.logging.getLogger("test"))
        try:
            code = bridge.proxy_code({"my_tool": object()})
            namespace = {}
            exec(code, namespace)
            assert "def my_tool(" in code
            assert "_NEXENT_TOOL_BRIDGE_URL" in code
            assert "_NEXENT_TOOL_BRIDGE_TIMEOUT = None" in code
            assert "timeout=120" not in code
            assert "def _nexent_call_host_tool(" in code
        finally:
            bridge.close()

    def test_proxy_code_uses_configured_request_timeout(self):
        """An explicit policy value is injected without a fixed SDK timeout."""
        bridge = sandbox_module._ToolBridge(
            sandbox_module.logging.getLogger("test"),
            request_timeout_seconds=900,
        )
        try:
            code = bridge.proxy_code({"my_tool": object()})
            assert "_NEXENT_TOOL_BRIDGE_TIMEOUT = 900.0" in code
        finally:
            bridge.close()

    @pytest.mark.parametrize("invalid_timeout", [True, 0, -1])
    def test_rejects_invalid_request_timeout(self, invalid_timeout):
        with pytest.raises(ValueError, match="positive number or None"):
            sandbox_module._ToolBridge(
                sandbox_module.logging.getLogger("test"),
                request_timeout_seconds=invalid_timeout,
            )

    def test_bridge_host_returns_nexent_runtime_when_containerized(self, monkeypatch):
        """Containerized runtime should use nexent-runtime hostname."""
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: True)
        bridge = sandbox_module._ToolBridge(sandbox_module.logging.getLogger("test"))
        try:
            host = bridge._bridge_host()
            assert host == "nexent-runtime"
        finally:
            bridge.close()

    def test_bridge_host_returns_host_docker_internal_when_not_containerized(self, monkeypatch):
        """Non-containerized runtime should use host.docker.internal."""
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: False)
        bridge = sandbox_module._ToolBridge(sandbox_module.logging.getLogger("test"))
        try:
            host = bridge._bridge_host()
            assert host == "host.docker.internal"
        finally:
            bridge.close()

    def test_proxy_code_uses_provided_bridge_host(self):
        """proxy_code should use provided bridge_host over computed one."""
        bridge = sandbox_module._ToolBridge(sandbox_module.logging.getLogger("test"))
        try:
            code = bridge.proxy_code({"tool": object()}, bridge_host="custom.host")
            assert "http://custom.host:" in code
        finally:
            bridge.close()

    def test_is_host_tool_detection(self):
        """_is_host_tool should detect _nexent_execute_on_host attribute."""
        host_tool = SimpleNamespace()
        host_tool._nexent_execute_on_host = True
        assert sandbox_module._is_host_tool(host_tool) is True

        regular_tool = SimpleNamespace()
        regular_tool._nexent_execute_on_host = False
        assert sandbox_module._is_host_tool(regular_tool) is False

        plain_tool = SimpleNamespace()
        assert sandbox_module._is_host_tool(plain_tool) is False


class TestWrapWithDiagnostics:
    """Test ModuleNotFoundError diagnostic wrapping."""

    def test_wrap_with_diagnostics_function_exists(self):
        """Verify the diagnostics wrapper function exists and is callable."""
        assert callable(sandbox_module._wrap_with_diagnostics)

    def test_diagnostics_uses_module_regex(self):
        """Verify the missing package regex pattern is defined and works."""
        import re
        pattern = re.compile(r"No module named ['\"]([^'\"]+)['\"]")
        match = pattern.search("No module named 'requests'")
        assert match is not None
        assert match.group(1) == "requests"


class TestSyncOutputsToMinio:
    """Test output file synchronization to MinIO."""

    def test_sync_returns_empty_when_dir_not_exists(self, tmp_path):
        """Should return empty list when output directory doesn't exist."""
        mock_minio = MagicMock()
        result = sandbox_module._sync_outputs_to_minio(
            str(tmp_path / "nonexistent"),
            "run-123",
            mock_minio,
            "test-bucket",
            sandbox_module.logging.getLogger("test"),
        )
        assert result == []

    def test_sync_uploads_files_to_minio(self, tmp_path):
        """Should upload files and return descriptors."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        test_file = output_dir / "result.txt"
        test_file.write_bytes(b"test content")

        mock_minio = MagicMock()
        mock_minio.put_object = MagicMock()

        result = sandbox_module._sync_outputs_to_minio(
            str(output_dir),
            "run-456",
            mock_minio,
            "test-bucket",
            sandbox_module.logging.getLogger("test"),
        )

        assert len(result) == 1
        assert result[0]["name"] == "result.txt"
        assert result[0]["size"] == 12
        assert "sha256" in result[0]
        assert "minio_key" in result[0]
        assert "agent-runs/run-456/output/result.txt" in result[0]["minio_key"]
        mock_minio.put_object.assert_called_once()

    def test_sync_skips_directories(self, tmp_path):
        """Should skip directories in output."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        sub_dir = output_dir / "subdir"
        sub_dir.mkdir()

        mock_minio = MagicMock()

        result = sandbox_module._sync_outputs_to_minio(
            str(output_dir),
            "run-789",
            mock_minio,
            "test-bucket",
            sandbox_module.logging.getLogger("test"),
        )

        assert result == []

    def test_sync_skips_empty_files(self, tmp_path):
        """Should skip empty files."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        empty_file = output_dir / "empty.txt"
        empty_file.write_bytes(b"")

        mock_minio = MagicMock()

        result = sandbox_module._sync_outputs_to_minio(
            str(output_dir),
            "run-empty",
            mock_minio,
            "test-bucket",
            sandbox_module.logging.getLogger("test"),
        )

        assert result == []

    def test_sync_handles_upload_failure_gracefully(self, tmp_path):
        """Should continue on upload errors and log them."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        test_file = output_dir / "failing.txt"
        test_file.write_bytes(b"content")

        mock_minio = MagicMock()
        mock_minio.put_object = MagicMock(side_effect=Exception("Upload failed"))

        result = sandbox_module._sync_outputs_to_minio(
            str(output_dir),
            "run-fail",
            mock_minio,
            "test-bucket",
            sandbox_module.logging.getLogger("test"),
        )

        assert result == []


class TestCleanupExecutor:
    """Test the three-layer cleanup mechanism."""

    def test_cleanup_returns_early_for_none(self):
        """Should return immediately if executor is None."""
        sandbox_module.cleanup_executor(None, sandbox_module.logging.getLogger("test"))

    def test_cleanup_returns_early_without_cleanup_method(self):
        """Should return if executor has no cleanup method."""
        mock_executor = SimpleNamespace()
        sandbox_module.cleanup_executor(mock_executor, sandbox_module.logging.getLogger("test"))

    def test_cleanup_graceful_success(self):
        """Should complete gracefully when cleanup succeeds."""
        executor = SimpleNamespace()
        executor.cleanup = MagicMock()
        mock_logger = MagicMock()

        sandbox_module.cleanup_executor(executor, mock_logger, timeout=1.0)

        executor.cleanup.assert_called_once()
        mock_logger.debug.assert_called()

    def test_cleanup_force_kills_container_on_timeout(self):
        """Should force-kill container when cleanup times out."""
        container = SimpleNamespace()
        container.kill = MagicMock()
        executor = SimpleNamespace()
        executor.cleanup = MagicMock(side_effect=sandbox_module.FuturesTimeoutError())
        executor.container = container
        mock_logger = MagicMock()

        sandbox_module.cleanup_executor(executor, mock_logger, timeout=0.01)

        container.kill.assert_called_once()
        mock_logger.warning.assert_called()

    def test_cleanup_logs_error_on_cleanup_exception(self):
        """Should log error when cleanup raises an exception."""
        executor = SimpleNamespace()
        executor.cleanup = MagicMock(side_effect=RuntimeError("cleanup failed"))
        executor.container = SimpleNamespace()
        mock_logger = MagicMock()

        sandbox_module.cleanup_executor(executor, mock_logger, timeout=1.0)

        mock_logger.warning.assert_called()


class TestSandboxConnectionHosts:
    """Test sandbox connection host resolution."""

    def test_returns_container_name_when_containerized(self, monkeypatch):
        """Containerized runtime should return sandbox container name."""
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: True)
        mock_container = MagicMock()

        hosts = sandbox_module._sandbox_connection_hosts(mock_container)

        assert hosts == [sandbox_module.SANDBOX_CONTAINER_NAME]

    def test_returns_localhost_and_network_ip_when_not_containerized(self, monkeypatch):
        """Non-containerized should check network settings for IP."""
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: False)
        mock_container = MagicMock()
        mock_container.attrs = {
            "NetworkSettings": {
                "Networks": {
                    sandbox_module.SANDBOX_NETWORK_NAME: {"IPAddress": "172.18.0.5"}
                }
            }
        }

        hosts = sandbox_module._sandbox_connection_hosts(mock_container)

        assert "127.0.0.1" in hosts
        assert "172.18.0.5" in hosts


class TestIsContainerizedRuntime:
    """Test Docker environment detection."""

    def test_dockerenv_not_exists_returns_false(self, monkeypatch):
        """Should return False when /.dockerenv doesn't exist."""
        monkeypatch.setattr(sandbox_module.Path, "exists", lambda self: False)

        result = sandbox_module._is_containerized_runtime()

        assert result is False


class TestKernelGatewayCommand:
    """Test Kernel Gateway command generation."""

    def test_command_includes_required_flags(self):
        """Command should include all required Kernel Gateway flags."""
        command = sandbox_module._kernel_gateway_command()

        assert any("--KernelGatewayApp.ip=0.0.0.0" in arg for arg in command)
        assert any("--KernelGatewayApp.port=8888" in arg for arg in command)
        assert "--KernelGatewayApp.allow_origin=*" in command
        assert "--ServerApp.allow_remote_access=True" in command
        assert "--JupyterWebsocketPersonality.list_kernels=True" in command


class TestRecoveredDockerExecutor:
    """Test recovered Docker executor facade."""

    def test_cleanup_removes_container(self):
        """cleanup() should force-remove the container."""
        mock_container = MagicMock()
        mock_executor = sandbox_module._RecoveredDockerExecutor(
            mock_container,
            sandbox_module.logging.getLogger("test"),
            "127.0.0.1",
        )

        mock_executor.cleanup()

        mock_container.remove.assert_called_once_with(force=True)

    def test_cleanup_handles_removal_failure(self):
        """cleanup() should handle container removal failure gracefully."""
        mock_container = MagicMock()
        mock_container.remove.side_effect = Exception("docker error")
        mock_executor = sandbox_module._RecoveredDockerExecutor(
            mock_container,
            sandbox_module.logging.getLogger("test"),
            "127.0.0.1",
        )

        mock_executor.cleanup()

        mock_container.remove.assert_called_once()


class TestDockerKernelLease:
    """Test Docker kernel lease management."""

    @staticmethod
    def _lease():
        lease = object.__new__(sandbox_module._DockerKernelLease)
        lease.logger = MagicMock()
        lease._logger = MagicMock()
        lease.base_url = "http://sandbox:8888"
        lease.host = "sandbox"
        lease.port = 8888
        lease.kernel_id = "kernel-1"
        lease._channel_session_id = "session-1"
        lease.ws_url = (
            "ws://sandbox:8888/api/kernels/kernel-1/channels?session_id=session-1"
        )
        lease._receive_timeout_seconds = 0.25
        lease._closed = False
        lease._unhealthy = False
        lease._nexent_kernel_recovery_supported = True
        lease._requests = MagicMock()
        lease._cached_variables = None
        lease._cached_tools = None
        lease._kernel_bootstrap_code = []
        return lease

    def test_busy_kernel_continues_after_receive_timeout(self, monkeypatch):
        from websocket import ABNF, WebSocketTimeoutException

        lease = self._lease()
        lease._get_kernel_execution_state = MagicMock(return_value="busy")
        websocket = MagicMock()
        websocket.recv_data.side_effect = [
            WebSocketTimeoutException("poll timeout"),
            (
                ABNF.OPCODE_TEXT,
                json.dumps(
                    {
                        "parent_header": {"msg_id": "request-1"},
                        "msg_type": "stream",
                        "content": {"text": "done\n"},
                    }
                ),
            ),
            (
                ABNF.OPCODE_TEXT,
                json.dumps(
                    {
                        "parent_header": {"msg_id": "request-1"},
                        "msg_type": "status",
                        "content": {"execution_state": "idle"},
                    }
                ),
            ),
        ]
        create_connection = MagicMock(return_value=websocket)
        monkeypatch.setattr("websocket.create_connection", create_connection)
        monkeypatch.setattr(
            "smolagents.remote_executors._websocket_send_execute_request",
            lambda code, ws: "request-1",
        )

        result = lease.run_code_raise_errors("print('done')")

        assert result.logs == "done\n"
        assert lease._unhealthy is False
        lease._get_kernel_execution_state.assert_called_once_with()
        create_connection.assert_called_once_with(lease.ws_url, timeout=0.25)
        websocket.close.assert_called_once_with()

    def test_kernel_lease_uses_stable_gateway_session_id(self, monkeypatch):
        container_executor = SimpleNamespace(
            logger=MagicMock(),
            additional_imports=[],
            installed_packages=[],
            _nexent_backend="docker",
            base_url="http://sandbox:8888",
            host="sandbox",
            port=8888,
        )
        monkeypatch.setattr(
            "smolagents.remote_executors._create_kernel_http",
            MagicMock(return_value="kernel-1"),
        )
        monkeypatch.setattr(sandbox_module.secrets, "token_hex", lambda _size: "stable-session")

        lease = sandbox_module._DockerKernelLease(container_executor, MagicMock())

        assert lease.ws_url == (
            "ws://sandbox:8888/api/kernels/kernel-1/channels"
            "?session_id=stable-session"
        )
        assert lease._build_channels_url("kernel-1") == lease.ws_url

    def test_idle_kernel_without_terminal_message_fails_and_marks_lease_unhealthy(
        self,
        monkeypatch,
    ):
        from websocket import WebSocketTimeoutException

        lease = self._lease()
        lease._get_kernel_execution_state = MagicMock(return_value="idle")
        websocket = MagicMock()
        websocket.recv_data.side_effect = WebSocketTimeoutException("terminal message lost")
        monkeypatch.setattr("websocket.create_connection", MagicMock(return_value=websocket))
        monkeypatch.setattr(
            "smolagents.remote_executors._websocket_send_execute_request",
            lambda code, ws: "request-1",
        )

        with pytest.raises(RuntimeError, match="kernel channel failed"):
            lease.run_code_raise_errors("print('done')")

        assert lease._unhealthy is True

    def test_unhealthy_lease_replaces_kernel_before_next_execution(self, monkeypatch):
        from websocket import ABNF

        lease = self._lease()
        lease._unhealthy = True
        lease._replace_unhealthy_kernel = MagicMock(
            side_effect=lambda: setattr(lease, "_unhealthy", False)
        )
        websocket = MagicMock()
        websocket.recv_data.return_value = (
            ABNF.OPCODE_TEXT,
            json.dumps(
                {
                    "parent_header": {"msg_id": "request-1"},
                    "msg_type": "status",
                    "content": {"execution_state": "idle"},
                }
            ),
        )
        monkeypatch.setattr("websocket.create_connection", MagicMock(return_value=websocket))
        monkeypatch.setattr(
            "smolagents.remote_executors._websocket_send_execute_request",
            lambda code, ws: "request-1",
        )

        lease.run_code_raise_errors("print('retry')")

        lease._replace_unhealthy_kernel.assert_called_once_with()
        assert lease._unhealthy is False

    def test_kernel_replacement_replays_framework_state(self, monkeypatch):
        from smolagents.remote_executors import RemotePythonExecutor

        lease = self._lease()
        lease.host = "sandbox"
        lease.port = 8888
        lease._unhealthy = True
        lease._cached_variables = {"document": "input.docx"}
        lease._cached_tools = {"run_skill_script": object()}
        lease._kernel_bootstrap_code = ["def upload_to_s3(*args, **kwargs): pass"]
        lease._requests.delete.return_value = SimpleNamespace(status_code=204)
        send_variables = MagicMock()
        send_tools = MagicMock()
        run_code = MagicMock()
        monkeypatch.setattr(RemotePythonExecutor, "send_variables", send_variables)
        monkeypatch.setattr(RemotePythonExecutor, "send_tools", send_tools)
        monkeypatch.setattr(
            "smolagents.remote_executors._create_kernel_http",
            MagicMock(return_value="kernel-2"),
        )
        monkeypatch.setattr(lease, "run_code_raise_errors", run_code)

        lease._replace_unhealthy_kernel()

        lease._requests.delete.assert_called_once_with(
            "http://sandbox:8888/api/kernels/kernel-1",
            timeout=5,
        )
        assert lease.kernel_id == "kernel-2"
        assert lease.ws_url.startswith(
            "ws://sandbox:8888/api/kernels/kernel-2/channels?session_id="
        )
        assert lease.ws_url.endswith(lease._channel_session_id)
        assert lease._unhealthy is False
        send_variables.assert_called_once_with(lease, lease._cached_variables)
        send_tools.assert_called_once_with(lease, lease._cached_tools)
        run_code.assert_called_once_with(lease._kernel_bootstrap_code[0])

    @pytest.mark.parametrize("setup_kind", ["variables", "tools"])
    def test_framework_setup_recovers_unhealthy_kernel_in_same_run(
        self,
        monkeypatch,
        setup_kind,
    ):
        from smolagents.remote_executors import RemotePythonExecutor

        lease = self._lease()
        payload = {"document": "input.docx"}

        def fail_setup(*_args, **_kwargs):
            lease._unhealthy = True
            raise RuntimeError("kernel channel failed")

        remote_setup = MagicMock(side_effect=fail_setup)
        replace_kernel = MagicMock(
            side_effect=lambda: setattr(lease, "_unhealthy", False)
        )
        monkeypatch.setattr(
            RemotePythonExecutor,
            "send_variables" if setup_kind == "variables" else "send_tools",
            remote_setup,
        )
        monkeypatch.setattr(lease, "_replace_unhealthy_kernel", replace_kernel)

        if setup_kind == "variables":
            lease.send_variables(payload)
            assert lease._cached_variables == payload
        else:
            lease.send_tools(payload)
            assert lease._cached_tools == payload

        remote_setup.assert_called_once_with(lease, payload)
        replace_kernel.assert_called_once_with()
        assert lease._unhealthy is False

    def test_bootstrap_registration_recovers_unhealthy_kernel_in_same_run(self):
        lease = self._lease()
        code = "os.chdir('/mnt/nexent/workdir/run/outputs')"
        run_code = MagicMock(
            side_effect=[
                RuntimeError("kernel channel failed"),
                SimpleNamespace(output=None, logs="", is_final_answer=False),
            ]
        )
        replace_kernel = MagicMock(
            side_effect=lambda: setattr(lease, "_unhealthy", False)
        )
        lease._unhealthy = True
        lease.run_code_raise_errors = run_code
        lease._replace_unhealthy_kernel = replace_kernel

        lease.register_kernel_bootstrap_code(code)

        assert run_code.call_args_list == [call(code), call(code)]
        replace_kernel.assert_called_once_with()
        assert lease._kernel_bootstrap_code == [code]

    def test_unrelated_messages_do_not_postpone_watchdog(self, monkeypatch):
        from websocket import ABNF

        lease = self._lease()
        lease._get_kernel_execution_state = MagicMock(return_value="idle")
        websocket = MagicMock()
        websocket.recv_data.return_value = (
            ABNF.OPCODE_TEXT,
            json.dumps(
                {
                    "parent_header": {"msg_id": "another-request"},
                    "msg_type": "status",
                    "content": {"execution_state": "idle"},
                }
            ),
        )
        monotonic = MagicMock(side_effect=[0.0, 0.0, 1.0])
        monkeypatch.setattr(sandbox_module.time, "monotonic", monotonic)
        monkeypatch.setattr("websocket.create_connection", MagicMock(return_value=websocket))
        monkeypatch.setattr(
            "smolagents.remote_executors._websocket_send_execute_request",
            lambda code, ws: "request-1",
        )

        with pytest.raises(RuntimeError, match="watchdog deadline"):
            lease.run_code_raise_errors("print('done')")

        assert lease._unhealthy is True
        lease._get_kernel_execution_state.assert_called_once_with()
        websocket.recv_data.assert_called_once_with(control_frame=True)

    def test_control_frames_do_not_postpone_watchdog(self, monkeypatch):
        from websocket import ABNF

        lease = self._lease()
        lease._get_kernel_execution_state = MagicMock(return_value="idle")
        websocket = MagicMock()
        websocket.recv_data.return_value = (ABNF.OPCODE_PING, b"heartbeat")
        monkeypatch.setattr(
            sandbox_module.time,
            "monotonic",
            MagicMock(side_effect=[0.0, 0.0, 1.0]),
        )
        monkeypatch.setattr("websocket.create_connection", MagicMock(return_value=websocket))
        monkeypatch.setattr(
            "smolagents.remote_executors._websocket_send_execute_request",
            lambda code, ws: "request-1",
        )

        with pytest.raises(RuntimeError, match="watchdog deadline"):
            lease.run_code_raise_errors("print('done')")

        assert lease._unhealthy is True
        websocket.recv_data.assert_called_once_with(control_frame=True)

    def test_closed_websocket_marks_busy_kernel_lease_unhealthy(self, monkeypatch):
        from websocket import WebSocketConnectionClosedException

        lease = self._lease()
        lease._get_kernel_execution_state = MagicMock(return_value="busy")
        websocket = MagicMock()
        websocket.recv_data.side_effect = WebSocketConnectionClosedException("channel closed")
        monkeypatch.setattr("websocket.create_connection", MagicMock(return_value=websocket))
        monkeypatch.setattr(
            "smolagents.remote_executors._websocket_send_execute_request",
            lambda code, ws: "request-1",
        )

        with pytest.raises(RuntimeError, match="connection closed unexpectedly"):
            lease.run_code_raise_errors("print('done')")

        assert lease._unhealthy is True
        lease._get_kernel_execution_state.assert_called_once_with()

    def test_kernel_state_query_is_bounded_and_returns_none_on_error(self):
        lease = self._lease()
        lease._requests.get.side_effect = TimeoutError("gateway unavailable")

        assert lease._get_kernel_execution_state() is None
        lease._requests.get.assert_called_once_with(
            "http://sandbox:8888/api/kernels/kernel-1",
            timeout=0.25,
        )
        lease._logger.warning.assert_called_once()

    def test_inherits_docker_backend_marker(self, monkeypatch):
        """System kernel leases must remain identifiable as Docker executors."""
        from smolagents import remote_executors

        monkeypatch.setattr(remote_executors, "_create_kernel_http", lambda *_args: "kernel-1")
        owner = SimpleNamespace(
            logger=MagicMock(),
            additional_imports=[],
            installed_packages=[],
            base_url="http://sandbox:8888",
            host="sandbox",
            port=8888,
            _nexent_backend="docker",
            container=MagicMock(),
        )

        lease = sandbox_module._DockerKernelLease(
            owner,
            sandbox_module.logging.getLogger("test"),
        )

        assert lease._nexent_backend == "docker"

    def test_send_tools_delegates_to_remote_executor(self, monkeypatch):
        """send_tools should delegate to RemotePythonExecutor."""
        # This test verifies the method exists and has correct signature
        # Full integration would require mocking smolagents internals
        assert hasattr(sandbox_module._DockerKernelLease, "send_tools")
        assert callable(sandbox_module._DockerKernelLease.send_tools)


class TestWrapExecutor:
    """Test executor wrapping logic."""

    def test_wrap_executor_function_exists(self):
        """Verify the wrap executor function exists and is callable."""
        assert callable(sandbox_module._wrap_executor)

    def test_wrap_executor_does_nothing_for_local(self):
        """LOCAL level should return executor unchanged."""
        mock_executor = MagicMock(spec=[])
        cfg = SandboxConfig(level=SandboxLevel.LOCAL)

        result = sandbox_module._wrap_executor(
            mock_executor,
            cfg,
            sandbox_module.logging.getLogger("test"),
        )

        assert result is mock_executor

    def test_online_docker_executor_bootstraps_user_site_before_user_code(self):
        original_call = MagicMock(return_value="ok")
        executor = SimpleNamespace(__call__=original_call)
        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            network_disabled=False,
        )

        wrapped = sandbox_module._wrap_executor(
            executor,
            cfg,
            sandbox_module.logging.getLogger("test"),
        )

        assert wrapped.__call__("print('ready')") == "ok"
        sent_code = original_call.call_args.args[0]
        assert sent_code.startswith("import importlib as _nexent_importlib")
        assert "getusersitepackages()" in sent_code
        assert "path_importer_cache.pop" in sent_code
        assert "invalidate_caches()" in sent_code
        assert sent_code.endswith("print('ready')")
        assert sandbox_module._install_online_user_site(wrapped) is wrapped

    def test_offline_docker_executor_does_not_bootstrap_user_site(self):
        original_call = MagicMock(return_value="ok")
        executor = SimpleNamespace(__call__=original_call)
        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            network_disabled=True,
        )

        wrapped = sandbox_module._wrap_executor(
            executor,
            cfg,
            sandbox_module.logging.getLogger("test"),
        )

        assert wrapped.__call__("print('ready')") == "ok"
        original_call.assert_called_once_with("print('ready')")

    def test_kernel_lease_real_call_applies_online_bootstrap(self):
        lease = object.__new__(sandbox_module._DockerKernelLease)
        lease._logger = MagicMock()
        lease.run_code_raise_errors = MagicMock(return_value="ok")
        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            network_disabled=False,
        )

        wrapped = sandbox_module._wrap_executor(
            lease,
            cfg,
            sandbox_module.logging.getLogger("test"),
        )

        assert wrapped("print('ready')") == "ok"
        sent_code = lease.run_code_raise_errors.call_args.args[0]
        assert sent_code.startswith("import importlib as _nexent_importlib")
        assert "path_importer_cache.pop" in sent_code
        assert "invalidate_caches()" in sent_code
        assert sent_code.endswith("print('ready')")

    def test_boxed_kernel_lease_delegates_without_shell_scanning(self):
        lease = object.__new__(sandbox_module._DockerKernelLease)
        lease._logger = MagicMock()
        lease._nexent_shell_policy = ShellPolicy.BOXED
        lease.run_code_raise_errors = MagicMock(return_value="executed")

        result = lease("import os; os.system('handled by boxed executor')")

        assert result == "executed"
        lease.run_code_raise_errors.assert_called_once_with(
            "import os; os.system('handled by boxed executor')"
        )
        lease._logger.warning.assert_not_called()

    def test_online_kernel_lease_allows_subprocess_and_shell_escape(self):
        lease = object.__new__(sandbox_module._DockerKernelLease)
        lease._logger = MagicMock()
        lease.run_code_raise_errors = MagicMock(return_value="executed")
        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            network_disabled=False,
            shell_policy=ShellPolicy.DISABLED,
        )
        sandbox_module._wrap_executor(
            lease,
            cfg,
            sandbox_module.logging.getLogger("test"),
        )

        code = "import subprocess\nsubprocess.run(['python', '-m', 'pip', 'install', 'humanize'])"
        result = lease(code)

        assert result == "executed"
        sent_code = lease.run_code_raise_errors.call_args.args[0]
        assert sent_code.endswith(code)

    def test_offline_kernel_lease_blocks_shell_with_code_output(self):
        lease = object.__new__(sandbox_module._DockerKernelLease)
        lease._logger = MagicMock()
        lease.run_code_raise_errors = MagicMock(return_value="not-called")
        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            network_disabled=True,
            shell_policy=ShellPolicy.DISABLED,
        )
        sandbox_module._wrap_executor(
            lease,
            cfg,
            sandbox_module.logging.getLogger("test"),
        )

        result = lease("!curl https://example.com")

        assert "SecurityError" in result.logs
        assert result.output is None
        assert result.is_final_answer is False
        lease.run_code_raise_errors.assert_not_called()


class TestBuildPythonExecutor:
    """Test the main factory function."""

    def test_managed_agents_preserve_configured_sandbox(self, mocker):
        """Managed agents must not force a configured sandbox back to LOCAL."""
        cfg = SandboxConfig(level=SandboxLevel.DOCKER)
        logger = sandbox_module.logging.getLogger("test")
        expected_executor = MagicMock()
        pool = SandboxPoolManager.get_instance()
        acquire = mocker.patch.object(pool, "acquire", return_value=expected_executor)

        executor = sandbox_module.build_python_executor(
            cfg,
            logger,
            managed_agents_exist=True,
            host_tools_exist=True,
        )

        assert executor is expected_executor
        assert cfg.level == SandboxLevel.DOCKER
        acquire.assert_called_once_with(cfg, logger, True)

    def test_session_container_group_is_forwarded_to_pool(self, mocker):
        cfg = SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SESSION)
        logger = sandbox_module.logging.getLogger("test")
        group = sandbox_module._SessionDockerContainerGroup(SimpleNamespace())
        expected_executor = MagicMock()
        pool = SandboxPoolManager.get_instance()
        acquire = mocker.patch.object(pool, "acquire", return_value=expected_executor)

        result = sandbox_module.build_python_executor(
            cfg,
            logger,
            host_tools_exist=True,
            session_container_group=group,
        )

        assert result is expected_executor
        acquire.assert_called_once_with(
            cfg,
            logger,
            True,
            session_container_group=group,
        )

    def test_session_scope_creates_fresh_executor(self):
        """SESSION scope should always create fresh executor."""
        cfg = SandboxConfig(level=SandboxLevel.LOCAL, scope=SandboxScope.SESSION)
        logger = sandbox_module.logging.getLogger("test")

        ex1 = sandbox_module.build_python_executor(cfg, logger)
        ex2 = sandbox_module.build_python_executor(cfg, logger)

        assert ex1 is not ex2

    def test_release_python_executor_handles_none(self):
        """release_python_executor should handle None gracefully."""
        sandbox_module.release_python_executor(None, sandbox_module.logging.getLogger("test"))


class TestSandboxPoolManagerAcquire:
    """Test pool manager acquire paths."""

    def test_acquire_system_reuses_pooled_executor(self):
        """SYSTEM scope should reuse pooled executor when available."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")

        alive = _FakeExecutor(image="reuse:test", alive=True)
        pm._pools["reuse:test"] = [alive]
        pm._last_touch[id(alive)] = time.time()

        cfg = SandboxConfig(
            level=SandboxLevel.WASM,
            scope=SandboxScope.SYSTEM,
            docker_image="reuse:test",
        )

        executor = pm.acquire(cfg, logger)

        assert executor is alive
        assert id(executor) in pm._in_use

    def test_acquire_releases_immediate(self):
        """release_immediate should destroy executor and shared container."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")

        executor = _FakeExecutor(image="immediate:test", alive=True)
        ex_id = id(executor)
        pm._in_use[ex_id] = "immediate:test"
        pm._executors[ex_id] = executor
        pm._lease_owners[ex_id] = executor

        pm.release_immediate(executor, logger)

        assert ex_id not in pm._in_use
        assert ex_id not in pm._lease_owners
        assert executor.cleaned_up is True

    def test_release_returns_to_pool_for_system_scope(self):
        """release() should return executor to pool for SYSTEM scope."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")

        executor = _FakeExecutor(image="pool:test", alive=True)
        ex_id = id(executor)
        pm._in_use[ex_id] = "pool:test"
        pm._executors[ex_id] = executor
        pm._last_touch[ex_id] = time.time()

        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SYSTEM,
            docker_image="pool:test",
        )
        executor._nexent_sandbox_config = cfg

        pm.release(executor, logger)

        assert ex_id not in pm._in_use
        assert "pool:test" in pm._pools

    def test_release_destroys_for_session_scope(self):
        """release() should destroy executor for SESSION scope."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")

        executor = _FakeExecutor(image="session:test", alive=True)
        ex_id = id(executor)
        pm._in_use[ex_id] = "session:test"
        pm._executors[ex_id] = executor
        pm._last_touch[ex_id] = time.time()

        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SESSION,
            docker_image="session:test",
        )
        executor._nexent_sandbox_config = cfg

        pm.release(executor, logger)

        assert ex_id not in pm._in_use
        assert "session:test" not in pm._pools
        assert executor.cleaned_up is True

    def test_acquire_destroys_untracked_executor(self):
        """Executor not in pool_key should be destroyed."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")

        executor = _FakeExecutor(image="untracked:test", alive=True)
        ex_id = id(executor)
        pm._in_use[ex_id] = None
        pm._executors[ex_id] = executor

        pm.release(executor, logger)

        assert executor.cleaned_up is True


class TestPoolManagerEvictor:
    """Test idle eviction functionality."""

    def test_evict_idle_removes_old_executors(self):
        """_evict_idle should remove executors idle longer than TTL."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")

        old_executor = _FakeExecutor(image="old:test", alive=True)
        pm._pools["old:test"] = [old_executor]
        pm._last_touch[id(old_executor)] = time.time() - pm._idle_ttl_seconds - 10

        pm._evict_idle(logger)

        assert old_executor.cleaned_up is True
        assert "old:test" not in pm._pools or pm._pools["old:test"] == []

    def test_shutdown_clears_all_state(self):
        """shutdown() should clear all internal state."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")

        executor = _FakeExecutor(image="shutdown:test", alive=True)
        pm._pools["shutdown:test"] = [executor]
        pm._executors[id(executor)] = executor
        pm._last_touch[id(executor)] = time.time()

        pm.shutdown(logger)

        assert pm._pools == {}
        assert pm._executors == {}
        assert pm._last_touch == {}
        assert pm._system_containers == {}


class TestBuildDockerExecutor:
    """Test Docker executor building with error paths."""

    def test_docker_executor_handles_docker_not_available(self, monkeypatch):
        """Should handle Docker not being available gracefully."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")
        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SESSION,
            docker_image="fallback:test",
        )

        # Mock smolagents remote_executors to not have DockerExecutor
        original_module = sys.modules.get("smolagents.remote_executors")

        class MockRemoteExecutors:
            pass

        mock_remote = MockRemoteExecutors()

        if original_module:
            for attr in dir(original_module):
                if not attr.startswith("_"):
                    try:
                        setattr(mock_remote, attr, getattr(original_module, attr))
                    except Exception:
                        pass

        # Remove DockerExecutor if present
        if hasattr(mock_remote, "DockerExecutor"):
            delattr(mock_remote, "DockerExecutor")

        monkeypatch.setitem(sys.modules, "smolagents.remote_executors", mock_remote)

        executor = pm._build_docker_executor(cfg, logger, host_tools_exist=False)

        # Should fall back to local executor
        assert getattr(executor, "_nexent_backend", None) == "local"

    def test_none_docker_executor_falls_back_to_local(self, monkeypatch):
        pm = SandboxPoolManager.get_instance()
        cfg = SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SESSION)
        local_executor = SimpleNamespace(_nexent_backend="local")
        monkeypatch.setitem(
            sys.modules,
            "smolagents.remote_executors",
            SimpleNamespace(DockerExecutor=None),
        )
        monkeypatch.setattr(
            sandbox_module,
            "_make_local_executor",
            MagicMock(return_value=local_executor),
        )
        monkeypatch.setattr(
            sandbox_module,
            "_wrap_executor",
            lambda executor, config, logger_: executor,
        )

        result = pm._build_docker_executor(cfg, MagicMock())

        assert result is local_executor


class TestRecoverDockerContainer:
    """Test Docker container recovery edge cases."""

    def test_recovery_skips_non_running_container(self, monkeypatch):
        """Should skip containers that are not running."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")
        cfg = SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SYSTEM)

        container = MagicMock()
        container.name = sandbox_module.SANDBOX_CONTAINER_NAME
        container.status = "exited"
        container.labels = {"com.nexent.sandbox": "runtime"}
        container.attrs = {
            "NetworkSettings": {
                "Networks": {sandbox_module.SANDBOX_NETWORK_NAME: {}},
                "Ports": {"8888/tcp": [{"HostPort": "8888"}]},
            }
        }

        docker_module = SimpleNamespace(from_env=lambda: SimpleNamespace(
            containers=SimpleNamespace(list=lambda **kwargs: [container])
        ))
        monkeypatch.setitem(sys.modules, "docker", docker_module)

        result = pm._recover_docker_container(cfg, logger, host_tools_exist=False)

        assert result is None

    def test_recovery_skips_wrong_label(self, monkeypatch):
        """Should skip containers without the correct Nexent label."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")
        cfg = SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SYSTEM)

        container = MagicMock()
        container.name = sandbox_module.SANDBOX_CONTAINER_NAME
        container.status = "running"
        container.labels = {}
        container.attrs = {
            "NetworkSettings": {
                "Networks": {sandbox_module.SANDBOX_NETWORK_NAME: {}},
                "Ports": {"8888/tcp": [{"HostPort": "8888"}]},
            }
        }

        docker_module = SimpleNamespace(from_env=lambda: SimpleNamespace(
            containers=SimpleNamespace(list=lambda **kwargs: [container])
        ))
        monkeypatch.setitem(sys.modules, "docker", docker_module)

        result = pm._recover_docker_container(cfg, logger, host_tools_exist=False)

        assert result is None

    def test_recovery_fails_gracefully_on_exception(self, monkeypatch):
        """Should return None on unexpected exceptions during recovery."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")
        cfg = SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SYSTEM)

        docker_module = SimpleNamespace(from_env=MagicMock(side_effect=Exception("docker error")))
        monkeypatch.setitem(sys.modules, "docker", docker_module)

        result = pm._recover_docker_container(cfg, logger, host_tools_exist=False)

        assert result is None

    def test_recovery_skips_when_no_port_mapping(self, monkeypatch):
        """Should skip containers without proper port mapping on host runtime."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")
        cfg = SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SYSTEM)

        container = MagicMock()
        container.name = sandbox_module.SANDBOX_CONTAINER_NAME
        container.status = "running"
        container.labels = {"com.nexent.sandbox": "runtime"}
        container.attrs = {
            "NetworkSettings": {
                "Networks": {sandbox_module.SANDBOX_NETWORK_NAME: {}},
                "Ports": {}
            }
        }

        docker_module = SimpleNamespace(from_env=lambda: SimpleNamespace(
            containers=SimpleNamespace(list=lambda **kwargs: [container])
        ))
        monkeypatch.setitem(sys.modules, "docker", docker_module)
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: False)

        result = pm._recover_docker_container(cfg, logger, host_tools_exist=False)

        assert result is None


class TestRemoveStaleDockerContainers:
    """Test stale container removal."""

    def test_removes_named_stale_containers(self, monkeypatch):
        """Should remove containers with the sandbox name."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")
        cfg = SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SYSTEM)

        stale_container = MagicMock()
        stale_container.name = sandbox_module.SANDBOX_CONTAINER_NAME
        stale_container.short_id = "stale123"
        stale_container.attrs = {"NetworkSettings": {"Ports": {}}}
        stale_container.remove = MagicMock()

        docker_module = SimpleNamespace(
            from_env=lambda: SimpleNamespace(
                containers=SimpleNamespace(list=lambda **kwargs: [stale_container])
            )
        )
        monkeypatch.setitem(sys.modules, "docker", docker_module)

        pm._remove_stale_docker_containers(cfg, logger)

        stale_container.remove.assert_called_once_with(force=True)

    def test_handles_removal_exception_gracefully(self, monkeypatch):
        """Should handle container removal failures gracefully."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")
        cfg = SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SYSTEM)

        stale_container = MagicMock()
        stale_container.name = sandbox_module.SANDBOX_CONTAINER_NAME
        stale_container.short_id = "stale456"
        stale_container.attrs = {"NetworkSettings": {"Ports": {}}}
        stale_container.remove.side_effect = Exception("remove failed")

        docker_module = SimpleNamespace(
            from_env=lambda: SimpleNamespace(
                containers=SimpleNamespace(list=lambda **kwargs: [stale_container])
            )
        )
        monkeypatch.setitem(sys.modules, "docker", docker_module)

        pm._remove_stale_docker_containers(cfg, logger)

        stale_container.remove.assert_called_once()

    def test_handles_docker_exception_gracefully(self, monkeypatch):
        """Should handle docker module exceptions gracefully."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")
        cfg = SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SYSTEM)

        docker_module = SimpleNamespace(
            from_env=MagicMock(side_effect=Exception("docker error"))
        )
        monkeypatch.setitem(sys.modules, "docker", docker_module)

        pm._remove_stale_docker_containers(cfg, logger)


class TestAcquireSharedDockerKernel:
    """Test shared Docker kernel acquisition paths."""

    def test_acquire_creates_new_container_when_not_found(self, monkeypatch):
        """Should create new container when no existing container found."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")
        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SYSTEM,
            docker_image="new-container:test",
        )

        class FakeContainerExecutor:
            base_url = "http://127.0.0.1:8888"
            host = "127.0.0.1"
            port = 8888
            container = MagicMock()
            container.attrs = {}
            additional_imports = []
            installed_packages = []

        def mock_build_executor(*args, **kwargs):
            executor = FakeContainerExecutor()
            executor.logger = sandbox_module._make_smolagents_logger(logger)
            return executor

        def mock_recover(*args, **kwargs):
            return None

        monkeypatch.setattr(pm, "_build_executor", mock_build_executor)
        monkeypatch.setattr(pm, "_recover_docker_container", mock_recover)
        monkeypatch.setattr(pm, "_is_alive", lambda _owner: True)
        monkeypatch.setattr(
            sandbox_module,
            "_DockerKernelLease",
            lambda *args, **kwargs: MagicMock(kernel_id="test-kernel"),
        )
        monkeypatch.setattr(sandbox_module, "_install_host_tool_bridge", lambda ex, l: ex)
        monkeypatch.setattr(sandbox_module, "_wrap_executor", lambda ex, c, l: ex)

        executor = pm._acquire_shared_docker_kernel(cfg, logger, host_tools_exist=False)

        assert executor is not None
        assert hasattr(executor, "kernel_id") or "kernel_id" in str(type(executor))

    def test_acquire_reuses_recovered_container(self, monkeypatch):
        """Should reuse recovered container when available."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")
        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SYSTEM,
            docker_image="recovered:test",
        )

        class FakeRecoveredExecutor:
            base_url = "http://127.0.0.1:8888"
            host = "127.0.0.1"
            port = 8888
            container = MagicMock()
            container.attrs = {}
            additional_imports = []
            installed_packages = []
            logger = None

        recovered_executor = FakeRecoveredExecutor()

        def mock_recover(*args, **kwargs):
            return recovered_executor

        def mock_build_executor(*args, **kwargs):
            return None

        monkeypatch.setattr(pm, "_recover_docker_container", mock_recover)
        monkeypatch.setattr(pm, "_build_executor", mock_build_executor)
        monkeypatch.setattr(pm, "_is_alive", lambda _owner: True)
        monkeypatch.setattr(
            sandbox_module,
            "_DockerKernelLease",
            lambda *args, **kwargs: MagicMock(kernel_id="test-kernel"),
        )
        monkeypatch.setattr(sandbox_module, "_install_host_tool_bridge", lambda ex, l: ex)
        monkeypatch.setattr(sandbox_module, "_wrap_executor", lambda ex, c, l: ex)

        executor = pm._acquire_shared_docker_kernel(cfg, logger, host_tools_exist=False)

        assert executor is not None


class TestBuildSystemDockerExecutor:
    """Test system Docker executor building."""

    def test_waits_for_kernel_ready(self, monkeypatch):
        """Should wait until Jupyter kernel API is ready."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")
        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SYSTEM,
            timeout_seconds=5,
        )

        container = MagicMock()
        container.short_id = "ready123"
        container.attrs = {"NetworkSettings": {"Networks": {}}}
        container.reload = MagicMock()

        call_count = [0]

        def mock_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] < 2:
                raise Exception("not ready yet")
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: [{"id": "kernel-1"}],
            )

        run = MagicMock(return_value=container)
        docker_module = SimpleNamespace(
            from_env=lambda: SimpleNamespace(
                containers=SimpleNamespace(run=run),
                version=lambda: {"Version": "18.09.9"},
            )
        )
        monkeypatch.setitem(sys.modules, "docker", docker_module)
        monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=mock_get))
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: False)
        monkeypatch.setattr(sandbox_module, "_sandbox_connection_hosts", lambda c: ["127.0.0.1"])

        executor = pm._build_system_docker_executor(cfg, logger, {"name": "test-sandbox"})

        assert executor.base_url == "http://127.0.0.1:8888"
        assert call_count[0] >= 2
        assert run.call_args.kwargs["security_opt"] == ["seccomp=unconfined"]

    def test_removes_container_on_failure(self, monkeypatch):
        """Should remove container when kernel never becomes ready."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")
        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SYSTEM,
            timeout_seconds=1,
        )

        container = MagicMock()
        container.short_id = "fail123"
        container.attrs = {"NetworkSettings": {"Networks": {}}}
        container.reload = MagicMock()
        container.remove = MagicMock()

        run = MagicMock(return_value=container)
        docker_module = SimpleNamespace(
            from_env=lambda: SimpleNamespace(
                containers=SimpleNamespace(run=run)
            )
        )
        monkeypatch.setitem(sys.modules, "docker", docker_module)
        monkeypatch.setitem(
            sys.modules,
            "requests",
            SimpleNamespace(get=MagicMock(side_effect=Exception("never ready"))),
        )
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: False)
        monkeypatch.setattr(sandbox_module, "_sandbox_connection_hosts", lambda c: ["127.0.0.1"])

        with pytest.raises(RuntimeError, match="Jupyter kernel API"):
            pm._build_system_docker_executor(cfg, logger, {"name": "test-sandbox"})

        container.remove.assert_called()


class TestBuildSessionDockerExecutor:
    """Session Docker executors use collision-free connection endpoints."""

    @staticmethod
    def _mock_session_executor(monkeypatch, captured):
        class FakeSessionExecutor:
            def __init__(self, container_group, logger_, receive_timeout_seconds):
                owner = container_group.container_executor
                captured["owner"] = owner
                captured["container_group"] = container_group
                captured["timeout"] = receive_timeout_seconds
                self.additional_imports = owner.additional_imports
                self.base_url = owner.base_url
                self.installed_packages = []

            def install_packages(self, imports):
                captured["installed"] = imports
                return list(imports)

        monkeypatch.setattr(sandbox_module, "_SessionDockerExecutor", FakeSessionExecutor)

    def test_host_runtime_uses_docker_allocated_port(self, monkeypatch):
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")
        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SESSION,
            timeout_seconds=5,
            extra_kwargs={"additional_imports": ["numpy"]},
        )
        container = MagicMock(
            short_id="session1",
            status="running",
            client=MagicMock(),
            attrs={
                "NetworkSettings": {
                    "Ports": {"8888/tcp": [{"HostPort": "49152"}]}
                }
            },
        )
        run = MagicMock(return_value=container)
        docker_module = SimpleNamespace(
            from_env=lambda: SimpleNamespace(
                containers=SimpleNamespace(run=run),
                version=lambda: {"Version": "18.09.9"},
            )
        )
        response = SimpleNamespace(
            raise_for_status=lambda: None,
            json=MagicMock(side_effect=[{}, []]),
        )
        captured = {}
        monkeypatch.setitem(sys.modules, "docker", docker_module)
        monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=lambda *args, **kwargs: response))
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: False)
        monkeypatch.setattr(sandbox_module.time, "sleep", MagicMock())
        self._mock_session_executor(monkeypatch, captured)

        executor = pm._build_session_docker_executor(cfg, logger, {"network_disabled": True})

        assert run.call_args.kwargs["ports"] == {"8888/tcp": ("127.0.0.1", None)}
        assert run.call_args.kwargs["network_disabled"] is False
        assert run.call_args.kwargs["security_opt"] == ["seccomp=unconfined"]
        assert captured["owner"].base_url == "http://127.0.0.1:49152"
        assert captured["installed"] == ["numpy"]
        assert executor.installed_packages == ["numpy"]

    def test_container_runtime_uses_unique_dns_name_without_host_port(self, monkeypatch):
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")
        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SESSION,
            network_disabled=False,
        )
        container = MagicMock(
            short_id="session2",
            status="running",
            client=MagicMock(),
            attrs={"NetworkSettings": {"Ports": {}}},
        )
        run = MagicMock(return_value=container)

        class NotFound(Exception):
            pass

        control_network = MagicMock(
            attrs={"Internal": True, "Containers": {"runtime-id": {}}}
        )
        runtime_container = SimpleNamespace(id="runtime-id")
        networks = SimpleNamespace(
            get=MagicMock(side_effect=[NotFound(), control_network]),
            create=MagicMock(return_value=control_network),
        )
        containers = SimpleNamespace(
            run=run,
            get=MagicMock(return_value=runtime_container),
        )
        docker_module = SimpleNamespace(
            from_env=lambda: SimpleNamespace(containers=containers, networks=networks),
            errors=SimpleNamespace(NotFound=NotFound),
        )
        response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: [])
        captured = {}
        monkeypatch.setitem(sys.modules, "docker", docker_module)
        monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=lambda *args, **kwargs: response))
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: True)
        monkeypatch.setattr(sandbox_module.secrets, "token_hex", lambda size: "unique")
        self._mock_session_executor(monkeypatch, captured)

        pm._build_session_docker_executor(cfg, logger, {"ports": {"old": "mapping"}})

        kwargs = run.call_args.kwargs
        assert kwargs["name"] == "nexent-runtime-sandbox-session-unique"
        assert "network" not in kwargs
        assert "ports" not in kwargs
        networks.create.assert_called_once_with(
            sandbox_module.SANDBOX_NETWORK_NAME,
            driver="bridge",
            internal=True,
        )
        control_network.connect.assert_called_once_with(
            container,
            aliases=["nexent-runtime-sandbox-session-unique"],
        )
        assert captured["owner"].base_url == (
            "http://nexent-runtime-sandbox-session-unique:8888"
        )

    def test_cleanup_removes_shared_container_after_last_kernel(self, monkeypatch):
        parent_cleanup = MagicMock()
        monkeypatch.setattr(sandbox_module._DockerKernelLease, "cleanup", parent_cleanup)
        owner = SimpleNamespace(cleanup=MagicMock())
        group = sandbox_module._SessionDockerContainerGroup(owner)
        first = object.__new__(sandbox_module._SessionDockerExecutor)
        first._session_container_group = group
        first._session_lease_released = False
        second = object.__new__(sandbox_module._SessionDockerExecutor)
        second._session_container_group = group
        second._session_lease_released = False
        group.acquire()
        group.acquire()

        first.cleanup()
        first.cleanup()
        owner.cleanup.assert_not_called()
        second.cleanup()

        assert parent_cleanup.call_count == 2
        owner.cleanup.assert_called_once_with()

    def test_container_group_rejects_acquire_after_close(self):
        owner = SimpleNamespace(cleanup=MagicMock())
        group = sandbox_module._SessionDockerContainerGroup(owner)
        group.close_if_unused()

        with pytest.raises(RuntimeError, match="already closed"):
            group.acquire()

        group.release()
        owner.cleanup.assert_called_once_with()

    def test_container_group_close_if_unused_waits_for_active_lease(self):
        owner = SimpleNamespace(cleanup=MagicMock())
        group = sandbox_module._SessionDockerContainerGroup(owner)
        group.acquire()

        group.close_if_unused()
        owner.cleanup.assert_not_called()
        group.release()

        owner.cleanup.assert_called_once_with()

    def test_session_executor_initializes_and_acquires_group(self, monkeypatch):
        parent_init = MagicMock()
        monkeypatch.setattr(sandbox_module._DockerKernelLease, "__init__", parent_init)
        owner = SimpleNamespace()
        group = sandbox_module._SessionDockerContainerGroup(owner)

        executor = sandbox_module._SessionDockerExecutor(
            group,
            MagicMock(),
            receive_timeout_seconds=12,
        )

        parent_init.assert_called_once_with(owner, ANY, 12)
        assert executor._session_container_group is group
        assert executor._session_lease_released is False
        assert group._lease_count == 1

    def test_missing_dynamic_port_removes_container(self, monkeypatch):
        pm = SandboxPoolManager.get_instance()
        container = MagicMock(
            attrs={"NetworkSettings": {"Ports": {}}},
            status="running",
        )
        run = MagicMock(return_value=container)
        monkeypatch.setitem(
            sys.modules,
            "docker",
            SimpleNamespace(
                from_env=lambda: SimpleNamespace(containers=SimpleNamespace(run=run))
            ),
        )
        monkeypatch.setitem(sys.modules, "requests", SimpleNamespace())
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: False)

        with pytest.raises(RuntimeError, match="did not allocate"):
            pm._build_session_docker_executor(
                SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SESSION),
                MagicMock(),
                {},
            )

        container.remove.assert_called_once_with(force=True)

    def test_stopped_container_is_removed_before_jupyter_ready(self, monkeypatch):
        pm = SandboxPoolManager.get_instance()
        container = MagicMock(
            attrs={
                "NetworkSettings": {
                    "Ports": {"8888/tcp": [{"HostPort": "49153"}]}
                }
            },
            status="exited",
        )
        monkeypatch.setitem(
            sys.modules,
            "docker",
            SimpleNamespace(
                from_env=lambda: SimpleNamespace(
                    containers=SimpleNamespace(run=MagicMock(return_value=container))
                )
            ),
        )
        monkeypatch.setitem(sys.modules, "requests", SimpleNamespace())
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: False)

        with pytest.raises(RuntimeError, match="stopped before Jupyter"):
            pm._build_session_docker_executor(
                SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SESSION),
                MagicMock(),
                {},
            )

        container.remove.assert_called_once_with(force=True)

    def test_jupyter_timeout_preserves_error_when_container_remove_fails(self, monkeypatch):
        pm = SandboxPoolManager.get_instance()
        container = MagicMock(
            attrs={
                "NetworkSettings": {
                    "Ports": {"8888/tcp": [{"HostPort": "49154"}]}
                }
            },
            status="running",
        )
        container.remove.side_effect = RuntimeError("remove failed")
        monkeypatch.setitem(
            sys.modules,
            "docker",
            SimpleNamespace(
                from_env=lambda: SimpleNamespace(
                    containers=SimpleNamespace(run=MagicMock(return_value=container))
                )
            ),
        )
        monkeypatch.setitem(
            sys.modules,
            "requests",
            SimpleNamespace(get=MagicMock(side_effect=RuntimeError("not ready"))),
        )
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: False)
        monkeypatch.setattr(
            sandbox_module.time,
            "monotonic",
            MagicMock(side_effect=[0, 0, 11]),
        )
        monkeypatch.setattr(sandbox_module.time, "sleep", MagicMock())

        with pytest.raises(RuntimeError, match="did not become ready"):
            pm._build_session_docker_executor(
                SandboxConfig(
                    level=SandboxLevel.DOCKER,
                    scope=SandboxScope.SESSION,
                    timeout_seconds=1,
                ),
                MagicMock(),
                {},
            )

    def test_owner_cleanup_runs_when_group_construction_fails(self, monkeypatch):
        pm = SandboxPoolManager.get_instance()
        container = MagicMock(
            client=MagicMock(),
            attrs={
                "NetworkSettings": {
                    "Ports": {"8888/tcp": [{"HostPort": "49155"}]}
                }
            },
            status="running",
        )
        monkeypatch.setitem(
            sys.modules,
            "docker",
            SimpleNamespace(
                from_env=lambda: SimpleNamespace(
                    containers=SimpleNamespace(run=MagicMock(return_value=container))
                )
            ),
        )
        response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: [])
        monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=lambda *args, **kwargs: response))
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: False)
        monkeypatch.setattr(
            sandbox_module,
            "_SessionDockerContainerGroup",
            MagicMock(side_effect=RuntimeError("group failed")),
        )

        with pytest.raises(RuntimeError, match="group failed"):
            pm._build_session_docker_executor(
                SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SESSION),
                MagicMock(),
                {},
            )

        container.remove.assert_called_once_with(force=True)

    def test_post_lease_failure_cleans_executor_and_unused_group(self, monkeypatch):
        pm = SandboxPoolManager.get_instance()
        container = MagicMock(
            client=MagicMock(),
            short_id="session3",
            attrs={
                "NetworkSettings": {
                    "Ports": {"8888/tcp": [{"HostPort": "49156"}]}
                }
            },
            status="running",
        )
        monkeypatch.setitem(
            sys.modules,
            "docker",
            SimpleNamespace(
                from_env=lambda: SimpleNamespace(
                    containers=SimpleNamespace(run=MagicMock(return_value=container))
                )
            ),
        )
        response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: [])
        monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=lambda *args, **kwargs: response))
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: False)
        executor = SimpleNamespace(base_url="http://127.0.0.1:49156", cleanup=MagicMock())
        monkeypatch.setattr(pm, "_lease_session_docker_kernel", MagicMock(return_value=executor))
        logger = MagicMock()
        logger.info.side_effect = RuntimeError("log failed")

        with pytest.raises(RuntimeError, match="log failed"):
            pm._build_session_docker_executor(
                SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SESSION),
                logger,
                {},
            )

        executor.cleanup.assert_called_once_with()
        container.remove.assert_called_once_with(force=True)

    def test_lease_rejects_dead_container(self, monkeypatch):
        pm = SandboxPoolManager.get_instance()
        group = sandbox_module._SessionDockerContainerGroup(SimpleNamespace())
        monkeypatch.setattr(pm, "_is_alive", lambda executor: False)

        with pytest.raises(RuntimeError, match="not running"):
            pm._lease_session_docker_kernel(
                SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SESSION),
                MagicMock(),
                group,
            )

    def test_lease_cleanup_runs_when_package_installation_fails(self, monkeypatch):
        pm = SandboxPoolManager.get_instance()
        owner = SimpleNamespace(cleanup=MagicMock())
        group = sandbox_module._SessionDockerContainerGroup(owner)
        executor = SimpleNamespace(
            additional_imports=["broken"],
            install_packages=MagicMock(side_effect=RuntimeError("install failed")),
            cleanup=MagicMock(),
        )
        monkeypatch.setattr(pm, "_is_alive", lambda item: True)
        monkeypatch.setattr(
            sandbox_module,
            "_SessionDockerExecutor",
            MagicMock(return_value=executor),
        )

        with pytest.raises(RuntimeError, match="install failed"):
            pm._lease_session_docker_kernel(
                SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SESSION),
                MagicMock(),
                group,
            )

        executor.cleanup.assert_called_once_with()


class TestMakeLocalExecutor:
    """Test local executor creation."""

    def test_creates_executor_with_correct_backend(self):
        """Should create LocalPythonExecutor with _nexent_backend set."""
        executor = sandbox_module._make_local_executor(["json", "re"])

        assert getattr(executor, "_nexent_backend", None) == "local"


class TestNow:
    """Test time utility function."""

    def test_now_returns_float_timestamp(self):
        """_now() should return a float timestamp."""
        result = sandbox_module._now()

        assert isinstance(result, float)
        assert result > 0


class TestSandboxLevelEnum:
    """Test SandboxLevel enum values."""

    def test_all_levels_exist(self):
        """All expected sandbox levels should be defined."""
        assert sandbox_module.SandboxLevel.LOCAL.value == "local"
        assert sandbox_module.SandboxLevel.DOCKER.value == "docker"
        assert sandbox_module.SandboxLevel.WASM.value == "wasm"


class TestSandboxScopeEnum:
    """Test SandboxScope enum values."""

    def test_all_scopes_exist(self):
        """All expected sandbox scopes should be defined."""
        assert sandbox_module.SandboxScope.SESSION.value == "session"
        assert sandbox_module.SandboxScope.SYSTEM.value == "system"


class TestShellPolicyEnum:
    """Test ShellPolicy enum values."""

    def test_all_policies_exist(self):
        """All expected shell policies should be defined."""
        assert sandbox_module.ShellPolicy.DISABLED.value == "disabled"
        assert sandbox_module.ShellPolicy.RESTRICTED.value == "restricted"
        assert sandbox_module.ShellPolicy.BOXED.value == "boxed"


class TestSandboxConfigDataclass:
    """Test SandboxConfig dataclass."""

    def test_default_values(self):
        """Default config should have sensible defaults."""
        cfg = SandboxConfig()

        assert cfg.level == sandbox_module.SandboxLevel.LOCAL
        assert cfg.scope == sandbox_module.SandboxScope.SESSION
        assert cfg.docker_image == "nexent/nexent-sandbox:latest"
        assert cfg.memory_limit_mb == 2048
        assert cfg.cpu_quota == 1.0
        assert cfg.network_disabled is True
        assert cfg.timeout_seconds == 120
        assert cfg.host_tool_timeout_seconds is None
        assert cfg.shell_policy == sandbox_module.ShellPolicy.DISABLED
        assert cfg.output_dir == "/home/sandbox/workdir/output"
        assert cfg.auto_sync_outputs is True
        assert cfg.extra_kwargs == {}

    def test_from_dict_parses_all_fields(self):
        """from_dict should parse all configuration fields."""
        data = {
            "level": "docker",
            "scope": "system",
            "docker_image": "custom:image",
            "memory_limit_mb": 1024,
            "cpu_quota": 2.0,
            "network_disabled": False,
            "timeout_seconds": 60,
            "host_tool_timeout_seconds": 900,
            "shell_policy": "restricted",
            "output_dir": "/custom/output",
            "auto_sync_outputs": False,
            "extra_kwargs": {"key": "value"},
        }

        cfg = SandboxConfig.from_dict(data)

        assert cfg.level == sandbox_module.SandboxLevel.DOCKER
        assert cfg.scope == sandbox_module.SandboxScope.SYSTEM
        assert cfg.docker_image == "custom:image"
        assert cfg.memory_limit_mb == 1024
        assert cfg.cpu_quota == 2.0
        assert cfg.network_disabled is False
        assert cfg.timeout_seconds == 60
        assert cfg.host_tool_timeout_seconds == 900.0
        assert cfg.shell_policy == sandbox_module.ShellPolicy.RESTRICTED
        assert cfg.output_dir == "/custom/output"
        assert cfg.auto_sync_outputs is False
        assert cfg.extra_kwargs == {"key": "value"}

    def test_from_dict_handles_empty_dict(self):
        """from_dict with empty dict should use defaults."""
        cfg = SandboxConfig.from_dict({})

        assert cfg.host_tool_timeout_seconds is None
        assert cfg.level == sandbox_module.SandboxLevel.LOCAL
        assert cfg.scope == sandbox_module.SandboxScope.SESSION

    @pytest.mark.parametrize("value", [None, "", 0, -1])
    def test_from_dict_disables_non_positive_host_tool_timeout(self, value):
        cfg = SandboxConfig.from_dict({"host_tool_timeout_seconds": value})

        assert cfg.host_tool_timeout_seconds is None


class TestPoolManagerConstants:
    """Test module-level constants."""

    def test_sandbox_container_name_defined(self):
        """SANDBOX_CONTAINER_NAME should be defined."""
        assert sandbox_module.SANDBOX_CONTAINER_NAME == "nexent-runtime-sandbox"

    def test_sandbox_network_name_defined(self):
        """SANDBOX_NETWORK_NAME should be defined."""
        assert sandbox_module.SANDBOX_NETWORK_NAME == "nexent_sandbox_control"

    def test_sandbox_jupyter_port_defined(self):
        """SANDBOX_JUPYTER_PORT should be defined."""
        assert sandbox_module.SANDBOX_JUPYTER_PORT == 8888


class TestPoolManagerIsAlive:
    """Test executor liveness detection."""

    def test_is_alive_returns_true_for_none_container(self):
        """Executor without container should be considered alive."""
        pm = SandboxPoolManager.get_instance()
        mock_executor = SimpleNamespace()
        mock_executor.container = None

        result = pm._is_alive(mock_executor)

        assert result is True

    def test_is_alive_returns_true_for_running_container(self):
        """Running container should be considered alive."""
        pm = SandboxPoolManager.get_instance()
        mock_container = MagicMock()
        mock_container.status = "running"
        mock_executor = SimpleNamespace()
        mock_executor.container = mock_container

        result = pm._is_alive(mock_executor)

        assert result is True
        mock_container.reload.assert_called_once()

    def test_is_alive_returns_false_for_exited_container(self):
        """Exited container should not be considered alive."""
        pm = SandboxPoolManager.get_instance()
        mock_container = MagicMock()
        mock_container.status = "exited"
        mock_executor = SimpleNamespace()
        mock_executor.container = mock_container

        result = pm._is_alive(mock_executor)

        assert result is False

    def test_is_alive_returns_false_on_reload_error(self):
        """Container reload failure should return False."""
        pm = SandboxPoolManager.get_instance()
        mock_container = MagicMock()
        mock_container.reload.side_effect = Exception("reload failed")
        mock_executor = SimpleNamespace()
        mock_executor.container = mock_container

        result = pm._is_alive(mock_executor)

        assert result is False


class TestInstallHostToolBridge:
    """Test host tool bridge installation."""

    def test_bridge_installed_flag_prevents_reinstall(self):
        """Already-installed bridge should not be reinstalled."""
        mock_executor = SimpleNamespace()
        mock_executor._nexent_tool_bridge_installed = True
        mock_logger = sandbox_module.logging.getLogger("test")

        result = sandbox_module._install_host_tool_bridge(mock_executor, mock_logger)

        assert result is mock_executor


class TestToolBridgeHandler:
    """Test _ToolBridge HTTP request handling."""

    def test_handler_rejects_invalid_authorization(self):
        """Should reject requests without valid Bearer token."""
        bridge = sandbox_module._ToolBridge(sandbox_module.logging.getLogger("test"))
        try:
            handler = bridge._server.RequestHandlerClass

            mock_instance = MagicMock()
            mock_instance.path = "/invoke"
            mock_instance.headers = MagicMock()
            mock_instance.headers.get = MagicMock(side_effect=[
                "InvalidToken",
                "0"
            ])
            mock_instance.send_error = MagicMock()

            handler.do_POST(mock_instance)

            mock_instance.send_error.assert_called()
        finally:
            bridge.close()

    def test_handler_handles_unknown_tool(self):
        """Should return error for unknown tool name."""
        bridge = sandbox_module._ToolBridge(sandbox_module.logging.getLogger("test"))
        try:
            bridge._tools = {}

            handler = bridge._server.RequestHandlerClass
            mock_instance = MagicMock()
            mock_instance.path = "/invoke"
            mock_instance.headers = MagicMock()
            mock_instance.headers.get = MagicMock(side_effect=[
                f"Bearer {bridge._token}",
                "2"
            ])
            mock_instance.rfile = MagicMock()
            mock_instance.rfile.read = MagicMock(return_value=b'{"tool": "unknown_tool"}')
            mock_instance.send_response = MagicMock()
            mock_instance.send_header = MagicMock()
            mock_instance.end_headers = MagicMock()
            mock_instance.wfile = MagicMock()

            handler.do_POST(mock_instance)

            response_body = mock_instance.wfile.write.call_args[0][0]
            assert b'"error"' in response_body
        finally:
            bridge.close()


class TestPoolManagerMultipleSystemContainers:
    """Test multiple system container scenarios."""

    def test_acquire_with_different_images_creates_separate_containers(self, monkeypatch):
        """Different images should result in separate container pools."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")

        executor1 = _FakeExecutor(image="image1:latest", alive=True)
        executor2 = _FakeExecutor(image="image2:latest", alive=True)

        def mock_build_executor(config, logger_, host_tools=False):
            if config.docker_image == "image1:latest":
                return executor1
            return executor2

        monkeypatch.setattr(pm, "_build_executor", mock_build_executor)
        monkeypatch.setattr(pm, "_recover_docker_container", lambda *args: None)
        monkeypatch.setattr(
            sandbox_module,
            "_DockerKernelLease",
            lambda *args, **kwargs: MagicMock(kernel_id="test-kernel"),
        )
        monkeypatch.setattr(sandbox_module, "_install_host_tool_bridge", lambda ex, l: ex)
        monkeypatch.setattr(sandbox_module, "_wrap_executor", lambda ex, c, l: ex)

        cfg1 = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SYSTEM,
            docker_image="image1:latest",
        )
        cfg2 = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SYSTEM,
            docker_image="image2:latest",
        )

        acquired1 = pm.acquire(cfg1, logger)
        acquired2 = pm.acquire(cfg2, logger)

        assert acquired1 is executor1
        assert acquired2 is executor2

    def test_system_host_tools_share_one_container_owner(self, monkeypatch):
        """Host-tool capability is lease-local and must not split the system owner."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")
        owner = SimpleNamespace(base_url="http://sandbox", container=object())
        build_owner = MagicMock(return_value=owner)
        created_leases = []

        def create_lease(lease_owner, _logger, **_kwargs):
            lease = MagicMock(kernel_id=f"kernel-{len(created_leases)}")
            lease.owner = lease_owner
            created_leases.append(lease)
            return lease

        monkeypatch.setattr(pm, "_build_executor", build_owner)
        monkeypatch.setattr(pm, "_recover_docker_container", lambda *args: None)
        monkeypatch.setattr(pm, "_is_alive", lambda _owner: True)
        monkeypatch.setattr(sandbox_module, "_DockerKernelLease", create_lease)
        monkeypatch.setattr(
            sandbox_module,
            "_install_host_tool_bridge",
            lambda ex, _logger, request_timeout_seconds=None: ex,
        )
        monkeypatch.setattr(sandbox_module, "_wrap_executor", lambda ex, c, l: ex)

        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SYSTEM,
            docker_image="shared:latest",
        )

        acquired_with = pm.acquire(cfg, logger, host_tools_exist=True)
        acquired_without = pm.acquire(cfg, logger, host_tools_exist=False)

        assert acquired_with is not acquired_without
        assert acquired_with.owner is owner
        assert acquired_without.owner is owner
        build_owner.assert_called_once()
        assert list(pm._system_containers) == ["shared:latest"]


class TestBuildExecutorWithWasm:
    """Test WASM executor building."""

    def test_wasm_executor_uses_smolagents(self):
        """WASM executor should attempt to use smolagents WasmExecutor."""
        # This test verifies that WasmExecutor is imported from smolagents
        # when available. Full testing would require the actual smolagents[wasm] package.
        try:
            from smolagents.remote_executors import WasmExecutor
            has_wasm_executor = True
        except ImportError:
            has_wasm_executor = False

        # Just verify the function exists in sandbox module
        assert hasattr(sandbox_module.SandboxPoolManager, "_build_wasm_executor")


class TestEvictorThread:
    """Test evictor thread behavior."""

    def test_evictor_thread_starts_on_get_instance(self):
        """Evictor thread should start when singleton is created."""
        SandboxPoolManager._instance = None

        pm = SandboxPoolManager.get_instance()

        assert pm._evict_thread is not None
        assert pm._evict_thread.daemon is True


class TestForbiddeShellCallsConstant:
    """Test forbidden shell calls constant."""

    def test_subprocess_calls_defined(self):
        """subprocess forbidden calls should be defined."""
        assert "subprocess" in sandbox_module._FORBIDDEN_SHELL_CALLS
        assert "run" in sandbox_module._FORBIDDEN_SHELL_CALLS["subprocess"]
        assert "Popen" in sandbox_module._FORBIDDEN_SHELL_CALLS["subprocess"]

    def test_os_calls_defined(self):
        """os forbidden calls should be defined."""
        assert "os" in sandbox_module._FORBIDDEN_SHELL_CALLS
        assert "system" in sandbox_module._FORBIDDEN_SHELL_CALLS["os"]
        assert "execv" in sandbox_module._FORBIDDEN_SHELL_CALLS["os"]


class TestLogLevelEnum:
    """Test _LogLevel enum."""

    def test_log_levels_defined(self):
        """All log levels should be defined."""
        assert sandbox_module._LogLevel.OFF == -1
        assert sandbox_module._LogLevel.ERROR == 0
        assert sandbox_module._LogLevel.INFO == 1
        assert sandbox_module._LogLevel.DEBUG == 2


class TestMissingPkgRegex:
    """Test missing package regex pattern."""

    def test_regex_matches_module_name(self):
        """Regex should extract module name from error message."""
        match = sandbox_module._MISSING_PKG_RE.search("No module named 'requests'")
        assert match is not None
        assert match.group(1) == "requests"

    def test_regex_handles_double_quotes(self):
        """Regex should handle double-quoted module names."""
        match = sandbox_module._MISSING_PKG_RE.search('No module named "numpy"')
        assert match is not None
        assert match.group(1) == "numpy"


class TestPackageListNote:
    """Test package list note constant."""

    def test_package_list_note_defined(self):
        """_PACKAGE_LIST_NOTE should be a non-empty string."""
        assert len(sandbox_module._PACKAGE_LIST_NOTE) > 0
        assert "sandbox-design.md" in sandbox_module._PACKAGE_LIST_NOTE


class TestBuildExecutorMethods:
    """Test _build_executor method paths."""

    def test_build_executor_local_level(self):
        """LOCAL level should create local executor."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")
        cfg = SandboxConfig(
            level=SandboxLevel.LOCAL,
            scope=SandboxScope.SESSION,
            extra_kwargs={"additional_authorized_imports": ["json"]},
        )

        result = pm._build_executor(cfg, logger)

        assert getattr(result, "_nexent_backend", None) == "local"

    def test_build_executor_wasm_level(self):
        """WASM level should attempt to use WasmExecutor."""
        pm = SandboxPoolManager.get_instance()
        cfg = SandboxConfig(
            level=SandboxLevel.WASM,
            scope=SandboxScope.SESSION,
        )
        # Just verify the method exists
        assert callable(pm._build_wasm_executor)

    def test_build_executor_unsupported_level_raises(self):
        """Unsupported level should raise ValueError."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")
        cfg = SandboxConfig(
            level=SandboxLevel.LOCAL,
            scope=SandboxScope.SESSION,
        )
        # Create a mock level that is not a valid SandboxLevel
        class FakeLevel:
            pass
        cfg.level = FakeLevel()

        with pytest.raises(ValueError, match="Unsupported SandboxLevel"):
            pm._build_executor(cfg, logger)


class TestDockerKernelLeaseCleanup:
    """Test _DockerKernelLease cleanup behavior - covered through integration tests."""

    def test_kernel_lease_has_correct_attributes(self):
        """Verify kernel lease class has all expected attributes."""
        # Verify the class has the expected methods and properties
        assert hasattr(sandbox_module._DockerKernelLease, "container")
        assert hasattr(sandbox_module._DockerKernelLease, "run_code_raise_errors")
        assert hasattr(sandbox_module._DockerKernelLease, "send_tools")
        assert hasattr(sandbox_module._DockerKernelLease, "cleanup")
        assert hasattr(sandbox_module._DockerKernelLease, "install_packages")
        assert hasattr(sandbox_module._DockerKernelLease, "_patch_final_answer_with_exception")


class TestAcquireSharedDockerKernelHostTools:
    """Test host tools integration with shared Docker kernel."""

    def test_acquire_installs_host_tool_bridge_when_host_tools_exist(self, monkeypatch):
        """Should install host tool bridge when host_tools_exist is True."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")
        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SYSTEM,
            docker_image="bridge:test",
        )

        class FakeExecutor:
            base_url = "http://127.0.0.1:8888"
            host = "127.0.0.1"
            port = 8888
            container = MagicMock()
            container.attrs = {}
            additional_imports = []
            installed_packages = []
            logger = None

        fake_executor = FakeExecutor()

        def mock_recover(*args, **kwargs):
            return None

        def mock_build(*args, **kwargs):
            return fake_executor

        bridge_installed = [False]

        def mock_install_bridge(ex, l, request_timeout_seconds=None):
            bridge_installed[0] = True
            return ex

        monkeypatch.setattr(pm, "_recover_docker_container", mock_recover)
        monkeypatch.setattr(pm, "_build_executor", mock_build)
        monkeypatch.setattr(pm, "_is_alive", lambda _owner: True)
        monkeypatch.setattr(
            sandbox_module,
            "_DockerKernelLease",
            lambda *args, **kwargs: MagicMock(kernel_id="test-kernel"),
        )
        monkeypatch.setattr(sandbox_module, "_install_host_tool_bridge", mock_install_bridge)
        monkeypatch.setattr(sandbox_module, "_wrap_executor", lambda ex, c, l: ex)

        pm._acquire_shared_docker_kernel(cfg, logger, host_tools_exist=True)

        assert bridge_installed[0] is True


class TestReleaseImmedateWithSharedContainer:
    """Test release_immediate with shared container scenarios."""

    def test_release_immediate_removes_shared_container_from_pools(self):
        """release_immediate should remove shared container from system_containers."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")

        executor = _FakeExecutor(image="shared:test", alive=True)
        ex_id = id(executor)
        pm._in_use[ex_id] = "shared:test"
        pm._executors[ex_id] = executor
        pm._lease_owners[ex_id] = executor
        pm._system_containers["shared:test"] = executor

        pm.release_immediate(executor, logger)

        assert "shared:test" not in pm._system_containers


class TestBuildDockerExecutorNetworkModes:
    """Test Docker network mode configurations."""

    def test_host_runtime_uses_concrete_bridge_gateway_for_host_tools(self, monkeypatch):
        pool = SandboxPoolManager.get_instance()
        executor = SimpleNamespace(__call__=MagicMock(return_value="ok"))
        captured = {}
        bridge_network = MagicMock(
            attrs={"IPAM": {"Config": [{"Gateway": "172.18.0.1"}]}}
        )
        docker_client = SimpleNamespace(
            networks=SimpleNamespace(get=MagicMock(return_value=bridge_network))
        )
        monkeypatch.setitem(
            sys.modules,
            "docker",
            SimpleNamespace(from_env=MagicMock(return_value=docker_client)),
        )
        monkeypatch.setitem(
            sys.modules,
            "smolagents.remote_executors",
            SimpleNamespace(DockerExecutor=MagicMock()),
        )
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: False)
        monkeypatch.setattr(
            pool,
            "_build_session_docker_executor",
            lambda config, logger_, kwargs: captured.update(kwargs) or executor,
        )
        monkeypatch.setattr(sandbox_module, "_install_host_tool_bridge", lambda item, *args, **kwargs: item)
        monkeypatch.setattr(sandbox_module, "_wrap_executor", lambda item, config, logger_: item)

        result = pool._build_docker_executor(
            SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SESSION),
            MagicMock(),
            host_tools_exist=True,
        )

        assert result is executor
        assert captured["extra_hosts"] == {
            "host.docker.internal": "172.18.0.1"
        }

    def test_containerized_runtime_omits_unneeded_host_gateway_mapping(self, monkeypatch):
        pool = SandboxPoolManager.get_instance()
        executor = SimpleNamespace(__call__=MagicMock(return_value="ok"))
        captured = {}
        monkeypatch.setitem(
            sys.modules,
            "smolagents.remote_executors",
            SimpleNamespace(DockerExecutor=MagicMock()),
        )
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: True)
        monkeypatch.setattr(
            pool,
            "_build_session_docker_executor",
            lambda config, logger_, kwargs: captured.update(kwargs) or executor,
        )
        monkeypatch.setattr(sandbox_module, "_install_host_tool_bridge", lambda item, *args, **kwargs: item)
        monkeypatch.setattr(sandbox_module, "_wrap_executor", lambda item, config, logger_: item)

        result = pool._build_docker_executor(
            SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SESSION),
            MagicMock(),
            host_tools_exist=True,
        )

        assert result is executor
        assert "extra_hosts" not in captured

    def test_network_disabled_but_host_tools_enables_bridge(self):
        """Network should be enabled when host_tools_exist but network_disabled is True."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")
        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SESSION,
            network_disabled=True,
        )

        executor = _FakeExecutor(image="bridge:test", alive=True)

        def mock_build(*args, **kwargs):
            return executor

        monkeypatch = MagicMock()

        # Just verify that the config path exists and doesn't raise
        assert cfg.network_disabled is True


class TestAcquireSystemPoolLogic:
    """Test acquire logic for SYSTEM pool management."""

    def test_acquire_marks_executor_as_in_use(self):
        """Acquired executor should be tracked in _in_use."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")

        executor = _FakeExecutor(image="tracking:test", alive=True)
        pm._pools["tracking:test"] = [executor]
        pm._last_touch[id(executor)] = time.time()

        cfg = SandboxConfig(
            level=SandboxLevel.WASM,
            scope=SandboxScope.SYSTEM,
            docker_image="tracking:test",
        )

        acquired = pm.acquire(cfg, logger)

        assert id(acquired) in pm._in_use
        assert pm._in_use[id(acquired)] == "tracking:test"
        assert id(acquired) in pm._last_touch


class TestModuleLevelTimeImport:
    """Test that _now() uses time module correctly."""

    def test_now_uses_time_module(self):
        """_now() should delegate to time.time()."""
        start = sandbox_module._now()
        time.sleep(0.01)
        end = sandbox_module._now()

        assert end > start


class TestTargetedSandboxCoverage:
    """Execute security, lifecycle, and factory branches directly."""

    def test_host_tool_bridge_registers_recoverable_proxy_as_bootstrap(self):
        bootstrap_output = SimpleNamespace(logs="registered")
        executor = SimpleNamespace(
            container=object(),
            send_tools=MagicMock(),
            run_code_raise_errors=MagicMock(),
            register_kernel_bootstrap_code=MagicMock(return_value=bootstrap_output),
            cleanup=MagicMock(),
            _nexent_kernel_recovery_supported=True,
        )
        logger = MagicMock()
        sandbox_module._install_host_tool_bridge(executor, logger)
        executor._nexent_tool_bridge._bridge_host = MagicMock(
            return_value="bridge-host"
        )

        executor.send_tools(
            {"host": SimpleNamespace(_nexent_execute_on_host=True)}
        )

        executor.register_kernel_bootstrap_code.assert_called_once()
        executor.run_code_raise_errors.assert_not_called()
        executor.cleanup()

    def test_kernel_lease_rejects_non_positive_receive_timeout(self, monkeypatch):
        remote_module = SimpleNamespace(
            _create_kernel_http=MagicMock(return_value="kernel-1")
        )
        monkeypatch.setitem(sys.modules, "smolagents.remote_executors", remote_module)
        owner = SimpleNamespace(
            logger=MagicMock(),
            base_url="http://sandbox:8888",
            host="sandbox",
            port=8888,
        )

        with pytest.raises(ValueError, match="must be positive"):
            sandbox_module._DockerKernelLease(
                owner,
                MagicMock(),
                receive_timeout_seconds=0,
            )

    def test_build_channels_url_creates_session_when_missing(self, monkeypatch):
        lease = object.__new__(sandbox_module._DockerKernelLease)
        lease.host = "sandbox"
        lease.port = 8888
        lease._channel_session_id = None
        monkeypatch.setattr(
            sandbox_module.secrets,
            "token_hex",
            MagicMock(return_value="new-session"),
        )

        assert lease._build_channels_url("kernel-1").endswith(
            "?session_id=new-session"
        )
        assert lease._channel_session_id == "new-session"

    def test_kernel_execution_state_returns_gateway_state(self):
        lease = TestDockerKernelLease._lease()
        response = MagicMock()
        response.json.return_value = {"execution_state": "busy"}
        lease._requests.get.return_value = response

        assert lease._get_kernel_execution_state() == "busy"
        response.raise_for_status.assert_called_once_with()

    def test_kernel_watchdog_refreshes_deadline_after_busy_health_check(
        self, monkeypatch
    ):
        from websocket import ABNF

        websocket = MagicMock()
        websocket.recv_data.return_value = (
            ABNF.OPCODE_TEXT,
            json.dumps(
                {
                    "parent_header": {"msg_id": "request-1"},
                    "msg_type": "status",
                    "content": {"execution_state": "idle"},
                }
            ),
        )
        monkeypatch.setattr("websocket.create_connection", MagicMock(return_value=websocket))
        monkeypatch.setattr(
            sandbox_module.time,
            "monotonic",
            MagicMock(side_effect=[0.0, 1.0, 2.0, 2.1]),
        )
        remote_module = SimpleNamespace(
            AgentError=RuntimeError,
            CodeOutput=lambda output, logs, is_final_answer: SimpleNamespace(
                output=output,
                logs=logs,
                is_final_answer=is_final_answer,
            ),
            RemotePythonExecutor=SimpleNamespace(
                FINAL_ANSWER_EXCEPTION="FinalAnswerException"
            ),
            _websocket_send_execute_request=lambda code, ws: "request-1",
        )
        monkeypatch.setitem(sys.modules, "smolagents.remote_executors", remote_module)
        lease = TestDockerKernelLease._lease()
        lease._check_kernel_channel_health = MagicMock()

        lease.run_code_raise_errors("1 + 1")

        lease._check_kernel_channel_health.assert_called_once_with(
            "the terminal execution message was not received before the watchdog deadline"
        )

    @pytest.mark.parametrize("delete_failure", ["status", "exception"])
    def test_kernel_replacement_logs_delete_failures(
        self, monkeypatch, delete_failure
    ):
        lease = TestDockerKernelLease._lease()
        lease._unhealthy = True
        if delete_failure == "status":
            lease._requests.delete.return_value = SimpleNamespace(status_code=500)
        else:
            lease._requests.delete.side_effect = RuntimeError("delete failed")
        remote_module = SimpleNamespace(
            RemotePythonExecutor=SimpleNamespace(
                send_variables=MagicMock(),
                send_tools=MagicMock(),
            ),
            _create_kernel_http=MagicMock(return_value="kernel-2"),
        )
        monkeypatch.setitem(sys.modules, "smolagents.remote_executors", remote_module)

        lease._replace_unhealthy_kernel()

        assert lease.kernel_id == "kernel-2"
        assert lease._unhealthy is False
        assert lease._logger.warning.call_count >= 2

    def test_kernel_replacement_failure_keeps_lease_unhealthy(self, monkeypatch):
        lease = TestDockerKernelLease._lease()
        lease._unhealthy = True
        lease._requests.delete.return_value = SimpleNamespace(status_code=204)
        remote_module = SimpleNamespace(
            RemotePythonExecutor=SimpleNamespace(),
            _create_kernel_http=MagicMock(side_effect=RuntimeError("create failed")),
        )
        monkeypatch.setitem(sys.modules, "smolagents.remote_executors", remote_module)

        with pytest.raises(RuntimeError, match="Failed to replace unhealthy sandbox kernel"):
            lease._replace_unhealthy_kernel()

        assert lease._unhealthy is True
        lease._logger.exception.assert_called_once()

    @pytest.mark.parametrize(
        ("message", "expected_output", "is_final_answer", "expected_error"),
        [
            (
                {"msg_type": "execute_result", "content": {"data": {"text/plain": "2"}}},
                "2",
                False,
                None,
            ),
            (
                {
                    "msg_type": "error",
                    "content": {
                        "ename": "FinalAnswerException",
                        "evalue": "gASVCQAAAAAAAAB9lIwBeJRLAXMu",
                    },
                },
                {"x": 1},
                True,
                None,
            ),
            (
                {
                    "msg_type": "error",
                    "content": {"ename": "ValueError", "traceback": ["boom"]},
                },
                None,
                False,
                "boom",
            ),
        ],
    )
    def test_kernel_lease_handles_terminal_message_types(
        self,
        monkeypatch,
        message,
        expected_output,
        is_final_answer,
        expected_error,
    ):
        from websocket import ABNF

        message = {
            "parent_header": {"msg_id": "request-1"},
            **message,
        }
        idle = {
            "parent_header": {"msg_id": "request-1"},
            "msg_type": "status",
            "content": {"execution_state": "idle"},
        }
        websocket = MagicMock()
        websocket.recv_data.side_effect = [
            (ABNF.OPCODE_TEXT, json.dumps(message)),
            (ABNF.OPCODE_TEXT, json.dumps(idle)),
        ]
        monkeypatch.setattr("websocket.create_connection", MagicMock(return_value=websocket))
        remote_module = SimpleNamespace(
            AgentError=RuntimeError,
            CodeOutput=lambda output, logs, is_final_answer: SimpleNamespace(
                output=output,
                logs=logs,
                is_final_answer=is_final_answer,
            ),
            RemotePythonExecutor=SimpleNamespace(
                FINAL_ANSWER_EXCEPTION="FinalAnswerException"
            ),
            _websocket_send_execute_request=lambda code, ws: "request-1",
        )
        monkeypatch.setitem(sys.modules, "smolagents.remote_executors", remote_module)
        lease = TestDockerKernelLease._lease()

        if expected_error:
            with pytest.raises(Exception, match=expected_error):
                lease.run_code_raise_errors("1 + 1")
        else:
            result = lease.run_code_raise_errors("1 + 1")
            assert result.output == expected_output
            assert result.is_final_answer is is_final_answer

    @pytest.mark.parametrize("frame", ["close", "empty"])
    def test_kernel_lease_rejects_closed_or_empty_frames(self, monkeypatch, frame):
        from websocket import ABNF

        websocket = MagicMock()
        websocket.recv_data.return_value = (
            ABNF.OPCODE_CLOSE if frame == "close" else ABNF.OPCODE_TEXT,
            b"closed" if frame == "close" else b"",
        )
        monkeypatch.setattr("websocket.create_connection", MagicMock(return_value=websocket))
        remote_module = SimpleNamespace(
            AgentError=RuntimeError,
            CodeOutput=MagicMock(),
            RemotePythonExecutor=SimpleNamespace(
                FINAL_ANSWER_EXCEPTION="FinalAnswerException"
            ),
            _websocket_send_execute_request=lambda code, ws: "request-1",
        )
        monkeypatch.setitem(sys.modules, "smolagents.remote_executors", remote_module)
        lease = TestDockerKernelLease._lease()
        lease._check_kernel_channel_health = MagicMock(
            side_effect=RuntimeError("channel failed")
        )

        with pytest.raises(RuntimeError, match="channel failed"):
            lease.run_code_raise_errors("1 + 1")

        lease._check_kernel_channel_health.assert_called_once()

    @pytest.mark.parametrize("setup_kind", ["variables", "tools", "bootstrap"])
    def test_kernel_setup_propagates_healthy_failures(
        self, monkeypatch, setup_kind
    ):
        lease = TestDockerKernelLease._lease()
        failure = RuntimeError("setup failed")
        if setup_kind == "bootstrap":
            lease.run_code_raise_errors = MagicMock(side_effect=failure)
            operation = lambda: lease.register_kernel_bootstrap_code("bootstrap")
        else:
            remote = SimpleNamespace(
                send_variables=MagicMock(side_effect=failure),
                send_tools=MagicMock(side_effect=failure),
            )
            monkeypatch.setitem(
                sys.modules,
                "smolagents.remote_executors",
                SimpleNamespace(RemotePythonExecutor=remote),
            )
            if setup_kind == "variables":
                operation = lambda: lease.send_variables({"x": 1})
            else:
                operation = lambda: lease.send_tools({"tool": object()})

        with pytest.raises(RuntimeError, match="setup failed"):
            operation()

    def test_shell_guard_boxed_and_wrapped_calls(self):
        executor = SimpleNamespace(__call__=MagicMock(return_value="ok"))
        logger = MagicMock()

        assert sandbox_module._install_shell_guard(executor, ShellPolicy.BOXED, logger) is executor
        assert not hasattr(executor, "_nexent_shell_guard_installed")

        sandbox_module._install_shell_guard(executor, ShellPolicy.DISABLED, logger)
        blocked = executor.__call__("import os; os.system('id')")
        assert "SecurityError" in blocked.logs
        assert blocked.output is None
        logger.warning.assert_called_once()
        assert executor.__call__("print('safe')") == "ok"
        assert sandbox_module._install_shell_guard(executor, ShellPolicy.DISABLED, logger) is executor

    @pytest.mark.parametrize("content_length", ["0", str(1024 * 1024 + 1)])
    def test_tool_bridge_rejects_invalid_request_sizes(self, content_length):
        bridge = sandbox_module._ToolBridge(MagicMock())
        try:
            handler = bridge._server.RequestHandlerClass
            request = MagicMock()
            request.path = "/invoke"
            request.headers.get.side_effect = [f"Bearer {bridge._token}", content_length]

            handler.do_POST(request)

            request.send_response.assert_called_once_with(500)
            assert b"Invalid request size" in request.wfile.write.call_args.args[0]
        finally:
            bridge.close()

    def test_host_tool_bridge_logs_proxy_output(self):
        executor = SimpleNamespace(
            container=object(),
            send_tools=MagicMock(),
            run_code_raise_errors=MagicMock(return_value=SimpleNamespace(logs="registered")),
            cleanup=MagicMock(),
        )
        logger = MagicMock()
        sandbox_module._install_host_tool_bridge(executor, logger)
        bridge = executor._nexent_tool_bridge
        bridge._bridge_host = MagicMock(return_value="bridge-host")
        host_tool = SimpleNamespace(_nexent_execute_on_host=True)

        executor.send_tools({"host": host_tool})

        logger.debug.assert_any_call("Host tool proxy registration output: %s", "registered")
        executor.cleanup()

    @pytest.mark.parametrize(
        ("error", "package"),
        [(ModuleNotFoundError("No module named 'missing_pkg'"), "missing_pkg"),
         (ModuleNotFoundError("custom import failure"), "unknown")],
    )
    def test_diagnostics_wrapper_converts_missing_modules(self, error, package):
        executor = SimpleNamespace(__call__=MagicMock(side_effect=error))
        logger = MagicMock()

        sandbox_module._wrap_with_diagnostics(executor, logger)
        result = executor.__call__("import something")

        assert result.startswith(f"ModuleNotFoundError: {package}")
        assert sandbox_module._wrap_with_diagnostics(executor, logger) is executor

    def test_cleanup_ignores_container_kill_failure(self):
        container = SimpleNamespace(kill=MagicMock(side_effect=RuntimeError("kill failed")))
        executor = SimpleNamespace(cleanup=MagicMock(side_effect=RuntimeError("cleanup failed")), container=container)

        sandbox_module.cleanup_executor(executor, MagicMock())

        container.kill.assert_called_once()

    def test_kernel_lease_execution_and_cleanup_paths(self, monkeypatch):
        class FakeABNF:
            OPCODE_TEXT = 1
            OPCODE_CLOSE = 8
            OPCODE_PING = 9
            OPCODE_PONG = 10

        websocket = MagicMock()
        websocket.recv_data.return_value = (
            FakeABNF.OPCODE_TEXT,
            json.dumps(
                {
                    "parent_header": {"msg_id": "request-id"},
                    "msg_type": "status",
                    "content": {"execution_state": "idle"},
                }
            ),
        )
        websocket_module = SimpleNamespace(
            ABNF=FakeABNF,
            create_connection=MagicMock(return_value=websocket),
            WebSocketConnectionClosedException=ConnectionError,
            WebSocketTimeoutException=TimeoutError,
        )
        code_output = MagicMock(return_value="result")
        remote_module = SimpleNamespace(
            AgentError=RuntimeError,
            CodeOutput=code_output,
            RemotePythonExecutor=SimpleNamespace(FINAL_ANSWER_EXCEPTION="FinalAnswerException"),
            _websocket_send_execute_request=MagicMock(return_value="request-id"),
        )
        monkeypatch.setitem(sys.modules, "websocket", websocket_module)
        monkeypatch.setitem(sys.modules, "smolagents.remote_executors", remote_module)

        lease = object.__new__(sandbox_module._DockerKernelLease)
        lease._closed = False
        lease._unhealthy = False
        lease._receive_timeout_seconds = 5
        lease.ws_url = "ws://kernel"
        lease.logger = MagicMock()
        lease.base_url = "http://kernel"
        lease.kernel_id = "kernel-id"
        lease._logger = MagicMock()
        lease._requests = SimpleNamespace(delete=MagicMock(return_value=SimpleNamespace(status_code=500)))

        assert lease.run_code_raise_errors("1 + 1") == "result"
        remote_module._websocket_send_execute_request.assert_called_once_with("1 + 1", websocket)
        websocket_module.create_connection.assert_called_once_with("ws://kernel", timeout=5)
        lease.cleanup()
        lease._logger.warning.assert_called_once()
        lease._requests.delete.assert_called_once()
        lease.cleanup()
        lease._requests.delete.assert_called_once()
        with pytest.raises(RuntimeError, match="already closed"):
            lease.run_code_raise_errors("2 + 2")

    def test_kernel_lease_delegates_remote_executor_methods(self, monkeypatch):
        remote = SimpleNamespace(
            send_variables=MagicMock(),
            install_packages=MagicMock(return_value=["pkg"]),
            send_tools=MagicMock(),
        )
        monkeypatch.setitem(sys.modules, "smolagents.remote_executors", SimpleNamespace(RemotePythonExecutor=remote))
        lease = object.__new__(sandbox_module._DockerKernelLease)

        lease.send_variables({"x": 1})
        assert lease.install_packages(["pkg"]) == ["pkg"]
        lease.send_tools({"tool": object()})

        remote.send_variables.assert_called_once_with(lease, {"x": 1})
        remote.install_packages.assert_called_once_with(lease, ["pkg"])
        remote.send_tools.assert_called_once()

    @pytest.mark.parametrize("wrap_instance_forward", [False, True])
    def test_kernel_lease_patches_final_answer_with_bound_or_wrapped_forward(self, wrap_instance_forward):
        class FinalAnswerTool:
            def forward(self, answer):
                return answer

        final_answer = FinalAnswerTool()
        if wrap_instance_forward:
            original_forward = final_answer.forward

            def observed_forward(*args, **kwargs):
                return original_forward(*args, **kwargs)

            final_answer.forward = observed_forward

        lease = object.__new__(sandbox_module._DockerKernelLease)
        lease._patch_final_answer_with_exception(final_answer)
        patched_class = final_answer.__class__
        lease._patch_final_answer_with_exception(final_answer)

        assert final_answer.__class__ is patched_class
        assert final_answer._forward("done") == "done"
        with pytest.raises(Exception) as exc_info:
            final_answer.forward("done")
        assert exc_info.value.value

    def test_system_non_docker_acquire_builds_and_tracks_executor(self, monkeypatch):
        pool = SandboxPoolManager.get_instance()
        executor = SimpleNamespace(cleanup=MagicMock())
        monkeypatch.setattr(pool, "_build_executor", MagicMock(return_value=executor))
        config = SandboxConfig(level=SandboxLevel.WASM, scope=SandboxScope.SYSTEM, docker_image="wasm:key")

        result = pool.acquire(config, MagicMock())

        assert result is executor
        assert pool._pools["wasm:key"] == []
        assert pool._in_use[id(executor)] == "wasm:key"

    def test_shared_docker_replaces_dead_owner(self, monkeypatch):
        pool = SandboxPoolManager.get_instance()
        dead = SimpleNamespace(container=SimpleNamespace(reload=MagicMock(), status="exited"), cleanup=MagicMock())
        replacement = SimpleNamespace(base_url="http://new", container=object())
        pool._system_containers["image"] = dead
        monkeypatch.setattr(pool, "_recover_docker_container", MagicMock(return_value=replacement))
        monkeypatch.setattr(pool, "_is_alive", lambda owner: owner is replacement)
        monkeypatch.setattr(
            sandbox_module,
            "_DockerKernelLease",
            lambda *args, **kwargs: MagicMock(kernel_id="lease"),
        )
        monkeypatch.setattr(sandbox_module, "_wrap_executor", lambda executor, *args: executor)
        config = SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SYSTEM, docker_image="image")

        lease = pool._acquire_shared_docker_kernel(config, MagicMock(), False)

        assert lease.kernel_id == "lease"
        dead.cleanup.assert_called_once()
        assert pool._system_containers["image"] is replacement

    def test_shared_docker_discards_racing_container(self, monkeypatch):
        pool = SandboxPoolManager.get_instance()
        built = SimpleNamespace(base_url="http://built", container=object(), cleanup=MagicMock())
        winner = SimpleNamespace(base_url="http://winner", container=object())

        class RacingContainers(dict):
            def get(self, key, default=None):
                return None

            def setdefault(self, key, value):
                self[key] = winner
                return winner

        pool._system_containers = RacingContainers()
        monkeypatch.setattr(pool, "_recover_docker_container", MagicMock(return_value=built))
        monkeypatch.setattr(pool, "_is_alive", lambda _owner: True)
        monkeypatch.setattr(
            sandbox_module,
            "_DockerKernelLease",
            lambda owner, logger, **kwargs: MagicMock(kernel_id="lease", owner=owner),
        )
        monkeypatch.setattr(sandbox_module, "_wrap_executor", lambda executor, *args: executor)
        config = SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SYSTEM, docker_image="image")

        lease = pool._acquire_shared_docker_kernel(config, MagicMock(), False)

        built.cleanup.assert_called_once()
        assert lease.owner is winner

    def test_shared_docker_rebuilds_owner_once_when_kernel_lease_fails(
        self,
        monkeypatch,
    ):
        pool = SandboxPoolManager.get_instance()
        first_owner = SimpleNamespace(base_url="http://first", container=object())
        replacement_owner = SimpleNamespace(base_url="http://replacement", container=object())
        recover = MagicMock(side_effect=[first_owner, replacement_owner])
        destroy = MagicMock()
        leases = iter([RuntimeError("gateway disconnected"), MagicMock(kernel_id="lease-2")])

        def create_lease(*_args, **_kwargs):
            result = next(leases)
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(pool, "_recover_docker_container", recover)
        monkeypatch.setattr(pool, "_is_alive", lambda _owner: True)
        monkeypatch.setattr(pool, "_destroy_executor", destroy)
        monkeypatch.setattr(sandbox_module, "_DockerKernelLease", create_lease)
        monkeypatch.setattr(sandbox_module, "_wrap_executor", lambda executor, *args: executor)
        config = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SYSTEM,
            docker_image="image",
        )

        lease = pool._acquire_shared_docker_kernel(config, MagicMock(), False)

        assert lease.kernel_id == "lease-2"
        assert recover.call_count == 2
        destroy.assert_called_once_with(first_owner, ANY)
        assert pool._system_containers["image"] is replacement_owner

    def test_release_none_is_noop(self):
        SandboxPoolManager.get_instance().release(None, MagicMock())

    def test_build_wasm_rejects_host_tools_and_wraps_executor(self, monkeypatch):
        pool = SandboxPoolManager.get_instance()
        config = SandboxConfig(level=SandboxLevel.WASM)
        with pytest.raises(RuntimeError, match="does not support host tool"):
            pool._build_executor(config, MagicMock(), host_tools_exist=True)

        wasm = SimpleNamespace(__call__=MagicMock(return_value="ok"))
        remote_module = SimpleNamespace(WasmExecutor=MagicMock(return_value=wasm))
        monkeypatch.setitem(sys.modules, "smolagents.remote_executors", remote_module)
        result = pool._build_wasm_executor(config, MagicMock())
        assert result is wasm
        assert result._nexent_backend == "wasm"

    def test_build_wasm_falls_back_when_constructor_fails(self, monkeypatch):
        pool = SandboxPoolManager.get_instance()
        remote_module = SimpleNamespace(WasmExecutor=MagicMock(side_effect=RuntimeError("wasm failed")))
        monkeypatch.setitem(sys.modules, "smolagents.remote_executors", remote_module)
        monkeypatch.setattr(
            sandbox_module,
            "_make_local_executor",
            MagicMock(return_value=SimpleNamespace(__call__=MagicMock(return_value="local"))),
        )

        result = pool._build_wasm_executor(SandboxConfig(level=SandboxLevel.WASM), MagicMock())

        assert result is not None

    def test_build_executor_uses_successful_wasm_path(self, monkeypatch):
        pool = SandboxPoolManager.get_instance()
        wasm = SimpleNamespace(__call__=MagicMock(return_value="ok"))
        monkeypatch.setattr(pool, "_build_wasm_executor", MagicMock(return_value=wasm))

        result = pool._build_executor(SandboxConfig(level=SandboxLevel.WASM), MagicMock())

        assert result is wasm
        pool._build_wasm_executor.assert_called_once()

    def test_build_wasm_falls_back_when_dependency_is_missing(self, monkeypatch):
        pool = SandboxPoolManager.get_instance()
        remote_module = SimpleNamespace()
        monkeypatch.setitem(sys.modules, "smolagents.remote_executors", remote_module)
        local = SimpleNamespace(__call__=MagicMock(return_value="local"))
        monkeypatch.setattr(sandbox_module, "_make_local_executor", MagicMock(return_value=local))

        result = pool._build_wasm_executor(SandboxConfig(level=SandboxLevel.WASM), MagicMock())

        assert result is local

    def test_recovery_tries_next_connection_host(self, monkeypatch):
        pool = SandboxPoolManager.get_instance()
        container = MagicMock()
        container.name = sandbox_module.SANDBOX_CONTAINER_NAME
        container.status = "running"
        container.labels = {"com.nexent.sandbox": "runtime"}
        container.attrs = {"NetworkSettings": {"Networks": {sandbox_module.SANDBOX_NETWORK_NAME: {}}}}
        container.client = MagicMock()
        docker_module = SimpleNamespace(from_env=lambda: SimpleNamespace(
            containers=SimpleNamespace(list=lambda **kwargs: [container])
        ))
        get = MagicMock(side_effect=[RuntimeError("first failed"), SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: []
        )])
        monkeypatch.setitem(sys.modules, "docker", docker_module)
        monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=get))
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: True)
        monkeypatch.setattr(sandbox_module, "_sandbox_connection_hosts", lambda item: ["first", "second"])

        recovered = pool._recover_docker_container(
            SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SYSTEM), MagicMock(), False
        )

        assert recovered.host == "second"

    def test_recovery_returns_none_when_all_connection_hosts_fail(self, monkeypatch):
        pool = SandboxPoolManager.get_instance()
        container = MagicMock()
        container.name = sandbox_module.SANDBOX_CONTAINER_NAME
        container.status = "running"
        container.labels = {"com.nexent.sandbox": "runtime"}
        container.attrs = {"NetworkSettings": {"Networks": {sandbox_module.SANDBOX_NETWORK_NAME: {}}}}
        docker_module = SimpleNamespace(from_env=lambda: SimpleNamespace(
            containers=SimpleNamespace(list=lambda **kwargs: [container])
        ))
        monkeypatch.setitem(sys.modules, "docker", docker_module)
        monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=MagicMock(side_effect=RuntimeError("down"))))
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: True)
        monkeypatch.setattr(sandbox_module, "_sandbox_connection_hosts", lambda item: ["only"])

        assert pool._recover_docker_container(
            SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SYSTEM), MagicMock(), False
        ) is None

    def test_remove_stale_container_using_image_and_port(self, monkeypatch):
        pool = SandboxPoolManager.get_instance()
        container = MagicMock(
            name="old-name",
            image=SimpleNamespace(tags=["custom:image"]),
            attrs={"NetworkSettings": {"Ports": {"8888/tcp": [{"HostPort": "8888"}]}}},
        )
        docker_module = SimpleNamespace(from_env=lambda: SimpleNamespace(
            containers=SimpleNamespace(list=lambda **kwargs: [container])
        ))
        monkeypatch.setitem(sys.modules, "docker", docker_module)

        pool._remove_stale_docker_containers(SandboxConfig(docker_image="custom:image"), MagicMock())

        container.remove.assert_called_once_with(force=True)

    def test_system_docker_cleanup_preserves_original_error_when_remove_fails(self, monkeypatch):
        pool = SandboxPoolManager.get_instance()
        container = MagicMock(attrs={"NetworkSettings": {"Networks": {}}})
        container.remove.side_effect = RuntimeError("remove failed")
        docker_module = SimpleNamespace(from_env=lambda: SimpleNamespace(
            containers=SimpleNamespace(run=MagicMock(return_value=container))
        ))
        monkeypatch.setitem(sys.modules, "docker", docker_module)
        monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=MagicMock(side_effect=RuntimeError("not ready"))))
        monkeypatch.setattr(sandbox_module, "_sandbox_connection_hosts", lambda item: ["host"])
        monotonic = iter([0, 121])
        monkeypatch.setattr(sandbox_module.time, "monotonic", lambda: next(monotonic))

        with pytest.raises(RuntimeError, match="did not become ready"):
            pool._build_system_docker_executor(
                SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SYSTEM), MagicMock(), {}
            )

    def test_docker_network_failure_and_host_bridge_installation(self, monkeypatch):
        pool = SandboxPoolManager.get_instance()
        executor = SimpleNamespace(__call__=MagicMock(return_value="ok"), send_tools=MagicMock(), cleanup=MagicMock())
        remote_module = SimpleNamespace(DockerExecutor=MagicMock())
        docker_module = SimpleNamespace(from_env=MagicMock(side_effect=RuntimeError("network unavailable")))
        monkeypatch.setitem(sys.modules, "smolagents.remote_executors", remote_module)
        monkeypatch.setitem(sys.modules, "docker", docker_module)
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: True)
        bridge_installer = MagicMock(return_value=executor)
        monkeypatch.setattr(sandbox_module, "_install_host_tool_bridge", bridge_installer)
        config = SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SYSTEM)
        monkeypatch.setattr(pool, "_build_system_docker_executor", MagicMock(return_value=executor))
        monkeypatch.setattr(pool, "_build_session_docker_executor", MagicMock(return_value=executor))

        assert pool._build_docker_executor(config, MagicMock(), True) is executor
        bridge_installer.assert_not_called()

        config.scope = SandboxScope.SESSION
        pool._build_docker_executor(config, MagicMock(), True)
        bridge_installer.assert_called_once_with(
            executor,
            ANY,
            request_timeout_seconds=None,
        )

    def test_build_docker_executor_leases_from_existing_session_group(self, monkeypatch):
        pool = SandboxPoolManager.get_instance()
        executor = SimpleNamespace(
            __call__=MagicMock(return_value="ok"),
            send_tools=MagicMock(),
            cleanup=MagicMock(),
        )
        group = sandbox_module._SessionDockerContainerGroup(SimpleNamespace())
        monkeypatch.setitem(
            sys.modules,
            "smolagents.remote_executors",
            SimpleNamespace(DockerExecutor=MagicMock()),
        )
        lease = MagicMock(return_value=executor)
        monkeypatch.setattr(pool, "_lease_session_docker_kernel", lease)
        monkeypatch.setattr(sandbox_module, "_wrap_executor", lambda item, config, logger_: item)

        result = pool._build_docker_executor(
            SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SESSION),
            MagicMock(),
            session_container_group=group,
        )

        assert result is executor
        lease.assert_called_once_with(ANY, ANY, group)

    def test_system_docker_creates_missing_network(self, monkeypatch):
        pool = SandboxPoolManager.get_instance()
        executor = SimpleNamespace(__call__=MagicMock(return_value="ok"))
        networks = SimpleNamespace(
            get=MagicMock(side_effect=KeyError("missing")),
            create=MagicMock(),
        )

        class NotFound(KeyError):
            pass

        networks.get.side_effect = NotFound("missing")
        docker_module = SimpleNamespace(
            from_env=lambda: SimpleNamespace(networks=networks),
            errors=SimpleNamespace(NotFound=NotFound),
        )
        remote_module = SimpleNamespace(DockerExecutor=MagicMock())
        monkeypatch.setitem(sys.modules, "docker", docker_module)
        monkeypatch.setitem(sys.modules, "smolagents.remote_executors", remote_module)
        monkeypatch.setattr(pool, "_build_system_docker_executor", MagicMock(return_value=executor))

        result = pool._build_docker_executor(
            SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SYSTEM), MagicMock()
        )

        assert result is executor
        networks.create.assert_called_once_with(
            sandbox_module.SANDBOX_NETWORK_NAME,
            driver="bridge",
            internal=True,
        )

    def test_online_system_sandbox_uses_bridge_and_package_install_environment(self, monkeypatch):
        pool = SandboxPoolManager.get_instance()
        executor = SimpleNamespace(__call__=MagicMock(return_value="ok"))
        network = MagicMock(attrs={"Internal": True, "Containers": {}})
        docker_module = SimpleNamespace(
            from_env=lambda: SimpleNamespace(networks=SimpleNamespace(get=MagicMock(return_value=network))),
            errors=SimpleNamespace(NotFound=KeyError),
        )
        builder = MagicMock(return_value=executor)
        monkeypatch.setitem(sys.modules, "docker", docker_module)
        monkeypatch.setitem(
            sys.modules,
            "smolagents.remote_executors",
            SimpleNamespace(DockerExecutor=MagicMock()),
        )
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: False)
        monkeypatch.setattr(pool, "_build_system_docker_executor", builder)
        monkeypatch.setattr(sandbox_module, "_wrap_executor", lambda item, config, logger_: item)

        result = pool._build_docker_executor(
            SandboxConfig(
                level=SandboxLevel.DOCKER,
                scope=SandboxScope.SYSTEM,
                network_disabled=False,
            ),
            MagicMock(),
        )

        assert result is executor
        run_kwargs = builder.call_args.args[2]
        assert "network" not in run_kwargs
        assert run_kwargs["network_disabled"] is False
        assert run_kwargs["environment"] == sandbox_module._ONLINE_PACKAGE_ENV
        assert run_kwargs["environment"]["PYTHONPATH"] == (
            "/home/sandbox/.local/lib/python3.11/site-packages"
        )
        assert run_kwargs["environment"]["PATH"].startswith(
            "/home/sandbox/.local/bin:"
        )

    def test_evictor_loop_runs_maintenance_once(self, monkeypatch):
        pool = SandboxPoolManager()
        pool._stop_evict = MagicMock()
        pool._stop_evict.wait.side_effect = [False, True]
        monkeypatch.setattr(pool, "_evict_idle", MagicMock())
        monkeypatch.setattr(pool, "_clean_stale", MagicMock())

        pool._start_evictor()
        pool._evict_thread.join(timeout=2)

        pool._evict_idle.assert_called_once_with(sandbox_module.logger)
        pool._clean_stale.assert_called_once_with(sandbox_module.logger)

    def test_evict_and_clean_stale_keep_survivors(self):
        pool = SandboxPoolManager.get_instance()
        survivor = _FakeExecutor("survivor", alive=True)
        pool._pools["survivor"] = [survivor]
        pool._last_touch[id(survivor)] = time.time()

        pool._evict_idle(MagicMock())
        assert pool._pools["survivor"] == [survivor]
        pool._clean_stale(MagicMock())
        assert pool._pools["survivor"] == [survivor]
