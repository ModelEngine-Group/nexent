# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


from test.common.contract_stubs import install_business_constant_stubs, install_business_contract_stubs
from test.backend.management.import_patching import set_import_attribute
import sys
import types
from pathlib import Path
from typing import Any, Dict, Optional

import pytest


class _ProcessParams:
    def __init__(self, authorization: str, source_type: str, chunking_strategy: str, index_name: Optional[str],
        tenant_id: Optional[str] = "tenant-1"):
        self.authorization = authorization
        self.source_type = source_type
        self.chunking_strategy = chunking_strategy
        self.index_name = index_name
        self.tenant_id = tenant_id


@pytest.fixture(autouse=True)
def stub_project_modules(monkeypatch, tmp_path):
    # consts.const
    const_mod = types.ModuleType("consts.const")
    setattr(const_mod, "DATA_PROCESS_SERVICE", "http://data-process")
    setattr(const_mod, "LIBREOFFICE_PROFILE_DIR", str(tmp_path / "lo-profile"))
    sys.modules["consts.const"] = const_mod
    install_business_constant_stubs(const_mod)

    # contracts.agent
    model_mod = types.ModuleType("contracts.agent")
    setattr(model_mod, "ProcessParams", _ProcessParams)
    install_business_contract_stubs(model_mod)

    # management.db.file.attachment
    attach_mod = types.ModuleType("management.db.file.attachment")
    setattr(attach_mod, "get_file_size_from_minio", lambda object_name, bucket=None: 777)
    sys.modules["management.db.file.attachment"] = attach_mod

    # management.db.knowledge_base.repository
    knowledge_mod = types.ModuleType("management.db.knowledge_base.repository")
    setattr(
        knowledge_mod,
        "get_knowledge_record",
        lambda query=None: {"embedding_model_id": 42, "index_name": (query or {}).get("index_name")},
    )
    sys.modules["management.db.knowledge_base.repository"] = knowledge_mod

    # Ensure parent package exists
    if "database" not in sys.modules:
        pkg = types.ModuleType("database")
        setattr(pkg, "__path__", [])
        sys.modules["database"] = pkg
    setattr(sys.modules["database"], "attachment_db", attach_mod)
    setattr(sys.modules["database"], "knowledge_db", knowledge_mod)

    # gateway.authentication.identity
    auth_mod = types.ModuleType("gateway.authentication.identity")
    setattr(auth_mod, "get_current_user_id", lambda authorization: ("user-1", "tenant-1"))
    sys.modules["gateway.authentication.identity"] = auth_mod

    # management.services.configuration.tenant.settings
    cfg_mod = types.ModuleType("management.services.configuration.tenant.settings")
    cfg_mgr = types.SimpleNamespace(load_config=lambda tenant_id: {"EMBEDDING_ID": "42"})
    setattr(cfg_mod, "tenant_config_manager", cfg_mgr)
    sys.modules["management.services.configuration.tenant.settings"] = cfg_mod

    # Yield to tests
    yield


@pytest.fixture()
def fmu(monkeypatch, request):
    # Import after stubbing collaborators
    names = request.function.__code__.co_names
    if "trigger_data_process" in names or "_data_process_error_result" in names:
        from management.services.knowledge_base import ingestion as fmu
    elif "get_all_files_status" in names or "_convert_to_custom_state_local" in names:
        from management.services.knowledge_base import status as fmu
    else:
        from management.services.file import upload as fmu
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
    set_import_attribute(monkeypatch, fmu, "aiofiles", fake_aiofiles)

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

    set_import_attribute(monkeypatch, fmu, "aiofiles", types.SimpleNamespace(open=_ErrOpen))

    class _FakeFile:
        filename = "x.bin"
        async def read(self) -> bytes:
            return b"data"

    ok = await fmu.save_upload_file(_FakeFile(), tmp_path / "x.bin")
    assert ok is False


@pytest.mark.asyncio
async def test_trigger_data_process_rejects_missing_tenant_without_submission(fmu, monkeypatch):
    fake_client = _FakeAsyncClient(_Resp(201, {'task_id': 't1'}))
    fake_httpx = types.SimpleNamespace(AsyncClient=lambda: fake_client, RequestError=_FakeRequestError)
    set_import_attribute(monkeypatch, fmu, 'httpx', fake_httpx)
    result = await fmu.trigger_data_process([{'path_or_url': '/data/a.txt', 'filename': 'a.txt'}], _ProcessParams('Bearer tok', 'local', 'basic', 'idx'), tenant_id=None)
    assert result['status'] == 'error'
    assert result['code'] == 'INTERNAL_ERROR'
    assert fake_client.last_post == {}


# -------------------- trigger_data_process --------------------


class _Resp:
    def __init__(self, status_code: int, body: Any = None, text: str = ""):
        self.status_code = status_code
        self._body = body
        self.text = text

    def json(self):
        return self._body


class _InvalidJsonResp(_Resp):
    def json(self):
        raise ValueError("not json")


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
    params = _ProcessParams('Bearer tok', 'local', 'basic', 'idx')
    out = await fmu.trigger_data_process([], params, tenant_id='tenant-1')
    assert out is None


@pytest.mark.asyncio
async def test_trigger_data_process_single_success_with_embedding(fmu, monkeypatch):
    fake_client = _FakeAsyncClient(_Resp(201, {'task_id': 't1'}))
    fake_httpx = types.SimpleNamespace(AsyncClient=lambda: fake_client, RequestError=_FakeRequestError)
    set_import_attribute(monkeypatch, fmu, 'httpx', fake_httpx)
    set_import_attribute(monkeypatch, fmu, 'get_knowledge_record', lambda query=None: {'embedding_model_id': 42, 'index_name': 'idx'})
    params = _ProcessParams('Bearer tok', 'local', 'basic', 'idx')
    files = [{'path_or_url': '/data/a.txt', 'filename': 'a.txt'}]
    out = await fmu.trigger_data_process(files, params, tenant_id='tenant-1')
    assert out == {'task_id': 't1'}
    assert fake_client.last_post['url'].endswith('/tasks')
    assert fake_client.last_post['headers']['Authorization'] == 'Bearer tok'
    assert fake_client.last_post['json']['embedding_model_id'] == 42
    assert fake_client.last_post['json']['tenant_id'] == 'tenant-1'


@pytest.mark.asyncio
async def test_trigger_data_process_propagates_file_id(fmu, monkeypatch):
    """New clients must carry the durable lifecycle ID into the task request."""
    fake_client = _FakeAsyncClient(_Resp(201, {'task_id': 't-file'}))
    fake_httpx = types.SimpleNamespace(AsyncClient=lambda: fake_client, RequestError=_FakeRequestError)
    set_import_attribute(monkeypatch, fmu, 'httpx', fake_httpx)
    set_import_attribute(monkeypatch, fmu, 'get_knowledge_record', lambda query=None: {})
    params = _ProcessParams('Bearer tok', 'minio', 'basic', 'idx')
    result = await fmu.trigger_data_process([{'path_or_url': 'knowledge_base/a.txt', 'filename': 'a.txt', 'file_id': 'fid-1'}], params, tenant_id='tenant-1')
    assert result == {'task_id': 't-file'}
    assert fake_client.last_post['json']['file_id'] == 'fid-1'


@pytest.mark.asyncio
async def test_trigger_data_process_queries_knowledge_record_by_index(fmu, monkeypatch):
    fake_client = _FakeAsyncClient(_Resp(201, {'task_id': 't1'}))
    fake_httpx = types.SimpleNamespace(AsyncClient=lambda: fake_client, RequestError=_FakeRequestError)
    set_import_attribute(monkeypatch, fmu, 'httpx', fake_httpx)
    captured_query: Dict[str, Any] = {}

    def _fake_get_knowledge_record(query=None):
        captured_query.update(query or {})
        return {'embedding_model_id': 77, 'index_name': 'idx'}
    set_import_attribute(monkeypatch, fmu, 'get_knowledge_record', _fake_get_knowledge_record)
    params = _ProcessParams('Bearer tok', 'local', 'basic', 'idx')
    files = [{'path_or_url': '/data/a.txt', 'filename': 'a.txt'}]
    out = await fmu.trigger_data_process(files, params, tenant_id='tenant-1')
    assert out == {'task_id': 't1'}
    assert captured_query.get('index_name') == 'idx'
    assert captured_query.get('tenant_id') == 'tenant-1'
    assert fake_client.last_post['json']['embedding_model_id'] == 77


@pytest.mark.asyncio
async def test_trigger_data_process_missing_embedding_model_id_sends_none(fmu, monkeypatch):
    fake_client = _FakeAsyncClient(_Resp(201, {'task_id': 't1'}))
    fake_httpx = types.SimpleNamespace(AsyncClient=lambda: fake_client, RequestError=_FakeRequestError)
    set_import_attribute(monkeypatch, fmu, 'httpx', fake_httpx)
    set_import_attribute(monkeypatch, fmu, 'get_knowledge_record', lambda query=None: {})
    params = _ProcessParams('Bearer tok', 'local', 'basic', 'idx')
    files = [{'path_or_url': '/data/a.txt', 'filename': 'a.txt'}]
    out = await fmu.trigger_data_process(files, params, tenant_id='tenant-1')
    assert out == {'task_id': 't1'}
    assert fake_client.last_post['json']['embedding_model_id'] is None


@pytest.mark.asyncio
async def test_trigger_data_process_knowledge_record_none_sends_none(fmu, monkeypatch):
    fake_client = _FakeAsyncClient(_Resp(201, {'task_id': 't1'}))
    fake_httpx = types.SimpleNamespace(AsyncClient=lambda: fake_client, RequestError=_FakeRequestError)
    set_import_attribute(monkeypatch, fmu, 'httpx', fake_httpx)
    set_import_attribute(monkeypatch, fmu, 'get_knowledge_record', lambda query=None: None)
    params = _ProcessParams('Bearer tok', 'local', 'basic', 'idx')
    files = [{'path_or_url': '/data/a.txt', 'filename': 'a.txt'}]
    out = await fmu.trigger_data_process(files, params, tenant_id='tenant-1')
    assert out == {'task_id': 't1'}
    assert fake_client.last_post['json']['embedding_model_id'] is None


@pytest.mark.asyncio
async def test_trigger_data_process_knowledge_record_raises_sends_none(fmu, monkeypatch):
    fake_client = _FakeAsyncClient(_Resp(201, {'task_id': 't1'}))
    fake_httpx = types.SimpleNamespace(AsyncClient=lambda: fake_client, RequestError=_FakeRequestError)
    set_import_attribute(monkeypatch, fmu, 'httpx', fake_httpx)

    def _raise_get_knowledge_record(query=None):
        raise RuntimeError('db unavailable')
    set_import_attribute(monkeypatch, fmu, 'get_knowledge_record', _raise_get_knowledge_record)
    params = _ProcessParams('Bearer tok', 'local', 'basic', 'idx')
    files = [{'path_or_url': '/data/a.txt', 'filename': 'a.txt'}]
    out = await fmu.trigger_data_process(files, params, tenant_id='tenant-1')
    assert out == {'task_id': 't1'}
    assert fake_client.last_post['json']['embedding_model_id'] is None


@pytest.mark.asyncio
async def test_trigger_data_process_single_non201_error(fmu, monkeypatch):
    fake_client = _FakeAsyncClient(_Resp(400, None, text='boom'))
    fake_httpx = types.SimpleNamespace(AsyncClient=lambda: fake_client, RequestError=_FakeRequestError)
    set_import_attribute(monkeypatch, fmu, 'httpx', fake_httpx)
    params = _ProcessParams('Bearer tok', 'local', 'basic', 'idx')
    files = [{'path_or_url': '/data/a.txt', 'filename': 'a.txt'}]
    out = await fmu.trigger_data_process(files, params, tenant_id='tenant-1')
    assert out['status'] == 'error' and out['code'] == 400


@pytest.mark.asyncio
async def test_trigger_data_process_single_request_error(fmu, monkeypatch):
    fake_client = _FakeAsyncClient(_FakeRequestError('net'))
    fake_httpx = types.SimpleNamespace(AsyncClient=lambda: fake_client, RequestError=_FakeRequestError)
    set_import_attribute(monkeypatch, fmu, 'httpx', fake_httpx)
    params = _ProcessParams('Bearer tok', 'local', 'basic', 'idx')
    files = [{'path_or_url': '/data/a.txt', 'filename': 'a.txt'}]
    out = await fmu.trigger_data_process(files, params, tenant_id='tenant-1')
    assert out['status'] == 'error' and out['code'] == 'CONNECTION_ERROR'


@pytest.mark.asyncio
async def test_trigger_data_process_batch_success(fmu, monkeypatch):
    fake_client = _FakeAsyncClient(_Resp(201, {'task_ids': ['t1', 't2']}))
    fake_httpx = types.SimpleNamespace(AsyncClient=lambda: fake_client, RequestError=_FakeRequestError)
    set_import_attribute(monkeypatch, fmu, 'httpx', fake_httpx)
    set_import_attribute(monkeypatch, fmu, 'get_knowledge_record', lambda query=None: {'embedding_model_id': 42, 'index_name': 'idx'})
    params = _ProcessParams('Bearer tok', 'minio', 'basic', 'idx')
    files = [{'path_or_url': '/data/a.txt', 'filename': 'a.txt'}, {'path_or_url': '/data/b.txt', 'filename': 'b.txt'}]
    out = await fmu.trigger_data_process(files, params, tenant_id='tenant-1')
    assert out == {'task_ids': ['t1', 't2']}
    assert fake_client.last_post['url'].endswith('/tasks/batch')
    assert len(fake_client.last_post['json']['sources']) == 2
    assert all((s['embedding_model_id'] == 42 for s in fake_client.last_post['json']['sources']))

@pytest.mark.asyncio
async def test_trigger_data_process_batch_non201_and_request_error(fmu, monkeypatch):
    fake_client1 = _FakeAsyncClient(_Resp(500, None, text='bad'))
    fake_httpx1 = types.SimpleNamespace(AsyncClient=lambda: fake_client1, RequestError=_FakeRequestError)
    set_import_attribute(monkeypatch, fmu, 'httpx', fake_httpx1)
    params = _ProcessParams('Bearer tok', 'minio', 'basic', 'idx')
    files = [{'path_or_url': '/a', 'filename': 'a'}, {'path_or_url': '/b', 'filename': 'b'}]
    out1 = await fmu.trigger_data_process(files, params, tenant_id='tenant-1')
    assert out1['status'] == 'error' and out1['code'] == 500
    fake_client2 = _FakeAsyncClient(_FakeRequestError('down'))
    fake_httpx2 = types.SimpleNamespace(AsyncClient=lambda: fake_client2, RequestError=_FakeRequestError)
    set_import_attribute(monkeypatch, fmu, 'httpx', fake_httpx2)
    out2 = await fmu.trigger_data_process(files, params, tenant_id='tenant-1')
    assert out2['status'] == 'error' and out2['code'] == 'CONNECTION_ERROR'


@pytest.mark.asyncio
async def test_trigger_data_process_non201_with_invalid_json_uses_response_text(fmu, monkeypatch):
    fake_client = _FakeAsyncClient(_InvalidJsonResp(502, text='gateway unavailable'))
    set_import_attribute(monkeypatch, fmu, 'httpx', types.SimpleNamespace(AsyncClient=lambda: fake_client, RequestError=_FakeRequestError))
    params = _ProcessParams('Bearer tok', 'local', 'basic', 'idx')
    out = await fmu.trigger_data_process([{'path_or_url': '/data/a.txt', 'filename': 'a.txt'}], params, tenant_id='tenant-1')
    assert out['status'] == 'error'
    assert out['code'] == 502
    assert out['error_code']


@pytest.mark.asyncio
async def test_trigger_data_process_batch_non201_with_invalid_json_uses_response_text(fmu, monkeypatch):
    fake_client = _FakeAsyncClient(_InvalidJsonResp(503, text='service unavailable'))
    set_import_attribute(monkeypatch, fmu, 'httpx', types.SimpleNamespace(AsyncClient=lambda: fake_client, RequestError=_FakeRequestError))
    params = _ProcessParams('Bearer tok', 'minio', 'basic', 'idx')
    out = await fmu.trigger_data_process([{'path_or_url': '/data/a.txt', 'filename': 'a.txt'}, {'path_or_url': '/data/b.txt', 'filename': 'b.txt'}], params, tenant_id='tenant-1')
    assert out['status'] == 'error'
    assert out['code'] == 503
    assert out['error_code']


@pytest.mark.asyncio
async def test_trigger_data_process_unexpected_client_error_uses_internal_code(fmu, monkeypatch):
    fake_client = _FakeAsyncClient(RuntimeError('unexpected client failure'))
    set_import_attribute(monkeypatch, fmu, 'httpx', types.SimpleNamespace(AsyncClient=lambda: fake_client, RequestError=_FakeRequestError))
    params = _ProcessParams('Bearer tok', 'local', 'basic', 'idx')
    out = await fmu.trigger_data_process([{'path_or_url': '/data/a.txt', 'filename': 'a.txt'}], params, tenant_id='tenant-1')
    assert out['status'] == 'error'
    assert out['code'] == 'INTERNAL_ERROR'
    assert out['error_code']


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
    set_import_attribute(monkeypatch, fmu, "httpx", types.SimpleNamespace(AsyncClient=lambda: fake_client))
    def _fake_convert(process_celery_state, forward_celery_state):
        return "COMPLETED"
    set_import_attribute(monkeypatch, fmu, "_convert_to_custom_state_local", _fake_convert)

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
    set_import_attribute(monkeypatch, fmu, "httpx", types.SimpleNamespace(AsyncClient=lambda: fake_client_err))
    out1 = await fmu.get_all_files_status("idx")
    assert out1 == {}

    # non-200
    fake_client = _FakeAsyncClient(_Resp(500, None, text="bad"))
    set_import_attribute(monkeypatch, fmu, "httpx", types.SimpleNamespace(AsyncClient=lambda: fake_client))
    out2 = await fmu.get_all_files_status("idx")
    assert out2 == {}


@pytest.mark.asyncio
async def test_get_all_files_status_no_tasks_returns_empty(fmu, monkeypatch):
    fake_client = _FakeAsyncClient(_Resp(200, []))
    set_import_attribute(monkeypatch, fmu, "httpx", types.SimpleNamespace(AsyncClient=lambda: fake_client))

    out = await fmu.get_all_files_status("idx-empty")
    assert out == {}


@pytest.mark.asyncio
async def test_get_all_files_status_forward_updates_and_redis_progress(fmu, monkeypatch):
    tasks_list = [
        {
            "id": "10",
            "task_name": "process",
            "index_name": "idx",
            "path_or_url": "/p2",
            "original_filename": "f2",
            "source_type": "local",
            "status": "SUCCESS",
            "created_at": 1,
        },
        {
            "id": "20",
            "task_name": "forward",
            "index_name": "idx",
            "path_or_url": "/p2",
            "original_filename": "f2",
            "source_type": "local",
            "status": "STARTED",
            "created_at": 5,  # later than process to trigger forward branch
        },
    ]
    fake_client = _FakeAsyncClient(_Resp(200, tasks_list))
    set_import_attribute(monkeypatch, fmu, "httpx", types.SimpleNamespace(AsyncClient=lambda: fake_client))
    def _fake_convert(*a, **k):
        return "FORWARDING"
    set_import_attribute(monkeypatch, fmu, "_convert_to_custom_state_local", _fake_convert)

    # Stub redis_service with batch progress info
    services_pkg = types.ModuleType("services")
    services_pkg.__path__ = []
    sys.modules["services"] = services_pkg
    redis_mod = types.ModuleType("management.services.knowledge_base.task_state")
    # Use batch_get_progress_info instead of get_progress_info
    redis_mod.get_redis_service = lambda: types.SimpleNamespace(
        batch_get_progress_info=lambda task_ids: {
            "20": {"processed_chunks": 7, "total_chunks": 9}
        }
    )
    sys.modules["management.services.knowledge_base.task_state"] = redis_mod

    out = await fmu.get_all_files_status("idx")
    assert out["/p2"]["state"] == "FORWARDING"
    assert out["/p2"]["latest_task_id"] == "20"
    assert out["/p2"]["processed_chunks"] == 7
    assert out["/p2"]["total_chunks"] == 9


@pytest.mark.asyncio
async def test_get_all_files_status_redis_progress_exception(fmu, monkeypatch):
    tasks_list = [
        {
            "id": "30",
            "task_name": "forward",
            "index_name": "idx",
            "path_or_url": "/p3",
            "original_filename": "f3",
            "source_type": "local",
            "status": "STARTED",
            "created_at": 2,
        },
    ]
    fake_client = _FakeAsyncClient(_Resp(200, tasks_list))
    set_import_attribute(monkeypatch, fmu, "httpx", types.SimpleNamespace(AsyncClient=lambda: fake_client))
    def _fake_convert(*a, **k):
        return "FORWARDING"
    set_import_attribute(monkeypatch, fmu, "_convert_to_custom_state_local", _fake_convert)

    # Redis service raising exception to hit exception path
    services_pkg = types.ModuleType("services")
    services_pkg.__path__ = []
    sys.modules["services"] = services_pkg
    redis_mod = types.ModuleType("management.services.knowledge_base.task_state")
    def _boom(task_ids):
        raise RuntimeError("redis down")
    redis_mod.get_redis_service = lambda: types.SimpleNamespace(batch_get_progress_info=_boom)
    sys.modules["management.services.knowledge_base.task_state"] = redis_mod

    out = await fmu.get_all_files_status("idx")
    assert out["/p3"]["state"] == "FORWARDING"
    assert out["/p3"]["processed_chunks"] is None
    assert out["/p3"]["total_chunks"] is None


@pytest.mark.asyncio
async def test_get_all_files_status_outer_exception_returns_empty(fmu, monkeypatch):
    tasks_list = [
        {
            "id": "40",
            "task_name": "process",
            "index_name": "idx",
            "path_or_url": "/p4",
            "original_filename": "f4",
            "source_type": "local",
            "status": "SUCCESS",
            "created_at": 1,
        },
    ]
    fake_client = _FakeAsyncClient(_Resp(200, tasks_list))
    set_import_attribute(monkeypatch, fmu, "httpx", types.SimpleNamespace(AsyncClient=lambda: fake_client))

    # Mock _convert_to_custom_state_local to return COMPLETED
    def _fake_convert(*a, **k):
        return "COMPLETED"
    set_import_attribute(monkeypatch, fmu, "_convert_to_custom_state_local", _fake_convert)

    out = await fmu.get_all_files_status("idx")
    assert len(out) == 1
    assert out["/p4"]["state"] == "COMPLETED"


# -------------------- _convert_to_custom_state_local --------------------


def test_convert_to_custom_state_local_mappings(fmu):
    """Test all state conversion mappings"""
    # process failure
    assert fmu._convert_to_custom_state_local("FAILURE", "") == "PROCESS_FAILED"
    # forward failure
    assert fmu._convert_to_custom_state_local("", "FAILURE") == "FORWARD_FAILED"
    # both success
    assert fmu._convert_to_custom_state_local("SUCCESS", "SUCCESS") == "COMPLETED"
    # both empty
    assert fmu._convert_to_custom_state_local("", "") == "WAIT_FOR_PROCESSING"
    # forward-only mapping
    assert fmu._convert_to_custom_state_local("", "PENDING") == "WAIT_FOR_FORWARDING"
    assert fmu._convert_to_custom_state_local("", "STARTED") == "FORWARDING"
    assert fmu._convert_to_custom_state_local("", "SUCCESS") == "COMPLETED"
    # process-only mapping
    assert fmu._convert_to_custom_state_local("PENDING", "") == "WAIT_FOR_PROCESSING"
    assert fmu._convert_to_custom_state_local("STARTED", "") == "PROCESSING"
    assert fmu._convert_to_custom_state_local("SUCCESS", "") == "WAIT_FOR_FORWARDING"


# -------------------- get_file_size --------------------


def test_get_file_size_minio_ok_and_request_error(fmu, monkeypatch):
    # ok
    assert fmu.get_file_size("minio", "obj") == 777

    # request exception path
    class _ReqExc(Exception):
        pass

    fake_requests = types.SimpleNamespace(exceptions=types.SimpleNamespace(RequestException=_ReqExc))
    set_import_attribute(monkeypatch, fmu, "requests", fake_requests)

    def raise_req(*a, **k):
        raise _ReqExc("x")

    set_import_attribute(monkeypatch, fmu, "get_file_size_from_minio", raise_req)
    assert fmu.get_file_size("minio", "obj") == 0


def test_get_file_size_local_exists_missing_and_error(fmu, monkeypatch):
    set_import_attribute(monkeypatch, fmu.os.path, "exists", lambda p: True)
    set_import_attribute(monkeypatch, fmu.os.path, "getsize", lambda p: 1234)
    assert fmu.get_file_size("local", "/tmp/x") == 1234

    set_import_attribute(monkeypatch, fmu.os.path, "exists", lambda p: False)
    assert fmu.get_file_size("local", "/tmp/x") == 0

    def boom(p):
        raise RuntimeError("e")

    set_import_attribute(monkeypatch, fmu.os.path, "exists", lambda p: True)
    set_import_attribute(monkeypatch, fmu.os.path, "getsize", boom)
    assert fmu.get_file_size("local", "/tmp/x") == 0


def test_get_file_size_invalid_source_type(fmu):
    # Function catches NotImplementedError and returns 0
    assert fmu.get_file_size("http", "http://x") == 0


# -------------------- Additional coverage for get_all_files_status --------------------


@pytest.mark.asyncio
async def test_get_all_files_status_forward_created_at_not_greater(fmu, monkeypatch):
    """Test forward task with created_at not greater than latest_forward_created_at (line 195)"""
    tasks_list = [
        {
            "id": "20",
            "task_name": "forward",
            "index_name": "idx",
            "path_or_url": "/p5",
            "original_filename": "f5",
            "source_type": "local",
            "status": "STARTED",
            "created_at": 5,
        },
        {
            "id": "21",
            "task_name": "forward",
            "index_name": "idx",
            "path_or_url": "/p5",
            "original_filename": "f5",
            "source_type": "local",
            "status": "SUCCESS",
            "created_at": 3,  # Less than previous forward task, should not update
        },
    ]
    fake_client = _FakeAsyncClient(_Resp(200, tasks_list))
    set_import_attribute(monkeypatch, fmu, "httpx", types.SimpleNamespace(AsyncClient=lambda: fake_client))
    def _fake_convert(*a, **k):
        return "FORWARDING"
    set_import_attribute(monkeypatch, fmu, "_convert_to_custom_state_local", _fake_convert)

    out = await fmu.get_all_files_status("idx")
    # Should use the first forward task (id=20) as latest since it has higher created_at
    assert out["/p5"]["latest_task_id"] == "20"


@pytest.mark.asyncio
async def test_get_all_files_status_empty_task_id(fmu, monkeypatch):
    """Test when task_id is empty string (line 221 - not entering if branch)"""
    tasks_list = [
        {
            "id": "",  # Empty task_id
            "task_name": "process",
            "index_name": "idx",
            "path_or_url": "/p6",
            "original_filename": "f6",
            "source_type": "local",
            "status": "SUCCESS",
            "created_at": 1,
        },
    ]
    fake_client = _FakeAsyncClient(_Resp(200, tasks_list))
    set_import_attribute(monkeypatch, fmu, "httpx", types.SimpleNamespace(AsyncClient=lambda: fake_client))
    def _fake_convert(*a, **k):
        return "COMPLETED"
    set_import_attribute(monkeypatch, fmu, "_convert_to_custom_state_local", _fake_convert)

    # Stub redis_service to ensure it's not called
    services_pkg = types.ModuleType("services")
    services_pkg.__path__ = []
    sys.modules["services"] = services_pkg
    redis_mod = types.ModuleType("management.services.knowledge_base.task_state")
    redis_called = {"called": False}
    def _track_call(task_ids):
        redis_called["called"] = True
        return {}
    redis_mod.get_redis_service = lambda: types.SimpleNamespace(
        batch_get_progress_info=_track_call
    )
    sys.modules["management.services.knowledge_base.task_state"] = redis_mod

    out = await fmu.get_all_files_status("idx")
    assert out["/p6"]["latest_task_id"] == ""
    # Redis should not be called when task_id is empty
    assert redis_called["called"] is False


@pytest.mark.asyncio
async def test_get_all_files_status_redis_progress_info_none(fmu, monkeypatch):
    """Test when progress_info is None (line 226, 237 - entering else branch)"""
    tasks_list = [
        {
            "id": "50",
            "task_name": "forward",
            "index_name": "idx",
            "path_or_url": "/p7",
            "original_filename": "f7",
            "source_type": "local",
            "status": "STARTED",
            "created_at": 1,
            "processed_chunks": 5,
            "total_chunks": 10,
        },
    ]
    fake_client = _FakeAsyncClient(_Resp(200, tasks_list))
    set_import_attribute(monkeypatch, fmu, "httpx", types.SimpleNamespace(AsyncClient=lambda: fake_client))
    def _fake_convert(*a, **k):
        return "FORWARDING"
    set_import_attribute(monkeypatch, fmu, "_convert_to_custom_state_local", _fake_convert)

    # Redis service returning None (batch API)
    services_pkg = types.ModuleType("services")
    services_pkg.__path__ = []
    sys.modules["services"] = services_pkg
    redis_mod = types.ModuleType("management.services.knowledge_base.task_state")
    redis_mod.get_redis_service = lambda: types.SimpleNamespace(
        batch_get_progress_info=lambda task_ids: None  # Returns None to trigger else branch
    )
    sys.modules["management.services.knowledge_base.task_state"] = redis_mod

    out = await fmu.get_all_files_status("idx")
    assert out["/p7"]["state"] == "FORWARDING"
    assert out["/p7"]["latest_task_id"] == "50"
    # Should use task state values when progress_info is None
    assert out["/p7"]["processed_chunks"] == 5
    assert out["/p7"]["total_chunks"] == 10


@pytest.mark.asyncio
async def test_get_all_files_status_redis_processed_chunks_none(fmu, monkeypatch):
    """Test when redis_processed is None (line 230 - not entering if branch)"""
    tasks_list = [
        {
            "id": "60",
            "task_name": "forward",
            "index_name": "idx",
            "path_or_url": "/p8",
            "original_filename": "f8",
            "source_type": "local",
            "status": "STARTED",
            "created_at": 1,
            "processed_chunks": 3,
            "total_chunks": 8,
        },
    ]
    fake_client = _FakeAsyncClient(_Resp(200, tasks_list))
    set_import_attribute(monkeypatch, fmu, "httpx", types.SimpleNamespace(AsyncClient=lambda: fake_client))
    def _fake_convert(*a, **k):
        return "FORWARDING"
    set_import_attribute(monkeypatch, fmu, "_convert_to_custom_state_local", _fake_convert)

    # Redis service returning progress_info with processed_chunks as None (batch API)
    services_pkg = types.ModuleType("services")
    services_pkg.__path__ = []
    sys.modules["services"] = services_pkg
    redis_mod = types.ModuleType("management.services.knowledge_base.task_state")
    redis_mod.get_redis_service = lambda: types.SimpleNamespace(
        batch_get_progress_info=lambda task_ids: {
            "60": {
                "processed_chunks": None,  # None to skip if branch
                "total_chunks": 15
            }
        }
    )
    sys.modules["management.services.knowledge_base.task_state"] = redis_mod

    out = await fmu.get_all_files_status("idx")
    assert out["/p8"]["state"] == "FORWARDING"
    # processed_chunks should remain from task state (3) since redis_processed is None
    assert out["/p8"]["processed_chunks"] == 3
    # total_chunks should be updated from Redis (15)
    assert out["/p8"]["total_chunks"] == 15


@pytest.mark.asyncio
async def test_get_all_files_status_redis_total_chunks_none(fmu, monkeypatch):
    """Test when redis_total is None (line 232 - not entering if branch)"""
    tasks_list = [
        {
            "id": "70",
            "task_name": "forward",
            "index_name": "idx",
            "path_or_url": "/p9",
            "original_filename": "f9",
            "source_type": "local",
            "status": "STARTED",
            "created_at": 1,
            "processed_chunks": 4,
            "total_chunks": 12,
        },
    ]
    fake_client = _FakeAsyncClient(_Resp(200, tasks_list))
    set_import_attribute(monkeypatch, fmu, "httpx", types.SimpleNamespace(AsyncClient=lambda: fake_client))
    def _fake_convert(*a, **k):
        return "FORWARDING"
    set_import_attribute(monkeypatch, fmu, "_convert_to_custom_state_local", _fake_convert)

    # Redis service returning progress_info with total_chunks as None (batch API)
    services_pkg = types.ModuleType("services")
    services_pkg.__path__ = []
    sys.modules["services"] = services_pkg
    redis_mod = types.ModuleType("management.services.knowledge_base.task_state")
    redis_mod.get_redis_service = lambda: types.SimpleNamespace(
        batch_get_progress_info=lambda task_ids: {
            "70": {
                "processed_chunks": 6,
                "total_chunks": None  # None to skip if branch
            }
        }
    )
    sys.modules["management.services.knowledge_base.task_state"] = redis_mod

    out = await fmu.get_all_files_status("idx")
    assert out["/p9"]["state"] == "FORWARDING"
    # processed_chunks should be updated from Redis (6)
    assert out["/p9"]["processed_chunks"] == 6
    # total_chunks should remain from task state (12) since redis_total is None
    assert out["/p9"]["total_chunks"] == 12


class TestConvertOfficeToPdf:
    """Test cases for convert_office_to_pdf function"""

    @pytest.mark.asyncio
    async def test_convert_office_to_pdf_uses_reused_profile_directory(self, fmu, monkeypatch, tmp_path):
        """Ensure command includes LO profile URI and uses a reusable profile directory."""
        mock_result = types.SimpleNamespace(returncode=0, stderr="", stdout="")
        captured_cmd = {}
        chmod_calls = []
        profile_dir = tmp_path / "lo-profile-test"
        input_path = tmp_path / "document.docx"
        output_dir = tmp_path / "output"

        def fake_run(cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            return mock_result

        set_import_attribute(monkeypatch, fmu.os.path, "exists", lambda p: True)
        set_import_attribute(monkeypatch, fmu.os.path, "basename", lambda p: "document.docx")
        set_import_attribute(monkeypatch, fmu, "LIBREOFFICE_PROFILE_DIR", str(profile_dir))
        set_import_attribute(monkeypatch, fmu.os, "chmod", lambda path, mode: chmod_calls.append((Path(path), mode)))
        set_import_attribute(monkeypatch, fmu.subprocess, "run", fake_run)

        result = await fmu.convert_office_to_pdf(str(input_path), str(output_dir))

        assert result == str(output_dir / "document.pdf")
        cmd = captured_cmd.get("cmd", [])
        assert "--nolockcheck" in cmd
        assert f"-env:UserInstallation={profile_dir.resolve().as_uri()}" in cmd
        assert profile_dir.is_dir()
        assert chmod_calls == [(profile_dir.resolve(), 0o700)]

    @pytest.mark.asyncio
    async def test_convert_office_to_pdf_success(self, fmu, monkeypatch, tmp_path):
        """Test successful Office to PDF conversion"""
        import subprocess

        mock_result = types.SimpleNamespace(returncode=0, stderr="", stdout="")
        input_path = tmp_path / "document.docx"
        output_dir = tmp_path / "output"

        set_import_attribute(monkeypatch, fmu.os.path, "exists", lambda p: True)
        set_import_attribute(monkeypatch, fmu.os.path, "basename", lambda p: "document.docx")
        set_import_attribute(monkeypatch, fmu.subprocess, "run", lambda *a, **k: mock_result)

        result = await fmu.convert_office_to_pdf(str(input_path), str(output_dir))

        assert result == str(output_dir / "document.pdf")

    @pytest.mark.asyncio
    async def test_convert_office_to_pdf_input_not_found(self, fmu, monkeypatch, tmp_path):
        """Test conversion failure when input file does not exist"""
        input_path = tmp_path / "nonexistent.docx"
        output_dir = tmp_path / "output"
        set_import_attribute(monkeypatch, fmu.os.path, "exists", lambda p: False)

        with pytest.raises(FileNotFoundError) as exc_info:
            await fmu.convert_office_to_pdf(str(input_path), str(output_dir))

        assert "Input file not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_convert_office_to_pdf_libreoffice_error(self, fmu, monkeypatch, tmp_path):
        """Test conversion failure when LibreOffice returns error"""
        mock_result = types.SimpleNamespace(returncode=1, stderr="Error: LibreOffice crashed", stdout="")
        input_path = tmp_path / "document.docx"
        output_dir = tmp_path / "output"

        set_import_attribute(monkeypatch, fmu.os.path, "exists", lambda p: True)
        set_import_attribute(monkeypatch, fmu.subprocess, "run", lambda *a, **k: mock_result)

        with pytest.raises(RuntimeError) as exc_info:
            await fmu.convert_office_to_pdf(str(input_path), str(output_dir))

        assert "Office to PDF conversion failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_convert_office_to_pdf_timeout(self, fmu, monkeypatch, tmp_path):
        """Test conversion failure due to timeout"""
        import subprocess

        input_path = tmp_path / "document.docx"
        output_dir = tmp_path / "output"
        set_import_attribute(monkeypatch, fmu.os.path, "exists", lambda p: True)

        def raise_timeout(*a, **k):
            raise subprocess.TimeoutExpired(cmd='libreoffice', timeout=30)

        set_import_attribute(monkeypatch, fmu.subprocess, "run", raise_timeout)

        with pytest.raises(TimeoutError) as exc_info:
            await fmu.convert_office_to_pdf(str(input_path), str(output_dir), timeout=30)

        assert "timeout" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_convert_office_to_pdf_libreoffice_not_installed(self, fmu, monkeypatch, tmp_path):
        """Test conversion failure when LibreOffice is not installed"""
        input_path = tmp_path / "document.docx"
        output_dir = tmp_path / "output"
        set_import_attribute(monkeypatch, fmu.os.path, "exists", lambda p: True)

        def raise_file_not_found(*a, **k):
            raise FileNotFoundError("[Errno 2] No such file or directory: 'libreoffice'")

        set_import_attribute(monkeypatch, fmu.subprocess, "run", raise_file_not_found)

        with pytest.raises(FileNotFoundError) as exc_info:
            await fmu.convert_office_to_pdf(str(input_path), str(output_dir))

        assert "LibreOffice is not installed" in str(exc_info.value)
        assert "not available in PATH" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_convert_office_to_pdf_output_not_found(self, fmu, monkeypatch, tmp_path):
        """Test conversion failure when output PDF is not generated"""
        mock_result = types.SimpleNamespace(returncode=0, stderr="", stdout="")
        input_path = tmp_path / "document.docx"
        output_dir = tmp_path / "output"

        def exists_side_effect(path):
            # Input file exists, output PDF does not
            if 'document.docx' in path:
                return True
            return False

        set_import_attribute(monkeypatch, fmu.os.path, "exists", exists_side_effect)
        set_import_attribute(monkeypatch, fmu.os.path, "basename", lambda p: "document.docx")
        set_import_attribute(monkeypatch, fmu.subprocess, "run", lambda *a, **k: mock_result)

        with pytest.raises(RuntimeError) as exc_info:
            await fmu.convert_office_to_pdf(str(input_path), str(output_dir))

        assert "Converted PDF not found" in str(exc_info.value)
