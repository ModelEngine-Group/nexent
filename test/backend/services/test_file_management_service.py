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
from unittest.mock import patch, MagicMock, AsyncMock, Mock
from pathlib import Path
from io import BytesIO

# Dynamically determine the backend path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.append(backend_dir)

# Patch environment variables before any imports that might use them
# Environment variables are now configured in conftest.py

# Apply critical patches before importing any modules
# This prevents real AWS/MinIO/Elasticsearch calls during import
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_mock).start()
patch('backend.database.client.minio_client', minio_mock).start()

# Stub Elasticsearch service module to avoid initializing real client during import
services_stub = types.ModuleType('services')
services_stub.__path__ = []  # Mark as package
sys.modules.setdefault('services', services_stub)

vdb_stub = types.ModuleType('services.vectordatabase_service')


class _StubElasticSearchService:
    @staticmethod
    async def list_files(index_name, include_chunks=False, vdb_core=None):
        return {"files": []}


def _stub_get_vector_db_core():
    return None


vdb_stub.ElasticSearchService = _StubElasticSearchService
vdb_stub.get_vector_db_core = _stub_get_vector_db_core
sys.modules['services.vectordatabase_service'] = vdb_stub
setattr(services_stub, 'vectordatabase_service', vdb_stub)

# Import the service module after mocking external dependencies
file_management_service = importlib.import_module(
    'backend.services.file_management_service')

upload_files_impl = file_management_service.upload_files_impl
upload_to_minio = file_management_service.upload_to_minio
get_file_url_impl = file_management_service.get_file_url_impl
get_file_stream_impl = file_management_service.get_file_stream_impl
delete_file_impl = file_management_service.delete_file_impl
list_files_impl = file_management_service.list_files_impl

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
                patch('backend.services.file_management_service.get_vector_db_core', MagicMock()) as mock_vdb_core, \
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
                patch('backend.services.file_management_service.get_vector_db_core', MagicMock()), \
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
                patch('backend.services.file_management_service.get_vector_db_core', MagicMock()), \
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


class TestGetLlmModel:
    """Test cases for get_llm_model function"""

    @patch('backend.services.file_management_service.MODEL_CONFIG_MAPPING', {"llm": "llm_config_key"})
    @patch('backend.services.file_management_service.MessageObserver')
    @patch('backend.services.file_management_service.OpenAILongContextModel')
    @patch('backend.services.file_management_service.get_model_name_from_config')
    @patch('backend.services.file_management_service.tenant_config_manager')
    def test_get_llm_model_success(self, mock_tenant_config, mock_get_model_name, mock_openai_model, mock_message_observer):
        """Test successful LLM model retrieval"""
        from backend.services.file_management_service import get_llm_model

        # Mock tenant config manager
        mock_config = {
            "base_url": "http://api.example.com",
            "api_key": "test_api_key",
            "max_tokens": 4096
        }
        mock_tenant_config.get_model_config.return_value = mock_config

        # Mock model name
        mock_get_model_name.return_value = "gpt-4"

        # Mock MessageObserver
        mock_observer_instance = Mock()
        mock_message_observer.return_value = mock_observer_instance

        # Mock OpenAILongContextModel
        mock_model_instance = Mock()
        mock_openai_model.return_value = mock_model_instance

        # Execute
        result = get_llm_model("tenant123")

        # Assertions
        assert result == mock_model_instance
        mock_tenant_config.get_model_config.assert_called_once_with(
            key="llm_config_key", tenant_id="tenant123")
        mock_get_model_name.assert_called_once_with(mock_config)
        mock_message_observer.assert_called_once()
        mock_openai_model.assert_called_once_with(
            observer=mock_observer_instance,
            model_id="gpt-4",
            api_base="http://api.example.com",
            api_key="test_api_key",
            max_context_tokens=4096,
            ssl_verify=True
        )

    @patch('backend.services.file_management_service.MODEL_CONFIG_MAPPING', {"llm": "llm_config_key"})
    @patch('backend.services.file_management_service.MessageObserver')
    @patch('backend.services.file_management_service.OpenAILongContextModel')
    @patch('backend.services.file_management_service.get_model_name_from_config')
    @patch('backend.services.file_management_service.tenant_config_manager')
    def test_get_llm_model_with_missing_config_values(self, mock_tenant_config, mock_get_model_name, mock_openai_model, mock_message_observer):
        """Test get_llm_model with missing config values"""
        from backend.services.file_management_service import get_llm_model

        # Mock tenant config manager with missing values
        mock_config = {
            "base_url": "http://api.example.com"
            # Missing api_key and max_tokens
        }
        mock_tenant_config.get_model_config.return_value = mock_config

        # Mock model name
        mock_get_model_name.return_value = "gpt-4"

        # Mock MessageObserver
        mock_observer_instance = Mock()
        mock_message_observer.return_value = mock_observer_instance

        # Mock OpenAILongContextModel
        mock_model_instance = Mock()
        mock_openai_model.return_value = mock_model_instance

        # Execute
        result = get_llm_model("tenant123")

        # Assertions
        assert result == mock_model_instance
        # Verify that get() is used for missing values (returns None)
        mock_openai_model.assert_called_once()
        call_kwargs = mock_openai_model.call_args[1]
        assert call_kwargs["api_key"] is None
        assert call_kwargs["max_context_tokens"] is None

    @patch('backend.services.file_management_service.MODEL_CONFIG_MAPPING', {"llm": "llm_config_key"})
    @patch('backend.services.file_management_service.MessageObserver')
    @patch('backend.services.file_management_service.OpenAILongContextModel')
    @patch('backend.services.file_management_service.get_model_name_from_config')
    @patch('backend.services.file_management_service.tenant_config_manager')
    def test_get_llm_model_with_different_tenant_ids(self, mock_tenant_config, mock_get_model_name, mock_openai_model, mock_message_observer):
        """Test get_llm_model with different tenant IDs"""
        from backend.services.file_management_service import get_llm_model

        # Mock tenant config manager
        mock_config = {
            "base_url": "http://api.example.com",
            "api_key": "test_api_key",
            "max_tokens": 4096
        }
        mock_tenant_config.get_model_config.return_value = mock_config

        # Mock model name
        mock_get_model_name.return_value = "gpt-4"

        # Mock MessageObserver
        mock_observer_instance = Mock()
        mock_message_observer.return_value = mock_observer_instance

        # Mock OpenAILongContextModel
        mock_model_instance = Mock()
        mock_openai_model.return_value = mock_model_instance

        # Execute with different tenant IDs
        result1 = get_llm_model("tenant1")
        result2 = get_llm_model("tenant2")

        # Assertions
        assert result1 == mock_model_instance
        assert result2 == mock_model_instance
        # Verify tenant config was called with different tenant IDs
        assert mock_tenant_config.get_model_config.call_count == 2
        assert mock_tenant_config.get_model_config.call_args_list[0][1]["tenant_id"] == "tenant1"
        assert mock_tenant_config.get_model_config.call_args_list[1][1]["tenant_id"] == "tenant2"


class TestPreviewFileImpl:
    """Test cases for preview_file_impl function"""

    @pytest.mark.asyncio
    async def test_preview_pdf_file_success(self):
        """Test previewing a PDF file returns stream directly"""
        from backend.services.file_management_service import preview_file_impl
        
        mock_stream = BytesIO(b"PDF content")
        
        with patch('backend.services.file_management_service.get_content_type', return_value='application/pdf'), \
             patch('backend.services.file_management_service.get_file_stream', return_value=mock_stream):
            
            result_stream, result_type = await preview_file_impl("test/document.pdf")
            
            assert result_type == 'application/pdf'
            assert result_stream == mock_stream

    @pytest.mark.asyncio
    async def test_preview_image_file_success(self):
        """Test previewing an image file returns stream directly"""
        from backend.services.file_management_service import preview_file_impl
        
        mock_stream = BytesIO(b"PNG content")
        
        with patch('backend.services.file_management_service.get_content_type', return_value='image/png'), \
             patch('backend.services.file_management_service.get_file_stream', return_value=mock_stream):
            
            result_stream, result_type = await preview_file_impl("test/image.png")
            
            assert result_type == 'image/png'
            assert result_stream == mock_stream

    @pytest.mark.asyncio
    async def test_preview_text_file_success(self):
        """Test previewing a text file returns stream directly"""
        from backend.services.file_management_service import preview_file_impl
        
        mock_stream = BytesIO(b"Text content")
        
        with patch('backend.services.file_management_service.get_content_type', return_value='text/plain'), \
             patch('backend.services.file_management_service.get_file_stream', return_value=mock_stream):
            
            result_stream, result_type = await preview_file_impl("test/readme.txt")
            
            assert result_type == 'text/plain'
            assert result_stream == mock_stream

    @pytest.mark.asyncio
    async def test_preview_csv_file_success(self):
        """Test previewing a CSV file returns stream directly"""
        from backend.services.file_management_service import preview_file_impl
        
        mock_stream = BytesIO(b"col1,col2\nval1,val2")
        
        with patch('backend.services.file_management_service.get_content_type', return_value='text/csv'), \
             patch('backend.services.file_management_service.get_file_stream', return_value=mock_stream):
            
            result_stream, result_type = await preview_file_impl("test/data.csv")
            
            assert result_type == 'text/csv'
            assert result_stream == mock_stream

    @pytest.mark.asyncio
    async def test_preview_markdown_file_success(self):
        """Test previewing a Markdown file returns stream directly"""
        from backend.services.file_management_service import preview_file_impl
        
        mock_stream = BytesIO(b"# Heading\nContent")
        
        with patch('backend.services.file_management_service.get_content_type', return_value='text/markdown'), \
             patch('backend.services.file_management_service.get_file_stream', return_value=mock_stream):
            
            result_stream, result_type = await preview_file_impl("test/readme.md")
            
            assert result_type == 'text/markdown'
            assert result_stream == mock_stream

    @pytest.mark.asyncio
    async def test_preview_office_docx_with_cache_hit(self):
        """Test previewing a Word document with cached PDF available"""
        from backend.services.file_management_service import preview_file_impl
        
        mock_pdf_stream = BytesIO(b"Cached PDF content")
        
        with patch('backend.services.file_management_service.get_content_type', 
                   return_value='application/vnd.openxmlformats-officedocument.wordprocessingml.document'), \
             patch('backend.services.file_management_service.file_exists', return_value=True), \
             patch('backend.services.file_management_service.get_file_stream', return_value=mock_pdf_stream):
            
            result_stream, result_type = await preview_file_impl("test/document.docx")
            
            assert result_type == 'application/pdf'
            assert result_stream == mock_pdf_stream

    @pytest.mark.asyncio
    async def test_preview_office_docx_cache_miss_convert_success(self):
        """Test previewing a Word document with cache miss triggers conversion"""
        from backend.services.file_management_service import preview_file_impl
        
        mock_original_stream = BytesIO(b"Original DOCX content")
        mock_converted_pdf_stream = BytesIO(b"%PDF-1.4 Converted PDF content")
        call_count = 0
        
        def mock_get_file_stream(object_name):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: get original file
                return mock_original_stream
            else:
                # Subsequent calls: return converted PDF
                return mock_converted_pdf_stream
        
        with patch('backend.services.file_management_service.get_content_type', 
                   return_value='application/vnd.openxmlformats-officedocument.wordprocessingml.document'), \
             patch('backend.services.file_management_service.file_exists', return_value=False), \
             patch('backend.services.file_management_service.get_file_stream', 
                   side_effect=mock_get_file_stream), \
             patch('tempfile.mkdtemp', return_value='/tmp/test_convert'), \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=100), \
             patch('shutil.rmtree'), \
             patch('builtins.open', MagicMock()), \
             patch('backend.utils.file_management_utils.convert_office_to_pdf', 
                   AsyncMock(return_value='/tmp/test_convert/document.pdf')), \
             patch('backend.services.file_management_service.upload_file', 
                   return_value={'success': True}), \
             patch('backend.services.file_management_service._validate_uploaded_pdf', 
                   return_value=True), \
             patch('backend.services.file_management_service.copy_file',
                   return_value={'success': True}), \
             patch('backend.services.file_management_service.delete_file', 
                   return_value={'success': True}):
            
            result_stream, result_type = await preview_file_impl("test/document.docx")
            
            assert result_type == 'application/pdf'
            assert result_stream == mock_converted_pdf_stream

    @pytest.mark.asyncio
    async def test_preview_office_conversion_failure(self):
        """Test previewing an Office document when conversion fails"""
        from backend.services.file_management_service import preview_file_impl
        
        mock_original_stream = BytesIO(b"Original DOCX content")
        
        with patch('backend.services.file_management_service.get_content_type', 
                   return_value='application/vnd.openxmlformats-officedocument.wordprocessingml.document'), \
             patch('backend.services.file_management_service.file_exists', return_value=False), \
             patch('backend.services.file_management_service.get_file_stream', return_value=mock_original_stream), \
             patch('tempfile.mkdtemp', return_value='/tmp/test_convert'), \
             patch('os.path.exists', return_value=True), \
             patch('shutil.rmtree'), \
             patch('builtins.open', MagicMock()), \
             patch('backend.services.file_management_service.delete_file', 
                   return_value={'success': True}), \
             patch('backend.utils.file_management_utils.convert_office_to_pdf', 
                   AsyncMock(side_effect=Exception("LibreOffice not installed"))):
            
            with pytest.raises(Exception) as exc_info:
                await preview_file_impl("test/document.docx")
            
            assert "Failed to convert Office document to PDF" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_preview_unsupported_file_type(self):
        """Test previewing an unsupported file type raises exception"""
        from backend.services.file_management_service import preview_file_impl
        
        with patch('backend.services.file_management_service.get_content_type', 
                   return_value='application/octet-stream'):
            
            with pytest.raises(Exception) as exc_info:
                await preview_file_impl("test/unknown.bin")
            
            assert "Unsupported file type for preview" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_preview_file_not_found(self):
        """Test previewing a non-existent file raises exception"""
        from backend.services.file_management_service import preview_file_impl
        
        with patch('backend.services.file_management_service.get_content_type', return_value='application/pdf'), \
             patch('backend.services.file_management_service.get_file_stream', return_value=None):
            
            with pytest.raises(Exception) as exc_info:
                await preview_file_impl("test/nonexistent.pdf")
            
            assert "File not found" in str(exc_info.value)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("content_type,expected_direct", [
        ('application/pdf', True),
        ('image/jpeg', True),
        ('image/png', True),
        ('image/gif', True),
        ('image/webp', True),
        ('text/plain', True),
        ('text/csv', True),
        ('text/markdown', True),
        ('application/vnd.openxmlformats-officedocument.wordprocessingml.document', False),
        ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', False),
        ('application/vnd.openxmlformats-officedocument.presentationml.presentation', False),
        ('application/msword', False),
        ('application/vnd.ms-excel', False),
        ('application/vnd.ms-powerpoint', False),
    ])
    async def test_preview_file_type_routing(self, content_type, expected_direct):
        """Test that different file types are routed correctly"""
        from backend.services.file_management_service import preview_file_impl
        
        mock_stream = BytesIO(b"test content")
        get_stream_call_count = 0
        
        def mock_get_file_stream(object_name):
            nonlocal get_stream_call_count
            get_stream_call_count += 1
            return mock_stream
        
        with patch('backend.services.file_management_service.get_content_type', return_value=content_type), \
             patch('backend.services.file_management_service.file_exists', return_value=True), \
             patch('backend.services.file_management_service.get_file_stream', side_effect=mock_get_file_stream):
            
            result_stream, result_type = await preview_file_impl("test/file")
            
            assert result_stream == mock_stream
            if expected_direct:
                # Direct file types should call get_file_stream once
                assert get_stream_call_count == 1
                assert result_type == content_type
            else:
                # Office files return PDF type
                assert result_type == 'application/pdf'


class TestValidateUploadedPdf:
    """Test cases for _validate_uploaded_pdf function"""

    def test_validate_uploaded_pdf_success(self):
        """Test successful PDF validation"""
        from backend.services.file_management_service import _validate_uploaded_pdf
        
        # Create a valid PDF stream (starts with %PDF-)
        mock_pdf_content = b'%PDF-1.4 valid pdf content here' + b'x' * 100
        mock_stream = BytesIO(mock_pdf_content)
        
        with patch('backend.services.file_management_service.get_file_stream', return_value=mock_stream), \
               patch('backend.services.file_management_service.get_file_size', return_value=len(mock_pdf_content)), \
             patch('os.path.getsize', return_value=len(mock_pdf_content)):
            
            result = _validate_uploaded_pdf('temp/file.pdf', '/local/path/file.pdf')
            
            assert result is True

    def test_validate_uploaded_pdf_size_mismatch(self):
        """Test PDF validation fails on size mismatch"""
        from backend.services.file_management_service import _validate_uploaded_pdf
        
        mock_pdf_content = b'%PDF-1.4 valid pdf content here' + b'x' * 100
        mock_stream = BytesIO(mock_pdf_content)
        
        with patch('backend.services.file_management_service.get_file_stream', return_value=mock_stream), \
               patch('backend.services.file_management_service.get_file_size', return_value=len(mock_pdf_content)), \
             patch('os.path.getsize', return_value=999):  # Different size
            
            result = _validate_uploaded_pdf('temp/file.pdf', '/local/path/file.pdf')
            
            assert result is False

    def test_validate_uploaded_pdf_invalid_header(self):
        """Test PDF validation fails on invalid header"""
        from backend.services.file_management_service import _validate_uploaded_pdf
        
        mock_content = b'NOT A PDF FILE' + b'x' * 100
        mock_stream = BytesIO(mock_content)
        
        with patch('backend.services.file_management_service.get_file_stream', return_value=mock_stream), \
               patch('backend.services.file_management_service.get_file_size', return_value=len(mock_content)), \
             patch('os.path.getsize', return_value=len(mock_content)):
            
            result = _validate_uploaded_pdf('temp/file.pdf', '/local/path/file.pdf')
            
            assert result is False

    def test_validate_uploaded_pdf_file_too_small(self):
        """Test PDF validation fails on file too small"""
        from backend.services.file_management_service import _validate_uploaded_pdf
        
        mock_content = b'%PDF-1.4 tiny'  # Less than 100 bytes
        mock_stream = BytesIO(mock_content)
        
        with patch('backend.services.file_management_service.get_file_stream', return_value=mock_stream), \
               patch('backend.services.file_management_service.get_file_size', return_value=len(mock_content)), \
             patch('os.path.getsize', return_value=len(mock_content)):
            
            result = _validate_uploaded_pdf('temp/file.pdf', '/local/path/file.pdf')
            
            assert result is False

    def test_validate_uploaded_pdf_stream_none(self):
        """Test PDF validation fails when stream is None"""
        from backend.services.file_management_service import _validate_uploaded_pdf
        
        with patch('backend.services.file_management_service.get_file_stream', return_value=None), \
             patch('backend.services.file_management_service.get_file_size', return_value=100), \
             patch('os.path.getsize', return_value=100):
            
            result = _validate_uploaded_pdf('temp/file.pdf', '/local/path/file.pdf')
            
            assert result is False

    def test_validate_uploaded_pdf_exception_handling(self):
        """Test PDF validation handles exceptions gracefully"""
        from backend.services.file_management_service import _validate_uploaded_pdf
        
        with patch('backend.services.file_management_service.get_file_stream', side_effect=Exception('Network error')), \
             patch('backend.services.file_management_service.get_file_size', return_value=100), \
             patch('os.path.getsize', return_value=100):
            
            result = _validate_uploaded_pdf('temp/file.pdf', '/local/path/file.pdf')
            
            assert result is False

