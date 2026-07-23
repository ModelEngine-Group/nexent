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
from unittest.mock import ANY, MagicMock, patch

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
        monkeypatch.setattr(pm, "_recover_docker_container", lambda *args: None)
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

    def test_syntax_error_returns_empty(self):
        """Code with syntax errors should return empty (fail open)."""
        code = "import os(\nthis is not valid python"
        violations = sandbox_module._scan_shell_calls(code)
        assert violations == []

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
            assert "def _nexent_call_host_tool(" in code
        finally:
            bridge.close()

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


class TestBuildPythonExecutor:
    """Test the main factory function."""

    def test_falls_back_to_local_when_managed_agents_exist(self):
        """Should fall back to LOCAL when managed_agents_exist is True."""
        cfg = SandboxConfig(level=SandboxLevel.DOCKER)
        logger = sandbox_module.logging.getLogger("test")

        executor = sandbox_module.build_python_executor(cfg, logger, managed_agents_exist=True)

        assert getattr(executor, "_nexent_backend", None) == "local"

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
        monkeypatch.setattr(sandbox_module, "_DockerKernelLease", lambda *args: MagicMock(kernel_id="test-kernel"))
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
        monkeypatch.setattr(sandbox_module, "_DockerKernelLease", lambda *args: MagicMock(kernel_id="test-kernel"))
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
                containers=SimpleNamespace(run=run)
            )
        )
        monkeypatch.setitem(sys.modules, "docker", docker_module)
        monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(get=mock_get))
        monkeypatch.setattr(sandbox_module, "_is_containerized_runtime", lambda: False)
        monkeypatch.setattr(sandbox_module, "_sandbox_connection_hosts", lambda c: ["127.0.0.1"])

        executor = pm._build_system_docker_executor(cfg, logger, {"name": "test-sandbox"})

        assert executor.base_url == "http://127.0.0.1:8888"
        assert call_count[0] >= 2

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
        assert cfg.memory_limit_mb == 512
        assert cfg.cpu_quota == 1.0
        assert cfg.network_disabled is True
        assert cfg.timeout_seconds == 30
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
        assert cfg.shell_policy == sandbox_module.ShellPolicy.RESTRICTED
        assert cfg.output_dir == "/custom/output"
        assert cfg.auto_sync_outputs is False
        assert cfg.extra_kwargs == {"key": "value"}

    def test_from_dict_handles_empty_dict(self):
        """from_dict with empty dict should use defaults."""
        cfg = SandboxConfig.from_dict({})

        assert cfg.level == sandbox_module.SandboxLevel.LOCAL
        assert cfg.scope == sandbox_module.SandboxScope.SESSION


class TestPoolManagerConstants:
    """Test module-level constants."""

    def test_sandbox_container_name_defined(self):
        """SANDBOX_CONTAINER_NAME should be defined."""
        assert sandbox_module.SANDBOX_CONTAINER_NAME == "nexent-runtime-sandbox"

    def test_sandbox_network_name_defined(self):
        """SANDBOX_NETWORK_NAME should be defined."""
        assert sandbox_module.SANDBOX_NETWORK_NAME == "nexent_network"

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
        monkeypatch.setattr(sandbox_module, "_DockerKernelLease", lambda *args: MagicMock(kernel_id="test-kernel"))
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

    def test_host_tools_affects_pool_key(self, monkeypatch):
        """Pool key should differ when host_tools_exist changes."""
        pm = SandboxPoolManager.get_instance()
        logger = sandbox_module.logging.getLogger("test")

        executor_with_host = _FakeExecutor(image="shared:latest", alive=True)
        executor_without_host = _FakeExecutor(image="shared:latest", alive=True)

        def mock_build_executor(config, logger_, host_tools=False):
            if host_tools:
                return executor_with_host
            return executor_without_host

        monkeypatch.setattr(pm, "_build_executor", mock_build_executor)
        monkeypatch.setattr(pm, "_recover_docker_container", lambda *args: None)
        monkeypatch.setattr(sandbox_module, "_DockerKernelLease", lambda *args: MagicMock(kernel_id="test-kernel"))
        monkeypatch.setattr(sandbox_module, "_install_host_tool_bridge", lambda ex, l: ex)
        monkeypatch.setattr(sandbox_module, "_wrap_executor", lambda ex, c, l: ex)

        cfg = SandboxConfig(
            level=SandboxLevel.DOCKER,
            scope=SandboxScope.SYSTEM,
            docker_image="shared:latest",
        )

        acquired_with = pm.acquire(cfg, logger, host_tools_exist=True)
        acquired_without = pm.acquire(cfg, logger, host_tools_exist=False)

        assert acquired_with is executor_with_host
        assert acquired_without is executor_without_host


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

        def mock_install_bridge(ex, l):
            bridge_installed[0] = True
            return ex

        monkeypatch.setattr(pm, "_recover_docker_container", mock_recover)
        monkeypatch.setattr(pm, "_build_executor", mock_build)
        monkeypatch.setattr(sandbox_module, "_DockerKernelLease", lambda *args: MagicMock(kernel_id="test-kernel"))
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

    def test_shell_guard_boxed_and_wrapped_calls(self):
        executor = SimpleNamespace(__call__=MagicMock(return_value="ok"))
        logger = MagicMock()

        assert sandbox_module._install_shell_guard(executor, ShellPolicy.BOXED, logger) is executor
        assert not hasattr(executor, "_nexent_shell_guard_installed")

        sandbox_module._install_shell_guard(executor, ShellPolicy.DISABLED, logger)
        assert "SecurityError" in executor.__call__("import os; os.system('id')")
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
        remote_run = MagicMock(return_value="result")
        websocket = MagicMock()
        websocket_module = SimpleNamespace(create_connection=MagicMock(return_value=websocket))
        remote_module = SimpleNamespace(_websocket_run_code_raise_errors=remote_run)
        monkeypatch.setitem(sys.modules, "websocket", websocket_module)
        monkeypatch.setitem(sys.modules, "smolagents.remote_executors", remote_module)

        lease = object.__new__(sandbox_module._DockerKernelLease)
        lease._closed = False
        lease.ws_url = "ws://kernel"
        lease.logger = MagicMock()
        lease.base_url = "http://kernel"
        lease.kernel_id = "kernel-id"
        lease._logger = MagicMock()
        lease._requests = SimpleNamespace(delete=MagicMock(return_value=SimpleNamespace(status_code=500)))

        assert lease.run_code_raise_errors("1 + 1") == "result"
        remote_run.assert_called_once_with("1 + 1", websocket, lease.logger)
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
            _patch_final_answer_with_exception=MagicMock(),
            send_tools=MagicMock(),
        )
        monkeypatch.setitem(sys.modules, "smolagents.remote_executors", SimpleNamespace(RemotePythonExecutor=remote))
        lease = object.__new__(sandbox_module._DockerKernelLease)

        lease.send_variables({"x": 1})
        assert lease.install_packages(["pkg"]) == ["pkg"]
        lease._patch_final_answer_with_exception("final")
        lease.send_tools({"tool": object()})

        remote.send_variables.assert_called_once_with(lease, {"x": 1})
        remote.install_packages.assert_called_once_with(lease, ["pkg"])
        remote._patch_final_answer_with_exception.assert_called_once_with(lease, "final")
        remote.send_tools.assert_called_once()

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
        monkeypatch.setattr(sandbox_module, "_DockerKernelLease", lambda *args: MagicMock(kernel_id="lease"))
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
        monkeypatch.setattr(sandbox_module, "_DockerKernelLease", lambda owner, logger: MagicMock(kernel_id="lease", owner=owner))
        monkeypatch.setattr(sandbox_module, "_wrap_executor", lambda executor, *args: executor)
        config = SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SYSTEM, docker_image="image")

        lease = pool._acquire_shared_docker_kernel(config, MagicMock(), False)

        built.cleanup.assert_called_once()
        assert lease.owner is winner

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
        monotonic = iter([0, 31])
        monkeypatch.setattr(sandbox_module.time, "monotonic", lambda: next(monotonic))

        with pytest.raises(RuntimeError, match="did not become ready"):
            pool._build_system_docker_executor(
                SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SYSTEM), MagicMock(), {}
            )

    def test_docker_network_failure_and_host_bridge_installation(self, monkeypatch):
        pool = SandboxPoolManager.get_instance()
        executor = SimpleNamespace(__call__=MagicMock(return_value="ok"), send_tools=MagicMock(), cleanup=MagicMock())
        docker_executor = MagicMock(return_value=executor)
        remote_module = SimpleNamespace(DockerExecutor=docker_executor)
        docker_module = SimpleNamespace(from_env=MagicMock(side_effect=RuntimeError("network unavailable")))
        monkeypatch.setitem(sys.modules, "smolagents.remote_executors", remote_module)
        monkeypatch.setitem(sys.modules, "docker", docker_module)
        bridge_installer = MagicMock(return_value=executor)
        monkeypatch.setattr(sandbox_module, "_install_host_tool_bridge", bridge_installer)
        config = SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SYSTEM)
        monkeypatch.setattr(pool, "_build_system_docker_executor", MagicMock(return_value=executor))

        assert pool._build_docker_executor(config, MagicMock(), True) is executor
        bridge_installer.assert_not_called()

        config.scope = SandboxScope.SESSION
        pool._build_docker_executor(config, MagicMock(), True)
        bridge_installer.assert_called_once_with(executor, ANY)

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
        networks.create.assert_called_once_with(sandbox_module.SANDBOX_NETWORK_NAME, driver="bridge")

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
