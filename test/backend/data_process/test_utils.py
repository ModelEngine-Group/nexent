"""
Focused tests for backend.data_process.utils.

Targets the public async helpers (`get_task_info`, `get_task_details`) and the
small parsing helpers `_parse_failure_info` / `get_all_task_ids_from_redis`.

The data_process package requires a heavy set of dependencies (celery, ray,
consts, services.redis_service, etc.), so this module installs minimal stubs
*before* importing backend.data_process.utils. We deliberately do NOT call
`import_tasks_with_fake_ray` from `test_tasks.py` because that helper reloads
celery — which fails when sibling tests have already installed MagicMock
versions of the celery.* submodules.
"""
import asyncio
import importlib
import sys
import types
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest


def _ensure_stubs(monkeypatch):
    """Install minimal stubs so `backend.data_process.utils` can be imported."""
    # Stub ray (utils never touches ray, but the package __init__ chains through
    # tasks → app → utils, so we still need it).
    fake_ray = types.ModuleType("ray")
    fake_ray.is_initialized = lambda: False
    fake_ray.init = lambda **kw: None
    fake_ray.get = lambda ref, *a, **kw: ref
    fake_ray.remote = lambda **kw: (lambda obj: obj)
    monkeypatch.setitem(sys.modules, "ray", fake_ray)

    # Stub celery.result with AsyncResult and allow_join_result (utils.py imports
    # both via `from celery.result import AsyncResult`).
    celery_result_mod = types.ModuleType("celery.result")

    @contextmanager
    def _allow_join_result():
        yield

    celery_result_mod.allow_join_result = _allow_join_result
    # AsyncResult is patched per-test by `_AsyncResultPatcher`.
    celery_result_mod.AsyncResult = lambda task_id, app=None: None
    monkeypatch.setitem(sys.modules, "celery.result", celery_result_mod)

    # Provide a thin celery package so `from celery.result import AsyncResult`
    # above resolves, and `from celery import Task, chain, states, group, chord`
    # (which tasks.py imports) also resolves.
    fake_celery = types.ModuleType("celery")
    fake_celery.result = celery_result_mod
    fake_celery.Task = type("Task", (), {})
    fake_celery.chain = lambda *args, **kwargs: None
    fake_celery.group = lambda *args, **kwargs: []
    fake_celery.chord = lambda *args, **kwargs: (lambda callback: None)
    fake_celery.states = types.SimpleNamespace(
        PENDING="PENDING", STARTED="STARTED", SUCCESS="SUCCESS",
        FAILURE="FAILURE", RETRY="RETRY", REVOKED="REVOKED",
    )
    fake_celery.Celery = lambda *args, **kwargs: None
    fake_celery.backends = types.SimpleNamespace(base=types.SimpleNamespace(
        DisabledBackend=type("DisabledBackend", (), {})
    ))
    fake_celery.signals = types.SimpleNamespace(
        worker_init=MagicMock(),
        worker_process_init=MagicMock(),
        worker_ready=MagicMock(),
        worker_shutting_down=MagicMock(),
        task_prerun=MagicMock(),
        task_postrun=MagicMock(),
        task_failure=MagicMock(),
    )
    monkeypatch.setitem(sys.modules, "celery", fake_celery)
    monkeypatch.setitem(sys.modules, "celery.backends.base",
                        fake_celery.backends.base)
    monkeypatch.setitem(sys.modules, "celery.signals", fake_celery.signals)
    # celery.exceptions needs to expose every name that celery's own submodules
    # import from it. celery.platforms does
    #     `from .exceptions import SecurityError, SecurityWarning, reraise`
    # and celery.exceptions itself re-exports those, so if a sibling test forces
    # celery.result to reload, this stub must contain them or that reload fails.
    monkeypatch.setitem(sys.modules, "celery.exceptions", types.SimpleNamespace(
        Retry=type("Retry", (Exception,), {}),
        SecurityError=type("SecurityError", (Exception,), {}),
        SecurityWarning=type("SecurityWarning", (Warning,), {}),
        reraise=type("reraise", (), {}),
    ))

    # backend.data_process.app: utils.py does `from .app import app as celery_app`.
    if "backend.data_process.app" not in sys.modules:
        fake_dp_app = types.ModuleType("backend.data_process.app")
        fake_dp_app.app = object()
        monkeypatch.setitem(sys.modules, "backend.data_process.app", fake_dp_app)

    # Stub backend.data_process.tasks: __init__.py does `from .tasks import ...`,
    # and tasks.py pulls in heavy deps (nexent.data_process.core → unstructured_inference).
    # We replace the module with a stub that exposes the names __init__ imports.
    fake_dp_tasks = types.ModuleType("backend.data_process.tasks")
    fake_dp_tasks.process = MagicMock()
    fake_dp_tasks.forward = MagicMock()
    fake_dp_tasks.process_and_forward = MagicMock()
    fake_dp_tasks.process_sync = MagicMock()
    monkeypatch.setitem(sys.modules, "backend.data_process.tasks", fake_dp_tasks)

    # Ensure backend.data_process package is registered so the relative imports
    # in tasks/utils resolve cleanly.
    if "backend.data_process" not in sys.modules:
        import os as _os
        backend_dp_pkg = types.ModuleType("backend.data_process")
        # Compute the directory containing backend/data_process/ so submodule
        # imports can locate utils.py on disk.
        here = _os.path.dirname(_os.path.abspath(__file__))
        backend_dp_pkg.__path__ = [_os.path.normpath(_os.path.join(
            here, '..', '..', '..', 'backend', 'data_process'))]
        monkeypatch.setitem(sys.modules, "backend.data_process", backend_dp_pkg)

    # services.redis_service: utils.py imports it lazily inside get_task_info
    # to call get_redis_service().get_progress_info(...).
    fake_redis_service = types.ModuleType("services.redis_service")
    fake_redis_service.get_redis_service = lambda: types.SimpleNamespace(
        get_progress_info=lambda tid: None,
    )
    monkeypatch.setitem(sys.modules, "services.redis_service", fake_redis_service)
    monkeypatch.setitem(sys.modules, "services", types.ModuleType("services"))

    return {
        "celery_result": celery_result_mod,
        "redis_service": fake_redis_service,
    }


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    """Auto-applied fixture: installs stubs and forces utils to reload."""
    stubs = _ensure_stubs(monkeypatch)
    # Force a fresh import of utils so the lazy imports pick up our stubs.
    sys.modules.pop("backend.data_process.utils", None)
    import backend.data_process.utils  # noqa: F401  (intentional reload)
    yield stubs


# ----------------------------------------------------------------------
# Test helpers
# ----------------------------------------------------------------------


class _FakeAsyncResult:
    """Stand-in for celery.result.AsyncResult with attribute-style access.

    Each attribute returns whatever the test sets on the instance, defaulting
    to values matching the production code's "no info / not failed / not
    successful / not started" path.
    """

    def __init__(self, **fields):
        self._fields = fields

    def __getattr__(self, name):
        if name in self._fields:
            value = self._fields[name]
            if callable(value):
                return value
            return value
        if name == "status":
            return None
        if name == "info":
            return None
        if name == "result":
            return None
        if name in ("failed", "successful"):
            return lambda: False
        raise AttributeError(name)


class _AsyncResultPatcher:
    """Context manager that swaps celery.result.AsyncResult for a fake.

    Also rebinds the name in already-imported modules (utils.py does
    `from celery.result import AsyncResult`).
    """

    def __init__(self, result_obj):
        self._result_obj = result_obj
        self._orig_outer = None
        self._orig_in_utils = None

    def __enter__(self):
        celery_result = sys.modules["celery.result"]
        self._orig_outer = celery_result.AsyncResult
        celery_result.AsyncResult = lambda task_id, app=None: self._result_obj
        # Rebind in already-imported utils module (it did `from ... import`)
        utils_mod = sys.modules.get("backend.data_process.utils")
        if utils_mod is not None:
            self._orig_in_utils = utils_mod.AsyncResult
            utils_mod.AsyncResult = celery_result.AsyncResult
        return utils_mod

    def __exit__(self, *args):
        celery_result = sys.modules["celery.result"]
        celery_result.AsyncResult = self._orig_outer
        utils_mod = sys.modules.get("backend.data_process.utils")
        if utils_mod is not None and self._orig_in_utils is not None:
            utils_mod.AsyncResult = self._orig_in_utils


@pytest.fixture
def patch_async_result():
    """Returns a function that creates a `_AsyncResultPatcher` for a fake."""

    def _make(result_obj):
        return _AsyncResultPatcher(result_obj)

    return _make


# ----------------------------------------------------------------------
# _parse_failure_info
# ----------------------------------------------------------------------


def test_parse_failure_info_dict_passthrough(monkeypatch):

    from backend.data_process.utils import _parse_failure_info

    info = {"message": "x"}
    parsed, plain = _parse_failure_info(info)
    assert parsed == info
    assert plain is None


def test_parse_failure_info_none_returns_none_pair(monkeypatch):

    from backend.data_process.utils import _parse_failure_info

    assert _parse_failure_info(None) == (None, None)


def test_parse_failure_info_empty_string_returns_none_pair(monkeypatch):

    from backend.data_process.utils import _parse_failure_info

    assert _parse_failure_info("") == (None, None)
    assert _parse_failure_info("   ") == (None, None)


def test_parse_failure_info_json_dict_returns_parsed(monkeypatch):

    from backend.data_process.utils import _parse_failure_info

    parsed, plain = _parse_failure_info('{"message": "boom"}')
    assert parsed == {"message": "boom"}
    assert plain is None


def test_parse_failure_info_json_non_dict_returns_plain(monkeypatch):

    from backend.data_process.utils import _parse_failure_info

    parsed, plain = _parse_failure_info("[1, 2, 3]")
    assert parsed is None
    assert plain == "[1, 2, 3]"


def test_parse_failure_info_non_json_returns_plain(monkeypatch):

    from backend.data_process.utils import _parse_failure_info

    parsed, plain = _parse_failure_info("plain failure text")
    assert parsed is None
    assert plain == "plain failure text"


def test_parse_failure_info_strips_whitespace(monkeypatch):

    from backend.data_process.utils import _parse_failure_info

    parsed, plain = _parse_failure_info('   {"message": "ok"}   ')
    assert parsed == {"message": "ok"}


def test_parse_failure_info_invalid_type_returns_stringified(monkeypatch):

    from backend.data_process.utils import _parse_failure_info

    parsed, plain = _parse_failure_info(42)
    assert parsed is None
    assert plain == "42"


# ----------------------------------------------------------------------
# get_all_task_ids_from_redis
# ----------------------------------------------------------------------


def test_get_all_task_ids_decodes_bytes_and_strings(monkeypatch):

    from backend.data_process.utils import get_all_task_ids_from_redis

    redis_client = MagicMock()
    redis_client.scan_iter.return_value = iter([
        b"celery-task-meta-aaa",
        "celery-task-meta-bbb",
    ])

    assert get_all_task_ids_from_redis(redis_client) == ["aaa", "bbb"]


def test_get_all_task_ids_skips_unrelated_keys(monkeypatch):

    from backend.data_process.utils import get_all_task_ids_from_redis

    redis_client = MagicMock()
    redis_client.scan_iter.return_value = iter([
        "unrelated-key",
        b"celery-task-meta-keep",
        b"not-meta-x",
    ])

    assert get_all_task_ids_from_redis(redis_client) == ["keep"]


def test_get_all_task_ids_handles_exception(monkeypatch):

    from backend.data_process.utils import get_all_task_ids_from_redis

    redis_client = MagicMock()
    redis_client.scan_iter.side_effect = RuntimeError("boom")

    assert get_all_task_ids_from_redis(redis_client) == []


def test_get_all_task_ids_empty_redis(monkeypatch):

    from backend.data_process.utils import get_all_task_ids_from_redis

    redis_client = MagicMock()
    redis_client.scan_iter.return_value = iter([])

    assert get_all_task_ids_from_redis(redis_client) == []


# ----------------------------------------------------------------------
# get_task_info — backend_available / status parsing
# ----------------------------------------------------------------------


def test_get_task_info_pending_status(monkeypatch, patch_async_result):

    fake = _FakeAsyncResult(status=None)
    with patch_async_result(fake) as utils:
        result = asyncio.run(utils.get_task_info("task-1"))
    assert result["status"] == "PENDING"
    assert result["id"] == "task-1"
    assert result["error"] is None


def test_get_task_info_pending_uses_provided_status(monkeypatch, patch_async_result):

    fake = _FakeAsyncResult(status="STARTED")
    with patch_async_result(fake) as utils:
        result = asyncio.run(utils.get_task_info("task-1"))
    assert result["status"] == "STARTED"


def test_get_task_info_disabled_backend_error(monkeypatch, patch_async_result):
    """AttributeError with 'DisabledBackend' on second status access → backend_available = False."""


    call_count = [0]

    class _BrokenResult(_FakeAsyncResult):
        def __getattr__(self, name):
            if name == "status":
                call_count[0] += 1
                n = call_count[0]
                if n >= 2:
                    raise AttributeError("DisabledBackend cannot be used here")
                return None
            return super().__getattr__(name)

    fake = _BrokenResult()
    with patch_async_result(fake) as utils:
        result = asyncio.run(utils.get_task_info("task-1"))
    assert "Result backend disabled" in result["error"]


def test_get_task_info_non_disabled_attribute_error(monkeypatch, patch_async_result):

    call_count = [0]

    class _BrokenResult(_FakeAsyncResult):
        def __getattr__(self, name):
            if name == "status":
                call_count[0] += 1
                if call_count[0] >= 2:
                    raise AttributeError("something else broke")
                return None
            return super().__getattr__(name)

    fake = _BrokenResult()
    with patch_async_result(fake) as utils:
        result = asyncio.run(utils.get_task_info("task-1"))
    assert "Backend error" in result["error"]


def test_get_task_info_generic_status_error(monkeypatch, patch_async_result):
    """Generic Exception on second status access → 'Status access error' message."""


    call_count = [0]

    class _BrokenResult(_FakeAsyncResult):
        def __getattr__(self, name):
            if name == "status":
                call_count[0] += 1
                if call_count[0] >= 2:
                    raise RuntimeError("redis dead")
                return None
            return super().__getattr__(name)

    fake = _BrokenResult()
    with patch_async_result(fake) as utils:
        result = asyncio.run(utils.get_task_info("task-1"))
    assert "Status access error" in result["error"]


# ----------------------------------------------------------------------
# get_task_info — metadata extraction from result.info
# ----------------------------------------------------------------------


def test_get_task_info_metadata_dict_extraction(monkeypatch, patch_async_result):

    metadata = {
        "task_name": "process",
        "start_time": 1700000000,
        "index_name": "kb-1",
        "source": "/data/file.pdf",
        "original_filename": "file.pdf",
        "file_id": "fid-metadata",
        "total_chunks": 100,
        "processed_chunks": 25,
    }
    fake = _FakeAsyncResult(status="STARTED", info=metadata)
    with patch_async_result(fake) as utils:
        result = asyncio.run(utils.get_task_info("task-1"))
    assert result["task_name"] == "process"
    assert result["created_at"] == 1700000000
    assert result["index_name"] == "kb-1"
    assert result["path_or_url"] == "/data/file.pdf"
    assert result["original_filename"] == "file.pdf"
    assert result["file_id"] == "fid-metadata"
    assert result["total_chunks"] == 100
    assert result["processed_chunks"] == 25


def test_get_task_info_redis_progress_overrides_metadata(
    monkeypatch, patch_async_result
):

    metadata = {"total_chunks": 100, "processed_chunks": 25}
    fake = _FakeAsyncResult(status="STARTED", info=metadata)

    rs = sys.modules["services.redis_service"]
    original_get = rs.get_redis_service
    rs.get_redis_service = lambda: types.SimpleNamespace(
        get_progress_info=lambda tid: {"processed_chunks": 80, "total_chunks": 100}
    )

    try:
        with patch_async_result(fake) as utils:
            result = asyncio.run(utils.get_task_info("task-1"))
    finally:
        rs.get_redis_service = original_get

    assert result["processed_chunks"] == 80
    assert result["total_chunks"] == 100


def test_get_task_info_redis_progress_failure_falls_back(
    monkeypatch, patch_async_result
):

    metadata = {"total_chunks": 10, "processed_chunks": 3}
    fake = _FakeAsyncResult(status="STARTED", info=metadata)

    class _Boom:
        def get_progress_info(self, task_id):
            raise RuntimeError("redis down")

    rs = sys.modules["services.redis_service"]
    original_get = rs.get_redis_service
    rs.get_redis_service = lambda: _Boom()

    try:
        with patch_async_result(fake) as utils:
            result = asyncio.run(utils.get_task_info("task-1"))
    finally:
        rs.get_redis_service = original_get

    assert result["processed_chunks"] == 3
    assert result["total_chunks"] == 10


def test_get_task_info_ignores_non_dict_info(monkeypatch, patch_async_result):

    fake = _FakeAsyncResult(status="STARTED", info="some-string-info")
    with patch_async_result(fake) as utils:
        result = asyncio.run(utils.get_task_info("task-1"))
    assert result["task_name"] == ""
    assert result["index_name"] == ""


def test_get_task_info_metadata_access_error(monkeypatch, patch_async_result):

    class _BrokenResult(_FakeAsyncResult):
        @property
        def info(self):
            raise RuntimeError("redis gone")

    with patch_async_result(_BrokenResult(status="STARTED")) as utils:
        result = asyncio.run(utils.get_task_info("task-1"))
    assert "Metadata access error" in result["error"]


# ----------------------------------------------------------------------
# get_task_info — failed-task branch
# ----------------------------------------------------------------------


def test_get_task_info_failed_with_structured_info(monkeypatch, patch_async_result):

    failure_info = {
        "message": "kaboom",
        "index_name": "kb-x",
        "task_name": "process",
        "source": "/x.txt",
        "original_filename": "x.txt",
        "file_id": "fid-failed",
    }
    fake = _FakeAsyncResult(
        status="FAILURE",
        info=failure_info,
        result=failure_info,
        failed=lambda: True,
        successful=lambda: False,
    )
    with patch_async_result(fake) as utils:
        result = asyncio.run(utils.get_task_info("task-1"))
    assert result["status"] == "FAILURE"
    assert result["error"] == "kaboom"
    assert result["index_name"] == "kb-x"
    assert result["task_name"] == "process"
    assert result["path_or_url"] == "/x.txt"
    assert result["original_filename"] == "x.txt"
    assert result["file_id"] == "fid-failed"


def test_get_task_info_failed_with_plain_text_info(monkeypatch, patch_async_result):

    fake = _FakeAsyncResult(
        status="FAILURE",
        info="plain failure",
        result="plain failure",
        failed=lambda: True,
        successful=lambda: False,
    )
    with patch_async_result(fake) as utils:
        result = asyncio.run(utils.get_task_info("task-1"))
    assert result["status"] == "FAILURE"
    assert result["error"] == "plain failure"


def test_get_task_info_failed_fallback_to_result_str(monkeypatch, patch_async_result):
    """info=None + failed=True → fallback uses result.result (string)."""

    fake = _FakeAsyncResult(
        status="FAILURE",
        info=None,
        result="string-result",
        failed=lambda: True,
        successful=lambda: False,
    )
    with patch_async_result(fake) as utils:
        result = asyncio.run(utils.get_task_info("task-1"))
    assert result["error"] == "string-result"


def test_get_task_info_failed_fallback_unknown_error(monkeypatch, patch_async_result):
    """info=None + result=None → fallback uses 'Unknown error'."""

    fake = _FakeAsyncResult(
        status="FAILURE",
        info=None,
        result=None,
        failed=lambda: True,
        successful=lambda: False,
    )
    with patch_async_result(fake) as utils:
        result = asyncio.run(utils.get_task_info("task-1"))
    assert result["error"] == "Unknown error"


def test_get_task_info_failed_outer_parse_error(monkeypatch, patch_async_result):
    """If _parse_failure_info itself raises, fall back to result.result."""

    fake = _FakeAsyncResult(
        status="FAILURE",
        info={"message": "x"},
        result="fallback-string",
        failed=lambda: True,
        successful=lambda: False,
    )

    def _raise(_info):
        raise RuntimeError("parse-failure-info exploded")

    utils_mod = sys.modules["backend.data_process.utils"]
    original = utils_mod._parse_failure_info
    utils_mod._parse_failure_info = _raise
    try:
        with patch_async_result(fake):
            result = asyncio.run(utils_mod.get_task_info("task-1"))
    finally:
        utils_mod._parse_failure_info = original

    assert result["error"] == "fallback-string"


# ----------------------------------------------------------------------
# get_task_info — successful-task branch
# ----------------------------------------------------------------------


def test_get_task_info_successful_with_result_fields(monkeypatch, patch_async_result):

    success_result = {
        "chunks_count": 5,
        "processing_time": 1.2,
        "storage_time": 0.4,
        "es_result": {"ok": True},
        "file_id": "fid-success",
        "ignored": True,
    }
    fake = _FakeAsyncResult(
        status="SUCCESS",
        info={"task_name": "process"},
        result=success_result,
        failed=lambda: False,
        successful=lambda: True,
    )
    with patch_async_result(fake) as utils:
        result = asyncio.run(utils.get_task_info("task-1"))
    assert result["chunks_count"] == 5
    assert result["processing_time"] == 1.2
    assert result["storage_time"] == 0.4
    assert result["es_result"] == {"ok": True}
    assert result["file_id"] == "fid-success"
    assert "ignored" not in result


def test_get_task_info_successful_non_dict_result_ignored(monkeypatch, patch_async_result):

    fake = _FakeAsyncResult(
        status="SUCCESS",
        info={"task_name": "process"},
        result=["list", "result"],
        failed=lambda: False,
        successful=lambda: True,
    )
    with patch_async_result(fake) as utils:
        result = asyncio.run(utils.get_task_info("task-1"))
    assert "chunks_count" not in result
    assert "processing_time" not in result


# ----------------------------------------------------------------------
# get_task_info — run_in_executor failure paths
# ----------------------------------------------------------------------


def test_get_task_info_legacy_value_error(monkeypatch, patch_async_result):
    """ValueError with the legacy marker → forcibly marked FAILURE."""

    real_message = "Exception information must include the exception type"

    async def _raise_legacy():
        raise ValueError(real_message)

    class _FakeLoop:
        def run_in_executor(self, *a, **kw):
            return _raise_legacy()

    monkeypatch.setattr(asyncio, "get_running_loop", lambda: _FakeLoop())

    with patch_async_result(_FakeAsyncResult()) as utils:
        result = asyncio.run(utils.get_task_info("task-1"))
    assert result["status"] == "FAILURE"
    assert "Legacy task error" in result["error"]


def test_get_task_info_generic_value_error(monkeypatch, patch_async_result):
    """ValueError without the legacy marker → generic failure response."""

    async def _raise_value():
        raise ValueError("some unrelated ValueError")

    class _FakeLoop:
        def run_in_executor(self, *a, **kw):
            return _raise_value()

    monkeypatch.setattr(asyncio, "get_running_loop", lambda: _FakeLoop())

    with patch_async_result(_FakeAsyncResult()) as utils:
        result = asyncio.run(utils.get_task_info("task-1"))
    assert result["status"] == "FAILURE"
    assert "Cannot retrieve task status" in result["error"]


def test_get_task_info_outer_exception(monkeypatch, patch_async_result):
    """Generic Exception outside the executor returns a minimal FAILURE shape."""

    async def _raise_generic():
        raise RuntimeError("totally unexpected")

    class _FakeLoop:
        def run_in_executor(self, *a, **kw):
            return _raise_generic()

    monkeypatch.setattr(asyncio, "get_running_loop", lambda: _FakeLoop())

    with patch_async_result(_FakeAsyncResult()) as utils:
        result = asyncio.run(utils.get_task_info("task-1"))
    assert result["status"] == "FAILURE"
    assert "totally unexpected" in result["error"]
    assert result["created_at"] == ""


# ----------------------------------------------------------------------
# get_task_details
# ----------------------------------------------------------------------


def test_get_task_details_successful(monkeypatch, patch_async_result):

    success_result = {
        "chunks_count": 7,
        "processing_time": 0.5,
        "storage_time": 0.1,
        "es_result": {"ok": True},
        "extra": "ignored",
    }
    fake = _FakeAsyncResult(
        status="SUCCESS",
        info={"task_name": "process"},
        result=success_result,
        failed=lambda: False,
        successful=lambda: True,
    )
    with patch_async_result(fake) as utils:
        result = asyncio.run(utils.get_task_details("task-1"))
    assert result["chunks_count"] == 7
    assert result["processing_time"] == 0.5
    assert result["storage_time"] == 0.1
    assert result["es_result"] == {"ok": True}
    assert result["result"] == success_result


def test_get_task_details_non_successful(monkeypatch, patch_async_result):
    """If result is not successful, get_task_details returns the base info only."""

    fake = _FakeAsyncResult(
        status="FAILURE",
        info={"task_name": "process"},
        result=None,
        failed=lambda: True,
        successful=lambda: False,
    )
    with patch_async_result(fake) as utils:
        result = asyncio.run(utils.get_task_details("task-1"))
    assert "chunks_count" not in result
    assert "result" not in result


def test_get_task_details_successful_non_dict_result(monkeypatch, patch_async_result):
    """When successful but result is non-dict, no whitelist fields are added."""

    fake = _FakeAsyncResult(
        status="SUCCESS",
        info={"task_name": "process"},
        result="not-a-dict",
        failed=lambda: False,
        successful=lambda: True,
    )
    with patch_async_result(fake) as utils:
        result = asyncio.run(utils.get_task_details("task-1"))
    assert "result" not in result


def test_get_task_details_partial_dict_result(monkeypatch, patch_async_result):
    """Only the keys present in result are copied over."""

    fake = _FakeAsyncResult(
        status="SUCCESS",
        info={"task_name": "process"},
        result={"chunks_count": 3},
        failed=lambda: False,
        successful=lambda: True,
    )
    with patch_async_result(fake) as utils:
        result = asyncio.run(utils.get_task_details("task-1"))
    assert result["chunks_count"] == 3
    assert result["result"] == {"chunks_count": 3}
    assert "processing_time" not in result
    assert "storage_time" not in result
    assert "es_result" not in result
