"""
Unit tests for backend/database/attachment_db.py
Tests attachment database utility functions
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch, mock_open, call
from io import BytesIO
from datetime import datetime

# Add project root to Python path
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', '..')))

# Mock consts module
consts_mock = MagicMock()
consts_mock.const = MagicMock()
# Environment variables are now configured in conftest.py

sys.modules['consts'] = consts_mock
sys.modules['consts.const'] = consts_mock.const

# Mock boto3
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

# Mock minio module
minio_mock = MagicMock()
minio_commonconfig_mock = MagicMock()
minio_commonconfig_mock.CopySource = MagicMock()
minio_mock.commonconfig = minio_commonconfig_mock
sys.modules['minio'] = minio_mock
sys.modules['minio.commonconfig'] = minio_commonconfig_mock

# Mock nexent.storage modules
nexent_mock = MagicMock()
nexent_storage_mock = MagicMock()
nexent_storage_factory_mock = MagicMock()
storage_client_mock = MagicMock()
nexent_storage_factory_mock.create_storage_client_from_config = MagicMock(return_value=storage_client_mock)
nexent_storage_factory_mock.MinIOStorageConfig = MagicMock()
nexent_storage_mock.storage_client_factory = nexent_storage_factory_mock
nexent_mock.storage = nexent_storage_mock
sys.modules['nexent'] = nexent_mock
sys.modules['nexent.storage'] = nexent_storage_mock
sys.modules['nexent.storage.storage_client_factory'] = nexent_storage_factory_mock

# Mock database.client
minio_client_mock = MagicMock()
minio_client_mock.storage_config = MagicMock()
minio_client_mock.storage_config.default_bucket = 'test-bucket'
client_mock = MagicMock()
client_mock.minio_client = minio_client_mock
sys.modules['database'] = MagicMock()
sys.modules['database.client'] = client_mock
sys.modules['backend.database.client'] = client_mock

# Patch minio_client before importing
with patch('backend.database.attachment_db.minio_client', minio_client_mock):
    from backend.database.attachment_db import (
        generate_object_name,
        upload_file,
        upload_fileobj,
        download_file,
        get_file_url,
        get_file_size,
        file_exists,
        copy_file,
        list_files,
        delete_file,
        get_file_stream,
        get_content_type
    )


class TestGenerateObjectName:
    """Test cases for generate_object_name function"""

    def test_generate_object_name_with_default_prefix(self):
        """Test generate_object_name with default prefix"""
        result = generate_object_name('test.txt')
        
        assert result.startswith('attachments/')
        assert result.endswith('.txt')
        assert len(result) > len('attachments/.txt')

    def test_generate_object_name_with_custom_prefix(self):
        """Test generate_object_name with custom prefix"""
        result = generate_object_name('test.jpg', prefix='images')
        
        assert result.startswith('images/')
        assert result.endswith('.jpg')
        assert len(result) > len('images/.jpg')

    def test_generate_object_name_without_extension(self):
        """Test generate_object_name with file without extension"""
        result = generate_object_name('testfile')
        
        assert result.startswith('attachments/')
        assert not result.endswith('.')

    def test_generate_object_name_unique(self):
        """Test generate_object_name generates unique names"""
        name1 = generate_object_name('test.txt')
        name2 = generate_object_name('test.txt')
        
        # Names should be different due to timestamp and UUID
        assert name1 != name2

    def test_generate_object_name_format(self):
        """Test generate_object_name format includes timestamp and UUID"""
        result = generate_object_name('test.txt')
        
        parts = result.split('/')
        assert len(parts) == 2
        assert parts[0] == 'attachments'
        
        # Check format: timestamp_uuid.ext
        filename_parts = parts[1].split('_')
        assert len(filename_parts) >= 2


class TestUploadFile:
    """Test cases for upload_file function"""

    @patch('backend.database.attachment_db.os.path.exists')
    @patch('backend.database.attachment_db.os.path.getsize')
    @patch('backend.database.attachment_db.os.path.basename')
    def test_upload_file_success(self, mock_basename, mock_getsize, mock_exists):
        """Test successful file upload"""
        mock_basename.return_value = 'test.txt'
        mock_exists.return_value = True
        mock_getsize.return_value = 1024
        minio_client_mock.upload_file.return_value = (True, '/bucket/attachments/test.txt')
        
        result = upload_file('/path/to/test.txt', 'attachments/test.txt', 'bucket')
        
        assert result['success'] is True
        assert result['object_name'] == 'attachments/test.txt'
        assert result['file_name'] == 'test.txt'
        assert result['file_size'] == 1024
        assert 'url' in result
        assert 'upload_time' in result
        minio_client_mock.upload_file.assert_called_once_with(
            '/path/to/test.txt', 'attachments/test.txt', 'bucket'
        )

    @patch('backend.database.attachment_db.os.path.exists')
    @patch('backend.database.attachment_db.os.path.getsize')
    @patch('backend.database.attachment_db.os.path.basename')
    @patch('backend.database.attachment_db.generate_object_name')
    def test_upload_file_auto_generate_object_name(self, mock_generate, mock_basename, mock_getsize, mock_exists):
        """Test upload_file auto-generates object name when not provided"""
        mock_basename.return_value = 'test.txt'
        mock_exists.return_value = True
        mock_getsize.return_value = 1024
        mock_generate.return_value = 'attachments/20240101120000_abc123.txt'
        minio_client_mock.upload_file.return_value = (True, '/bucket/attachments/20240101120000_abc123.txt')
        
        result = upload_file('/path/to/test.txt', None, 'bucket')
        
        assert result['success'] is True
        assert result['object_name'] == 'attachments/20240101120000_abc123.txt'
        last_call = minio_client_mock.upload_file.call_args
        assert last_call == call('/path/to/test.txt', 'attachments/20240101120000_abc123.txt', 'bucket')

    @patch('backend.database.attachment_db.os.path.exists')
    @patch('backend.database.attachment_db.os.path.getsize')
    @patch('backend.database.attachment_db.os.path.basename')
    def test_upload_file_failure(self, mock_basename, mock_getsize, mock_exists):
        """Test upload_file handles upload failure"""
        mock_basename.return_value = 'test.txt'
        mock_exists.return_value = True
        mock_getsize.return_value = 1024
        minio_client_mock.upload_file.return_value = (False, 'Upload failed')
        
        result = upload_file('/path/to/test.txt', 'attachments/test.txt', 'bucket')
        
        assert result['success'] is False
        assert result['error'] == 'Upload failed'
        assert 'url' not in result

    @patch('backend.database.attachment_db.os.path.exists')
    @patch('backend.database.attachment_db.os.path.getsize')
    @patch('backend.database.attachment_db.os.path.basename')
    def test_upload_file_nonexistent_file(self, mock_basename, mock_getsize, mock_exists):
        """Test upload_file with nonexistent file"""
        mock_basename.return_value = 'test.txt'
        mock_exists.return_value = False
        mock_getsize.return_value = 0
        minio_client_mock.upload_file.return_value = (True, '/bucket/attachments/test.txt')
        
        result = upload_file('/path/to/nonexistent.txt', 'attachments/test.txt', 'bucket')
        
        assert result['file_size'] == 0


class TestUploadFileobj:
    """Test cases for upload_fileobj function"""

    @patch('backend.database.attachment_db.generate_object_name')
    def test_upload_fileobj_success(self, mock_generate):
        """Test successful file object upload"""
        mock_generate.return_value = 'attachments/20240101120000_abc123.txt'
        minio_client_mock.upload_fileobj.return_value = (True, '/bucket/attachments/20240101120000_abc123.txt')
        
        file_obj = BytesIO(b'test data')
        result = upload_fileobj(file_obj, 'test.txt', 'bucket', 'attachments')
        
        assert result['success'] is True
        assert result['object_name'] == 'attachments/20240101120000_abc123.txt'
        assert result['file_name'] == 'test.txt'
        assert result['file_size'] == len(b'test data')
        assert 'url' in result
        assert 'upload_time' in result
        mock_generate.assert_called_once_with('test.txt', prefix='attachments')
        minio_client_mock.upload_fileobj.assert_called_once()

    @patch('backend.database.attachment_db.generate_object_name')
    def test_upload_fileobj_failure(self, mock_generate):
        """Test upload_fileobj handles upload failure"""
        mock_generate.return_value = 'attachments/20240101120000_abc123.txt'
        minio_client_mock.upload_fileobj.return_value = (False, 'Upload failed')
        
        file_obj = BytesIO(b'test data')
        result = upload_fileobj(file_obj, 'test.txt', 'bucket')
        
        assert result['success'] is False
        assert result['error'] == 'Upload failed'
        assert 'url' not in result

    @patch('backend.database.attachment_db.generate_object_name')
    def test_upload_fileobj_preserves_file_position(self, mock_generate):
        """Test upload_fileobj preserves original file position"""
        mock_generate.return_value = 'attachments/test.txt'
        minio_client_mock.upload_fileobj.return_value = (True, '/bucket/attachments/test.txt')
        
        file_obj = BytesIO(b'test data')
        original_pos = 4
        file_obj.seek(original_pos)
        
        result = upload_fileobj(file_obj, 'test.txt', 'bucket')
        
        # File position should be restored
        assert file_obj.tell() == original_pos


class TestDownloadFile:
    """Test cases for download_file function"""

    def test_download_file_success(self):
        """Test successful file download"""
        minio_client_mock.download_file.return_value = (True, 'Downloaded successfully')
        
        result = download_file('attachments/test.txt', '/path/to/download.txt', 'bucket')
        
        assert result['success'] is True
        assert result['object_name'] == 'attachments/test.txt'
        assert result['file_path'] == '/path/to/download.txt'
        assert 'error' not in result
        minio_client_mock.download_file.assert_called_once_with(
            'attachments/test.txt', '/path/to/download.txt', 'bucket'
        )

    def test_download_file_failure(self):
        """Test download_file handles download failure"""
        minio_client_mock.download_file.return_value = (False, 'Download failed')
        
        result = download_file('attachments/test.txt', '/path/to/download.txt', 'bucket')
        
        assert result['success'] is False
        assert result['error'] == 'Download failed'


class TestGetFileUrl:
    """Test cases for get_file_url function"""

    def test_get_file_url_success(self):
        """Test successful presigned URL generation"""
        minio_client_mock.get_file_url.return_value = (True, 'http://example.com/presigned-url')
        
        result = get_file_url('attachments/test.txt', 'bucket', 7200)
        
        assert result['success'] is True
        assert result['url'] == 'http://example.com/presigned-url'
        assert result['object_name'] == 'attachments/test.txt'
        assert result['expires_in'] == 7200
        assert 'error' not in result
        minio_client_mock.get_file_url.assert_called_once_with(
            'attachments/test.txt', 'bucket', 7200
        )

    def test_get_file_url_failure(self):
        """Test get_file_url handles URL generation failure"""
        minio_client_mock.get_file_url.return_value = (False, 'URL generation failed')
        
        result = get_file_url('attachments/test.txt', 'bucket', 7200)
        
        assert result['success'] is False
        assert result['error'] == 'URL generation failed'


class TestGetFileSizeFromMinio:
    """Test cases for get_file_size function"""

    def test_get_file_size_success(self):
        """Test successful file size retrieval"""
        minio_client_mock.get_file_size.return_value = 1024
        
        size = ('attachments/test.txt', 'bucket')
        
        assert size == 1024
        minio_client_mock.get_file_size.assert_called_once_with('attachments/test.txt', 'bucket')

    def test_get_file_size_uses_default_bucket(self):
        """Test  uses default bucket when not specified"""
        minio_client_mock.get_file_size.return_value = 2048
        
        size = ('attachments/test.txt')
        
        assert size == 2048
        assert minio_client_mock.get_file_size.call_args_list[-1] == call(
            'attachments/test.txt', 'test-bucket'
        )


class TestListFiles:
    """Test cases for list_files function"""

    def test_list_files_success(self):
        """Test successful file listing"""
        from datetime import datetime
        mock_files = [
            {
                'key': 'attachments/file1.txt',
                'size': 100,
                'last_modified': datetime(2024, 1, 1)
            },
            {
                'key': 'attachments/file2.txt',
                'size': 200,
                'last_modified': datetime(2024, 1, 2)
            }
        ]
        minio_client_mock.list_files.return_value = mock_files
        minio_client_mock.get_file_url.return_value = (True, 'http://example.com/file1.txt')
        
        files = list_files('attachments/', 'bucket')
        
        assert len(files) == 2
        assert files[0]['key'] == 'attachments/file1.txt'
        assert files[0]['size'] == 100
        assert 'content_type' in files[0]
        assert 'url' in files[0]
        minio_client_mock.list_files.assert_called_once_with('attachments/', 'bucket')

    def test_list_files_empty(self):
        """Test list_files with empty result"""
        minio_client_mock.list_files.return_value = []
        
        files = list_files('attachments/', 'bucket')
        
        assert files == []

    def test_list_files_url_generation_failure(self):
        """Test list_files handles URL generation failure"""
        from datetime import datetime
        mock_files = [
            {
                'key': 'attachments/file1.txt',
                'size': 100,
                'last_modified': datetime(2024, 1, 1)
            }
        ]
        minio_client_mock.list_files.return_value = mock_files
        minio_client_mock.get_file_url.return_value = (False, 'URL generation failed')
        
        files = list_files('attachments/', 'bucket')
        
        assert len(files) == 1
        assert 'url' not in files[0]


class TestDeleteFile:
    """Test cases for delete_file function"""

    def test_delete_file_success(self):
        """Test successful file deletion"""
        minio_client_mock.delete_file.return_value = (True, 'Deleted successfully')
        
        result = delete_file('attachments/test.txt', 'bucket')
        
        assert result['success'] is True
        assert result['object_name'] == 'attachments/test.txt'
        assert 'error' not in result
        minio_client_mock.delete_file.assert_called_once_with('attachments/test.txt', 'bucket')

    def test_delete_file_uses_default_bucket(self):
        """Test delete_file uses default bucket when not specified"""
        minio_client_mock.delete_file.return_value = (True, 'Deleted successfully')
        
        result = delete_file('attachments/test.txt')
        
        assert result['success'] is True
        assert minio_client_mock.delete_file.call_args_list[-1] == call(
            'attachments/test.txt', 'test-bucket'
        )

    def test_delete_file_failure(self):
        """Test delete_file handles deletion failure"""
        minio_client_mock.delete_file.return_value = (False, 'Delete failed')
        
        result = delete_file('attachments/test.txt', 'bucket')
        
        assert result['success'] is False
        assert result['error'] == 'Delete failed'


class TestGetFileStream:
    """Test cases for get_file_stream function"""

    def test_get_file_stream_success(self):
        """Test successful file stream retrieval"""
        mock_stream = BytesIO(b'test data')
        minio_client_mock.get_file_stream.return_value = (True, mock_stream)
        
        result = get_file_stream('attachments/test.txt', 'bucket')
        
        assert result is not None
        assert isinstance(result, BytesIO)
        assert result.read() == b'test data'
        minio_client_mock.get_file_stream.assert_called_once_with('attachments/test.txt', 'bucket')

    def test_get_file_stream_failure(self):
        """Test get_file_stream returns None on failure"""
        minio_client_mock.get_file_stream.return_value = (False, 'Stream failed')
        
        result = get_file_stream('attachments/test.txt', 'bucket')
        
        assert result is None

    def test_get_file_stream_read_error(self):
        """Test get_file_stream handles read errors"""
        mock_stream = MagicMock()
        mock_stream.read.side_effect = Exception("Read error")
        minio_client_mock.get_file_stream.return_value = (True, mock_stream)
        
        result = get_file_stream('attachments/test.txt', 'bucket')
        
        assert result is None


class TestGetContentType:
    """Test cases for get_content_type function"""

    def test_get_content_type_jpeg(self):
        """Test get_content_type for JPEG files"""
        assert get_content_type('test.jpg') == 'image/jpeg'
        assert get_content_type('test.JPEG') == 'image/jpeg'

    def test_get_content_type_png(self):
        """Test get_content_type for PNG files"""
        assert get_content_type('test.png') == 'image/png'

    def test_get_content_type_pdf(self):
        """Test get_content_type for PDF files"""
        assert get_content_type('test.pdf') == 'application/pdf'

    def test_get_content_type_txt(self):
        """Test get_content_type for text files"""
        assert get_content_type('test.txt') == 'text/plain'

    def test_get_content_type_json(self):
        """Test get_content_type for JSON files"""
        assert get_content_type('test.json') == 'application/json'

    def test_get_content_type_unknown(self):
        """Test get_content_type for unknown file types"""
        assert get_content_type('test.unknown') == 'application/octet-stream'

    def test_get_content_type_no_extension(self):
        """Test get_content_type for files without extension"""
        assert get_content_type('testfile') == 'application/octet-stream'

    def test_get_content_type_with_path(self):
        """Test get_content_type with full file path"""
        assert get_content_type('/path/to/test.jpg') == 'image/jpeg'
        assert get_content_type('C:\\path\\to\\test.png') == 'image/png'

    def test_get_content_type_case_insensitive(self):
        """Test get_content_type is case insensitive"""
        assert get_content_type('test.JPG') == 'image/jpeg'
        assert get_content_type('test.PNG') == 'image/png'
        assert get_content_type('test.PDF') == 'application/pdf'


class TestFileExists:
    """Test cases for file_exists function"""

    def test_file_exists_returns_true_when_file_exists(self):
        """Test file_exists returns True when file exists in bucket"""
        with patch('backend.database.attachment_db.minio_client') as mock_client:
            mock_client.file_exists.return_value = True
            
            result = file_exists('test/file.txt')
            
            assert result is True
            mock_client.file_exists.assert_called_once_with('test/file.txt', None)

    def test_file_exists_returns_false_when_file_not_exists(self):
        """Test file_exists returns False when file does not exist"""
        with patch('backend.database.attachment_db.minio_client') as mock_client:
            mock_client.file_exists.return_value = False
            
            result = file_exists('nonexistent/file.txt')
            
            assert result is False
            mock_client.file_exists.assert_called_once_with('nonexistent/file.txt', None)

    def test_file_exists_with_custom_bucket(self):
        """Test file_exists with custom bucket parameter"""
        with patch('backend.database.attachment_db.minio_client') as mock_client:
            mock_client.file_exists.return_value = True
            
            result = file_exists('test/file.txt', bucket='custom-bucket')
            
            assert result is True
            mock_client.file_exists.assert_called_once_with('test/file.txt', 'custom-bucket')

    def test_file_exists_handles_any_exception(self):
        """Test file_exists handles any exception and returns False"""
        with patch('backend.database.attachment_db.minio_client') as mock_client:
            mock_client.file_exists.side_effect = RuntimeError('Connection failed')
            
            result = file_exists('test/file.txt')
            
            assert result is False
            mock_client.file_exists.assert_called_once_with('test/file.txt', None)


class TestCopyFile:
    """Test cases for copy_file function"""

    def test_copy_file_success(self):
        """Test successful file copy"""
        with patch('backend.database.attachment_db.minio_client') as mock_client:
            mock_client.copy_file.return_value = (True, 'dest/file.pdf')
            
            result = copy_file('source/file.pdf', 'dest/file.pdf')
            
            assert result['success'] is True
            assert result['object_name'] == 'dest/file.pdf'
            mock_client.copy_file.assert_called_once_with('source/file.pdf', 'dest/file.pdf', None)

    def test_copy_file_with_custom_bucket(self):
        """Test copy_file with custom bucket"""
        with patch('backend.database.attachment_db.minio_client') as mock_client:
            mock_client.copy_file.return_value = (True, 'dest/file.pdf')
            
            result = copy_file('source/file.pdf', 'dest/file.pdf', bucket='custom-bucket')
            
            assert result['success'] is True
            mock_client.copy_file.assert_called_once_with('source/file.pdf', 'dest/file.pdf', 'custom-bucket')

    def test_copy_file_failure(self):
        """Test copy_file handles errors"""
        with patch('backend.database.attachment_db.minio_client') as mock_client:
            mock_client.copy_file.return_value = (False, 'Copy failed')
            
            result = copy_file('source/file.pdf', 'dest/file.pdf')
            
            assert result['success'] is False
            assert 'Copy failed' in result['error']

