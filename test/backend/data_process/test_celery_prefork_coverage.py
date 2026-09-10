"""Coverage-focused tests for the Ray-free Celery data-process boundary."""

import asyncio
import io
import json
import sys
import types

import pytest


def _configure_celery_environment(monkeypatch):
    broker_url = "redis://localhost:6379/0"
    backend_url = "redis://localhost:6379/1"
    monkeypatch.setenv("REDIS_URL", broker_url)
    monkeypatch.setenv("REDIS_BACKEND_URL", backend_url)
    from consts import const as constants

    monkeypatch.setattr(constants, "REDIS_URL", broker_url)
    monkeypatch.setattr(constants, "REDIS_BACKEND_URL", backend_url)


def _disable_celery_result_backend(monkeypatch, module):
    """Keep direct task.run() coverage tests independent of a live Redis backend."""
    task_names = (
        "parser_bootstrap",
        "process_part",
        "aggregate_parts",
        "aggregate_store_chunks",
        "process",
        "process_sync",
        "forward_part",
        "aggregate_forward_parts",
        "forward",
        "cleanup_source",
        "process_and_forward",
    )
    for task_name in task_names:
        task = getattr(module, task_name, None)
        if task is not None and hasattr(task, "update_state"):
            monkeypatch.setattr(task, "update_state", lambda **_kwargs: None)


@pytest.fixture()
def tasks(monkeypatch):
    _configure_celery_environment(monkeypatch)
    import data_process.tasks as module

    _disable_celery_result_backend(monkeypatch, module)
    return module


@pytest.fixture()
def parser_runtime(monkeypatch):
    _configure_celery_environment(monkeypatch)
    from data_process import parse_tasks
    from data_process import parser_runtime as module

    _disable_celery_result_backend(monkeypatch, parse_tasks)
    return module


class FakeSelf:
    def __init__(self, task_id="task-1", retries=0):
        self.request = types.SimpleNamespace(id=task_id, retries=retries)
        self.states = []

    def update_state(self, **kwargs):
        self.states.append(kwargs)

    def retry(self, **kwargs):
        raise RuntimeError("retry requested")


def test_task_helpers_and_error_paths(tasks, monkeypatch):
    from data_process import parse_tasks

    assert parse_tasks._count_image_metadata_chunks(None) == 0
    assert parse_tasks._count_image_metadata_chunks(
        [{"process_source": "UniversalImageExtractor"}, {"metadata": {"process_source": "UniversalImageExtractor"}}]
    ) == 2
    assert tasks._build_balanced_batches([]) == []
    assert len(tasks._build_balanced_batches([{"content": str(i)} for i in range(5)], batch_size=2)) == 3
    with pytest.raises(RuntimeError, match="while distributing"):
        tasks._distribute_chunks_round_robin([[{"content": "full"}]], [{"content": "extra"}], 1, "text chunks")

    assert tasks._redis_error_reason(types.SimpleNamespace(error_code="E2", error_message="bad")) == '{"error_code": "E2"}'
    assert tasks._redis_error_reason(types.SimpleNamespace(error_code=None, error_message="bad")) == "bad"
    assert tasks._parse_json_or_none('{"a": 1}') == {"a": 1}
    assert tasks._parse_json_or_none("[]") is None
    error = tasks._build_forward_error("bad", "idx", "source", "name", "E3")
    assert json.loads(str(error))["error_code"] == "E3"

    class RedisService:
        def save_error_info(self, task_id, reason):
            return task_id == "ok"

        def is_task_cancelled(self, task_id):
            return task_id == "cancelled"

    monkeypatch.setattr(tasks, "get_redis_service", lambda: RedisService())
    tasks.save_error_to_redis("", "bad")
    tasks.save_error_to_redis("ok", "bad")
    tasks.save_error_to_redis("no", "bad")
    tasks.save_error_to_redis("ok", "")

    ctx = tasks._init_forward_context(
        task_id="cancelled", request_id="request", start_time=0, source="source", index_name="idx",
        original_filename="name",
    )
    monkeypatch.setattr(tasks, "get_redis_service", lambda: RedisService())
    assert tasks._is_forward_task_cancelled(ctx) is True
    assert tasks._build_forward_cancelled_result(ctx)["chunks_stored"] == 0


def test_task_storage_and_lifecycle_helpers(tasks, monkeypatch):
    class Client:
        def __init__(self):
            self.values = {}
            self.deleted = []

        def set(self, key, value, ex=None):
            self.values[key] = value

        def get(self, key):
            return self.values.get(key)

        def delete(self, *keys):
            self.deleted.extend(keys)

    client = Client()
    monkeypatch.setattr(tasks, "_forward_redis_client", lambda: client)
    key = tasks._store_forward_batch("task", 1, [{"content": "payload"}])
    assert tasks._load_forward_batch(key) == [{"content": "payload"}]
    tasks._cleanup_forward_batches([key])
    assert client.deleted == [key]
    with pytest.raises(RuntimeError, match="missing"):
        tasks._load_forward_batch("missing")

    class Response:
        status_code = 200
        text = '{"status":"success"}'

        def json(self):
            return {"status": "success"}

    monkeypatch.setattr(tasks.requests, "delete", lambda *args, **kwargs: Response())
    deleted = tasks._delete_source_file_via_http_sync(
        base_url="http://api/", index_name="idx", path_or_url="source", scope="source_only", authorization="Bearer x"
    )
    assert deleted["http_status"] == 200
    with pytest.raises(RuntimeError, match="not configured"):
        tasks._delete_source_file_via_http_sync(
            base_url="", index_name="idx", path_or_url="source", scope="source_only"
        )


def test_run_async_and_forward_aggregation(tasks, monkeypatch):
    async def value():
        return "value"

    assert tasks.run_async(value()) == "value"
    loop = asyncio.new_event_loop()
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: loop)
    assert tasks.run_async(value()) == "value"
    loop.close()

    assert tasks.aggregate_forward_parts.run(
        [{"total_indexed": 2, "total_submitted": 3}, None, {"total_indexed": 1}]
    )["total_indexed"] == 3
    assert tasks._extract_error_code_from_es_response({"error_code": "E"}, "") == "E"
    assert tasks._extract_error_code_from_es_response(None, "plain") is None


def test_load_forward_chunks_from_inline_and_redis(tasks, monkeypatch):
    fake = FakeSelf("forward")
    inline = tasks._load_forward_chunks(
        fake,
        processed_data={"chunks": [{"content": "inline"}], "source": "new-source", "index_name": "new-index"},
        original_source="source",
        original_index_name="idx",
        filename=None,
    )
    assert inline[0] == [{"content": "inline"}] and inline[2:4] == ("new-source", "new-index")

    class Client:
        def get(self, key):
            return '{"ready":true}' if key == "redis-key" else "1"

    redis_module = types.ModuleType("redis")
    redis_module.Redis = types.SimpleNamespace(from_url=lambda *args, **kwargs: Client())
    monkeypatch.setitem(sys.modules, "redis", redis_module)
    loaded = tasks._load_forward_chunks(
        fake,
        processed_data={"redis_key": "redis-key", "split_async": True, "original_filename": "loaded.txt"},
        original_source="source",
        original_index_name="idx",
        filename=None,
    )
    assert loaded[0] == {"ready": True} and loaded[-1] == "loaded.txt"

    monkeypatch.setattr(tasks, "REDIS_BACKEND_URL", None)
    with pytest.raises(Exception, match="REDIS_BACKEND_URL"):
        tasks._load_forward_chunks(
            fake, processed_data={"redis_key": "key"}, original_source="source", original_index_name="idx", filename=None
        )

    monkeypatch.setattr(tasks, "REDIS_BACKEND_URL", "redis://localhost")
    monkeypatch.setitem(sys.modules, "redis", types.SimpleNamespace(
        Redis=types.SimpleNamespace(from_url=lambda *args, **kwargs: types.SimpleNamespace(get=lambda _key: "not-json"))
    ))
    with pytest.raises(Exception, match="Failed to retrieve chunks"):
        tasks._load_forward_chunks(
            fake, processed_data={"redis_key": "key"}, original_source="source", original_index_name="idx", filename=None
        )
    with pytest.raises(Exception, match="No chunks received"):
        tasks._load_forward_chunks(
            fake, processed_data={"chunks": None}, original_source="source", original_index_name="idx", filename=None
        )


def test_send_chunks_to_es_http_paths(tasks, monkeypatch):
    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://es")

    class Response:
        def __init__(self, status, body, json_body=None, enter_error=None):
            self.status = status
            self._body = body
            self._json_body = json_body
            self._enter_error = enter_error

        async def __aenter__(self):
            if self._enter_error:
                raise self._enter_error
            return self

        async def __aexit__(self, *args):
            return False

        async def text(self):
            return self._body

        async def json(self):
            return self._json_body

    class Session:
        def __init__(self, response):
            self.response = response

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return self.response

    monkeypatch.setattr(tasks.aiohttp, "ClientSession", lambda **kwargs: Session(Response(200, '{"success":true}', {"success": True})))
    assert tasks._send_chunks_to_es([{"content": "x"}], "idx", "Bearer x", task_id="t", large_mode=True)["success"] is True

    monkeypatch.setattr(tasks.aiohttp, "ClientSession", lambda **kwargs: Session(Response(200, "not-json", {"success": True})))
    assert tasks._send_chunks_to_es([], "idx", None)["success"] is True

    monkeypatch.setattr(tasks.aiohttp, "ClientSession", lambda **kwargs: Session(Response(400, '{"error_code":"E"}')))
    with pytest.raises(Exception, match="Unexpected error"):
        tasks._send_chunks_to_es([], "idx", None)
    monkeypatch.setattr(tasks.aiohttp, "ClientSession", lambda **kwargs: Session(Response(400, "bad")))
    with pytest.raises(Exception, match="Unexpected error"):
        tasks._send_chunks_to_es([], "idx", None)
    monkeypatch.setattr(tasks.aiohttp, "ClientSession", lambda **kwargs: Session(Response(200, "", enter_error=asyncio.TimeoutError())))
    with pytest.raises(Exception, match="Timeout when indexing"):
        tasks._send_chunks_to_es([], "idx", None)

    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", None)
    with pytest.raises(Exception, match="ELASTICSEARCH_SERVICE env is not set"):
        tasks._send_chunks_to_es([], "idx", None)


def test_forward_success_and_failure_paths(tasks, monkeypatch):
    monkeypatch.setattr(tasks, "_update_file_lifecycle", lambda **kwargs: None)
    monkeypatch.setattr(tasks, "_is_forward_task_cancelled", lambda _ctx: False)
    monkeypatch.setattr(tasks, "get_file_size", lambda *args: 11)
    monkeypatch.setattr(tasks, "_send_chunks_to_es", lambda **kwargs: {"success": True, "total_indexed": 1, "total_submitted": 1})
    monkeypatch.setattr(tasks, "get_redis_service", lambda: types.SimpleNamespace(save_progress_info=lambda *args: None))

    tasks.forward.push_request(id="forward")
    try:
        result = tasks.forward.run(
            {"chunks": [{"content": "text", "metadata": {"date": "today"}}, {"content": "  "}]},
            index_name="idx", source="source", source_type="local", original_filename="name.txt",
        )
    finally:
        tasks.forward.pop_request()
    assert result["chunks_stored"] == 2 and result["es_result"]["success"] is True

    monkeypatch.setattr(tasks, "_is_forward_task_cancelled", lambda _ctx: True)
    tasks.forward.push_request(id="cancelled")
    try:
        assert tasks.forward.run({"chunks": [{"content": "x"}]}, index_name="idx", source="source")["chunks_stored"] == 0
    finally:
        tasks.forward.pop_request()

    monkeypatch.setattr(tasks, "_is_forward_task_cancelled", lambda _ctx: False)
    monkeypatch.setattr(tasks, "save_error_to_redis", lambda *args: None)
    tasks.forward.push_request(id="failed")
    try:
        with pytest.raises(Exception, match="No valid chunks"):
            tasks.forward.run({"chunks": [{"content": " "}]}, index_name="idx", source="source")
    finally:
        tasks.forward.pop_request()


def test_forward_part_and_cleanup_paths(tasks, monkeypatch):
    fake = FakeSelf("parent")
    monkeypatch.setattr(tasks, "_load_forward_batch", lambda _key: [{"content": "x"}])
    monkeypatch.setattr(tasks, "_send_chunks_to_es", lambda **kwargs: {"success": True, "total_indexed": 2, "total_submitted": 2})
    progress = []
    redis_service = types.SimpleNamespace(
        is_task_cancelled=lambda _task_id: False,
        increment_progress_info=lambda **kwargs: progress.append(kwargs),
    )
    monkeypatch.setattr(tasks, "get_redis_service", lambda: redis_service)
    tasks.forward_part.push_request(id="parent", retries=0)
    try:
        result = tasks.forward_part.run(
            "batch-key", "idx", parent_task_id="parent", parent_total_chunks=2, batch_index=1, total_batches=1
        )
    finally:
        tasks.forward_part.pop_request()
    assert result["total_indexed"] == 2 and progress

    redis_service.is_task_cancelled = lambda _task_id: True
    tasks.forward_part.push_request(id="parent", retries=0)
    try:
        assert tasks.forward_part.run("batch-key", "idx", parent_task_id="parent")["cancelled"] is True
    finally:
        tasks.forward_part.pop_request()

    monkeypatch.setattr(tasks, "get_knowledge_record", lambda _query: {"preserve_source_file": True})
    kept = tasks.cleanup_source.run({"index_name": "idx", "source": "source"})
    assert kept["source_cleanup"]["skipped_reason"] == "preserve_source_file_true"
    missing = tasks.cleanup_source.run({})
    assert missing["source_cleanup"]["skipped_reason"] == "missing_index_name_or_source"

    monkeypatch.setattr(tasks, "get_knowledge_record", lambda _query: {"preserve_source_file": False})
    monkeypatch.setattr(
        tasks, "_delete_source_file_via_http_sync", lambda **kwargs: {"http_status": 204, "response_json": None, "response_text": ""}
    )
    cleaned = tasks.cleanup_source.run({"index_name": "idx", "source": "source"})
    assert cleaned["source_cleanup"]["success"] is True


def test_submit_chain_and_combined_task(tasks, monkeypatch):
    class Signature:
        def set(self, **kwargs):
            return self

    class TaskStub:
        def s(self, **kwargs):
            return Signature()

    class Chain:
        def apply_async(self):
            return types.SimpleNamespace(id="chain-id")

    monkeypatch.setattr(tasks, "process", TaskStub())
    monkeypatch.setattr(tasks, "forward", TaskStub())
    monkeypatch.setattr(tasks, "cleanup_source", TaskStub())
    monkeypatch.setattr(tasks, "chain", lambda *args: Chain())
    assert tasks.submit_process_forward_chain(
        source="source", source_type="minio", chunking_strategy="basic", index_name="idx", file_id="fid"
    ) == "chain-id"
    assert tasks.process_and_forward.run(
        source="source", source_type="minio", chunking_strategy="basic", index_name="idx"
    ) == "chain-id"


def test_parser_runtime_paths_and_result_normalization(parser_runtime, monkeypatch, tmp_path):
    assert parser_runtime._aliases_from_config(" a, b,,a ") == ["a", "b", "a"]
    assert parser_runtime.ParserRuntime._normalize_result(([{"content": "x"}], [{"image_bytes": b"x"}]))[0]
    assert parser_runtime.ParserRuntime._normalize_result((None, None)) == ([], [])
    assert parser_runtime.ParserRuntime._validate_chunks("bad", "source") == []

    local = tmp_path / "file.txt"
    local.write_bytes(b"hello")
    assert parser_runtime.ParserRuntime.read_source(str(local), "local") == b"hello"
    with pytest.raises(NotImplementedError):
        parser_runtime.ParserRuntime.read_source(str(local), "unsupported")

    runtime = parser_runtime.ParserRuntime(2, [])
    runtime._core = types.SimpleNamespace(file_process=lambda **kwargs: ([{"content": "x"}], []))
    runtime._initialized = True
    assert runtime.process_source(file_data=b"x", filename="x.txt", chunking_strategy="basic") == [{"content": "x"}]
    runtime._core = types.SimpleNamespace(file_split=lambda **kwargs: [io.BytesIO(b"a"), io.BytesIO(b"b")])
    assert runtime.split_source(file_data=b"ab", filename="x.txt", target_parts=2) == [b"a", b"b"]


def test_parser_runtime_initialization_and_image_append(parser_runtime, monkeypatch):
    calls = []

    class Core:
        def __init__(self, model_paths=None):
            calls.append(model_paths)

        def preload_models(self, aliases):
            calls.append(aliases)

    fake_package = types.ModuleType("nexent.data_process")
    fake_package.DataProcessCore = Core
    monkeypatch.setitem(sys.modules, "nexent.data_process", fake_package)
    monkeypatch.setattr(parser_runtime, "_configure_third_party_model_paths", lambda paths: paths)
    runtime = parser_runtime.ParserRuntime(2, ["unstructured_default"])
    runtime.ensure_initialized()
    runtime.ensure_initialized()
    assert runtime.initialized and calls[1] == ["unstructured_default"]

    uploads = []
    attachment = types.ModuleType("database.attachment_db")
    attachment.upload_fileobj = lambda **kwargs: uploads.append(kwargs) or {"success": True, "object_name": "image.png"}
    attachment.build_s3_url = lambda name: "s3://" + name
    monkeypatch.setitem(sys.modules, "database.attachment_db", attachment)
    chunks = []
    parser_runtime.ParserRuntime._append_image_chunks(
        "doc.pdf", chunks, [{"image_bytes": b"x", "image_format": "png", "position": 1}, {"position": 2}]
    )
    assert len(chunks) == 1 and uploads


def test_parse_task_storage_bootstrap_and_part_tasks(parser_runtime, monkeypatch):
    from data_process import parse_tasks

    class Client:
        def __init__(self):
            self.calls = []
            self.values = {"key": json.dumps([{"content": "chunk"}])}

        def set(self, *args, **kwargs):
            self.calls.append(("set", args, kwargs))

        def get(self, key):
            return self.values.get(key)

        def delete(self, *keys):
            self.calls.append(("delete", keys))

        def rename(self, *args):
            self.calls.append(("rename", args))

        def sadd(self, *args):
            self.calls.append(("sadd", args))

        def expire(self, *args):
            self.calls.append(("expire", args))

        def scard(self, _key):
            return 1

    client = Client()
    monkeypatch.setattr(parse_tasks, "_redis_client", lambda: client)
    import database.attachment_db as attachment

    deleted = []
    monkeypatch.setattr(attachment, "delete_file", lambda uri: deleted.append(uri))
    monkeypatch.setattr(attachment, "upload_fileobj", lambda **kwargs: {"success": True})
    monkeypatch.setattr(attachment, "build_s3_url", lambda name: "s3://" + name)
    parse_tasks.store_chunks_atomically("key", [{"content": "chunk"}])
    assert parse_tasks.load_chunks_from_redis("key") == [{"content": "chunk"}]
    parse_tasks.cleanup_parser_artifacts("task", [{"part_index": 0, "uri": "s3://part"}], include_final=True)

    part = parse_tasks._upload_part("task", 0, "file.txt", b"data")
    assert part["part_index"] == 0 and deleted == ["s3://part"]

    runtime = types.SimpleNamespace(preload_models=["unstructured_default"])
    monkeypatch.setattr(parse_tasks, "ensure_parser_runtime", lambda: runtime)
    parse_tasks.parser_bootstrap.push_request(id="bootstrap")
    try:
        ready = parse_tasks.parser_bootstrap.run("generation", 1)
    finally:
        parse_tasks.parser_bootstrap.pop_request()
    assert ready["ready"] is True

    parser = types.SimpleNamespace(
        read_source=lambda source, source_type: b"data",
        process_source=lambda **kwargs: [{"content": "part"}],
    )
    monkeypatch.setattr(parse_tasks, "get_parser_runtime", lambda: parser)
    monkeypatch.setattr(parse_tasks, "store_chunks_atomically", lambda *args: None)
    parse_tasks.process_part.push_request(id="parent")
    try:
        result = parse_tasks.process_part.run(
            {"uri": "s3://part", "part_index": 0}, "file.txt", "basic", "part-key", parser_task_id="parent"
        )
    finally:
        parse_tasks.process_part.pop_request()
    assert result["chunks_count"] == 1

    monkeypatch.setattr(parse_tasks, "get_parser_runtime", lambda: (_ for _ in ()).throw(RuntimeError("parse failed")))
    monkeypatch.setattr(parse_tasks, "cleanup_parser_artifacts", lambda *args, **kwargs: None)
    parse_tasks.process_part.push_request(id="parent")
    try:
        with pytest.raises(RuntimeError, match="parse failed"):
            parse_tasks.process_part.run(
                {"uri": "s3://part", "part_index": 0}, "file.txt", "basic", "part-key", parser_task_id="parent"
            )
    finally:
        parse_tasks.process_part.pop_request()


def test_parse_aggregation_and_process_tasks(parser_runtime, monkeypatch):
    from data_process import parse_tasks

    monkeypatch.setattr(parse_tasks, "load_chunks_from_redis", lambda key: [{"content": key}])
    stored = []
    monkeypatch.setattr(parse_tasks, "store_chunks_atomically", lambda key, chunks: stored.append((key, chunks)))
    monkeypatch.setattr(parse_tasks, "cleanup_parser_artifacts", lambda *args, **kwargs: None)
    monkeypatch.setattr(parse_tasks, "ensure_document_not_deleted", lambda **_kwargs: None)
    client = types.SimpleNamespace(delete=lambda *args: None)
    monkeypatch.setattr(parse_tasks, "_redis_client", lambda: client)
    parse_tasks.aggregate_store_chunks.push_request(id="aggregate")
    try:
        result = parse_tasks.aggregate_store_chunks.run(
            [{"part_index": 1, "part_redis_key": "b"}, {"part_index": 0, "part_redis_key": "a"}],
            "final", source="source", index_name="idx", task_id="aggregate",
        )
    finally:
        parse_tasks.aggregate_store_chunks.pop_request()
    assert result["split_async"] is True and stored[-1][0] == "final"

    monkeypatch.setattr(parse_tasks, "load_chunks_from_redis", lambda key: [])
    parse_tasks.aggregate_store_chunks.push_request(id="aggregate")
    try:
        with pytest.raises(Exception, match="produced 0 chunks"):
            parse_tasks.aggregate_store_chunks.run([], "final", source="source", index_name="idx", task_id="aggregate")
    finally:
        parse_tasks.aggregate_store_chunks.pop_request()

    runtime = types.SimpleNamespace(
        read_source=lambda source, source_type: b"data",
        process_source=lambda **kwargs: [{"content": "chunk"}],
        preload_models=[],
    )
    monkeypatch.setattr(parse_tasks, "get_parser_runtime", lambda: runtime)
    monkeypatch.setattr(parse_tasks, "store_chunks_atomically", lambda *args: None)
    parse_tasks.process.push_request(id="process")
    try:
        result = parse_tasks.process.run("source", "local", index_name="idx", original_filename="file.txt")
    finally:
        parse_tasks.process.pop_request()
    assert result["chunks_count"] == 1 and result["chunks"] is None

    monkeypatch.setattr(runtime, "process_source", lambda **kwargs: [])
    monkeypatch.setattr(parse_tasks, "cleanup_parser_artifacts", lambda *args, **kwargs: None)
    parse_tasks.process.push_request(id="process-failed")
    try:
        with pytest.raises(Exception, match="produced 0 chunks"):
            parse_tasks.process.run("source", "local", index_name="idx", original_filename="file.txt")
    finally:
        parse_tasks.process.pop_request()

    sync_runtime = types.SimpleNamespace(
        read_source=lambda source, source_type: b"data",
        process_source=lambda **kwargs: [{"content": "hello"}, {"content": "world"}],
    )
    monkeypatch.setattr(parse_tasks, "get_parser_runtime", lambda: sync_runtime)
    parse_tasks.process_sync.push_request(id="sync")
    try:
        result = parse_tasks.process_sync.run("source", "local")
    finally:
        parse_tasks.process_sync.pop_request()
    assert result["text_length"] == 10


def test_parser_runtime_configuration_prepare_params_and_minio(parser_runtime, monkeypatch, tmp_path):
    config_dir = tmp_path / "unstructured"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    config_file.write_text("{}", encoding="utf-8")
    assert parser_runtime._normalize_model_config_path(str(config_dir)) == str(config_file)
    assert parser_runtime._normalize_model_config_path(None) is None
    assert parser_runtime._normalize_model_config_path(str(tmp_path / "missing.json")) == str(tmp_path / "missing.json")

    table_path = tmp_path / "table-model"
    table_path.mkdir()
    configured = parser_runtime._configure_third_party_model_paths(
        {"unstructured_default": str(config_file), "table_transformer": str(table_path)}
    )
    assert configured["unstructured_default"] == str(config_file)
    assert parser_runtime.os.environ["UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH"] == str(config_file)
    assert parser_runtime._configure_third_party_model_paths(
        {"unstructured_default": str(config_file), "table_transformer": str(tmp_path / "bad")}
    )["table_transformer"] == str(tmp_path / "bad")

    runtime = parser_runtime.ParserRuntime(1, [])
    runtime.model_paths = {"unstructured_default": str(config_file), "table_transformer": str(table_path)}
    model_db = types.ModuleType("database.model_management_db")
    model_db.get_model_by_model_id = lambda **kwargs: {
        "maximum_chunk_size": 123,
        "expected_chunk_size": 45,
        "model_type": "custom",
    }
    monkeypatch.setitem(sys.modules, "database.model_management_db", model_db)
    params = runtime._prepare_params(task_id="task", model_id=7, tenant_id="tenant", params={"extra": True})
    assert params["task_id"] == "task" and params["max_characters"] == 123
    assert params["new_after_n_chars"] == 45 and params["model_type"] == "custom"

    stream = io.BytesIO(b"minio-data")
    closed = []
    original_close = stream.close
    stream.close = lambda: (closed.append(True), original_close())[1]
    import database.attachment_db as attachment

    monkeypatch.setattr(attachment, "get_file_stream", lambda _source: stream)
    assert parser_runtime.ParserRuntime.read_source("s3://object", "minio") == b"minio-data"
    assert closed
    monkeypatch.setattr(attachment, "get_file_stream", lambda _source: None)
    with pytest.raises(FileNotFoundError):
        parser_runtime.ParserRuntime.read_source("s3://missing", "minio")


def test_parser_runtime_process_split_and_pid_safe_singleton(parser_runtime, monkeypatch):
    runtime = parser_runtime.ParserRuntime(2, [])
    runtime._initialized = True
    runtime._core = types.SimpleNamespace(
        file_process=lambda **kwargs: ([{"content": "text"}], [{"image_bytes": b"img", "position": 1}]),
        file_split=lambda **kwargs: [io.BytesIO(b"a"), io.BytesIO(b"b")],
    )
    appended = []
    monkeypatch.setattr(parser_runtime.ParserRuntime, "_append_image_chunks", lambda *args: appended.append(args))
    processed = runtime.process_source(
        file_data=b"data", filename="file.txt", chunking_strategy="basic", task_id="task", params={"max_size": 9}
    )
    assert processed == [{"content": "text"}] and appended
    assert runtime.split_source(file_data=b"data", filename="file.txt", target_parts=2, params={"max_size": 9}) == [b"a", b"b"]

    original_runtime = parser_runtime._runtime
    original_pid = parser_runtime._runtime_pid
    try:
        monkeypatch.setattr(parser_runtime.os, "getpid", lambda: 100)
        first = parser_runtime.get_parser_runtime()
        monkeypatch.setattr(parser_runtime.os, "getpid", lambda: 101)
        second = parser_runtime.get_parser_runtime()
        assert first is not second
    finally:
        parser_runtime._runtime = original_runtime
        parser_runtime._runtime_pid = original_pid


def test_model_registry_lazy_loading_and_validation(monkeypatch, tmp_path):
    from nexent.data_process.model_registry import ModelRegistry

    registry = ModelRegistry({"table_transformer": str(tmp_path)})
    assert registry.validate_aliases(["", "unstructured_default", "unstructured_default"]) == ["unstructured_default"]
    with pytest.raises(ValueError, match="Unsupported"):
        registry.validate_aliases(["unknown"])
    with pytest.raises(ValueError, match="Unsupported"):
        registry.get("unknown")

    calls = []
    monkeypatch.setattr(registry, "_load_unstructured_default", lambda: calls.append("load") or object())
    first = registry.get("unstructured_default")
    assert registry.get("unstructured_default") is first and calls == ["load"]
    assert registry.preload(["unstructured_default", "unstructured_default"]) == {"unstructured_default": first}

    model_module = types.ModuleType("unstructured_inference.models.base")
    model_module.get_model = lambda: "default-model"
    monkeypatch.setitem(sys.modules, "unstructured_inference.models.base", model_module)
    fresh = ModelRegistry()
    assert fresh._load_unstructured_default() == "default-model"
    with pytest.raises(FileNotFoundError):
        fresh._normalize_path(str(tmp_path / "missing"))
    assert fresh._normalize_path(None) is None


def test_model_registry_table_loader(monkeypatch, tmp_path):
    from nexent.data_process import extract_image
    from nexent.data_process.model_registry import ModelRegistry

    model_path = tmp_path / "table"
    model_path.mkdir()
    calls = []
    monkeypatch.setattr(extract_image, "custom_load_table_model", lambda: calls.append("load"))
    monkeypatch.setattr(extract_image, "get_tables_agent", lambda: "table-agent")
    registry = ModelRegistry({"table_transformer": str(model_path)})
    assert registry.get("table_transformer") == "table-agent"
    assert calls == ["load"] and extract_image.TABLE_TRANSFORMER_MODEL_PATH == str(model_path)
    with pytest.raises(ValueError, match="TABLE_TRANSFORMER_MODEL_PATH"):
        ModelRegistry().get("table_transformer")


def test_worker_validation_signals_and_service_checks(monkeypatch):
    _configure_celery_environment(monkeypatch)
    from data_process import worker

    monkeypatch.setattr(worker, "QUEUES", "forward_q, parse_q")
    assert worker._queue_set() == {"forward_q", "parse_q"}
    assert worker._is_parser_worker()
    monkeypatch.setattr(worker, "DP_PARSE_MAX_PROCESSES", 0)
    with pytest.raises(ValueError, match="MAX_PROCESSES"):
        worker._validate_parser_config()
    monkeypatch.setattr(worker, "DP_PARSE_MAX_PROCESSES", 2)
    monkeypatch.setattr(worker, "DP_PARSE_MIN_PROCESSES", 3)
    with pytest.raises(ValueError, match="MIN_PROCESSES"):
        worker._validate_parser_config()
    monkeypatch.setattr(worker, "DP_PARSE_MIN_PROCESSES", 1)
    monkeypatch.setattr(worker, "DP_PARSE_THREADS_PER_PROCESS", 0)
    with pytest.raises(ValueError, match="THREADS_PER_PROCESS"):
        worker._validate_parser_config()
    monkeypatch.setattr(worker, "DP_PARSE_THREADS_PER_PROCESS", 1)
    monkeypatch.setattr(worker, "DP_PARSE_MAX_TASKS_PER_CHILD", -1)
    with pytest.raises(ValueError, match="MAX_TASKS_PER_CHILD"):
        worker._validate_parser_config()
    monkeypatch.setattr(worker, "DP_PARSE_MAX_TASKS_PER_CHILD", 1)
    monkeypatch.setattr(worker, "DP_PRELOAD_MODELS", "unknown")
    worker._validate_parser_config()
    monkeypatch.setattr(worker, "QUEUES", "forward_q")
    monkeypatch.setattr(worker, "DP_PARSE_MAX_PROCESSES", 0)
    worker._validate_parser_config()
    assert not worker._is_parser_worker()

    worker.worker_state.update({"initialized": False, "ready": False, "tasks_completed": 0, "tasks_failed": 0})
    monkeypatch.setattr(worker, "_validate_parser_config", lambda: None)
    worker.setup_worker_environment()
    assert worker.worker_state["initialized"]
    worker.worker_ready_handler()
    assert worker.worker_state["ready"]
    worker.task_postrun_handler(task_id="ok", state="SUCCESS")
    worker.task_postrun_handler(task_id="bad", state="FAILURE")
    worker.task_failure_handler(sender=None, task_id="bad", exception=RuntimeError("x"))
    assert worker.worker_state["tasks_completed"] == 1 and worker.worker_state["tasks_failed"] == 1
    worker.task_prerun_handler(sender="sender", task_id="id")
    worker.worker_shutdown_handler()


def test_worker_ready_bootstrap_and_process_resource_paths(monkeypatch):
    _configure_celery_environment(monkeypatch)
    from data_process import parse_tasks, worker

    monkeypatch.setattr(worker, "QUEUES", "parse_q")
    monkeypatch.setattr(worker, "DP_PARSE_MIN_PROCESSES", 2)
    monkeypatch.setattr(worker, "DP_PRELOAD_MODELS", "unstructured_default")
    bootstrap_calls = []
    monkeypatch.setattr(parse_tasks.parser_bootstrap, "apply_async", lambda **kwargs: bootstrap_calls.append(kwargs))
    worker.worker_ready_handler()
    assert len(bootstrap_calls) == 2 and all(call["queue"] == "parse_q" for call in bootstrap_calls)

    monitoring = types.ModuleType("utils.monitoring")
    monitoring.monitoring_manager = types.SimpleNamespace(is_enabled=True)
    monkeypatch.setitem(sys.modules, "utils.monitoring", monitoring)
    worker.setup_worker_process_resources()
    monkeypatch.setitem(sys.modules, "utils.monitoring", None)
    worker.setup_worker_process_resources()

    worker.worker_state["start_time"] = 0
    worker.worker_state["process_id"] = 1
    worker.worker_shutdown_handler()


def test_worker_redis_validation_and_startup_error_paths(monkeypatch):
    _configure_celery_environment(monkeypatch)
    from data_process import worker

    monkeypatch.setattr(worker, "QUEUES", "forward_q")

    class InterruptApp:
        conf = types.SimpleNamespace(broker_url="broker", result_backend="backend")

        def worker_main(self, _args):
            raise KeyboardInterrupt

    monkeypatch.setattr(worker, "app", InterruptApp())
    monkeypatch.setattr(worker.sys, "exit", lambda code: None)
    monkeypatch.setattr(worker, "_validate_parser_config", lambda: None)
    worker.start_worker()

    class ErrorApp(InterruptApp):
        def worker_main(self, _args):
            raise RuntimeError("startup failed")

    monkeypatch.setattr(worker, "app", ErrorApp())
    worker.start_worker()


def test_parse_storage_lifecycle_bootstrap_and_aggregation_error_paths(parser_runtime, monkeypatch):
    from data_process import parse_tasks

    class Client:
        def __init__(self, value=None, ready_count=1):
            self.value = value
            self.ready_count = ready_count
            self.calls = []

        def set(self, *args, **kwargs):
            self.calls.append(("set", args, kwargs))

        def get(self, key):
            self.calls.append(("get", key))
            return self.value

        def rename(self, *args):
            self.calls.append(("rename", args))

        def delete(self, *args):
            self.calls.append(("delete", args))

        def sadd(self, *args):
            self.calls.append(("sadd", args))

        def expire(self, *args):
            self.calls.append(("expire", args))

        def scard(self, _key):
            return self.ready_count

    client = Client(json.dumps({"wrong": "shape"}))
    monkeypatch.setattr(parse_tasks, "_redis_client", lambda: client)
    parse_tasks.store_chunks_atomically("chunks", [{"content": "x"}])
    assert any(call[0] == "set" for call in client.calls)
    assert not any(call[0] == "rename" for call in client.calls)
    assert parse_tasks.load_chunks_from_redis("wrong-shape") == {"wrong": "shape"}
    client.value = "not-json"
    with pytest.raises(json.JSONDecodeError):
        parse_tasks.load_chunks_from_redis("bad")
    client.value = None
    assert parse_tasks.load_chunks_from_redis("missing") == []

    import database.attachment_db as attachment
    monkeypatch.setattr(attachment, "delete_file", lambda _uri: (_ for _ in ()).throw(RuntimeError("delete failed")))
    parse_tasks.cleanup_parser_artifacts("task", [{"part_index": 1, "uri": "s3://part"}], include_final=False)
    parse_tasks.cleanup_parser_artifacts("task", None, include_final=True)

    runtime = types.SimpleNamespace(preload_models=["unstructured_default"])
    monkeypatch.setattr(parse_tasks, "ensure_parser_runtime", lambda: runtime)
    parse_tasks.parser_bootstrap.push_request(id="bootstrap")
    try:
        result = parse_tasks.parser_bootstrap.run("generation", 1)
    finally:
        parse_tasks.parser_bootstrap.pop_request()
    assert result["ready"] is True

    bad_result = {"part_index": 0, "part_redis_key": "part"}
    monkeypatch.setattr(parse_tasks, "load_chunks_from_redis", lambda _key: [])
    monkeypatch.setattr(parse_tasks, "cleanup_parser_artifacts", lambda *args, **kwargs: None)
    parse_tasks.aggregate_store_chunks.push_request(id="aggregate-error")
    try:
        with pytest.raises(Exception, match="produced 0 chunks"):
            parse_tasks.aggregate_store_chunks.run([bad_result], "final", source="source", index_name="idx")
    finally:
        parse_tasks.aggregate_store_chunks.pop_request()

    assert not hasattr(parse_tasks, "aggregate_parts")


def test_parse_bootstrap_timeout_and_process_split_path(parser_runtime, monkeypatch):
    from data_process import parse_tasks

    client = types.SimpleNamespace(
        sadd=lambda *args: None,
        expire=lambda *args: None,
        scard=lambda _key: 0,
        set=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(parse_tasks, "_redis_client", lambda: client)
    monkeypatch.setattr(parse_tasks, "DP_REDIS_CHUNKS_WAIT_TIMEOUT_S", 0)
    monkeypatch.setattr(parse_tasks, "ensure_parser_runtime", lambda: types.SimpleNamespace(preload_models=[]))
    parse_tasks.parser_bootstrap.push_request(id="bootstrap-timeout")
    try:
        with pytest.raises(TimeoutError, match="timed out"):
            parse_tasks.parser_bootstrap.run("generation", 2)
    finally:
        parse_tasks.parser_bootstrap.pop_request()

    runtime = types.SimpleNamespace(
        read_source=lambda source, source_type: b"large",
        split_source=lambda **kwargs: [b"a", b"b"],
        process_source=lambda **kwargs: [{"content": "fallback"}],
    )
    monkeypatch.setattr(parse_tasks, "get_parser_runtime", lambda: runtime)
    monkeypatch.setattr(parse_tasks, "DP_FILE_SPLIT_SIZE_MB", 0)
    monkeypatch.setattr(parse_tasks, "DP_PART_PROCESSOR_COUNT", 2)
    monkeypatch.setattr(parse_tasks, "_upload_part", lambda task_id, index, filename, data: {"uri": f"s3://{index}", "part_index": index})
    replaced = []
    parse_tasks.process.push_request(id="split")
    try:
        parse_tasks.process.replace = lambda signature: replaced.append(signature) or "replaced"
        result = parse_tasks.process.run("source", "local", index_name="idx", original_filename="file.txt")
    finally:
        parse_tasks.process.pop_request()
    assert result == "replaced" and replaced

    monkeypatch.setattr(parse_tasks, "DP_PART_PROCESSOR_COUNT", 1)
    monkeypatch.setattr(parse_tasks, "store_chunks_atomically", lambda *args: None)
    parse_tasks.process_sync.push_request(id="sync-error")
    try:
        monkeypatch.setattr(runtime, "process_source", lambda **kwargs: [])
        with pytest.raises(Exception, match="produced 0 chunks"):
            parse_tasks.process_sync.run("source", "local")
    finally:
        parse_tasks.process_sync.pop_request()


def test_task_base_helpers_lifecycle_and_batch_edge_cases(tasks, monkeypatch):
    base = tasks.LoggingTask()
    assert base.on_success("ok", "task", (), {}) is None
    assert base.on_failure(RuntimeError("bad"), "task", (), {}, None) is None
    assert base.on_retry(RuntimeError("retry"), "task", (), {}, None) is None

    assert tasks._get_next_available_batch_index([[1], []], 0, 1) == 1
    with pytest.raises(RuntimeError, match="No available"):
        tasks._get_next_available_batch_index([[1], [2]], 0, 1)
    assert tasks._build_balanced_batches([{"process_source": "UniversalImageExtractor"}] * 64, batch_size=64)[0]
    assert tasks._redis_error_reason(types.SimpleNamespace(error_code=None, error_message="x" * 205)).endswith("...")

    lifecycle_calls = []
    lifecycle = types.ModuleType("database.knowledge_file_lifecycle_db")
    lifecycle.get_file_record = lambda **kwargs: (
        {"file_id": "record", "status": "PROCESSING"} if kwargs.get("object_name") else None
    )
    lifecycle.transition_file_record = lambda file_id, **kwargs: lifecycle_calls.append((file_id, kwargs))
    monkeypatch.setitem(sys.modules, "database.knowledge_file_lifecycle_db", lifecycle)
    tasks._update_file_lifecycle(
        file_id="missing", tenant_id="tenant", index_name="idx", source="source", status="FAILED", stage="PROCESS"
    )
    assert lifecycle_calls and lifecycle_calls[0][0] == "record"
    lifecycle.get_file_record = lambda **kwargs: {"file_id": "record", "status": "DELETED"}
    tasks._update_file_lifecycle(
        file_id="record", tenant_id="tenant", index_name="idx", source="source", status="FAILED", stage="PROCESS"
    )
    lifecycle.transition_file_record = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db down"))
    lifecycle.get_file_record = lambda **kwargs: {"file_id": "record", "status": "PROCESSING"}
    tasks._update_file_lifecycle(
        file_id="record", tenant_id="tenant", index_name="idx", source="source", status="FAILED", stage="PROCESS"
    )


def test_parse_task_hooks_and_low_level_failure_branches(parser_runtime, monkeypatch):
    import data_process.tasks as tasks_module
    from data_process import parse_tasks

    monkeypatch.setattr(parse_tasks, "REDIS_BACKEND_URL", None)
    with pytest.raises(RuntimeError, match="REDIS_BACKEND_URL"):
        parse_tasks._redis_client()

    import database.attachment_db as attachment
    monkeypatch.setattr(attachment, "upload_fileobj", lambda **kwargs: {"success": False, "error": "quota"})
    with pytest.raises(RuntimeError, match="Failed to upload"):
        parse_tasks._upload_part("task", 0, "file.txt", b"x")

    client = types.SimpleNamespace(delete=lambda *args: None)
    monkeypatch.setattr(parse_tasks, "_redis_client", lambda: client)
    monkeypatch.setattr(parse_tasks, "load_chunks_from_redis", lambda _key: [{"content": "loaded"}])
    stored = []
    monkeypatch.setattr(parse_tasks, "store_chunks_atomically", lambda key, chunks: stored.append((key, chunks)))
    monkeypatch.setattr(parse_tasks, "ensure_document_not_deleted", lambda **_kwargs: None)
    parse_tasks.aggregate_store_chunks.push_request(id="parts")
    try:
        result = parse_tasks.aggregate_store_chunks.run(
            [{"part_redis_key": "part", "part_index": 0}], "explicit", source="source", index_name="idx"
        )
    finally:
        parse_tasks.aggregate_store_chunks.pop_request()
    assert result["chunks_count"] == 1 and stored

    monkeypatch.setattr(parse_tasks, "get_parser_runtime", lambda: (_ for _ in ()).throw(RuntimeError("parse")))
    monkeypatch.setattr(parse_tasks, "cleanup_parser_artifacts", lambda *args, **kwargs: None)
    monkeypatch.setattr(tasks_module, "save_error_to_redis", lambda *args: (_ for _ in ()).throw(RuntimeError("redis")))
    parse_tasks.process_part.push_request(id="part-failure")
    try:
        with pytest.raises(RuntimeError, match="parse"):
            parse_tasks.process_part.run(
                {"uri": "s3://part", "part_index": 0}, "file.txt", "basic", "part-key", parser_task_id="parent"
            )
    finally:
        parse_tasks.process_part.pop_request()

    runtime = types.SimpleNamespace(
        read_source=lambda source, source_type: b"data",
        process_source=lambda **kwargs: (_ for _ in ()).throw(Exception(json.dumps({"message": "bad", "error_code": "E"}))),
        preload_models=[],
    )
    monkeypatch.setattr(parse_tasks, "get_parser_runtime", lambda: runtime)
    monkeypatch.setattr(parse_tasks, "cleanup_parser_artifacts", lambda *args, **kwargs: None)
    parse_tasks.process.push_request(id="process-json-error")
    try:
        with pytest.raises(Exception, match='"error_code": "E"'):
            parse_tasks.process.run("source", "local", index_name="idx")
    finally:
        parse_tasks.process.pop_request()


def test_load_forward_retry_and_http_connection_paths(tasks, monkeypatch):
    from celery.exceptions import Retry

    class RetrySelf(FakeSelf):
        def retry(self, **kwargs):
            raise Retry("retry")

    fake = RetrySelf("retry-task")
    redis_module = types.ModuleType("redis")

    class Client:
        def __init__(self, values):
            self.values = values

        def get(self, key):
            return self.values.get(key)

    redis_module.Redis = types.SimpleNamespace(from_url=lambda *args, **kwargs: Client({"key:ready": None, "key": None}))
    monkeypatch.setitem(sys.modules, "redis", redis_module)
    with pytest.raises(Retry):
        tasks._load_forward_chunks(
            fake, processed_data={"redis_key": "key", "split_async": True}, original_source="source", original_index_name="idx", filename=None
        )
    redis_module.Redis = types.SimpleNamespace(from_url=lambda *args, **kwargs: Client({"key:ready": "1", "key": None}))
    with pytest.raises(Retry):
        tasks._load_forward_chunks(
            fake, processed_data={"redis_key": "key", "split_async": True}, original_source="source", original_index_name="idx", filename=None
        )
    redis_module.Redis = types.SimpleNamespace(from_url=lambda *args, **kwargs: Client({"key": "[]"}))
    with pytest.raises(Retry):
        tasks._load_forward_chunks(
            fake, processed_data={"redis_key": "key", "split_async": True}, original_source="source", original_index_name="idx", filename=None
        )

    class ConnectError(Exception):
        pass

    class Response:
        status = 200

        async def __aenter__(self):
            raise ConnectError("connection refused")

        async def __aexit__(self, *args):
            return False

        async def text(self):
            return ""

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(tasks, "ELASTICSEARCH_SERVICE", "http://es")
    monkeypatch.setattr(tasks.aiohttp, "ClientConnectorError", ConnectError)
    monkeypatch.setattr(tasks.aiohttp, "ClientSession", lambda **kwargs: Session())
    with pytest.raises(Exception, match="Failed to connect"):
        tasks._send_chunks_to_es([], "idx", None)


def test_forward_part_failures_and_large_batch_forward(tasks, monkeypatch):
    from celery.exceptions import Retry

    monkeypatch.setattr(tasks, "_load_forward_batch", lambda _key: [{"content": "x"}])
    monkeypatch.setattr(tasks, "ensure_document_not_deleted", lambda **_kwargs: None)
    monkeypatch.setattr(tasks, "_send_chunks_to_es", lambda **kwargs: {"success": True, "total_indexed": 1, "total_submitted": 1})
    no_parent = tasks.forward_part.run("batch-key", "idx")
    assert no_parent["total_indexed"] == 1

    monkeypatch.setattr(tasks, "_send_chunks_to_es", lambda **kwargs: (_ for _ in ()).throw(
        Exception(json.dumps({"error_code": "es_bulk_failed", "message": "bulk"}))
    ))
    cancelled = []
    monkeypatch.setattr(tasks, "get_redis_service", lambda: types.SimpleNamespace(mark_task_cancelled=lambda task_id: cancelled.append(task_id)))
    tasks.forward_part.push_request(id="nonretry", retries=0)
    try:
        with pytest.raises(Exception, match="bulk"):
            tasks.forward_part.run("batch-key", "idx", parent_task_id="parent")
    finally:
        tasks.forward_part.pop_request()
    assert cancelled == ["parent"]

    monkeypatch.setattr(tasks, "_send_chunks_to_es", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("temporary")))
    monkeypatch.setattr(tasks.forward_part, "retry", lambda **kwargs: (_ for _ in ()).throw(Retry("retry")))
    tasks.forward_part.push_request(id="retry", retries=1)
    try:
        with pytest.raises(Retry):
            tasks.forward_part.run("batch-key", "idx", parent_task_id=None)
    finally:
        tasks.forward_part.pop_request()

    chunks = [{"content": f"chunk-{index}"} for index in range(tasks.FORWARD_ES_CHUNK_BATCH_SIZE + 1)]
    monkeypatch.setattr(tasks, "_update_file_lifecycle", lambda **kwargs: None)
    monkeypatch.setattr(tasks, "get_file_size", lambda *args: 1)
    monkeypatch.setattr(tasks, "get_redis_service", lambda: types.SimpleNamespace(save_progress_info=lambda *args: None))
    monkeypatch.setattr(tasks, "_store_forward_batch", lambda task_id, batch_index, batch: f"batch-{batch_index}")
    monkeypatch.setattr(tasks, "group", lambda signatures: list(signatures))
    monkeypatch.setattr(tasks, "chord", lambda signatures: lambda callback: types.SimpleNamespace(
        get=lambda: {"success": True, "total_indexed": len(chunks), "total_submitted": len(chunks)}
    ))
    tasks.forward.push_request(id="large")
    try:
        large_result = tasks.forward.run({"chunks": chunks}, index_name="idx", source="source", source_type="local")
    finally:
        tasks.forward.pop_request()
    assert large_result["chunks_stored"] == len(chunks)


def test_forward_result_errors_cleanup_and_chain_fallbacks(tasks, monkeypatch):
    monkeypatch.setattr(tasks, "_update_file_lifecycle", lambda **kwargs: None)
    monkeypatch.setattr(tasks, "_is_forward_task_cancelled", lambda _ctx: False)
    monkeypatch.setattr(tasks, "get_file_size", lambda *args: 1)
    monkeypatch.setattr(tasks, "get_redis_service", lambda: types.SimpleNamespace(save_progress_info=lambda *args: None))
    monkeypatch.setattr(tasks, "save_error_to_redis", lambda *args: None)
    for response, message in (({"success": False, "message": "gateway"}, "main_server API error"), (None, "Unexpected API response")):
        monkeypatch.setattr(tasks, "_send_chunks_to_es", lambda **kwargs: response)
        tasks.forward.push_request(id="response-error")
        try:
            with pytest.raises(Exception, match=message):
                tasks.forward.run({"chunks": [{"content": "x"}]}, index_name="idx", source="source", source_type="local")
        finally:
            tasks.forward.pop_request()

    monkeypatch.setattr(tasks, "_send_chunks_to_es", lambda **kwargs: {"success": True, "total_indexed": 0, "total_submitted": 1})
    tasks.forward.push_request(id="partial")
    try:
        with pytest.raises(Exception, match="Failure reported"):
            tasks.forward.run({"chunks": [{"content": "x"}]}, index_name="idx", source="source", source_type="local")
    finally:
        tasks.forward.pop_request()

    monkeypatch.setattr(tasks, "get_knowledge_record", lambda _query: (_ for _ in ()).throw(RuntimeError("lookup")))
    lookup = tasks.cleanup_source.run({"index_name": "idx", "source": "source"})
    assert lookup["source_cleanup"]["skipped_reason"] == "knowledge_record_lookup_failed"
    monkeypatch.setattr(tasks, "get_knowledge_record", lambda _query: {"preserve_source_file": False})
    monkeypatch.setattr(tasks, "_delete_source_file_via_http_sync", lambda **kwargs: {"http_status": 400, "response_json": {"status": "error"}, "response_text": "bad"})
    failed_cleanup = tasks.cleanup_source.run({"index_name": "idx", "source": "source"})
    assert failed_cleanup["source_cleanup"]["success"] is False
    monkeypatch.setattr(tasks, "_delete_source_file_via_http_sync", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("delete")))
    errored_cleanup = tasks.cleanup_source.run({"index_name": "idx", "source": "source"})
    assert errored_cleanup["source_cleanup"]["success"] is False

    class Signature:
        def set(self, **kwargs):
            return self

    class Stub:
        def s(self, **kwargs):
            return Signature()

    class Chain:
        def apply_async(self):
            return None

    monkeypatch.setattr(tasks, "process", Stub())
    monkeypatch.setattr(tasks, "forward", Stub())
    monkeypatch.setattr(tasks, "cleanup_source", Stub())
    monkeypatch.setattr(tasks, "chain", lambda *args: Chain())
    assert tasks.submit_process_forward_chain(source="s", source_type="local", chunking_strategy="basic") == ""
    monkeypatch.setattr(tasks, "submit_process_forward_chain", lambda **kwargs: "")
    assert tasks.process_and_forward.run("s", "local", "basic") == ""


def test_parser_runtime_initialization_guards_and_source_error_paths(parser_runtime, monkeypatch):
    runtime = parser_runtime.ParserRuntime(2, [])
    runtime._core = types.SimpleNamespace()
    monkeypatch.setattr(runtime, "ensure_initialized", lambda: None)
    assert runtime.core is runtime._core

    failed = parser_runtime.ParserRuntime(1, [])
    monkeypatch.setattr(parser_runtime, "_configure_third_party_model_paths", lambda _paths: (_ for _ in ()).throw(ValueError("bad model path")))
    with pytest.raises(ValueError, match="bad model path"):
        failed.ensure_initialized()
    assert failed._core is None and failed.initialized is False

    model_db = types.ModuleType("database.model_management_db")
    model_db.get_model_by_model_id = lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("db unavailable"))
    monkeypatch.setitem(sys.modules, "database.model_management_db", model_db)
    runtime._initialized = True
    runtime._core = types.SimpleNamespace(file_process=lambda **_kwargs: ([{"content": "chunk"}], []))
    assert runtime.process_source(
        file_data=b"data", filename="file.txt", chunking_strategy="basic", model_id=1, tenant_id="tenant"
    ) == [{"content": "chunk"}]

    stream = io.BytesIO(b"minio-data")
    attachment = types.ModuleType("database.attachment_db")
    attachment.get_file_stream = lambda _source: stream
    monkeypatch.setitem(sys.modules, "database.attachment_db", attachment)
    assert parser_runtime.ParserRuntime.read_source("s3://object", "minio") == b"minio-data"
    assert stream.closed
    attachment.get_file_stream = lambda _source: None
    with pytest.raises(FileNotFoundError):
        parser_runtime.ParserRuntime.read_source("s3://missing", "minio")

    sentinel_runtime = types.SimpleNamespace(ensure_initialized=lambda: None)
    monkeypatch.setattr(parser_runtime, "get_parser_runtime", lambda: sentinel_runtime)
    assert parser_runtime.ensure_parser_runtime() is sentinel_runtime


def test_parser_task_low_level_redis_and_error_cleanup_paths(parser_runtime, monkeypatch):
    from data_process import parse_tasks

    redis_module = types.ModuleType("redis")
    redis_module.Redis = types.SimpleNamespace(from_url=lambda *args, **kwargs: (args, kwargs))
    monkeypatch.setitem(sys.modules, "redis", redis_module)
    client = parse_tasks._redis_client()
    assert client[0] == (parse_tasks.REDIS_BACKEND_URL,)
    assert client[1]["decode_responses"] is True

    monkeypatch.setattr(parse_tasks, "cleanup_parser_artifacts", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("cleanup")))
    tasks_module = sys.modules["data_process.tasks"]
    monkeypatch.setattr(tasks_module, "save_error_to_redis", lambda *args: (_ for _ in ()).throw(RuntimeError("redis")))
    parse_tasks.aggregate_store_chunks.push_request(id="aggregate-errors")
    try:
        with pytest.raises(RuntimeError, match="no Redis key"):
            parse_tasks.aggregate_store_chunks.run([{"part_index": 0}], "final", source="source", index_name="idx")
    finally:
        parse_tasks.aggregate_store_chunks.pop_request()

    runtime = types.SimpleNamespace(
        read_source=lambda *_args: b"data",
        process_source=lambda **_kwargs: [{"content": "x"}],
        split_source=lambda **_kwargs: [b"one", b"two"],
    )
    monkeypatch.setattr(parse_tasks, "get_parser_runtime", lambda: runtime)
    monkeypatch.setattr(parse_tasks, "cleanup_parser_artifacts", lambda *args, **kwargs: None)
    parse_tasks.process.push_request(id="process-error")
    try:
        with pytest.raises(Exception, match="read failed"):
            monkeypatch.setattr(runtime, "read_source", lambda *_args: (_ for _ in ()).throw(RuntimeError("read failed")))
            parse_tasks.process.run("source", "local", index_name="idx")
    finally:
        parse_tasks.process.pop_request()

    monkeypatch.setattr(parse_tasks, "get_parser_runtime", lambda: runtime)
    monkeypatch.setattr(runtime, "read_source", lambda *_args: b"data")
    monkeypatch.setattr(runtime, "split_source", lambda **_kwargs: [b"one", b"two"])
    monkeypatch.setattr(parse_tasks, "DP_FILE_SPLIT_SIZE_MB", 0)
    monkeypatch.setattr(parse_tasks, "DP_PART_PROCESSOR_COUNT", 2)
    monkeypatch.setattr(parse_tasks, "_upload_part", lambda *args: {"uri": "s3://part", "part_index": 0})
    monkeypatch.setattr(parse_tasks.process, "replace", lambda _signature: (_ for _ in ()).throw(parse_tasks.Ignore()))
    parse_tasks.process.push_request(id="process-ignore")
    try:
        with pytest.raises(parse_tasks.Ignore):
            parse_tasks.process.run("source", "local", index_name="idx")
    finally:
        parse_tasks.process.pop_request()


def test_parse_cancellation_and_cleanup_boundaries(parser_runtime, monkeypatch):
    """Cover cancellation boundaries without starting a worker or loading a model."""
    from data_process import parse_tasks

    class FailingRedis:
        def delete(self, *_keys):
            raise RuntimeError("redis unavailable")

    monkeypatch.setattr(parse_tasks, "_redis_client", lambda: FailingRedis())
    import database.attachment_db as attachment
    monkeypatch.setattr(attachment, "delete_file", lambda _uri: {"success": False, "error": "gone"})
    parse_tasks.cleanup_parser_artifacts(
        "cleanup", [{"part_index": 0, "uri": "s3://part"}], include_final=True
    )

    monkeypatch.setitem(sys.modules, "database.attachment_db", None)
    parse_tasks.cleanup_parser_artifacts("missing-attachment", None, include_final=False)
    monkeypatch.setitem(sys.modules, "database.attachment_db", attachment)

    cleanup_calls = []
    monkeypatch.setattr(parse_tasks, "cleanup_parser_artifacts", lambda *args, **kwargs: cleanup_calls.append((args, kwargs)))
    parse_tasks.cleanup_failed_parser_parts(
        None, RuntimeError("chord"), None, task_id="failed", part_refs=[{"part_index": 0}]
    )
    assert cleanup_calls[-1][1]["include_final"] is True

    cancelled = parse_tasks._build_process_cancelled_result(
        task_id="cancelled", source="source", index_name="idx", original_filename="file.txt", file_id="fid"
    )
    assert cancelled["cancelled"] is True

    class BootstrapRedis:
        def __init__(self):
            self.counts = iter((0, 1))

        def sadd(self, *_args):
            return 1

        def expire(self, *_args):
            return True

        def scard(self, _key):
            return next(self.counts)

        def set(self, *_args, **_kwargs):
            return True

    bootstrap_client = BootstrapRedis()
    monkeypatch.setattr(parse_tasks, "_redis_client", lambda: bootstrap_client)
    monkeypatch.setattr(parse_tasks, "DP_REDIS_CHUNKS_WAIT_TIMEOUT_S", 1)
    clock = iter((0, 0)).__next__
    monkeypatch.setattr(parse_tasks.time, "time", clock)
    monkeypatch.setattr(parse_tasks.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(parse_tasks, "ensure_parser_runtime", lambda: types.SimpleNamespace(preload_models=[]))
    parse_tasks.parser_bootstrap.push_request(id="bootstrap-sleep")
    try:
        assert parse_tasks.parser_bootstrap.run("generation", 1)["ready"] is True
    finally:
        parse_tasks.parser_bootstrap.pop_request()

    monkeypatch.setattr(
        parse_tasks,
        "ensure_document_not_deleted",
        lambda **_kwargs: (_ for _ in ()).throw(parse_tasks.DocumentDeleteRequested("deleted")),
    )
    parse_tasks.process_part.push_request(id="part-cancelled")
    try:
        part_result = parse_tasks.process_part.run(
            {"uri": "s3://part", "part_index": 0}, "file.txt", "basic", "part-key", parser_task_id="parent"
        )
    finally:
        parse_tasks.process_part.pop_request()
    assert part_result["cancelled"] is True

    aggregate_cleanup = []
    monkeypatch.setattr(parse_tasks, "cleanup_parser_artifacts", lambda *args, **kwargs: aggregate_cleanup.append(kwargs))
    monkeypatch.setattr(parse_tasks, "ensure_document_not_deleted", lambda **_kwargs: None)
    parse_tasks.aggregate_store_chunks.push_request(id="aggregate-cancelled")
    try:
        result = parse_tasks.aggregate_store_chunks.run(
            [{"part_redis_key": "part-key", "part_index": 0, "cancelled": True}],
            "final-key",
            source="source",
            index_name="idx",
            task_id="aggregate-cancelled",
        )
    finally:
        parse_tasks.aggregate_store_chunks.pop_request()
    assert result["cancelled"] is True and aggregate_cleanup[-1]["include_final"] is True

    monkeypatch.setattr(parse_tasks, "is_document_delete_requested", lambda **_kwargs: True)
    parse_tasks.process.push_request(id="process-pre-cancel")
    try:
        assert parse_tasks.process.run("source", "local", index_name="idx")["cancelled"] is True
    finally:
        parse_tasks.process.pop_request()

    runtime = types.SimpleNamespace(
        read_source=lambda *_args: b"data",
        process_source=lambda **_kwargs: [{"content": "chunk"}],
    )
    monkeypatch.setattr(parse_tasks, "is_document_delete_requested", lambda **_kwargs: False)
    monkeypatch.setattr(parse_tasks, "get_parser_runtime", lambda: runtime)
    monkeypatch.setattr(parse_tasks, "update_file_lifecycle", lambda **_kwargs: None)
    monkeypatch.setattr(
        parse_tasks,
        "ensure_document_not_deleted",
        lambda **_kwargs: (_ for _ in ()).throw(parse_tasks.DocumentDeleteRequested("deleted")),
    )
    post_cleanup = []
    monkeypatch.setattr(parse_tasks, "cleanup_parser_artifacts", lambda *args, **kwargs: post_cleanup.append(kwargs))
    parse_tasks.process.push_request(id="process-post-cancel")
    try:
        assert parse_tasks.process.run("source", "local", index_name="idx")["cancelled"] is True
    finally:
        parse_tasks.process.pop_request()
    assert post_cleanup


def test_worker_exception_paths_and_prefork_runtime_processor_lazy_loading(monkeypatch):
    _configure_celery_environment(monkeypatch)
    from data_process import parse_tasks, worker

    monkeypatch.setattr(worker, "QUEUES", "parse_q")
    monkeypatch.setattr(parse_tasks.parser_bootstrap, "apply_async", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("dispatch")))
    worker.worker_ready_handler()

    monkeypatch.setitem(sys.modules, "utils.monitoring", None)
    monkeypatch.setattr(worker, "QUEUES", "forward_q")
    monkeypatch.setattr(worker, "app", types.SimpleNamespace(worker_main=lambda _args: None))
    monkeypatch.setattr(worker, "_validate_parser_config", lambda: None)
    worker.start_worker()

    from nexent.data_process.core import DataProcessCore

    core = DataProcessCore()
    fake_classes = {
        "unstructured_processor": ("UnstructuredProcessor",),
        "openpyxl_processor": ("OpenPyxlProcessor",),
        "extract_image": ("UniversalImageExtractor",),
        "file_splitter": ("FileSplitter",),
    }
    for module_name, class_names in fake_classes.items():
        module = types.ModuleType(f"nexent.data_process.{module_name}")
        for class_name in class_names:
            setattr(module, class_name, type(class_name, (), {}))
        monkeypatch.setitem(sys.modules, f"nexent.data_process.{module_name}", module)
    for name in ("Unstructured", "OpenPyxl", "UniversalImageExtractor", "FileSplitter"):
        assert core._load_processor(name).__class__.__name__ in {"UnstructuredProcessor", "OpenPyxlProcessor", "UniversalImageExtractor", "FileSplitter"}
    with pytest.raises(ValueError, match="Unsupported processor"):
        core._load_processor("unknown")
    assert core._get_processor("Unstructured") is core.processors["Unstructured"]
    core.model_registry.model_paths = {"unstructured_default": "model.json", "table_transformer": "table"}
    ensured = []
    monkeypatch.setattr(core, "ensure_model", lambda alias: ensured.append(alias))
    core.processors["UniversalImageExtractor"] = types.SimpleNamespace(process_file=lambda *args, **kwargs: [])
    core.processors["Unstructured"] = types.SimpleNamespace(process_file=lambda *args, **kwargs: [{"content": "ok"}])
    assert core.file_process(b"data", "file.pdf", model_type="multi_embedding")[0]
    assert ensured == ["unstructured_default", "unstructured_default", "table_transformer"]
    assert core.preload_models([]) == {}
    core.ensure_model("missing")
    assert ensured[-1] == "missing"
