"""
Unit tests for minio.py
Tests the MinIOStorageClient class
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch, Mock, mock_open
from io import BytesIO
from botocore.exceptions import ClientError

# Add project root to Python path
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', '..')))

from nexent.storage.minio import MinIOStorageClient


class TestMinIOStorageClientInit:
    """Test cases for MinIOStorageClient initialization"""

    @patch('nexent.storage.minio.boto3')
    def test_init_with_all_parameters(self, mock_boto3):
        """Test initialization with all parameters"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            region="us-east-1",
            default_bucket="test-bucket",
            secure=False
        )

        assert client.endpoint == "http://localhost:9000"
        assert client.access_key == "minioadmin"
        assert client.secret_key == "minioadmin"
        assert client.region == "us-east-1"
        assert client.default_bucket == "test-bucket"
        assert client.secure is False
        mock_boto3.client.assert_called_once()
        mock_client.head_bucket.assert_called_once_with(Bucket="test-bucket")

    @patch('nexent.storage.minio.boto3')
    def test_init_with_minimal_parameters(self, mock_boto3):
        """Test initialization with minimal parameters"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin"
        )

        assert client.endpoint == "http://localhost:9000"
        assert client.region == "us-east-1"  # Default region
        assert client.default_bucket is None
        assert client.secure is True  # Default secure

    @patch('nexent.storage.minio.boto3')
    def test_init_with_default_bucket_creation(self, mock_boto3):
        """Test initialization creates bucket if it doesn't exist"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        
        # First call raises 404 (bucket doesn't exist), second succeeds (bucket created)
        error_404 = ClientError(
            {'Error': {'Code': '404', 'Message': 'Not Found'}},
            'HeadBucket'
        )
        mock_client.head_bucket.side_effect = [error_404, None]
        mock_client.create_bucket.return_value = None

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="new-bucket"
        )

        mock_client.head_bucket.assert_called_with(Bucket="new-bucket")
        mock_client.create_bucket.assert_called_once_with(Bucket="new-bucket")

    @patch('nexent.storage.minio.boto3')
    def test_init_bucket_check_permission_error(self, mock_boto3):
        """Test initialization handles permission errors when checking bucket"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        
        error_403 = ClientError(
            {'Error': {'Code': '403', 'Message': 'Forbidden'}},
            'HeadBucket'
        )
        mock_client.head_bucket.side_effect = error_403

        with pytest.raises(ClientError):
            MinIOStorageClient(
                endpoint="http://localhost:9000",
                access_key="minioadmin",
                secret_key="minioadmin",
                default_bucket="test-bucket"
            )

    @patch('nexent.storage.minio.boto3')
    def test_init_bucket_creation_failure(self, mock_boto3):
        """Test initialization handles bucket creation failure"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        
        error_404 = ClientError(
            {'Error': {'Code': '404', 'Message': 'Not Found'}},
            'HeadBucket'
        )
        create_error = ClientError(
            {'Error': {'Code': 'AccessDenied', 'Message': 'Access Denied'}},
            'CreateBucket'
        )
        mock_client.head_bucket.side_effect = error_404
        mock_client.create_bucket.side_effect = create_error

        with pytest.raises(ClientError):
            MinIOStorageClient(
                endpoint="http://localhost:9000",
                access_key="minioadmin",
                secret_key="minioadmin",
                default_bucket="test-bucket"
            )


class TestMinIOStorageClientUploadFile:
    """Test cases for upload_file method"""

    @patch('nexent.storage.minio.boto3')
    def test_upload_file_success(self, mock_boto3):
        """Test successful file upload"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        with patch('builtins.open', mock_open(read_data=b'test data')):
            with patch('os.path.basename', return_value='test.txt'):
                success, result = client.upload_file('/path/to/test.txt', 'test.txt', 'test-bucket')

        assert success is True
        assert result == "/test-bucket/test.txt"
        mock_client.upload_file.assert_called_once_with('/path/to/test.txt', 'test-bucket', 'test.txt')

    @patch('nexent.storage.minio.boto3')
    def test_upload_file_without_bucket(self, mock_boto3):
        """Test upload_file fails when bucket is not specified"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin"
        )

        success, result = client.upload_file('/path/to/test.txt')

        assert success is False
        assert result == "Bucket name is required"

    @patch('nexent.storage.minio.boto3')
    def test_upload_file_without_object_name(self, mock_boto3):
        """Test upload_file uses filename when object_name is not specified"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        with patch('builtins.open', mock_open(read_data=b'test data')):
            with patch('os.path.basename', return_value='test.txt'):
                success, result = client.upload_file('/path/to/test.txt', None, 'test-bucket')

        assert success is True
        assert result == "/test-bucket/test.txt"
        mock_client.upload_file.assert_called_once_with('/path/to/test.txt', 'test-bucket', 'test.txt')

    @patch('nexent.storage.minio.boto3')
    def test_upload_file_exception(self, mock_boto3):
        """Test upload_file handles exceptions"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None
        mock_client.upload_file.side_effect = Exception("Upload failed")

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        success, result = client.upload_file('/path/to/test.txt', 'test.txt')

        assert success is False
        assert "Upload failed" in result


class TestMinIOStorageClientUploadFileobj:
    """Test cases for upload_fileobj method"""

    @patch('nexent.storage.minio.boto3')
    def test_upload_fileobj_success(self, mock_boto3):
        """Test successful file object upload"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        file_obj = BytesIO(b'test data')
        success, result = client.upload_fileobj(file_obj, 'test.txt', 'test-bucket')

        assert success is True
        assert result == "/test-bucket/test.txt"
        mock_client.upload_fileobj.assert_called_once_with(file_obj, 'test-bucket', 'test.txt')

    @patch('nexent.storage.minio.boto3')
    def test_upload_fileobj_without_bucket(self, mock_boto3):
        """Test upload_fileobj fails when bucket is not specified"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin"
        )

        file_obj = BytesIO(b'test data')
        success, result = client.upload_fileobj(file_obj, 'test.txt')

        assert success is False
        assert result == "Bucket name is required"

    @patch('nexent.storage.minio.boto3')
    def test_upload_fileobj_exception(self, mock_boto3):
        """Test upload_fileobj handles exceptions"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None
        mock_client.upload_fileobj.side_effect = Exception("Upload failed")

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        file_obj = BytesIO(b'test data')
        success, result = client.upload_fileobj(file_obj, 'test.txt')

        assert success is False
        assert "Upload failed" in result


class TestMinIOStorageClientDownloadFile:
    """Test cases for download_file method"""

    @patch('nexent.storage.minio.boto3')
    def test_download_file_success(self, mock_boto3):
        """Test successful file download"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        success, result = client.download_file('test.txt', '/path/to/download.txt', 'test-bucket')

        assert success is True
        assert "downloaded successfully" in result
        mock_client.download_file.assert_called_once_with('test-bucket', 'test.txt', '/path/to/download.txt')

    @patch('nexent.storage.minio.boto3')
    def test_download_file_without_bucket(self, mock_boto3):
        """Test download_file fails when bucket is not specified"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin"
        )

        success, result = client.download_file('test.txt', '/path/to/download.txt')

        assert success is False
        assert result == "Bucket name is required"

    @patch('nexent.storage.minio.boto3')
    def test_download_file_exception(self, mock_boto3):
        """Test download_file handles exceptions"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None
        mock_client.download_file.side_effect = Exception("Download failed")

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        success, result = client.download_file('test.txt', '/path/to/download.txt')

        assert success is False
        assert "Download failed" in result


class TestMinIOStorageClientGetFileUrl:
    """Test cases for get_file_url method"""

    @patch('nexent.storage.minio.boto3')
    def test_get_file_url_success(self, mock_boto3):
        """Test successful presigned URL generation"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None
        mock_client.generate_presigned_url.return_value = "http://example.com/presigned-url"

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        success, result = client.get_file_url('test.txt', 'test-bucket', 7200)

        assert success is True
        assert result == "http://example.com/presigned-url"
        mock_client.generate_presigned_url.assert_called_once_with(
            'get_object',
            Params={'Bucket': 'test-bucket', 'Key': 'test.txt'},
            ExpiresIn=7200
        )

    @patch('nexent.storage.minio.boto3')
    def test_get_file_url_without_bucket(self, mock_boto3):
        """Test get_file_url fails when bucket is not specified"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin"
        )

        success, result = client.get_file_url('test.txt')

        assert success is False
        assert result == "Bucket name is required"

    @patch('nexent.storage.minio.boto3')
    def test_get_file_url_exception(self, mock_boto3):
        """Test get_file_url handles exceptions"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None
        mock_client.generate_presigned_url.side_effect = Exception("URL generation failed")

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        success, result = client.get_file_url('test.txt')

        assert success is False
        assert "URL generation failed" in result


class TestMinIOStorageClientGetFileStream:
    """Test cases for get_file_stream method"""

    @patch('nexent.storage.minio.boto3')
    def test_get_file_stream_success(self, mock_boto3):
        """Test successful file stream retrieval"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None
        mock_stream = MagicMock()
        mock_client.get_object.return_value = {'Body': mock_stream}

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        success, result = client.get_file_stream('test.txt', 'test-bucket')

        assert success is True
        assert result == mock_stream
        mock_client.get_object.assert_called_once_with(Bucket='test-bucket', Key='test.txt')

    @patch('nexent.storage.minio.boto3')
    def test_get_file_stream_without_bucket(self, mock_boto3):
        """Test get_file_stream fails when bucket is not specified"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin"
        )

        success, result = client.get_file_stream('test.txt')

        assert success is False
        assert result == "Bucket name is required"

    @patch('nexent.storage.minio.boto3')
    def test_get_file_stream_not_found(self, mock_boto3):
        """Test get_file_stream handles 404 error (file not found)"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None
        
        error_404 = ClientError(
            {'Error': {'Code': '404', 'Message': 'Not Found'}},
            'GetObject'
        )
        mock_client.get_object.side_effect = error_404

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        success, result = client.get_file_stream('test.txt')

        assert success is False
        assert "File not found" in result

    @patch('nexent.storage.minio.boto3')
    def test_get_file_stream_permission_error(self, mock_boto3):
        """Test get_file_stream handles permission errors"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None
        
        error_403 = ClientError(
            {'Error': {'Code': '403', 'Message': 'Forbidden'}},
            'GetObject'
        )
        mock_client.get_object.side_effect = error_403

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        success, result = client.get_file_stream('test.txt')

        assert success is False
        assert "Failed to get file stream" in result

    @patch('nexent.storage.minio.boto3')
    def test_get_file_stream_unexpected_error(self, mock_boto3):
        """Test get_file_stream handles unexpected errors"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None
        mock_client.get_object.side_effect = Exception("Unexpected error")

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        success, result = client.get_file_stream('test.txt')

        assert success is False
        assert "Unexpected error" in result


class TestMinIOStorageClientGetFileSize:
    """Test cases for get_file_size method"""

    @patch('nexent.storage.minio.boto3')
    def test_get_file_size_success(self, mock_boto3):
        """Test successful file size retrieval"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None
        mock_client.head_object.return_value = {'ContentLength': 1024}

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        size = client.get_file_size('test.txt', 'test-bucket')

        assert size == 1024
        mock_client.head_object.assert_called_once_with(Bucket='test-bucket', Key='test.txt')

    @patch('nexent.storage.minio.boto3')
    def test_get_file_size_without_bucket(self, mock_boto3):
        """Test get_file_size returns 0 when bucket is not specified"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin"
        )

        size = client.get_file_size('test.txt')

        assert size == 0

    @patch('nexent.storage.minio.boto3')
    def test_get_file_size_not_found(self, mock_boto3):
        """Test get_file_size handles 404 error (file not found)"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None
        
        error_404 = ClientError(
            {'Error': {'Code': '404', 'Message': 'Not Found'}},
            'HeadObject'
        )
        mock_client.head_object.side_effect = error_404

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        size = client.get_file_size('test.txt')

        assert size == 0

    @patch('nexent.storage.minio.boto3')
    def test_get_file_size_permission_error(self, mock_boto3):
        """Test get_file_size handles permission errors"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None
        
        error_403 = ClientError(
            {'Error': {'Code': '403', 'Message': 'Forbidden'}},
            'HeadObject'
        )
        mock_client.head_object.side_effect = error_403

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        size = client.get_file_size('test.txt')

        assert size == 0


class TestMinIOStorageClientListFiles:
    """Test cases for list_files method"""

    @patch('nexent.storage.minio.boto3')
    def test_list_files_success(self, mock_boto3):
        """Test successful file listing"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None
        
        from datetime import datetime
        mock_client.list_objects_v2.return_value = {
            'Contents': [
                {
                    'Key': 'file1.txt',
                    'Size': 100,
                    'LastModified': datetime(2024, 1, 1)
                },
                {
                    'Key': 'file2.txt',
                    'Size': 200,
                    'LastModified': datetime(2024, 1, 2)
                }
            ]
        }

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        files = client.list_files('prefix/', 'test-bucket')

        assert len(files) == 2
        assert files[0]['key'] == 'file1.txt'
        assert files[0]['size'] == 100
        assert files[1]['key'] == 'file2.txt'
        assert files[1]['size'] == 200
        mock_client.list_objects_v2.assert_called_once_with(
            Bucket='test-bucket',
            Prefix='prefix/'
        )

    @patch('nexent.storage.minio.boto3')
    def test_list_files_empty(self, mock_boto3):
        """Test list_files returns empty list when no files found"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None
        mock_client.list_objects_v2.return_value = {}

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        files = client.list_files('prefix/', 'test-bucket')

        assert files == []

    @patch('nexent.storage.minio.boto3')
    def test_list_files_without_bucket(self, mock_boto3):
        """Test list_files returns empty list when bucket is not specified"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin"
        )

        files = client.list_files('prefix/')

        assert files == []

    @patch('nexent.storage.minio.boto3')
    def test_list_files_exception(self, mock_boto3):
        """Test list_files handles exceptions"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None
        mock_client.list_objects_v2.side_effect = Exception("List failed")

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        files = client.list_files('prefix/')

        assert files == []


class TestMinIOStorageClientDeleteFile:
    """Test cases for delete_file method"""

    @patch('nexent.storage.minio.boto3')
    def test_delete_file_success(self, mock_boto3):
        """Test successful file deletion"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        success, result = client.delete_file('test.txt', 'test-bucket')

        assert success is True
        assert "deleted successfully" in result
        mock_client.delete_object.assert_called_once_with(Bucket='test-bucket', Key='test.txt')

    @patch('nexent.storage.minio.boto3')
    def test_delete_file_without_bucket(self, mock_boto3):
        """Test delete_file fails when bucket is not specified"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin"
        )

        success, result = client.delete_file('test.txt')

        assert success is False
        assert result == "Bucket name is required"

    @patch('nexent.storage.minio.boto3')
    def test_delete_file_not_found(self, mock_boto3):
        """Test delete_file handles 404 error (file not found - idempotent)"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None
        
        error_404 = ClientError(
            {'Error': {'Code': '404', 'Message': 'Not Found'}},
            'DeleteObject'
        )
        mock_client.delete_object.side_effect = error_404

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        success, result = client.delete_file('test.txt')

        assert success is True
        assert "does not exist" in result

    @patch('nexent.storage.minio.boto3')
    def test_delete_file_permission_error(self, mock_boto3):
        """Test delete_file handles permission errors"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None
        
        error_403 = ClientError(
            {'Error': {'Code': '403', 'Message': 'Forbidden'}},
            'DeleteObject'
        )
        mock_client.delete_object.side_effect = error_403

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        success, result = client.delete_file('test.txt')

        assert success is False
        assert "Forbidden" in result

    @patch('nexent.storage.minio.boto3')
    def test_delete_file_unexpected_error(self, mock_boto3):
        """Test delete_file handles unexpected errors"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None
        mock_client.delete_object.side_effect = Exception("Unexpected error")

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        success, result = client.delete_file('test.txt')

        assert success is False
        assert "Unexpected error" in result


class TestMinIOStorageClientExists:
    """Test cases for exists method"""

    @patch('nexent.storage.minio.boto3')
    def test_exists_true(self, mock_boto3):
        """Test exists returns True when file exists"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None
        mock_client.head_object.return_value = {}

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        exists = client.exists('test.txt', 'test-bucket')

        assert exists is True
        mock_client.head_object.assert_called_once_with(Bucket='test-bucket', Key='test.txt')

    @patch('nexent.storage.minio.boto3')
    def test_exists_false(self, mock_boto3):
        """Test exists returns False when file doesn't exist"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None
        
        error_404 = ClientError(
            {'Error': {'Code': '404', 'Message': 'Not Found'}},
            'HeadObject'
        )
        mock_client.head_object.side_effect = error_404

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        exists = client.exists('test.txt')

        assert exists is False

    @patch('nexent.storage.minio.boto3')
    def test_exists_without_bucket(self, mock_boto3):
        """Test exists returns False when bucket is not specified"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin"
        )

        exists = client.exists('test.txt')

        assert exists is False


class TestMinIOStorageClientCopyFile:
    """Test cases for copy_file method"""

    @patch('nexent.storage.minio.boto3')
    def test_copy_file_success(self, mock_boto3):
        """Test successful file copy within the same bucket"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        success, result = client.copy_file('src.txt', 'dst.txt', 'test-bucket')

        assert success is True
        assert result == 'dst.txt'
        mock_client.copy_object.assert_called_once_with(
            Bucket='test-bucket',
            Key='dst.txt',
            CopySource={'Bucket': 'test-bucket', 'Key': 'src.txt'}
        )

    @patch('nexent.storage.minio.boto3')
    def test_copy_file_uses_default_bucket(self, mock_boto3):
        """Test copy_file falls back to default bucket when bucket is not specified"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        success, result = client.copy_file('src.txt', 'dst.txt')

        assert success is True
        assert result == 'dst.txt'
        mock_client.copy_object.assert_called_once_with(
            Bucket='test-bucket',
            Key='dst.txt',
            CopySource={'Bucket': 'test-bucket', 'Key': 'src.txt'}
        )

    @patch('nexent.storage.minio.boto3')
    def test_copy_file_without_bucket(self, mock_boto3):
        """Test copy_file fails when no bucket is configured"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin"
        )

        success, result = client.copy_file('src.txt', 'dst.txt')

        assert success is False
        assert result == "Bucket name is required"
        mock_client.copy_object.assert_not_called()

    @patch('nexent.storage.minio.boto3')
    def test_copy_file_exception(self, mock_boto3):
        """Test copy_file returns failure on unexpected exception"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None
        mock_client.copy_object.side_effect = Exception("copy failed")

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        success, result = client.copy_file('src.txt', 'dst.txt')

        assert success is False
        assert "copy failed" in result


class TestMinIOStorageClientGetFileRange:
    """Test cases for get_file_range method"""

    @patch('nexent.storage.minio.boto3')
    def test_get_file_range_success(self, mock_boto3):
        """Test successful byte-range retrieval returns body stream"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None
        mock_body = MagicMock()
        mock_client.get_object.return_value = {'Body': mock_body}

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        success, result = client.get_file_range('test.pdf', 0, 4095, 'test-bucket')

        assert success is True
        assert result is mock_body
        mock_client.get_object.assert_called_once_with(
            Bucket='test-bucket',
            Key='test.pdf',
            Range='bytes=0-4095',
        )

    @patch('nexent.storage.minio.boto3')
    def test_get_file_range_uses_default_bucket(self, mock_boto3):
        """Test get_file_range falls back to default_bucket when bucket is omitted"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None
        mock_body = MagicMock()
        mock_client.get_object.return_value = {'Body': mock_body}

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        success, _ = client.get_file_range('test.pdf', 100, 199)

        assert success is True
        mock_client.get_object.assert_called_once_with(
            Bucket='test-bucket',
            Key='test.pdf',
            Range='bytes=100-199',
        )

    @patch('nexent.storage.minio.boto3')
    def test_get_file_range_without_bucket(self, mock_boto3):
        """Test get_file_range fails when no bucket is configured"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin"
        )

        success, result = client.get_file_range('test.pdf', 0, 99)

        assert success is False
        assert result == "Bucket name is required"
        mock_client.get_object.assert_not_called()

    @patch('nexent.storage.minio.boto3')
    def test_get_file_range_not_found(self, mock_boto3):
        """Test get_file_range handles 404 ClientError"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None
        error_404 = ClientError(
            {'Error': {'Code': '404', 'Message': 'Not Found'}},
            'GetObject'
        )
        mock_client.get_object.side_effect = error_404

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        success, result = client.get_file_range('missing.pdf', 0, 99)

        assert success is False
        assert "File not found" in result

    @patch('nexent.storage.minio.boto3')
    def test_get_file_range_client_error(self, mock_boto3):
        """Test get_file_range handles non-404 ClientError"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None
        error_403 = ClientError(
            {'Error': {'Code': '403', 'Message': 'Forbidden'}},
            'GetObject'
        )
        mock_client.get_object.side_effect = error_403

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        success, result = client.get_file_range('test.pdf', 0, 99)

        assert success is False
        assert "Failed to get file range" in result

    @patch('nexent.storage.minio.boto3')
    def test_get_file_range_unexpected_error(self, mock_boto3):
        """Test get_file_range handles unexpected exceptions"""
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.head_bucket.return_value = None
        mock_client.get_object.side_effect = Exception("network failure")

        client = MinIOStorageClient(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="test-bucket"
        )

        success, result = client.get_file_range('test.pdf', 0, 99)

        assert success is False
        assert "network failure" in result
