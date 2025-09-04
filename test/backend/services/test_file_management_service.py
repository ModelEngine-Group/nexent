"""
Unit tests for the file management service.
These tests verify the behavior of file upload, download, and management operations
without actual file system or MinIO connections.
All external services and dependencies are mocked to isolate the tests.
"""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
from io import BytesIO

# Dynamically determine the backend path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.append(backend_dir)

# Apply critical patches before importing any modules
# This prevents real AWS/MinIO calls during import
patch('botocore.client.BaseClient._make_api_call', return_value={}).start()

# Create a full mock for MinioClient to avoid initialization issues
minio_mock = MagicMock()
minio_mock._ensure_bucket_exists = MagicMock()
minio_mock.client = MagicMock()
patch('backend.database.client.MinioClient', return_value=minio_mock).start()
patch('backend.database.client.boto3.client', return_value=MagicMock()).start()
patch('backend.database.client.minio_client', minio_mock).start()

# Import the service functions after mocking
from backend.services.file_management_service import (
    upload_files_impl,
    upload_to_minio,
    get_file_url_impl,
    get_file_stream_impl,
    delete_file_impl,
    list_files_impl
)

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
