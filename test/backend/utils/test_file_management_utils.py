import sys
import types
from typing import Any, Dict, Optional

import pytest


class _ProcessParams:
    def __init__(self, authorization: str, source_type: str, chunking_strategy: str, index_name: Optional[str]):
        self.authorization = authorization
        self.source_type = source_type
        self.chunking_strategy = chunking_strategy
        self.index_name = index_name


@pytest.fixture(autouse=True)
def stub_project_modules(monkeypatch):
    # consts.const
    const_mod = types.ModuleType("consts.const")
    setattr(const_mod, "DATA_PROCESS_SERVICE", "http://data-process")
    sys.modules["consts.const"] = const_mod

    # consts.model
    model_mod = types.ModuleType("consts.model")
    setattr(model_mod, "ProcessParams", _ProcessParams)
    sys.modules["consts.model"] = model_mod

    # database.attachment_db
    attach_mod = types.ModuleType("database.attachment_db")
    setattr(attach_mod, "get_file_size_from_minio", lambda object_name, bucket=None: 777)
    sys.modules["database.attachment_db"] = attach_mod

    # Ensure parent package exists
    if "database" not in sys.modules:
        pkg = types.ModuleType("database")
        setattr(pkg, "__path__", [])
        sys.modules["database"] = pkg
    setattr(sys.modules["database"], "attachment_db", attach_mod)

    # utils.auth_utils
    auth_mod = types.ModuleType("utils.auth_utils")
    setattr(auth_mod, "get_current_user_id", lambda authorization: ("user-1", "tenant-1"))
    sys.modules["utils.auth_utils"] = auth_mod

    # utils.config_utils
    cfg_mod = types.ModuleType("utils.config_utils")
    cfg_mgr = types.SimpleNamespace(load_config=lambda tenant_id: {"EMBEDDING_ID": "42"})
    setattr(cfg_mod, "tenant_config_manager", cfg_mgr)
    sys.modules["utils.config_utils"] = cfg_mod

    # Yield to tests
    yield


@pytest.fixture()
def fmu(monkeypatch):
    # Import after stubbing collaborators
    from backend.utils import file_management_utils as fmu
    return fmu


# -------------------- save_upload_file --------------------


@pytest.mark.asyncio
async def test_save_upload_file_success(tmp_path, fmu, monkeypatch):
    written: Dict[str, bytes] = {}

    class _FakeFile:
        async def read(self) -> bytes:
            return b"hello"

    class _FakeAIOOpen:
        def __init__(self, path, mode):
            self.path = str(path)
            self.mode = mode

        async def __aenter__(self):
            class _Writer:
                async def write(_, b: bytes):  # noqa: N803
                    written[self.path] = b

            return _Writer()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    fake_aiofiles = types.SimpleNamespace(open=_FakeAIOOpen)
    monkeypatch.setattr(fmu, "aiofiles", fake_aiofiles)

    ok = await fmu.save_upload_file(_FakeFile(), tmp_path / "x.bin")
    assert ok is True
    assert written[str(tmp_path / "x.bin")] == b"hello"


@pytest.mark.asyncio
async def test_save_upload_file_error(tmp_path, fmu, monkeypatch):
    class _ErrOpen:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            raise RuntimeError("fail")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(fmu, "aiofiles", types.SimpleNamespace(open=_ErrOpen))

    class _FakeFile:
        filename = "x.bin"
        async def read(self) -> bytes:
            return b"data"

    ok = await fmu.save_upload_file(_FakeFile(), tmp_path / "x.bin")
    assert ok is False


# -------------------- trigger_data_process --------------------


class _Resp:
    def __init__(self, status_code: int, body: Any = None, text: str = ""):
        self.status_code = status_code
        self._body = body
        self.text = text

    def json(self):
        return self._body


class _FakeRequestError(Exception):
    pass


class _FakeAsyncClient:
    def __init__(self, resp: _Resp = _Resp(201, {"ok": True})):
        self._resp = resp
        self.last_post: Dict[str, Any] = {}
        self.last_get: Dict[str, Any] = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url: str, headers: Dict[str, str], json: Dict[str, Any], timeout: float):
        self.last_post = {"url": url, "headers": headers, "json": json, "timeout": timeout}
        if isinstance(self._resp, Exception):
            raise self._resp
        return self._resp

    async def get(self, url: str, timeout: float):
        self.last_get = {"url": url, "timeout": timeout}
        if isinstance(self._resp, Exception):
            raise self._resp
        return self._resp


@pytest.mark.asyncio
async def test_trigger_data_process_empty_files_returns_none(fmu):
    params = _ProcessParams("tok", "local", "basic", "idx")
    out = await fmu.trigger_data_process([], params)
    assert out is None


@pytest.mark.asyncio
async def test_trigger_data_process_single_success_with_embedding(fmu, monkeypatch):
    fake_client = _FakeAsyncClient(_Resp(201, {"task_id": "t1"}))
    fake_httpx = types.SimpleNamespace(AsyncClient=lambda: fake_client, RequestError=_FakeRequestError)
    monkeypatch.setattr(fmu, "httpx", fake_httpx)

    params = _ProcessParams("tok", "local", "basic", "idx")
    files = [{"path_or_url": "/data/a.txt", "filename": "a.txt"}]
    out = await fmu.trigger_data_process(files, params)
    assert out == {"task_id": "t1"}
    assert fake_client.last_post["url"].endswith("/tasks")
    assert fake_client.last_post["headers"]["Authorization"] == "Bearer tok"
    assert fake_client.last_post["json"]["embedding_model_id"] == 42
    assert fake_client.last_post["json"]["tenant_id"] == "tenant-1"


@pytest.mark.asyncio
async def test_trigger_data_process_single_non201_error(fmu, monkeypatch):
    fake_client = _FakeAsyncClient(_Resp(400, None, text="boom"))
    fake_httpx = types.SimpleNamespace(AsyncClient=lambda: fake_client, RequestError=_FakeRequestError)
    monkeypatch.setattr(fmu, "httpx", fake_httpx)

    params = _ProcessParams("tok", "local", "basic", "idx")
    files = [{"path_or_url": "/data/a.txt", "filename": "a.txt"}]
    out = await fmu.trigger_data_process(files, params)
    assert out["status"] == "error" and out["code"] == 400


@pytest.mark.asyncio
async def test_trigger_data_process_single_request_error(fmu, monkeypatch):
    fake_client = _FakeAsyncClient(_FakeRequestError("net"))
    fake_httpx = types.SimpleNamespace(AsyncClient=lambda: fake_client, RequestError=_FakeRequestError)
    monkeypatch.setattr(fmu, "httpx", fake_httpx)

    params = _ProcessParams("tok", "local", "basic", "idx")
    files = [{"path_or_url": "/data/a.txt", "filename": "a.txt"}]
    out = await fmu.trigger_data_process(files, params)
    assert out["status"] == "error" and out["code"] == "CONNECTION_ERROR"


@pytest.mark.asyncio
async def test_trigger_data_process_batch_success(fmu, monkeypatch):
    fake_client = _FakeAsyncClient(_Resp(201, {"task_ids": ["t1", "t2"]}))
    fake_httpx = types.SimpleNamespace(AsyncClient=lambda: fake_client, RequestError=_FakeRequestError)
    monkeypatch.setattr(fmu, "httpx", fake_httpx)

    params = _ProcessParams("tok", "minio", "basic", "idx")
    files = [
        {"path_or_url": "/data/a.txt", "filename": "a.txt"},
        {"path_or_url": "/data/b.txt", "filename": "b.txt"},
    ]
    out = await fmu.trigger_data_process(files, params)
    assert out == {"task_ids": ["t1", "t2"]}
    assert fake_client.last_post["url"].endswith("/tasks/batch")
    assert len(fake_client.last_post["json"]["sources"]) == 2


@pytest.mark.asyncio
async def test_trigger_data_process_batch_non201_and_request_error(fmu, monkeypatch):
    # non-201
    fake_client1 = _FakeAsyncClient(_Resp(500, None, text="bad"))
    fake_httpx1 = types.SimpleNamespace(AsyncClient=lambda: fake_client1, RequestError=_FakeRequestError)
    monkeypatch.setattr(fmu, "httpx", fake_httpx1)
    params = _ProcessParams("tok", "minio", "basic", "idx")
    files = [
        {"path_or_url": "/a", "filename": "a"},
        {"path_or_url": "/b", "filename": "b"},
    ]
    out1 = await fmu.trigger_data_process(files, params)
    assert out1["status"] == "error" and out1["code"] == 500

    # request error
    fake_client2 = _FakeAsyncClient(_FakeRequestError("down"))
    fake_httpx2 = types.SimpleNamespace(AsyncClient=lambda: fake_client2, RequestError=_FakeRequestError)
    monkeypatch.setattr(fmu, "httpx", fake_httpx2)
    out2 = await fmu.trigger_data_process(files, params)
    assert out2["status"] == "error" and out2["code"] == "CONNECTION_ERROR"


# -------------------- get_all_files_status --------------------


@pytest.mark.asyncio
async def test_get_all_files_status_success_and_convert(fmu, monkeypatch):
    tasks_list = [
        {
            "id": "1",
            "task_name": "process",
            "index_name": "idx",
            "path_or_url": "/p1",
            "original_filename": "f1",
            "source_type": "local",
            "status": "SUCCESS",
            "created_at": 1,
        },
        {
            "id": "2",
            "task_name": "forward",
            "index_name": "idx",
            "path_or_url": "/p1",
            "original_filename": "f1",
            "source_type": "local",
            "status": "PENDING",
            "created_at": 2,
        },
    ]
    fake_client = _FakeAsyncClient(_Resp(200, tasks_list))
    monkeypatch.setattr(fmu, "httpx", types.SimpleNamespace(AsyncClient=lambda: fake_client))
    async def _fake_convert(process_celery_state, forward_celery_state):
        return "COMPLETED"
    monkeypatch.setattr(fmu, "_convert_to_custom_state", _fake_convert)

    out = await fmu.get_all_files_status("idx")
    assert "/p1" in out
    assert out["/p1"]["state"] == "COMPLETED"
    assert out["/p1"]["latest_task_id"] == "2"
    assert out["/p1"]["original_filename"] == "f1"
    assert out["/p1"]["source_type"] == "local"


@pytest.mark.asyncio
async def test_get_all_files_status_connect_error_and_non200(fmu, monkeypatch):
    # connect error
    fake_client_err = _FakeAsyncClient(Exception("down"))
    monkeypatch.setattr(fmu, "httpx", types.SimpleNamespace(AsyncClient=lambda: fake_client_err))
    out1 = await fmu.get_all_files_status("idx")
    assert out1 == {}

    # non-200
    fake_client = _FakeAsyncClient(_Resp(500, None, text="bad"))
    monkeypatch.setattr(fmu, "httpx", types.SimpleNamespace(AsyncClient=lambda: fake_client))
    out2 = await fmu.get_all_files_status("idx")
    assert out2 == {}


# -------------------- _convert_to_custom_state --------------------


@pytest.mark.asyncio
async def test_convert_to_custom_state_remote_success(fmu, monkeypatch):
    fake_client = _FakeAsyncClient(_Resp(200, {"state": "COMPLETED"}))
    monkeypatch.setattr(fmu, "httpx", types.SimpleNamespace(AsyncClient=lambda: fake_client))
    out = await fmu._convert_to_custom_state("SUCCESS", "SUCCESS")
    assert out == "COMPLETED"


@pytest.mark.asyncio
async def test_convert_to_custom_state_fallback_mappings(fmu, monkeypatch):
    # non-200 triggers fallback
    fake_client = _FakeAsyncClient(_Resp(500, None))
    monkeypatch.setattr(fmu, "httpx", types.SimpleNamespace(AsyncClient=lambda: fake_client))

    # process failure
    assert (await fmu._convert_to_custom_state("FAILURE", "")) == "PROCESS_FAILED"
    # forward failure
    assert (await fmu._convert_to_custom_state("", "FAILURE")) == "FORWARD_FAILED"
    # both success
    assert (await fmu._convert_to_custom_state("SUCCESS", "SUCCESS")) == "COMPLETED"
    # both empty
    assert (await fmu._convert_to_custom_state("", "")) == "WAIT_FOR_PROCESSING"
    # forward-only mapping
    assert (await fmu._convert_to_custom_state("", "PENDING")) == "WAIT_FOR_FORWARDING"
    assert (await fmu._convert_to_custom_state("", "STARTED")) == "FORWARDING"
    assert (await fmu._convert_to_custom_state("", "SUCCESS")) == "COMPLETED"
    assert (await fmu._convert_to_custom_state("", "X")) == "WAIT_FOR_FORWARDING"
    # process-only mapping
    assert (await fmu._convert_to_custom_state("PENDING", "")) == "WAIT_FOR_PROCESSING"
    assert (await fmu._convert_to_custom_state("STARTED", "")) == "PROCESSING"
    assert (await fmu._convert_to_custom_state("SUCCESS", "")) == "WAIT_FOR_FORWARDING"
    assert (await fmu._convert_to_custom_state("Y", "")) == "WAIT_FOR_PROCESSING"


# -------------------- get_file_size --------------------


def test_get_file_size_minio_ok_and_request_error(fmu, monkeypatch):
    # ok
    assert fmu.get_file_size("minio", "obj") == 777

    # request exception path
    class _ReqExc(Exception):
        pass

    fake_requests = types.SimpleNamespace(exceptions=types.SimpleNamespace(RequestException=_ReqExc))
    monkeypatch.setattr(fmu, "requests", fake_requests)

    def raise_req(*a, **k):
        raise _ReqExc("x")

    monkeypatch.setattr(fmu, "get_file_size_from_minio", raise_req)
    assert fmu.get_file_size("minio", "obj") == 0


def test_get_file_size_local_exists_missing_and_error(fmu, monkeypatch):
    monkeypatch.setattr(fmu.os.path, "exists", lambda p: True)
    monkeypatch.setattr(fmu.os.path, "getsize", lambda p: 1234)
    assert fmu.get_file_size("local", "/tmp/x") == 1234

    monkeypatch.setattr(fmu.os.path, "exists", lambda p: False)
    assert fmu.get_file_size("local", "/tmp/x") == 0

    def boom(p):
        raise RuntimeError("e")

    monkeypatch.setattr(fmu.os.path, "exists", lambda p: True)
    monkeypatch.setattr(fmu.os.path, "getsize", boom)
    assert fmu.get_file_size("local", "/tmp/x") == 0


def test_get_file_size_invalid_source_type(fmu):
    # Function catches NotImplementedError and returns 0
    assert fmu.get_file_size("http", "http://x") == 0


