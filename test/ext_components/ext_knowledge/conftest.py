"""Fidelity-test bootstrap for the ext-knowledge mock service.

Loads the real mock server (test/mock-services/ext-knowledge-mock/server.py)
via importlib, runs it with uvicorn on an ephemeral port in a background
thread, and resets all state before every test. Fidelity tests then drive
the REAL product adapters (DataMateClient, dify/idata/ragflow/haotian
services) against that live server, so adapter-contract drift shows up here
instead of in a late E2E run.

sys.path / env-var setup mirrors the sibling aidp conftest, with one
addition: the aidp conftest stubs the ``nexent`` package with MagicMock
modules when it is imported first in a minimal environment, which would
poison our real-SDK imports. We drop the stub, import the real SDK, and
restore an identical stub when the real import is unavailable, so the aidp
tests keep working either way.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import threading
import time
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import httpx
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
BACKEND_ROOT = os.path.join(PROJECT_ROOT, "backend")
for _path in (BACKEND_ROOT, PROJECT_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

MOCK_DIR = Path(PROJECT_ROOT) / "test" / "mock-services" / "ext-knowledge-mock"
if str(MOCK_DIR) not in sys.path:
    sys.path.insert(0, str(MOCK_DIR))

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
    cannot be imported in this environment; adapter-level tests then skip.
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


def _load_server_module():
    spec = importlib.util.spec_from_file_location(
        "ext_knowledge_mock_server", MOCK_DIR / "server.py"
    )
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
            time.sleep(0.05)
        raise RuntimeError("ext-knowledge mock server did not start in time")

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)


@pytest.fixture(scope="session")
def mock_server():
    server_module = _load_server_module()
    runner = _UvicornThread(server_module.app)
    runner.start()
    base_url = f"http://127.0.0.1:{runner.port}"
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
    runner.stop()


@pytest.fixture(scope="session")
def mock_base_url(mock_server) -> str:
    return f"http://127.0.0.1:{mock_server.port}"


@pytest.fixture()
def http_client(mock_base_url):
    with httpx.Client(base_url=mock_base_url, timeout=15) as client:
        yield client


@pytest.fixture(autouse=True)
def _reset_all_state(mock_base_url):
    """Fresh seed state (route sets + AIDP) and a clean failure plan per test."""
    with httpx.Client(base_url=mock_base_url, timeout=15) as client:
        response = client.post("/_reset")
        assert response.status_code == 200, response.text


@pytest.fixture(scope="session")
def require_real_nexent():
    if not NEXENT_REAL:
        pytest.skip("real nexent SDK not importable in this environment")
