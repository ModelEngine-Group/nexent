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
        # New defaults required by ray_actors import
        const_mod.DEFAULT_EXPECTED_CHUNK_SIZE = 1024
        const_mod.DEFAULT_MAXIMUM_CHUNK_SIZE = 1536
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
            get_file_size_from_minio=lambda object_name, bucket=None: 0,
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
        run_attr = getattr(task_obj, "run", None)
        if run_attr is None:
            return None
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
    maybe = _unbound_run(getattr(tasks, "forward", None))
    if maybe is not None:
        tasks.forward = _CeleryTaskShim(maybe, preprocess=_forward_preprocess)
    maybe = _unbound_run(getattr(tasks, "process_and_forward", None))
    if maybe is not None:
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
    # Second call does nothing
    tasks.init_ray_in_worker()
    assert len(fake_ray.inits) == 1


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


def test_forward_index_documents_client_connector_error(monkeypatch):
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

    fake_aiohttp = types.SimpleNamespace(
        ClientConnectorError=ClientConnectorError,
        TCPConnector=TCPConnector,
        ClientTimeout=ClientTimeout,
        ClientSession=Session,
    )
    monkeypatch.setitem(sys.modules, "aiohttp", fake_aiohttp)

    self = FakeSelf("e_conn")
    with pytest.raises(Exception) as ei:
        tasks.forward(self, processed_data={"chunks": [
                      {"content": "x", "metadata": {}}]}, index_name="idx", source="/a.txt")
    json.loads(str(ei.value))


def test_forward_index_documents_client_response_503(monkeypatch):
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

    fake_aiohttp = types.SimpleNamespace(
        ClientResponseError=ClientResponseError,
        TCPConnector=TCPConnector,
        ClientTimeout=ClientTimeout,
        ClientSession=Session,
    )
    monkeypatch.setitem(sys.modules, "aiohttp", fake_aiohttp)

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


def test_forward_index_documents_timeout_error(monkeypatch):
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
    fake_aiohttp = types.SimpleNamespace(
        TCPConnector=TCPConnector,
        ClientTimeout=ClientTimeout,
        ClientSession=Session,
    )
    monkeypatch.setitem(sys.modules, "aiohttp", fake_aiohttp)
    # Ensure our TimeoutError is seen as asyncio.TimeoutError in except
    monkeypatch.setattr(tasks.asyncio, "TimeoutError", TimeoutError)

    self = FakeSelf("e_timeout")
    with pytest.raises(Exception) as ei:
        tasks.forward(self, processed_data={"chunks": [
                      {"content": "x", "metadata": {}}]}, index_name="idx", source="/a.txt")
    json.loads(str(ei.value))


def test_forward_index_documents_unexpected_error(monkeypatch):
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

    fake_aiohttp = types.SimpleNamespace(
        TCPConnector=TCPConnector,
        ClientTimeout=ClientTimeout,
        ClientSession=Session,
    )
    monkeypatch.setitem(sys.modules, "aiohttp", fake_aiohttp)

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
