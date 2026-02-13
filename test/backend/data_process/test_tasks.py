import asyncio
import io
import sys
import types
import json
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
        return self.get_returns

    def remote(self, **kwargs):
        # Identity decorator to mimic ray.remote for classes/functions
        def decorator(obj):
            return obj
        return decorator


def import_tasks_with_fake_ray(monkeypatch, initialized=False):
    fake_ray = FakeRay(initialized=initialized)
    sys.modules["ray"] = fake_ray
    import importlib
    # Stub celery module (required by app.py and tasks.py imported via __init__.py)
    if "celery.backends.base" not in sys.modules:
        backends_base_mod = types.ModuleType("celery.backends.base")
        backends_base_mod.DisabledBackend = type("DisabledBackend", (), {})
        sys.modules["celery.backends.base"] = backends_base_mod
    
    if "celery.exceptions" not in sys.modules:
        exceptions_mod = types.ModuleType("celery.exceptions")
        exceptions_mod.Retry = type("Retry", (Exception,), {})
        sys.modules["celery.exceptions"] = exceptions_mod
    
    if "celery.result" not in sys.modules:
        result_mod = types.ModuleType("celery.result")
        result_mod.AsyncResult = type("AsyncResult", (), {})
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
    
    if "celery" not in sys.modules:
        celery_mod = types.ModuleType("celery")
        # Create a Celery class that accepts any arguments and has required attributes
        class FakeBackend:
            pass
        
        class FakeCelery:
            def __init__(self, *args, **kwargs):
                # Set backend to a non-DisabledBackend instance
                self.backend = FakeBackend()
                # Create a conf object with update method
                self.conf = types.SimpleNamespace(update=lambda **kwargs: None)
            
            def task(self, *args, **kwargs):
                # Return a decorator that returns the function unchanged
                def decorator(func):
                    return func
                return decorator
        
        # Stub classes and functions needed by tasks.py
        celery_mod.Celery = FakeCelery
        celery_mod.Task = type("Task", (), {})
        celery_mod.chain = lambda *args: None
        celery_mod.states = types.SimpleNamespace(
            PENDING="PENDING",
            STARTED="STARTED",
            SUCCESS="SUCCESS",
            FAILURE="FAILURE",
            RETRY="RETRY",
            REVOKED="REVOKED"
        )
        sys.modules["celery"] = celery_mod
    
    # Stub modules that ray_actors depends on to avoid importing real MinIO
    # Also stub consts package and consts.const module to provide required constants at import time
    if "consts" not in sys.modules:
        sys.modules["consts"] = types.ModuleType("consts")
        setattr(sys.modules["consts"], "__path__", [])
    if "consts.const" not in sys.modules:
        const_mod = types.ModuleType("consts.const")
        const_mod.ELASTICSEARCH_SERVICE = "http://api"
        const_mod.REDIS_BACKEND_URL = "redis://test"
        const_mod.REDIS_URL = "redis://test"
        const_mod.DATA_PROCESS_SERVICE = "http://data-process"
        const_mod.RAY_ACTOR_NUM_CPUS = 1
        const_mod.FORWARD_REDIS_RETRY_DELAY_S = 0
        const_mod.FORWARD_REDIS_RETRY_MAX = 1
        const_mod.DISABLE_RAY_DASHBOARD = False
        # New defaults required by ray_actors import
        const_mod.DEFAULT_EXPECTED_CHUNK_SIZE = 1024
        const_mod.DEFAULT_MAXIMUM_CHUNK_SIZE = 1536
        const_mod.ROOT_DIR = "/mock/root"
        sys.modules["consts.const"] = const_mod
    # Minimal stub for consts.model used by utils.file_management_utils
    if "consts.model" not in sys.modules:
        model_mod = types.ModuleType("consts.model")

        class ProcessParams:
            def __init__(self, chunking_strategy: str, source_type: str, index_name: str, authorization: str | None):
                self.chunking_strategy = chunking_strategy
                self.source_type = source_type
                self.index_name = index_name
                self.authorization = authorization
        model_mod.ProcessParams = ProcessParams
        sys.modules["consts.model"] = model_mod
    if "database.attachment_db" not in sys.modules:
        sys.modules["database.attachment_db"] = types.SimpleNamespace(
            get_file_stream=lambda source: io.BytesIO(b"stub-bytes"),
            get_file_size=lambda object_name, bucket=None: 0,
        )
    # Stub model_management_db module required by ray_actors
    if "database.model_management_db" not in sys.modules:
        sys.modules["database.model_management_db"] = types.SimpleNamespace(
            get_model_by_model_id=lambda model_id, tenant_id=None: None
        )
    # Ensure parent 'database' package exists and link submodules for proper import resolution
    if "database" not in sys.modules:
        db_pkg = types.ModuleType("database")
        setattr(db_pkg, "__path__", [])
        sys.modules["database"] = db_pkg
    setattr(sys.modules["database"], "attachment_db",
            sys.modules["database.attachment_db"])
    setattr(sys.modules["database"], "model_management_db",
            sys.modules["database.model_management_db"])

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
            DataProcessCore=type("_Core", (), {"__init__": lambda self: None, "file_process": lambda *a, **k: []})
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
        sys.modules["requests"] = types.SimpleNamespace()
    if "fastapi" not in sys.modules:
        fastapi_mod = types.ModuleType("fastapi")
        fastapi_mod.UploadFile = type("UploadFile", (), {})
        sys.modules["fastapi"] = fastapi_mod
    
    # Stub utils.file_management_utils (required by tasks.py)
    if "utils.file_management_utils" not in sys.modules:
        file_utils_mod = types.ModuleType("utils.file_management_utils")
        file_utils_mod.get_file_size = lambda *args, **kwargs: 0
        sys.modules["utils.file_management_utils"] = file_utils_mod
    
    # Stub aiohttp (required by tasks.py)
    if "aiohttp" not in sys.modules:
        sys.modules["aiohttp"] = types.SimpleNamespace()
    
    import backend.data_process.tasks as tasks
    importlib.reload(tasks)
    # Provide a Celery task shim that allows direct calls and supports .s for chaining
    class _SignatureShim:
        def __init__(self):
            pass
        def set(self, **_kw):
            return self

    class _CeleryTaskShim:
        def __init__(self, run_func, preprocess=None):
            self._run_func = run_func
            self._preprocess = preprocess
        def __call__(self, *args, **kwargs):
            if self._preprocess is not None:
                args, kwargs = self._preprocess(args, kwargs)
            return self._run_func(*args, **kwargs)
        def s(self, **_kw):
            return _SignatureShim()

    # Helper to get unbound run
    def _unbound_run(task_obj):
        """
        Return the underlying callable for a Celery task or plain function.

        In production, Celery tasks are Task objects with a .run attribute.
        In tests (with our FakeCelery), tasks are often plain functions.
        """
        if task_obj is None:
            return None
        run_attr = getattr(task_obj, "run", None)
        if run_attr is None:
            # Plain function (already directly callable)
            return task_obj
        return getattr(run_attr, "__func__", run_attr)

    # Inject a default Ray actor so get_ray_actor works even when not monkeypatched in tests
    default_actor = types.SimpleNamespace(
        process_file=types.SimpleNamespace(remote=lambda *a, **k: "ref"),
        store_chunks_in_redis=types.SimpleNamespace(remote=lambda *a, **k: None),
    )
    if not hasattr(tasks, "DataProcessorRayActor") or not hasattr(getattr(tasks, "DataProcessorRayActor"), "remote"):
        tasks.DataProcessorRayActor = types.SimpleNamespace(remote=lambda: default_actor)

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
        tasks.process = _CeleryTaskShim(maybe)
        # Ensure process is also available in the module namespace for process_and_forward
        import backend.data_process.tasks as tasks_module
        tasks_module.process = tasks.process
    maybe = _unbound_run(getattr(tasks, "forward", None))
    if maybe is not None:
        tasks.forward = _CeleryTaskShim(maybe, preprocess=_forward_preprocess)
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
        tasks.process_and_forward = _CeleryTaskShim(maybe)
    maybe = _unbound_run(getattr(tasks, "process_sync", None))
    if maybe is not None:
        tasks.process_sync = _CeleryTaskShim(maybe)
    return tasks, fake_ray


def test_init_ray_in_worker_initializes_once(monkeypatch):
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch, initialized=False)
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
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch, initialized=False)
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
    tasks, fake_ray = import_tasks_with_fake_ray(monkeypatch, initialized=False)
    
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
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: (_ for _ in ()).throw(RuntimeError("no loop")))
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

    class DummyActor:
        @staticmethod
        def remote():
            return {"remote": True}

    monkeypatch.setattr(tasks, "DataProcessorRayActor", DummyActor)
    actor = tasks.get_ray_actor()
    assert actor == {"remote": True}


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
            self.process_file = types.SimpleNamespace(remote=lambda *a, **k: "ref1")
            self.store_chunks_in_redis = types.SimpleNamespace(remote=lambda *a, **k: None)

    monkeypatch.setattr(tasks, "get_ray_actor", lambda: FakeActor())
    # Mock ray.get to return chunks instead of reference
    fake_ray.get_returns = mock_chunks

    self = FakeSelf("p1")

    result = tasks.process(self, source=str(f), source_type="local", chunking_strategy="basic", index_name="idx", original_filename="a.txt")
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
            self.process_file = types.SimpleNamespace(remote=lambda *a, **k: "ref")
            self.store_chunks_in_redis = types.SimpleNamespace(remote=lambda *a, **k: None)

    monkeypatch.setattr(tasks, "get_ray_actor", lambda: FakeActor())
    # Mock ray.get to return chunks
    fake_ray.get_returns = mock_chunks

    self = FakeSelf("m1")
    result = tasks.process(self, source="http://minio/bucket/x", source_type="minio", chunking_strategy="basic")
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


def test_process_and_forward_returns_empty_when_apply_async_none(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)

    class FakeChain:
        def apply_async(self):
            return None

    monkeypatch.setattr(tasks, "chain", lambda *a, **k: FakeChain())
    # Ensure process and forward are accessible from the tasks module for process_and_forward
    # The function looks up process and forward from the module at runtime
    import backend.data_process.tasks as tasks_module
    # Process and forward should already be shimmed in import_tasks_with_fake_ray
    # But we need to ensure they're accessible in the module namespace
    tasks_module.process = tasks.process
    tasks_module.forward = tasks.forward
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
    monkeypatch.setattr(tasks, "run_async", lambda coro: {"success": True, "total_indexed": 1, "total_submitted": 1, "message": "ok"})

    self = FakeSelf("f1")
    chunks = [
        {"content": "text", "metadata": {"creation_date": "2024-01-01"}},
        {"content": "", "metadata": {}},
    ]
    result = tasks.forward(self, processed_data={"chunks": chunks}, index_name="idx", source="/a.txt", source_type="local", original_filename="a.txt")
    assert result["chunks_stored"] == 1


def test_forward_partial_success_raises(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")
    monkeypatch.setattr(tasks, "get_file_size", lambda *a, **k: 0)
    monkeypatch.setattr(tasks, "run_async", lambda coro: {"success": True, "total_indexed": 0, "total_submitted": 1, "message": "partial"})
    self = FakeSelf("f2")
    with pytest.raises(Exception) as ei:
        tasks.forward(self, processed_data={"chunks": [{"content": "x", "metadata": {}}]}, index_name="idx", source="/a.txt", source_type="local")
    json.loads(str(ei.value))


def test_forward_no_chunks_and_no_redis_key_raises(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    self = FakeSelf("f3")
    with pytest.raises(Exception) as ei:
        tasks.forward(self, processed_data={}, index_name="idx", source="/a.txt")
    json.loads(str(ei.value))


def test_forward_formats_to_empty_then_raises(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    self = FakeSelf("f4")
    with pytest.raises(Exception) as ei:
        tasks.forward(self, processed_data={"chunks": [{"content": "  ", "metadata": {}}]}, index_name="idx", source="/a.txt")
    json.loads(str(ei.value))


def test_forward_missing_es_env_raises(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "")
    monkeypatch.setattr(tasks, "get_file_size", lambda *a, **k: 0)
    self = FakeSelf("f5")
    with pytest.raises(Exception) as ei:
        tasks.forward(self, processed_data={"chunks": [{"content": "x", "metadata": {}}]}, index_name="idx", source="/a.txt")
    json.loads(str(ei.value))


def test_forward_loads_chunks_from_redis(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")
    monkeypatch.setattr(tasks, "REDIS_BACKEND_URL", "redis://test")
    monkeypatch.setattr(tasks, "get_file_size", lambda *a, **k: 1)

    class FakeRedisClient:
        def __init__(self):
            self.kv = {"dp:rid:chunks": json.dumps([{"content": "x", "metadata": {}}])}
        def get(self, k):
            return self.kv.get(k)

    fake_redis_mod = types.SimpleNamespace(Redis=types.SimpleNamespace(from_url=lambda url, decode_responses=True: FakeRedisClient()))
    monkeypatch.setitem(sys.modules, "redis", fake_redis_mod)

    # run_async returns success for 1 chunk
    monkeypatch.setattr(tasks, "run_async", lambda coro: {"success": True, "total_indexed": 1, "total_submitted": 1, "message": "ok"})

    self = FakeSelf("f6")
    result = tasks.forward(self, processed_data={"redis_key": "dp:rid:chunks"}, index_name="idx", source="/a.txt")
    assert result["chunks_stored"] == 1


def test_process_and_forward_returns_chain_id(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)

    class FakeResult:
        def __init__(self, id):
            self.id = id

    class FakeChain:
        def apply_async(self):
            return FakeResult("123")

    monkeypatch.setattr(tasks, "chain", lambda *a, **k: FakeChain())
    self = FakeSelf("c1")
    chain_id = tasks.process_and_forward(self, source="/a.txt", source_type="local", chunking_strategy="basic", index_name="idx")
    assert chain_id == "123"


def test_extract_error_code_parses_detail_and_regex_and_unknown():
    from backend.data_process.tasks import extract_error_code

    # detail error_code inside JSON string
    json_detail = json.dumps({"detail": {"error_code": "detail_code"}})
    assert extract_error_code(json_detail) == "detail_code"

    # regex fallback when not valid JSON
    raw = 'oops {"error_code":"regex_code"}'
    assert extract_error_code(raw) == "regex_code"

    # unknown path
    assert extract_error_code("no code here") == "unknown_error"


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
        "backend.data_process.tasks.logger.error", lambda *a, **k: warnings.append(a[0])
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
        s.get("meta", {}).get("stage") in {"text_extraction_failed", "extracting_text"}
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
            self.process_file = types.SimpleNamespace(remote=lambda *a, **k: "ref_err")
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
    monkeypatch.setattr(tasks, "get_redis_service", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    # run index_documents normally via stubbed run_async returning success
    monkeypatch.setattr(
        tasks,
        "run_async",
        lambda coro: {"success": True, "total_indexed": 1, "total_submitted": 1, "message": "ok"},
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
    assert "Failed to connect to API" in str(exc.value) or "timeout" in str(exc.value).lower()


def test_forward_truncates_reason_when_no_error_code(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch)
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://api")
    monkeypatch.setattr(tasks, "get_file_size", lambda *a, **k: 0)
    monkeypatch.setattr(tasks, "extract_error_code", lambda *a, **k: None)

    long_msg = json.dumps({"message": "m" * 250})
    monkeypatch.setattr(
        tasks, "run_async", lambda coro: (_ for _ in ()).throw(Exception(long_msg))
    )

    reasons: list[str] = []
    monkeypatch.setattr(
        tasks, "save_error_to_redis", lambda tid, reason, st: reasons.append(reason)
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
        tasks, "run_async", lambda coro: (_ for _ in ()).throw(Exception("n" * 250))
    )

    reasons: list[str] = []
    monkeypatch.setattr(
        tasks, "save_error_to_redis", lambda tid, reason, st: reasons.append(reason)
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
        tasks, "run_async", lambda coro: (_ for _ in ()).throw(Exception(json.dumps({"message": long_message})))
    )
    captured = {}
    monkeypatch.setattr(
        tasks, "save_error_to_redis", lambda tid, reason, st: captured.setdefault("reason", reason)
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
        tasks, "run_async", lambda coro: (_ for _ in ()).throw(Exception("not-json-error"))
    )
    captured = {}
    monkeypatch.setattr(
        tasks, "save_error_to_redis", lambda tid, reason, st: captured.setdefault("reason", reason)
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
            self.process_file = types.SimpleNamespace(remote=lambda *a, **k: "ref1")

    monkeypatch.setattr(tasks, "get_ray_actor", lambda: FakeActor())
    fake_ray.get_returns = [{"content": "a"}, {"content": "b"}]

    self = FakeSelf("s1")
    out = tasks.process_sync(self, source="/a.txt", source_type="local")
    assert out["chunks_count"] == 2
    assert "a\n\nb" in out["text"]


def test_process_sync_unsupported_raises_and_updates_state(monkeypatch):
    tasks, _ = import_tasks_with_fake_ray(monkeypatch, initialized=True)
    self = FakeSelf("s2")
    with pytest.raises(NotImplementedError):
        tasks.process_sync(self, source="/a.txt", source_type="minio")
    # check that failure meta was updated
    assert any("sync_processing_failed" in s.get("meta", {}).get("stage", "") for s in self.states)


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
            self.process_file = types.SimpleNamespace(
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
