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
import importlib
import importlib.util
import os
import sys
import time
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

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
        importlib.import_module("smolagents")
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
        # The pool manager uses ``executor.container`` to check liveness.
        # Make it a MagicMock whose ``status`` reflects ``_alive``.
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

    def test_system_docker_uses_one_container_and_distinct_kernel_leases(self, monkeypatch):
        """SYSTEM Docker shares one container while isolating each run by kernel."""
        pm = self._build_pool()
        logger = sandbox_module.logging.getLogger("test_sandbox")
        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SYSTEM,
            docker_image="img:latest",
        )

        class FakeOwner:
            base_url = "http://127.0.0.1:8888"
            host = "127.0.0.1"
            port = 8888
            container = MagicMock()

        owner = FakeOwner()
        pm._system_containers.pop("img:latest|host_tools=true", None)
        owner.logger = logger
        owner.container.status = "running"
        owner.container.reload.return_value = None
        leases = iter([MagicMock(kernel_id="kernel-1"), MagicMock(kernel_id="kernel-2")])
        leased_executors = []

        def install_bridge(executor, logger_):
            leased_executors.append(executor)
            return executor

        monkeypatch.setattr(pm, "_build_executor", lambda *args: owner)
        monkeypatch.setattr(sandbox_module, "_DockerKernelLease", lambda *args: next(leases))
        monkeypatch.setattr(sandbox_module, "_install_host_tool_bridge", install_bridge)

        ex1 = pm.acquire(cfg, logger, host_tools_exist=True)
        ex2 = pm.acquire(cfg, logger, host_tools_exist=True)

        assert ex1 is not ex2
        assert leased_executors == [ex1, ex2]
        assert pm._system_containers["img:latest|host_tools=true"] is owner
        pm.release(ex1, logger)
        pm.release(ex2, logger)
        owner.cleanup = MagicMock()
        pm.shutdown(logger)
        owner.cleanup.assert_called_once()

    def test_acquire_system_drops_dead_executor(self):
        """Stale (no-longer-running) executors are destroyed, not handed out.

        ``acquire`` walks the pool via ``.pop()`` which removes the LAST
        element first.  We seed the pool ``[alive, dead]`` (dead at the
        tail) so the iterator pops ``dead`` first, destroys it, and then
        pops ``alive`` and returns it.
        """
        pm = self._build_pool()
        logger = sandbox_module.logging.getLogger("test_sandbox")

        alive = _FakeExecutor(image="img:latest", alive=True)
        dead = _FakeExecutor(image="img:latest", alive=False)
        # Dead at the tail so acquire pops it first.
        pm._pools["img:latest"] = [alive, dead]
        pm._last_touch[id(alive)] = time.time()
        pm._last_touch[id(dead)] = time.time()

        cfg = SandboxConfig(
            level=SandboxLevel.WASM,
            scope=SandboxScope.SYSTEM,
            docker_image="img:latest",
        )
        # acquire should destroy ``dead`` first, then hand out ``alive``.
        ex = pm.acquire(cfg, logger)
        assert ex is alive
        assert dead.cleaned_up is True
        # Handed-out executor should be tracked, and the dead one removed.
        assert id(ex) in pm._in_use
        assert pm._pools["img:latest"] == []  # dead cleaned, alive checked out

    def test_clean_stale_destroys_dead_pool_entries(self):
        """The reaper destroys dead pool entries even when acquire is idle."""
        pm = self._build_pool()
        logger = sandbox_module.logging.getLogger("test_sandbox")

        dead = _FakeExecutor(image="img:latest", alive=False)
        pm._pools["img:latest"] = [dead]
        pm._last_touch[id(dead)] = time.time()

        pm._clean_stale(logger)
        assert dead.cleaned_up is True
        assert pm._pools["img:latest"] == []  # cleaned up


# ---------------------------------------------------------------------------
# Docker-level integration tests (skipped if docker is not running)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not _docker_available(),
    reason="Docker daemon not reachable on this machine",
)
class TestDockerIntegration:
    """End-to-end exercise of session + system scope with the real DockerExecutor."""

    IMAGE = "nexent/nexent-sandbox:latest"

    def test_session_scope_does_not_share_container(self):
        """SESSION: every build yields a distinct executor (each gets its own container)."""
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

        # Free up: SESSION cleanup destroys the container.
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
            # Hand the executor back so teardown can destroy it cleanly.
            release_python_executor(
                build_python_executor(cfg, logger) or None.__class__(),  # type: ignore[arg-type]
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
                build_python_executor(cfg, logger) or None.__class__(),  # type: ignore[arg-type]
                logger,
            )
            pool = SandboxPoolManager.get_instance()
            pool.shutdown(logger)
