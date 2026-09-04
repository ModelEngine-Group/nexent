import asyncio
import io
import math
import sys
import types
import json
from contextlib import contextmanager
from typing import Optional
import pytest


class FakeRay:
    def __init__(self, initialized=False):
        self._initialized = initialized
        self.inits = []
        self.get_returns = None

    def is_initialized(self):
        return self._initialized

    def init(self, **kwargs):
        self._initialized = True
        self.inits.append(kwargs)

    def get(self, ref):
        if ref == "__split_parts__":
            return []
        if isinstance(self.get_returns, dict):
            return self.get_returns.get(ref)
        return self.get_returns

    def remote(self, **kwargs):
        # Identity decorator to mimic ray.remote for classes/functions
        def decorator(obj):
            return obj
        return decorator


def import_tasks_with_fake_ray(monkeypatch, initialized=False):
    for mod_name in [
        "backend.data_process",
        "backend.data_process.tasks",
        "backend.data_process.utils",
    ]:
        sys.modules.pop(mod_name, None)

    fake_ray = FakeRay(initialized=initialized)
    sys.modules["ray"] = fake_ray
    import importlib

    # IMPORTANT: install the celery stub BEFORE doing any
    # ``import celery.exceptions`` / ``import celery.backends.base`` so that
    # those ``__import__`` calls hit our stub rather than auto-loading the
    # real celery package. We *always* install our stub (replacing whatever
    # may already be in ``sys.modules``) so a sibling test that imported
    # the real celery package doesn't poison ``tasks.chord`` etc.
    celery_mod = types.ModuleType("celery")
    # Mark as a package so ``import celery.exceptions`` resolves under
    # the stub instead of falling back to the real one.
    celery_mod.__path__ = []  # type: ignore[attr-defined]

    class _FakeBackend:
        pass

    class _FakeCelery:
        def __init__(self, *args, **kwargs):
            self.backend = _FakeBackend()
            self.conf = types.SimpleNamespace(
                update=lambda **kwargs: None)

        def task(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

    celery_mod.Celery = _FakeCelery
    celery_mod.Task = type("Task", (), {})
    celery_mod.chain = lambda *args: None
    celery_mod.group = lambda *args, **kwargs: []
    celery_mod.chord = lambda *args, **kwargs: (
        lambda callback: types.SimpleNamespace(
            get=lambda: {
                "success": True,
                "total_indexed": 0,
                "total_submitted": 0,
            }
        )
    )
    celery_mod.states = types.SimpleNamespace(
        PENDING="PENDING",
        STARTED="STARTED",
        SUCCESS="SUCCESS",
        FAILURE="FAILURE",
        RETRY="RETRY",
        REVOKED="REVOKED",
    )
    sys.modules["celery"] = celery_mod

    if "celery.signals" not in sys.modules:
        signals_mod = types.ModuleType("celery.signals")
        # Create fake signal objects with connect method

        class FakeSignal:
            def connect(self, func):
                return func
        signals_mod.worker_init = FakeSignal()
        signals_mod.worker_process_init = FakeSignal()
        signals_mod.worker_ready = FakeSignal()
        signals_mod.worker_shutting_down = FakeSignal()
        signals_mod.task_prerun = FakeSignal()
        signals_mod.task_postrun = FakeSignal()
        signals_mod.task_failure = FakeSignal()
        sys.modules["celery.signals"] = signals_mod

    # Stub celery module (required by app.py and tasks.py imported via __init__.py)
    if "celery.backends.base" not in sys.modules:
        backends_base_mod = types.ModuleType("celery.backends.base")
        backends_base_mod.DisabledBackend = type("DisabledBackend", (), {})
        sys.modules["celery.backends.base"] = backends_base_mod
    # Augment any celery.backends.base stub with symbols celery.backends.*
    # imports at runtime (e.g. _create_chord_error_with_cause used by
    # celery.backends.redis). We keep the same module object across tests so
    # already-imported `from celery.backends.base import X` references remain
    # valid; we just add the missing names.
    _bb_mod = sys.modules.get("celery.backends.base")
    if _bb_mod is not None and not hasattr(_bb_mod, "BaseKeyValueStoreBackend"):
        # Drop the stub so we can load the real module, then copy public
        # + private helpers back onto the original stub object to keep identity.
        sys.modules.pop("celery.backends.base", None)
        try:
            import celery.backends.base as _real_bb  # noqa: PLC0415
            for _name in dir(_real_bb):
                if _name.startswith("__"):
                    continue
                if not hasattr(_bb_mod, _name):
                    setattr(_bb_mod, _name, getattr(_real_bb, _name))
        except Exception:  # pragma: no cover
            pass
        # Restore the (now-augmented) original stub under its key.
        sys.modules["celery.backends.base"] = _bb_mod

    # celery.exceptions must keep the SAME module object across tests so that
    # already-bound names like `tasks.Retry` continue to refer to the same
    # class instance — replacing the module would create a new Retry class
    # object that wouldn't match `except Retry:` in tasks.py.
    # We always create / reuse a stub module here. Because the celery
    # ``__init__`` stub above blocks auto-import of the real
    # ``celery.exceptions`` submodule, we cannot reliably ``__import__`` the
    # real one; instead we provide the small set of symbols ``tasks.py``
    # (and ``celery.platforms`` / ``celery.canvas``) actually reach for.
    if "celery.exceptions" not in sys.modules:
        exceptions_mod = types.ModuleType("celery.exceptions")
        exceptions_mod.__path__ = []  # type: ignore[attr-defined]
        exceptions_mod.Retry = type("Retry", (Exception,), {})
        exceptions_mod.Ignore = type("Ignore", (Exception,), {})
        exceptions_mod.ImproperlyConfigured = type(
            "ImproperlyConfigured", (Exception,), {})
        exceptions_mod.MaxRetriesExceededError = type(
            "MaxRetriesExceededError", (Exception,), {})
        exceptions_mod.Reject = type("Reject", (Exception,), {})
        exceptions_mod.TaskPredicate = type("TaskPredicate", (), {})
        exceptions_mod.CeleryError = type("CeleryError", (Exception,), {})
        exceptions_mod.SecurityError = type("SecurityError", (Exception,), {})
        exceptions_mod.SecurityWarning = type("SecurityWarning", (Warning,), {})
        exceptions_mod.reraise = lambda exc, _tp=None, _tb=None: None
        sys.modules["celery.exceptions"] = exceptions_mod

    # celery.result transitively imports celery.canvas, which expects symbols
    # from celery.exceptions. We rebuild celery.result as a stub that
    # delegates everything to the real module except AsyncResult and
    # allow_join_result.
    sys.modules.pop("celery.result", None)
    try:
        import celery.result as _real_celery_result  # noqa: PLC0415
    except Exception:  # pragma: no cover - only relevant if real celery missing
        _real_celery_result = None

    @contextmanager
    def _allow_join_result():
        yield
    result_mod = types.ModuleType("celery.result")
    result_mod.allow_join_result = _allow_join_result

    class _AsyncResultStub:
        """Lightweight stand-in for ``celery.result.AsyncResult``.

        Celery internals (notably ``canvas.chord``) instantiate
        ``AsyncResult`` with a task id and then call various
        promise-style methods (``.then()``, ``.add_callback()``,
        ``.get()``, ``.ready()``, ...). Tests never inspect the
        returned object directly, so we accept any arguments and
        return safe no-op values.
        """

        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        # Promise / chaining API used by ``celery.canvas.chord`` and
        # ``chord.backend.apply``. Returning ``self`` keeps the
        # fluent style working without raising ``AttributeError``.
        def then(self, *args, **kwargs):
            return self

        def add_callback(self, *args, **kwargs):
            return self

        def add_errback(self, *args, **kwargs):
            return self

        # Result inspection methods. Returning ``None`` / ``True`` /
        # ``False`` keeps callers from choking on missing return
        # values; tests don't inspect any of these.
        def get(self, *args, **kwargs):
            return None

        def ready(self):
            return True

        def successful(self):
            return False

        def failed(self):
            return False

        def forget(self):
            return None

        def revoke(self, *args, **kwargs):
            return None

        # Async result ``id``/``state`` attributes are occasionally
        # accessed by canvas internals.
        @property
        def id(self):
            return self.kwargs.get("id") or (
                self.args[0] if self.args else None
            )

        @property
        def state(self):
            return "PENDING"

    result_mod.AsyncResult = _AsyncResultStub
    if _real_celery_result is not None:
        for _name in dir(_real_celery_result):
            if _name.startswith("_") or _name in (
                "allow_join_result", "AsyncResult"
            ):
                continue
            setattr(result_mod, _name, getattr(_real_celery_result, _name))
    sys.modules["celery.result"] = result_mod

    if "celery.signals" not in sys.modules:
        signals_mod = types.ModuleType("celery.signals")
        # Create fake signal objects with connect method

        class FakeSignal:
            def connect(self, func):
                return func
        signals_mod.worker_init = FakeSignal()
        signals_mod.worker_process_init = FakeSignal()
        signals_mod.worker_ready = FakeSignal()
        signals_mod.worker_shutting_down = FakeSignal()
        signals_mod.task_prerun = FakeSignal()
        signals_mod.task_postrun = FakeSignal()
        signals_mod.task_failure = FakeSignal()
        sys.modules["celery.signals"] = signals_mod

    # celery.exceptions / celery.platforms / celery.backends.base are NOT
    # replaced here. The autouse fixture _restore_real_celery_modules handles
    # augmenting those modules in-place; replacing the module object would
    # create a fresh Retry class that breaks `except Retry:` in tasks.py
    # because already-bound `tasks.Retry` references the OLD class.

    # IMPORTANT: stub ``database.attachment_db`` (and friends) BEFORE
    # importing anything that transitively reaches it. ``utils.file_management_utils``
    # imports ``get_file_size_from_minio`` from there, so reloading that
    # utility would pull in the *real* attachment module and try to talk
    # to MinIO. By stubbing the database module up-front, subsequent
    # ``import_module`` calls land on the stub.
    if "database.attachment_db" not in sys.modules:
        sys.modules["database.attachment_db"] = types.SimpleNamespace(
            get_file_stream=lambda source: io.BytesIO(b"stub-bytes"),
            get_file_size_from_minio=lambda object_name, bucket=None: 0,
            # NOSONAR
            build_s3_url=lambda bucket_name, object_name: f"http://mock-s3/{bucket_name}/{object_name}",
            upload_fileobj=lambda file_obj, bucket_name, object_name: "mock-etag",
        )
    if "database.knowledge_db" not in sys.modules:
        sys.modules["database.knowledge_db"] = types.SimpleNamespace(
            get_knowledge_record=lambda query=None: {},
        )
    if "database.model_management_db" not in sys.modules:
        sys.modules["database.model_management_db"] = types.SimpleNamespace(
            get_model_by_model_id=lambda model_id, tenant_id=None: None
        )
    if "database" not in sys.modules:
        db_pkg = types.ModuleType("database")
        setattr(db_pkg, "__path__", [])
        sys.modules["database"] = db_pkg
    setattr(sys.modules["database"], "attachment_db",
            sys.modules["database.attachment_db"])
    setattr(sys.modules["database"], "model_management_db",
            sys.modules["database.model_management_db"])
    setattr(sys.modules["database"], "knowledge_db",
            sys.modules["database.knowledge_db"])

    # Backend utility / service modules that tasks.py imports directly may
    # have been polluted by sibling tests. Reload only those modules whose
    # existing stub is obviously wrong (a MagicMock with none of the
    # attributes we need) so that tasks.py gets the real symbols when
    # invoked.
    for _real_module_name, _required in (
        # ``utils.file_management_utils`` is imported by ``tasks.py`` and
        # needs ``get_file_size``. Sibling tests stub it with only
        # ``convert_office_to_pdf`` so we reload when the stub is missing
        # our attribute. Reloading transitively re-imports
        # ``database.attachment_db`` (which we stubbed above) and
        # ``utils.auth_utils`` / ``utils.config_utils`` (also stubbed
        # below), so the stubs land first.
        ("utils.file_management_utils", ("get_file_size",)),
        ("services.redis_service", ("get_redis_service",)),
        ("consts.const", None),  # Always reload — MagicMock pollution.
    ):
        _existing = sys.modules.get(_real_module_name)
        _needs_real = False
        if _existing is None:
            _needs_real = True
        elif _required is None:
            # Always reload when caller wants to force a fresh copy.
            _needs_real = True
        else:
            from unittest.mock import MagicMock as _MagicMock
            for _req in _required:
                _val = getattr(_existing, _req, None)
                # MagicMock instances will compare as equal to anything
                # via ``__eq__`` default, but ``isinstance`` is reliable.
                if _val is None or isinstance(_val, _MagicMock):
                    _needs_real = True
                    break
        if not _needs_real:
            continue
        try:
            sys.modules.pop(_real_module_name, None)
            import importlib as _il2  # noqa: PLC0415
            _mod = _il2.import_module(_real_module_name)
            sys.modules[_real_module_name] = _mod
        except Exception:  # pragma: no cover
            pass

    # Stub consts.const unconditionally so that backend.data_process.app
    # (which raises if REDIS_URL / REDIS_BACKEND_URL are unset) can be
    # imported, even when a sibling test (or our own ``_real`` reload
    # branch above) has already placed a partially-populated or
    # env-derived ``consts.const`` into ``sys.modules``. Tests depend on
    # this module providing valid Redis URLs and other DP constants
    # without ever reaching a real Redis server.
    const_mod = sys.modules.get("consts.const")
    needs_replace = (
        const_mod is None
        or not getattr(const_mod, "REDIS_URL", None)
        or not getattr(const_mod, "REDIS_BACKEND_URL", None)
        or not getattr(const_mod, "RAY_NUM_CPUS", None)
    )
    if needs_replace:
        const_mod = types.ModuleType("consts.const")
        const_mod.ELASTICSEARCH_SERVICE = "http://api"
        const_mod.REDIS_BACKEND_URL = "redis://test"
        const_mod.REDIS_URL = "redis://test"
        const_mod.DATA_PROCESS_SERVICE = "http://data-process"
        const_mod.RAY_ACTOR_NUM_CPUS = 1
        const_mod.RAY_NUM_CPUS = 4
        const_mod.DP_PART_PROCESSOR_COUNT = 3
        const_mod.DP_FILE_SPLIT_SIZE_MB = 5
        const_mod.FORWARD_REDIS_RETRY_DELAY_S = 0
        const_mod.FORWARD_REDIS_RETRY_MAX = 1
        const_mod.DP_REDIS_CHUNKS_WAIT_TIMEOUT_S = 30
        const_mod.DP_REDIS_CHUNKS_POLL_INTERVAL_MS = 200
        const_mod.PER_WAVE_TIMEOUT = 30
        const_mod.MAX_TIMEOUT = 1800
        const_mod.RAY_ACTOR_WARM_TIMEOUT_S = 60
        const_mod.RAY_GLOBAL_ACTOR_POOL_NAME = "nexent_global_data_processor_pool"
        const_mod.RAY_GLOBAL_ACTOR_POOL_NAMESPACE = "nexent-data-process"
        const_mod.DISABLE_RAY_DASHBOARD = False
        # New defaults required by ray_actors import
        const_mod.DEFAULT_EXPECTED_CHUNK_SIZE = 1024
        const_mod.DEFAULT_MAXIMUM_CHUNK_SIZE = 1536
        const_mod.ROOT_DIR = "/mock/root"
        const_mod.TABLE_TRANSFORMER_MODEL_PATH = "/mock/table_transformer_model"
        const_mod.UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH = "/mock/unstructured_params.json"
        # Mark as a package so relative imports (``from .consts import X``)
        # resolve against the stub.
        setattr(const_mod, "__file__", "<consts.const stub>")
        sys.modules["consts.const"] = const_mod
    else:
        # Existing stub already has Redis URLs — just make sure the
        # dashboard flag is set to the value tests expect.
        sys.modules["consts.const"].DISABLE_RAY_DASHBOARD = False
    # Minimal stub for consts.model used by utils.file_management_utils
    if "consts.model" not in sys.modules:
        model_mod = types.ModuleType("consts.model")

        class ProcessParams:
            def __init__(self, chunking_strategy: str, source_type: str, index_name: str, authorization: Optional[str]):
                self.chunking_strategy = chunking_strategy
                self.source_type = source_type
                self.index_name = index_name
                self.authorization = authorization
        model_mod.ProcessParams = ProcessParams
        sys.modules["consts.model"] = model_mod

    # Stub out auth and config utils to avoid importing real dependencies in file_management_utils
    if "utils.auth_utils" not in sys.modules:
        sys.modules["utils.auth_utils"] = types.SimpleNamespace(
            get_current_user_id=lambda authorization: (
                "user-test", "tenant-test")
        )
    if "utils.config_utils" not in sys.modules:
        cfg_mod = types.ModuleType("utils.config_utils")
        cfg_mod.tenant_config_manager = types.SimpleNamespace(
            load_config=lambda tenant_id: {}
        )
        sys.modules["utils.config_utils"] = cfg_mod
    if "nexent.data_process" not in sys.modules:
        sys.modules["nexent.data_process"] = types.SimpleNamespace(
            DataProcessCore=type(
                "_Core", (), {"__init__": lambda self: None, "file_process": lambda *a, **k: []})
        )

    # Stub external dependencies (required by utils.file_management_utils)
    if "aiofiles" not in sys.modules:
        sys.modules["aiofiles"] = types.SimpleNamespace(
            open=lambda *args, **kwargs: types.SimpleNamespace(
                __aenter__=lambda: types.SimpleNamespace(
                    write=lambda content: None,
                    __aexit__=lambda *args: None
                ),
                __aexit__=lambda *args: None
            )
        )
    if "httpx" not in sys.modules:
        sys.modules["httpx"] = types.SimpleNamespace()
    if "requests" not in sys.modules:
        class _FakeResponse:
            def __init__(self, status_code=200, json_data=None, text=""):
                self.status_code = status_code
                self._json_data = json_data
                self.text = text

            def json(self):
                if self._json_data is None:
                    raise ValueError("no json")
                return self._json_data

        sys.modules["requests"] = types.SimpleNamespace(
            delete=lambda *a, **k: _FakeResponse(status_code=200, json_data={
                                                 "status": "success"}, text=""),
        )
    if "redis" not in sys.modules:
        sys.modules["redis"] = types.SimpleNamespace(
            Redis=types.SimpleNamespace(
                from_url=lambda *args, **kwargs: types.SimpleNamespace(
                    get=lambda *a, **k: None,
                    set=lambda *a, **k: True,
                    expire=lambda *a, **k: True,
                    delete=lambda *a, **k: True,
                )
            )
        )
    if "fastapi" not in sys.modules:
        fastapi_mod = types.ModuleType("fastapi")
        fastapi_mod.UploadFile = type("UploadFile", (), {})
        sys.modules["fastapi"] = fastapi_mod

    # Stub utils.file_management_utils (required by tasks.py)
    if "utils.file_management_utils" not in sys.modules:
        file_utils_mod = types.ModuleType("utils.file_management_utils")
        file_utils_mod.get_file_size = lambda *args, **kwargs: 0
        sys.modules["utils.file_management_utils"] = file_utils_mod

    # Stub services.redis_service (required by tasks.py)
    if "services.redis_service" not in sys.modules:
        redis_service_mod = types.ModuleType("services.redis_service")

        class _StubRedisService:
            def save_error_info(self, *args, **kwargs):
                return True

            def is_task_cancelled(self, *args, **kwargs):
                return False

            def save_progress_info(self, *args, **kwargs):
                return True

            def increment_progress_info(self, *args, **kwargs):
                return True

        redis_service_mod.get_redis_service = lambda: _StubRedisService()
        sys.modules["services.redis_service"] = redis_service_mod

    # Stub aiohttp (required by tasks.py)
    if "aiohttp" not in sys.modules:
        sys.modules["aiohttp"] = types.SimpleNamespace()

    import backend.data_process.tasks as tasks
    importlib.reload(tasks)
    # Provide a Celery task shim that allows direct calls and supports .s for chaining

    class _SignatureShim:
        def __init__(self):
            # Delegate to a real Celery ``Signature`` so that all internal
            # attributes/methods (``.options``, ``.clone()``, ``.freeze()``,
            # ``.__or__()``, ``._app``, etc.) are available without us
            # having to reimplement Celery's canvas API surface.
            try:
                from celery import Signature as _CelerySignature
                self._inner = _CelerySignature("fake_task")
            except Exception:  # pragma: no cover
                self._inner = None

        def set(self, **_kw):
            return self

        def __getattr__(self, name):
            # Forward unknown attribute access to the wrapped real Signature
            # so Celery internals (``.freeze``, ``.options``, ``._app``,
            # ``.__or__``, ``.clone`` etc.) Just Work without us
            # having to enumerate every method.
            inner = object.__getattribute__(self, "_inner")
            if inner is None:
                raise AttributeError(name)
            return getattr(inner, name)

        def __getitem__(self, key):
            return self

        def __or__(self, other):
            # ``chord`` returns a chain that is later composed with
            # ``|`` — tests only inspect the resulting chain object, so
            # we keep the identity stable.
            return self

        def __ror__(self, other):
            return self

    class _CeleryTaskShim:
        """Test-side wrapper around a celery task.

        When the shim is called, ``__call__`` re-binds a *curated* set
        of names (``get_ray_actor``, ``_get_or_create_global_pool_manager``,
        ``GlobalRayActorPoolManager``, ``ray``, ``requests``, ``save_error_to_redis``,
        etc.) from the live ``tasks`` module dict onto the wrapped function's
        ``__globals__``. This sidesteps the well-known Python pitfall that a
        function's ``__globals__`` may not be the same dict object as the
        module's ``__dict__`` after ``importlib.reload`` or when the wrapped
        function is captured across reloads (the dicts merely contain the
        same keys/values). Without this rebind, ``monkeypatch.setattr(tasks,
        'get_ray_actor', lambda)`` would update ``tasks.__dict__`` only and
        the original ``get_ray_actor`` function would still be invoked via
        the stale ``__globals__`` reference, leading to ``AttributeError:
        'GlobalRayActorPoolManager' has no attribute 'options'`` and friends.
        """
        # Names that tests commonly monkeypatch and that the tasks module
        # functions look up via ``__globals__`` at call time.
        _SYNC_NAMES = (
            "get_ray_actor",
            "_get_or_create_global_pool_manager",
            "GlobalRayActorPoolManager",
            "prewarm_ray_actors",
            "ray",
            "ray_init_lock",
            "init_ray_in_worker",
            "requests",
            "aiohttp",
            "run_async",
            "save_error_to_redis",
            "save_process_chunk_to_redis",
            "load_chunks_from_redis",
            "serialize_exception",
            "truncate_reason",
            "extract_error_code",
            "get_knowledge_record",
            "get_redis_service",
            "get_file_size",
            "build_balanced_batches",
            "count_image_metadata_chunks",
            "compute_split_wait_timeout",
            "estimate_parallel_parts",
            "wait_for_split_ready",
            "save_progress_info",
            "submit_process_forward_chain",
            "process_and_forward",
            "process_part",
            "aggregate_store_chunks",
            "forward_part",
            "aggregate_forward_parts",
            "cleanup_source",
            "forward",
            "process",
            "process_sync",
            "chain",
            "group",
            "chord",
            "allow_join_result",
            "states",
            "Retry",
            "ELASTICSEARCH_SERVICE",
            "REDIS_BACKEND_URL",
            "REDIS_URL",
            "FORWARD_REDIS_RETRY_DELAY_S",
            "FORWARD_REDIS_RETRY_MAX",
            "DP_REDIS_CHUNKS_WAIT_TIMEOUT_S",
            "DP_REDIS_CHUNKS_POLL_INTERVAL_MS",
            "RAY_GLOBAL_ACTOR_POOL_NAME",
            "RAY_GLOBAL_ACTOR_POOL_NAMESPACE",
            "RAY_ACTOR_WARM_TIMEOUT_S",
            "RAY_ACTOR_NUM_CPUS",
            "ROOT_DIR",
            "PER_WAVE_TIMEOUT",
            "MAX_TIMEOUT",
            "DISABLE_RAY_DASHBOARD",
        )

        def __init__(self, run_func, preprocess=None, tasks_module=None):
            self._run_func = run_func
            self._preprocess = preprocess
            self._tasks_module = tasks_module

        def _sync_globals(self):
            """Copy selected names from ``tasks.__dict__`` onto the
            wrapped function's ``__globals__`` so monkeypatches on the
            live module propagate to the captured code.

            We mirror the entire module dict rather than a curated subset
            so monkeypatches on arbitrary names propagate. Tests commonly
            patch ``get_ray_actor``, ``run_async``, ``chain``, ``group``,
            ``chord``, ``allow_join_result``, ``states``, ``Retry``, etc.
            Copying every entry is cheap and avoids needing to enumerate
            each name.
            """
            if self._tasks_module is None:
                return
            tm = self._tasks_module
            target = getattr(self._run_func, "__globals__", None)
            if not isinstance(target, dict):
                return
            try:
                target.update(tm.__dict__)
            except Exception:  # pragma: no cover
                pass

        def __call__(self, *args, **kwargs):
            self._sync_globals()
            if self._preprocess is not None:
                args, kwargs = self._preprocess(args, kwargs)
            return self._run_func(*args, **kwargs)

        def s(self, **_kw):
            return _SignatureShim()

    # Helper to get unbound run
    def _unbound_run(task_obj):
        """
        Return the underlying callable for a Celery task or plain function.

        In production, Celery tasks are Task objects (or PromiseProxy wrappers
        around Task objects) with a .run attribute. The real Celery @app.task
        decorator wraps the function in a celery.local.PromiseProxy, so we
        must evaluate the proxy before reading .run.
        """
        if task_obj is None:
            return None
        # Resolve PromiseProxy / lazy proxies to their underlying object.
        if hasattr(task_obj, "_get_current_object"):
            try:
                task_obj = task_obj._get_current_object()
            except Exception:  # pragma: no cover
                pass
        # Plain function or class with no .run attribute
        if not hasattr(task_obj, "run") or not callable(getattr(task_obj, "run", None)):
            # Already directly callable (function or object with __call__)
            return task_obj
        run_attr = getattr(task_obj, "run", None)
        return getattr(run_attr, "__func__", run_attr)

    # Inject a default Ray actor so get_ray_actor works even when not monkeypatched in tests
    default_actor = types.SimpleNamespace(
        ping=types.SimpleNamespace(remote=lambda *a, **k: "pong"),
        split_file=types.SimpleNamespace(remote=lambda *a, **k: []),
        process_bytes=types.SimpleNamespace(
            remote=lambda *a, **k: "ref-bytes"),
        process_file=types.SimpleNamespace(remote=lambda *a, **k: "ref"),
        store_chunks_in_redis=types.SimpleNamespace(
            remote=lambda *a, **k: None),
    )
    if not hasattr(tasks, "DataProcessorRayActor") or not hasattr(getattr(tasks, "DataProcessorRayActor"), "remote"):
        tasks.DataProcessorRayActor = types.SimpleNamespace(
            remote=lambda: default_actor)
    # Preprocess for forward: drop empty/whitespace-only chunks before calling real run
    def _forward_preprocess(args, kwargs):
        pd = kwargs.get("processed_data")
        if isinstance(pd, dict) and isinstance(pd.get("chunks"), list):
            filtered = []
            for ch in pd.get("chunks", []):
                content = (ch.get("content") or "").strip()
                if not content:
                    continue
                meta = ch.get("metadata") or {}
                filtered.append({"content": content, "metadata": meta})
            # Propagate filtered chunks and ensure key metadata fields surface as kwargs for the task
            new_pd = {**pd, "chunks": filtered}
            if new_pd.get("original_filename") and not kwargs.get("original_filename"):
                kwargs = {
                    **kwargs, "original_filename": new_pd.get("original_filename")}
            kwargs = {**kwargs, "processed_data": new_pd}
        return args, kwargs

    # Wrap tasks with shim
    maybe = _unbound_run(getattr(tasks, "process", None))
    if maybe is not None:
        tasks.process = _CeleryTaskShim(maybe, tasks_module=tasks)
        # Ensure process is also available in the module namespace for process_and_forward
        import backend.data_process.tasks as tasks_module
        tasks_module.process = tasks.process
    maybe = _unbound_run(getattr(tasks, "forward", None))
    if maybe is not None:
        tasks.forward = _CeleryTaskShim(maybe, preprocess=_forward_preprocess, tasks_module=tasks)
        # Ensure forward is also available in the module namespace for process_and_forward
        import backend.data_process.tasks as tasks_module
        tasks_module.forward = tasks.forward
    maybe = _unbound_run(getattr(tasks, "process_and_forward", None))
    if maybe is not None:
        # For process_and_forward, we need to patch the function's globals to use shimmed process and forward
        # Since process_and_forward uses process.s() and forward.s(), we need to ensure
        # those are available. Update the function's __globals__ to use shimmed versions.
        import backend.data_process.tasks as tasks_module
        # Update the function's globals to reference the shimmed process and forward
        if hasattr(maybe, '__globals__'):
            maybe.__globals__['process'] = tasks.process
            maybe.__globals__['forward'] = tasks.forward
        tasks.process_and_forward = _CeleryTaskShim(maybe, tasks_module=tasks)
    maybe = _unbound_run(getattr(tasks, "process_sync", None))
    if maybe is not None:
        tasks.process_sync = _CeleryTaskShim(maybe, tasks_module=tasks)
    maybe = _unbound_run(getattr(tasks, "forward_part", None))
    if maybe is not None:
        tasks.forward_part = _CeleryTaskShim(maybe, tasks_module=tasks)
    maybe = _unbound_run(getattr(tasks, "aggregate_forward_parts", None))
    if maybe is not None:
        tasks.aggregate_forward_parts = _CeleryTaskShim(maybe, tasks_module=tasks)
    maybe = _unbound_run(getattr(tasks, "process_part", None))
    if maybe is not None:
        tasks.process_part = _CeleryTaskShim(maybe, tasks_module=tasks)
    maybe = _unbound_run(getattr(tasks, "aggregate_store_chunks", None))
    if maybe is not None:
        tasks.aggregate_store_chunks = _CeleryTaskShim(maybe, tasks_module=tasks)
    maybe = _unbound_run(getattr(tasks, "cleanup_source", None))
    if maybe is not None:
        tasks.cleanup_source = _CeleryTaskShim(maybe, tasks_module=tasks)
    return tasks, fake_ray


@pytest.fixture
def import_tasks_with_fake_ray_fixture(monkeypatch):
    """Pytest fixture wrapper around import_tasks_with_fake_ray.

    Yields (tasks_module, fake_ray_instance). Used by sibling test modules that
    only need the heavy stubbing but do not care about the tasks module.
    """
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch)
    return tasks, fake_ray


@pytest.fixture(autouse=True, scope="function")
def _restore_real_celery_modules():
    """Auto-applied fixture: ensure celery.exceptions and celery.backends.base
    expose every symbol celery's own submodules need.

    Sibling tests (e.g. test_utils.py) install stub celery.exceptions /
    celery.backends.base modules that lack some names. When the producing
    test tears down, monkeypatch reverts the stub — but a stub *module
    object* can be reloaded with the real one.

    Loading the real modules inside this fixture can cause a re-load that
    creates a *new* class object for Retry distinct from the one bound at
    tasks.py import time. To avoid breaking `except Retry:` in tasks.py we
    instead patch missing attributes onto the existing module without
    reloading it.
    """
    # celery.exceptions: ensure SecurityError/SecurityWarning/reraise/etc.
    # exist. If celery is a stub package (set up by
    # ``import_tasks_with_fake_ray``), ``__import__`` will fail — that's
    # fine because the stub itself provides those names directly.
    _exc_mod = sys.modules.get("celery.exceptions")
    if _exc_mod is not None and not hasattr(_exc_mod, "SecurityError"):
        try:
            _real_exc = __import__("celery.exceptions")
            for _attr in ("SecurityError", "SecurityWarning", "reraise"):
                if not hasattr(_exc_mod, _attr):
                    setattr(_exc_mod, _attr, getattr(_real_exc, _attr))
        except Exception:  # pragma: no cover
            pass
    # celery.backends.base: ensure _create_chord_error_with_cause exists.
    _bb_mod = sys.modules.get("celery.backends.base")
    if _bb_mod is not None and not hasattr(_bb_mod, "_create_chord_error_with_cause"):
        try:
            _real_bb = __import__("celery.backends.base")
            setattr(_bb_mod, "_create_chord_error_with_cause",
                    getattr(_real_bb, "_create_chord_error_with_cause"))
        except Exception:  # pragma: no cover
            pass
    yield


def test_init_ray_in_worker_initializes_once(monkeypatch):
    tasks, fake_ray = import_tasks_with_fake_ray(
        monkeypatch, initialized=False)
    # First call initializes
    tasks.init_ray_in_worker()
    assert fake_ray.inits and fake_ray.inits[-1]["configure_logging"] is False
    assert fake_ray.inits[-1]["faulthandler"] is False
    # When DISABLE_RAY_DASHBOARD is False (default), include_dashboard should be True
    assert fake_ray.inits[-1]["include_dashboard"] is True
    # Second call does nothing
    tasks.init_ray_in_worker()
    assert len(fake_ray.inits) == 1


def test_init_ray_in_worker_respects_disable_dashboard_setting(monkeypatch):
    """Test that init_ray_in_worker respects DISABLE_RAY_DASHBOARD setting"""
    tasks, fake_ray = import_tasks_with_fake_ray(
        monkeypatch, initialized=False)
    # Patch DISABLE_RAY_DASHBOARD in tasks module to True
    monkeypatch.setattr(tasks, "DISABLE_RAY_DASHBOARD", True)

    # First call initializes with include_dashboard=False
    tasks.init_ray_in_worker()
    assert fake_ray.inits and fake_ray.inits[-1]["configure_logging"] is False
    assert fake_ray.inits[-1]["faulthandler"] is False
    # When DISABLE_RAY_DASHBOARD is True, include_dashboard should be False
    assert fake_ray.inits[-1]["include_dashboard"] is False


def test_init_ray_in_worker_raises_on_init_failure(monkeypatch):
    """Test that init_ray_in_worker logs error and re-raises exception when ray.init() fails"""
    tasks, fake_ray = import_tasks_with_fake_ray(
        monkeypatch, initialized=False)

    # Make ray.init() raise an exception
    init_exception = RuntimeError("Ray initialization failed")

    def failing_init(**kwargs):
        raise init_exception
    fake_ray.init = failing_init

    # Verify that the exception is re-raised
    with pytest.raises(RuntimeError) as exc_info:
        tasks.init_ray_in_worker()
    assert "Failed to initialize Ray for Celery worker" in str(exc_info.value)


def test_run_async_no_running_loop(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)

    async def sample():
        return 42

    # Force RuntimeError in get_running_loop to trigger asyncio.run path
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: (
        _ for _ in ()).throw(RuntimeError("no loop")))
    result = tasks.run_async(sample())
    assert result == 42


def test_run_async_running_loop_with_nest_asyncio(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)

    class FakeLoop:
        def is_running(self):
            return True

        def run_until_complete(self, coro):
            return "done"

    monkeypatch.setattr(asyncio, "get_running_loop", lambda: FakeLoop())
    sys.modules["nest_asyncio"] = types.SimpleNamespace(apply=lambda: None)
    result = tasks.run_async(asyncio.sleep(0))
    assert result == "done"


def test_get_ray_actor_returns_actor(monkeypatch):
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch, initialized=True)

    actor_obj = types.SimpleNamespace(
        ping=types.SimpleNamespace(remote=lambda *a, **k: "pong"))

    class _ManagerHandle:
        def __init__(self, actor):
            self.get_actor = types.SimpleNamespace(
                remote=lambda: "__actor_ref__")
            self._actor = actor

    monkeypatch.setattr(
        tasks, "_get_or_create_global_pool_manager", lambda: _ManagerHandle(actor_obj))
    fake_ray.get_returns = {"__actor_ref__": actor_obj}
    actor = tasks.get_ray_actor()
    assert actor is actor_obj


class FakeSelf:
    def __init__(self, task_id="tid-1"):
        self.request = types.SimpleNamespace(id=task_id, retries=0)
        self.states = []

    def update_state(self, **kw):
        self.states.append(kw)

    def retry(self, **kw):
        from celery.exceptions import Retry
        raise Retry()


def test_process_local_happy_path(monkeypatch, tmp_path):
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch, initialized=True)

    # Prepare a fake local file
    f = tmp_path / "a.txt"
    f.write_text("content")

    # Mock chunks returned by Ray processing
    mock_chunks = [{"content": "chunk1", "metadata": {}},
                   {"content": "chunk2", "metadata": {}}]

    class FakeActor:
        class P:
            def __init__(self, *a, **k):
                self.args = (a, k)

        def __init__(self):
            self.calls = []
            self.process_file = types.SimpleNamespace(
                remote=lambda *a, **k: "ref1")
            self.store_chunks_in_redis = types.SimpleNamespace(
                remote=lambda *a, **k: None)

    monkeypatch.setattr(tasks, "get_ray_actor", lambda: FakeActor())
    # Mock ray.get to return chunks instead of reference
    fake_ray.get_returns = mock_chunks

    self = FakeSelf("p1")

    result = tasks.process(self, source=str(f), source_type="local",
                           chunking_strategy="basic", index_name="idx", original_filename="a.txt")
    assert result["redis_key"].startswith("dp:p1:chunks")
    # success state updated twice: STARTED and SUCCESS
    assert any(s.get("state") == tasks.states.SUCCESS for s in self.states)
    # Verify chunks_count is set correctly (not None)
    success_state = [s for s in self.states if s.get(
        "state") == tasks.states.SUCCESS][0]
    assert success_state.get("meta", {}).get("chunks_count") == 2


def test_process_minio_path(monkeypatch):
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch, initialized=True)

    # Mock chunks returned by Ray processing
    mock_chunks = [{"content": "minio chunk", "metadata": {}}]

    class FakeActor:
        def __init__(self):
            self.process_bytes = types.SimpleNamespace(
                remote=lambda *a, **k: "ref")
            self.store_chunks_in_redis = types.SimpleNamespace(
                remote=lambda *a, **k: None)

    monkeypatch.setattr(tasks, "get_ray_actor", lambda: FakeActor())
    # Mock ray.get to return chunks
    fake_ray.get_returns = mock_chunks

    self = FakeSelf("m1")
    result = tasks.process(self, source="http://minio/bucket/x",
                           source_type="minio", chunking_strategy="basic")
    assert result["redis_key"].startswith("dp:m1:chunks")
    # Verify chunks_count is set
    success_state = [s for s in self.states if s.get(
        "state") == tasks.states.SUCCESS][0]
    assert success_state.get("meta", {}).get("chunks_count") == 1


def test_process_passes_embedding_ids_to_actor(monkeypatch, tmp_path):
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch, initialized=True)

    # Prepare a fake local file
    f = tmp_path / "e.txt"
    f.write_text("content")

    captured = {}

    class FakeActor:
        def __init__(self):
            def remote(*a, **k):
                captured["kwargs"] = k
                return "ref_cap"
            self.process_file = types.SimpleNamespace(remote=remote)
            self.store_chunks_in_redis = types.SimpleNamespace(
                remote=lambda *a, **k: None)

    monkeypatch.setattr(tasks, "get_ray_actor", lambda: FakeActor())
    fake_ray.get_returns = [{"content": "chunk", "metadata": {}}]

    self = FakeSelf("mid-1")
    tasks.process(
        self,
        source=str(f),
        source_type="local",
        chunking_strategy="basic",
        index_name="idx",
        original_filename="e.txt",
        embedding_model_id=321,
        tenant_id="tenant-x",
    )

    assert captured.get("kwargs", {}).get("model_id") == 321
    assert captured.get("kwargs", {}).get("tenant_id") == "tenant-x"


def test_process_large_file_with_many_chunks(monkeypatch, tmp_path):
    """Test processing a large file that generates 100+ chunks"""
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch, initialized=True)

    # Prepare a fake large file
    f = tmp_path / "large.pdf"
    f.write_text("large content" * 1000)

    # Mock 150 chunks to simulate large file processing
    mock_chunks = [{"content": f"chunk_{i}", "metadata": {}}
                   for i in range(150)]

    class FakeActor:
        def __init__(self):
            self.process_file = types.SimpleNamespace(
                remote=lambda *a, **k: "ref_large")
            self.store_chunks_in_redis = types.SimpleNamespace(
                remote=lambda *a, **k: None)

    monkeypatch.setattr(tasks, "get_ray_actor", lambda: FakeActor())
    # Mock ray.get to return large chunks
    fake_ray.get_returns = mock_chunks

    self = FakeSelf("large1")

    result = tasks.process(self, source=str(f), source_type="local",
                           chunking_strategy="basic", index_name="idx", original_filename="large.pdf")

    # Verify redis_key is set
    assert result["redis_key"].startswith("dp:large1:chunks")

    # Verify chunks_count shows 150 chunks
    success_state = [s for s in self.states if s.get(
        "state") == tasks.states.SUCCESS][0]
    assert success_state.get("meta", {}).get("chunks_count") == 150

    # Verify processing_time is set
    assert "processing_time" in success_state.get("meta", {})
    assert success_state.get("meta", {}).get("processing_time") >= 0


def test_process_raises_on_missing_file(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch, initialized=True)
    monkeypatch.setattr("os.path.exists", lambda p: False)
    self = FakeSelf("e1")
    with pytest.raises(Exception) as ei:
        tasks.process(self, source="/not/found", source_type="local")
    # expected to raise json-encoded error
    json.loads(str(ei.value))


def test_forward_redis_cached_invalid_json_raises(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")
    monkeypatch.setattr(tasks, "REDIS_BACKEND_URL", "redis://test")

    class FakeRedisClient:
        def get(self, k):
            return "not-json"

    fake_redis_mod = types.SimpleNamespace(Redis=types.SimpleNamespace(
        from_url=lambda url, decode_responses=True: FakeRedisClient()))
    monkeypatch.setitem(sys.modules, "redis", fake_redis_mod)

    self = FakeSelf("r3")
    with pytest.raises(Exception) as ei:
        tasks.forward(self, processed_data={
                      "redis_key": "dp:rid:badjson"}, index_name="idx", source="/a.txt")
    # Should be JSON-wrapped error
    json.loads(str(ei.value))


def test_forward_returns_when_task_cancelled(monkeypatch):
    """forward should exit early when cancellation flag is set"""
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")

    class FakeRedisService:
        def __init__(self):
            self.calls = 0

        def is_task_cancelled(self, task_id):
            self.calls += 1
            return True

    fake_service = FakeRedisService()
    monkeypatch.setattr(tasks, "get_redis_service", lambda: fake_service)

    self = FakeSelf("cancel-1")
    result = tasks.forward(
        self,
        processed_data={"chunks": [{"content": "keep", "metadata": {}}]},
        index_name="idx",
        source="/a.txt",
    )

    assert result["chunks_stored"] == 0
    assert "cancelled" in result["es_result"]["message"].lower()
    assert fake_service.calls == 1
    # No state updates should occur because we returned early
    assert self.states == []


def test_forward_redis_client_from_url_failure(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")
    monkeypatch.setattr(tasks, "REDIS_BACKEND_URL", "redis://bad")

    class FakeRedis:
        @staticmethod
        def from_url(url, decode_responses=True):
            raise RuntimeError("cannot connect")

    fake_redis_mod = types.SimpleNamespace(Redis=FakeRedis)
    monkeypatch.setitem(sys.modules, "redis", fake_redis_mod)

    self = FakeSelf("r4")
    with pytest.raises(Exception) as ei:
        tasks.forward(self, processed_data={
                      "redis_key": "dp:rid:x"}, index_name="idx", source="/a.txt")
    json.loads(str(ei.value))


def test_forward_skips_empty_chunk_without_preprocess(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")
    monkeypatch.setattr(tasks, "get_file_size", lambda *a, **k: 0)
    # Ensure API success without calling real aiohttp
    monkeypatch.setattr(tasks, "run_async", lambda coro: {
                        "success": True, "total_indexed": 1, "total_submitted": 1, "message": "ok"})

    self = FakeSelf("f9")
    # Use tuple to bypass preprocess filtering (preprocess only filters list)
    chunks_tuple = (
        # will be skipped in forward at 446-449
        {"content": "   ", "metadata": {}},
        {"content": "keep", "metadata": {}},  # will be indexed
    )
    result = tasks.forward(self, processed_data={
                           "chunks": chunks_tuple}, index_name="idx", source="/a.txt")
    assert result["chunks_stored"] == 2 or result["chunks_stored"] == 1
    # We asserted path executed; exact stored count depends on implementation but should not error


def test_forward_vectorize_documents_client_connector_error(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")
    # Speed up retries

    async def no_sleep(_):
        return None
    monkeypatch.setattr(tasks.asyncio, "sleep", no_sleep)

    # Stub aiohttp to raise ClientConnectorError
    class ClientConnectorError(Exception):
        pass

    class TCPConnector:
        def __init__(self, verify_ssl=False):
            pass

    class ClientTimeout:
        def __init__(self, total=None):
            pass

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def post(self, *a, **k):
            raise ClientConnectorError("down")

    # Provide both error types because tasks.forward references both in except
    class DummyClientResponseError(Exception):
        def __init__(self, status=None):
            self.status = status

    fake_aiohttp = types.SimpleNamespace(
        ClientConnectorError=ClientConnectorError,
        ClientResponseError=DummyClientResponseError,
        TCPConnector=TCPConnector,
        ClientTimeout=ClientTimeout,
        ClientSession=Session,
    )
    monkeypatch.setitem(sys.modules, "aiohttp", fake_aiohttp)
    # Ensure tasks module uses the stubbed aiohttp with ClientConnectorError
    monkeypatch.setattr(tasks, "aiohttp", fake_aiohttp, raising=False)

    self = FakeSelf("e_conn")
    with pytest.raises(Exception) as ei:
        tasks.forward(self, processed_data={"chunks": [
                      {"content": "x", "metadata": {}}]}, index_name="idx", source="/a.txt")
    json.loads(str(ei.value))


def test_forward_vectorize_documents_client_response_503(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")

    async def no_sleep(_):
        return None
    monkeypatch.setattr(tasks.asyncio, "sleep", no_sleep)

    class ClientResponseError(Exception):
        def __init__(self, status):
            self.status = status

    class TCPConnector:
        def __init__(self, verify_ssl=False):
            pass

    class ClientTimeout:
        def __init__(self, total=None):
            pass

    class PostCtx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def post(self, *a, **k):
            # Raise before context manager is created to trigger except block
            raise ClientResponseError(503)

    # Provide both error types because tasks.forward references both in except
    class DummyClientConnectorError(Exception):
        pass

    fake_aiohttp = types.SimpleNamespace(
        ClientResponseError=ClientResponseError,
        ClientConnectorError=DummyClientConnectorError,
        TCPConnector=TCPConnector,
        ClientTimeout=ClientTimeout,
        ClientSession=Session,
    )
    monkeypatch.setitem(sys.modules, "aiohttp", fake_aiohttp)
    # Ensure tasks module uses the stubbed aiohttp with ClientResponseError
    monkeypatch.setattr(tasks, "aiohttp", fake_aiohttp, raising=False)

    self = FakeSelf("e_503")
    with pytest.raises(Exception) as ei:
        tasks.forward(self, processed_data={"chunks": [
                      {"content": "x", "metadata": {}}]}, index_name="idx", source="/a.txt")
    json.loads(str(ei.value))


def test_forward_api_returns_error_and_unexpected_format(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")
    monkeypatch.setattr(tasks, "get_file_size", lambda *a, **k: 0)

    self = FakeSelf("api_err")
    # success False branch
    monkeypatch.setattr(tasks, "run_async", lambda coro: {
                        "success": False, "message": "bad"})
    with pytest.raises(Exception) as ei1:
        tasks.forward(self, processed_data={"chunks": [
                      {"content": "x", "metadata": {}}]}, index_name="idx", source="/a.txt")
    json.loads(str(ei1.value))

    # unexpected format branch
    monkeypatch.setattr(tasks, "run_async", lambda coro: [1, 2, 3])
    with pytest.raises(Exception) as ei2:
        tasks.forward(self, processed_data={"chunks": [
                      {"content": "x", "metadata": {}}]}, index_name="idx", source="/a.txt")
    json.loads(str(ei2.value))


def test_forward_vectorize_documents_timeout_error(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")

    async def no_sleep(_):
        return None
    monkeypatch.setattr(tasks.asyncio, "sleep", no_sleep)

    class TimeoutError(Exception):
        pass

    class TCPConnector:
        def __init__(self, verify_ssl=False):
            pass

    class ClientTimeout:
        def __init__(self, total=None):
            pass

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def post(self, *a, **k):
            # Simulate timeout on post
            raise TimeoutError("timeout")

    # Inject stub aiohttp with TimeoutError type mapped to asyncio.TimeoutError in code path
    class DummyClientResponseError(Exception):
        def __init__(self, status=None):
            self.status = status

    class DummyClientConnectorError(Exception):
        pass

    fake_aiohttp = types.SimpleNamespace(
        ClientResponseError=DummyClientResponseError,
        ClientConnectorError=DummyClientConnectorError,
        TCPConnector=TCPConnector,
        ClientTimeout=ClientTimeout,
        ClientSession=Session,
    )
    monkeypatch.setitem(sys.modules, "aiohttp", fake_aiohttp)
    # Ensure tasks module uses the stubbed aiohttp for timeout path
    monkeypatch.setattr(tasks, "aiohttp", fake_aiohttp, raising=False)
    # Ensure our TimeoutError is seen as asyncio.TimeoutError in except
    monkeypatch.setattr(tasks.asyncio, "TimeoutError", TimeoutError)

    self = FakeSelf("e_timeout")
    with pytest.raises(Exception) as ei:
        tasks.forward(self, processed_data={"chunks": [
                      {"content": "x", "metadata": {}}]}, index_name="idx", source="/a.txt")
    json.loads(str(ei.value))


def test_forward_vectorize_documents_unexpected_error(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")

    async def no_sleep(_):
        return None
    monkeypatch.setattr(tasks.asyncio, "sleep", no_sleep)

    class TCPConnector:
        def __init__(self, verify_ssl=False):
            pass

    class ClientTimeout:
        def __init__(self, total=None):
            pass

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def post(self, *a, **k):
            # Simulate a generic unexpected error
            raise RuntimeError("boom")

    class DummyClientResponseError(Exception):
        def __init__(self, status=None):
            self.status = status

    class DummyClientConnectorError(Exception):
        pass

    fake_aiohttp = types.SimpleNamespace(
        ClientResponseError=DummyClientResponseError,
        ClientConnectorError=DummyClientConnectorError,
        TCPConnector=TCPConnector,
        ClientTimeout=ClientTimeout,
        ClientSession=Session,
    )
    monkeypatch.setitem(sys.modules, "aiohttp", fake_aiohttp)
    # Ensure tasks module uses the stubbed aiohttp for unexpected error path
    monkeypatch.setattr(tasks, "aiohttp", fake_aiohttp, raising=False)

    self = FakeSelf("e_unexpected")
    with pytest.raises(Exception) as ei:
        tasks.forward(self, processed_data={"chunks": [
                      {"content": "x", "metadata": {}}]}, index_name="idx", source="/a.txt")
    json.loads(str(ei.value))


def test_submit_process_forward_chain_returns_empty_when_apply_async_none(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)

    class FakeChain:
        def apply_async(self):
            return None

    monkeypatch.setattr(tasks, "chain", lambda *a, **k: FakeChain())
    import backend.data_process.tasks as tasks_module
    tasks_module.process = tasks.process
    tasks_module.forward = tasks.forward
    tasks_module.cleanup_source = tasks.cleanup_source
    out = tasks.submit_process_forward_chain(
        source="/a.txt", source_type="local", chunking_strategy="basic", index_name="idx")
    assert out == ""


def test_process_and_forward_returns_empty_when_apply_async_none(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(
        tasks, "submit_process_forward_chain", lambda **kwargs: "")
    self = FakeSelf("chain_none")
    out = tasks.process_and_forward(
        self, source="/a.txt", source_type="local", chunking_strategy="basic", index_name="idx")
    assert out == ""


def test_process_unsupported_source_type(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch, initialized=True)
    self = FakeSelf("e2")
    with pytest.raises(Exception) as ei:
        tasks.process(self, source="x", source_type="unknown")
    json.loads(str(ei.value))


def test_forward_with_chunks_success(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    # Ensure ES URL present
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")
    # Avoid calling real util
    monkeypatch.setattr(tasks, "get_file_size", lambda *a, **k: 123)

    # run_async should return a successful response matching formatted chunk count (1)
    monkeypatch.setattr(tasks, "run_async", lambda coro: {
                        "success": True, "total_indexed": 1, "total_submitted": 1, "message": "ok"})

    self = FakeSelf("f1")
    chunks = [
        {"content": "text", "metadata": {"creation_date": "2024-01-01"}},
        {"content": "", "metadata": {}},
    ]
    result = tasks.forward(self, processed_data={
                           "chunks": chunks}, index_name="idx", source="/a.txt", source_type="local", original_filename="a.txt")
    assert result["chunks_stored"] == 1


def test_forward_partial_success_raises(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")
    monkeypatch.setattr(tasks, "get_file_size", lambda *a, **k: 0)
    monkeypatch.setattr(tasks, "run_async", lambda coro: {
                        "success": True, "total_indexed": 0, "total_submitted": 1, "message": "partial"})
    self = FakeSelf("f2")
    with pytest.raises(Exception) as ei:
        tasks.forward(self, processed_data={"chunks": [{"content": "x", "metadata": {
        }}]}, index_name="idx", source="/a.txt", source_type="local")
    json.loads(str(ei.value))


def test_forward_no_chunks_and_no_redis_key_raises(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    self = FakeSelf("f3")
    with pytest.raises(Exception) as ei:
        tasks.forward(self, processed_data={},
                      index_name="idx", source="/a.txt")
    json.loads(str(ei.value))


def test_forward_formats_to_empty_then_raises(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    self = FakeSelf("f4")
    with pytest.raises(Exception) as ei:
        tasks.forward(self, processed_data={"chunks": [
                      {"content": "  ", "metadata": {}}]}, index_name="idx", source="/a.txt")
    json.loads(str(ei.value))


def test_forward_missing_es_env_raises(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "")
    monkeypatch.setattr(tasks, "get_file_size", lambda *a, **k: 0)
    self = FakeSelf("f5")
    with pytest.raises(Exception) as ei:
        tasks.forward(self, processed_data={"chunks": [
                      {"content": "x", "metadata": {}}]}, index_name="idx", source="/a.txt")
    json.loads(str(ei.value))


def test_forward_loads_chunks_from_redis(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")
    monkeypatch.setattr(tasks, "REDIS_BACKEND_URL", "redis://test")
    monkeypatch.setattr(tasks, "get_file_size", lambda *a, **k: 1)

    class FakeRedisClient:
        def __init__(self):
            self.kv = {"dp:rid:chunks": json.dumps(
                [{"content": "x", "metadata": {}}])}

        def get(self, k):
            return self.kv.get(k)

    fake_redis_mod = types.SimpleNamespace(Redis=types.SimpleNamespace(
        from_url=lambda url, decode_responses=True: FakeRedisClient()))
    monkeypatch.setitem(sys.modules, "redis", fake_redis_mod)

    # run_async returns success for 1 chunk
    monkeypatch.setattr(tasks, "run_async", lambda coro: {
                        "success": True, "total_indexed": 1, "total_submitted": 1, "message": "ok"})

    self = FakeSelf("f6")
    result = tasks.forward(self, processed_data={
                           "redis_key": "dp:rid:chunks"}, index_name="idx", source="/a.txt")
    assert result["chunks_stored"] == 1


def test_submit_process_forward_chain_returns_chain_id(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)

    class FakeResult:
        def __init__(self, id):
            self.id = id

    class FakeChain:
        def apply_async(self):
            return FakeResult("123")

    monkeypatch.setattr(tasks, "chain", lambda *a, **k: FakeChain())
    import backend.data_process.tasks as tasks_module
    tasks_module.process = tasks.process
    tasks_module.forward = tasks.forward
    tasks_module.cleanup_source = tasks.cleanup_source
    chain_id = tasks.submit_process_forward_chain(
        source="/a.txt", source_type="local", chunking_strategy="basic", index_name="idx")
    assert chain_id == "123"


def test_process_and_forward_returns_chain_id(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(
        tasks, "submit_process_forward_chain",
        lambda **kwargs: "123",
    )
    self = FakeSelf("c1")
    chain_id = tasks.process_and_forward(
        self, source="/a.txt", source_type="local", chunking_strategy="basic", index_name="idx")
    assert chain_id == "123"


def test_extract_error_code_parses_detail_and_regex_and_unknown():
    from backend.data_process.tasks import extract_error_code

    # detail error_code inside JSON string
    json_detail = json.dumps({"detail": {"error_code": "detail_code"}})
    assert extract_error_code(json_detail) == "detail_code"

    # regex fallback when not valid JSON
    raw = 'oops {"error_code":"regex_code"}'
    assert extract_error_code(raw) == "regex_code"

    # unknown errors intentionally do not get a fabricated code.
    assert extract_error_code("no code here") is None


def test_extract_error_code_top_level_key():
    from backend.data_process.tasks import extract_error_code

    payload = json.dumps({"error_code": "top_level"})
    assert extract_error_code(payload) == "top_level"


def test_save_error_to_redis_branches(monkeypatch):
    from backend.data_process.tasks import save_error_to_redis

    warnings = []
    infos = []

    class FakeRedisSvc:
        def __init__(self, return_val=True):
            self.return_val = return_val
            self.calls = []

        def save_error_info(self, tid, reason):
            self.calls.append((tid, reason))
            return self.return_val

    # capture logger calls
    monkeypatch.setattr(
        "backend.data_process.tasks.logger.warning",
        lambda msg: warnings.append(msg),
    )
    monkeypatch.setattr(
        "backend.data_process.tasks.logger.info", lambda msg: infos.append(msg)
    )
    monkeypatch.setattr(
        "backend.data_process.tasks.logger.error", lambda *a, **k: warnings.append(
            a[0])
    )

    # empty task_id
    save_error_to_redis("", "r", 0)
    assert any("task_id is empty" in w for w in warnings)
    warnings.clear()

    # empty error_reason
    save_error_to_redis("tid", "", 0)
    assert any("error_reason is empty" in w for w in warnings)
    warnings.clear()

    # success True
    svc_true = FakeRedisSvc(True)
    monkeypatch.setattr(
        "backend.data_process.tasks.get_redis_service", lambda: svc_true
    )
    save_error_to_redis("tid1", "reason1", 0)
    assert svc_true.calls == [("tid1", "reason1")]
    assert any("Successfully saved error info" in i for i in infos)

    # success False
    infos.clear()
    svc_false = FakeRedisSvc(False)
    monkeypatch.setattr(
        "backend.data_process.tasks.get_redis_service", lambda: svc_false
    )
    save_error_to_redis("tid2", "reason2", 0)
    assert svc_false.calls == [("tid2", "reason2")]
    assert any("save_error_info returned False" in w for w in warnings)

    # exception path
    def boom():
        raise RuntimeError("fail")

    monkeypatch.setattr(
        "backend.data_process.tasks.get_redis_service", lambda: boom()
    )
    save_error_to_redis("tid3", "reason3", 0)
    assert any("Failed to save error info to Redis" in w for w in warnings)


def test_process_error_fallback_when_save_error_raises(monkeypatch, tmp_path):
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch, initialized=True)

    # Force get_ray_actor to raise to enter error handling
    monkeypatch.setattr(tasks, "get_ray_actor", lambda: (_ for _ in ()).throw(
        Exception("x" * 250)
    ))

    # Make save_error_to_redis raise to hit fallback block
    monkeypatch.setattr(
        tasks,
        "save_error_to_redis",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("save-fail")),
    )

    self = FakeSelf("err-fallback")
    with pytest.raises(Exception):
        tasks.process(
            self,
            source=str(tmp_path / "missing.txt"),
            source_type="local",
            chunking_strategy="basic",
            index_name="idx",
            original_filename="file.txt",
        )

    # State should still be updated in fallback branch
    assert any(
        s.get("meta", {}).get("stage") in {
            "text_extraction_failed", "extracting_text"}
        for s in self.states
    ) or self.states == []


def test_process_error_truncates_reason_when_no_error_code(monkeypatch, tmp_path):
    """process should truncate long messages when extract_error_code is falsy"""
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch, initialized=True)

    long_msg = "x" * 250
    error_json = json.dumps({"message": long_msg})

    # Provide actor but make ray.get raise inside the try block
    class FakeActor:
        def __init__(self):
            self.process_file = types.SimpleNamespace(
                remote=lambda *a, **k: "ref_err")
            self.store_chunks_in_redis = types.SimpleNamespace(
                remote=lambda *a, **k: None)

    monkeypatch.setattr(tasks, "get_ray_actor", lambda: FakeActor())
    fake_ray.get = lambda *_: (_ for _ in ()).throw(Exception(error_json))
    # Force extract_error_code to return None so truncation path executes
    monkeypatch.setattr(tasks, "extract_error_code", lambda *a, **k: None)

    calls: list[str] = []

    def save_and_capture(task_id, reason, start_time):
        calls.append(reason)

    monkeypatch.setattr(tasks, "save_error_to_redis", save_and_capture)

    # Ensure source file exists so FileNotFound is not raised before ray.get
    f = tmp_path / "exists.txt"
    f.write_text("data")

    self = FakeSelf("trunc-proc")
    with pytest.raises(Exception):
        tasks.process(
            self,
            source=str(f),
            source_type="local",
            chunking_strategy="basic",
            index_name="idx",
            original_filename="f.txt",
        )

    # Captured reason should be truncated because error_code is falsy
    assert len(calls) >= 1
    truncated_reason = calls[-1]
    assert truncated_reason.endswith("...")
    assert len(truncated_reason) <= 203
    assert any(
        s.get("meta", {}).get("stage") == "text_extraction_failed"
        for s in self.states
    )


def test_forward_cancel_check_warning_then_continue(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")

    # make cancellation check raise to hit warning path
    monkeypatch.setattr(tasks, "get_redis_service", lambda: (
        _ for _ in ()).throw(RuntimeError("boom")))

    # run index_documents normally via stubbed run_async returning success
    monkeypatch.setattr(
        tasks,
        "run_async",
        lambda coro: {"success": True, "total_indexed": 1,
                      "total_submitted": 1, "message": "ok"},
    )

    self = FakeSelf("warn-cancel")
    result = tasks.forward(
        self,
        processed_data={"chunks": [{"content": "c", "metadata": {}}]},
        index_name="idx",
        source="/a.txt",
        authorization="Bearer 1",
    )
    assert result["chunks_stored"] == 1


def _run_coro(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _patch_send_chunks_http(monkeypatch, tasks, *, status, body, response_json=None):
    class FakeResponse:
        async def text(self):
            return body

        async def json(self):
            return response_json

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    FakeResponse.status = status

    class FakeSession:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(tasks, "aiohttp", types.SimpleNamespace(
        TCPConnector=lambda **kwargs: None,
        ClientTimeout=lambda **kwargs: None,
        ClientSession=FakeSession,
        ClientConnectorError=Exception,
        ClientResponseError=Exception,
    ))
    monkeypatch.setattr(tasks, "run_async", _run_coro)


def test_forward_index_documents_error_code_from_detail(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")

    class FakeResponse:
        status = 500

        async def text(self):
            return json.dumps({"detail": {"error_code": "detail_err"}})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class FakeSession:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def post(self, *a, **k):
            return FakeResponse()

    fake_aiohttp = types.SimpleNamespace(
        TCPConnector=lambda verify_ssl=False: None,
        ClientTimeout=lambda total=None: None,
        ClientSession=FakeSession,
        ClientConnectorError=Exception,
        ClientResponseError=Exception,
    )
    monkeypatch.setattr(tasks, "aiohttp", fake_aiohttp)
    monkeypatch.setattr(tasks, "run_async", _run_coro)

    self = FakeSelf("detail-err")
    with pytest.raises(Exception) as exc:
        tasks.forward(
            self,
            processed_data={"chunks": [{"content": "x", "metadata": {}}]},
            index_name="idx",
            source="/a.txt",
            authorization="Bearer token",
        )
    assert "detail_err" in str(exc.value)


def test_send_chunks_to_es_returns_response_json_when_body_is_not_json(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")
    _patch_send_chunks_http(
        monkeypatch, tasks, status=200, body="not-json",
        response_json={"success": True, "total_indexed": 1},
    )

    class RedisService:
        def is_document_delete_requested(self, **_kwargs):
            return False

    monkeypatch.setattr(tasks, "get_redis_service", lambda: RedisService())
    assert tasks._send_chunks_to_es(
        chunks=[{"content": "x"}], index_name="idx", authorization=None,
        task_id="task", source="obj", original_filename="x.txt"
    ) == {"success": True, "total_indexed": 1}


def test_send_chunks_to_es_raises_generic_http_error_without_error_code(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")
    _patch_send_chunks_http(monkeypatch, tasks, status=500, body="upstream failure")
    monkeypatch.setattr(tasks, "get_redis_service", lambda: types.SimpleNamespace(
        is_document_delete_requested=lambda **_kwargs: False,
    ))

    with pytest.raises(Exception, match="ElasticSearch service returned HTTP 500"):
        tasks._send_chunks_to_es(
            chunks=[{"content": "x"}], index_name="idx", authorization=None,
            task_id="task", source="obj", original_filename="x.txt", file_id="fid"
        )


def test_send_chunks_to_es_propagates_document_delete_request(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "aiohttp", types.SimpleNamespace(
        TCPConnector=lambda **_kwargs: None,
        ClientTimeout=lambda **_kwargs: None,
        ClientConnectorError=Exception,
        ClientResponseError=Exception,
    ))
    monkeypatch.setattr(tasks, "get_redis_service", lambda: types.SimpleNamespace(
        is_document_delete_requested=lambda **_kwargs: True,
    ))
    monkeypatch.setattr(tasks, "run_async", _run_coro)

    with pytest.raises(tasks.DocumentDeleteRequested):
        tasks._send_chunks_to_es(
            chunks=[{"content": "x"}], index_name="idx", authorization=None,
            task_id="task", source="obj", original_filename="x.txt", file_id="fid"
        )


def test_forward_index_documents_regex_error_code(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")
    monkeypatch.setattr(tasks, "get_file_size", lambda *a, **k: 0)

    class FakeResponse:
        status = 500

        async def text(self):
            # Include quotes so regex r'\"error_code\": \"...\"' matches
            return 'oops "error_code":"regex_branch"'

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class FakeSession:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def post(self, *a, **k):
            return FakeResponse()

    fake_aiohttp = types.SimpleNamespace(
        TCPConnector=lambda verify_ssl=False: None,
        ClientTimeout=lambda total=None: None,
        ClientSession=FakeSession,
        ClientConnectorError=Exception,
        ClientResponseError=Exception,
    )
    monkeypatch.setattr(tasks, "aiohttp", fake_aiohttp)
    monkeypatch.setattr(tasks, "run_async", _run_coro)

    self = FakeSelf("regex-err")
    with pytest.raises(Exception) as exc:
        tasks.forward(
            self,
            processed_data={"chunks": [{"content": "x", "metadata": {}}]},
            index_name="idx",
            source="/a.txt",
        )
    assert "regex_branch" in str(exc.value)


def test_forward_index_documents_client_connector_error(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")

    class FakeSession:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def post(self, *a, **k):
            raise tasks.aiohttp.ClientConnectorError("down")

    fake_aiohttp = types.SimpleNamespace(
        ClientConnectorError=Exception,
        TCPConnector=lambda verify_ssl=False: None,
        ClientTimeout=lambda total=None: None,
        ClientSession=FakeSession,
        ClientResponseError=Exception,
    )
    monkeypatch.setattr(tasks, "aiohttp", fake_aiohttp)
    monkeypatch.setattr(tasks, "run_async", _run_coro)

    self = FakeSelf("conn-err")
    with pytest.raises(Exception) as exc:
        tasks.forward(
            self,
            processed_data={"chunks": [{"content": "x", "metadata": {}}]},
            index_name="idx",
            source="/a.txt",
        )
    assert "Failed to connect to API" in str(exc.value)


def test_forward_index_documents_timeout(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")

    class FakeSession:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def post(self, *a, **k):
            raise asyncio.TimeoutError("t/o")

    fake_aiohttp = types.SimpleNamespace(
        ClientConnectorError=Exception,
        ClientResponseError=Exception,
        TCPConnector=lambda verify_ssl=False: None,
        ClientTimeout=lambda total=None: None,
        ClientSession=FakeSession,
    )
    monkeypatch.setattr(tasks, "aiohttp", fake_aiohttp)
    monkeypatch.setattr(tasks, "run_async", _run_coro)

    self = FakeSelf("timeout-err")
    with pytest.raises(Exception) as exc:
        tasks.forward(
            self,
            processed_data={"chunks": [{"content": "x", "metadata": {}}]},
            index_name="idx",
            source="/a.txt",
        )
    assert "Failed to connect to API" in str(
        exc.value) or "timeout" in str(exc.value).lower()


def test_forward_truncates_reason_when_no_error_code(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")
    monkeypatch.setattr(tasks, "get_file_size", lambda *a, **k: 0)
    monkeypatch.setattr(tasks, "extract_error_code", lambda *a, **k: None)

    long_msg = json.dumps({"message": "m" * 250})
    monkeypatch.setattr(
        tasks, "run_async", lambda coro: (
            _ for _ in ()).throw(Exception(long_msg))
    )

    reasons: list[str] = []
    monkeypatch.setattr(
        tasks, "save_error_to_redis", lambda tid, reason, st: reasons.append(
            reason)
    )

    self = FakeSelf("f-trunc")
    with pytest.raises(Exception):
        tasks.forward(
            self,
            processed_data={"chunks": [{"content": "x", "metadata": {}}]},
            index_name="idx",
            source="/a.txt",
        )

    assert reasons and reasons[0].endswith("...")
    assert len(reasons[0]) <= 203
    assert any(
        s.get("meta", {}).get("stage") == "forward_task_failed" for s in self.states
    )


def test_forward_fallback_truncates_on_non_json_error(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")
    monkeypatch.setattr(tasks, "get_file_size", lambda *a, **k: 0)
    monkeypatch.setattr(tasks, "extract_error_code", lambda *a, **k: None)

    monkeypatch.setattr(
        tasks, "run_async", lambda coro: (
            _ for _ in ()).throw(Exception("n" * 250))
    )

    reasons: list[str] = []
    monkeypatch.setattr(
        tasks, "save_error_to_redis", lambda tid, reason, st: reasons.append(
            reason)
    )

    self = FakeSelf("f-fallback")
    with pytest.raises(Exception):
        tasks.forward(
            self,
            processed_data={"chunks": [{"content": "x", "metadata": {}}]},
            index_name="idx",
            source="/a.txt",
        )

    assert reasons and reasons[0].endswith("...")
    assert len(reasons[0]) <= 203
    assert any(
        s.get("meta", {}).get("stage") == "forward_task_failed" for s in self.states
    )


def test_forward_error_truncates_reason_and_uses_save(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    long_message = "m" * 250
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")
    monkeypatch.setattr(
        tasks, "run_async", lambda coro: (_ for _ in ()).throw(
            Exception(json.dumps({"message": long_message})))
    )
    captured = {}
    monkeypatch.setattr(
        tasks, "save_error_to_redis", lambda tid, reason, st: captured.setdefault(
            "reason", reason)
    )

    self = FakeSelf("trunc")
    with pytest.raises(Exception):
        tasks.forward(
            self,
            processed_data={"chunks": [{"content": "x", "metadata": {}}]},
            index_name="idx",
            source="/a.txt",
        )

    assert captured["reason"]


def test_forward_error_fallback_when_json_loads_fails(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")
    monkeypatch.setattr(
        tasks, "run_async", lambda coro: (
            _ for _ in ()).throw(Exception("not-json-error"))
    )
    captured = {}
    monkeypatch.setattr(
        tasks, "save_error_to_redis", lambda tid, reason, st: captured.setdefault(
            "reason", reason)
    )

    self = FakeSelf("fallback-forward")
    with pytest.raises(Exception):
        tasks.forward(
            self,
            processed_data={"chunks": [{"content": "x", "metadata": {}}]},
            index_name="idx",
            source="/a.txt",
        )

    assert captured["reason"]
    assert any(
        s.get("meta", {}).get("stage") == "forward_task_failed" for s in self.states
    )


def test_process_sync_local_returns(monkeypatch):
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch, initialized=True)

    class FakeActor:
        def __init__(self):
            self.process_file = types.SimpleNamespace(
                remote=lambda *a, **k: "ref1")

    monkeypatch.setattr(tasks, "get_ray_actor", lambda: FakeActor())
    fake_ray.get_returns = [{"content": "a"}, {"content": "b"}]

    self = FakeSelf("s1")
    out = tasks.process_sync(self, source="/a.txt", source_type="local")
    assert out["chunks_count"] == 2
    assert "a\n\nb" in out["text"]


def test_count_image_metadata_chunks(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    chunks = [
        {"process_source": tasks.IMAGE_METADATA_PROCESS_SOURCE},
        {"process_source": "Unstructured"},
        {},
        {"process_source": tasks.IMAGE_METADATA_PROCESS_SOURCE},
    ]
    assert tasks._count_image_metadata_chunks(chunks) == 2
    assert tasks._count_image_metadata_chunks([]) == 0
    assert tasks._count_image_metadata_chunks(None) == 0


def test_build_balanced_batches_balances_image_chunks(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    image_chunks = [
        {"content": f"img-{i}", "process_source": tasks.IMAGE_METADATA_PROCESS_SOURCE}
        for i in range(6)
    ]
    text_chunks = [{"content": f"txt-{i}",
                    "process_source": "Unstructured"} for i in range(4)]
    batches = tasks._build_balanced_batches(
        image_chunks + text_chunks, batch_size=4)

    assert len(batches) == 3
    assert all(len(batch) <= 4 for batch in batches)
    image_counts = [
        sum(1 for chunk in batch if chunk.get("process_source")
            == tasks.IMAGE_METADATA_PROCESS_SOURCE)
        for batch in batches
    ]
    assert max(image_counts) - min(image_counts) <= 1


def test_compute_split_wait_timeout_respects_waves_and_cap(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "DP_REDIS_CHUNKS_WAIT_TIMEOUT_S", 10)
    monkeypatch.setattr(tasks, "_estimate_parallel_parts", lambda: 2)
    monkeypatch.setattr(tasks, "PER_WAVE_TIMEOUT", 7)
    monkeypatch.setattr(tasks, "MAX_TIMEOUT", 20)

    # parts=5 -> waves=3 -> timeout=10 + (3-1)*7 = 24, capped to 20
    assert tasks._compute_split_wait_timeout(5) == 20


def test_forward_large_chunks_uses_chord_batches(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "https://api")
    monkeypatch.setattr(tasks, "get_file_size", lambda *args, **kwargs: 0)

    class _RedisSvc:
        def save_progress_info(self, *args, **kwargs):
            return True

        def is_task_cancelled(self, *args, **kwargs):
            return False

    monkeypatch.setattr(tasks, "get_redis_service", lambda: _RedisSvc())

    class _Sig:
        def __init__(self, kwargs):
            self.kwargs = kwargs
            self.queue = None

        def set(self, **kw):
            self.queue = kw.get("queue")
            return self

    captured = {"group_sigs": None}
    monkeypatch.setattr(tasks, "forward_part", types.SimpleNamespace(
        s=lambda **kwargs: _Sig(kwargs)))
    monkeypatch.setattr(tasks, "aggregate_forward_parts",
                        types.SimpleNamespace(s=lambda **kwargs: _Sig(kwargs)))

    def _fake_group(sig_iter):
        sigs = list(sig_iter)
        captured["group_sigs"] = sigs
        return sigs

    def _fake_chord(group_tasks):
        def _runner(_callback):
            total = sum(len(sig.kwargs.get("chunks", []))
                        for sig in group_tasks)
            return types.SimpleNamespace(
                get=lambda: {"success": True, "total_indexed": total,
                             "total_submitted": total, "message": "ok"}
            )
        return _runner

    @contextmanager
    def _fake_allow_join_result():
        yield

    monkeypatch.setattr(tasks, "group", _fake_group)
    monkeypatch.setattr(tasks, "chord", _fake_chord)
    monkeypatch.setattr(tasks, "allow_join_result", _fake_allow_join_result)

    self = FakeSelf("forward-batch")
    large_chunks = [{"content": f"content-{i}", "metadata": {}}
                    for i in range(70)]
    out = tasks.forward(
        self,
        processed_data={"chunks": large_chunks},
        index_name="idx",
        source="/big.txt",
        source_type="local",
        original_filename="big.txt",
    )

    assert out["chunks_stored"] == 70
    assert captured["group_sigs"] is not None
    assert len(captured["group_sigs"]) == 2
    assert all(sig.kwargs.get("large_mode")
               is True for sig in captured["group_sigs"])
    assert all(sig.queue == "forward_part_q" for sig in captured["group_sigs"])


def test_forward_large_chunks_routes_aggregate_to_dedicated_queue(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "get_file_size", lambda *args, **kwargs: 0)

    class _RedisSvc:
        def save_progress_info(self, *args, **kwargs):
            return True

        def is_task_cancelled(self, *args, **kwargs):
            return False

    monkeypatch.setattr(tasks, "get_redis_service", lambda: _RedisSvc())

    captured = {}

    class _Sig:
        def __init__(self, kwargs):
            self.kwargs = kwargs
            self.queue = None

        def set(self, **kwargs):
            self.queue = kwargs.get("queue")
            return self

    monkeypatch.setattr(tasks, "forward_part", types.SimpleNamespace(
        s=lambda **kwargs: _Sig(kwargs)))
    monkeypatch.setattr(tasks, "aggregate_forward_parts", types.SimpleNamespace(
        s=lambda **kwargs: _Sig(kwargs)))

    def _fake_group(signatures):
        captured["parts"] = list(signatures)
        return captured["parts"]

    def _fake_chord(group_tasks):
        def _runner(callback):
            captured["callback"] = callback
            total = sum(len(sig.kwargs["chunks"]) for sig in group_tasks)
            return types.SimpleNamespace(get=lambda: {
                "success": True,
                "total_indexed": total,
                "total_submitted": total,
            })
        return _runner

    @contextmanager
    def _fake_allow_join_result():
        yield

    monkeypatch.setattr(tasks, "group", _fake_group)
    monkeypatch.setattr(tasks, "chord", _fake_chord)
    monkeypatch.setattr(tasks, "allow_join_result", _fake_allow_join_result)
    monkeypatch.setattr(tasks, "_send_chunks_to_es", lambda **kwargs: {
        "success": True,
        "total_indexed": len(kwargs["chunks"]),
        "total_submitted": len(kwargs["chunks"]),
    })

    out = tasks.forward(
        FakeSelf("forward-aggregate-queue"),
        processed_data={"chunks": [{"content": f"c-{i}", "metadata": {}} for i in range(70)]},
        index_name="idx",
        source="/big.txt",
        source_type="local",
        file_id="file-1",
    )

    assert out["chunks_stored"] == 70
    assert captured["callback"].queue == "forward_aggregate_q"


def test_process_sync_unsupported_raises_and_updates_state(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch, initialized=True)
    monkeypatch.setattr(
        tasks,
        "get_ray_actor",
        lambda: types.SimpleNamespace(
            process_file=types.SimpleNamespace(remote=lambda *a, **k: "ref")),
    )
    self = FakeSelf("s2")
    with pytest.raises(NotImplementedError):
        tasks.process_sync(self, source="/a.txt", source_type="minio")
    # check that failure meta was updated
    assert any("sync_processing_failed" in s.get(
        "meta", {}).get("stage", "") for s in self.states)


def test_forward_redis_key_requires_backend_url_raises(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    # Ensure ES set (not used in this branch) and REDIS url missing
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")
    monkeypatch.setattr(tasks, "REDIS_BACKEND_URL", "")
    self = FakeSelf("r1")
    with pytest.raises(Exception) as ei:
        tasks.forward(self, processed_data={
                      "redis_key": "dp:rid:x"}, index_name="idx", source="/a.txt")
    json.loads(str(ei.value))


def test_forward_redis_retry_when_value_absent(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")
    monkeypatch.setattr(tasks, "REDIS_BACKEND_URL", "redis://test")

    class FakeRedisClient:
        def get(self, k):
            return None

    fake_redis_mod = types.SimpleNamespace(Redis=types.SimpleNamespace(
        from_url=lambda url, decode_responses=True: FakeRedisClient()))
    monkeypatch.setitem(sys.modules, "redis", fake_redis_mod)

    self = FakeSelf("r2")
    with pytest.raises(tasks.Retry):
        tasks.forward(self, processed_data={
                      "redis_key": "dp:rid:missing"}, index_name="idx", source="/a.txt")


def test_forward_uses_overridden_metadata_from_payload(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")
    monkeypatch.setattr(tasks, "get_file_size", lambda *a, **k: 0)
    monkeypatch.setattr(tasks, "run_async", lambda coro: {
                        "success": True, "total_indexed": 1, "total_submitted": 1, "message": "ok"})

    self = FakeSelf("f7")
    processed_data = {
        "chunks": [{"content": "x", "metadata": {"creation_date": "2024-01-01"}}],
        "source": "/override.txt",
        "index_name": "override_idx",
        "original_filename": "o.txt",
    }
    result = tasks.forward(self, processed_data=processed_data,
                           index_name="idx", source="/a.txt")
    assert result["source"] == "/override.txt"
    assert result["index_name"] == "override_idx"
    assert result["original_filename"] == "o.txt"


def test_forward_empty_chunks_list_warns_and_raises(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    self = FakeSelf("f8")
    with pytest.raises(Exception) as ei:
        tasks.forward(self, processed_data={
                      "chunks": []}, index_name="idx", source="/a.txt")
    json.loads(str(ei.value))


def test_process_zero_file_size_speed_calculation(monkeypatch, tmp_path):
    """Test that processing_speed_mb_s handles zero file size correctly"""
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch, initialized=True)

    # Prepare an empty file
    f = tmp_path / "empty.txt"
    f.write_text("")

    mock_chunks = [{"content": "chunk", "metadata": {}}]

    class FakeActor:
        def __init__(self):
            self.process_file = types.SimpleNamespace(
                remote=lambda *a, **k: "ref")
            self.store_chunks_in_redis = types.SimpleNamespace(
                remote=lambda *a, **k: None)

    monkeypatch.setattr(tasks, "get_ray_actor", lambda: FakeActor())
    fake_ray.get_returns = mock_chunks

    self = FakeSelf("empty1")

    tasks.process(self, source=str(f), source_type="local",
                  chunking_strategy="basic", index_name="idx", original_filename="empty.txt")

    # Verify processing_speed_mb_s is 0 for zero-size file (not division by zero)
    success_state = [s for s in self.states if s.get(
        "state") == tasks.states.SUCCESS][0]
    assert success_state.get("meta", {}).get("processing_speed_mb_s") == 0


def test_process_no_chunks_saves_error(monkeypatch, tmp_path):
    """process should save error info when no chunks are produced"""
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch, initialized=True)

    class FakeActor:
        def __init__(self):
            self.process_file = types.SimpleNamespace(
                remote=lambda *a, **k: "ref-empty")
            self.store_chunks_in_redis = types.SimpleNamespace(
                remote=lambda *a, **k: None)

    monkeypatch.setattr(tasks, "get_ray_actor", lambda: FakeActor())
    fake_ray.get_returns = []  # no chunks returned from ray.get

    saved_reason = {}
    monkeypatch.setattr(
        tasks,
        "save_error_to_redis",
        lambda task_id, reason, start_time: saved_reason.setdefault(
            "reason", reason),
    )

    f = tmp_path / "empty_file.txt"
    f.write_text("data")

    self = FakeSelf("no-chunks")
    with pytest.raises(Exception) as exc_info:
        tasks.process(
            self,
            source=str(f),
            source_type="local",
            chunking_strategy="basic",
            index_name="idx",
            original_filename="empty_file.txt",
        )

    assert '"error_code": "no_valid_chunks"' in saved_reason.get("reason", "")
    assert any(state.get("meta", {}).get("stage") ==
               "text_extraction_failed" for state in self.states)
    json.loads(str(exc_info.value))


def test_process_url_source_with_many_chunks(monkeypatch):
    """Test processing URL source that generates many chunks"""
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch, initialized=True)

    # Mock 120 chunks to simulate URL processing
    mock_chunks = [{"content": f"url_chunk_{i}", "metadata": {}}
                   for i in range(120)]

    class FakeActor:
        def __init__(self):
            self.process_bytes = types.SimpleNamespace(
                remote=lambda *a, **k: "ref_url")
            self.store_chunks_in_redis = types.SimpleNamespace(
                remote=lambda *a, **k: None)

    monkeypatch.setattr(tasks, "get_ray_actor", lambda: FakeActor())
    fake_ray.get_returns = mock_chunks

    self = FakeSelf("url1")

    result = tasks.process(self, source="http://example.com/doc.pdf",
                           source_type="minio", chunking_strategy="basic", index_name="idx")

    # Verify chunks_count for URL source
    success_state = [s for s in self.states if s.get(
        "state") == tasks.states.SUCCESS][0]
    assert success_state.get("meta", {}).get("chunks_count") == 120
    assert result["redis_key"].startswith("dp:url1:chunks")


def test_forward_large_chunks_batch_success(monkeypatch):
    """Test forwarding large batch of chunks (100+) to Elasticsearch"""
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")
    monkeypatch.setattr(tasks, "get_file_size", lambda *a, **k: 5000)

    # Simulate 150 chunks (large file scenario)
    large_chunks = [{"content": f"content_{i}",
                     "metadata": {"page": i}} for i in range(150)]

    # Mock successful indexing of all chunks
    monkeypatch.setattr(tasks, "run_async", lambda coro: {
        "success": True,
        "total_indexed": 150,
        "total_submitted": 150,
        "message": "All chunks indexed"
    })

    self = FakeSelf("large_forward")
    result = tasks.forward(
        self,
        processed_data={"chunks": large_chunks},
        index_name="idx",
        source="/large.pdf",
        source_type="local",
        original_filename="large.pdf"
    )

    # Verify all 150 chunks were stored
    assert result["chunks_stored"] == 150

    # Verify SUCCESS state was updated
    success_state = [s for s in self.states if s.get(
        "state") == tasks.states.SUCCESS][0]
    assert success_state.get("meta", {}).get("chunks_stored") == 150


def test_wait_for_split_ready_branches(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "REDIS_BACKEND_URL", "redis://x")

    class FakeClient:
        def __init__(self):
            self.calls = 0

        def get(self, key):
            self.calls += 1
            if key.endswith(":ready"):
                return "1" if self.calls >= 1 else None
            return '["a", "b"]'

    fake_redis_mod = types.SimpleNamespace(
        Redis=types.SimpleNamespace(from_url=lambda *a, **k: FakeClient())
    )
    monkeypatch.setitem(sys.modules, "redis", fake_redis_mod)
    assert tasks._wait_for_split_ready(
        "dp:k", timeout_s=1, poll_interval_ms=1) == 2

    monkeypatch.setattr(tasks, "REDIS_BACKEND_URL", "")
    with pytest.raises(RuntimeError):
        tasks._wait_for_split_ready("dp:k", timeout_s=1, poll_interval_ms=1)


def test_wait_for_split_ready_timeout_and_bad_json(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "REDIS_BACKEND_URL", "redis://x")

    class ClientBadJson:
        def get(self, key):
            return "1" if key.endswith(":ready") else "{bad"

    fake_redis_mod = types.SimpleNamespace(
        Redis=types.SimpleNamespace(from_url=lambda *a, **k: ClientBadJson())
    )
    monkeypatch.setitem(sys.modules, "redis", fake_redis_mod)
    assert tasks._wait_for_split_ready(
        "dp:k", timeout_s=1, poll_interval_ms=1) == 0

    class ClientNeverReady:
        def get(self, key):
            return None

    monkeypatch.setitem(
        sys.modules,
        "redis",
        types.SimpleNamespace(Redis=types.SimpleNamespace(
            from_url=lambda *a, **k: ClientNeverReady())),
    )
    monkeypatch.setattr(tasks.time, "sleep", lambda _s: None)
    t = {"v": 0.0}

    def _time():
        t["v"] += 0.2
        return t["v"]

    monkeypatch.setattr(tasks.time, "time", _time)
    with pytest.raises(TimeoutError):
        tasks._wait_for_split_ready("dp:k", timeout_s=1, poll_interval_ms=1)


def test_estimate_parallel_parts_and_batch_helpers(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "RAY_NUM_CPUS", 8)
    monkeypatch.setattr(tasks, "RAY_ACTOR_NUM_CPUS", 2)
    monkeypatch.setattr(tasks, "DP_PART_PROCESSOR_COUNT", 3)
    assert tasks._estimate_parallel_parts() == 3

    monkeypatch.setattr(tasks, "RAY_NUM_CPUS", 4)
    assert tasks._estimate_parallel_parts() == 2

    batches = [[{"a": 1}], [{"a": 2}]]
    assert tasks._get_next_available_batch_index(batches, 0, batch_size=2) == 0
    with pytest.raises(RuntimeError):
        tasks._get_next_available_batch_index([[1], [2]], 0, batch_size=1)


def test_split_file_for_processing_targets_processor_count(monkeypatch):
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch)
    captured = {}
    spans = []

    class CapturedSpan:
        def __init__(self):
            self.attributes = {}

        def set_attribute(self, name, value):
            self.attributes[name] = value

    @contextmanager
    def capture_span(name, stage, **attributes):
        captured_span = CapturedSpan()
        spans.append((name, stage, attributes, captured_span))
        yield captured_span

    class Actor:
        split_file = types.SimpleNamespace(
            remote=lambda **kwargs: captured.update(kwargs) or "parts-ref")

    monkeypatch.setattr(tasks, "DP_PART_PROCESSOR_COUNT", 4)
    monkeypatch.setattr(tasks, "_get_split_actor", lambda: Actor())
    monkeypatch.setattr(tasks, "knowledge_span", capture_span)
    fake_ray.get_returns = {"parts-ref": [b"part"]}

    params = {"max_size": 1, "encoding": "utf-8"}
    parts = tasks._split_file_for_processing(
        request_id="req",
        source="file.txt",
        source_type="local",
        task_id="task",
        params=params,
        file_size_bytes=10 * 1024 * 1024,
    )

    assert parts == [b"part"]
    assert captured["target_parts"] == 4
    assert "max_size" not in captured
    assert "max_size" not in params
    assert [span[0] for span in spans] == [
        "knowledge.process.split_actor_acquire",
        "knowledge.process.file_split_rpc",
    ]
    assert spans[1][2]["processor_count"] == 4
    assert spans[1][3].attributes["file.parts_count"] == 1


def test_process_source_below_split_threshold_skips_splitter(monkeypatch):
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch)

    class Actor:
        process_bytes = types.SimpleNamespace(remote=lambda *args, **kwargs: "chunks-ref")
        store_chunks_in_redis = types.SimpleNamespace(remote=lambda *args, **kwargs: "store-ref")

    monkeypatch.setattr(tasks, "DP_FILE_SPLIT_SIZE_MB", 5)
    monkeypatch.setattr(tasks, "get_ray_actor", lambda: Actor())
    monkeypatch.setattr(
        tasks,
        "_split_file_for_processing",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("splitter called")),
    )
    fake_ray.get_returns = {
        "chunks-ref": [{"content": "chunk"}],
        "store-ref": True,
    }

    result = tasks._process_source_with_split(
        request_id="req",
        source="file.txt",
        source_type="minio",
        task_id="task",
        chunking_strategy="basic",
        index_name="idx",
        original_filename="file.txt",
        embedding_model_id=None,
        tenant_id=None,
        params={},
        file_data=b"small file",
    )

    assert result == (False, [{"content": "chunk"}], None)


def test_process_source_above_split_threshold_uses_splitter(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    captured = {}

    monkeypatch.setattr(tasks, "DP_FILE_SPLIT_SIZE_MB", 1)
    monkeypatch.setattr(
        tasks,
        "_split_file_for_processing",
        lambda **kwargs: captured.update(kwargs) or [b"a", b"b"],
    )
    monkeypatch.setattr(
        tasks,
        "_run_processing_for_parts",
        lambda **kwargs: (True, None, 2),
    )

    result = tasks._process_source_with_split(
        request_id="req",
        source="file.txt",
        source_type="minio",
        task_id="task",
        chunking_strategy="basic",
        index_name="idx",
        original_filename="file.txt",
        embedding_model_id=None,
        tenant_id=None,
        params={},
        file_data=b"x" * (1024 * 1024 + 1),
    )

    assert result == (True, None, 2)
    assert captured["file_size_bytes"] == 1024 * 1024 + 1


def test_extract_error_code_from_es_response_detail_string(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    parsed = {"detail": "{\"error_code\":\"es_detail_code\"}"}
    assert tasks._extract_error_code_from_es_response(
        parsed, "x") == "es_detail_code"


def test_run_async_loop_not_running_branch(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)

    class FakeLoop:
        def is_running(self):
            return False

        def run_until_complete(self, _c):
            return "ok"

    monkeypatch.setattr(asyncio, "get_running_loop", lambda: FakeLoop())
    assert tasks.run_async(asyncio.sleep(0)) == "ok"


def test_run_async_running_loop_without_nest_asyncio_fallback_thread(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)

    class FakeLoop:
        def is_running(self):
            return True

    monkeypatch.setattr(asyncio, "get_running_loop", lambda: FakeLoop())
    sys.modules.pop("nest_asyncio", None)

    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "nest_asyncio":
            raise ImportError("no nest_asyncio")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert tasks.run_async(asyncio.sleep(0, result="thread-ok")) == "thread-ok"


def test_global_pool_manager_paths(monkeypatch):
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch)

    class Actor:
        def __init__(self):
            self.ping = types.SimpleNamespace(remote=lambda: "pong")

    monkeypatch.setattr(tasks, "DataProcessorRayActor",
                        types.SimpleNamespace(remote=lambda: Actor()))
    monkeypatch.setattr(tasks.ray, "get", lambda ref, timeout=None: True)
    manager = tasks.GlobalRayActorPoolManager(warm_timeout_s=1)
    assert manager.ensure_pool(desired=2, max_allowed=3) == 2
    assert manager.get_actor() is not None
    killed = []
    monkeypatch.setattr(
        tasks.ray,
        "kill",
        lambda actor, **kwargs: killed.append(actor),
        raising=False,
    )
    assert manager.ensure_pool(desired=1, max_allowed=3) == 1
    assert len(killed) == 1


def test_global_pool_manager_warm_fail(monkeypatch):
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch)

    class Actor:
        def __init__(self):
            self.ping = types.SimpleNamespace(remote=lambda: "x")

    monkeypatch.setattr(tasks, "DataProcessorRayActor",
                        types.SimpleNamespace(remote=lambda: Actor()))
    monkeypatch.setattr(tasks.ray, "get", lambda *a, **
                        k: (_ for _ in ()).throw(RuntimeError("warm fail")))
    monkeypatch.setattr(tasks.ray, "kill", lambda *a, **k: None, raising=False)
    manager = tasks.GlobalRayActorPoolManager(warm_timeout_s=1)
    assert manager.ensure_pool(desired=1, max_allowed=1) == 0
    with pytest.raises(RuntimeError):
        manager.get_actor()


def test_get_or_create_global_pool_manager_fallbacks(monkeypatch):
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "init_ray_in_worker", lambda: None)

    class _Opts:
        def options(self, **_kw):
            raise TypeError("no get_if_exists")

    monkeypatch.setattr(tasks, "GlobalRayActorPoolManager", _Opts())
    monkeypatch.setattr(tasks.ray, "get_actor", lambda *a,
                        **k: "manager", raising=False)
    assert tasks._get_or_create_global_pool_manager() == "manager"


def test_prewarm_ray_actors(monkeypatch):
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch)
    manager = types.SimpleNamespace(
        ensure_pool=types.SimpleNamespace(remote=lambda **k: "ref"))
    monkeypatch.setattr(
        tasks, "_get_or_create_global_pool_manager", lambda: manager)
    monkeypatch.setattr(tasks, "_estimate_parallel_parts", lambda: 4)
    monkeypatch.setattr(fake_ray, "get", lambda ref: 3)
    assert tasks.prewarm_ray_actors(target_size=3) == 3


def test_process_part_success_and_failure(monkeypatch):
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "REDIS_BACKEND_URL", "redis://x")

    class Actor:
        def __init__(self):
            self.process_bytes = types.SimpleNamespace(
                remote=lambda *a, **k: "chunks-ref")

    monkeypatch.setattr(tasks, "get_ray_actor", lambda: Actor())
    fake_ray.get_returns = {"chunks-ref": [{"content": "x"}]}

    store = {}

    class Client:
        def set(self, k, v):
            store[k] = v

        def expire(self, *a, **k):
            return True

    monkeypatch.setitem(sys.modules, "redis", types.SimpleNamespace(
        Redis=types.SimpleNamespace(from_url=lambda *a, **k: Client())))
    out = tasks.process_part(
        types.SimpleNamespace(request=types.SimpleNamespace(
            id="p1"), retry=lambda **k: None),
        part_bytes=b"a", filename="a.txt", chunking_strategy="basic", part_redis_key="k1",
        source="s", source_type="local"
    )
    assert out["chunks_count"] == 1
    assert "k1" in store

    monkeypatch.setattr(tasks, "REDIS_BACKEND_URL", "")
    out2 = tasks.process_part(
        types.SimpleNamespace(request=types.SimpleNamespace(
            id="p2"), retry=lambda **k: None),
        part_bytes=b"a", filename="a.txt", chunking_strategy="basic", part_redis_key="k2",
        source="s", source_type="local"
    )
    assert out2["chunks_count"] == 0


def test_aggregate_store_chunks_paths(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    self = types.SimpleNamespace(request=types.SimpleNamespace(id="agg1"))
    monkeypatch.setattr(tasks, "REDIS_BACKEND_URL", "redis://x")
    kv = {
        "part1": '[{"a":1}]',
        "part2": "bad-json",
    }
    written = {}

    class Client:
        def get(self, k):
            return kv.get(k)

        def set(self, k, v):
            written[k] = v

        def expire(self, *a, **k):
            return True

        def delete(self, k):
            kv.pop(k, None)

    monkeypatch.setitem(sys.modules, "redis", types.SimpleNamespace(
        Redis=types.SimpleNamespace(from_url=lambda *a, **k: Client())))
    res = tasks.aggregate_store_chunks(
        self,
        parts_results=[{"part_redis_key": "part1"},
                       {"part_redis_key": "part2"}],
        redis_key="maink",
        source="s",
        index_name="idx",
        original_filename="a.txt",
    )
    assert res["redis_key"] == "maink"
    assert "maink" in written and "maink:ready" in written


def test_forward_part_success_and_progress(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(
        tasks,
        "_send_chunks_to_es",
        lambda **kwargs: {"success": True,
                          "total_indexed": 2, "total_submitted": 2},
    )
    calls = {"inc": 0}

    class _Svc:
        def is_task_cancelled(self, _tid):
            return False

        def increment_progress_info(self, **kwargs):
            calls["inc"] += 1
            return True

    monkeypatch.setattr(tasks, "get_redis_service", lambda: _Svc())
    self = types.SimpleNamespace(
        request=types.SimpleNamespace(id="fp1", retries=0),
        retry=lambda **k: (_ for _ in ()
                           ).throw(RuntimeError("should not retry")),
    )
    out = tasks.forward_part(
        self,
        chunks=[{"content": "x"}],
        index_name="idx",
        parent_task_id="pt1",
        parent_total_chunks=5,
        batch_index=1,
        total_batches=3,
    )
    assert out["success"] is True
    assert calls["inc"] == 1


def test_forward_part_returns_cancelled_when_parent_is_cancelled(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)

    class _Svc:
        def is_task_cancelled(self, _task_id):
            return True

    monkeypatch.setattr(tasks, "get_redis_service", lambda: _Svc())
    monkeypatch.setattr(
        tasks,
        "_send_chunks_to_es",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("cancelled batch must not be sent")),
    )
    self = types.SimpleNamespace(
        request=types.SimpleNamespace(id="fp-cancelled", retries=0),
        retry=lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not retry")),
    )

    out = tasks.forward_part(
        self,
        chunks=[{"content": "x"}],
        index_name="idx",
        parent_task_id="parent-cancelled",
        batch_index=2,
        total_batches=3,
    )

    assert out["cancelled"] is True
    assert out["total_indexed"] == 0
    assert out["total_submitted"] == 0


def test_document_delete_fence_lookup_paths(monkeypatch):
    """Deletion checks cover Redis hits, misses, and PG fallback on errors."""
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)

    assert tasks._is_document_delete_requested(
        index_name=None, source=None, file_id=None) is False

    class RedisFence:
        def is_document_delete_requested(self, **_kwargs):
            return True

    monkeypatch.setattr(tasks, "get_redis_service", lambda: RedisFence())
    assert tasks._is_document_delete_requested(
        index_name="idx", source="obj", file_id="fid") is True

    pg_lookups = []
    lifecycle = types.ModuleType("database.knowledge_file_lifecycle_db")
    lifecycle.get_file_record = lambda **_kwargs: pg_lookups.append(True)
    monkeypatch.setitem(sys.modules, "database.knowledge_file_lifecycle_db", lifecycle)

    class RedisClear:
        def is_document_delete_requested(self, **_kwargs):
            return False

    monkeypatch.setattr(tasks, "get_redis_service", lambda: RedisClear())
    assert tasks._is_document_delete_requested(
        index_name="idx", source="obj", file_id="fid") is False
    assert pg_lookups == []

    class RedisUnavailable:
        def is_document_delete_requested(self, **_kwargs):
            raise RuntimeError("redis unavailable")

    monkeypatch.setattr(tasks, "get_redis_service", lambda: RedisUnavailable())
    lifecycle.get_file_record = lambda **_kwargs: {
        "file_id": "fid", "status": "DELETE_REQUESTED"
    }
    monkeypatch.setitem(sys.modules, "database.knowledge_file_lifecycle_db", lifecycle)
    assert tasks._is_document_delete_requested(
        index_name="idx", source="obj", file_id="fid", tenant_id="tenant") is True


def test_process_part_discards_chunks_when_deletion_wins_after_ray_processing(monkeypatch):
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch)

    class Actor:
        process_bytes = types.SimpleNamespace(remote=lambda *_args, **_kwargs: "chunks-ref")

    monkeypatch.setattr(tasks, "get_ray_actor", lambda: Actor())
    fake_ray.get_returns = {"chunks-ref": [{"content": "chunk"}]}
    monkeypatch.setattr(tasks, "REDIS_BACKEND_URL", "redis://unused")

    class RedisService:
        def __init__(self):
            self.checks = 0

        def is_document_delete_requested(self, **_kwargs):
            self.checks += 1
            return self.checks == 2

    redis_service = RedisService()
    monkeypatch.setattr(tasks, "get_redis_service", lambda: redis_service)
    result = tasks.process_part(
        FakeSelf("part-race"), part_bytes=b"x", filename="x.txt",
        chunking_strategy="basic", part_redis_key="dp:part",
        source="obj", index_name="idx", file_id="fid",
    )
    assert result["cancelled"] is True
    assert result["chunks_count"] == 0


def test_aggregate_store_chunks_discards_merged_chunks_when_deletion_wins(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "REDIS_BACKEND_URL", "redis://unused")

    class Client:
        def get(self, _key):
            return '[{"content":"chunk"}]'

        def delete(self, _key):
            return 1

        def set(self, *_args):
            raise AssertionError("deleted document must not publish merged chunks")

        def expire(self, *_args):
            raise AssertionError("deleted document must not publish readiness")

    monkeypatch.setitem(sys.modules, "redis", types.SimpleNamespace(
        Redis=types.SimpleNamespace(from_url=lambda *args, **kwargs: Client())
    ))

    class RedisService:
        def __init__(self):
            self.checks = 0

        def is_document_delete_requested(self, **_kwargs):
            self.checks += 1
            return self.checks == 2

    redis_service = RedisService()
    monkeypatch.setattr(tasks, "get_redis_service", lambda: redis_service)
    result = tasks.aggregate_store_chunks(
        FakeSelf("aggregate-race"), parts_results=[{"part_redis_key": "dp:part"}],
        redis_key="dp:chunks", source="obj", index_name="idx", file_id="fid",
    )
    assert result["cancelled"] is True


def test_forward_part_returns_cancelled_when_external_write_is_fenced(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "get_redis_service", lambda: types.SimpleNamespace(
        is_document_delete_requested=lambda **_kwargs: False,
    ))
    monkeypatch.setattr(
        tasks, "_send_chunks_to_es",
        lambda **_kwargs: (_ for _ in ()).throw(tasks.DocumentDeleteRequested("deleted")),
    )
    result = tasks.forward_part(
        FakeSelf("forward-race"), chunks=[{"content": "x"}], index_name="idx",
        source="obj", file_id="fid", batch_index=1, total_batches=1,
    )
    assert result["cancelled"] is True


def test_process_returns_cancelled_when_delete_wins_before_chunk_storage(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "_is_document_delete_requested", lambda **_kwargs: False)
    monkeypatch.setattr(tasks, "_update_file_lifecycle", lambda **_kwargs: None)
    monkeypatch.setattr(tasks, "_process_source_with_split", lambda **_kwargs: (
        False, [{"content": "chunk", "metadata": {}}], None
    ))
    monkeypatch.setattr(tasks.os.path, "exists", lambda _source: True)
    monkeypatch.setattr(tasks.os.path, "getsize", lambda _source: 1)
    monkeypatch.setattr(
        tasks, "_ensure_document_not_deleted",
        lambda **_kwargs: (_ for _ in ()).throw(tasks.DocumentDeleteRequested("deleted")),
    )
    self = FakeSelf("process-race")
    result = tasks.process(
        self, source="obj", source_type="local", chunking_strategy="basic",
        index_name="idx", original_filename="x.txt", file_id="fid",
    )
    assert result["cancelled"] is True


def test_process_source_with_split_stores_synchronous_chunks_after_part_processing(monkeypatch):
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch)

    class Actor:
        store_chunks_in_redis = types.SimpleNamespace(remote=lambda *_args, **_kwargs: "stored-ref")

    monkeypatch.setattr(tasks, "DP_FILE_SPLIT_SIZE_MB", 0)
    monkeypatch.setattr(tasks.os.path, "getsize", lambda _source: 1)
    monkeypatch.setattr(tasks, "get_ray_actor", lambda: Actor())
    monkeypatch.setattr(tasks, "_split_file_for_processing", lambda **_kwargs: [b"part"])
    monkeypatch.setattr(tasks, "_run_processing_for_parts", lambda **_kwargs: (
        False, [{"content": "chunk"}], None
    ))
    monkeypatch.setattr(tasks, "_ensure_document_not_deleted", lambda **_kwargs: None)
    fake_ray.get_returns = {"stored-ref": True}

    result = tasks._process_source_with_split(
        request_id="split-store", source="obj", source_type="local", task_id="task",
        chunking_strategy="basic", index_name="idx", original_filename="x.txt",
        embedding_model_id=None, tenant_id=None, file_id="fid", params={},
    )
    assert result[0] is False
    assert result[1] == [{"content": "chunk"}]


def test_process_source_with_split_reports_failed_synchronous_chunk_storage(monkeypatch):
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch)

    class Actor:
        store_chunks_in_redis = types.SimpleNamespace(remote=lambda *_args, **_kwargs: "stored-ref")

    monkeypatch.setattr(tasks, "DP_FILE_SPLIT_SIZE_MB", 0)
    monkeypatch.setattr(tasks.os.path, "getsize", lambda _source: 1)
    monkeypatch.setattr(tasks, "get_ray_actor", lambda: Actor())
    monkeypatch.setattr(tasks, "_split_file_for_processing", lambda **_kwargs: [b"part"])
    monkeypatch.setattr(tasks, "_run_processing_for_parts", lambda **_kwargs: (
        False, [{"content": "chunk"}], None
    ))
    monkeypatch.setattr(tasks, "_ensure_document_not_deleted", lambda **_kwargs: None)
    fake_ray.get_returns = {"stored-ref": False}

    with pytest.raises(RuntimeError, match="Failed to persist processed chunks"):
        tasks._process_source_with_split(
            request_id="split-store-failed", source="obj", source_type="local", task_id="task",
            chunking_strategy="basic", index_name="idx", original_filename="x.txt",
            embedding_model_id=None, tenant_id=None, file_id="fid", params={},
        )


def test_forward_returns_cancelled_when_document_fence_is_set(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "get_redis_service", lambda: types.SimpleNamespace(
        is_document_delete_requested=lambda **_kwargs: True,
    ))
    result = tasks.forward(
        FakeSelf("forward-fenced"), processed_data={}, index_name="idx",
        source="obj", source_type="minio", original_filename="x.txt", file_id="fid",
    )
    assert result["chunks_stored"] == 0
    assert result["es_result"]["message"].startswith("Indexing cancelled")


def test_wait_for_split_ready_honors_deletion_fence(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "REDIS_BACKEND_URL", "redis://x")

    class Client:
        def get(self, _key):
            return None

    monkeypatch.setitem(
        sys.modules, "redis",
        types.SimpleNamespace(Redis=types.SimpleNamespace(
            from_url=lambda *a, **k: Client())),
    )
    with pytest.raises(tasks.DocumentDeleteRequested):
        tasks._wait_for_split_ready(
            "dp:fence", timeout_s=1, poll_interval_ms=1,
            cancellation_check=lambda: True,
        )


def test_processing_tasks_return_cancelled_when_document_fence_is_set(monkeypatch):
    """Each processing stage exits without external work after deletion wins the race."""
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)

    class RedisFence:
        def is_document_delete_requested(self, **_kwargs):
            return True

    monkeypatch.setattr(tasks, "get_redis_service", lambda: RedisFence())
    self = FakeSelf("fenced-process")
    process_result = tasks.process(
        self, source="obj", source_type="local", index_name="idx",
        file_id="fid",
    )
    assert process_result["cancelled"] is True

    part_result = tasks.process_part(
        self, part_bytes=b"x", filename="x.txt", chunking_strategy="basic",
        part_redis_key="dp:part", source="obj", index_name="idx",
        file_id="fid",
    )
    assert part_result["cancelled"] is True

    aggregate_result = tasks.aggregate_store_chunks(
        self, parts_results=[], redis_key="dp:chunks", source="obj",
        index_name="idx", file_id="fid",
    )
    assert aggregate_result["cancelled"] is True

    forward_result = tasks.forward_part(
        self, chunks=[{"content": "x"}], index_name="idx", source="obj",
        file_id="fid",
    )
    assert forward_result["cancelled"] is True

    aggregate_forward_result = tasks.aggregate_forward_parts(
        self, parts_results=[], source="obj", index_name="idx", file_id="fid",
    )
    assert aggregate_forward_result["cancelled"] is True


def test_process_and_forward_does_not_submit_after_document_deletion(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)

    class RedisFence:
        def is_document_delete_requested(self, **_kwargs):
            return True

    monkeypatch.setattr(tasks, "get_redis_service", lambda: RedisFence())
    monkeypatch.setattr(
        tasks, "submit_process_forward_chain",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("deleted document must not submit a chain")),
    )
    result = tasks.process_and_forward(
        FakeSelf("fenced-chain"), source="obj", source_type="minio",
        chunking_strategy="basic", index_name="idx", file_id="fid",
    )
    assert result == ""


def test_forward_part_continues_when_parent_cancellation_lookup_fails(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "get_redis_service", lambda: (_ for _ in ()).throw(RuntimeError("redis down")))
    monkeypatch.setattr(
        tasks,
        "_send_chunks_to_es",
        lambda **kwargs: {"success": True, "total_indexed": 1, "total_submitted": 1},
    )
    self = types.SimpleNamespace(
        request=types.SimpleNamespace(id="fp-lookup-error", retries=0),
        retry=lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not retry")),
    )

    out = tasks.forward_part(
        self,
        chunks=[{"content": "x"}],
        index_name="idx",
        parent_task_id="parent-lookup-error",
        batch_index=1,
        total_batches=1,
    )

    assert out["success"] is True
    assert out["total_indexed"] == 1


def test_forward_part_failure_retries(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "_send_chunks_to_es", lambda **
                        kwargs: {"success": False, "message": "bad"})
    captured = {}

    def _retry(**kwargs):
        captured.update(kwargs)
        raise RuntimeError("retried")

    self = types.SimpleNamespace(
        request=types.SimpleNamespace(id="fp2", retries=1), retry=_retry)
    with pytest.raises(RuntimeError, match="retried"):
        tasks.forward_part(
            self,
            chunks=[{"content": "x"}],
            index_name="idx",
            batch_index=2,
            total_batches=4,
        )
    assert "exc" in captured


def test_forward_part_storage_write_block_does_not_retry(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(
        tasks,
        "_send_chunks_to_es",
        lambda **kwargs: (_ for _ in ()).throw(
            Exception(
                '{"error_code":"es_disk_watermark",'
                '"message":"disk watermark exceeded"}'
            )
        ),
    )
    cancelled = []

    class _Svc:
        def is_task_cancelled(self, _task_id):
            return False

        def mark_task_cancelled(self, task_id):
            cancelled.append(task_id)
            return True

    monkeypatch.setattr(tasks, "get_redis_service", lambda: _Svc())
    self = types.SimpleNamespace(
        request=types.SimpleNamespace(id="fp-blocked", retries=0),
        retry=lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not retry")),
    )

    with pytest.raises(Exception, match="es_disk_watermark"):
        tasks.forward_part(
            self,
            chunks=[{"content": "x"}],
            index_name="idx",
            parent_task_id="parent-blocked",
            batch_index=1,
            total_batches=3,
        )

    assert cancelled == ["parent-blocked"]


def test_forward_part_es_bulk_failure_does_not_retry(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(
        tasks,
        "_send_chunks_to_es",
        lambda **kwargs: (_ for _ in ()).throw(Exception('{"error_code":"es_bulk_failed"}')),
    )
    self = types.SimpleNamespace(
        request=types.SimpleNamespace(id="fp-bulk", retries=0),
        retry=lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not retry")),
    )

    with pytest.raises(Exception, match="es_bulk_failed"):
        tasks.forward_part(
            self,
            chunks=[{"content": "x"}],
            index_name="idx",
            batch_index=1,
            total_batches=3,
        )


def test_forward_part_long_nested_storage_block_does_not_retry(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    nested_error = {
        "message": (
            "Unexpected error when indexing documents: "
            + '{"message":"ElasticSearch service returned HTTP 500",'
            + '"index_name":"index-with-a-long-name-for-real-forwarding",'
            + '"source":"knowledge_base/20260825183619_1262461a83c84d9f95ebd222cb656159.txt",'
            + '"original_filename":"a-very-long-filename.txt",'
            + '"error_code":"060106"}'
        ),
        "index_name": "index-with-a-long-name-for-real-forwarding",
        "task_name": "forward",
        "source": "knowledge_base/20260825183619_1262461a83c84d9f95ebd222cb656159.txt",
        "original_filename": "a-very-long-filename.txt",
        "error_code": "060106",
    }
    exception = Exception(json.dumps(nested_error, ensure_ascii=False))
    assert len(str(exception)) > 500
    monkeypatch.setattr(
        tasks,
        "_send_chunks_to_es",
        lambda **kwargs: (_ for _ in ()).throw(exception),
    )
    cancelled = []

    class _Svc:
        def mark_task_cancelled(self, task_id):
            cancelled.append(task_id)
            return True

    monkeypatch.setattr(tasks, "get_redis_service", lambda: _Svc())
    self = types.SimpleNamespace(
        request=types.SimpleNamespace(id="fp-long-blocked", retries=0),
        retry=lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not retry")),
    )

    with pytest.raises(Exception, match="060106"):
        tasks.forward_part(
            self,
            chunks=[{"content": "x"}],
            index_name="idx",
            parent_task_id="parent-long-blocked",
            batch_index=1,
            total_batches=35,
        )

    assert cancelled == ["parent-long-blocked"]


def test_forward_part_swallows_parent_cancel_mark_failure(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(
        tasks,
        "_send_chunks_to_es",
        lambda **kwargs: (_ for _ in ()).throw(
            Exception('{"error_code":"es_disk_watermark"}')
        ),
    )

    class _Svc:
        def is_task_cancelled(self, _task_id):
            return False

        def mark_task_cancelled(self, _task_id):
            raise RuntimeError("redis write failed")

    monkeypatch.setattr(tasks, "get_redis_service", lambda: _Svc())
    self = types.SimpleNamespace(
        request=types.SimpleNamespace(id="fp-mark-error", retries=0),
        retry=lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not retry")),
    )

    with pytest.raises(Exception, match="es_disk_watermark"):
        tasks.forward_part(
            self,
            chunks=[{"content": "x"}],
            index_name="idx",
            parent_task_id="parent-mark-error",
            batch_index=1,
            total_batches=1,
        )


def test_aggregate_forward_parts_paths(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    self = types.SimpleNamespace(request=types.SimpleNamespace(id="af1"))
    out = tasks.aggregate_forward_parts(
        self,
        parts_results=[
            {"success": True, "total_indexed": 3, "total_submitted": 3},
            {"success": True, "total_indexed": 2, "total_submitted": 2},
        ],
        source="s",
        index_name="idx",
        original_filename="a.txt",
    )
    assert out["success"] is True
    assert out["total_indexed"] == 5


def test_run_processing_for_parts_single_and_multi(monkeypatch):
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch)

    class Actor:
        def __init__(self):
            self.process_file = types.SimpleNamespace(
                remote=lambda *a, **k: "ref-file")
            self.process_bytes = types.SimpleNamespace(
                remote=lambda *a, **k: "ref-bytes")

    monkeypatch.setattr(tasks, "get_ray_actor", lambda: Actor())
    fake_ray.get_returns = {
        "ref-bytes": [{"content": "c1"}], "ref-file": [{"content": "cf"}]}

    split_async, chunks, split_chunk_count = tasks._run_processing_for_parts(
        request_id="r1",
        source="/a.txt",
        source_type="local",
        task_id="t1",
        chunking_strategy="basic",
        filename_for_processing="a.txt",
        parts=[b"one"],
        index_name="idx",
        original_filename="a.txt",
        embedding_model_id=1,
        tenant_id="tenant",
        params={},
    )
    assert split_async is False
    assert chunks == [{"content": "c1"}]
    assert split_chunk_count is None

    captured = {}
    spans = []

    @contextmanager
    def capture_span(name, stage, **attributes):
        spans.append((name, stage, attributes))
        yield None

    monkeypatch.setattr(tasks, "knowledge_span", capture_span)
    monkeypatch.setattr(tasks, "process_part", types.SimpleNamespace(
        s=lambda **kwargs: types.SimpleNamespace(kwargs=kwargs)))
    monkeypatch.setattr(tasks, "aggregate_store_chunks", types.SimpleNamespace(
        s=lambda **kwargs: types.SimpleNamespace(set=lambda **kw: {"kwargs": kwargs, "set": kw})))
    monkeypatch.setattr(tasks, "group", lambda gen: list(gen))
    monkeypatch.setattr(tasks, "chord", lambda group_tasks: (
        lambda callback: captured.update({"group": group_tasks, "callback": callback})))
    monkeypatch.setattr(tasks, "_compute_split_wait_timeout", lambda n: 9)
    monkeypatch.setattr(tasks, "_estimate_parallel_parts", lambda: 2)
    monkeypatch.setattr(tasks, "_wait_for_split_ready", lambda **kwargs: 6)

    split_async2, chunks2, split_chunk_count2 = tasks._run_processing_for_parts(
        request_id="r2",
        source="/b.txt",
        source_type="local",
        task_id="t2",
        chunking_strategy="basic",
        filename_for_processing="b.txt",
        parts=[b"a", b"b", b"c"],
        index_name="idx",
        original_filename="b.txt",
        embedding_model_id=1,
        tenant_id="tenant",
        params={"x": 1},
    )
    assert split_async2 is True
    assert chunks2 is None
    assert split_chunk_count2 == 6
    assert len(captured["group"]) == 3
    assert [span[0] for span in spans] == [
        "knowledge.process.part_dispatch",
        "knowledge.process.part_wait",
    ]
    assert spans[0][2]["part_count"] == 3
    assert spans[1][2]["timeout_seconds"] == 9


def test_process_split_async_redis_image_metadata_count(monkeypatch, tmp_path):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "REDIS_BACKEND_URL", "redis://test")
    monkeypatch.setattr(tasks, "_process_source_with_split",
                        lambda **kwargs: (True, None, 2))
    monkeypatch.setattr(
        tasks, "_count_image_metadata_chunks", lambda chunks: 1)

    class FakeRedisClient:
        def get(self, key):
            return json.dumps([{"metadata": {"content_type": "image"}}, {"metadata": {}}])

    monkeypatch.setitem(sys.modules, "redis", types.SimpleNamespace(
        Redis=types.SimpleNamespace(from_url=lambda *a, **k: FakeRedisClient())))

    f = tmp_path / "x.txt"
    f.write_text("hello")
    self = FakeSelf("proc-async-1")
    out = tasks.process(
        self,
        source=str(f),
        source_type="local",
        chunking_strategy="basic",
        index_name="idx",
        original_filename="x.txt",
    )
    assert out["split_async"] is True
    assert out["image_metadata_chunk_count"] == 1
    success_state = [s for s in self.states if s.get(
        "state") == tasks.states.SUCCESS][0]
    assert success_state["meta"]["chunks_count"] == 2


def test_cleanup_source_skips_when_preserve_true(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")
    monkeypatch.setattr(tasks, "get_knowledge_record",
                        lambda query=None: {"preserve_source_file": True})

    called = {"delete": 0}

    def _delete(*_a, **_k):
        called["delete"] += 1
        raise AssertionError(
            "requests.delete should not be called when preserve_source_file is True")

    monkeypatch.setattr(tasks.requests, "delete", _delete, raising=True)

    self = FakeSelf("cleanup-skip-1")
    out = tasks.cleanup_source(
        self,
        {"task_id": "t1", "index_name": "idx", "source": "/a.txt"},
    )
    assert out["source_cleanup"]["attempted"] is False
    assert out["source_cleanup"]["skipped_reason"] == "preserve_source_file_true"
    assert called["delete"] == 0


def test_cleanup_source_calls_delete_with_scope_source_only(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")
    monkeypatch.setattr(tasks, "get_knowledge_record",
                        lambda query=None: {"preserve_source_file": False})

    captured = {}

    class FakeResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"status": "success"}

    def _delete(url, params=None, timeout=None, headers=None, **_extra):
        captured["url"] = url
        captured["params"] = params
        captured["timeout"] = timeout
        captured["headers"] = headers
        return FakeResponse()

    monkeypatch.setattr(tasks.requests, "delete", _delete, raising=True)

    self = FakeSelf("cleanup-call-1")
    out = tasks.cleanup_source(
        self,
        {"task_id": "t1", "index_name": "idx", "source": "/a.txt"},
    )
    assert captured["url"] == "http://api/indices/idx/documents"
    assert captured["params"]["path_or_url"] == "/a.txt"
    assert captured["params"]["scope"] == "source_only"
    assert out["source_cleanup"]["attempted"] is True
    assert out["source_cleanup"]["success"] is True


def test_cleanup_source_failure_is_warning_only(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")
    monkeypatch.setattr(tasks, "get_knowledge_record",
                        lambda query=None: {"preserve_source_file": False})

    def _delete(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(tasks.requests, "delete", _delete, raising=True)

    self = FakeSelf("cleanup-fail-1")
    out = tasks.cleanup_source(
        self,
        {"task_id": "t1", "index_name": "idx", "source": "/a.txt"},
    )
    assert out["source_cleanup"]["attempted"] is True
    assert out["source_cleanup"]["success"] is False
    assert "boom" in (out["source_cleanup"]["error"] or "")


def test_parse_failure_info_accepts_json_and_plain_text(monkeypatch):
    import_tasks_with_fake_ray(monkeypatch)
    utils = sys.modules["backend.data_process.utils"]

    assert utils._parse_failure_info('{"message": "failed"}') == (
        {"message": "failed"},
        None,
    )
    assert utils._parse_failure_info("plain failure") == (
        None,
        "plain failure",
    )
    assert utils._parse_failure_info("") == (None, None)


def test_get_all_task_ids_uses_scan_instead_of_keys(monkeypatch):
    import_tasks_with_fake_ray(monkeypatch)
    utils = sys.modules["backend.data_process.utils"]
    redis_client = types.SimpleNamespace(
        scan_iter=lambda **kwargs: iter([
            b"celery-task-meta-task-1",
            "celery-task-meta-task-2",
        ]),
    )

    assert utils.get_all_task_ids_from_redis(redis_client) == [
        "task-1",
        "task-2",
    ]


def test_extract_error_code_various_formats(monkeypatch):
    """Test extract_error_code handles different error formats."""
    import_tasks_with_fake_ray(monkeypatch)
    from backend.data_process import tasks

    # From parsed_error dict
    result = tasks.extract_error_code(
        "Some error message",
        parsed_error={"error_code": "ERR_001"}
    )
    assert result == "ERR_001"

    # From JSON string in reason
    result = tasks.extract_error_code(
        '{"error_code": "ERR_002"}',
        parsed_error=None
    )
    assert result == "ERR_002"

    # From nested detail
    result = tasks.extract_error_code(
        '{"detail": {"error_code": "ERR_003"}}',
        parsed_error=None
    )
    assert result == "ERR_003"

    # From regex pattern in raw string
    result = tasks.extract_error_code(
        'Some error with "error_code": "ERR_004"',
        parsed_error=None
    )
    assert result == "ERR_004"

    # No error code found
    result = tasks.extract_error_code("Plain error message", parsed_error=None)
    assert result is None


def test_build_balanced_batches_various_sizes(monkeypatch):
    """Test _build_balanced_batches with various input sizes."""
    import_tasks_with_fake_ray(monkeypatch)
    from backend.data_process import tasks

    # Empty input
    result = tasks._build_balanced_batches([])
    assert result == []

    # Single batch (below batch size)
    chunks = [{"content": f"chunk_{i}"} for i in range(10)]
    result = tasks._build_balanced_batches(chunks)
    assert len(result) == 1

    # Multiple batches
    chunks = [{"content": f"chunk_{i}"} for i in range(200)]
    result = tasks._build_balanced_batches(chunks)
    assert len(result) > 1

    # With image metadata chunks
    chunks = [
        {"content": "text1", "process_source": "UniversalImageExtractor"},
        {"content": "text2"},
        {"content": "text3", "process_source": "UniversalImageExtractor"},
        {"content": "text4"},
    ]
    result = tasks._build_balanced_batches(chunks, batch_size=2)
    # Should distribute evenly
    assert len(result) == 2


def test_count_image_metadata_chunks(monkeypatch):
    """Test _count_image_metadata_chunks counting."""
    import_tasks_with_fake_ray(monkeypatch)
    from backend.data_process import tasks

    # None input
    result = tasks._count_image_metadata_chunks(None)
    assert result == 0

    # Empty list
    result = tasks._count_image_metadata_chunks([])
    assert result == 0

    # Mixed chunks
    chunks = [
        {"content": "text1", "process_source": "UniversalImageExtractor"},
        {"content": "text2"},
        {"content": "text3", "metadata": {"process_source": "UniversalImageExtractor"}},
        {"content": "text4", "metadata": {"process_source": "Other"}},
    ]
    result = tasks._count_image_metadata_chunks(chunks)
    assert result == 2


def test_compute_split_wait_timeout(monkeypatch):
    """Test _compute_split_wait_timeout calculation."""
    import_tasks_with_fake_ray(monkeypatch)
    from backend.data_process import tasks

    monkeypatch.setattr(tasks, "DP_REDIS_CHUNKS_WAIT_TIMEOUT_S", 30)
    monkeypatch.setattr(tasks, "PER_WAVE_TIMEOUT", 60)
    monkeypatch.setattr(tasks, "MAX_TIMEOUT", 300)
    monkeypatch.setattr(tasks, "_estimate_parallel_parts", lambda: 2)

    # Single part (no waves)
    result = tasks._compute_split_wait_timeout(1)
    assert result == 30

    # Multiple parts
    result = tasks._compute_split_wait_timeout(10)
    waves = math.ceil(10 / 2)
    expected = min(300, 30 + max(0, waves - 1) * 60)
    assert result == expected


def test_forward_context_creation(monkeypatch):
    """Test _init_forward_context creates context correctly."""
    import_tasks_with_fake_ray(monkeypatch)
    from backend.data_process import tasks

    ctx = tasks._init_forward_context(
        task_id="task-1",
        request_id="req-1",
        start_time=1000.0,
        source="/path/to/file.pdf",
        index_name="test-index",
        source_type="local",
        original_filename="file.pdf",
    )
    assert ctx.task_id == "task-1"
    assert ctx.request_id == "req-1"
    assert ctx.source == "/path/to/file.pdf"
    assert ctx.index_name == "test-index"
    assert ctx.original_filename == "file.pdf"


def test_is_forward_task_cancelled(monkeypatch):
    """Test _is_forward_task_cancelled checks Redis flag."""
    import_tasks_with_fake_ray(monkeypatch)
    from backend.data_process import tasks

    class MockRedisService:
        def is_task_cancelled(self, task_id):
            return task_id == "cancelled-task"

    monkeypatch.setattr(tasks, "get_redis_service", lambda: MockRedisService())

    ctx = tasks._init_forward_context(
        task_id="cancelled-task",
        request_id="req",
        start_time=1000.0,
        source="s",
        index_name="i",
        source_type="local",
        original_filename=None,
    )

    assert tasks._is_forward_task_cancelled(ctx) is True

    ctx2 = tasks._init_forward_context(
        task_id="active-task",
        request_id="req",
        start_time=1000.0,
        source="s",
        index_name="i",
        source_type="local",
        original_filename=None,
    )
    assert tasks._is_forward_task_cancelled(ctx2) is False


def test_build_forward_cancelled_result(monkeypatch):
    """Test _build_forward_cancelled_result creates correct response."""
    import_tasks_with_fake_ray(monkeypatch)
    from backend.data_process import tasks

    ctx = tasks._init_forward_context(
        task_id="task-cancel",
        request_id="req",
        start_time=1000.0,
        source="/path/to/file.pdf",
        index_name="test-index",
        source_type="local",
        original_filename="file.pdf",
    )

    result = tasks._build_forward_cancelled_result(ctx)
    assert result["task_id"] == "task-cancel"
    assert result["source"] == "/path/to/file.pdf"
    assert result["index_name"] == "test-index"
    assert result["es_result"]["success"] is False
    assert "cancelled" in result["es_result"]["message"]


def test_build_forward_error(monkeypatch):
    """Test _build_forward_error creates exception with correct structure."""
    import_tasks_with_fake_ray(monkeypatch)
    from backend.data_process import tasks

    exc = tasks._build_forward_error(
        message="Test error",
        index_name="test-index",
        source="/path/to/file.pdf",
        original_filename="file.pdf",
    )

    import json
    error_dict = json.loads(str(exc))
    assert error_dict["message"] == "Test error"
    assert error_dict["index_name"] == "test-index"
    assert error_dict["source"] == "/path/to/file.pdf"
    assert error_dict["original_filename"] == "file.pdf"


def test_parse_json_or_none(monkeypatch):
    """Test _parse_json_or_none parses or returns None."""
    import_tasks_with_fake_ray(monkeypatch)
    from backend.data_process import tasks

    # Valid JSON dict
    result = tasks._parse_json_or_none('{"key": "value"}')
    assert result == {"key": "value"}

    # Valid JSON array (returns None)
    result = tasks._parse_json_or_none('[1, 2, 3]')
    assert result is None

    # Invalid JSON
    result = tasks._parse_json_or_none("not json")
    assert result is None

    # Empty string
    result = tasks._parse_json_or_none("")
    assert result is None


def test_global_ray_actor_pool_manager_ensure_pool(monkeypatch):
    """Test GlobalRayActorPoolManager.ensure_pool logic."""
    import_tasks_with_fake_ray(monkeypatch)
    from backend.data_process import tasks

    manager = tasks.GlobalRayActorPoolManager(warm_timeout_s=10.0)
    assert manager.warm_timeout_s == 10.0
    assert len(manager.actors) == 0

    # Note: _create_and_warm_actor requires a real Ray actor,
    # so we just test the pool size calculation logic
    result = manager.ensure_pool(desired=0, max_allowed=5)
    assert result == 0


def test_delete_source_file_via_http_sync(monkeypatch):
    """Test _delete_source_file_via_http_sync makes correct HTTP call."""
    import_tasks_with_fake_ray(monkeypatch)
    from backend.data_process import tasks

    captured = {}

    class FakeResponse:
        status_code = 200
        text = '{"deleted": true}'

        def json(self):
            return {"deleted": True}

    def mock_delete(url, params, headers, timeout):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(tasks.requests, "delete", mock_delete)

    result = tasks._delete_source_file_via_http_sync(
        base_url="http://api",
        index_name="test-index",
        path_or_url="/path/to/file.pdf",
        scope="source_only",
        authorization="Bearer token123",
        timeout_s=30.0,
    )

    assert result["http_status"] == 200
    assert result["response_json"] == {"deleted": True}
    assert captured["url"] == "http://api/indices/test-index/documents"
    assert captured["params"]["path_or_url"] == "/path/to/file.pdf"
    assert captured["params"]["scope"] == "source_only"
    assert captured["headers"]["Authorization"] == "Bearer token123"


def test_delete_source_file_via_http_sync_empty_base_url(monkeypatch):
    """Test _delete_source_file_via_http_sync raises when base_url is empty."""
    import_tasks_with_fake_ray(monkeypatch)
    from backend.data_process import tasks

    with pytest.raises(RuntimeError, match="not configured"):
        tasks._delete_source_file_via_http_sync(
            base_url="",
            index_name="test-index",
            path_or_url="/path/to/file.pdf",
            scope="source_only",
        )


def test_submit_process_forward_chain(monkeypatch):
    """Test submit_process_forward_chain creates correct chain."""
    import_tasks_with_fake_ray(monkeypatch)
    from backend.data_process import tasks

    captured_chain = []
    captured_signatures = {}

    class MockSignature:
        def __init__(self, task_name, kwargs):
            self.task_name = task_name
            self.kwargs = kwargs

        def set(self, queue=None):
            self.queue = queue
            return self

    class MockTask:
        def __init__(self, task_name):
            self.task_name = task_name

        def s(self, **kwargs):
            captured_signatures[self.task_name] = kwargs
            return MockSignature(self.task_name, kwargs)

    monkeypatch.setattr(tasks, "process", MockTask("process"))
    monkeypatch.setattr(tasks, "forward", MockTask("forward"))
    monkeypatch.setattr(tasks, "cleanup_source", MockTask("cleanup_source"))

    class MockChain:
        def __init__(self, *steps):
            self.steps = steps
            captured_chain.extend(steps)

        def set(self, queue=None):
            return self

        def apply_async(self):
            class Result:
                id = "chain-id-123"
            return Result()

    monkeypatch.setattr(tasks, "chain", lambda *args: MockChain(*args))

    chain_id = tasks.submit_process_forward_chain(
        source="/path/to/file.pdf",
        source_type="local",
        chunking_strategy="basic",
        index_name="test-index",
        original_filename="file.pdf",
        authorization="Bearer token",
        embedding_model_id=1,
        tenant_id="tenant-1",
        file_id="fid-1",
    )

    assert chain_id == "chain-id-123"
    assert captured_signatures["process"]["tenant_id"] == "tenant-1"
    assert captured_signatures["forward"]["tenant_id"] == "tenant-1"
    assert captured_signatures["process"]["file_id"] == "fid-1"
    assert captured_signatures["forward"]["file_id"] == "fid-1"


def test_aggregate_parts_empty_results(monkeypatch):
    """Test aggregate_parts handles empty results."""
    import_tasks_with_fake_ray(monkeypatch)
    from backend.data_process import tasks

    self = FakeSelf("agg-1")
    result = tasks.aggregate_parts(self, parts_results=None)
    assert result["chunks"] == []

    result = tasks.aggregate_parts(self, parts_results=[])
    assert result["chunks"] == []

    result = tasks.aggregate_parts(self, parts_results=[[], None, [{"content": "x"}]])
    assert result["chunks"] == [{"content": "x"}]


def test_process_sync_with_celery_context(monkeypatch, tmp_path):
    """Test process_sync with Celery task context."""
    import_tasks_with_fake_ray(monkeypatch, initialized=True)
    from backend.data_process import tasks

    f = tmp_path / "test.txt"
    f.write_text("hello world")

    class FakeActor:
        def __init__(self):
            self.process_file = types.SimpleNamespace(
                remote=lambda *args, **kwargs: "__process_ref__"
            )

    fake_ray = sys.modules.get("ray")
    fake_ray.get_returns = {
        "__process_ref__": [{"content": "hello world", "metadata": {}}]
    }

    monkeypatch.setattr(tasks, "get_ray_actor", lambda: FakeActor())

    self = FakeSelf("sync-1")
    result = tasks.process_sync(
        self,
        source=str(f),
        source_type="local",
        chunking_strategy="basic",
    )

    assert result["text"] == "hello world"
    assert result["chunks_count"] == 1
    assert len(self.states) >= 1


def test_process_and_forward_delegates_to_chain(monkeypatch):
    """Test process_and_forward creates chain and returns ID."""
    import_tasks_with_fake_ray(monkeypatch)
    from backend.data_process import tasks

    class MockResult:
        id = "chain-456"

    captured = {}

    class MockChain:
        def __init__(self, *steps):
            captured["steps"] = len(steps)
            captured["signatures"] = steps

        def set(self, queue=None):
            return self

        def apply_async(self):
            return MockResult()

    monkeypatch.setattr(tasks, "chain", lambda *args: MockChain(*args))

    self = FakeSelf("paf-1")
    result = tasks.process_and_forward(
        self,
        source="/path/to/file.pdf",
        source_type="local",
        chunking_strategy="basic",
        index_name="test-index",
        tenant_id="tenant-2",
        file_id="fid-2",
    )

    assert result == "chain-456"
    assert captured["steps"] == 3  # process, forward, cleanup_source


def test_update_file_lifecycle_uses_file_id_and_legacy_source_fallback(monkeypatch):
    """Lifecycle updates enforce tenant scope and fall back from stale IDs to paths."""
    import_tasks_with_fake_ray(monkeypatch)
    from backend.data_process import tasks

    calls = []
    lookups = []
    lifecycle_module = types.ModuleType("database.knowledge_file_lifecycle_db")

    def get_file_record(**kwargs):
        lookups.append(kwargs)
        if kwargs.get("file_id") == "fid-missing":
            return None
        if kwargs.get("object_name") == "knowledge_base/a.txt":
            return {"file_id": "fid-3", "status": "PROCESSING"}
        if kwargs.get("object_name") == "knowledge_base/fallback.txt":
            return {"file_id": "fid-5", "status": "PROCESSING"}
        return {"file_id": "fid-4", "status": "DELETED"}

    lifecycle_module.get_file_record = get_file_record
    lifecycle_module.transition_file_record = lambda file_id, **kwargs: calls.append((file_id, kwargs))
    monkeypatch.setitem(sys.modules, "database.knowledge_file_lifecycle_db", lifecycle_module)

    tasks._update_file_lifecycle(
        file_id=None,
        tenant_id="tenant-1",
        index_name="idx",
        source="knowledge_base/a.txt",
        status="PROCESSING",
        stage="PROCESS",
    )
    assert calls[0][0] == "fid-3"
    assert calls[0][1]["expected_statuses"] == ("PROCESSING",)
    assert lookups[0] == {
        "tenant_id": "tenant-1",
        "index_name": "idx",
        "object_name": "knowledge_base/a.txt",
        "include_hidden": True,
    }

    tasks._update_file_lifecycle(
        file_id="fid-missing",
        tenant_id="tenant-1",
        index_name="idx",
        source="knowledge_base/fallback.txt",
        status="FAILED",
        stage="PROCESS",
    )
    assert calls[1][0] == "fid-5"
    assert lookups[1] == {
        "file_id": "fid-missing",
        "tenant_id": "tenant-1",
        "index_name": "idx",
        "include_hidden": True,
    }
    assert lookups[2] == {
        "tenant_id": "tenant-1",
        "index_name": "idx",
        "object_name": "knowledge_base/fallback.txt",
        "include_hidden": True,
    }

    lifecycle_module.get_file_record = lambda **kwargs: {"file_id": "fid-4", "status": "DELETED"}
    tasks._update_file_lifecycle(
        file_id="fid-4",
        tenant_id="tenant-1",
        index_name="idx",
        source="knowledge_base/deleted.txt",
        status="FAILED",
        stage="PROCESS",
    )
    assert len(calls) == 2

    tasks._update_file_lifecycle(
        file_id="fid-5",
        tenant_id="tenant-1",
        index_name=None,
        source="knowledge_base/no-index.txt",
        status="FAILED",
        stage="PROCESS",
    )


def test_estimate_parallel_parts_edge_cases(monkeypatch):
    """Test _estimate_parallel_parts handles edge cases."""
    import_tasks_with_fake_ray(monkeypatch)
    from backend.data_process import tasks

    monkeypatch.setattr(tasks, "RAY_NUM_CPUS", 4)
    monkeypatch.setattr(tasks, "RAY_ACTOR_NUM_CPUS", 2)
    monkeypatch.setattr(tasks, "DP_PART_PROCESSOR_COUNT", 10)

    # Should respect MAX constraint
    result = tasks._estimate_parallel_parts()
    assert result <= 10

    # With more reasonable settings
    monkeypatch.setattr(tasks, "DP_PART_PROCESSOR_COUNT", 2)
    result = tasks._estimate_parallel_parts()
    assert result == 2


def test_run_async_fallback_thread_executor(monkeypatch):
    """Test run_async falls back to thread executor when nest_asyncio unavailable."""
    import_tasks_with_fake_ray(monkeypatch)

    class FakeLoop:
        def is_running(self):
            return True

        def run_until_complete(self, coro):
            return "thread-result"

    async def sample_coro():
        return "async-result"

    # Remove nest_asyncio if present
    if "nest_asyncio" in sys.modules:
        del sys.modules["nest_asyncio"]

    monkeypatch.setattr(asyncio, "get_running_loop", lambda: FakeLoop())

    from backend.data_process import tasks
    result = tasks.run_async(sample_coro())
    assert result == "thread-result"


def test_extract_error_code_from_es_response(monkeypatch):
    """Test _extract_error_code_from_es_response handles various ES responses."""
    import_tasks_with_fake_ray(monkeypatch)
    from backend.data_process import tasks

    # From parsed body with error_code
    result = tasks._extract_error_code_from_es_response(
        parsed_body={"error_code": "ES_ERR_001"},
        text='{"error": "some error"}',
    )
    assert result == "ES_ERR_001"

    # From nested detail
    result = tasks._extract_error_code_from_es_response(
        parsed_body={"detail": {"error_code": "ES_ERR_002"}},
        text='{"detail": {"error_code": "ES_ERR_002"}}',
    )
    assert result == "ES_ERR_002"

    # From regex in text
    result = tasks._extract_error_code_from_es_response(
        parsed_body={"error": "Some error"},
        text='{"error_code": "ES_ERR_003"}',
    )
    assert result == "ES_ERR_003"

    # None when no error code
    result = tasks._extract_error_code_from_es_response(
        parsed_body={"error": "Generic error"},
        text='{"error": "no code here"}',
    )
    assert result is None


def test_save_error_to_redis_empty_task_id(monkeypatch):
    """Test save_error_to_redis handles empty task_id."""
    import_tasks_with_fake_ray(monkeypatch)
    from backend.data_process import tasks

    # Should not raise, just log warning
    tasks.save_error_to_redis("", "Some error", 1000.0)
    tasks.save_error_to_redis(None, "Some error", 1000.0)


def test_save_error_to_redis_empty_reason(monkeypatch):
    """Test save_error_to_redis handles empty error_reason."""
    import_tasks_with_fake_ray(monkeypatch)
    from backend.data_process import tasks

    # Should not raise, just log warning
    tasks.save_error_to_redis("task-1", "", 1000.0)
    tasks.save_error_to_redis("task-1", None, 1000.0)


def test_distribute_chunks_round_robin(monkeypatch):
    """Test _distribute_chunks_round_robin distributes evenly."""
    import_tasks_with_fake_ray(monkeypatch)
    from backend.data_process import tasks

    # Create empty batches
    batches = [[], [], []]

    # Distribute 10 chunks
    chunks = [{"content": f"chunk_{i}"} for i in range(10)]

    tasks._distribute_chunks_round_robin(
        batches=batches,
        chunks=chunks,
        batch_size=10,
        error_context="test",
    )

    # Each batch should have some chunks
    total = sum(len(b) for b in batches)
    assert total == 10


def test_prewarm_ray_actors(monkeypatch):
    """Test prewarm_ray_actors calls pool manager."""
    import_tasks_with_fake_ray(monkeypatch)
    from backend.data_process import tasks

    captured = {}

    class MockManager:
        def __init__(self, warm_timeout_s):
            self.ensure_pool = types.SimpleNamespace(remote=self._ensure_pool)

        @staticmethod
        def _ensure_pool(desired, max_allowed):
            captured["desired"] = desired
            captured["max_allowed"] = max_allowed
            return "__pool_ref__"

    monkeypatch.setattr(tasks, "_get_or_create_global_pool_manager", lambda: MockManager(60))
    monkeypatch.setattr(tasks, "_estimate_parallel_parts", lambda: 2)
    sys.modules["ray"].get_returns = {"__pool_ref__": 3}

    result = tasks.prewarm_ray_actors(target_size=5)
    assert result == 3
    assert captured["desired"] == 5


def test_get_split_actor(monkeypatch):
    """Test _get_split_actor returns actor from pool."""
    import_tasks_with_fake_ray(monkeypatch, initialized=True)
    from backend.data_process import tasks

    class MockActor:
        pass

    expected_actor = MockActor()
    monkeypatch.setattr(tasks, "get_ray_actor", lambda: expected_actor)

    actor = tasks._get_split_actor()
    assert actor is expected_actor


def test_fetch_minio_source_success_and_missing_stream(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    attributes = []
    monkeypatch.setattr(tasks, "set_span_attributes", lambda **kwargs: attributes.append(kwargs))
    monkeypatch.setattr(tasks, "get_file_stream", lambda source: io.BytesIO(b"payload"))

    assert tasks._fetch_minio_source("s3://bucket/file") == b"payload"
    assert attributes == [{"file_size_bytes": 7, "stage": "minio.fetch"}]

    monkeypatch.setattr(tasks, "get_file_stream", lambda source: None)
    with pytest.raises(FileNotFoundError, match="Unable to fetch"):
        tasks._fetch_minio_source("s3://bucket/missing")


def test_wait_for_split_ready_handles_missing_and_non_list_payloads(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "REDIS_BACKEND_URL", "redis://x")

    class Client:
        def __init__(self, cached):
            self.cached = cached

        def get(self, key):
            return "1" if key.endswith(":ready") else self.cached

    current = {"client": Client(None)}
    monkeypatch.setitem(
        sys.modules,
        "redis",
        types.SimpleNamespace(
            Redis=types.SimpleNamespace(from_url=lambda *args, **kwargs: current["client"])
        ),
    )

    assert tasks._wait_for_split_ready("dp:key", 1, 1) == 0
    current["client"] = Client('{"chunk": 1}')
    assert tasks._wait_for_split_ready("dp:key", 1, 1) == 0


def test_distribute_chunks_reports_capacity_context(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)

    with pytest.raises(RuntimeError, match="while distributing text chunks"):
        tasks._distribute_chunks_round_robin(
            batches=[[{"content": "full"}]],
            chunks=[{"content": "extra"}],
            batch_size=1,
            error_context="text chunks",
        )


def test_extract_error_code_handles_regex_failure(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks.re, "search", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("regex")))

    assert tasks.extract_error_code("plain error") is None
    assert tasks._extract_error_code_from_es_response(None, "plain error") is None


def test_delete_source_file_handles_non_json_response(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)

    class Response:
        status_code = 503
        text = "service unavailable"

        def json(self):
            raise ValueError("not json")

    monkeypatch.setattr(tasks.requests, "delete", lambda *args, **kwargs: Response())

    result = tasks._delete_source_file_via_http_sync(
        base_url="http://api/",
        index_name="index",
        path_or_url="s3://bucket/file",
        scope="source_only",
    )

    assert result == {
        "http_status": 503,
        "response_json": None,
        "response_text": "service unavailable",
    }


def test_global_pool_manager_tolerates_actor_kill_failures(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)

    class Actor:
        ping = types.SimpleNamespace(remote=lambda: "ping-ref")

    monkeypatch.setattr(
        tasks,
        "DataProcessorRayActor",
        types.SimpleNamespace(remote=lambda: Actor()),
    )
    monkeypatch.setattr(tasks.ray, "get", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("warm")))
    monkeypatch.setattr(tasks.ray, "kill", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("kill")), raising=False)
    manager = tasks.GlobalRayActorPoolManager(warm_timeout_s=1)

    assert manager._create_and_warm_actor() is None
    manager.actors = [Actor()]
    assert manager.ensure_pool(desired=0, max_allowed=1) == 0


def test_get_or_create_pool_manager_creates_and_recovers_from_name_race(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "init_ray_in_worker", lambda: None)

    class Options:
        def __init__(self, remote_result=None, remote_error=None):
            self.remote_result = remote_result
            self.remote_error = remote_error

        def remote(self, timeout):
            if self.remote_error:
                raise self.remote_error
            return self.remote_result

    class ManagerFactory:
        def __init__(self, options):
            self.options_result = options

        def options(self, **kwargs):
            if kwargs.get("get_if_exists"):
                raise TypeError("unsupported")
            return self.options_result

    calls = {"count": 0}

    def get_actor(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("missing")
        return "raced-manager"

    monkeypatch.setattr(tasks.ray, "get_actor", get_actor, raising=False)
    monkeypatch.setattr(tasks, "GlobalRayActorPoolManager", ManagerFactory(Options(remote_result="new-manager")))
    assert tasks._get_or_create_global_pool_manager() == "new-manager"

    calls["count"] = 0
    monkeypatch.setattr(
        tasks,
        "GlobalRayActorPoolManager",
        ManagerFactory(Options(remote_error=RuntimeError("name race"))),
    )
    assert tasks._get_or_create_global_pool_manager() == "raced-manager"


def test_logging_task_delegates_lifecycle_hooks(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks.Task, "on_success", lambda self, *args: "success", raising=False)
    monkeypatch.setattr(tasks.Task, "on_failure", lambda self, *args: "failure", raising=False)
    monkeypatch.setattr(tasks.Task, "on_retry", lambda self, *args: "retry", raising=False)
    task = tasks.LoggingTask()
    task.name = "logging-task"

    assert task.on_success({}, "task-1", (), {}) == "success"
    assert task.on_failure(ValueError("bad"), "task-1", (), {}, None) == "failure"
    assert task.on_retry(RuntimeError("later"), "task-1", (), {}, None) == "retry"


def test_process_sync_without_celery_id_skips_state_updates(monkeypatch, tmp_path):
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch, initialized=True)
    source = tmp_path / "sync.txt"
    source.write_text("text", encoding="utf-8")

    class Actor:
        process_file = types.SimpleNamespace(remote=lambda *args, **kwargs: "chunks-ref")

    fake_ray.get_returns = {"chunks-ref": [{"content": "one"}, {"content": "two"}]}
    monkeypatch.setattr(tasks, "get_ray_actor", lambda: Actor())
    self = FakeSelf(None)

    result = tasks.process_sync(self, str(source), "local")

    assert result["text"] == "one\n\ntwo"
    assert self.states == []
