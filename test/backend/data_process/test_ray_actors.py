import io
import json
import sys
import types

import pytest


class _NoopKnowledgeSpan:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


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


def make_temp_file(tmp_path, name: str, content: bytes = b"file-bytes") -> str:
    path = tmp_path / name
    path.write_bytes(content)
    return str(path)


def stub_consts(monkeypatch):
    fake_consts_pkg = types.ModuleType("consts")
    fake_consts_const = types.ModuleType("consts.const")
    fake_consts_const.RAY_ACTOR_NUM_CPUS = 1
    fake_consts_const.REDIS_BACKEND_URL = ""
    # New defaults required by ray_actors import
    fake_consts_const.DEFAULT_EXPECTED_CHUNK_SIZE = 1024
    fake_consts_const.DEFAULT_MAXIMUM_CHUNK_SIZE = 1536
    fake_consts_const.TABLE_TRANSFORMER_MODEL_PATH = "/models/table"
    fake_consts_const.UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH = "/models/unstructured.json"
    monkeypatch.setitem(sys.modules, "consts", fake_consts_pkg)
    monkeypatch.setitem(sys.modules, "consts.const", fake_consts_const)
    return fake_consts_const


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
    telemetry_module = types.SimpleNamespace(
        knowledge_span=lambda *args, **kwargs: _NoopKnowledgeSpan()
    )
    monkeypatch.setitem(sys.modules, "utils.knowledge_telemetry", telemetry_module)

    # Provide a full stub module for database.attachment_db to avoid importing real Minio client
    fake_attachment_db_mod = types.ModuleType("database.attachment_db")
    fake_attachment_db_mod.get_file_stream = lambda source: io.BytesIO(b"file-bytes")
    fake_attachment_db_mod.get_file_size_from_minio = lambda path_or_url: 0
    fake_attachment_db_mod.upload_fileobj = lambda file_obj, file_name, prefix=None, bucket=None: {
        "success": True,
        "object_name": f"{prefix}/{file_name}" if prefix else file_name,
    }
    fake_attachment_db_mod.build_s3_url = lambda object_name: f"s3://bucket/{object_name}"
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
    stub_consts(monkeypatch)

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


def test_process_file_happy_path(monkeypatch, tmp_path):
    ray_actors = import_module(monkeypatch)
    actor = ray_actors.DataProcessorRayActor()

    source_path = make_temp_file(tmp_path, "a.txt")
    chunks = actor.process_file(
        source=source_path,
        chunking_strategy="basic",
        destination="local",
        task_id="tid-1",
        extra_option=True,
    )

    assert isinstance(chunks, list)
    assert len(chunks) == 1
    assert chunks[0]["content"] == "hello world"


def test_process_file_applies_chunk_sizes_from_model(monkeypatch, tmp_path):
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
    source_path = make_temp_file(tmp_path, "a.txt")
    actor.process_file(
        source=source_path,
        chunking_strategy="basic",
        destination="local",
        model_id=9,
        tenant_id="t1",
    )

    assert RecorderCore.captured_params is not None
    assert RecorderCore.captured_params.get("new_after_n_chars") == 2000
    assert RecorderCore.captured_params.get("max_characters") == 3000
    assert RecorderCore.captured_params.get("table_transformer_model_path") == "/models/table"
    assert RecorderCore.captured_params.get(
        "unstructured_default_model_initialize_params_json_path"
    ) == "/models/unstructured.json"


def test_process_file_no_model_omits_chunk_params(monkeypatch, tmp_path):
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
    source_path = make_temp_file(tmp_path, "b.txt")
    actor.process_file(
        source=source_path,
        chunking_strategy="basic",
        destination="local",
        model_id=10,
        tenant_id="t2",
    )

    assert RecorderCore.captured_params is not None
    assert "new_after_n_chars" not in RecorderCore.captured_params
    assert "max_characters" not in RecorderCore.captured_params
    assert RecorderCore.captured_params.get("table_transformer_model_path") == "/models/table"
    assert RecorderCore.captured_params.get(
        "unstructured_default_model_initialize_params_json_path"
    ) == "/models/unstructured.json"


def test_process_file_model_lookup_exception_uses_defaults(monkeypatch, tmp_path):
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
    source_path = make_temp_file(tmp_path, "c.txt")
    actor.process_file(
        source=source_path,
        chunking_strategy="basic",
        destination="local",
        model_id=11,
        tenant_id="t3",
    )

    assert RecorderCore.captured_params is not None
    assert "new_after_n_chars" not in RecorderCore.captured_params
    assert "max_characters" not in RecorderCore.captured_params
    assert RecorderCore.captured_params.get("table_transformer_model_path") == "/models/table"
    assert RecorderCore.captured_params.get(
        "unstructured_default_model_initialize_params_json_path"
    ) == "/models/unstructured.json"


def test_process_file_get_stream_none_raises(monkeypatch):
    # Override get_file_stream to return None
    fake_attachment_db_mod = types.ModuleType("database.attachment_db")
    fake_attachment_db_mod.get_file_stream = lambda source: None
    fake_attachment_db_mod.get_file_size_from_minio = lambda path_or_url: 0
    fake_attachment_db_mod.upload_fileobj = lambda *a, **k: {"success": True, "object_name": "o"}
    fake_attachment_db_mod.build_s3_url = lambda object_name: f"s3://bucket/{object_name}"
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
    stub_consts(monkeypatch)

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


def test_process_file_core_returns_none_list_variants(monkeypatch, tmp_path):
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
        fake_attachment_db_mod.get_file_size_from_minio = lambda path_or_url: 0
        fake_attachment_db_mod.upload_fileobj = lambda *a, **k: {"success": True, "object_name": "o"}
        fake_attachment_db_mod.build_s3_url = lambda object_name: f"s3://bucket/{object_name}"
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
        stub_consts(monkeypatch)

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
        source_path = make_temp_file(tmp_path, f"a_{core_cls.__name__}.txt")
        chunks = actor.process_file(source_path, "basic", destination="local")
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


def test_process_file_appends_image_chunks(monkeypatch, tmp_path):
    ray_actors = import_module(monkeypatch)

    class CoreWithImages:
        def file_process(self, *a, **k):
            return (
                [{"content": "text", "metadata": {}}],
                [
                    {
                        "image_bytes": b"img",
                        "image_format": "png",
                        "position": {"page_number": 1},
                    }
                ],
            )

    monkeypatch.setattr(ray_actors, "DataProcessCore", CoreWithImages)
    monkeypatch.setattr(
        ray_actors,
        "upload_fileobj",
        lambda file_obj, file_name, prefix=None: {"object_name": f"{prefix}/{file_name}"},
    )
    monkeypatch.setattr(
        ray_actors,
        "build_s3_url",
        lambda object_name: f"s3://bucket/{object_name}",
    )

    actor = ray_actors.DataProcessorRayActor()
    source_path = make_temp_file(tmp_path, "a.pdf", content=b"%PDF-1.4")
    chunks = actor.process_file(source_path, "basic", destination="local")

    assert len(chunks) == 2
    assert chunks[1]["metadata"]["process_source"] == "UniversalImageExtractor"
    assert "image_url" in chunks[1]["metadata"]


def test_process_file_skips_invalid_image_entries(monkeypatch, tmp_path):
    ray_actors = import_module(monkeypatch)

    class CoreWithBadImages:
        def file_process(self, *a, **k):
            return (
                [{"content": "text", "metadata": {}}],
                [{"not": "dict"}, {"image_format": "png"}],
            )

    monkeypatch.setattr(ray_actors, "DataProcessCore", CoreWithBadImages)
    actor = ray_actors.DataProcessorRayActor()
    source_path = make_temp_file(tmp_path, "a.pdf", content=b"%PDF-1.4")
    chunks = actor.process_file(source_path, "basic", destination="local")

    assert chunks == [{"content": "text", "metadata": {}}]
def test_process_bytes_and_split_file_branches(monkeypatch):
    ray_actors = import_module(monkeypatch)

    class PartOK:
        def getvalue(self):
            return b"ok"

    class PartBad:
        def getvalue(self):
            raise ValueError("bad part")

    class CoreWithSplit(FakeDataProcessCore):
        def file_split(self, file_data, filename, max_size, **params):
            return [PartOK(), PartBad()]

    monkeypatch.setattr(ray_actors, "DataProcessCore", CoreWithSplit)
    actor = ray_actors.DataProcessorRayActor()
    chunks = actor.process_bytes(b"abc", "x.txt", "basic", task_id="t1")
    assert len(chunks) == 1
    parts = actor.split_file("x.txt", "local", file_data=b"seed")
    assert parts == [b"ok"]


def test_split_file_fetch_stream_none_raises(monkeypatch):
    ray_actors = import_module(monkeypatch)
    monkeypatch.setattr(ray_actors, "get_file_stream", lambda source: None)
    actor = ray_actors.DataProcessorRayActor()
    with pytest.raises(FileNotFoundError):
        actor.split_file("missing", "minio")


def test_store_chunks_in_redis_len_error_and_client_error(monkeypatch):
    ray_actors = import_module(monkeypatch)
    monkeypatch.setattr(ray_actors, "REDIS_BACKEND_URL", "redis://test")

    class LenBoomList(list):
        def __len__(self):
            raise RuntimeError("len boom")

    fake_client = FakeRedisClient()
    fake_redis_module = types.SimpleNamespace(Redis=types.SimpleNamespace(from_url=lambda *a, **k: fake_client))
    monkeypatch.setitem(sys.modules, "redis", fake_redis_module)

    actor = ray_actors.DataProcessorRayActor()
    assert actor.store_chunks_in_redis("k-len", LenBoomList([{"a": 1}])) is True
    assert json.loads(fake_client.get("k-len")) == [{"a": 1}]

    bad_redis_module = types.SimpleNamespace(
        Redis=types.SimpleNamespace(from_url=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("conn"))))
    monkeypatch.setitem(sys.modules, "redis", bad_redis_module)
    assert actor.store_chunks_in_redis("k-err", [{"a": 1}]) is False


def test_apply_model_chunk_sizes_and_read_file_bytes_helpers(monkeypatch):
    ray_actors = import_module(monkeypatch)
    actor = ray_actors.DataProcessorRayActor()

    monkeypatch.setattr(
        ray_actors,
        "get_model_by_model_id",
        lambda model_id, tenant_id=None: {
            "expected_chunk_size": 111,
            "maximum_chunk_size": 222,
            "display_name": "emb",
            "model_type": "embedding",
        },
    )
    params = {}
    actor._apply_model_chunk_sizes(1, "t1", params)
    assert params["new_after_n_chars"] == 111
    assert params["max_characters"] == 222
    assert params["model_type"] == "embedding"

    monkeypatch.setattr(ray_actors, "get_file_stream", lambda source: io.BytesIO(b"bytes"))
    assert actor._read_file_bytes("s3://x") == b"bytes"

    monkeypatch.setattr(ray_actors, "get_file_stream", lambda source: None)
    with pytest.raises(FileNotFoundError):
        actor._read_file_bytes("s3://missing")


def test_split_file_returns_empty_when_no_parts(monkeypatch):
    ray_actors = import_module(monkeypatch)

    class CoreNoParts(FakeDataProcessCore):
        def file_split(self, *a, **k):
            return []

    monkeypatch.setattr(ray_actors, "DataProcessCore", CoreNoParts)
    actor = ray_actors.DataProcessorRayActor()
    assert actor.split_file("x.txt", "local", file_data=b"abc") == []


def test_ping_returns_true(monkeypatch):
    """Test that ping() returns True for health check."""
    ray_actors = import_module(monkeypatch)
    actor = ray_actors.DataProcessorRayActor()
    assert actor.ping() is True


def test_normalize_processor_result_variants(monkeypatch):
    """Test _normalize_processor_result handles various return types."""
    ray_actors = import_module(monkeypatch)
    actor = ray_actors.DataProcessorRayActor()

    # Tuple with both chunks and images
    result1 = ([{"content": "a"}], [{"image": "b"}])
    chunks, images = actor._normalize_processor_result(result1)
    assert chunks == [{"content": "a"}]
    assert images == [{"image": "b"}]

    # Empty tuple
    result2 = ([], [])
    chunks, images = actor._normalize_processor_result(result2)
    assert chunks == []
    assert images == []

    # None result
    result3 = None
    chunks, images = actor._normalize_processor_result(result3)
    assert chunks == []
    assert images == []

    # List only (not a tuple)
    result4 = [{"content": "list-only"}]
    chunks, images = actor._normalize_processor_result(result4)
    assert chunks == [{"content": "list-only"}]
    assert images == []

    # Empty list
    result5 = []
    chunks, images = actor._normalize_processor_result(result5)
    assert chunks == []
    assert images == []


def test_validate_chunks_variants(monkeypatch):
    """Test _validate_chunks handles edge cases."""
    ray_actors = import_module(monkeypatch)
    actor = ray_actors.DataProcessorRayActor()

    # None chunks
    result = actor._validate_chunks(None, "source.txt")
    assert result == []

    # Non-list type
    result = actor._validate_chunks("string", "source.txt")
    assert result == []

    # Empty list
    result = actor._validate_chunks([], "source.txt")
    assert result == []

    # Valid list
    valid_chunks = [{"content": "valid"}]
    result = actor._validate_chunks(valid_chunks, "source.txt")
    assert result == valid_chunks


def test_append_image_chunks_skips_invalid_entries(monkeypatch):
    """Test _append_image_chunks skips non-dict and missing-image_bytes entries."""
    ray_actors = import_module(monkeypatch)

    class CoreWithBadImages:
        def file_process(self, *a, **k):
            return (
                [{"content": "text", "metadata": {}}],
                [
                    "not-a-dict",
                    {"image_format": "png"},  # Missing image_bytes
                ],
            )

    monkeypatch.setattr(ray_actors, "DataProcessCore", CoreWithBadImages)
    monkeypatch.setattr(
        ray_actors,
        "upload_fileobj",
        lambda file_obj, file_name, prefix=None: {"object_name": f"{prefix}/{file_name}"},
    )
    monkeypatch.setattr(
        ray_actors,
        "build_s3_url",
        lambda object_name: f"s3://bucket/{object_name}",
    )

    actor = ray_actors.DataProcessorRayActor()
    chunks = [{"content": "text", "metadata": {}}]
    images = [
        "not-a-dict",
        {"image_format": "png"},
    ]
    actor._append_image_chunks("source.pdf", chunks, images)
    # Only valid text chunk should remain, no image chunks added
    assert len(chunks) == 1
    assert chunks[0]["content"] == "text"


def test_apply_model_paths_sets_correct_keys(monkeypatch):
    """Test _apply_model_paths sets the required model path keys."""
    ray_actors = import_module(monkeypatch)
    actor = ray_actors.DataProcessorRayActor()
    params = {}
    actor._apply_model_paths(params)
    assert "table_transformer_model_path" in params
    assert "unstructured_default_model_initialize_params_json_path" in params
    assert params["table_transformer_model_path"] == "/models/table"
    assert params["unstructured_default_model_initialize_params_json_path"] == "/models/unstructured.json"


def test_process_bytes_with_minio_source(monkeypatch):
    """Test process_bytes with minio source fetching file data."""
    ray_actors = import_module(monkeypatch)

    class CoreRecords:
        captured = {}

        def __init__(self):
            pass

        def file_process(self, file_data, filename, chunking_strategy, **params):
            CoreRecords.captured = {
                "file_data": file_data,
                "filename": filename,
                "chunking_strategy": chunking_strategy,
            }
            return [{"content": "processed", "metadata": {}}]

    monkeypatch.setattr(ray_actors, "DataProcessCore", CoreRecords)
    actor = ray_actors.DataProcessorRayActor()

    # With file_data provided directly
    chunks = actor.process_bytes(
        b"file bytes content",
        "test.pdf",
        "basic",
        task_id="task-123",
        model_id=5,
        tenant_id="tenant-1"
    )
    assert len(chunks) == 1
    assert CoreRecords.captured["filename"] == "test.pdf"
    assert CoreRecords.captured["chunking_strategy"] == "basic"


def test_split_file_logs_timing_and_parts(monkeypatch, caplog):
    """Test split_file logs timing and part statistics."""
    ray_actors = import_module(monkeypatch)

    class PartBytes:
        def __init__(self, data):
            self._data = data

        def getvalue(self):
            return self._data

    class CoreWithSplit:
        def file_split(self, *a, **k):
            # Return 3 parts with different sizes
            return [
                PartBytes(b"part1 data here"),
                PartBytes(b"part2 data"),
                PartBytes(b"part3"),
            ]

    monkeypatch.setattr(ray_actors, "DataProcessCore", CoreWithSplit)
    actor = ray_actors.DataProcessorRayActor()
    parts = actor.split_file("large.pdf", "local", file_data=b"large file content")

    assert len(parts) == 3
    assert parts[0] == b"part1 data here"
    assert parts[1] == b"part2 data"
    assert parts[2] == b"part3"


def test_split_file_handles_exception_in_getvalue(monkeypatch):
    """Test split_file continues when part.getvalue() raises."""
    ray_actors = import_module(monkeypatch)

    class PartGood:
        def getvalue(self):
            return b"good part"

    class PartBad:
        def getvalue(self):
            raise RuntimeError("getvalue failed")

    class CoreWithBadParts:
        def file_split(self, *a, **k):
            return [PartGood(), PartBad(), PartGood()]

    monkeypatch.setattr(ray_actors, "DataProcessCore", CoreWithBadParts)
    actor = ray_actors.DataProcessorRayActor()
    parts = actor.split_file("test.pdf", "local", file_data=b"content")

    # Only good parts should be returned
    assert len(parts) == 2
    assert parts[0] == b"good part"
    assert parts[1] == b"good part"


def test_store_chunks_in_redis_with_various_chunks(monkeypatch):
    """Test store_chunks_in_redis with various chunk inputs."""
    ray_actors = import_module(monkeypatch)
    monkeypatch.setattr(ray_actors, "REDIS_BACKEND_URL", "redis://test")

    fake_client = FakeRedisClient()
    fake_redis_module = types.SimpleNamespace(
        Redis=types.SimpleNamespace(from_url=lambda *a, **k: fake_client)
    )
    monkeypatch.setitem(sys.modules, "redis", fake_redis_module)

    actor = ray_actors.DataProcessorRayActor()

    # Empty list
    ok = actor.store_chunks_in_redis("k-empty", [])
    assert ok is True
    assert json.loads(fake_client.get("k-empty")) == []

    # List with various types
    ok = actor.store_chunks_in_redis("k-mixed", [
        {"content": "text", "metadata": {"key": "value"}},
        {"content": "text2", "numbers": [1, 2, 3]},
    ])
    assert ok is True
    stored = json.loads(fake_client.get("k-mixed"))
    assert len(stored) == 2

    # Verify expiration was set
    assert "k-empty" in fake_client.expirations
    assert fake_client.expirations["k-empty"] == 2 * 60 * 60


def test_prepare_process_params(monkeypatch):
    """Test _prepare_process_params applies model paths and chunk sizes."""
    ray_actors = import_module(monkeypatch)

    class RecorderCore:
        captured_params = None

        def __init__(self):
            pass

        def file_process(self, file_data, filename, chunking_strategy, **params):
            RecorderCore.captured_params = params
            return [{"content": "x", "metadata": {}}]

    monkeypatch.setattr(ray_actors, "DataProcessCore", RecorderCore)
    monkeypatch.setattr(
        ray_actors,
        "get_model_by_model_id",
        lambda model_id, tenant_id=None: {
            "expected_chunk_size": 500,
            "maximum_chunk_size": 1000,
            "display_name": "test-model",
            "model_type": "embedding",
        },
    )

    actor = ray_actors.DataProcessorRayActor()
    params = {"extra_key": "extra_value"}
    result = actor._prepare_process_params(
        task_id="task-1",
        model_id=5,
        tenant_id="tenant-1",
        params=params,
    )

    assert result["task_id"] == "task-1"
    assert result["new_after_n_chars"] == 500
    assert result["max_characters"] == 1000
    assert result["model_type"] == "embedding"
    assert result["table_transformer_model_path"] == "/models/table"
    assert result["extra_key"] == "extra_value"


def test_run_file_process_with_telemetry_context(monkeypatch):
    """Test _run_file_process uses knowledge_span for telemetry."""
    ray_actors = import_module(monkeypatch)

    captured_spans = []

    class MockKnowledgeSpan:
        def __init__(self, name, operation, **kwargs):
            self.name = name
            self.operation = operation
            self.kwargs = kwargs
            captured_spans.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class RecordingCore:
        def __init__(self):
            self.calls = []

        def file_process(self, file_data, filename, chunking_strategy, **params):
            self.calls.append((filename, chunking_strategy, params))
            return [{"content": "test content", "metadata": {"creation_date": "2024-01-01"}}]

    monkeypatch.setattr(ray_actors, "DataProcessCore", RecordingCore)
    telemetry_module = types.SimpleNamespace(knowledge_span=MockKnowledgeSpan)
    monkeypatch.setitem(sys.modules, "utils.knowledge_telemetry", telemetry_module)

    actor = ray_actors.DataProcessorRayActor()
    result = actor._run_file_process(
        file_data=b"test data",
        filename="test.txt",
        chunking_strategy="basic",
        process_params={
            "telemetry_context": {"trace_id": "abc123"},
            "task_id": "task-1",
        },
        log_subject="test",
    )

    assert len(result) == 1
    assert result[0]["content"] == "test content"
    assert len(captured_spans) == 1
    assert captured_spans[0].kwargs["telemetry_context"] == {"trace_id": "abc123"}


def test_actor_initializes_monitoring_when_available(monkeypatch):
    ray_actors = import_module(monkeypatch)
    manager = types.SimpleNamespace(is_enabled=True)
    monitoring_module = types.SimpleNamespace(monitoring_manager=manager)
    monkeypatch.setitem(sys.modules, "utils.monitoring", monitoring_module)

    actor = ray_actors.DataProcessorRayActor()

    assert actor._monitoring_manager is manager


def test_actor_degrades_when_monitoring_status_fails(monkeypatch):
    ray_actors = import_module(monkeypatch)

    class BrokenManager:
        @property
        def is_enabled(self):
            raise RuntimeError("monitoring unavailable")

    monitoring_module = types.SimpleNamespace(monitoring_manager=BrokenManager())
    monkeypatch.setitem(sys.modules, "utils.monitoring", monitoring_module)

    actor = ray_actors.DataProcessorRayActor()

    assert actor._monitoring_manager is None


def test_split_file_fetches_stream_and_model_type_is_optional(monkeypatch):
    ray_actors = import_module(monkeypatch)

    class Part:
        def getvalue(self):
            return b"part"

    class RecordingCore(FakeDataProcessCore):
        captured_file_data = None

        def file_split(self, file_data, **kwargs):
            RecordingCore.captured_file_data = file_data
            return [Part()]

    monkeypatch.setattr(ray_actors, "DataProcessCore", RecordingCore)
    monkeypatch.setattr(ray_actors, "get_file_stream", lambda source: io.BytesIO(b"stream-data"))
    monkeypatch.setattr(
        ray_actors,
        "get_model_by_model_id",
        lambda model_id, tenant_id=None: {
            "expected_chunk_size": 100,
            "maximum_chunk_size": 200,
            "display_name": "model-without-type",
            "model_type": None,
        },
    )

    actor = ray_actors.DataProcessorRayActor()
    params = {}
    actor._apply_model_chunk_sizes(model_id=1, tenant_id="tenant", params=params)
    parts = actor.split_file("s3://bucket/source.pdf", "minio")

    assert "model_type" not in params
    assert parts == [b"part"]
    assert RecordingCore.captured_file_data == b"stream-data"
