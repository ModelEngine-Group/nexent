"""
Unit tests for the file management service.
These tests verify the behavior of file upload, download, and management operations
without actual file system or MinIO connections.
All external services and dependencies are mocked to isolate the tests.
"""
import importlib
import os
import sys
import types
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
from io import BytesIO

# Dynamically determine the backend path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.append(backend_dir)

# Apply critical patches before importing any modules
# This prevents real AWS/MinIO/Elasticsearch calls during import
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

# Create a full mock for MinioClient to avoid initialization issues
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()
patch('backend.database.client.MinioClient', return_value=minio_mock).start()
patch('backend.database.client.boto3.client', return_value=MagicMock()).start()
patch('backend.database.client.minio_client', minio_mock).start()

# Stub Elasticsearch service module to avoid initializing real client during import
services_stub = types.ModuleType('services')
services_stub.__path__ = []  # Mark as package
sys.modules.setdefault('services', services_stub)

es_stub = types.ModuleType('services.elasticsearch_service')


class _StubElasticSearchService:
    @staticmethod
    async def list_files(index_name, include_chunks=False, es_core=None):
        return {"files": []}


def _stub_get_es_core():
    return None


es_stub.ElasticSearchService = _StubElasticSearchService
es_stub.get_es_core = _stub_get_es_core
sys.modules['services.elasticsearch_service'] = es_stub
setattr(services_stub, 'elasticsearch_service', es_stub)

# Import the service module after mocking external dependencies
file_management_service = importlib.import_module(
    'backend.services.file_management_service')

upload_files_impl = file_management_service.upload_files_impl
upload_to_minio = file_management_service.upload_to_minio
get_file_url_impl = file_management_service.get_file_url_impl
get_file_stream_impl = file_management_service.get_file_stream_impl
delete_file_impl = file_management_service.delete_file_impl
list_files_impl = file_management_service.list_files_impl
preprocess_files_generator = file_management_service.preprocess_files_generator
process_image_file = file_management_service.process_image_file
process_text_file = file_management_service.process_text_file
get_file_description = file_management_service.get_file_description

@pytest.fixture(scope="module", autouse=True)
def setup_patches():
    """Setup global patches for the test module"""
    patches = [
        patch('backend.database.client.db_client', MagicMock()),
        patch('backend.database.attachment_db.minio_client', minio_mock),
        patch('backend.database.attachment_db.upload_fileobj', MagicMock()),
        patch('backend.database.attachment_db.get_file_url', MagicMock()),
        patch('backend.database.attachment_db.get_content_type', MagicMock()),
        patch('backend.database.attachment_db.get_file_stream', MagicMock()),
        patch('backend.database.attachment_db.delete_file', MagicMock()),
        patch('backend.database.attachment_db.list_files', MagicMock()),
        patch('backend.services.file_management_service.save_upload_file', AsyncMock()),
        patch('backend.services.file_management_service.upload_semaphore', MagicMock()),
        patch('backend.services.file_management_service.upload_dir',
              Path("/test/uploads")),
        patch('backend.services.file_management_service.logger', MagicMock())
    ]

    # Start all patches
    for p in patches:
        p.start()

    yield

    # Stop all patches
    for p in patches:
        p.stop()


class TestUploadFilesImpl:
    """Test cases for upload_files_impl function"""

    @pytest.mark.asyncio
    async def test_upload_files_impl_local_success(self):
        """Test successful local file upload"""
        # Create mock UploadFile
        mock_file = MagicMock()
        mock_file.filename = "test.txt"
        mock_file.read = AsyncMock(return_value=b"test content")
        mock_file.seek = AsyncMock()

        with patch('backend.services.file_management_service.save_upload_file', AsyncMock(return_value=True)) as mock_save:
            # Execute
            errors, uploaded_paths, uploaded_names = await upload_files_impl(
                destination="local", file=[mock_file])

            # Assertions
            assert errors == []
            assert len(uploaded_paths) == 1
            assert len(uploaded_names) == 1
            assert uploaded_names[0] == "test.txt"
            mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_files_impl_local_failure(self):
        """Test local file upload failure"""
        # Create mock UploadFile
        mock_file = MagicMock()
        mock_file.filename = "test.txt"

        with patch('backend.services.file_management_service.save_upload_file', AsyncMock(return_value=False)) as mock_save:
            # Execute
            errors, uploaded_paths, uploaded_names = await upload_files_impl(
                destination="local", file=[mock_file])

            # Assertions
            assert len(errors) == 1
            assert "Failed to save file: test.txt" in errors[0]
            assert uploaded_paths == []
            assert uploaded_names == []

    @pytest.mark.asyncio
    async def test_upload_files_impl_local_empty_file(self):
        """Test local upload with empty or invalid file"""
        # Create mock UploadFile with no filename
        mock_file = MagicMock()
        mock_file.filename = None

        with patch('backend.services.file_management_service.save_upload_file', AsyncMock(return_value=True)) as mock_save:
            # Execute
            errors, uploaded_paths, uploaded_names = await upload_files_impl(
                destination="local", file=[mock_file])

            # Assertions
            assert errors == []
            assert len(uploaded_paths) == 1
            assert len(uploaded_names) == 1
            assert uploaded_names[0] == ""
            # Path ends with uploads directory
            assert uploaded_paths[0].endswith("uploads")
            mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_files_impl_minio_success(self):
        """Test successful MinIO file upload"""
        # Create mock UploadFile
        mock_file = MagicMock()
        mock_file.filename = "test.txt"
        mock_file.read = AsyncMock(return_value=b"test content")
        mock_file.seek = AsyncMock()

        with patch('backend.services.file_management_service.upload_to_minio', AsyncMock(return_value=[
            {"success": True, "file_name": "test.txt",
                "object_name": "folder/test.txt"}
        ])) as mock_upload:
            # Execute
            errors, uploaded_paths, uploaded_names = await upload_files_impl(
                destination="minio", file=[mock_file], folder="folder")

            # Assertions
            assert errors == []
            assert len(uploaded_paths) == 1
            assert len(uploaded_names) == 1
            assert uploaded_names[0] == "test.txt"
            assert uploaded_paths[0] == "folder/test.txt"
            mock_upload.assert_called_once_with(
                files=[mock_file], folder="folder")

    @pytest.mark.asyncio
    async def test_upload_files_impl_minio_failure(self):
        """Test MinIO file upload failure"""
        # Create mock UploadFile
        mock_file = MagicMock()
        mock_file.filename = "test.txt"
        mock_file.read = AsyncMock(return_value=b"test content")
        mock_file.seek = AsyncMock()

        with patch('backend.services.file_management_service.upload_to_minio', AsyncMock(return_value=[
            {"success": False, "file_name": "test.txt", "error": "Upload failed"}
        ])) as mock_upload:
            # Execute
            errors, uploaded_paths, uploaded_names = await upload_files_impl(
                destination="minio", file=[mock_file], folder="folder")

            # Assertions
            assert len(errors) == 1
            assert "Failed to upload test.txt: Upload failed" in errors[0]
            assert uploaded_paths == []
            assert uploaded_names == []

    @pytest.mark.asyncio
    async def test_upload_files_impl_minio_unknown_error(self):
        """Test MinIO file upload with unknown error"""
        # Create mock UploadFile
        mock_file = MagicMock()
        mock_file.filename = "test.txt"
        mock_file.read = AsyncMock(return_value=b"test content")
        mock_file.seek = AsyncMock()

        with patch('backend.services.file_management_service.upload_to_minio', AsyncMock(return_value=[
            {"success": False, "file_name": "test.txt"}
        ])) as mock_upload:
            # Execute
            errors, uploaded_paths, uploaded_names = await upload_files_impl(
                destination="minio", file=[mock_file], folder="folder")

            # Assertions
            assert len(errors) == 1
            assert "Failed to upload test.txt: Unknown error" in errors[0]
            assert uploaded_paths == []
            assert uploaded_names == []

    @pytest.mark.asyncio
    async def test_upload_files_impl_invalid_destination(self):
        """Test upload with invalid destination"""
        mock_file = MagicMock()
        mock_file.filename = "test.txt"

        # Execute and assert exception
        with pytest.raises(Exception) as exc_info:
            await upload_files_impl(destination="invalid", file=[mock_file])

        # Assertions
        assert "Invalid destination. Must be 'local' or 'minio'." in str(
            exc_info.value)

    @pytest.mark.asyncio
    async def test_upload_files_impl_multiple_files_mixed_results(self):
        """Test upload with multiple files having mixed success/failure results"""
        # Create mock UploadFiles
        mock_file1 = MagicMock()
        mock_file1.filename = "test1.txt"
        mock_file1.read = AsyncMock(return_value=b"test content 1")
        mock_file1.seek = AsyncMock()

        mock_file2 = MagicMock()
        mock_file2.filename = "test2.txt"
        mock_file2.read = AsyncMock(return_value=b"test content 2")
        mock_file2.seek = AsyncMock()

        with patch('backend.services.file_management_service.upload_to_minio', AsyncMock(return_value=[
            {"success": True, "file_name": "test1.txt",
                "object_name": "folder/test1.txt"},
            {"success": False, "file_name": "test2.txt", "error": "Upload failed"}
        ])) as mock_upload:
            # Execute
            errors, uploaded_paths, uploaded_names = await upload_files_impl(
                destination="minio", file=[mock_file1, mock_file2], folder="folder")

            # Assertions
            assert len(errors) == 1
            assert "Failed to upload test2.txt: Upload failed" in errors[0]
            assert len(uploaded_paths) == 1
            assert len(uploaded_names) == 1
            assert uploaded_names[0] == "test1.txt"
            assert uploaded_paths[0] == "folder/test1.txt"

    @pytest.mark.asyncio
    async def test_upload_files_impl_minio_conflict_resolution(self):
        """When index_name is provided, filenames should be made unique against existing ES docs."""
        # Create mock UploadFiles
        mock_file1 = MagicMock()
        mock_file1.filename = "test.txt"
        mock_file2 = MagicMock()
        mock_file2.filename = "doc.pdf"

        # uploaded results echo original names
        minio_return = [
            {"success": True, "file_name": "test.txt",
                "object_name": "folder/test.txt"},
            {"success": True, "file_name": "doc.pdf",
                "object_name": "folder/doc.pdf"},
        ]

        existing = {
            "files": [
                {"file": "test.txt"},
                {"filename": "doc.pdf"},
            ]
        }

        with patch('backend.services.file_management_service.upload_to_minio', AsyncMock(return_value=minio_return)) as mock_upload, \
                patch('backend.services.file_management_service.get_es_core', MagicMock()) as mock_es_core, \
                patch('backend.services.file_management_service.ElasticSearchService.list_files', AsyncMock(return_value=existing)) as mock_list:

            errors, uploaded_paths, uploaded_names = await upload_files_impl(
                destination="minio", file=[mock_file1, mock_file2], folder="folder", index_name="kb1")

            assert errors == []
            assert uploaded_paths == ["folder/test.txt", "folder/doc.pdf"]
            # Both collide; expect suffixed names
            assert uploaded_names == ["test_1.txt", "doc_1.pdf"]
            mock_upload.assert_called_once()
            mock_list.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_files_impl_minio_conflict_resolution_case_insensitive_duplicates(self):
        """Case-insensitive uniqueness across existing and within-batch duplicates."""
        mock_file1 = MagicMock()
        mock_file1.filename = "DOC.PDF"
        mock_file2 = MagicMock()
        mock_file2.filename = "doc.pdf"

        minio_return = [
            {"success": True, "file_name": "DOC.PDF",
                "object_name": "folder/DOC.PDF"},
            {"success": True, "file_name": "doc.pdf",
                "object_name": "folder/doc.pdf"},
        ]

        existing = {"files": [{"file": "doc.pdf"}]}

        with patch('backend.services.file_management_service.upload_to_minio', AsyncMock(return_value=minio_return)), \
                patch('backend.services.file_management_service.get_es_core', MagicMock()), \
                patch('backend.services.file_management_service.ElasticSearchService.list_files', AsyncMock(return_value=existing)):

            errors, uploaded_paths, uploaded_names = await upload_files_impl(
                destination="minio", file=[mock_file1, mock_file2], folder="folder", index_name="kb1")

            assert errors == []
            assert uploaded_paths == ["folder/DOC.PDF", "folder/doc.pdf"]
            # First collides with existing -> _1; second collides with both existing and first -> _2
            assert uploaded_names == ["DOC_1.PDF", "doc_2.pdf"]

    @pytest.mark.asyncio
    async def test_upload_files_impl_minio_conflict_resolution_es_exception(self):
        """If ES lookup fails, service should warn and leave names unchanged."""
        mock_file = MagicMock()
        mock_file.filename = "a.txt"

        minio_return = [
            {"success": True, "file_name": "a.txt", "object_name": "folder/a.txt"},
        ]

        with patch('backend.services.file_management_service.upload_to_minio', AsyncMock(return_value=minio_return)), \
                patch('backend.services.file_management_service.get_es_core', MagicMock()), \
                patch('backend.services.file_management_service.ElasticSearchService.list_files', AsyncMock(side_effect=Exception("boom"))), \
                patch('backend.services.file_management_service.logger') as mock_logger:

            errors, uploaded_paths, uploaded_names = await upload_files_impl(
                destination="minio", file=[mock_file], folder="folder", index_name="kb1")

            assert errors == []
            assert uploaded_paths == ["folder/a.txt"]
            assert uploaded_names == ["a.txt"]
            mock_logger.warning.assert_called()


class TestUploadToMinio:
    """Test cases for upload_to_minio function"""

    @pytest.mark.asyncio
    async def test_upload_to_minio_success(self):
        """Test successful MinIO file upload"""
        # Create mock UploadFile
        mock_file = MagicMock()
        mock_file.filename = "test.txt"
        mock_file.read = AsyncMock(return_value=b"test content")
        mock_file.seek = AsyncMock()

        with patch('backend.services.file_management_service.upload_fileobj', MagicMock(return_value={
            "success": True, "file_name": "test.txt", "object_name": "folder/test.txt"
        })) as mock_upload:
            # Execute
            results = await upload_to_minio(files=[mock_file], folder="folder")

            # Assertions
            assert len(results) == 1
            assert results[0]["success"] is True
            assert results[0]["file_name"] == "test.txt"
            assert results[0]["object_name"] == "folder/test.txt"
            mock_file.read.assert_called_once()
            mock_file.seek.assert_called_once_with(0)
            mock_upload.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_to_minio_file_read_exception(self):
        """Test MinIO upload with file read exception"""
        # Create mock UploadFile that raises exception on read
        mock_file = MagicMock()
        mock_file.filename = "test.txt"
        mock_file.read = AsyncMock(side_effect=Exception("Read error"))

        with patch('backend.services.file_management_service.logger', MagicMock()) as mock_logger:
            # Execute
            results = await upload_to_minio(files=[mock_file], folder="folder")

            # Assertions
            assert len(results) == 1
            assert results[0]["success"] is False
            assert results[0]["file_name"] == "test.txt"
            assert results[0]["error"] == "An error occurred while processing the file."
            mock_logger.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_to_minio_upload_exception(self):
        """Test MinIO upload with upload_fileobj exception"""
        # Create mock UploadFile
        mock_file = MagicMock()
        mock_file.filename = "test.txt"
        mock_file.read = AsyncMock(return_value=b"test content")
        mock_file.seek = AsyncMock()

        with patch('backend.services.file_management_service.upload_fileobj', MagicMock(side_effect=Exception("Upload error"))) as mock_upload, \
                patch('backend.services.file_management_service.logger', MagicMock()) as mock_logger:
            # Execute
            results = await upload_to_minio(files=[mock_file], folder="folder")

            # Assertions
            assert len(results) == 1
            assert results[0]["success"] is False
            assert results[0]["file_name"] == "test.txt"
            assert results[0]["error"] == "An error occurred while processing the file."
            mock_file.read.assert_called_once()
            # seek is not called when upload_fileobj throws exception
            mock_file.seek.assert_not_called()
            mock_logger.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_to_minio_empty_filename(self):
        """Test MinIO upload with empty filename"""
        # Create mock UploadFile with empty filename
        mock_file = MagicMock()
        mock_file.filename = None
        mock_file.read = AsyncMock(return_value=b"test content")
        mock_file.seek = AsyncMock()

        with patch('backend.services.file_management_service.upload_fileobj', MagicMock(return_value={
            "success": True, "file_name": "", "object_name": "folder/"
        })) as mock_upload:
            # Execute
            results = await upload_to_minio(files=[mock_file], folder="folder")

            # Assertions
            assert len(results) == 1
            assert results[0]["success"] is True
            assert results[0]["file_name"] == ""
            mock_upload.assert_called_once()
            # Verify that empty string was passed as filename
            call_args = mock_upload.call_args
            assert call_args[1]["file_name"] == ""

    @pytest.mark.asyncio
    async def test_upload_to_minio_multiple_files_mixed_results(self):
        """Test MinIO upload with multiple files having mixed success/failure results"""
        # Create mock UploadFiles
        mock_file1 = MagicMock()
        mock_file1.filename = "test1.txt"
        mock_file1.read = AsyncMock(return_value=b"test content 1")
        mock_file1.seek = AsyncMock()

        mock_file2 = MagicMock()
        mock_file2.filename = "test2.txt"
        mock_file2.read = AsyncMock(side_effect=Exception("Read error"))

        with patch('backend.services.file_management_service.upload_fileobj', MagicMock(return_value={
            "success": True, "file_name": "test1.txt", "object_name": "folder/test1.txt"
        })) as mock_upload, \
                patch('backend.services.file_management_service.logger', MagicMock()) as mock_logger:
            # Execute
            results = await upload_to_minio(files=[mock_file1, mock_file2], folder="folder")

            # Assertions
            assert len(results) == 2

            # First file success
            assert results[0]["success"] is True
            assert results[0]["file_name"] == "test1.txt"

            # Second file failure
            assert results[1]["success"] is False
            assert results[1]["file_name"] == "test2.txt"
            assert results[1]["error"] == "An error occurred while processing the file."

            mock_upload.assert_called_once()  # Only called for successful file
            mock_logger.error.assert_called_once()  # Called for failed file

    @pytest.mark.asyncio
    async def test_upload_to_minio_seek_exception(self):
        """Test MinIO upload with seek exception after successful upload"""
        # Create mock UploadFile
        mock_file = MagicMock()
        mock_file.filename = "test.txt"
        mock_file.read = AsyncMock(return_value=b"test content")
        mock_file.seek = AsyncMock(side_effect=Exception("Seek error"))

        with patch('backend.services.file_management_service.upload_fileobj', MagicMock(return_value={
            "success": True, "file_name": "test.txt", "object_name": "folder/test.txt"
        })) as mock_upload, \
                patch('backend.services.file_management_service.logger', MagicMock()) as mock_logger:
            # Execute
            results = await upload_to_minio(files=[mock_file], folder="folder")

            # Assertions
            assert len(results) == 1
            assert results[0]["success"] is False
            assert results[0]["file_name"] == "test.txt"
            assert results[0]["error"] == "An error occurred while processing the file."
            mock_file.read.assert_called_once()
            mock_file.seek.assert_called_once_with(0)
            mock_logger.error.assert_called_once()


class TestGetFileUrlImpl:
    """Test cases for get_file_url_impl function"""

    @pytest.mark.asyncio
    async def test_get_file_url_impl_success(self):
        """Test successful file URL retrieval"""
        # Mock successful result
        mock_result = {
            "success": True,
            "url": "https://example.com/file.txt",
            "expires": 3600
        }

        with patch('backend.services.file_management_service.get_file_url', MagicMock(return_value=mock_result)) as mock_get_url:
            # Execute
            result = await get_file_url_impl(object_name="test/file.txt", expires=3600)

            # Assertions
            assert result == mock_result
            assert result["success"] is True
            assert result["url"] == "https://example.com/file.txt"
            mock_get_url.assert_called_once_with(
                object_name="test/file.txt", expires=3600)

    @pytest.mark.asyncio
    async def test_get_file_url_impl_failure(self):
        """Test file URL retrieval failure"""
        # Mock failed result
        mock_result = {
            "success": False,
            "error": "File not found"
        }

        with patch('backend.services.file_management_service.get_file_url', MagicMock(return_value=mock_result)) as mock_get_url:
            # Execute and assert exception
            with pytest.raises(Exception) as exc_info:
                await get_file_url_impl(object_name="nonexistent/file.txt", expires=3600)

            # Assertions
            assert "File does not exist or cannot be accessed: File not found" in str(
                exc_info.value)
            mock_get_url.assert_called_once_with(
                object_name="nonexistent/file.txt", expires=3600)


class TestGetFileStreamImpl:
    """Test cases for get_file_stream_impl function"""

    @pytest.mark.asyncio
    async def test_get_file_stream_impl_success(self):
        """Test successful file stream retrieval"""
        # Mock successful result
        mock_file_stream = BytesIO(b"test file content")
        mock_content_type = "text/plain"

        with patch('backend.services.file_management_service.get_file_stream', MagicMock(return_value=mock_file_stream)) as mock_get_stream, \
                patch('backend.services.file_management_service.get_content_type', MagicMock(return_value=mock_content_type)) as mock_get_type:
            # Execute
            file_stream, content_type = await get_file_stream_impl(object_name="test/file.txt")

            # Assertions
            assert file_stream == mock_file_stream
            assert content_type == mock_content_type
            mock_get_stream.assert_called_once_with(
                object_name="test/file.txt")
            mock_get_type.assert_called_once_with("test/file.txt")

    @pytest.mark.asyncio
    async def test_get_file_stream_impl_failure(self):
        """Test file stream retrieval failure"""
        # Mock failed result (None file stream)
        with patch('backend.services.file_management_service.get_file_stream', MagicMock(return_value=None)) as mock_get_stream:
            # Execute and assert exception
            with pytest.raises(Exception) as exc_info:
                await get_file_stream_impl(object_name="nonexistent/file.txt")

            # Assertions
            assert "File not found or failed to read from storage" in str(
                exc_info.value)
            mock_get_stream.assert_called_once_with(
                object_name="nonexistent/file.txt")


class TestDeleteFileImpl:
    """Test cases for delete_file_impl function"""

    @pytest.mark.asyncio
    async def test_delete_file_impl_success(self):
        """Test successful file deletion"""
        # Mock successful result
        mock_result = {
            "success": True,
            "message": "File deleted successfully"
        }

        with patch('backend.services.file_management_service.delete_file', MagicMock(return_value=mock_result)) as mock_delete:
            # Execute
            result = await delete_file_impl(object_name="test/file.txt")

            # Assertions
            assert result == mock_result
            assert result["success"] is True
            assert result["message"] == "File deleted successfully"
            mock_delete.assert_called_once_with(object_name="test/file.txt")

    @pytest.mark.asyncio
    async def test_delete_file_impl_failure(self):
        """Test file deletion failure"""
        # Mock failed result
        mock_result = {
            "success": False,
            "error": "File not found"
        }

        with patch('backend.services.file_management_service.delete_file', MagicMock(return_value=mock_result)) as mock_delete:
            # Execute and assert exception
            with pytest.raises(Exception) as exc_info:
                await delete_file_impl(object_name="nonexistent/file.txt")

            # Assertions
            assert "File does not exist or deletion failed: File not found" in str(
                exc_info.value)
            mock_delete.assert_called_once_with(
                object_name="nonexistent/file.txt")


class TestListFilesImpl:
    """Test cases for list_files_impl function"""

    @pytest.mark.asyncio
    async def test_list_files_impl_without_limit(self):
        """Test file listing without limit"""
        # Mock file list
        mock_files = [
            {"name": "folder/file1.txt", "size": 1024},
            {"name": "folder/file2.txt", "size": 2048},
            {"name": "folder/file3.txt", "size": 1536}
        ]

        with patch('backend.services.file_management_service.list_files', MagicMock(return_value=mock_files)) as mock_list:
            # Execute
            result = await list_files_impl(prefix="folder/")

            # Assertions
            assert result == mock_files
            assert len(result) == 3
            mock_list.assert_called_once_with(prefix="folder/")

    @pytest.mark.asyncio
    async def test_list_files_impl_with_limit(self):
        """Test file listing with limit"""
        # Mock file list
        mock_files = [
            {"name": "folder/file1.txt", "size": 1024},
            {"name": "folder/file2.txt", "size": 2048},
            {"name": "folder/file3.txt", "size": 1536},
            {"name": "folder/file4.txt", "size": 512}
        ]

        with patch('backend.services.file_management_service.list_files', MagicMock(return_value=mock_files)) as mock_list:
            # Execute
            result = await list_files_impl(prefix="folder/", limit=2)

            # Assertions
            assert len(result) == 2
            assert result == mock_files[:2]
            assert result[0]["name"] == "folder/file1.txt"
            assert result[1]["name"] == "folder/file2.txt"
            mock_list.assert_called_once_with(prefix="folder/")


class TestProcessImageFile:
    """Test cases for process_image_file function"""

    @pytest.mark.asyncio
    async def test_process_image_file_success(self):
        """Test successful image file processing"""
        with patch('backend.services.file_management_service.convert_image_to_text', return_value="Extracted text from image") as mock_convert:
            # Execute
            result = await process_image_file(
                query="Test query",
                filename="test.jpg",
                file_content=b"image binary data",
                tenant_id="tenant123",
                language="en"
            )

            # Assertions
            assert "Image file test.jpg content" in result
            assert "Extracted text from image" in result
            mock_convert.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_image_file_with_error(self):
        """Test image file processing with error"""
        with patch('backend.services.file_management_service.convert_image_to_text', side_effect=Exception("Processing failed")) as mock_convert:
            # Execute
            result = await process_image_file(
                query="Test query",
                filename="test.jpg",
                file_content=b"image binary data",
                tenant_id="tenant123",
                language="zh"
            )

            # Assertions - expect Chinese messages since language="zh"
            assert "图片文件 test.jpg 内容" in result
            assert "处理图片文件 test.jpg 时出错: Processing failed" in result
            mock_convert.assert_called_once()


class TestProcessTextFile:
    """Test cases for process_text_file function"""

    @pytest.mark.asyncio
    async def test_process_text_file_success(self):
        """Test successful text file processing"""
        # Mock the HTTP response from the data processing service
        mock_response_data = {"text": "Raw text content from API"}
        
        with patch('httpx.AsyncClient.post') as mock_post, \
             patch('backend.services.file_management_service.convert_long_text_to_text', return_value=("Processed text content", "0")) as mock_convert:
            
            # Mock the HTTP response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_response_data
            mock_post.return_value = mock_response
            
            # Execute
            result, truncation_percentage = await process_text_file(
                query="Test query",
                filename="test.txt",
                file_content=b"test file content",
                tenant_id="tenant123",
                language="en"
            )

            # Assertions
            assert "File test.txt content" in result
            assert "Processed text content" in result
            assert truncation_percentage == "0"
            mock_convert.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_text_file_with_error(self):
        """Test text file processing with error"""
        # Mock the HTTP response from the data processing service
        mock_response_data = {"text": "Raw text content from API"}
        
        with patch('httpx.AsyncClient.post') as mock_post, \
             patch('backend.services.file_management_service.convert_long_text_to_text', side_effect=Exception("Processing failed")) as mock_convert:
            
            # Mock the HTTP response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_response_data
            mock_post.return_value = mock_response
            
            # Execute
            result, truncation_percentage = await process_text_file(
                query="Test query",
                filename="test.txt",
                file_content=b"test file content",
                tenant_id="tenant123",
                language="zh"
            )

            # Assertions - expect Chinese messages since language="zh"
            assert "文件 test.txt 内容" in result
            assert "处理文本文件 test.txt 时出错: Processing failed" in result
            assert truncation_percentage is None
            mock_convert.assert_called_once()


class TestGetFileDescription:
    """Test cases for get_file_description function"""

    def test_get_file_description_with_files(self):
        """Test file description generation with files"""
        # Create mock UploadFile objects
        text_file = MagicMock()
        text_file.filename = "document.txt"

        image_file = MagicMock()
        image_file.filename = "photo.jpg"

        # Execute
        result = get_file_description([text_file, image_file])

        # Assertions
        assert "User provided some reference files" in result
        assert "Image file photo.jpg" in result
        assert "File document.txt" in result

    def test_get_file_description_empty_list(self):
        """Test file description generation with empty file list"""
        # Execute
        result = get_file_description([])

        # Assertions
        assert "User provided some reference files" in result
        assert "No files provided" in result


class TestPreprocessFilesGenerator:
    """Test cases for preprocess_files_generator function"""

    @pytest.mark.asyncio
    async def test_preprocess_files_generator_success(self):
        """Test successful file preprocessing generator"""
        file_cache = [
            {
                "filename": "test.txt",
                "content": b"test content",
                "ext": ".txt"
            },
            {
                "filename": "test.jpg",
                "content": b"image data",
                "ext": ".jpg"
            }
        ]

        with patch('backend.services.file_management_service.process_text_file', AsyncMock(return_value=("Processed text", None))) as mock_process_text, \
             patch('backend.services.file_management_service.process_image_file', AsyncMock(return_value="Processed image")) as mock_process_image, \
             patch('backend.services.file_management_service.preprocess_manager') as mock_preprocess_manager:

            # Mock preprocess manager
            mock_preprocess_manager.register_preprocess_task = MagicMock()
            mock_preprocess_manager.unregister_preprocess_task = MagicMock()

            # Execute
            results = []
            async for result in preprocess_files_generator(
                query="Test query",
                file_cache=file_cache,
                tenant_id="tenant123",
                language="en",
                task_id="task123",
                conversation_id=1
            ):
                results.append(result)

            # Assertions
            assert len(results) > 0
            mock_process_text.assert_called_once()
            mock_process_image.assert_called_once()
            mock_preprocess_manager.register_preprocess_task.assert_called_once()
            mock_preprocess_manager.unregister_preprocess_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_preprocess_files_generator_with_errors(self):
        """Test file preprocessing generator with processing errors"""
        file_cache = [
            {
                "filename": "test.txt",
                "content": b"test content",
                "ext": ".txt"
            }
        ]

        with patch('backend.services.file_management_service.process_text_file', AsyncMock(side_effect=Exception("Processing failed"))) as mock_process_text, \
             patch('backend.services.file_management_service.preprocess_manager') as mock_preprocess_manager:

            # Mock preprocess manager
            mock_preprocess_manager.register_preprocess_task = MagicMock()
            mock_preprocess_manager.unregister_preprocess_task = MagicMock()

            # Execute
            results = []
            async for result in preprocess_files_generator(
                query="Test query",
                file_cache=file_cache,
                tenant_id="tenant123",
                language="en",
                task_id="task123",
                conversation_id=1
            ):
                results.append(result)

            # Assertions
            assert len(results) > 0
            mock_process_text.assert_called_once()
            mock_preprocess_manager.register_preprocess_task.assert_called_once()
            mock_preprocess_manager.unregister_preprocess_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_preprocess_files_generator_with_truncation(self):
        """Test file preprocessing generator with file truncation"""
        file_cache = [
            {
                "filename": "test.txt",
                "content": b"test content",
                "ext": ".txt"
            }
        ]

        with patch('backend.services.file_management_service.process_text_file', AsyncMock(return_value=("Processed text", "50"))) as mock_process_text, \
             patch('backend.services.file_management_service.preprocess_manager') as mock_preprocess_manager:

            # Mock preprocess manager
            mock_preprocess_manager.register_preprocess_task = MagicMock()
            mock_preprocess_manager.unregister_preprocess_task = MagicMock()

            # Execute
            results = []
            async for result in preprocess_files_generator(
                query="Test query",
                file_cache=file_cache,
                tenant_id="tenant123",
                language="en",
                task_id="task123",
                conversation_id=1
            ):
                results.append(result)

            # Assertions
            assert len(results) > 0
            mock_process_text.assert_called_once()
            mock_preprocess_manager.register_preprocess_task.assert_called_once()
            mock_preprocess_manager.unregister_preprocess_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_preprocess_files_generator_with_zero_truncation(self):
        """Test file preprocessing generator with zero truncation percentage"""
        file_cache = [
            {
                "filename": "test.txt",
                "content": b"test content",
                "ext": ".txt"
            }
        ]

        with patch('backend.services.file_management_service.process_text_file', AsyncMock(return_value=("Processed text", "0"))) as mock_process_text, \
             patch('backend.services.file_management_service.preprocess_manager') as mock_preprocess_manager:

            # Mock preprocess manager
            mock_preprocess_manager.register_preprocess_task = MagicMock()
            mock_preprocess_manager.unregister_preprocess_task = MagicMock()

            # Execute
            results = []
            async for result in preprocess_files_generator(
                query="Test query",
                file_cache=file_cache,
                tenant_id="tenant123",
                language="en",
                task_id="task123",
                conversation_id=1
            ):
                results.append(result)

            # Assertions
            assert len(results) > 0
            mock_process_text.assert_called_once()
            mock_preprocess_manager.register_preprocess_task.assert_called_once()
            mock_preprocess_manager.unregister_preprocess_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_preprocess_files_generator_with_file_error(self):
        """Test file preprocessing generator with file that has error in cache"""
        file_cache = [
            {
                "filename": "test.txt",
                "content": b"test content",
                "ext": ".txt",
                "error": "File corrupted"
            }
        ]

        with patch('backend.services.file_management_service.preprocess_manager') as mock_preprocess_manager:

            # Mock preprocess manager
            mock_preprocess_manager.register_preprocess_task = MagicMock()
            mock_preprocess_manager.unregister_preprocess_task = MagicMock()

            # Execute
            results = []
            async for result in preprocess_files_generator(
                query="Test query",
                file_cache=file_cache,
                tenant_id="tenant123",
                language="en",
                task_id="task123",
                conversation_id=1
            ):
                results.append(result)

            # Assertions
            assert len(results) > 0
            mock_preprocess_manager.register_preprocess_task.assert_called_once()
            mock_preprocess_manager.unregister_preprocess_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_preprocess_files_generator_empty_cache(self):
        """Test file preprocessing generator with empty file cache"""
        file_cache = []

        with patch('backend.services.file_management_service.preprocess_manager') as mock_preprocess_manager:

            # Mock preprocess manager
            mock_preprocess_manager.register_preprocess_task = MagicMock()
            mock_preprocess_manager.unregister_preprocess_task = MagicMock()

            # Execute
            results = []
            async for result in preprocess_files_generator(
                query="Test query",
                file_cache=file_cache,
                tenant_id="tenant123",
                language="en",
                task_id="task123",
                conversation_id=1
            ):
                results.append(result)

            # Assertions
            assert len(results) > 0  # Should still yield completion message
            mock_preprocess_manager.register_preprocess_task.assert_called_once()
            mock_preprocess_manager.unregister_preprocess_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_preprocess_files_generator_task_cancellation(self):
        """Test file preprocessing generator with task cancellation"""
        file_cache = [
            {
                "filename": "test.txt",
                "content": b"test content",
                "ext": ".txt"
            }
        ]

        with patch('backend.services.file_management_service.preprocess_manager') as mock_preprocess_manager:

            # Mock preprocess manager
            mock_preprocess_manager.register_preprocess_task = MagicMock()
            mock_preprocess_manager.unregister_preprocess_task = MagicMock()

            # Mock current task to be done (cancelled)
            mock_task = MagicMock()
            mock_task.done.return_value = True
            with patch('asyncio.current_task', return_value=mock_task):
                # Execute
                results = []
                async for result in preprocess_files_generator(
                    query="Test query",
                    file_cache=file_cache,
                    tenant_id="tenant123",
                    language="en",
                    task_id="task123",
                    conversation_id=1
                ):
                    results.append(result)

                # Assertions
                assert len(results) > 0
                mock_preprocess_manager.register_preprocess_task.assert_called_once()
                mock_preprocess_manager.unregister_preprocess_task.assert_called_once()


class TestUtilityFunctions:
    """Test cases for utility functions"""

    def test_get_parsing_file_data(self):
        """Test get_parsing_file_data function returns correct structure"""
        from backend.services.file_management_service import get_parsing_file_data
        
        result = get_parsing_file_data(0, 3, "test.txt")
        expected = {
            "params": {
                "index": 1,
                "total": 3,
                "filename": "test.txt"
            }
        }
        assert result == expected
        
        result = get_parsing_file_data(2, 5, "document.pdf")
        expected = {
            "params": {
                "index": 3,
                "total": 5,
                "filename": "document.pdf"
            }
        }
        assert result == expected

    def test_get_truncation_data(self):
        """Test get_truncation_data function returns correct structure"""
        from backend.services.file_management_service import get_truncation_data
        
        result = get_truncation_data("test.txt", 50)
        expected = {
            "params": {
                "filename": "test.txt",
                "percentage": 50
            }
        }
        assert result == expected
        
        result = get_truncation_data("document.pdf", 25)
        expected = {
            "params": {
                "filename": "document.pdf",
                "percentage": 25
            }
        }
        assert result == expected


class TestEdgeCasesAndErrorHandling:
    """Test cases for edge cases and error handling scenarios"""

    @pytest.mark.asyncio
    async def test_upload_files_impl_with_none_file(self):
        """Test upload_files_impl with None file in list"""
        # Create mock UploadFile
        mock_file = MagicMock()
        mock_file.filename = "test.txt"
        mock_file.read = AsyncMock(return_value=b"test content")
        mock_file.seek = AsyncMock()

        with patch('backend.services.file_management_service.save_upload_file', AsyncMock(return_value=True)) as mock_save:
            # Execute with None file in the list
            errors, uploaded_paths, uploaded_names = await upload_files_impl(
                destination="local", file=[mock_file, None])

            # Assertions
            assert errors == []
            assert len(uploaded_paths) == 1  # Only one file processed
            assert len(uploaded_names) == 1
            assert uploaded_names[0] == "test.txt"
            mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_files_impl_with_empty_file_list(self):
        """Test upload_files_impl with empty file list"""
        # Execute with empty file list
        errors, uploaded_paths, uploaded_names = await upload_files_impl(
            destination="local", file=[])

        # Assertions
        assert errors == []
        assert uploaded_paths == []
        assert uploaded_names == []

    @pytest.mark.asyncio
    async def test_upload_to_minio_with_empty_file_list(self):
        """Test upload_to_minio with empty file list"""
        # Execute with empty file list
        results = await upload_to_minio(files=[], folder="folder")

        # Assertions
        assert results == []

    @pytest.mark.asyncio
    async def test_process_text_file_http_error_response(self):
        """Test process_text_file with HTTP error response"""
        # Mock the HTTP response with error status
        mock_response_data = {"detail": "File processing failed"}
        
        with patch('httpx.AsyncClient.post') as mock_post:
            # Mock the HTTP response with error status
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.headers = {"content-type": "application/json"}
            mock_response.json.return_value = mock_response_data
            mock_post.return_value = mock_response
            
            # Execute
            result, truncation_percentage = await process_text_file(
                query="Test query",
                filename="test.txt",
                file_content=b"test file content",
                tenant_id="tenant123",
                language="en"
            )

            # Assertions
            assert "Error processing text file test.txt" in result
            assert "File processing failed (status code: 400)" in result
            assert truncation_percentage is None

    @pytest.mark.asyncio
    async def test_process_text_file_http_error_non_json_response(self):
        """Test process_text_file with HTTP error response that's not JSON"""
        with patch('httpx.AsyncClient.post') as mock_post:
            # Mock the HTTP response with error status and non-JSON content
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.text = "Internal Server Error"
            mock_post.return_value = mock_response
            
            # Execute
            result, truncation_percentage = await process_text_file(
                query="Test query",
                filename="test.txt",
                file_content=b"test file content",
                tenant_id="tenant123",
                language="en"
            )

            # Assertions
            assert "Error processing text file test.txt" in result
            assert "File processing failed (status code: 500)" in result
            assert truncation_percentage is None

    @pytest.mark.asyncio
    async def test_process_text_file_json_decode_error(self):
        """Test process_text_file with JSON decode error"""
        with patch('httpx.AsyncClient.post') as mock_post:
            # Mock the HTTP response with invalid JSON
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.side_effect = ValueError("Invalid JSON")
            mock_post.return_value = mock_response
            
            # Execute
            result, truncation_percentage = await process_text_file(
                query="Test query",
                filename="test.txt",
                file_content=b"test file content",
                tenant_id="tenant123",
                language="en"
            )

            # Assertions
            assert "Error processing text file test.txt" in result
            assert "Invalid JSON" in result
            assert truncation_percentage is None

    def test_get_file_description_with_none_filename(self):
        """Test get_file_description with file having None filename"""
        # Create mock UploadFile with None filename
        mock_file = MagicMock()
        mock_file.filename = None

        # Execute
        result = get_file_description([mock_file])

        # Assertions
        assert "User provided some reference files" in result
        assert "File " in result  # Should handle None filename gracefully

    def test_get_file_description_with_various_file_types(self):
        """Test get_file_description with various file types"""
        # Create mock UploadFiles with different extensions
        image_files = [
            MagicMock(filename="test.jpg"),
            MagicMock(filename="test.jpeg"),
            MagicMock(filename="test.png"),
            MagicMock(filename="test.gif"),
            MagicMock(filename="test.bmp")
        ]
        
        text_files = [
            MagicMock(filename="test.txt"),
            MagicMock(filename="test.pdf"),
            MagicMock(filename="test.docx")
        ]

        # Execute
        result = get_file_description(image_files + text_files)

        # Assertions
        assert "User provided some reference files" in result
        for file in image_files:
            assert f"Image file {file.filename}" in result
        for file in text_files:
            assert f"File {file.filename}" in result

    @pytest.mark.asyncio
    async def test_list_files_impl_with_none_limit(self):
        """Test list_files_impl with None limit"""
        # Mock file list
        mock_files = [
            {"name": "folder/file1.txt", "size": 1024},
            {"name": "folder/file2.txt", "size": 2048},
            {"name": "folder/file3.txt", "size": 1536}
        ]

        with patch('backend.services.file_management_service.list_files', MagicMock(return_value=mock_files)) as mock_list:
            # Execute with None limit
            result = await list_files_impl(prefix="folder/", limit=None)

            # Assertions
            assert result == mock_files
            assert len(result) == 3
            mock_list.assert_called_once_with(prefix="folder/")

    @pytest.mark.asyncio
    async def test_list_files_impl_with_limit_larger_than_files(self):
        """Test list_files_impl with limit larger than available files"""
        # Mock file list
        mock_files = [
            {"name": "folder/file1.txt", "size": 1024},
            {"name": "folder/file2.txt", "size": 2048}
        ]

        with patch('backend.services.file_management_service.list_files', MagicMock(return_value=mock_files)) as mock_list:
            # Execute with limit larger than available files
            result = await list_files_impl(prefix="folder/", limit=10)

            # Assertions
            assert result == mock_files
            assert len(result) == 2
            mock_list.assert_called_once_with(prefix="folder/")


class TestConcurrencyAndFileTypes:
    """Test cases for concurrency control and file type handling"""

    @pytest.mark.asyncio
    async def test_upload_files_impl_semaphore_usage(self):
        """Test that upload_files_impl uses semaphore for local uploads"""
        # Create mock UploadFile
        mock_file = MagicMock()
        mock_file.filename = "test.txt"
        mock_file.read = AsyncMock(return_value=b"test content")
        mock_file.seek = AsyncMock()

        with patch('backend.services.file_management_service.save_upload_file', AsyncMock(return_value=True)) as mock_save, \
             patch('backend.services.file_management_service.upload_semaphore') as mock_semaphore:
            
            # Mock semaphore context manager
            mock_semaphore.__aenter__ = AsyncMock()
            mock_semaphore.__aexit__ = AsyncMock()
            
            # Execute
            errors, uploaded_paths, uploaded_names = await upload_files_impl(
                destination="local", file=[mock_file])

            # Assertions
            assert errors == []
            assert len(uploaded_paths) == 1
            assert len(uploaded_names) == 1
            mock_save.assert_called_once()
            # Verify semaphore was used
            mock_semaphore.__aenter__.assert_called_once()
            mock_semaphore.__aexit__.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_files_impl_no_semaphore_for_minio(self):
        """Test that upload_files_impl doesn't use semaphore for MinIO uploads"""
        # Create mock UploadFile
        mock_file = MagicMock()
        mock_file.filename = "test.txt"
        mock_file.read = AsyncMock(return_value=b"test content")
        mock_file.seek = AsyncMock()

        with patch('backend.services.file_management_service.upload_to_minio', AsyncMock(return_value=[
            {"success": True, "file_name": "test.txt", "object_name": "folder/test.txt"}
        ])) as mock_upload, \
             patch('backend.services.file_management_service.upload_semaphore') as mock_semaphore:
            
            # Execute
            errors, uploaded_paths, uploaded_names = await upload_files_impl(
                destination="minio", file=[mock_file], folder="folder")

            # Assertions
            assert errors == []
            assert len(uploaded_paths) == 1
            mock_upload.assert_called_once()
            # Verify semaphore was NOT used for MinIO
            mock_semaphore.__aenter__.assert_not_called()
            mock_semaphore.__aexit__.assert_not_called()

    @pytest.mark.asyncio
    async def test_preprocess_files_generator_different_file_types(self):
        """Test preprocess_files_generator with different file types"""
        file_cache = [
            {
                "filename": "test.txt",
                "content": b"test content",
                "ext": ".txt"
            },
            {
                "filename": "test.jpg",
                "content": b"image data",
                "ext": ".jpg"
            },
            {
                "filename": "test.jpeg",
                "content": b"image data",
                "ext": ".jpeg"
            },
            {
                "filename": "test.png",
                "content": b"image data",
                "ext": ".png"
            },
            {
                "filename": "test.gif",
                "content": b"image data",
                "ext": ".gif"
            },
            {
                "filename": "test.bmp",
                "content": b"image data",
                "ext": ".bmp"
            },
            {
                "filename": "test.webp",
                "content": b"image data",
                "ext": ".webp"
            },
            {
                "filename": "test.pdf",
                "content": b"pdf data",
                "ext": ".pdf"
            }
        ]

        with patch('backend.services.file_management_service.process_text_file', AsyncMock(return_value=("Processed text", None))) as mock_process_text, \
             patch('backend.services.file_management_service.process_image_file', AsyncMock(return_value="Processed image")) as mock_process_image, \
             patch('backend.services.file_management_service.preprocess_manager') as mock_preprocess_manager:

            # Mock preprocess manager
            mock_preprocess_manager.register_preprocess_task = MagicMock()
            mock_preprocess_manager.unregister_preprocess_task = MagicMock()

            # Execute
            results = []
            async for result in preprocess_files_generator(
                query="Test query",
                file_cache=file_cache,
                tenant_id="tenant123",
                language="en",
                task_id="task123",
                conversation_id=1
            ):
                results.append(result)

            # Assertions
            assert len(results) > 0
            # Should call process_text_file for .txt and .pdf files (2 calls)
            assert mock_process_text.call_count == 2
            # Should call process_image_file for image files (6 calls)
            assert mock_process_image.call_count == 6
            mock_preprocess_manager.register_preprocess_task.assert_called_once()
            mock_preprocess_manager.unregister_preprocess_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_text_file_with_empty_response_text(self):
        """Test process_text_file with empty text in response"""
        # Mock the HTTP response with empty text
        mock_response_data = {"text": ""}
        
        with patch('httpx.AsyncClient.post') as mock_post, \
             patch('backend.services.file_management_service.convert_long_text_to_text', return_value=("Processed text", "0")) as mock_convert:
            
            # Mock the HTTP response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_response_data
            mock_post.return_value = mock_response
            
            # Execute
            result, truncation_percentage = await process_text_file(
                query="Test query",
                filename="test.txt",
                file_content=b"test file content",
                tenant_id="tenant123",
                language="en"
            )

            # Assertions
            assert "File test.txt content" in result
            assert "Processed text" in result
            assert truncation_percentage == "0"
            mock_convert.assert_called_once_with("Test query", "", "tenant123", "en")

    @pytest.mark.asyncio
    async def test_process_text_file_with_missing_text_in_response(self):
        """Test process_text_file with missing text field in response"""
        # Mock the HTTP response without text field
        mock_response_data = {"status": "success"}
        
        with patch('httpx.AsyncClient.post') as mock_post, \
             patch('backend.services.file_management_service.convert_long_text_to_text', return_value=("Processed text", "0")) as mock_convert:
            
            # Mock the HTTP response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_response_data
            mock_post.return_value = mock_response
            
            # Execute
            result, truncation_percentage = await process_text_file(
                query="Test query",
                filename="test.txt",
                file_content=b"test file content",
                tenant_id="tenant123",
                language="en"
            )

            # Assertions
            assert "File test.txt content" in result
            assert "Processed text" in result
            assert truncation_percentage == "0"
            mock_convert.assert_called_once_with("Test query", "", "tenant123", "en")

    @pytest.mark.asyncio
    async def test_upload_to_minio_with_none_folder(self):
        """Test upload_to_minio with None folder"""
        # Create mock UploadFile
        mock_file = MagicMock()
        mock_file.filename = "test.txt"
        mock_file.read = AsyncMock(return_value=b"test content")
        mock_file.seek = AsyncMock()

        with patch('backend.services.file_management_service.upload_fileobj', MagicMock(return_value={
            "success": True, "file_name": "test.txt", "object_name": "test.txt"
        })) as mock_upload:
            # Execute with None folder
            results = await upload_to_minio(files=[mock_file], folder=None)

            # Assertions
            assert len(results) == 1
            assert results[0]["success"] is True
            assert results[0]["file_name"] == "test.txt"
            mock_upload.assert_called_once()
            # Verify that None was passed as prefix
            call_args = mock_upload.call_args
            assert call_args[1]["prefix"] is None

    @pytest.mark.asyncio
    async def test_upload_to_minio_with_empty_folder(self):
        """Test upload_to_minio with empty folder string"""
        # Create mock UploadFile
        mock_file = MagicMock()
        mock_file.filename = "test.txt"
        mock_file.read = AsyncMock(return_value=b"test content")
        mock_file.seek = AsyncMock()

        with patch('backend.services.file_management_service.upload_fileobj', MagicMock(return_value={
            "success": True, "file_name": "test.txt", "object_name": "test.txt"
        })) as mock_upload:
            # Execute with empty folder
            results = await upload_to_minio(files=[mock_file], folder="")

            # Assertions
            assert len(results) == 1
            assert results[0]["success"] is True
            assert results[0]["file_name"] == "test.txt"
            mock_upload.assert_called_once()
            # Verify that empty string was passed as prefix
            call_args = mock_upload.call_args
            assert call_args[1]["prefix"] == ""
