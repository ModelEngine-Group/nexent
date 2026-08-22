import sys
import types
from typing import Any, Dict, List, Optional, Tuple
from http import HTTPStatus

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

# Install consts.exceptions at module level so OfficeConversionException is bound
# in the app module's namespace on first import.
_exc_mod = types.ModuleType("consts.exceptions")


class _OfficeConversionException(Exception):
    """Stub exception for Office document conversion failures."""


_exc_mod.OfficeConversionException = _OfficeConversionException  # type: ignore[attr-defined]
sys.modules["consts.exceptions"] = _exc_mod


class _TaskRequest(BaseModel):
    source: str
    source_type: str
    chunking_strategy: str = "basic"
    index_name: Optional[str] = None
    original_filename: Optional[str] = None
    embedding_model_id: Optional[int] = None
    tenant_id: Optional[str] = None


class _BatchTaskRequest(BaseModel):
    sources: List[_TaskRequest]


class _ConvertStateRequest(BaseModel):
    process_state: Optional[str] = None
    forward_state: Optional[str] = None


class _DummyResult:
    def __init__(self, id_: str, payload: Optional[Dict[str, Any]] = None, exc: Optional[Exception] = None):
        self.id = id_
        self._payload = payload or {}
        self._exc = exc

    def get(self, timeout: Optional[int] = None):
        if self._exc:
            raise self._exc
        return self._payload


class _TasksStub:
    def __init__(self):
        self._delay_result = _DummyResult("task-stub-id", payload={})
        self._apply_async_result = _DummyResult(
            "task-sync-id",
            payload={
                "text": "hello world",
                "chunks": [{"content": "hello"}],
                "chunks_count": 1,
                "processing_time": 0.1,
                "text_length": 11,
            },
        )

    def process_and_forward_delay(self, **kwargs):
        return self._delay_result

    def process_sync_apply_async(self, **kwargs):
        return self._apply_async_result


class _ServiceStub:
    def __init__(self):
        self.started = False
        self.stopped = False

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def create_batch_tasks_impl(self, authorization: Optional[str], request: _BatchTaskRequest) -> List[str]:
        return [f"tid-{i}" for i, _ in enumerate(request.sources, start=1)]

    async def load_image(self, url: str):
        if url == "none":
            return None
        return object()

    async def convert_to_base64(self, image: object) -> Tuple[str, str]:
        return ("ZmFrZSBiYXNlNjQ=", "image/png")

    async def get_all_tasks(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": "1",
                "task_name": "process",
                "index_name": "idx",
                "path_or_url": "/p1",
                "original_filename": "f1.txt",
                "source_type": "local",
                "status": "STARTED",
                "created_at": 1,
                "updated_at": 2,
                "error": "",
            },
            {
                "id": "2",
                "task_name": "forward",
                "index_name": "idx",
                "path_or_url": "/p1",
                "original_filename": "f1.txt",
                "source_type": "local",
                "status": "SUCCESS",
                "created_at": 3,
                "updated_at": 4,
                "error": "",
            },
        ]

    async def get_index_tasks(self, index_name: str):
        if index_name == "boom":
            raise RuntimeError("oops")
        return [{"id": "x"}]

    async def get_task_details(self, task_id: str):
        if task_id == "missing":
            return None
        return {"id": task_id, "ok": True}

    async def filter_important_image(self, image_url: str, positive_prompt: str, negative_prompt: str):
        if image_url == "err":
            raise RuntimeError("bad")
        return {"important": True, "score": 0.9}

    async def process_uploaded_text_file(self, file_content: bytes, filename: str, chunking_strategy: str):
        if filename == "err.bin":
            raise RuntimeError("bad file")
        return {"filename": filename, "text": file_content.decode(errors="ignore")}

    def convert_celery_states_to_custom(self, process_celery_state: str, forward_celery_state: str) -> str:
        if process_celery_state == "SUCCESS" and forward_celery_state == "SUCCESS":
            return "COMPLETED"
        return "WAIT_FOR_PROCESSING"

    async def convert_office_to_pdf_impl(self, object_name: str, pdf_object_name: str) -> None:
        """Stub: raise OfficeConversionException for sentinel inputs, otherwise succeed."""
        from consts.exceptions import OfficeConversionException
        if object_name == "fail.docx":
            raise OfficeConversionException("conversion failed")
        if object_name == "err.docx":
            raise RuntimeError("unexpected error")


@pytest.fixture(autouse=True)
def stub_modules(monkeypatch):
    # consts.model
    model_mod = types.ModuleType("consts.model")
    setattr(model_mod, "TaskRequest", _TaskRequest)
    setattr(model_mod, "BatchTaskRequest", _BatchTaskRequest)
    setattr(model_mod, "ConvertStateRequest", _ConvertStateRequest)
    sys.modules["consts.model"] = model_mod

    # data_process.tasks
    tasks_mod = types.ModuleType("data_process.tasks")
    _tasks = _TasksStub()
    class _PAndF:
        def delay(self, **kwargs):
            return _tasks.process_and_forward_delay(**kwargs)
    class _PSync:
        def apply_async(self, **kwargs):
            return _tasks.process_sync_apply_async(**kwargs)
    setattr(tasks_mod, "process_and_forward", _PAndF())
    setattr(tasks_mod, "process_sync", _PSync())
    sys.modules["data_process.tasks"] = tasks_mod

    # services.data_process_service
    service_stub = _ServiceStub()
    svc_mod = types.ModuleType("services.data_process_service")
    setattr(svc_mod, "get_data_process_service", lambda: service_stub)
    sys.modules["services.data_process_service"] = svc_mod

    # data_process.utils
    utils_mod = types.ModuleType("data_process.utils")
    async def get_task_details(task_id: str):
        if task_id == "missing":
            return None
        return {"id": task_id, "ok": True}
    setattr(utils_mod, "get_task_details", get_task_details)
    sys.modules["data_process.utils"] = utils_mod

    # yield to tests
    yield


def _build_app():
    from backend.apps import data_process_app as app_module
    app = FastAPI()
    app.include_router(app_module.router)
    return app


def test_create_task_success():
    app = _build_app()
    client = TestClient(app)
    payload = {
        "source": "/tmp/a.txt",
        "source_type": "local",
        "chunking_strategy": "basic",
        "index_name": "idx",
        "original_filename": "a.txt",
    }
    resp = client.post("/tasks", json=payload, headers={"Authorization": "Bearer t"})
    assert resp.status_code == 201
    assert resp.json()["task_id"] == "task-stub-id"


def test_process_sync_endpoint_success():
    app = _build_app()
    client = TestClient(app)
    resp = client.post(
        "/tasks/process",
        data={"source": "/tmp/a.txt", "source_type": "local", "chunking_strategy": "basic", "timeout": 5},
    )
    body = resp.json()
    assert resp.status_code == 200
    assert body["success"] is True
    assert body["task_id"] == "task-sync-id"
    assert body["chunks_count"] == 1


def test_process_sync_endpoint_error(monkeypatch):
    # Reconfigure tasks stub to raise when getting result
    from backend.apps import data_process_app as app_module

    class _ErrResult(_DummyResult):
        def get(self, timeout=None):
            raise RuntimeError("boom")

    class _PSyncErr:
        def apply_async(self, **kwargs):
            return _ErrResult("tid")

    monkeypatch.setattr(app_module, "process_sync", _PSyncErr(), raising=True)

    app = _build_app()
    client = TestClient(app)
    resp = client.post(
        "/tasks/process",
        data={"source": "/tmp/a.txt", "source_type": "local"},
    )
    assert resp.status_code == 500


def test_process_sync_endpoint_http_exception(monkeypatch):
    from backend.apps import data_process_app as app_module

    class _PSyncHTTP:
        def apply_async(self, **kwargs):
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST, detail="bad req")

    monkeypatch.setattr(app_module, "process_sync", _PSyncHTTP(), raising=True)

    app = _build_app()
    client = TestClient(app)
    resp = client.post(
        "/tasks/process",
        data={"source": "/tmp/a.txt", "source_type": "local"},
    )
    assert resp.status_code == HTTPStatus.BAD_REQUEST


def test_batch_tasks_success():
    app = _build_app()
    client = TestClient(app)
    payload = {
        "sources": [
            {"source": "s1", "source_type": "local"},
            {"source": "s2", "source_type": "minio"},
        ]
    }
    resp = client.post("/tasks/batch", json=payload, headers={"Authorization": "Bearer t"})
    assert resp.status_code == 201
    assert resp.json()["task_ids"] == ["tid-1", "tid-2"]


def test_batch_tasks_error(monkeypatch):
    # Make service raise
    from backend.apps import data_process_app as app_module

    async def err(*args, **kwargs):
        raise RuntimeError("x")

    monkeypatch.setattr(app_module.service,
                        "create_batch_tasks_impl", err, raising=True)

    app = _build_app()
    client = TestClient(app)
    resp = client.post("/tasks/batch", json={"sources": []}, headers={"Authorization": "Bearer t"})
    assert resp.status_code == 500


def test_batch_tasks_http_exception(monkeypatch):
    from backend.apps import data_process_app as app_module

    async def err_http(*args, **kwargs):
        raise HTTPException(
            status_code=HTTPStatus.NOT_ACCEPTABLE, detail="bad batch")

    monkeypatch.setattr(app_module.service,
                        "create_batch_tasks_impl", err_http, raising=True)

    app = _build_app()
    client = TestClient(app)
    resp = client.post(
        "/tasks/batch", json={"sources": []}, headers={"Authorization": "Bearer t"})
    assert resp.status_code == HTTPStatus.NOT_ACCEPTABLE


def test_load_image_success_and_not_found():
    app = _build_app()
    client = TestClient(app)
    ok = client.get("/tasks/load_image", params={"url": "u"})
    assert ok.status_code == 200
    assert ok.json()["success"] is True
    nf = client.get("/tasks/load_image", params={"url": "none"})
    assert nf.status_code == 404


def test_load_image_internal_error(monkeypatch):
    from backend.apps import data_process_app as app_module

    async def err(url: str):
        raise RuntimeError("bad")

    monkeypatch.setattr(app_module.service, "load_image", err, raising=True)
    app = _build_app()
    client = TestClient(app)
    resp = client.get("/tasks/load_image", params={"url": "x"})
    assert resp.status_code == 500


def test_filter_important_image_http_exception(monkeypatch):
    from backend.apps import data_process_app as app_module

    async def err_http(*args, **kwargs):
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail="bad image")

    monkeypatch.setattr(app_module.service,
                        "filter_important_image", err_http, raising=True)

    app = _build_app()
    client = TestClient(app)
    resp = client.post(
        "/tasks/filter_important_image",
        data={"image_url": "u"},
    )
    assert resp.status_code == HTTPStatus.BAD_REQUEST


def test_list_tasks():
    app = _build_app()
    client = TestClient(app)
    resp = client.get("/tasks")
    assert resp.status_code == 200
    body = resp.json()
    assert "tasks" in body and len(body["tasks"]) == 2


def test_get_index_tasks_success_and_error():
    app = _build_app()
    client = TestClient(app)
    ok = client.get("/tasks/indices/idx")
    assert ok.status_code == 200
    err = client.get("/tasks/indices/boom")
    assert err.status_code == 500


def test_get_task_details_success_and_404():
    app = _build_app()
    client = TestClient(app)
    ok = client.get("/tasks/abc/details")
    assert ok.status_code == 200 and ok.json()["ok"] is True
    nf = client.get("/tasks/missing/details")
    assert nf.status_code == 404


def test_filter_important_image_success_and_error():
    app = _build_app()
    client = TestClient(app)
    ok = client.post(
        "/tasks/filter_important_image",
        data={"image_url": "u", "positive_prompt": "p", "negative_prompt": "n"},
    )
    assert ok.status_code == 200 and ok.json()["important"] is True
    err = client.post(
        "/tasks/filter_important_image",
        data={"image_url": "err", "positive_prompt": "p", "negative_prompt": "n"},
    )
    assert err.status_code == 500


def test_process_text_file_success_and_error(tmp_path):
    app = _build_app()
    client = TestClient(app)
    # success
    files = {"file": ("a.txt", b"hello", "text/plain")}
    ok = client.post("/tasks/process_text_file", files=files, data={"chunking_strategy": "basic"})
    assert ok.status_code == 200
    # error branch
    files = {"file": ("err.bin", b"data", "application/octet-stream")}
    bad = client.post("/tasks/process_text_file", files=files, data={"chunking_strategy": "basic"})
    assert bad.status_code == 500


def test_process_text_file_http_exception(monkeypatch):
    from backend.apps import data_process_app as app_module

    async def err_http(*args, **kwargs):
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail="bad file")

    monkeypatch.setattr(app_module.service,
                        "process_uploaded_text_file", err_http, raising=True)

    app = _build_app()
    client = TestClient(app)
    files = {"file": ("x.txt", b"hello", "text/plain")}
    resp = client.post("/tasks/process_text_file", files=files,
                       data={"chunking_strategy": "basic"})
    assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_convert_state_success_and_error(monkeypatch):
    app = _build_app()
    client = TestClient(app)
    ok = client.post("/tasks/convert_state", json={"process_state": "SUCCESS", "forward_state": "SUCCESS"})
    assert ok.status_code == 200 and ok.json()["state"] == "COMPLETED"

    # Make service raise
    from backend.apps import data_process_app as app_module
    def raise_convert(*args, **kwargs):
        raise RuntimeError("x")
    monkeypatch.setattr(
        app_module.service, "convert_celery_states_to_custom", raise_convert, raising=True)
    err = client.post("/tasks/convert_state", json={"process_state": "PENDING", "forward_state": ""})
    assert err.status_code == 500


def test_convert_state_http_exception(monkeypatch):
    app = _build_app()
    client = TestClient(app)

    from backend.apps import data_process_app as app_module

    def raise_convert_http(*args, **kwargs):
        raise HTTPException(
            status_code=HTTPStatus.NOT_ACCEPTABLE, detail="bad convert")

    monkeypatch.setattr(
        app_module.service, "convert_celery_states_to_custom", raise_convert_http, raising=True
    )

    resp = client.post("/tasks/convert_state",
                       json={"process_state": "PENDING", "forward_state": ""})
    assert resp.status_code == HTTPStatus.NOT_ACCEPTABLE


def test_convert_to_pdf_success():
    """Valid request returns 200 {success: True}."""
    app = _build_app()
    client = TestClient(app)
    resp = client.post(
        "/tasks/convert_to_pdf",
        data={"object_name": "uploads/doc.docx", "pdf_object_name": "converted/doc.pdf"},
    )
    assert resp.status_code == HTTPStatus.OK
    assert resp.json()["success"] is True


def test_convert_to_pdf_office_conversion_exception(monkeypatch):
    """OfficeConversionException from service maps to HTTP 500."""
    app = _build_app()
    client = TestClient(app)
    # Trigger the sentinel path in _ServiceStub
    resp = client.post(
        "/tasks/convert_to_pdf",
        data={"object_name": "fail.docx", "pdf_object_name": "converted/fail.pdf"},
    )
    assert resp.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert "conversion failed" in resp.json()["detail"]


def test_convert_to_pdf_unexpected_exception():
    """Unexpected RuntimeError from service also maps to HTTP 500."""
    app = _build_app()
    client = TestClient(app)
    resp = client.post(
        "/tasks/convert_to_pdf",
        data={"object_name": "err.docx", "pdf_object_name": "converted/err.pdf"},
    )
    assert resp.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


def test_convert_to_pdf_missing_params():
    """Missing required form fields returns HTTP 422 Unprocessable Entity."""
    app = _build_app()
    client = TestClient(app)
    resp = client.post("/tasks/convert_to_pdf", data={})
    assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
