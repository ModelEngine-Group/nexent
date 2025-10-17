"""
Unit tests for backend.apps.file_management_app

We stub external dependencies before importing the app module to avoid
side effects and real network/storage calls.
"""

import sys
import types
from typing import Any, AsyncGenerator, List

import pytest
from unittest.mock import AsyncMock, MagicMock


# --- Bootstrap: insert stub modules BEFORE importing the app under test ---

# Add project backend root to sys.path
import os

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "../../.."))
BACKEND_ROOT = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_ROOT not in sys.path:
    sys.path.append(BACKEND_ROOT)


# Stub services.file_management_service to prevent importing the real service
services_pkg = types.ModuleType("services")
services_pkg.__path__ = []
sys.modules.setdefault("services", services_pkg)

sfms_stub = types.ModuleType("services.file_management_service")

async def _stub_upload_to_minio(files, folder):
    return []

async def _stub_upload_files_impl(destination, file, folder, index_name):
    return [], [], []

async def _stub_get_file_url_impl(object_name: str, expires: int):
    return {"success": True, "url": f"http://example.com/{object_name}"}

async def _stub_get_file_stream_impl(object_name: str):
    return AsyncMock(), "application/octet-stream"

async def _stub_delete_file_impl(object_name: str):
    return {"success": True}

async def _stub_list_files_impl(prefix: str, limit: int | None = None):
    files = [{"name": "a.txt", "url": "http://u"}]
    return files[:limit] if limit else files

async def _stub_preprocess_files_generator(*_: Any, **__: Any) -> AsyncGenerator[str, None]:
    yield "data: {\"type\": \"progress\", \"progress\": 0}\n\n"
    yield "data: {\"type\": \"complete\", \"progress\": 100}\n\n"

sfms_stub.upload_to_minio = _stub_upload_to_minio
sfms_stub.upload_files_impl = _stub_upload_files_impl
sfms_stub.get_file_url_impl = _stub_get_file_url_impl
sfms_stub.get_file_stream_impl = _stub_get_file_stream_impl
sfms_stub.delete_file_impl = _stub_delete_file_impl
sfms_stub.list_files_impl = _stub_list_files_impl
sfms_stub.preprocess_files_generator = _stub_preprocess_files_generator
sys.modules["services.file_management_service"] = sfms_stub
setattr(services_pkg, "file_management_service", sfms_stub)


# Stub utils.auth_utils.get_current_user_info
utils_pkg = types.ModuleType("utils")
utils_pkg.__path__ = []
sys.modules.setdefault("utils", utils_pkg)

auth_utils_stub = types.ModuleType("utils.auth_utils")
def _stub_get_current_user_info(authorization, request):
    return ("user1", "tenant1", "en")
auth_utils_stub.get_current_user_info = _stub_get_current_user_info
sys.modules["utils.auth_utils"] = auth_utils_stub
setattr(utils_pkg, "auth_utils", auth_utils_stub)


# Stub utils.file_management_utils.trigger_data_process
fmu_stub = types.ModuleType("utils.file_management_utils")
async def _stub_trigger_data_process(files: List[dict], params: Any):
    return [{"task_id": 1}]
fmu_stub.trigger_data_process = _stub_trigger_data_process
sys.modules["utils.file_management_utils"] = fmu_stub
setattr(utils_pkg, "file_management_utils", fmu_stub)


# Stub consts.model.ProcessParams
consts_pkg = types.ModuleType("consts")
consts_pkg.__path__ = []
sys.modules.setdefault("consts", consts_pkg)

model_stub = types.ModuleType("consts.model")
class ProcessParams:  # minimal stub
    def __init__(self, chunking_strategy: str, source_type: str, index_name: str, authorization: str | None):
        self.chunking_strategy = chunking_strategy
        self.source_type = source_type
        self.index_name = index_name
        self.authorization = authorization
model_stub.ProcessParams = ProcessParams
sys.modules["consts.model"] = model_stub
setattr(consts_pkg, "model", model_stub)


# Import the module under test after stubbing deps
file_management_app = __import__(
    "backend.apps.file_management_app", fromlist=["*"]
)


# --- Helpers ---

def make_upload_file(filename: str, content: bytes = b"data"):
    f = MagicMock()
    f.filename = filename
    f.read = AsyncMock(return_value=content)
    return f


# --- Tests ---

@pytest.mark.asyncio
async def test_options_route_ok():
    resp = await file_management_app.options_route("any/path")
    assert resp.status_code == 200
    assert resp.body == b'{"detail":"OK"}'


@pytest.mark.asyncio
async def test_upload_files_success(monkeypatch):
    async def fake_upload_impl(dest, files, folder, index_name):
        return [], ["/abs/path1"], ["a.txt"]

    monkeypatch.setattr(file_management_app, "upload_files_impl", fake_upload_impl)

    result = await file_management_app.upload_files(
        file=[make_upload_file("a.txt")], destination="local", folder="attachments", index_name=None
    )
    assert result.status_code == 200
    content = result.body.decode()
    assert "Files uploaded successfully" in content
    assert "a.txt" in content and "/abs/path1" in content


@pytest.mark.asyncio
async def test_upload_files_no_files_bad_request():
    with pytest.raises(Exception) as ei:
        await file_management_app.upload_files(file=[], destination="local", folder="attachments", index_name=None)
    assert "No files in the request" in str(ei.value)


@pytest.mark.asyncio
async def test_upload_files_no_valid_files_uploaded(monkeypatch):
    async def fake_upload_impl(dest, files, folder, index_name):
        return ["err"], [], []

    monkeypatch.setattr(file_management_app, "upload_files_impl", fake_upload_impl)
    with pytest.raises(Exception) as ei:
        await file_management_app.upload_files(
            file=[make_upload_file("x.txt")], destination="minio", folder="attachments", index_name=None
        )
    assert "No valid files uploaded" in str(ei.value)


@pytest.mark.asyncio
async def test_process_files_success(monkeypatch):
    async def fake_trigger(files, params):
        return [{"task_id": 123}]

    monkeypatch.setattr(file_management_app, "trigger_data_process", fake_trigger)
    resp = await file_management_app.process_files(
        files=[{"path_or_url": "/tmp/a.txt", "filename": "a.txt"}],
        chunking_strategy="basic",
        index_name="kb1",
        destination="local",
        authorization="Bearer x",
    )
    assert resp.status_code == 201
    assert "Files processing triggered successfully" in resp.body.decode()


@pytest.mark.asyncio
async def test_process_files_error_none(monkeypatch):
    async def fake_trigger(files, params):
        return None

    monkeypatch.setattr(file_management_app, "trigger_data_process", fake_trigger)
    with pytest.raises(Exception) as ei:
        await file_management_app.process_files(
            files=[{"path_or_url": "x", "filename": "x"}],
            chunking_strategy="basic",
            index_name="kb",
            destination="local",
            authorization=None,
        )
    assert "Data process service failed" in str(ei.value)


@pytest.mark.asyncio
async def test_process_files_error_message(monkeypatch):
    async def fake_trigger(files, params):
        return {"status": "error", "message": "boom"}

    monkeypatch.setattr(file_management_app, "trigger_data_process", fake_trigger)
    with pytest.raises(Exception) as ei:
        await file_management_app.process_files(
            files=[{"path_or_url": "x", "filename": "x"}],
            chunking_strategy="basic",
            index_name="kb",
            destination="local",
            authorization=None,
        )
    assert "boom" in str(ei.value)


@pytest.mark.asyncio
async def test_storage_upload_files_counts(monkeypatch):
    async def fake_upload(files, folder):
        return [
            {"success": True, "file_name": "a.txt"},
            {"success": False, "file_name": "b.txt", "error": "x"},
        ]

    monkeypatch.setattr(file_management_app, "upload_to_minio", fake_upload)
    f1 = make_upload_file("a.txt")
    f2 = make_upload_file("b.txt")
    result = await file_management_app.storage_upload_files(files=[f1, f2], folder="attachments")
    assert result["message"].startswith("Processed 2")
    assert result["success_count"] == 1
    assert result["failed_count"] == 1
    assert len(result["results"]) == 2


@pytest.mark.asyncio
async def test_get_storage_files_include_and_strip_urls(monkeypatch):
    async def fake_list(prefix, limit):
        return [{"name": "a", "url": "http://u"}, {"name": "b"}]

    monkeypatch.setattr(file_management_app, "list_files_impl", fake_list)
    # include URLs
    out1 = await file_management_app.get_storage_files(prefix="", limit=10, include_urls=True)
    assert out1["total"] == 2
    assert out1["files"][0]["url"] == "http://u"
    # strip URLs
    out2 = await file_management_app.get_storage_files(prefix="", limit=10, include_urls=False)
    assert out2["total"] == 2
    assert "url" not in out2["files"][0]


@pytest.mark.asyncio
async def test_get_storage_files_error(monkeypatch):
    async def boom(prefix, limit):
        raise RuntimeError("oops")

    monkeypatch.setattr(file_management_app, "list_files_impl", boom)
    with pytest.raises(Exception) as ei:
        await file_management_app.get_storage_files(prefix="p", limit=1, include_urls=True)
    assert "Failed to get file list" in str(ei.value)


@pytest.mark.asyncio
async def test_get_storage_file_redirect(monkeypatch):
    async def fake_get_url(object_name, expires):
        return {"success": True, "url": "http://example.com/a"}

    monkeypatch.setattr(file_management_app, "get_file_url_impl", fake_get_url)
    resp = await file_management_app.get_storage_file(object_name="a.txt", download="redirect", expires=60)
    # Starlette RedirectResponse defaults to 307
    assert 300 <= resp.status_code < 400
    assert resp.headers["location"] == "http://example.com/a"


@pytest.mark.asyncio
async def test_get_storage_file_stream(monkeypatch):
    async def fake_get_stream(object_name):
        async def gen():
            yield b"chunk1"
        return gen(), "text/plain"

    monkeypatch.setattr(file_management_app, "get_file_stream_impl", fake_get_stream)
    resp = await file_management_app.get_storage_file(object_name="a.txt", download="stream", expires=60)
    assert resp.media_type == "text/plain"
    assert "inline; filename=\"a.txt\"" in resp.headers.get("content-disposition", "")
    # consume stream
    chunks = []
    async for part in resp.body_iterator:  # type: ignore[attr-defined]
        chunks.append(part)
    assert b"chunk1" in b"".join(chunks)


@pytest.mark.asyncio
async def test_get_storage_file_metadata(monkeypatch):
    async def fake_get_url(object_name, expires):
        return {"success": True, "url": "http://example.com/x"}

    monkeypatch.setattr(file_management_app, "get_file_url_impl", fake_get_url)
    result = await file_management_app.get_storage_file(object_name="x", download="ignore", expires=10)
    assert result["url"] == "http://example.com/x"


@pytest.mark.asyncio
async def test_get_storage_file_error(monkeypatch):
    async def boom_url(object_name, expires):
        raise RuntimeError("x")

    monkeypatch.setattr(file_management_app, "get_file_url_impl", boom_url)
    with pytest.raises(Exception) as ei:
        await file_management_app.get_storage_file(object_name="x", download="ignore", expires=1)
    assert "Failed to get file information" in str(ei.value)


@pytest.mark.asyncio
async def test_remove_storage_file_success(monkeypatch):
    async def ok_delete(object_name):
        return {"success": True}

    monkeypatch.setattr(file_management_app, "delete_file_impl", ok_delete)
    result = await file_management_app.remove_storage_file(object_name="x")
    assert result["success"] is True


@pytest.mark.asyncio
async def test_remove_storage_file_error(monkeypatch):
    async def boom_delete(object_name):
        raise RuntimeError("nope")

    monkeypatch.setattr(file_management_app, "delete_file_impl", boom_delete)
    with pytest.raises(Exception) as ei:
        await file_management_app.remove_storage_file(object_name="x")
    assert "Failed to delete file" in str(ei.value)


@pytest.mark.asyncio
async def test_get_storage_file_batch_urls_validation_error():
    with pytest.raises(Exception) as ei:
        await file_management_app.get_storage_file_batch_urls(request_data={}, expires=10)
    assert "object_names" in str(ei.value)


@pytest.mark.asyncio
async def test_get_storage_file_batch_urls_mixed(monkeypatch):
    def fake_get(object_name, expires):
        # Synchronous stub to match non-awaited usage in implementation
        if object_name == "ok":
            return {"success": True, "url": "http://u"}
        raise RuntimeError("bad")

    monkeypatch.setattr(file_management_app, "get_file_url_impl", fake_get)
    out = await file_management_app.get_storage_file_batch_urls(
        request_data={"object_names": ["ok", "bad"]}, expires=5
    )
    assert out["total"] == 2
    assert out["success_count"] == 1
    assert any(item["object_name"] == "bad" and item["success"] is False for item in out["results"])


@pytest.mark.asyncio
async def test_agent_preprocess_api_success(monkeypatch):
    # Patch get_current_user_info
    monkeypatch.setattr(file_management_app, "get_current_user_info", lambda a, r: ("u", "t", "en"))

    # Provide an async generator object for streaming
    async def gen():
        yield "data: {\\\"type\\\": \\\"complete\\\"}\n\n"

    monkeypatch.setattr(file_management_app, "preprocess_files_generator", lambda **_: gen())

    # Mock files
    f1 = make_upload_file("a.txt", b"hello")
    f2 = make_upload_file("b.jpg", b"img")

    # Minimal ASGI scope for Request
    from starlette.requests import Request
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/file/preprocess",
        "headers": [],
        "query_string": b"conversation_id=42",
    }
    req = Request(scope)

    resp = await file_management_app.agent_preprocess_api(
        request=req, query="q", files=[f1, f2], authorization="Bearer x"
    )
    assert resp.media_type == "text/event-stream"
    assert resp.headers.get("Cache-Control") == "no-cache"
    # Consume a small portion of stream
    chunks = []
    async for part in resp.body_iterator:  # type: ignore[attr-defined]
        chunks.append(part)
        break
    assert chunks


@pytest.mark.asyncio
async def test_agent_preprocess_api_error_from_auth(monkeypatch):
    def boom_auth(a, r):
        raise RuntimeError("auth failed")

    monkeypatch.setattr(file_management_app, "get_current_user_info", boom_auth)

    from starlette.requests import Request
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/file/preprocess",
        "headers": [],
        "query_string": b"",
    }
    req = Request(scope)

    with pytest.raises(Exception) as ei:
        await file_management_app.agent_preprocess_api(
            request=req, query="q", files=[make_upload_file("a.txt")], authorization=None
        )
    assert "File preprocessing error" in str(ei.value)


