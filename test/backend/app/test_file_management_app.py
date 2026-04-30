"""
Unit tests for backend.apps.file_management_app

We stub external dependencies before importing the app module to avoid
side effects and real network/storage calls.
"""

import sys
import types
from typing import Any, AsyncGenerator, Dict, List

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

async def _stub_upload_to_minio(files, folder, user_id=None):
    return []

async def _stub_upload_files_impl(destination, file, folder, index_name, user_id=None):
    return [], [], []

async def _stub_get_file_url_impl(object_name: str, expires: int):
    return {"success": True, "url": f"http://example.com/{object_name}"}

async def _stub_get_file_stream_impl(object_name: str):
    return AsyncMock(), "application/octet-stream"

async def _stub_delete_file_impl(object_name: str):
    return {"success": True}

async def _stub_list_files_impl(prefix: str, limit: int | None = None):
    files = [{"name": "a.txt", "url": "http://u", "key": "knowledge_base/a.txt"}]
    return files[:limit] if limit else files

def _stub_check_file_access(object_name: str, user_id: str) -> bool:
    """Stub for check_file_access - allows access by default for testing."""
    if object_name.startswith("attachments/"):
        # attachments/{user_id}/*: only owner can access
        if user_id:
            expected_prefix = f"attachments/{user_id}"
            return object_name.startswith(expected_prefix)
        return False
    # knowledge_base/*: all authenticated users can access
    return object_name.startswith("knowledge_base/")


def _stub_check_file_access_batch(object_names: List[str], user_id: str) -> Dict[str, bool]:
    """Stub for check_file_access_batch - returns dict of object_name -> allowed."""
    return {name: _stub_check_file_access(name, user_id) for name in object_names}

async def _stub_preprocess_files_generator(*_: Any, **__: Any) -> AsyncGenerator[str, None]:
    yield "data: {\"type\": \"progress\", \"progress\": 0}\n\n"
    yield "data: {\"type\": \"complete\", \"progress\": 100}\n\n"

async def _stub_resolve_preview_file(object_name: str):
    return object_name, "application/pdf", 1024

def _stub_get_preview_stream(actual_object_name, start=None, end=None):
    mock_s = MagicMock()
    mock_s.iter_chunks = MagicMock(return_value=iter([b"PDF content"]))
    return mock_s

sfms_stub.resolve_preview_file = _stub_resolve_preview_file
sfms_stub.get_preview_stream = _stub_get_preview_stream
sfms_stub.upload_to_minio = _stub_upload_to_minio
sfms_stub.upload_files_impl = _stub_upload_files_impl
sfms_stub.get_file_url_impl = _stub_get_file_url_impl
sfms_stub.get_file_stream_impl = _stub_get_file_stream_impl
sfms_stub.delete_file_impl = _stub_delete_file_impl
sfms_stub.list_files_impl = _stub_list_files_impl
sfms_stub.preprocess_files_generator = _stub_preprocess_files_generator
sfms_stub.check_file_access = _stub_check_file_access
sfms_stub.check_file_access_batch = _stub_check_file_access_batch
sys.modules["services.file_management_service"] = sfms_stub
setattr(services_pkg, "file_management_service", sfms_stub)


# Stub utils.auth_utils.get_current_user_id (the function actually used in the app)
utils_pkg = types.ModuleType("utils")
utils_pkg.__path__ = []
sys.modules.setdefault("utils", utils_pkg)

auth_utils_stub = types.ModuleType("utils.auth_utils")

def _stub_get_current_user_id(authorization):
    """Stub for get_current_user_id - returns user_id and tenant_id tuple."""
    if authorization is None or (isinstance(authorization, str) and not authorization.strip()):
        # Return None user_id when no auth (simulates real behavior in speed mode disabled)
        return (None, "tenant1")
    return ("user1", "tenant1")

auth_utils_stub.get_current_user_id = _stub_get_current_user_id
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
sys.modules.setdefault("consts.model", model_stub)
setattr(consts_pkg, "model", model_stub)

# Stub consts.exceptions with real exception classes so isinstance checks work
exceptions_stub = types.ModuleType("consts.exceptions")
class NotFoundException(Exception): pass
class OfficeConversionException(Exception): pass
class UnsupportedFileTypeException(Exception): pass
class FileTooLargeException(Exception): pass
exceptions_stub.NotFoundException = NotFoundException
exceptions_stub.OfficeConversionException = OfficeConversionException
exceptions_stub.UnsupportedFileTypeException = UnsupportedFileTypeException
exceptions_stub.FileTooLargeException = FileTooLargeException
sys.modules["consts.exceptions"] = exceptions_stub
setattr(consts_pkg, "exceptions", exceptions_stub)


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


# Mock authorization header for tests
MOCK_AUTH = "Bearer mock_token"
MOCK_AUTH_NONE = None


# --- Tests ---

@pytest.mark.asyncio
async def test_options_route_ok():
    resp = await file_management_app.options_route("any/path")
    assert resp.status_code == 200
    assert resp.body == b'{"detail":"OK"}'


@pytest.mark.asyncio
async def test_upload_files_success(monkeypatch):
    async def fake_upload_impl(dest, files, folder, index_name, user_id=None):
        return [], ["/abs/path1"], ["a.txt"]

    monkeypatch.setattr(file_management_app, "upload_files_impl", fake_upload_impl)

    result = await file_management_app.upload_files(
        file=[make_upload_file("a.txt")], destination="local", folder="attachments", index_name=None,
        authorization=MOCK_AUTH
    )
    assert result.status_code == 200
    content = result.body.decode()
    assert "Files uploaded successfully" in content
    assert "a.txt" in content and "/abs/path1" in content


@pytest.mark.asyncio
async def test_upload_files_no_files_bad_request():
    with pytest.raises(Exception) as ei:
        await file_management_app.upload_files(
            file=[], destination="local", folder="attachments", index_name=None,
            authorization=MOCK_AUTH
        )
    assert "No files in the request" in str(ei.value)


@pytest.mark.asyncio
async def test_upload_files_no_valid_files_uploaded(monkeypatch):
    async def fake_upload_impl(dest, files, folder, index_name, user_id=None):
        return ["err"], [], []

    monkeypatch.setattr(file_management_app, "upload_files_impl", fake_upload_impl)
    with pytest.raises(Exception) as ei:
        await file_management_app.upload_files(
            file=[make_upload_file("x.txt")], destination="minio", folder="attachments", index_name=None,
            authorization=MOCK_AUTH
        )
    assert "No valid files uploaded" in str(ei.value)


@pytest.mark.asyncio
async def test_upload_files_internal_error(monkeypatch):
    """Test upload_files with internal error returns 500."""
    async def fake_upload_impl(dest, files, folder, index_name, user_id=None):
        raise RuntimeError("Storage failed")

    monkeypatch.setattr(file_management_app, "upload_files_impl", fake_upload_impl)
    with pytest.raises(Exception) as ei:
        await file_management_app.upload_files(
            file=[make_upload_file("a.txt")], destination="local", folder="attachments", index_name=None,
            authorization=MOCK_AUTH
        )
    assert "File upload error" in str(ei.value)


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


# --- storage_upload_files tests ---

@pytest.mark.asyncio
async def test_storage_upload_files_knowledge_base_folder(monkeypatch):
    """Test storage_upload_files with knowledge_base folder (shared, no user isolation)."""
    async def fake_upload(files, folder, user_id=None):
        return [{"success": True, "file_name": "shared.pdf", "key": f"{folder}/shared.pdf"}]

    monkeypatch.setattr(file_management_app, "upload_to_minio", fake_upload)

    f1 = make_upload_file("shared.pdf")
    result = await file_management_app.storage_upload_files(
        files=[f1],
        folder="knowledge_base",
        authorization=MOCK_AUTH
    )
    assert result["message"].startswith("Processed 1")
    assert result["success_count"] == 1
    assert result["failed_count"] == 0


@pytest.mark.asyncio
async def test_storage_upload_files_attachments_folder_user_isolation(monkeypatch):
    """Test storage_upload_files with attachments folder uses user_id for isolation."""
    captured_params = {}

    async def fake_upload(files, folder, user_id=None):
        captured_params["folder"] = folder
        captured_params["user_id"] = user_id
        return [{"success": True, "file_name": "private.txt"}]

    monkeypatch.setattr(file_management_app, "upload_to_minio", fake_upload)

    f1 = make_upload_file("private.txt")
    result = await file_management_app.storage_upload_files(
        files=[f1],
        folder="attachments",
        authorization=MOCK_AUTH
    )
    # Folder should be prefixed with user_id
    assert captured_params["folder"] == "attachments/user1"
    assert captured_params["user_id"] == "user1"
    assert result["success_count"] == 1


@pytest.mark.asyncio
async def test_storage_upload_files_attachments_no_auth_uses_raw_folder(monkeypatch):
    """Test storage_upload_files without auth uses raw folder name."""
    captured_params = {}

    async def fake_upload(files, folder, user_id=None):
        captured_params["folder"] = folder
        captured_params["user_id"] = user_id
        return [{"success": True, "file_name": "test.txt"}]

    monkeypatch.setattr(file_management_app, "upload_to_minio", fake_upload)

    f1 = make_upload_file("test.txt")
    result = await file_management_app.storage_upload_files(
        files=[f1],
        folder="attachments",
        authorization=MOCK_AUTH_NONE
    )
    # Without user_id, folder should be raw value
    assert captured_params["folder"] == "attachments"
    assert captured_params["user_id"] is None
    assert result["success_count"] == 1


@pytest.mark.asyncio
async def test_storage_upload_files_counts(monkeypatch):
    async def fake_upload(files, folder, user_id=None):
        return [
            {"success": True, "file_name": "a.txt"},
            {"success": False, "file_name": "b.txt", "error": "x"},
        ]

    monkeypatch.setattr(file_management_app, "upload_to_minio", fake_upload)
    f1 = make_upload_file("a.txt")
    f2 = make_upload_file("b.txt")
    result = await file_management_app.storage_upload_files(
        files=[f1, f2],
        folder="attachments",
        authorization=MOCK_AUTH
    )
    assert result["message"].startswith("Processed 2")
    assert result["success_count"] == 1
    assert result["failed_count"] == 1
    assert len(result["results"]) == 2


@pytest.mark.asyncio
async def test_storage_upload_files_internal_error(monkeypatch):
    """Test storage_upload_files with internal error returns 500."""
    async def fake_upload(files, folder, user_id=None):
        raise RuntimeError("MinIO connection failed")

    monkeypatch.setattr(file_management_app, "upload_to_minio", fake_upload)
    f1 = make_upload_file("a.txt")

    with pytest.raises(Exception) as ei:
        await file_management_app.storage_upload_files(
            files=[f1],
            folder="attachments",
            authorization=MOCK_AUTH
        )
    assert "Storage upload error" in str(ei.value)


# --- get_storage_files tests ---

@pytest.mark.asyncio
async def test_get_storage_files_include_and_strip_urls(monkeypatch):
    async def fake_list(prefix, limit):
        return [
            {"name": "a", "url": "http://u", "key": "knowledge_base/a.txt"},
            {"name": "b", "key": "attachments/user1/b.txt"}
        ]

    monkeypatch.setattr(file_management_app, "list_files_impl", fake_list)
    # include URLs
    out1 = await file_management_app.get_storage_files(
        prefix="", limit=10, include_urls=True, authorization=MOCK_AUTH
    )
    assert out1["total"] == 2
    assert out1["files"][0]["url"] == "http://u"
    # strip URLs
    out2 = await file_management_app.get_storage_files(
        prefix="", limit=10, include_urls=False, authorization=MOCK_AUTH
    )
    assert out2["total"] == 2
    assert "url" not in out2["files"][0]


@pytest.mark.asyncio
async def test_get_storage_files_with_user_id_filters_by_access(monkeypatch):
    """Test that get_storage_files filters files based on user access control."""
    async def fake_list(prefix, limit):
        return [
            {"name": "a", "key": "knowledge_base/shared.txt"},
            {"name": "b", "key": "attachments/user1/mine.txt"},
            {"name": "c", "key": "attachments/user2/theirs.txt"},  # Should be filtered out
            {"name": "d", "key": "attachments/another_user/private.txt"},  # Should be filtered out
        ]

    monkeypatch.setattr(file_management_app, "list_files_impl", fake_list)

    out = await file_management_app.get_storage_files(
        prefix="", limit=10, include_urls=False, authorization=MOCK_AUTH
    )
    # user1 can access knowledge_base and attachments/user1
    keys = [f["key"] for f in out["files"]]
    assert "knowledge_base/shared.txt" in keys
    assert "attachments/user1/mine.txt" in keys
    assert "attachments/user2/theirs.txt" not in keys
    assert "attachments/another_user/private.txt" not in keys


@pytest.mark.asyncio
async def test_get_storage_files_no_auth_only_knowledge_base(monkeypatch):
    """Test that unauthenticated requests only see knowledge_base files."""
    async def fake_list(prefix, limit):
        return [
            {"name": "a", "key": "knowledge_base/shared.txt"},
            {"name": "b", "key": "attachments/user1/mine.txt"},
        ]

    monkeypatch.setattr(file_management_app, "list_files_impl", fake_list)

    out = await file_management_app.get_storage_files(
        prefix="", limit=10, include_urls=False, authorization=MOCK_AUTH_NONE
    )
    # Without auth, only knowledge_base files should be visible
    keys = [f["key"] for f in out["files"]]
    assert "knowledge_base/shared.txt" in keys
    assert "attachments/user1/mine.txt" not in keys


@pytest.mark.asyncio
async def test_get_storage_files_error(monkeypatch):
    async def boom(prefix, limit):
        raise RuntimeError("oops")

    monkeypatch.setattr(file_management_app, "list_files_impl", boom)
    with pytest.raises(Exception) as ei:
        await file_management_app.get_storage_files(
            prefix="p", limit=1, include_urls=True, authorization=MOCK_AUTH
        )
    assert "Failed to get file list" in str(ei.value) or "Get storage files error" in str(ei.value)


# --- get_storage_file tests ---

@pytest.mark.asyncio
async def test_get_storage_file_redirect(monkeypatch):
    async def fake_get_url(object_name, expires):
        return {"success": True, "url": "http://example.com/a"}

    monkeypatch.setattr(file_management_app, "get_file_url_impl", fake_get_url)
    resp = await file_management_app.get_storage_file(
        object_name="knowledge_base/a.txt",
        download="redirect",
        expires=60,
        filename="a.txt",
        authorization=MOCK_AUTH
    )
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
    resp = await file_management_app.get_storage_file(
        object_name="attachments/user1/a.txt",
        download="stream",
        expires=60,
        filename="a.txt",
        authorization=MOCK_AUTH
    )
    assert resp.headers["content-type"].startswith("text/plain")
    assert resp.media_type == "text/plain"
    # Content-Disposition should be "attachment" not "inline", and filename should be extracted from object_name
    content_disposition = resp.headers.get("content-disposition", "")
    assert "attachment" in content_disposition
    assert "a.txt" in content_disposition
    # consume stream
    chunks = []
    async for part in resp.body_iterator:  # type: ignore[attr-defined]
        chunks.append(part)
    assert b"chunk1" in b"".join(chunks)


@pytest.mark.asyncio
async def test_get_storage_file_base64_success(monkeypatch):
    """get_storage_file should return JSON with base64 content when download=base64."""
    async def fake_get_stream(object_name):
        class FakeStream:
            def read(self):
                return b"hello-bytes"

        return FakeStream(), "image/png"

    monkeypatch.setattr(file_management_app, "get_file_stream_impl", fake_get_stream)

    resp = await file_management_app.get_storage_file(
        object_name="attachments/user1/img.png",
        download="base64",
        expires=60,
        filename=None,
        authorization=MOCK_AUTH
    )

    assert resp.status_code == 200
    data = resp.body.decode()
    assert '"success":true' in data
    assert '"content_type":"image/png"' in data


@pytest.mark.asyncio
async def test_get_storage_file_base64_read_error(monkeypatch):
    """get_storage_file should raise HTTPException when reading stream fails in base64 mode."""
    async def fake_get_stream(object_name):
        class FakeStream:
            def read(self):
                raise RuntimeError("read-failed")

        return FakeStream(), "image/png"

    monkeypatch.setattr(file_management_app, "get_file_stream_impl", fake_get_stream)

    with pytest.raises(Exception) as exc_info:
        await file_management_app.get_storage_file(
            object_name="attachments/user1/img.png",
            download="base64",
            expires=60,
            filename=None,
            authorization=MOCK_AUTH
        )

    assert "Failed to read file content for base64 encoding" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_storage_file_metadata(monkeypatch):
    async def fake_get_url(object_name, expires):
        return {"success": True, "url": "http://example.com/x"}

    monkeypatch.setattr(file_management_app, "get_file_url_impl", fake_get_url)
    result = await file_management_app.get_storage_file(
        object_name="knowledge_base/x",
        download="ignore",
        expires=10,
        filename="x.txt",
        authorization=MOCK_AUTH
    )
    assert result["url"] == "http://example.com/x"


@pytest.mark.asyncio
async def test_get_storage_file_error(monkeypatch):
    async def boom_url(object_name, expires):
        raise RuntimeError("x")

    monkeypatch.setattr(file_management_app, "get_file_url_impl", boom_url)
    with pytest.raises(Exception) as ei:
        await file_management_app.get_storage_file(
            object_name="knowledge_base/x",
            download="ignore",
            expires=1,
            filename="x.txt",
            authorization=MOCK_AUTH
        )
    assert "Failed to get file information" in str(ei.value) or "Failed to get file" in str(ei.value)


@pytest.mark.asyncio
async def test_get_storage_file_access_denied_for_attachments(monkeypatch):
    """Test that access to other user's attachments is forbidden."""
    def fake_check_access(object_name, user_id):
        if object_name.startswith("attachments/"):
            expected_prefix = f"attachments/{user_id}"
            return object_name.startswith(expected_prefix)
        return object_name.startswith("knowledge_base/")

    monkeypatch.setattr(file_management_app, "check_file_access", fake_check_access)

    with pytest.raises(Exception) as ei:
        await file_management_app.get_storage_file(
            object_name="attachments/other_user/file.txt",
            download="ignore",
            expires=60,
            filename="file.txt",
            authorization=MOCK_AUTH
        )
    assert "permission" in str(ei.value).lower() or "forbidden" in str(ei.value).lower()


@pytest.mark.asyncio
async def test_get_storage_file_allows_knowledge_base_access(monkeypatch):
    """Test that knowledge_base files are accessible to all authenticated users."""
    async def fake_get_url(object_name, expires):
        return {"success": True, "url": "http://example.com/shared"}

    monkeypatch.setattr(file_management_app, "get_file_url_impl", fake_get_url)

    result = await file_management_app.get_storage_file(
        object_name="knowledge_base/shared.pdf",
        download="redirect",
        expires=60,
        filename="shared.pdf",
        authorization=MOCK_AUTH
    )
    assert result.headers["location"] == "http://example.com/shared"


# --- remove_storage_file tests ---

@pytest.mark.asyncio
async def test_remove_storage_file_success(monkeypatch):
    async def ok_delete(object_name):
        return {"success": True}

    monkeypatch.setattr(file_management_app, "delete_file_impl", ok_delete)
    result = await file_management_app.remove_storage_file(
        object_name="attachments/user1/x",
        authorization=MOCK_AUTH
    )
    assert result["success"] is True


@pytest.mark.asyncio
async def test_remove_storage_file_access_denied(monkeypatch):
    """Test that deletion of other user's file is forbidden."""
    def fake_check_access(object_name, user_id):
        if object_name.startswith("attachments/"):
            expected_prefix = f"attachments/{user_id}"
            return object_name.startswith(expected_prefix)
        return object_name.startswith("knowledge_base/")

    monkeypatch.setattr(file_management_app, "check_file_access", fake_check_access)

    with pytest.raises(Exception) as ei:
        await file_management_app.remove_storage_file(
            object_name="attachments/other_user/file.txt",
            authorization=MOCK_AUTH
        )
    assert "permission" in str(ei.value).lower() or "forbidden" in str(ei.value).lower()


@pytest.mark.asyncio
async def test_remove_storage_file_error(monkeypatch):
    async def boom_delete(object_name):
        raise RuntimeError("nope")

    monkeypatch.setattr(file_management_app, "delete_file_impl", boom_delete)
    with pytest.raises(Exception) as ei:
        await file_management_app.remove_storage_file(
            object_name="attachments/user1/x",
            authorization=MOCK_AUTH
        )
    assert "Failed to delete file" in str(ei.value) or "Remove storage file error" in str(ei.value)


# --- get_storage_file_batch_urls tests ---

@pytest.mark.asyncio
async def test_get_storage_file_batch_urls_validation_error():
    with pytest.raises(Exception) as ei:
        await file_management_app.get_storage_file_batch_urls(
            request_data={}, expires=10, authorization=MOCK_AUTH
        )
    assert "object_names" in str(ei.value)


@pytest.mark.asyncio
async def test_get_storage_file_batch_urls_mixed(monkeypatch):
    def fake_get(object_name, expires):
        # Synchronous stub to match non-awaited usage in implementation
        if object_name == "knowledge_base/ok.txt":
            return {"success": True, "url": "http://u"}
        raise RuntimeError("bad")

    monkeypatch.setattr(file_management_app, "get_file_url_impl", fake_get)
    out = await file_management_app.get_storage_file_batch_urls(
        request_data={"object_names": ["knowledge_base/ok.txt", "knowledge_base/bad.txt"]}, expires=5, authorization=MOCK_AUTH
    )
    assert out["total"] == 2
    assert out["success_count"] == 1
    assert any(item["object_name"] == "knowledge_base/bad.txt" and item["success"] is False for item in out["results"])


@pytest.mark.asyncio
async def test_get_storage_file_batch_urls_all_denied(monkeypatch):
    """Test batch URLs when all files are denied access."""
    def fake_check_access(object_name, user_id):
        return False  # Deny all access

    def fake_get(object_name, expires):
        return {"success": True, "url": "http://u"}

    monkeypatch.setattr(file_management_app, "check_file_access", fake_check_access)
    monkeypatch.setattr(file_management_app, "get_file_url_impl", fake_get)

    out = await file_management_app.get_storage_file_batch_urls(
        request_data={"object_names": ["knowledge_base/file1.txt", "knowledge_base/file2.txt"]},
        expires=5,
        authorization=MOCK_AUTH
    )
    assert out["total"] == 2
    assert out["success_count"] == 0
    assert out["failed_count"] == 2
    assert all(item["success"] is False and item["error"] == "Access denied" for item in out["results"])


@pytest.mark.asyncio
async def test_get_storage_file_batch_urls_error(monkeypatch):
    """Test batch URLs with internal error returns error in results, not exception."""
    def fake_check_access(object_name, user_id):
        return True

    def fake_get(object_name, expires):
        raise RuntimeError("Internal error")

    monkeypatch.setattr(file_management_app, "check_file_access", fake_check_access)
    monkeypatch.setattr(file_management_app, "get_file_url_impl", fake_get)

    out = await file_management_app.get_storage_file_batch_urls(
        request_data={"object_names": ["knowledge_base/file1.txt"]},
        expires=5,
        authorization=MOCK_AUTH
    )
    # Error should be captured in results, not raised
    assert out["total"] == 1
    assert out["success_count"] == 0
    assert out["failed_count"] == 1
    assert "Internal error" in out["results"][0]["error"]


# --- Tests for build_content_disposition_header ---

def test_build_content_disposition_header_ascii():
    """Test build_content_disposition_header with ASCII filename"""
    result = file_management_app.build_content_disposition_header("test.pdf")
    assert result == 'attachment; filename="test.pdf"'


def test_build_content_disposition_header_non_ascii():
    """Test build_content_disposition_header with non-ASCII filename"""
    result = file_management_app.build_content_disposition_header("测试文件.pdf")
    assert 'attachment; filename=' in result
    assert 'filename*=UTF-8' in result
    assert '测试文件' in result or '%E6%B5%8B%E8%AF%95' in result


def test_build_content_disposition_header_non_ascii_with_extension():
    """Test build_content_disposition_header with non-ASCII filename and extension"""
    result = file_management_app.build_content_disposition_header("文档.docx")
    assert 'attachment; filename=' in result
    assert 'filename*=UTF-8' in result
    assert '.docx' in result


def test_build_content_disposition_header_exception_handling(monkeypatch):
    """Test build_content_disposition_header exception handling"""
    def boom(_value: str, safe: str = "") -> str:
        raise RuntimeError("quote failure")

    monkeypatch.setattr("backend.apps.file_management_app.quote", boom)

    result = file_management_app.build_content_disposition_header("测试.pdf")
    assert 'attachment; filename=' in result
    assert 'filename*=UTF-8' not in result


def test_build_content_disposition_header_inline_ascii():
    """Test build_content_disposition_header with inline=True for ASCII filename"""
    result = file_management_app.build_content_disposition_header("test.pdf", inline=True)
    assert result == 'inline; filename="test.pdf"'
    assert 'attachment' not in result


def test_build_content_disposition_header_inline_non_ascii():
    """Test build_content_disposition_header with inline=True for non-ASCII filename"""
    result = file_management_app.build_content_disposition_header("测试文档.pdf", inline=True)
    assert 'inline; filename=' in result
    assert 'attachment' not in result
    assert 'filename*=UTF-8' in result


def test_build_content_disposition_header_inline_false_explicit():
    """Test build_content_disposition_header with inline=False explicitly"""
    result = file_management_app.build_content_disposition_header("test.pdf", inline=False)
    assert result == 'attachment; filename="test.pdf"'
    assert 'inline' not in result


def test_build_content_disposition_header_inline_exception_handling(monkeypatch):
    """Test build_content_disposition_header inline mode exception handling"""
    def boom(_value: str, safe: str = "") -> str:
        raise RuntimeError("quote failure")

    monkeypatch.setattr("backend.apps.file_management_app.quote", boom)

    result = file_management_app.build_content_disposition_header("中文.pdf", inline=True)
    assert 'inline; filename=' in result
    assert 'attachment' not in result


def test_build_content_disposition_header_empty_filename():
    """Test build_content_disposition_header with empty/None filename"""
    result = file_management_app.build_content_disposition_header(None)
    assert 'attachment; filename="download"' in result


def test_build_content_disposition_header_sanitizes_control_chars():
    """Test that control characters are removed from filename"""
    result = file_management_app.build_content_disposition_header("test\x00file.pdf")
    assert 'testfile.pdf' in result


def test_build_content_disposition_header_sanitizes_backslash():
    """Test that backslash is replaced with underscore"""
    result = file_management_app.build_content_disposition_header("test\\file.pdf")
    assert '_' in result
    assert '\\' not in result


def test_build_content_disposition_header_sanitizes_leading_dots():
    """Test that leading dots are removed (Windows restriction)"""
    result = file_management_app.build_content_disposition_header(".hidden.pdf")
    assert '.hidden.pdf' not in result or result == 'attachment; filename="hidden.pdf"'


# --- Tests for get_storage_file with filename parameter ---

@pytest.mark.asyncio
async def test_get_storage_file_stream_with_filename(monkeypatch):
    """Test get_storage_file stream mode with filename parameter"""
    async def fake_get_stream(object_name):
        async def gen():
            yield b"chunk1"
        return gen(), "application/pdf"

    monkeypatch.setattr(file_management_app, "get_file_stream_impl", fake_get_stream)
    resp = await file_management_app.get_storage_file(
        object_name="attachments/user1/file.pdf",
        download="stream",
        expires=60,
        filename="原始文件名.pdf",
        authorization=MOCK_AUTH
    )
    assert resp.media_type == "application/pdf"
    content_disposition = resp.headers.get("content-disposition", "")
    assert "原始文件名.pdf" in content_disposition or "filename*=UTF-8" in content_disposition


@pytest.mark.asyncio
async def test_get_storage_file_stream_without_filename(monkeypatch):
    """Test get_storage_file stream mode without filename parameter (extract from object_name)"""
    async def fake_get_stream(object_name):
        async def gen():
            yield b"chunk1"
        return gen(), "text/plain"

    monkeypatch.setattr(file_management_app, "get_file_stream_impl", fake_get_stream)
    resp = await file_management_app.get_storage_file(
        object_name="attachments/user1/test.txt",
        download="stream",
        expires=60,
        filename=None,
        authorization=MOCK_AUTH
    )
    assert resp.media_type == "text/plain"
    content_disposition = resp.headers.get("content-disposition", "")
    assert "test.txt" in content_disposition


@pytest.mark.asyncio
async def test_get_storage_file_stream_error(monkeypatch):
    """Test get_storage_file stream mode error handling"""
    async def fake_get_stream(object_name):
        raise RuntimeError("Stream error")

    monkeypatch.setattr(file_management_app, "get_file_stream_impl", fake_get_stream)
    with pytest.raises(Exception) as ei:
        await file_management_app.get_storage_file(
            object_name="attachments/user1/test.txt",
            download="stream",
            expires=60,
            filename="test.txt",
            authorization=MOCK_AUTH
        )
    assert "Failed to get file information" in str(ei.value) or "Failed to get file" in str(ei.value)


# --- Tests for download_datamate_file ---

@pytest.mark.asyncio
async def test_download_datamate_file_with_url(monkeypatch):
    """Test download_datamate_file with full URL"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"file content"
    mock_response.headers = {"Content-Type": "application/pdf", "Content-Disposition": 'attachment; filename="test.pdf"'}
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr("httpx.AsyncClient", lambda **kwargs: mock_client)

    resp = await file_management_app.download_datamate_file(
        url="http://example.com/api/data-management/datasets/123/files/456/download",
        base_url=None,
        dataset_id=None,
        file_id=None,
        filename="test.pdf",
        authorization=None,
    )
    assert resp.media_type == "application/pdf"
    content_disposition = resp.headers.get("content-disposition", "")
    assert "test.pdf" in content_disposition


@pytest.mark.asyncio
async def test_download_datamate_file_with_parts(monkeypatch):
    """Test download_datamate_file with base_url, dataset_id, file_id"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"file content"
    mock_response.headers = {"Content-Type": "application/pdf"}
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr("httpx.AsyncClient", lambda **kwargs: mock_client)

    resp = await file_management_app.download_datamate_file(
        url=None,
        base_url="http://example.com",
        dataset_id="123",
        file_id="456",
        filename=None,
        authorization=None,
    )
    assert resp.media_type == "application/pdf"


@pytest.mark.asyncio
async def test_download_datamate_file_404_error(monkeypatch):
    """Test download_datamate_file with 404 error"""
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.headers = {}
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr("httpx.AsyncClient", lambda **kwargs: mock_client)

    with pytest.raises(Exception) as ei:
        await file_management_app.download_datamate_file(
            url="http://example.com/api/data-management/datasets/123/files/456/download",
            base_url=None,
            dataset_id=None,
            file_id=None,
            filename=None,
            authorization=None,
        )
    assert "File not found" in str(ei.value)


@pytest.mark.asyncio
async def test_download_datamate_file_http_error(monkeypatch):
    """Test download_datamate_file with HTTP error"""
    import httpx

    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=httpx.HTTPError("Network error"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr("httpx.AsyncClient", lambda **kwargs: mock_client)

    with pytest.raises(Exception) as ei:
        await file_management_app.download_datamate_file(
            url="http://example.com/api/data-management/datasets/123/files/456/download",
            base_url=None,
            dataset_id=None,
            file_id=None,
            filename=None,
            authorization=None,
        )
    assert "Failed to download file from URL" in str(ei.value)


@pytest.mark.asyncio
async def test_download_datamate_file_missing_params():
    """Test download_datamate_file with missing parameters"""
    with pytest.raises(Exception) as ei:
        await file_management_app.download_datamate_file(
            url=None,
            base_url=None,
            dataset_id=None,
            file_id=None,
            filename=None,
            authorization=None,
        )
    assert "Either url or (base_url, dataset_id, file_id) must be provided" in str(ei.value)


@pytest.mark.asyncio
async def test_download_datamate_file_extract_filename_from_content_disposition(monkeypatch):
    """Test download_datamate_file extracting filename from Content-Disposition header"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"file content"
    mock_response.headers = {"Content-Type": "application/pdf", "Content-Disposition": 'attachment; filename="extracted.pdf"'}
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr("httpx.AsyncClient", lambda **kwargs: mock_client)

    resp = await file_management_app.download_datamate_file(
        url="http://example.com/api/data-management/datasets/123/files/456/download",
        base_url=None,
        dataset_id=None,
        file_id=None,
        filename=None,
        authorization=None,
    )
    content_disposition = resp.headers.get("content-disposition", "")
    assert "extracted.pdf" in content_disposition


@pytest.mark.asyncio
async def test_download_datamate_file_extract_filename_from_url(monkeypatch):
    """Test download_datamate_file extracting filename from URL path"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"file content"
    mock_response.headers = {"Content-Type": "application/pdf"}
    mock_response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr("httpx.AsyncClient", lambda **kwargs: mock_client)

    resp = await file_management_app.download_datamate_file(
        url="http://example.com/api/data-management/datasets/123/files/456/download",
        base_url=None,
        dataset_id=None,
        file_id=None,
        filename=None,
        authorization=None,
    )
    content_disposition = resp.headers.get("content-disposition", "")
    assert "attachment" in content_disposition


@pytest.mark.asyncio
async def test_download_datamate_file_with_authorization(monkeypatch):
    """Test download_datamate_file with authorization header"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"file content"
    mock_response.headers = {"Content-Type": "application/pdf"}
    mock_response.raise_for_status = MagicMock()

    call_args_list = []
    async def fake_httpx_get(url, headers=None, follow_redirects=True):
        call_args_list.append((url, headers))
        return mock_response

    mock_client = MagicMock()
    mock_client.get = fake_httpx_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr("httpx.AsyncClient", lambda **kwargs: mock_client)

    await file_management_app.download_datamate_file(
        url="http://example.com/api/data-management/datasets/123/files/456/download",
        base_url=None,
        dataset_id=None,
        file_id=None,
        filename=None,
        authorization="Bearer token123",
    )
    assert len(call_args_list) > 0
    assert call_args_list[0][1].get("Authorization") == "Bearer token123"


@pytest.mark.asyncio
async def test_download_datamate_file_unexpected_exception(monkeypatch):
    """Unexpected exceptions should surface with new 500 message."""

    def fail_normalize(_url: str):
        raise ValueError("boom")

    monkeypatch.setattr(
        file_management_app,
        "_normalize_datamate_download_url",
        fail_normalize,
    )

    with pytest.raises(Exception) as exc:
        await file_management_app.download_datamate_file(
            url="http://example.com/api/data-management/datasets/123/files/456/download",
            base_url=None,
            dataset_id=None,
            file_id=None,
            filename=None,
            authorization=None,
        )
    assert "Failed to download file: boom" in str(exc.value)


@pytest.mark.asyncio
async def test_download_datamate_file_internal_error(monkeypatch):
    """Test download_datamate_file with internal unexpected error."""
    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=RuntimeError("Unexpected error"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr("httpx.AsyncClient", lambda **kwargs: mock_client)

    with pytest.raises(Exception) as exc:
        await file_management_app.download_datamate_file(
            url="http://example.com/api/data-management/datasets/123/files/456/download",
            base_url=None,
            dataset_id=None,
            file_id=None,
            filename=None,
            authorization=None,
        )
    assert "Failed to download file" in str(exc.value)


# --- Tests for _normalize_datamate_download_url ---

def test_normalize_datamate_download_url_valid():
    """Test _normalize_datamate_download_url with valid URL"""
    url = "http://example.com/api/data-management/datasets/123/files/456/download"
    result = file_management_app._normalize_datamate_download_url(url)
    assert result == url


def test_normalize_datamate_download_url_adds_scheme():
    """URLs without scheme should default to http://"""
    url = "example.com/api/data-management/datasets/123/files/456/download"
    result = file_management_app._normalize_datamate_download_url(url)
    assert result.startswith("http://example.com")


def test_normalize_datamate_download_url_with_prefix():
    """Test _normalize_datamate_download_url with URL prefix"""
    url = "http://example.com/prefix/api/data-management/datasets/123/files/456/download"
    result = file_management_app._normalize_datamate_download_url(url)
    assert "/prefix/api/data-management/datasets/123/files/456/download" in result


def test_normalize_datamate_download_url_missing_data_management():
    """Test _normalize_datamate_download_url with missing data-management segment"""
    with pytest.raises(Exception) as ei:
        file_management_app._normalize_datamate_download_url("http://example.com/invalid/url")
    assert "missing 'data-management' segment" in str(ei.value)


def test_normalize_datamate_download_url_invalid_structure():
    """Test _normalize_datamate_download_url with invalid URL structure"""
    with pytest.raises(Exception) as ei:
        file_management_app._normalize_datamate_download_url("http://example.com/data-management/invalid")
    assert "unable to parse dataset_id or file_id" in str(ei.value)


# --- Tests for _build_datamate_url_from_parts ---

def test_build_datamate_url_from_parts_with_api():
    """Test _build_datamate_url_from_parts with base_url ending with /api"""
    result = file_management_app._build_datamate_url_from_parts(
        "http://example.com/api",
        "123",
        "456"
    )
    assert "/api/data-management/datasets/123/files/456/download" in result


def test_build_datamate_url_from_parts_without_scheme():
    """base_url without scheme should default to http://"""
    result = file_management_app._build_datamate_url_from_parts(
        "example.com",
        "123",
        "456"
    )
    assert result.startswith("http://example.com/api/")


def test_build_datamate_url_from_parts_without_api():
    """Test _build_datamate_url_from_parts with base_url without /api"""
    result = file_management_app._build_datamate_url_from_parts(
        "http://example.com",
        "123",
        "456"
    )
    assert "/api/data-management/datasets/123/files/456/download" in result


def test_build_datamate_url_from_parts_with_slash():
    """Test _build_datamate_url_from_parts with base_url ending with slash"""
    result = file_management_app._build_datamate_url_from_parts(
        "http://example.com/",
        "123",
        "456"
    )
    assert "/api/data-management/datasets/123/files/456/download" in result


def test_build_datamate_url_from_parts_appends_api_segment():
    """Ensure /api is appended when missing from base path"""
    result = file_management_app._build_datamate_url_from_parts(
        "http://example.com/service",
        "123",
        "456"
    )
    assert result.startswith("http://example.com/service/api/")


def test_build_datamate_url_from_parts_defaults_api_when_no_path():
    """Ensure empty base path defaults to /api"""
    result = file_management_app._build_datamate_url_from_parts(
        "http://example.com",
        "123",
        "456"
    )
    assert result.startswith("http://example.com/api/")


def test_build_datamate_url_from_parts_trailing_slash_branch(monkeypatch):
    """Force branch where rstrip result still ends with slash."""

    class DummyPath:
        def rstrip(self, chars=None):
            return "/prefix/"

    class DummyParseResult:
        scheme = "http"
        netloc = "example.com"
        path = DummyPath()

    def fake_urlparse(_url: str):
        return DummyParseResult()

    monkeypatch.setattr("backend.apps.file_management_app.urlparse", fake_urlparse)

    result = file_management_app._build_datamate_url_from_parts(
        "http://placeholder",
        "123",
        "456"
    )
    assert result.startswith("http://example.com/prefix/api/")


def test_build_datamate_url_from_parts_empty_base_url():
    """Test _build_datamate_url_from_parts with empty base_url"""
    with pytest.raises(Exception) as ei:
        file_management_app._build_datamate_url_from_parts("", "123", "456")
    assert "base_url is required" in str(ei.value)


# --- Tests for _ensure_http_scheme ---

def test_ensure_http_scheme_empty():
    """Test _ensure_http_scheme with empty URL raises error"""
    with pytest.raises(Exception) as ei:
        file_management_app._ensure_http_scheme("")
    assert "URL cannot be empty" in str(ei.value)


def test_ensure_http_scheme_invalid_scheme():
    """Test _ensure_http_scheme with invalid scheme raises error"""
    with pytest.raises(Exception) as ei:
        file_management_app._ensure_http_scheme("ftp://example.com/file")
    assert "http:// or https://" in str(ei.value)


def test_ensure_http_scheme_double_slash():
    """Test _ensure_http_scheme with // prefix"""
    result = file_management_app._ensure_http_scheme("//example.com/file")
    assert result.startswith("http://")


# --- Tests for preview_file endpoint ---

def _make_mock_stream(content: bytes = b"content"):
    """Helper: return a mock boto3 Body with iter_chunks."""
    mock_s = MagicMock()
    mock_s.iter_chunks = MagicMock(return_value=iter([content]))
    mock_s.close = MagicMock()
    return mock_s


@pytest.mark.asyncio
async def test_preview_file_pdf_success(monkeypatch):
    """PDF file: 200 response with inline disposition, Accept-Ranges, ETag."""
    mock_stream = _make_mock_stream(b"PDF content")
    monkeypatch.setattr(file_management_app, "resolve_preview_file",
                        AsyncMock(return_value=("knowledge_base/test.pdf", "application/pdf", 2048)))
    monkeypatch.setattr(file_management_app, "get_preview_stream",
                        MagicMock(return_value=mock_stream))

    resp = await file_management_app.preview_file(
        object_name="knowledge_base/test.pdf",
        filename="test.pdf",
        range_header=None,
        authorization=MOCK_AUTH
    )

    assert resp.media_type == "application/pdf"
    assert resp.status_code == 200
    cd = resp.headers.get("content-disposition", "")
    assert "inline" in cd
    assert "test.pdf" in cd
    assert resp.headers.get("accept-ranges") == "bytes"
    assert resp.headers.get("content-length") == "2048"
    assert resp.headers.get("cache-control") == "public, max-age=3600"
    assert "knowledge_base/test.pdf" in resp.headers.get("etag", "")
    assert resp.background is not None
    await resp.background()
    mock_stream.close.assert_called_once()


@pytest.mark.asyncio
async def test_preview_file_image_success(monkeypatch):
    """Image file: 200 response with correct content type."""
    monkeypatch.setattr(file_management_app, "resolve_preview_file",
                        AsyncMock(return_value=("knowledge_base/photo.png", "image/png", 512)))
    monkeypatch.setattr(file_management_app, "get_preview_stream",
                        MagicMock(return_value=_make_mock_stream(b"PNG data")))

    resp = await file_management_app.preview_file(
        object_name="knowledge_base/photo.png",
        filename="photo.png",
        range_header=None,
        authorization=MOCK_AUTH
    )

    assert resp.media_type == "image/png"
    assert "inline" in resp.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_preview_file_text_success(monkeypatch):
    """Text file: 200 response with correct content type."""
    monkeypatch.setattr(file_management_app, "resolve_preview_file",
                        AsyncMock(return_value=("knowledge_base/readme.txt", "text/plain", 128)))
    monkeypatch.setattr(file_management_app, "get_preview_stream",
                        MagicMock(return_value=_make_mock_stream(b"Hello World")))

    resp = await file_management_app.preview_file(
        object_name="knowledge_base/readme.txt",
        filename="readme.txt",
        range_header=None,
        authorization=MOCK_AUTH
    )

    assert resp.media_type == "text/plain"
    assert "inline" in resp.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_preview_file_without_filename_extracts_from_path(monkeypatch):
    """No filename parameter: extracts name from the last path segment."""
    monkeypatch.setattr(file_management_app, "resolve_preview_file",
                        AsyncMock(return_value=("knowledge_base/subfolder/document.pdf", "application/pdf", 1024)))
    monkeypatch.setattr(file_management_app, "get_preview_stream",
                        MagicMock(return_value=_make_mock_stream()))

    resp = await file_management_app.preview_file(
        object_name="knowledge_base/subfolder/document.pdf",
        filename=None,
        range_header=None,
        authorization=MOCK_AUTH
    )

    assert "document.pdf" in resp.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_preview_file_chinese_filename(monkeypatch):
    """Chinese filename: RFC 5987 UTF-8 encoded in Content-Disposition."""
    monkeypatch.setattr(file_management_app, "resolve_preview_file",
                        AsyncMock(return_value=("knowledge_base/test.pdf", "application/pdf", 1024)))
    monkeypatch.setattr(file_management_app, "get_preview_stream",
                        MagicMock(return_value=_make_mock_stream()))

    resp = await file_management_app.preview_file(
        object_name="knowledge_base/test.pdf",
        filename="测试文档.pdf",
        range_header=None,
        authorization=MOCK_AUTH
    )

    cd = resp.headers.get("content-disposition", "")
    assert "inline" in cd
    assert "filename*=UTF-8" in cd or "测试文档" in cd


@pytest.mark.asyncio
async def test_preview_file_simple_object_name_without_slash(monkeypatch):
    """Object name without slash: uses it directly as display filename."""
    monkeypatch.setattr(file_management_app, "resolve_preview_file",
                        AsyncMock(return_value=("knowledge_base/simple.pdf", "application/pdf", 256)))
    monkeypatch.setattr(file_management_app, "get_preview_stream",
                        MagicMock(return_value=_make_mock_stream()))

    resp = await file_management_app.preview_file(
        object_name="knowledge_base/simple.pdf",
        filename=None,
        range_header=None,
        authorization=MOCK_AUTH
    )

    assert "simple.pdf" in resp.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_preview_file_office_converted_to_pdf(monkeypatch):
    """Office document: resolve returns PDF path; response is application/pdf."""
    monkeypatch.setattr(file_management_app, "resolve_preview_file",
                        AsyncMock(return_value=("knowledge_base/converted/report_abc.pdf", "application/pdf", 8192)))
    monkeypatch.setattr(file_management_app, "get_preview_stream",
                        MagicMock(return_value=_make_mock_stream(b"Converted PDF")))

    resp = await file_management_app.preview_file(
        object_name="knowledge_base/report.docx",
        filename="report.docx",
        range_header=None,
        authorization=MOCK_AUTH
    )

    assert resp.media_type == "application/pdf"
    assert "inline" in resp.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_preview_file_access_denied(monkeypatch):
    """Test preview_file access denied for other user's attachments."""
    def fake_check_access(object_name, user_id):
        if object_name.startswith("attachments/"):
            expected_prefix = f"attachments/{user_id}"
            return object_name.startswith(expected_prefix)
        return object_name.startswith("knowledge_base/")

    monkeypatch.setattr(file_management_app, "check_file_access", fake_check_access)

    with pytest.raises(Exception) as ei:
        await file_management_app.preview_file(
            object_name="attachments/other_user/file.pdf",
            filename=None,
            range_header=None,
            authorization=MOCK_AUTH
        )
    assert "permission" in str(ei.value).lower() or "forbidden" in str(ei.value).lower()


@pytest.mark.asyncio
async def test_preview_file_allows_knowledge_base(monkeypatch):
    """Test preview_file allows knowledge_base files."""
    monkeypatch.setattr(file_management_app, "resolve_preview_file",
                        AsyncMock(return_value=("knowledge_base/shared.pdf", "application/pdf", 1024)))
    monkeypatch.setattr(file_management_app, "get_preview_stream",
                        MagicMock(return_value=_make_mock_stream()))

    resp = await file_management_app.preview_file(
        object_name="knowledge_base/shared.pdf",
        filename=None,
        range_header=None,
        authorization=MOCK_AUTH
    )

    assert resp.status_code == 200
    assert resp.media_type == "application/pdf"


# --- Range request tests ---

@pytest.mark.asyncio
async def test_preview_file_range_request_returns_206(monkeypatch):
    """Valid Range header: 206 with Content-Range and correct Content-Length."""
    mock_stream = _make_mock_stream(b"partial chunk")
    monkeypatch.setattr(file_management_app, "resolve_preview_file",
                        AsyncMock(return_value=("knowledge_base/test.pdf", "application/pdf", 10000)))
    monkeypatch.setattr(file_management_app, "get_preview_stream",
                        MagicMock(return_value=mock_stream))

    resp = await file_management_app.preview_file(
        object_name="knowledge_base/test.pdf",
        filename=None,
        range_header="bytes=0-4095",
        authorization=MOCK_AUTH
    )

    assert resp.status_code == 206
    assert resp.headers.get("content-range") == "bytes 0-4095/10000"
    assert resp.headers.get("content-length") == "4096"
    assert resp.headers.get("accept-ranges") == "bytes"
    assert resp.background is not None
    await resp.background()
    mock_stream.close.assert_called_once()


@pytest.mark.asyncio
async def test_preview_file_range_suffix_form(monkeypatch):
    """Suffix range (bytes=-N): 206 with correct Content-Range."""
    monkeypatch.setattr(file_management_app, "resolve_preview_file",
                        AsyncMock(return_value=("knowledge_base/test.pdf", "application/pdf", 10000)))
    monkeypatch.setattr(file_management_app, "get_preview_stream",
                        MagicMock(return_value=_make_mock_stream(b"tail chunk")))

    resp = await file_management_app.preview_file(
        object_name="knowledge_base/test.pdf",
        filename=None,
        range_header="bytes=-500",
        authorization=MOCK_AUTH
    )

    assert resp.status_code == 206
    assert resp.headers.get("content-range") == "bytes 9500-9999/10000"
    assert resp.headers.get("content-length") == "500"


@pytest.mark.asyncio
async def test_preview_file_range_open_ended(monkeypatch):
    """Open-ended range (bytes=N-): 206 reaching end of file."""
    monkeypatch.setattr(file_management_app, "resolve_preview_file",
                        AsyncMock(return_value=("knowledge_base/test.pdf", "application/pdf", 1000)))
    monkeypatch.setattr(file_management_app, "get_preview_stream",
                        MagicMock(return_value=_make_mock_stream(b"tail")))

    resp = await file_management_app.preview_file(
        object_name="knowledge_base/test.pdf",
        filename=None,
        range_header="bytes=500-",
        authorization=MOCK_AUTH
    )

    assert resp.status_code == 206
    assert resp.headers.get("content-range") == "bytes 500-999/1000"
    assert resp.headers.get("content-length") == "500"


@pytest.mark.asyncio
async def test_preview_file_empty_file_returns_200_without_stream(monkeypatch):
    """Empty file: return 200 with zero content length and no stream fetch."""
    mock_get_stream = MagicMock()
    monkeypatch.setattr(file_management_app, "resolve_preview_file",
                        AsyncMock(return_value=("knowledge_base/empty.txt", "text/plain", 0)))
    monkeypatch.setattr(file_management_app, "get_preview_stream", mock_get_stream)

    resp = await file_management_app.preview_file(
        object_name="knowledge_base/empty.txt",
        filename="empty.txt",
        range_header=None,
        authorization=MOCK_AUTH
    )

    assert resp.status_code == 200
    assert resp.media_type == "text/plain"
    assert resp.headers.get("content-length") == "0"
    mock_get_stream.assert_not_called()


@pytest.mark.asyncio
async def test_preview_file_empty_file_ignores_range_and_returns_200(monkeypatch):
    """Empty file with Range header: still return 200 empty response."""
    mock_get_stream = MagicMock()
    monkeypatch.setattr(file_management_app, "resolve_preview_file",
                        AsyncMock(return_value=("knowledge_base/empty.txt", "text/plain", 0)))
    monkeypatch.setattr(file_management_app, "get_preview_stream", mock_get_stream)

    resp = await file_management_app.preview_file(
        object_name="knowledge_base/empty.txt",
        filename="empty.txt",
        range_header="bytes=0-10",
        authorization=MOCK_AUTH
    )

    assert resp.status_code == 200
    assert resp.headers.get("content-length") == "0"
    mock_get_stream.assert_not_called()


@pytest.mark.asyncio
async def test_preview_file_invalid_range_returns_416(monkeypatch):
    """Out-of-bounds Range: 416 with Content-Range: bytes */total."""
    monkeypatch.setattr(file_management_app, "resolve_preview_file",
                        AsyncMock(return_value=("knowledge_base/test.pdf", "application/pdf", 10000)))

    resp = await file_management_app.preview_file(
        object_name="knowledge_base/test.pdf",
        filename=None,
        range_header="bytes=20000-30000",
        authorization=MOCK_AUTH
    )

    assert resp.status_code == 416
    assert "bytes */10000" in resp.headers.get("content-range", "")


@pytest.mark.asyncio
async def test_preview_file_malformed_range_returns_416(monkeypatch):
    """Malformed Range header: 416."""
    monkeypatch.setattr(file_management_app, "resolve_preview_file",
                        AsyncMock(return_value=("knowledge_base/test.pdf", "application/pdf", 1000)))

    resp = await file_management_app.preview_file(
        object_name="knowledge_base/test.pdf",
        filename=None,
        range_header="invalid-range",
        authorization=MOCK_AUTH
    )

    assert resp.status_code == 416


# --- Exception mapping tests ---

@pytest.mark.asyncio
async def test_preview_file_too_large_error(monkeypatch):
    """FileTooLargeException from resolve_preview_file -> HTTP 413."""
    _FileTooLargeException = sys.modules["consts.exceptions"].FileTooLargeException

    async def fake_resolve(object_name):
        raise _FileTooLargeException("File size 110 MB exceeds the 100 MB preview limit")

    monkeypatch.setattr(file_management_app, "resolve_preview_file", fake_resolve)

    with pytest.raises(Exception) as ei:
        await file_management_app.preview_file(
            object_name="knowledge_base/huge.pdf",
            filename=None,
            range_header=None,
            authorization=MOCK_AUTH
        )
    assert "100 MB" in str(ei.value)


@pytest.mark.asyncio
async def test_preview_file_not_found_from_resolve(monkeypatch):
    """NotFoundException from resolve_preview_file -> HTTP 404."""
    _NotFoundException = sys.modules["consts.exceptions"].NotFoundException

    async def fake_resolve(object_name):
        raise _NotFoundException("The specified key does not exist")

    monkeypatch.setattr(file_management_app, "resolve_preview_file", fake_resolve)

    with pytest.raises(Exception) as ei:
        await file_management_app.preview_file(
            object_name="knowledge_base/missing/file.pdf",
            filename=None,
            range_header=None,
            authorization=MOCK_AUTH
        )
    assert "File not found" in str(ei.value)


@pytest.mark.asyncio
async def test_preview_file_not_found_from_stream(monkeypatch):
    """NotFoundException from get_preview_stream -> HTTP 404."""
    not_found_exception = sys.modules["consts.exceptions"].NotFoundException

    monkeypatch.setattr(file_management_app, "resolve_preview_file",
                        AsyncMock(return_value=("knowledge_base/test.pdf", "application/pdf", 1024)))

    def fake_stream(actual_name, start=None, end=None):
        raise not_found_exception("File not found during streaming")

    monkeypatch.setattr(file_management_app, "get_preview_stream", fake_stream)

    with pytest.raises(Exception) as ei:
        await file_management_app.preview_file(
            object_name="knowledge_base/test.pdf",
            filename=None,
            range_header=None,
            authorization=MOCK_AUTH
        )
    assert "File not found" in str(ei.value)


@pytest.mark.asyncio
async def test_preview_file_unexpected_error_from_stream(monkeypatch):
    """Unexpected exception from get_preview_stream should map to HTTP 500."""
    monkeypatch.setattr(file_management_app, "resolve_preview_file",
                        AsyncMock(return_value=("knowledge_base/test.pdf", "application/pdf", 1024)))

    def fake_stream(actual_name, start=None, end=None):
        raise RuntimeError("stream broken")

    monkeypatch.setattr(file_management_app, "get_preview_stream", fake_stream)

    with pytest.raises(Exception) as ei:
        await file_management_app.preview_file(
            object_name="knowledge_base/test.pdf",
            filename=None,
            range_header=None,
            authorization=MOCK_AUTH
        )
    assert "Failed to preview file" in str(ei.value)


@pytest.mark.asyncio
async def test_preview_file_unsupported_format_error(monkeypatch):
    """UnsupportedFileTypeException from resolve_preview_file -> HTTP 400."""
    _UnsupportedFileTypeException = sys.modules["consts.exceptions"].UnsupportedFileTypeException

    async def fake_resolve(object_name):
        raise _UnsupportedFileTypeException("Unsupported file format for preview")

    monkeypatch.setattr(file_management_app, "resolve_preview_file", fake_resolve)

    with pytest.raises(Exception) as ei:
        await file_management_app.preview_file(
            object_name="knowledge_base/archive.zip",
            filename=None,
            range_header=None,
            authorization=MOCK_AUTH
        )
    assert "not supported for preview" in str(ei.value)


@pytest.mark.asyncio
async def test_preview_file_internal_error(monkeypatch):
    """Unexpected exception from resolve_preview_file -> HTTP 500."""
    async def fake_resolve(object_name):
        raise Exception("Internal server error")

    monkeypatch.setattr(file_management_app, "resolve_preview_file", fake_resolve)

    with pytest.raises(Exception) as ei:
        await file_management_app.preview_file(
            object_name="knowledge_base/test.pdf",
            filename=None,
            range_header=None,
            authorization=MOCK_AUTH
        )
    assert "Failed to preview file" in str(ei.value)
    assert "Internal server error" not in str(ei.value)


@pytest.mark.asyncio
async def test_preview_file_office_conversion_error(monkeypatch):
    """OfficeConversionException (subclass of Exception) -> HTTP 500."""
    _OfficeConversionException = sys.modules["consts.exceptions"].OfficeConversionException

    async def fake_resolve(object_name):
        raise _OfficeConversionException("LibreOffice conversion failed")

    monkeypatch.setattr(file_management_app, "resolve_preview_file", fake_resolve)

    with pytest.raises(Exception) as ei:
        await file_management_app.preview_file(
            object_name="knowledge_base/report.docx",
            filename=None,
            range_header=None,
            authorization=MOCK_AUTH
        )
    assert "Failed to preview file" in str(ei.value)


# --- _parse_range_header unit tests ---

class TestParseRangeHeader:
    """Unit tests for the _parse_range_header helper."""

    def test_full_range(self):
        """bytes=start-end returns (start, end)."""
        assert file_management_app._parse_range_header("bytes=0-1023", 10000) == (0, 1023)

    def test_open_ended_range(self):
        """bytes=N- returns (N, total_size-1)."""
        assert file_management_app._parse_range_header("bytes=500-", 1000) == (500, 999)

    def test_suffix_range(self):
        """bytes=-N returns last N bytes."""
        assert file_management_app._parse_range_header("bytes=-100", 1000) == (900, 999)

    def test_suffix_range_larger_than_file(self):
        """bytes=-N where N > total_size: clamps start to 0."""
        assert file_management_app._parse_range_header("bytes=-5000", 1000) == (0, 999)

    def test_single_byte(self):
        """Single byte range."""
        assert file_management_app._parse_range_header("bytes=0-0", 1000) == (0, 0)

    def test_last_byte(self):
        """Last byte of file."""
        assert file_management_app._parse_range_header("bytes=999-999", 1000) == (999, 999)

    def test_invalid_unit_returns_none(self):
        """Non-bytes unit is rejected."""
        assert file_management_app._parse_range_header("items=0-10", 1000) is None

    def test_start_beyond_file_size_returns_none(self):
        """Start >= total_size is not satisfiable."""
        assert file_management_app._parse_range_header("bytes=1000-1099", 1000) is None

    def test_end_beyond_file_size_is_clamped(self):
        """End >= total_size is clamped to total_size-1 per RFC 7233 §2.1."""
        assert file_management_app._parse_range_header("bytes=0-1000", 1000) == (0, 999)

    def test_inverted_range_returns_none(self):
        """end < start is invalid."""
        assert file_management_app._parse_range_header("bytes=500-100", 1000) is None

    def test_empty_spec_returns_none(self):
        """bytes= with no range spec."""
        assert file_management_app._parse_range_header("bytes=-", 1000) is None

    def test_non_numeric_returns_none(self):
        """Non-numeric values are rejected."""
        assert file_management_app._parse_range_header("bytes=abc-def", 1000) is None

    def test_missing_dash_returns_none(self):
        """bytes=N without '-' is malformed and rejected."""
        assert file_management_app._parse_range_header("bytes=100", 1000) is None

    def test_zero_size_file_returns_none(self):
        """Empty files do not support satisfiable ranges."""
        assert file_management_app._parse_range_header("bytes=0-10", 0) is None

    def test_negative_start_returns_none(self):
        """Negative start values are invalid."""
        assert file_management_app._parse_range_header("bytes=-10-20", 1000) is None
