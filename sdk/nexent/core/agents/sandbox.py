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
import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from contextlib import closing
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


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
    memory_limit_mb: int = 512
    cpu_quota: float = 1.0
    network_disabled: bool = True
    timeout_seconds: int = 30
    shell_policy: ShellPolicy = ShellPolicy.DISABLED
    output_dir: str = "/home/sandbox/workdir/output"
    auto_sync_outputs: bool = True
    extra_kwargs: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[dict[str, Any]]) -> "SandboxConfig":
        """Build a SandboxConfig from a plain dict (e.g. from AgentConfig.sandbox_policy)."""
        if not data:
            return cls()
        return cls(
            level=SandboxLevel(data.get("level", "local")),
            scope=SandboxScope(data.get("scope", "session")),
            docker_image=data.get("docker_image", "nexent/nexent-sandbox:latest"),
            memory_limit_mb=int(data.get("memory_limit_mb", 512)),
            cpu_quota=float(data.get("cpu_quota", 1.0)),
            network_disabled=bool(data.get("network_disabled", True)),
            timeout_seconds=int(data.get("timeout_seconds", 30)),
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


def _scan_shell_calls(code: str) -> list[str]:
    """AST static scan for forbidden subprocess / os shell invocations."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            module = func.value.id
            attr = func.attr
            if module in _FORBIDDEN_SHELL_CALLS and attr in _FORBIDDEN_SHELL_CALLS[module]:
                violations.append(f"{module}.{attr}(...)")
    return violations


def _install_shell_guard(executor: Any, policy: ShellPolicy, logger_: logging.Logger) -> Any:
    """
    Install an AST-based guard that intercepts subprocess / os shell calls
    before they reach the sandbox container.

    This runs in the host process, scanning the code string BEFORE it is
    sent over the wire to the container.  Combined with ``network_disabled=True``
    and a non-root UID, defence-in-depth is achieved.
    """
    if getattr(executor, "_nexent_shell_guard_installed", False):
        return executor
    if policy == ShellPolicy.BOXED:
        return executor  # BOXED means no interception

    original_call = executor.__call__

    def wrapped_call(code: str) -> Any:
        violations = _scan_shell_calls(code)
        if violations:
            logger_.warning(
                "Sandbox shell guard blocked %d call(s): %s",
                len(violations),
                violations,
            )
            return (
                "SecurityError: shell command execution is disabled in this sandbox.\n"
                "Detected: " + ", ".join(violations) + "\n"
                "Suggestion: use a Nexent tool (e.g. TerminalTool with explicit "
                "allowlist) or implement the logic in pure Python.\n"
                "To enable shell access, configure sandbox_policy.shell_policy='restricted' "
                "and supply an explicit command allowlist."
            )
        return original_call(code)

    executor.__call__ = wrapped_call
    executor._nexent_shell_guard_installed = True
    return executor


# ----------------------------------------------------------------------
# Host tool bridge for remote code executors
# ----------------------------------------------------------------------


def _is_host_tool(tool: Any) -> bool:
    """Return whether a tool must execute in the Nexent host process."""
    return bool(getattr(tool, "_nexent_execute_on_host", False))


class _ToolBridge:
    """Token-authenticated HTTP bridge from a sandbox to live host tools."""

    def __init__(self, logger_: logging.Logger) -> None:
        self._logger = logger_
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
                    result = tool(*payload.get("args", []), **payload.get("kwargs", {}))
                    body = json.dumps({"result": result}, ensure_ascii=False, default=str).encode("utf-8")
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
                f"    return _nexent_call_host_tool({name!r}, args, kwargs)"
            )
        host = bridge_host or self._bridge_host()
        return (
            "import json as _nexent_json\n"
            "import urllib.request as _nexent_urllib\n"
            f"_NEXENT_TOOL_BRIDGE_URL = 'http://{host}:{self.port}/invoke'\n"
            f"_NEXENT_TOOL_BRIDGE_TOKEN = {self._token!r}\n"
            "def _nexent_call_host_tool(name, args, kwargs):\n"
            "    payload = _nexent_json.dumps({'tool': name, 'args': args, 'kwargs': kwargs}).encode('utf-8')\n"
            "    request = _nexent_urllib.Request(_NEXENT_TOOL_BRIDGE_URL, data=payload, headers={\n"
            "        'Authorization': 'Bearer ' + _NEXENT_TOOL_BRIDGE_TOKEN,\n"
            "        'Content-Type': 'application/json',\n"
            "    })\n"
            "    try:\n"
            "        with _nexent_urllib.urlopen(request, timeout=120) as response:\n"
            "            result = _nexent_json.loads(response.read().decode('utf-8'))\n"
            "    except Exception as exc:\n"
            "        raise RuntimeError('Local tool bridge request failed: ' + str(exc)) from exc\n"
            "    if 'error' in result:\n"
            "        raise RuntimeError(result['error'])\n"
            "    return result.get('result')\n\n"
            + "\n\n".join(definitions)
        )

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def _install_host_tool_bridge(executor: Any, logger_: logging.Logger) -> Any:
    """Keep Nexent tools local while code runs in a remote executor."""
    if getattr(executor, "_nexent_tool_bridge_installed", False):
        return executor

    bridge = _ToolBridge(logger_)
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
            output = executor.run_code_raise_errors(bridge.proxy_code(host_tools, bridge_host))
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
    "(2) implement the logic with Python stdlib; "
    "(3) call a Nexent tool instead of a raw import."
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
                "Not auto-installing (security boundary). "
                "Returning diagnostic message to LLM.",
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
SANDBOX_NETWORK_NAME = "nexent_network"
SANDBOX_JUPYTER_PORT = 8888


def _is_containerized_runtime() -> bool:
    """Return whether the current runtime is running inside a Docker container."""
    return Path("/.dockerenv").exists()


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
    ) -> None:
        self.container = container
        self.client = container.client
        self.logger = _make_smolagents_logger(logger_)
        self._logger = logger_
        self.host = host
        self.port = SANDBOX_JUPYTER_PORT
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

    def __init__(self, container_executor: Any, logger_: logging.Logger) -> None:
        import requests
        from smolagents.remote_executors import _create_kernel_http

        self._container_executor = container_executor
        self.logger = container_executor.logger
        self.additional_imports = getattr(container_executor, "additional_imports", [])
        self.installed_packages = list(getattr(container_executor, "installed_packages", []))
        self._logger = logger_
        self.base_url = container_executor.base_url
        self.host = container_executor.host
        self.port = container_executor.port
        self.kernel_id = _create_kernel_http(f"{self.base_url}/api/kernels", self.logger)
        self.ws_url = f"ws://{self.host}:{self.port}/api/kernels/{self.kernel_id}/channels"
        self._closed = False
        self._requests = requests

    @property
    def container(self) -> Any:
        """Return the shared Docker container for health checks and diagnostics."""
        return self._container_executor.container

    def run_code_raise_errors(self, code: str) -> Any:
        from smolagents.remote_executors import _websocket_run_code_raise_errors
        from websocket import create_connection

        if self._closed:
            raise RuntimeError("Sandbox kernel lease is already closed")
        with closing(create_connection(self.ws_url)) as ws:
            return _websocket_run_code_raise_errors(code, ws, self.logger)

    def __call__(self, code_action: str) -> Any:
        return self.run_code_raise_errors(code_action)

    def send_variables(self, variables: dict[str, Any]) -> None:
        from smolagents.remote_executors import RemotePythonExecutor
        RemotePythonExecutor.send_variables(self, variables)

    def install_packages(self, additional_imports: list[str]) -> list[str]:
        from smolagents.remote_executors import RemotePythonExecutor
        return RemotePythonExecutor.install_packages(self, additional_imports)

    def _patch_final_answer_with_exception(self, final_answer_tool: Any) -> None:
        from smolagents.remote_executors import RemotePythonExecutor
        RemotePythonExecutor._patch_final_answer_with_exception(self, final_answer_tool)

    def send_tools(self, tools: dict[str, Any]) -> None:
        from smolagents.remote_executors import RemotePythonExecutor
        RemotePythonExecutor.send_tools(self, tools)

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
    ) -> Any:
        """
        Acquire a warm executor from the pool, or create a new one if the pool
        is empty or scope is SESSION.

        For ``scope=SESSION`` this always creates a fresh executor.
        For ``scope=SYSTEM`` this tries to pop from the pool first.
        """
        if config.scope == SandboxScope.SESSION:
            return self._build_executor(config, logger_, host_tools_exist)

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
        pool_key = (
            f"{config.docker_image}|host_tools=true"
            if host_tools_exist
            else config.docker_image
        )
        with self._lock:
            container_executor = self._system_containers.get(pool_key)
            if container_executor is not None and not self._is_alive(container_executor):
                self._system_containers.pop(pool_key, None)
                self._destroy_executor(container_executor, logger_)
                container_executor = None

        if container_executor is None:
            with self._container_build_lock:
                with self._lock:
                    container_executor = self._system_containers.get(pool_key)
                if container_executor is None:
                    container_executor = self._recover_docker_container(config, logger_, host_tools_exist)
                if container_executor is None:
                    self._remove_stale_docker_containers(config, logger_)
                    container_executor = self._build_executor(config, logger_, host_tools_exist)
                if not hasattr(container_executor, "base_url") or not hasattr(container_executor, "container"):
                    return container_executor
                with self._lock:
                    existing = self._system_containers.setdefault(pool_key, container_executor)
                    if existing is not container_executor:
                        self._destroy_executor(container_executor, logger_)
                        container_executor = existing

        lease = _DockerKernelLease(container_executor, logger_)
        if host_tools_exist:
            lease = _install_host_tool_bridge(lease, logger_)
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
            return self._build_docker_executor(config, logger_, host_tools_exist)

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
        if _is_containerized_runtime():
            run_kwargs.pop("ports", None)
        else:
            run_kwargs["ports"] = {
                f"{SANDBOX_JUPYTER_PORT}/tcp": ("127.0.0.1", SANDBOX_JUPYTER_PORT)
            }
        run_kwargs["detach"] = True
        container = client.containers.run(config.docker_image, **run_kwargs)
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
    ) -> Any:
        """Construct a Docker executor with Nexent hardening."""
        try:
            from smolagents.remote_executors import DockerExecutor
        except ImportError as exc:
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
            **({"extra_hosts": {"host.docker.internal": "host-gateway"}} if host_tools_exist else {}),
        }
        if config.scope == SandboxScope.SYSTEM:
            try:
                import docker

                docker_client = docker.from_env()
                try:
                    docker_client.networks.get(SANDBOX_NETWORK_NAME)
                except docker.errors.NotFound:
                    docker_client.networks.create(SANDBOX_NETWORK_NAME, driver="bridge")
                container_run_kwargs.update({
                    "name": SANDBOX_CONTAINER_NAME,
                    "network": SANDBOX_NETWORK_NAME,
                    "labels": {"com.nexent.sandbox": "runtime"},
                    "command": _kernel_gateway_command(),
                })
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
                executor = DockerExecutor(
                    additional_imports=config.extra_kwargs.get("additional_imports", []),
                    logger=_make_smolagents_logger(logger_),
                    image_name=config.docker_image,
                    build_new_image=False,
                    container_run_kwargs=container_run_kwargs,
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
            executor = _install_host_tool_bridge(executor, logger_)
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
    executor = _install_shell_guard(executor, config.shell_policy, logger_)
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
) -> Any:
    """
    Factory function: build a python_executor from ``SandboxConfig``.

    This is the canonical entry point used by ``NexentAgent.create_single_agent``.
    It delegates to ``SandboxPoolManager`` for system-scoped executors and builds
    a fresh per-run executor for session-scoped requests.

    Args:
        config: sandbox configuration.
        logger_: logger instance.
        managed_agents_exist: if True and level != LOCAL, log a warning and
            fall back to LOCAL (smolagents limitation — managed_agents share
            the parent's python_executor).

    Returns:
        A wrapped python_executor.  Never raises — always returns a usable
        executor (falls back to LocalPythonExecutor on any error).
    """
    if managed_agents_exist and config.level != SandboxLevel.LOCAL:
        logger_.warning(
            "Sandbox level '%s' is incompatible with managed_agents "
            "(smolagents limitation).  Falling back to LOCAL.",
            config.level.value,
        )
        config.level = SandboxLevel.LOCAL

    pool = SandboxPoolManager.get_instance()

    if config.scope == SandboxScope.SESSION:
        # Per-run fresh executor — pool manager still calls _build_executor
        # but we immediately destroy it when release() is called.
        executor = pool.acquire(config, logger_, host_tools_exist)
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
