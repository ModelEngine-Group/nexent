import io
import json
import sys
import types

import pytest


def make_fake_ray_module_identity_decorator():
    fake_ray = types.ModuleType("ray")

    def remote(**kwargs):
        def decorator(obj):
            return obj
        return decorator

    def is_initialized():
        return True

    fake_ray.remote = remote
    fake_ray.is_initialized = is_initialized
    return fake_ray


class FakeDataProcessCore:
    def __init__(self):
        self.calls = []

    def file_process(self, file_data, filename, chunking_strategy, **params):
        # Default behavior: return one chunk
        self.calls.append((filename, chunking_strategy, params))
        return [
            {"content": "hello world", "metadata": {"creation_date": "2024-01-01"}}
        ]


class FakeRedisClient:
    def __init__(self):
        self.store = {}
        self.expirations = {}

    @classmethod
    def from_url(cls, url, decode_responses=False):
        return cls()

    def set(self, key, value):
        self.store[key] = value

    def get(self, key):
        return self.store.get(key)

    def expire(self, key, seconds):
        self.expirations[key] = seconds


@pytest.fixture(autouse=True)
def stub_ray_before_import(monkeypatch):
    # Ensure that when module under test imports ray, it gets our stub
    sys.modules["ray"] = make_fake_ray_module_identity_decorator()
    yield
    sys.modules.pop("ray", None)


def import_module(monkeypatch):
    # Patch dependencies used by the module
    from pathlib import Path

    # Stub DataProcessCore and get_file_stream
    monkeypatch.setitem(sys.modules, "nexent.data_process", types.SimpleNamespace(DataProcessCore=FakeDataProcessCore))

    # Provide a full stub module for database.attachment_db to avoid importing real Minio client
    fake_attachment_db_mod = types.ModuleType("database.attachment_db")
    fake_attachment_db_mod.get_file_stream = lambda source: io.BytesIO(b"file-bytes")
    fake_attachment_db_mod.get_file_size = lambda path_or_url: 0
    monkeypatch.setitem(sys.modules, "database.attachment_db", fake_attachment_db_mod)
    # Ensure parent package 'database' exists and link submodule for proper resolution
    if "database" not in sys.modules:
        fake_database_pkg = types.ModuleType("database")
        fake_database_pkg.__path__ = []
        monkeypatch.setitem(sys.modules, "database", fake_database_pkg)
    setattr(sys.modules["database"], "attachment_db", fake_attachment_db_mod)

    # Stub celery (and celery.result.AsyncResult) to avoid dependency
    fake_celery = types.ModuleType("celery")
    fake_celery_result = types.ModuleType("celery.result")
    class _AsyncResult:
        def __init__(self, *a, **k):
            self.id = k.get("id", "fake")
        def ready(self):
            return True
        def successful(self):
            return True
        def failed(self):
            return False
        def state(self):
            return "SUCCESS"
        def get(self, *a, **k):
            return None
    fake_celery_result.AsyncResult = _AsyncResult
    # Link submodule to package
    fake_celery.result = fake_celery_result
    monkeypatch.setitem(sys.modules, "celery", fake_celery)
    monkeypatch.setitem(sys.modules, "celery.result", fake_celery_result)

    # Stub redis to avoid requiring the real dependency during package import
    if "redis" not in sys.modules:
        fake_redis = types.ModuleType("redis")
        # minimal Redis class to satisfy type hints in backend.data_process.utils
        class _Redis:
            pass
        fake_redis.Redis = _Redis
        monkeypatch.setitem(sys.modules, "redis", fake_redis)

    # Create lightweight package stubs to bypass backend.data_process __init__ execution
    project_root = Path(__file__).resolve().parents[3]
    backend_pkg = types.ModuleType("backend")
    backend_pkg.__path__ = [str(project_root / "backend")]
    monkeypatch.setitem(sys.modules, "backend", backend_pkg)

    backend_dp_pkg = types.ModuleType("backend.data_process")
    backend_dp_pkg.__path__ = [str(project_root / "backend" / "data_process")]
    monkeypatch.setitem(sys.modules, "backend.data_process", backend_dp_pkg)

    # Stub modules that might still be imported elsewhere
    fake_dp_app = types.ModuleType("backend.data_process.app")
    fake_dp_app.app = object()
    monkeypatch.setitem(sys.modules, "backend.data_process.app", fake_dp_app)
    fake_dp_tasks = types.ModuleType("backend.data_process.tasks")
    fake_dp_tasks.process = lambda *a, **k: None
    fake_dp_tasks.forward = lambda *a, **k: None
    fake_dp_tasks.process_and_forward = lambda *a, **k: None
    fake_dp_tasks.process_sync = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "backend.data_process.tasks", fake_dp_tasks)

    # Stub consts.const needed by ray_actors imports
    fake_consts_pkg = types.ModuleType("consts")
    fake_consts_const = types.ModuleType("consts.const")
    fake_consts_const.RAY_ACTOR_NUM_CPUS = 1
    fake_consts_const.REDIS_BACKEND_URL = ""
    # New defaults required by ray_actors import
    fake_consts_const.DEFAULT_EXPECTED_CHUNK_SIZE = 1024
    fake_consts_const.DEFAULT_MAXIMUM_CHUNK_SIZE = 1536
    monkeypatch.setitem(sys.modules, "consts", fake_consts_pkg)
    monkeypatch.setitem(sys.modules, "consts.const", fake_consts_const)

    # Ensure model_management_db is stubbed to avoid importing real DB layer
    if "database.model_management_db" not in sys.modules:
        monkeypatch.setitem(
            sys.modules,
            "database.model_management_db",
            types.SimpleNamespace(
                get_model_by_model_id=lambda model_id, tenant_id=None: None
            ),
        )
    # Link model_management_db to parent 'database' package
    if "database" not in sys.modules:
        fake_database_pkg = types.ModuleType("database")
        fake_database_pkg.__path__ = []
        monkeypatch.setitem(sys.modules, "database", fake_database_pkg)
    setattr(
        sys.modules["database"],
        "model_management_db",
        sys.modules["database.model_management_db"],
    )

    # Stub database.model_management_db so import succeeds
    if "database.model_management_db" not in sys.modules:
        monkeypatch.setitem(
            sys.modules,
            "database.model_management_db",
            types.SimpleNamespace(
                get_model_by_model_id=lambda model_id, tenant_id=None: None),
        )

    # Import module under test
    import backend.data_process.ray_actors as ray_actors
    return ray_actors


def test_process_file_happy_path(monkeypatch):
    ray_actors = import_module(monkeypatch)
    actor = ray_actors.DataProcessorRayActor()

    chunks = actor.process_file(
        source="/tmp/a.txt",
        chunking_strategy="basic",
        destination="local",
        task_id="tid-1",
        extra_option=True,
    )

    assert isinstance(chunks, list)
    assert len(chunks) == 1
    assert chunks[0]["content"] == "hello world"


def test_process_file_applies_chunk_sizes_from_model(monkeypatch):
    ray_actors = import_module(monkeypatch)

    # Recorder core to capture params
    class RecorderCore:
        captured_params = None

        def __init__(self):
            pass

        def file_process(self, file_data, filename, chunking_strategy, **params):
            RecorderCore.captured_params = params
            return [{"content": "x", "metadata": {}}]

    # Use recorder core and a model record with explicit sizes
    monkeypatch.setattr(ray_actors, "DataProcessCore", RecorderCore)
    monkeypatch.setattr(
        ray_actors,
        "get_model_by_model_id",
        lambda model_id, tenant_id=None: {
            "expected_chunk_size": 2000,
            "maximum_chunk_size": 3000,
            "display_name": "emb",
            "model_type": "embedding",
        },
    )

    actor = ray_actors.DataProcessorRayActor()
    actor.process_file(
        source="/tmp/a.txt",
        chunking_strategy="basic",
        destination="local",
        model_id=9,
        tenant_id="t1",
    )

    assert RecorderCore.captured_params is not None
    assert RecorderCore.captured_params.get("new_after_n_chars") == 2000
    assert RecorderCore.captured_params.get("max_characters") == 3000


def test_process_file_no_model_omits_chunk_params(monkeypatch):
    ray_actors = import_module(monkeypatch)

    class RecorderCore:
        captured_params = None

        def __init__(self):
            pass

        def file_process(self, file_data, filename, chunking_strategy, **params):
            RecorderCore.captured_params = params
            return [{"content": "y", "metadata": {}}]

    # No model found
    monkeypatch.setattr(ray_actors, "DataProcessCore", RecorderCore)
    monkeypatch.setattr(
        ray_actors,
        "get_model_by_model_id",
        lambda model_id, tenant_id=None: None,
    )

    actor = ray_actors.DataProcessorRayActor()
    actor.process_file(
        source="/tmp/b.txt",
        chunking_strategy="basic",
        destination="local",
        model_id=10,
        tenant_id="t2",
    )

    assert RecorderCore.captured_params is not None
    assert "new_after_n_chars" not in RecorderCore.captured_params
    assert "max_characters" not in RecorderCore.captured_params


def test_process_file_model_lookup_exception_uses_defaults(monkeypatch):
    ray_actors = import_module(monkeypatch)

    class RecorderCore:
        captured_params = None

        def __init__(self):
            pass

        def file_process(self, file_data, filename, chunking_strategy, **params):
            RecorderCore.captured_params = params
            return [{"content": "z", "metadata": {}}]

    # Make model lookup raise to hit exception handler (lines 84-85)
    monkeypatch.setattr(ray_actors, "DataProcessCore", RecorderCore)
    monkeypatch.setattr(
        ray_actors,
        "get_model_by_model_id",
        lambda model_id, tenant_id=None: (
            _ for _ in ()).throw(RuntimeError("db down")),
    )

    actor = ray_actors.DataProcessorRayActor()
    actor.process_file(
        source="/tmp/c.txt",
        chunking_strategy="basic",
        destination="local",
        model_id=11,
        tenant_id="t3",
    )

    assert RecorderCore.captured_params is not None
    assert "new_after_n_chars" not in RecorderCore.captured_params
    assert "max_characters" not in RecorderCore.captured_params


def test_process_file_get_stream_none_raises(monkeypatch):
    # Override get_file_stream to return None
    fake_attachment_db_mod = types.ModuleType("database.attachment_db")
    fake_attachment_db_mod.get_file_stream = lambda source: None
    fake_attachme = lambda path_or_url: 0
    monkeypatch.setitem(sys.modules, "database.attachment_db", fake_attachment_db_mod)
    # Ensure parent 'database' exists and link attachment_db
    if "database" not in sys.modules:
        fake_database_pkg = types.ModuleType("database")
        fake_database_pkg.__path__ = []
        monkeypatch.setitem(sys.modules, "database", fake_database_pkg)
    setattr(sys.modules["database"], "attachment_db", fake_attachment_db_mod)

    # Ensure DataProcessCore is stubbed during reload as well
    monkeypatch.setitem(
        sys.modules,
        "nexent.data_process",
        types.SimpleNamespace(DataProcessCore=FakeDataProcessCore),
    )

    # Also stub celery and backend.data_process.{app,tasks} to avoid importing real modules
    fake_celery = types.ModuleType("celery")
    fake_celery_result = types.ModuleType("celery.result")
    class _AsyncResult:
        def __init__(self, *a, **k):
            self.id = k.get("id", "fake")
        def ready(self):
            return True
        def successful(self):
            return True
        def failed(self):
            return False
        def state(self):
            return "SUCCESS"
        def get(self, *a, **k):
            return None
    fake_celery_result.AsyncResult = _AsyncResult
    fake_celery.result = fake_celery_result
    monkeypatch.setitem(sys.modules, "celery", fake_celery)
    monkeypatch.setitem(sys.modules, "celery.result", fake_celery_result)
    if "redis" not in sys.modules:
        fake_redis = types.ModuleType("redis")
        class _Redis:
            pass
        fake_redis.Redis = _Redis
        monkeypatch.setitem(sys.modules, "redis", fake_redis)
    # Create lightweight package stubs to bypass backend.data_process __init__ execution
    from pathlib import Path
    project_root = Path(__file__).resolve().parents[3]
    backend_pkg = types.ModuleType("backend")
    backend_pkg.__path__ = [str(project_root / "backend")]
    monkeypatch.setitem(sys.modules, "backend", backend_pkg)
    backend_dp_pkg = types.ModuleType("backend.data_process")
    backend_dp_pkg.__path__ = [str(project_root / "backend" / "data_process")]
    monkeypatch.setitem(sys.modules, "backend.data_process", backend_dp_pkg)
    fake_dp_app = types.ModuleType("backend.data_process.app")
    fake_dp_app.app = object()
    monkeypatch.setitem(sys.modules, "backend.data_process.app", fake_dp_app)
    fake_dp_tasks = types.ModuleType("backend.data_process.tasks")
    fake_dp_tasks.process = lambda *a, **k: None
    fake_dp_tasks.forward = lambda *a, **k: None
    fake_dp_tasks.process_and_forward = lambda *a, **k: None
    fake_dp_tasks.process_sync = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "backend.data_process.tasks", fake_dp_tasks)
    # Stub consts.const again for reload path
    fake_consts_pkg = types.ModuleType("consts")
    fake_consts_const = types.ModuleType("consts.const")
    fake_consts_const.RAY_ACTOR_NUM_CPUS = 1
    fake_consts_const.REDIS_BACKEND_URL = ""
    # Provide defaults required by backend.data_process.ray_actors import
    fake_consts_const.DEFAULT_EXPECTED_CHUNK_SIZE = 1024
    fake_consts_const.DEFAULT_MAXIMUM_CHUNK_SIZE = 1536
    monkeypatch.setitem(sys.modules, "consts", fake_consts_pkg)
    monkeypatch.setitem(sys.modules, "consts.const", fake_consts_const)

    # Stub database.model_management_db and link to parent to avoid real DB import
    if "database.model_management_db" not in sys.modules:
        monkeypatch.setitem(
            sys.modules,
            "database.model_management_db",
            types.SimpleNamespace(
                get_model_by_model_id=lambda model_id, tenant_id=None: None
            ),
        )
    if "database" not in sys.modules:
        fake_database_pkg = types.ModuleType("database")
        fake_database_pkg.__path__ = []
        monkeypatch.setitem(sys.modules, "database", fake_database_pkg)
    setattr(
        sys.modules["database"],
        "model_management_db",
        sys.modules["database.model_management_db"],
    )

    # Re-import to take new stub
    from importlib import reload
    import backend.data_process.ray_actors as ray_actors
    reload(ray_actors)

    actor = ray_actors.DataProcessorRayActor()
    with pytest.raises(FileNotFoundError):
        actor.process_file("url://missing", "basic", destination="minio")


def test_process_file_core_returns_none_list_variants(monkeypatch):
    class CoreNone(FakeDataProcessCore):
        def file_process(self, *a, **k):
            return None

    class CoreNotList(FakeDataProcessCore):
        def file_process(self, *a, **k):
            return {"not": "list"}

    class CoreEmpty(FakeDataProcessCore):
        def file_process(self, *a, **k):
            return []

    # Patch DataProcessCore to different variants and assert [] result
    for core_cls in (CoreNone, CoreNotList, CoreEmpty):
        monkeypatch.setitem(
            sys.modules,
            "nexent.data_process",
            types.SimpleNamespace(DataProcessCore=core_cls),
        )
        # Stub attachment_db to avoid importing real Minio client
        fake_attachment_db_mod = types.ModuleType("database.attachment_db")
        fake_attachment_db_mod.get_file_stream = lambda source: io.BytesIO(b"file-bytes")
        fake_attachme = lambda path_or_url: 0
        monkeypatch.setitem(sys.modules, "database.attachment_db", fake_attachment_db_mod)
        # Also stub celery.result.AsyncResult and redis module
        fake_celery = types.ModuleType("celery")
        fake_celery_result = types.ModuleType("celery.result")
        class _AsyncResult:
            def __init__(self, *a, **k):
                self.id = k.get("id", "fake")
            def ready(self):
                return True
            def successful(self):
                return True
            def failed(self):
                return False
            def state(self):
                return "SUCCESS"
            def get(self, *a, **k):
                return None
        fake_celery_result.AsyncResult = _AsyncResult
        fake_celery.result = fake_celery_result
        monkeypatch.setitem(sys.modules, "celery", fake_celery)
        monkeypatch.setitem(sys.modules, "celery.result", fake_celery_result)
        if "redis" not in sys.modules:
            fake_redis = types.ModuleType("redis")
            class _Redis:
                pass
            fake_redis.Redis = _Redis
            monkeypatch.setitem(sys.modules, "redis", fake_redis)
        # Stub backend package and submodules to avoid __init__ side effects
        from pathlib import Path
        project_root = Path(__file__).resolve().parents[3]
        backend_pkg = types.ModuleType("backend")
        backend_pkg.__path__ = [str(project_root / "backend")]
        monkeypatch.setitem(sys.modules, "backend", backend_pkg)
        backend_dp_pkg = types.ModuleType("backend.data_process")
        backend_dp_pkg.__path__ = [str(project_root / "backend" / "data_process")]
        monkeypatch.setitem(sys.modules, "backend.data_process", backend_dp_pkg)
        fake_dp_app = types.ModuleType("backend.data_process.app")
        fake_dp_app.app = object()
        monkeypatch.setitem(sys.modules, "backend.data_process.app", fake_dp_app)
        fake_dp_tasks = types.ModuleType("backend.data_process.tasks")
        fake_dp_tasks.process = lambda *a, **k: None
        fake_dp_tasks.forward = lambda *a, **k: None
        fake_dp_tasks.process_and_forward = lambda *a, **k: None
        fake_dp_tasks.process_sync = lambda *a, **k: None
        monkeypatch.setitem(sys.modules, "backend.data_process.tasks", fake_dp_tasks)
        # Stub consts.const for ray_actors imports
        fake_consts_pkg = types.ModuleType("consts")
        fake_consts_const = types.ModuleType("consts.const")
        fake_consts_const.RAY_ACTOR_NUM_CPUS = 1
        fake_consts_const.REDIS_BACKEND_URL = ""
        # Provide defaults required by backend.data_process.ray_actors import
        fake_consts_const.DEFAULT_EXPECTED_CHUNK_SIZE = 1024
        fake_consts_const.DEFAULT_MAXIMUM_CHUNK_SIZE = 1536
        monkeypatch.setitem(sys.modules, "consts", fake_consts_pkg)
        monkeypatch.setitem(sys.modules, "consts.const", fake_consts_const)

        # Ensure model_management_db is stubbed to avoid importing real DB layer
        if "database.model_management_db" not in sys.modules:
            monkeypatch.setitem(
                sys.modules,
                "database.model_management_db",
                types.SimpleNamespace(
                    get_model_by_model_id=lambda model_id, tenant_id=None: None
                ),
            )
        from importlib import reload
        import backend.data_process.ray_actors as ray_actors
        reload(ray_actors)
        actor = ray_actors.DataProcessorRayActor()
        chunks = actor.process_file("/tmp/a.txt", "basic", destination="local")
        assert chunks == []


def test_store_chunks_in_redis_success(monkeypatch):
    # Import with default stubs
    ray_actors = import_module(monkeypatch)

    # Ensure REDIS_BACKEND_URL is set and stub redis
    monkeypatch.setattr(ray_actors, "REDIS_BACKEND_URL", "redis://test")
    fake_redis_module = types.SimpleNamespace(Redis=types.SimpleNamespace(from_url=FakeRedisClient.from_url))
    monkeypatch.setitem(sys.modules, "redis", fake_redis_module)

    actor = ray_actors.DataProcessorRayActor()
    ok = actor.store_chunks_in_redis("key1", [{"content": "a"}])
    assert ok is True


def test_store_chunks_in_redis_handles_none_and_serialization_error(monkeypatch):
    ray_actors = import_module(monkeypatch)
    monkeypatch.setattr(ray_actors, "REDIS_BACKEND_URL", "redis://test")
    fake_client = FakeRedisClient()
    fake_redis_module = types.SimpleNamespace(Redis=types.SimpleNamespace(from_url=lambda *a, **k: fake_client))
    monkeypatch.setitem(sys.modules, "redis", fake_redis_module)

    actor = ray_actors.DataProcessorRayActor()

    # None chunks -> stored []
    ok_none = actor.store_chunks_in_redis("k-none", None)
    assert ok_none is True
    assert json.loads(fake_client.get("k-none")) == []

    # Non-serializable -> fallback []
    ok_bad = actor.store_chunks_in_redis("k-bad", [{"s": {1, 2, 3}}])
    assert ok_bad is True
    assert json.loads(fake_client.get("k-bad")) == []


def test_store_chunks_in_redis_no_url_returns_false(monkeypatch):
    ray_actors = import_module(monkeypatch)
    monkeypatch.setattr(ray_actors, "REDIS_BACKEND_URL", "")
    actor = ray_actors.DataProcessorRayActor()
    assert actor.store_chunks_in_redis("k", [{"content": "x"}]) is False

