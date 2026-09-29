"""Per-case controlled service lifecycle, adapted from the original run-case entrypoint."""
from contextlib import contextmanager
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import build_opener, ProxyHandler


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait_ready(url, process, timeout=20, *, accepted_statuses=(200,)):
    deadline = time.monotonic() + timeout
    # Host-local readiness must not be sent through a developer's HTTP proxy.
    opener = build_opener(ProxyHandler({}))
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Controlled service exited before readiness")
        try:
            with opener.open(url, timeout=1) as response:
                if response.status in accepted_statuses:
                    return
        except HTTPError as exc:
            if exc.code in accepted_statuses:
                return  # Streamable HTTP MCP requires protocol headers.
        except (URLError, TimeoutError):
            pass
        time.sleep(0.2)
    raise RuntimeError("Controlled service readiness timed out")


@contextmanager
def controlled_services(repo, directory, env, enabled):
    if not enabled:
        yield
        return
    host = env.get("NEXENT_TEST_ASSETS_CONTAINER_HOST", "").strip()
    mcp_host = env.get("NEXENT_TEST_MCP_CONTAINER_HOST", "").strip() or host
    if not host or not mcp_host:
        raise RuntimeError("Configure container-reachable controlled service hosts explicitly")
    processes, handles = [], []
    try:
        (directory / "runtime").mkdir(parents=True, exist_ok=True)
        for name, suffix, ready_path in (("test-assets", "ASSETS", "/health"), ("test-mcp", "MCP", "/mcp")):
            port = free_port()
            log_path = directory / "logs" / f"{name}.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            output = log_path.open("w", encoding="utf-8")
            handles.append(output)
            variable = "NEXENT_TEST_API_WIRE_LOG" if suffix == "ASSETS" else "NEXENT_TEST_MCP_WIRE_LOG"
            env[variable] = str(directory / "runtime" / f"{name}-wire.jsonl")
            # Inherit the worker process group so its timeout kills all services too.
            process = subprocess.Popen([sys.executable, str(repo / "test-e2e/infra/environment/services" / name / "server.py"),
                                        "--host", "0.0.0.0", "--port", str(port)],
                                       cwd=repo, env=env, stdout=output, stderr=subprocess.STDOUT)
            processes.append(process)
            wait_ready(f"http://127.0.0.1:{port}{ready_path}", process,
                       accepted_statuses=(200, 400, 405, 406) if suffix == "MCP" else (200,))
            endpoint = "/mcp" if suffix == "MCP" else ""
            advertised_host = mcp_host if suffix == "MCP" else host
            env[f"NEXENT_TEST_{suffix}_URL"] = f"http://{advertised_host}:{port}{endpoint}"
            env[f"NEXENT_TEST_{suffix}_LOCAL_URL"] = f"http://127.0.0.1:{port}{endpoint}"
        yield
    finally:
        errors = []
        for process in reversed(processes):
            try:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
            except Exception as exc:
                errors.append(type(exc).__name__)
        for handle in handles:
            handle.close()
        if errors:
            raise RuntimeError("Controlled service shutdown failed: " + ", ".join(errors))
