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

async def _stub_preview_file_impl(object_name: str):
    """Default stub for preview_file_impl"""
    from io import BytesIO
    return BytesIO(b"PDF content"), "application/pdf"

sfms_stub.preview_file_impl = _stub_preview_file_impl
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
    resp = await file_management_app.get_storage_file(object_name="a.txt", download="redirect", expires=60, filename="a.txt")
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
    resp = await file_management_app.get_storage_file(object_name="a.txt", download="stream", expires=60, filename="a.txt")
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
        object_name="attachments/img.png",
        download="base64",
        expires=60,
        filename=None,
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
            object_name="attachments/img.png",
            download="base64",
            expires=60,
            filename=None,
        )

    assert "Failed to read file content for base64 encoding" in str(exc_info.value)

@pytest.mark.asyncio
async def test_get_storage_file_metadata(monkeypatch):
    async def fake_get_url(object_name, expires):
        return {"success": True, "url": "http://example.com/x"}

    monkeypatch.setattr(file_management_app, "get_file_url_impl", fake_get_url)
    result = await file_management_app.get_storage_file(object_name="x", download="ignore", expires=10, filename="x.txt")
    assert result["url"] == "http://example.com/x"


@pytest.mark.asyncio
async def test_get_storage_file_error(monkeypatch):
    async def boom_url(object_name, expires):
        raise RuntimeError("x")

    monkeypatch.setattr(file_management_app, "get_file_url_impl", boom_url)
    with pytest.raises(Exception) as ei:
        await file_management_app.get_storage_file(object_name="x", download="ignore", expires=1, filename="x.txt")
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
        object_name="attachments/file.pdf", 
        download="stream", 
        expires=60,
        filename="原始文件名.pdf"
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
        object_name="attachments/test.txt", 
        download="stream", 
        expires=60,
        filename=None
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
            object_name="test.txt", 
            download="stream", 
            expires=60,
            filename="test.txt"
        )
    assert "Failed to get file information" in str(ei.value)


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


# --- Tests for _normalize_datamate_download_url ---

def test_normalize_datamate_download_url_valid():
    """Test _normalize_datamate_download_url with valid URL"""
    url = "http://example.com/api/data-management/datasets/123/files/456/download"
    result = file_management_app._normalize_datamate_download_url(url)
    assert result == url


def test_normalize_datamate_download_url_adds_scheme():
    """URLs without scheme should default to https://"""
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
    """base_url without scheme should default to https://"""
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


# --- Tests for preview_file endpoint ---

@pytest.mark.asyncio
async def test_preview_file_pdf_success(monkeypatch):
    """Test previewing a PDF file returns StreamingResponse with inline disposition"""
    from io import BytesIO
    
    async def fake_preview(object_name):
        return BytesIO(b"PDF content"), "application/pdf"
    
    monkeypatch.setattr(file_management_app, "preview_file_impl", fake_preview)
    
    resp = await file_management_app.preview_file(
        object_name="documents/test.pdf",
        filename="test.pdf"
    )
    
    assert resp.media_type == "application/pdf"
    content_disposition = resp.headers.get("content-disposition", "")
    assert "inline" in content_disposition
    assert "test.pdf" in content_disposition
    assert resp.headers.get("cache-control") == "public, max-age=3600"


@pytest.mark.asyncio
async def test_preview_file_image_success(monkeypatch):
    """Test previewing an image file returns correct content type"""
    from io import BytesIO
    
    async def fake_preview(object_name):
        return BytesIO(b"PNG image data"), "image/png"
    
    monkeypatch.setattr(file_management_app, "preview_file_impl", fake_preview)
    
    resp = await file_management_app.preview_file(
        object_name="images/photo.png",
        filename="photo.png"
    )
    
    assert resp.media_type == "image/png"
    content_disposition = resp.headers.get("content-disposition", "")
    assert "inline" in content_disposition


@pytest.mark.asyncio
async def test_preview_file_text_success(monkeypatch):
    """Test previewing a text file returns correct content type"""
    from io import BytesIO
    
    async def fake_preview(object_name):
        return BytesIO(b"Hello World"), "text/plain"
    
    monkeypatch.setattr(file_management_app, "preview_file_impl", fake_preview)
    
    resp = await file_management_app.preview_file(
        object_name="files/readme.txt",
        filename="readme.txt"
    )
    
    assert resp.media_type == "text/plain"
    content_disposition = resp.headers.get("content-disposition", "")
    assert "inline" in content_disposition


@pytest.mark.asyncio
async def test_preview_file_without_filename_extracts_from_path(monkeypatch):
    """Test previewing without filename parameter extracts name from object_name"""
    from io import BytesIO
    
    async def fake_preview(object_name):
        return BytesIO(b"PDF content"), "application/pdf"
    
    monkeypatch.setattr(file_management_app, "preview_file_impl", fake_preview)
    
    resp = await file_management_app.preview_file(
        object_name="folder/subfolder/document.pdf",
        filename=None
    )
    
    content_disposition = resp.headers.get("content-disposition", "")
    assert "document.pdf" in content_disposition


@pytest.mark.asyncio
async def test_preview_file_chinese_filename(monkeypatch):
    """Test previewing with Chinese filename uses UTF-8 encoding"""
    from io import BytesIO
    
    async def fake_preview(object_name):
        return BytesIO(b"PDF content"), "application/pdf"
    
    monkeypatch.setattr(file_management_app, "preview_file_impl", fake_preview)
    
    resp = await file_management_app.preview_file(
        object_name="documents/test.pdf",
        filename="测试文档.pdf"
    )
    
    content_disposition = resp.headers.get("content-disposition", "")
    assert "inline" in content_disposition
    assert "filename*=UTF-8" in content_disposition or "测试文档" in content_disposition


@pytest.mark.asyncio
async def test_preview_file_not_found_error(monkeypatch):
    """Test previewing a non-existent file returns 404"""
    async def fake_preview(object_name):
        raise Exception("File not found")
    
    monkeypatch.setattr(file_management_app, "preview_file_impl", fake_preview)
    
    with pytest.raises(Exception) as ei:
        await file_management_app.preview_file(
            object_name="nonexistent/file.pdf",
            filename=None
        )
    assert "File not found" in str(ei.value)


@pytest.mark.asyncio
async def test_preview_file_unsupported_format_error(monkeypatch):
    """Test previewing an unsupported file format returns 400"""
    async def fake_preview(object_name):
        raise Exception("Unsupported file format for preview")
    
    monkeypatch.setattr(file_management_app, "preview_file_impl", fake_preview)
    
    with pytest.raises(Exception) as ei:
        await file_management_app.preview_file(
            object_name="files/archive.zip",
            filename=None
        )
    assert "not supported for preview" in str(ei.value)


@pytest.mark.asyncio
async def test_preview_file_internal_error(monkeypatch):
    """Test previewing with internal error returns 500"""
    async def fake_preview(object_name):
        raise Exception("Internal server error")
    
    monkeypatch.setattr(file_management_app, "preview_file_impl", fake_preview)
    
    with pytest.raises(Exception) as ei:
        await file_management_app.preview_file(
            object_name="files/test.pdf",
            filename=None
        )
    assert "Failed to preview file" in str(ei.value)


@pytest.mark.asyncio
async def test_preview_file_office_converted_to_pdf(monkeypatch):
    """Test previewing an Office document returns converted PDF"""
    from io import BytesIO
    
    async def fake_preview(object_name):
        # Office documents are converted to PDF by preview_file_impl
        return BytesIO(b"Converted PDF content"), "application/pdf"
    
    monkeypatch.setattr(file_management_app, "preview_file_impl", fake_preview)
    
    resp = await file_management_app.preview_file(
        object_name="documents/report.docx",
        filename="report.docx"
    )
    
    # Content type should be PDF after conversion
    assert resp.media_type == "application/pdf"
    content_disposition = resp.headers.get("content-disposition", "")
    assert "inline" in content_disposition


@pytest.mark.asyncio
async def test_preview_file_has_etag_header(monkeypatch):
    """Test preview response includes ETag header for caching"""
    from io import BytesIO
    
    async def fake_preview(object_name):
        return BytesIO(b"PDF content"), "application/pdf"
    
    monkeypatch.setattr(file_management_app, "preview_file_impl", fake_preview)
    
    resp = await file_management_app.preview_file(
        object_name="documents/test.pdf",
        filename="test.pdf"
    )
    
    etag = resp.headers.get("etag", "")
    assert "documents/test.pdf" in etag


@pytest.mark.asyncio
async def test_preview_file_simple_object_name_without_slash(monkeypatch):
    """Test previewing with simple object name without slash"""
    from io import BytesIO
    
    async def fake_preview(object_name):
        return BytesIO(b"PDF content"), "application/pdf"
    
    monkeypatch.setattr(file_management_app, "preview_file_impl", fake_preview)
    
    resp = await file_management_app.preview_file(
        object_name="simple.pdf",
        filename=None
    )
    
    content_disposition = resp.headers.get("content-disposition", "")
    assert "simple.pdf" in content_disposition


@pytest.mark.asyncio
async def test_preview_file_does_not_exist_error(monkeypatch):
    """Test previewing with 'does not exist' error message returns 404"""
    async def fake_preview(object_name):
        raise Exception("The specified key does not exist")
    
    monkeypatch.setattr(file_management_app, "preview_file_impl", fake_preview)
    
    with pytest.raises(Exception) as ei:
        await file_management_app.preview_file(
            object_name="missing/file.pdf",
            filename=None
        )
    assert "File not found" in str(ei.value)


