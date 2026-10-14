"""Fidelity-test bootstrap for the ext-knowledge mock service.

Assembles a complete temporary copy of the mock (source + seeds, plus the
AIDP mock and its graph JSON taken from the SAME checkout) before importing
anything, points every state file at session-private paths, and only then
loads the server module and serves it on an ephemeral 127.0.0.1 port in a
background thread. Nothing in the source tree — and no separately deployed
instance — is ever read or written at runtime, so parallel file-level
subprocess runs (run_all_test.py) and xdist workers each get an isolated
session. Every test starts from a full ``POST /_reset`` (route sets + AIDP
data, failure counters and runtime knobs).

Fidelity tests then drive the REAL product adapters (DataMateClient,
dify/idata/ragflow/haotian services) against that live server, so
adapter-contract drift shows up here instead of in a late E2E run.

sys.path / env-var setup mirrors the sibling aidp conftest, with one
addition: the aidp conftest stubs the ``nexent`` package with MagicMock
modules when it is imported first in a minimal environment, which would
poison our real-SDK imports. We drop the stub, try the real SDK, and
restore an identical stub when the real import is unavailable, so the aidp
tests keep working either way. Unlike the previous revision, adapter-level
tests then FAIL (not skip) when the real SDK is missing — a skipped
adapter test must never be counted as a green fidelity run.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import httpx
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
BACKEND_ROOT = os.path.join(PROJECT_ROOT, "backend")
SDK_ROOT = os.path.join(PROJECT_ROOT, "sdk")


def _prefer_checkout_modules() -> None:
    """Resolve backend and nexent imports to THIS checkout, process-local.

    The shared WSL venv binds the nexent SDK and the backend as PEP 660
    editable installs pointing at another worktree; their meta-path finders
    shadow every sys.path entry. Fidelity must exercise the adapters from
    THIS checkout, so the editable finders are dropped for this process
    only (the venv itself is never modified) and both checkout paths are
    placed on sys.path ahead of anything else.
    """
    for finder in list(sys.meta_path):
        module = type(finder).__module__.lower()
        name = type(finder).__name__.lower()
        if "editable" in module or "editable" in name:
            sys.meta_path.remove(finder)
    for key in [k for k in sys.modules if k == "nexent" or k.startswith("nexent.")]:
        del sys.modules[key]
    for _path in (BACKEND_ROOT, SDK_ROOT, PROJECT_ROOT):
        if _path not in sys.path:
            sys.path.insert(0, _path)


_prefer_checkout_modules()

MOCK_SOURCE = Path(PROJECT_ROOT) / "test-e2e" / "infra" / "mock-services" / "ext-knowledge-mock"
AIDP_SOURCE = Path(PROJECT_ROOT) / "test" / "ext_components" / "aidp" / "mock_servers"

# Exactly what the temporary service copy contains (mirrors build_context.py).
MOCK_COPY_FILES = (
    "server.py", "control.py", "mock_common.py",
    "datamate_mock.py", "dify_mock.py", "ragflow_mock.py",
    "idata_mock.py", "haotian_mock.py", "assets_mock.py",
    "fault_provider_mock.py",
)
SEED_FILES = ("assets.json", "datamate.json", "dify.json", "haotian.json", "idata.json", "ragflow.json")
AIDP_COPY_FILES = ("aidp_mgmt_mock_server.py", "graph_config_template_chinese.json")

# Ensure env vars are set so consts.const can load without a .env file
# (same list as the sibling aidp conftest).
for _var in (
    "POSTGRES_HOST", "POSTGRES_USER", "POSTGRES_PASSWORD",
    "POSTGRES_DB", "POSTGRES_PORT", "NEXENT_POSTGRES_PASSWORD",
    "MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY",
    "MINIO_REGION", "MINIO_DEFAULT_BUCKET",
):
    os.environ.setdefault(_var, "test")


def _install_nexent_stub() -> None:
    """Replicate the sibling aidp conftest's nexent stub verbatim."""
    if "nexent" in sys.modules:
        return
    _nexent = ModuleType("nexent")
    _nexent.__path__ = []
    sys.modules["nexent"] = _nexent
    _nexent_utils = ModuleType("nexent.utils")
    _nexent_utils.__path__ = []
    sys.modules["nexent.utils"] = _nexent_utils
    _http_mgr = ModuleType("nexent.utils.http_client_manager")
    _http_mgr.http_client_manager = MagicMock()
    sys.modules["nexent.utils.http_client_manager"] = _http_mgr
    _nexent_storage = ModuleType("nexent.storage")
    _nexent_storage.__path__ = []
    sys.modules["nexent.storage"] = _nexent_storage
    _storage_factory = ModuleType("nexent.storage.storage_client_factory")
    _storage_factory.create_storage_client_from_config = MagicMock()

    class _MinIOStorageConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    _storage_factory.MinIOStorageConfig = _MinIOStorageConfig
    sys.modules["nexent.storage.storage_client_factory"] = _storage_factory


def _load_real_nexent() -> bool:
    """Make the REAL nexent SDK importable for adapter-level tests.

    Returns False (leaving a working module state behind) when the real SDK
    cannot be imported in this environment; adapter-level tests then fail
    with an explicit blocker instead of being skipped green.
    """
    root = sys.modules.get("nexent")
    stubbed = root is not None and not hasattr(root, "__file__")
    if stubbed:
        for key in [k for k in sys.modules if k == "nexent" or k.startswith("nexent.")]:
            del sys.modules[key]
    try:
        from nexent.utils.http_client_manager import http_client_manager  # noqa: F401
        return True
    except Exception:
        if stubbed:
            _install_nexent_stub()
        return False


NEXENT_REAL = _load_real_nexent()


def _repo_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _copy_into(source_dir: Path, names: tuple[str, ...], target_dir: Path) -> None:
    for name in names:
        source = source_dir / name
        if not source.is_file():
            raise RuntimeError(f"fidelity copy is incomplete: {source} is missing")
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target_dir / name)


def _session_identity(mock_copy: Path, aidp_copy: Path) -> dict[str, str]:
    """Session-owned identity, mirroring build_context.py's manifest digest."""
    digest = hashlib.sha256()
    for directory, names in (
        (mock_copy, MOCK_COPY_FILES),
        (mock_copy / "seeds", SEED_FILES),
        (aidp_copy, AIDP_COPY_FILES),
    ):
        for name in names:
            data = (directory / name).read_bytes()
            digest.update(name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(hashlib.sha256(data).digest())
    return {
        "run_id": f"fidelity-{uuid.uuid4().hex[:8]}",
        "source_revision": _repo_head(),
        "build_manifest_sha256": digest.hexdigest(),
    }


def _load_server_module(server_file: Path):
    spec = importlib.util.spec_from_file_location("ext_knowledge_mock_server", server_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _UvicornThread:
    """uvicorn bound to an ephemeral port, serving in a daemon thread."""

    def __init__(self, app):
        import uvicorn

        self._server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self.port = None

    def start(self, timeout: float = 30.0) -> None:
        self._thread.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._server.started and self._server.servers:
                self.port = self._server.servers[0].sockets[0].getsockname()[1]
                return
            if not self._thread.is_alive():
                raise RuntimeError("ext-knowledge mock server thread exited during startup")
            time.sleep(0.05)
        raise RuntimeError("ext-knowledge mock server did not start in time")

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)
        if self._thread.is_alive():
            raise RuntimeError("ext-knowledge mock server thread did not stop in time")


@pytest.fixture(scope="session")
def expected_identity(mock_server):
    """Identity values the session-owned instance must report."""
    return globals()["_SESSION_IDENTITY"]


@pytest.fixture(scope="session")
def mock_server():
    workdir = Path(tempfile.mkdtemp(prefix="ext-knowledge-fidelity-"))
    mock_copy = workdir / "mock"
    aidp_copy = workdir / "aidp"
    _copy_into(MOCK_SOURCE, MOCK_COPY_FILES, mock_copy)
    _copy_into(MOCK_SOURCE / "seeds", SEED_FILES, mock_copy / "seeds")
    _copy_into(AIDP_SOURCE, AIDP_COPY_FILES, aidp_copy)

    identity = _session_identity(mock_copy, aidp_copy)
    globals()["_SESSION_IDENTITY"] = identity

    # Import-time environment: the server module loads the AIDP app (which
    # captures AIDP_MOCK_STATE_FILE) while these are set; they are restored
    # right after the import so sibling sessions in the same process are
    # unaffected. The identity variables are read per-request by the control
    # plane, so they stay for the whole session.
    import_env = {
        "EXT_KNOWLEDGE_AIDP_MOCK_PATH": str(aidp_copy / "aidp_mgmt_mock_server.py"),
        "AIDP_MOCK_STATE_FILE": str(workdir / "aidp-state" / "knowledge_bases.json"),
    }
    saved = {key: os.environ.get(key) for key in import_env}
    os.environ.update(import_env)
    try:
        server_module = _load_server_module(mock_copy / "server.py")
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    identity_env = {
        "EXT_KNOWLEDGE_MOCK_RUN_ID": identity["run_id"],
        "EXT_KNOWLEDGE_SOURCE_REVISION": identity["source_revision"],
        "EXT_KNOWLEDGE_BUILD_MANIFEST_SHA256": identity["build_manifest_sha256"],
    }
    saved_identity = {key: os.environ.get(key) for key in identity_env}
    os.environ.update(identity_env)

    runner = _UvicornThread(server_module.app)
    runner.start()
    base_url = f"http://127.0.0.1:{runner.port}"
    try:
        with httpx.Client(base_url=base_url, timeout=15) as probe:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    if probe.get("/health").status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("ext-knowledge mock never became healthy")
        yield runner
    finally:
        runner.stop()
        shutil.rmtree(workdir, ignore_errors=True)
        for key, value in saved_identity.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.fixture(scope="session")
def mock_base_url(mock_server) -> str:
    return f"http://127.0.0.1:{mock_server.port}"


@pytest.fixture
def http_client(mock_base_url):
    with httpx.Client(base_url=mock_base_url, timeout=15) as client:
        yield client


@pytest.fixture(autouse=True)
def _reset_all_state(mock_base_url):
    """Fresh seed state (route sets + AIDP data/faults/knobs) per test.

    The wire log is cleared alongside the state so request records from one
    test can never leak into the next (design §7 requires per-test state,
    fault and wire reset; /_reset alone does not touch the wire log).
    """
    with httpx.Client(base_url=mock_base_url, timeout=15) as client:
        response = client.post("/_reset")
        assert response.status_code == 200, response.text
        cleared = client.post("/_wire-log/clear")
        assert cleared.status_code == 200, cleared.text


@pytest.fixture(scope="session")
def require_real_nexent():
    if not NEXENT_REAL:
        pytest.fail(
            "real nexent SDK is not importable in this environment; adapter "
            "fidelity cannot be verified green here",
            pytrace=False,
        )
