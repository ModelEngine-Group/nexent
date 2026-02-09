"""
Unit tests for backend/database/client.py
Tests PostgresClient, MinioClient, and utility functions
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch, Mock
from contextlib import contextmanager

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

# Mock nexent.storage modules
nexent_mock = MagicMock()
nexent_storage_mock = MagicMock()
nexent_storage_factory_mock = MagicMock()
storage_client_mock = MagicMock()
nexent_storage_factory_mock.create_storage_client_from_config = MagicMock(
    return_value=storage_client_mock)
nexent_storage_factory_mock.MinIOStorageConfig = MagicMock()
nexent_storage_mock.storage_client_factory = nexent_storage_factory_mock
nexent_mock.storage = nexent_storage_mock
sys.modules['nexent'] = nexent_mock
sys.modules['nexent.storage'] = nexent_storage_mock
sys.modules['nexent.storage.storage_client_factory'] = nexent_storage_factory_mock

# Mock database.db_models
db_models_mock = MagicMock()
db_models_mock.TableBase = MagicMock()
sys.modules['database'] = MagicMock()
sys.modules['database.db_models'] = db_models_mock
sys.modules['backend.database.db_models'] = db_models_mock

# Mock sqlalchemy
sqlalchemy_mock = MagicMock()
sys.modules['sqlalchemy'] = sqlalchemy_mock
sys.modules['sqlalchemy.orm'] = MagicMock()
sys.modules['sqlalchemy.orm.class_mapper'] = MagicMock()
sys.modules['sqlalchemy.orm.sessionmaker'] = MagicMock()

# Mock psycopg2
sys.modules['psycopg2'] = MagicMock()
sys.modules['psycopg2.extensions'] = MagicMock()

# Patch storage factory before importing
with patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock), \
        patch('nexent.storage.storage_client_factory.MinIOStorageConfig'):
    from backend.database.client import (
        PostgresClient,
        MinioClient,
        db_client,
        minio_client,
        get_db_session,
        as_dict,
        filter_property
    )


class TestPostgresClient:
    """Test cases for PostgresClient class"""

    def test_postgres_client_init(self, mocker):
        """Test PostgresClient initialization"""
        # Reset singleton instance
        PostgresClient._instance = None

        # Patch the constants
        mocker.patch('backend.database.client.POSTGRES_HOST', 'localhost')
        mocker.patch('backend.database.client.POSTGRES_USER', 'test_user')
        mocker.patch(
            'backend.database.client.NEXENT_POSTGRES_PASSWORD', 'test_password')
        mocker.patch('backend.database.client.POSTGRES_DB', 'test_db')
        mocker.patch('backend.database.client.POSTGRES_PORT', 5432)

        # Mock the SQLAlchemy functions
        mock_engine = MagicMock()
        mock_create_engine = mocker.patch(
            'backend.database.client.create_engine', return_value=mock_engine)
        mock_session = MagicMock()
        mock_sessionmaker = mocker.patch(
            'backend.database.client.sessionmaker', return_value=mock_session)

        client = PostgresClient()

        assert client.host == 'localhost'
        assert client.user == 'test_user'
        assert client.password == 'test_password'
        assert client.database == 'test_db'
        assert client.port == 5432
        mock_create_engine.assert_called_once()
        mock_sessionmaker.assert_called_once_with(bind=mock_engine)

    def test_postgres_client_singleton(self):
        """Test PostgresClient is a singleton"""
        # Reset singleton instance
        PostgresClient._instance = None

        client1 = PostgresClient()
        client2 = PostgresClient()

        assert client1 is client2

    def test_clean_string_values(self):
        """Test clean_string_values static method"""
        data = {
            'str1': 'test string',
            'str2': 'another string',
            'int1': 123,
            'list1': [1, 2, 3],
            'dict1': {'key': 'value'}
        }

        result = PostgresClient.clean_string_values(data)

        assert result['str1'] == 'test string'
        assert result['str2'] == 'another string'
        assert result['int1'] == 123
        assert result['list1'] == [1, 2, 3]
        assert result['dict1'] == {'key': 'value'}

    def test_clean_string_values_with_unicode(self):
        """Test clean_string_values handles unicode strings"""
        data = {
            'unicode_str': '测试字符串',
            'normal_str': 'normal string'
        }

        result = PostgresClient.clean_string_values(data)

        assert result['unicode_str'] == '测试字符串'
        assert result['normal_str'] == 'normal string'


class TestMinioClient:
    """Test cases for MinioClient class"""

    @patch('backend.database.client.create_storage_client_from_config')
    @patch('backend.database.client.MinIOStorageConfig')
    def test_minio_client_init(self, mock_config_class, mock_create_client):
        """Test MinioClient initialization"""
        # Reset singleton instance
        MinioClient._instance = None

        mock_config = MagicMock()
        mock_config.default_bucket = 'test-bucket'
        mock_config_class.return_value = mock_config
        mock_storage_client = MagicMock()
        mock_create_client.return_value = mock_storage_client

        client = MinioClient()

        assert client.storage_config == mock_config
        assert client._storage_client == mock_storage_client
        mock_config_class.assert_called_once()
        mock_create_client.assert_called_once_with(mock_config)

    def test_minio_client_singleton(self):
        """Test MinioClient is a singleton"""
        # Reset singleton instance
        MinioClient._instance = None

        with patch('backend.database.client.create_storage_client_from_config'), \
                patch('backend.database.client.MinIOStorageConfig'):
            client1 = MinioClient()
            client2 = MinioClient()

            assert client1 is client2

    @patch('backend.database.client.create_storage_client_from_config')
    @patch('backend.database.client.MinIOStorageConfig')
    def test_minio_client_upload_file(self, mock_config_class, mock_create_client):
        """Test MinioClient.upload_file delegates to storage client"""
        MinioClient._instance = None

        mock_storage_client = MagicMock()
        mock_storage_client.upload_file.return_value = (
            True, '/bucket/file.txt')
        mock_create_client.return_value = mock_storage_client
        mock_config_class.return_value = MagicMock()

        client = MinioClient()
        success, result = client.upload_file(
            '/path/to/file.txt', 'file.txt', 'bucket')

        assert success is True
        assert result == '/bucket/file.txt'
        mock_storage_client.upload_file.assert_called_once_with(
            '/path/to/file.txt', 'file.txt', 'bucket')

    @patch('backend.database.client.create_storage_client_from_config')
    @patch('backend.database.client.MinIOStorageConfig')
    def test_minio_client_upload_fileobj(self, mock_config_class, mock_create_client):
        """Test MinioClient.upload_fileobj delegates to storage client"""
        MinioClient._instance = None

        from io import BytesIO
        mock_storage_client = MagicMock()
        mock_storage_client.upload_fileobj.return_value = (
            True, '/bucket/file.txt')
        mock_create_client.return_value = mock_storage_client
        mock_config_class.return_value = MagicMock()

        client = MinioClient()
        file_obj = BytesIO(b'test data')
        success, result = client.upload_fileobj(file_obj, 'file.txt', 'bucket')

        assert success is True
        assert result == '/bucket/file.txt'
        mock_storage_client.upload_fileobj.assert_called_once_with(
            file_obj, 'file.txt', 'bucket')

    @patch('backend.database.client.create_storage_client_from_config')
    @patch('backend.database.client.MinIOStorageConfig')
    def test_minio_client_download_file(self, mock_config_class, mock_create_client):
        """Test MinioClient.download_file delegates to storage client"""
        MinioClient._instance = None

        mock_storage_client = MagicMock()
        mock_storage_client.download_file.return_value = (
            True, 'Downloaded successfully')
        mock_create_client.return_value = mock_storage_client
        mock_config_class.return_value = MagicMock()

        client = MinioClient()
        success, result = client.download_file(
            'file.txt', '/path/to/download.txt', 'bucket')

        assert success is True
        assert result == 'Downloaded successfully'
        mock_storage_client.download_file.assert_called_once_with(
            'file.txt', '/path/to/download.txt', 'bucket')

    @patch('backend.database.client.create_storage_client_from_config')
    @patch('backend.database.client.MinIOStorageConfig')
    def test_minio_client_get_file_url(self, mock_config_class, mock_create_client):
        """Test MinioClient.get_file_url delegates to storage client"""
        MinioClient._instance = None

        mock_storage_client = MagicMock()
        mock_storage_client.get_file_url.return_value = (
            True, 'http://example.com/file.txt')
        mock_create_client.return_value = mock_storage_client
        mock_config_class.return_value = MagicMock()

        client = MinioClient()
        success, result = client.get_file_url('file.txt', 'bucket', 7200)

        assert success is True
        assert result == 'http://example.com/file.txt'
        mock_storage_client.get_file_url.assert_called_once_with(
            'file.txt', 'bucket', 7200)

    @patch('backend.database.client.create_storage_client_from_config')
    @patch('backend.database.client.MinIOStorageConfig')
    def test_minio_client_get_file_size(self, mock_config_class, mock_create_client):
        """Test MinioClient.get_file_size delegates to storage client"""
        MinioClient._instance = None

        mock_storage_client = MagicMock()
        mock_storage_client.get_file_size.return_value = 1024
        mock_create_client.return_value = mock_storage_client
        mock_config_class.return_value = MagicMock()

        client = MinioClient()
        size = client.get_file_size('file.txt', 'bucket')

        assert size == 1024
        mock_storage_client.get_file_size.assert_called_once_with(
            'file.txt', 'bucket')

    @patch('backend.database.client.create_storage_client_from_config')
    @patch('backend.database.client.MinIOStorageConfig')
    def test_minio_client_list_files(self, mock_config_class, mock_create_client):
        """Test MinioClient.list_files delegates to storage client"""
        MinioClient._instance = None

        mock_storage_client = MagicMock()
        mock_storage_client.list_files.return_value = [
            {'key': 'file1.txt', 'size': 100},
            {'key': 'file2.txt', 'size': 200}
        ]
        mock_create_client.return_value = mock_storage_client
        mock_config_class.return_value = MagicMock()

        client = MinioClient()
        files = client.list_files('prefix/', 'bucket')

        assert len(files) == 2
        assert files[0]['key'] == 'file1.txt'
        mock_storage_client.list_files.assert_called_once_with(
            'prefix/', 'bucket')

    @patch('backend.database.client.create_storage_client_from_config')
    @patch('backend.database.client.MinIOStorageConfig')
    def test_minio_client_delete_file(self, mock_config_class, mock_create_client):
        """Test MinioClient.delete_file delegates to storage client"""
        MinioClient._instance = None

        mock_storage_client = MagicMock()
        mock_storage_client.delete_file.return_value = (
            True, 'Deleted successfully')
        mock_create_client.return_value = mock_storage_client
        mock_config_class.return_value = MagicMock()

        client = MinioClient()
        success, result = client.delete_file('file.txt', 'bucket')

        assert success is True
        assert result == 'Deleted successfully'
        mock_storage_client.delete_file.assert_called_once_with(
            'file.txt', 'bucket')

    @patch('backend.database.client.create_storage_client_from_config')
    @patch('backend.database.client.MinIOStorageConfig')
    def test_minio_client_get_file_stream(self, mock_config_class, mock_create_client):
        """Test MinioClient.get_file_stream delegates to storage client"""
        MinioClient._instance = None

        from io import BytesIO
        mock_storage_client = MagicMock()
        mock_stream = BytesIO(b'test data')
        mock_storage_client.get_file_stream.return_value = (True, mock_stream)
        mock_create_client.return_value = mock_storage_client
        mock_config_class.return_value = MagicMock()

        client = MinioClient()
        success, result = client.get_file_stream('file.txt', 'bucket')

        assert success is True
        assert result == mock_stream
        mock_storage_client.get_file_stream.assert_called_once_with(
            'file.txt', 'bucket')

    @patch('backend.database.client.create_storage_client_from_config')
    @patch('backend.database.client.MinIOStorageConfig')
    def test_minio_client_file_exists_true(self, mock_config_class, mock_create_client):
        """Test MinioClient.file_exists returns True when file exists"""
        MinioClient._instance = None

        mock_storage_client = MagicMock()
        mock_storage_client.file_exists.return_value = True
        mock_create_client.return_value = mock_storage_client
        mock_config_class.return_value = MagicMock()

        client = MinioClient()
        result = client.file_exists('file.txt', 'bucket')

        assert result is True
        mock_storage_client.file_exists.assert_called_once_with('file.txt', 'bucket')

    @patch('backend.database.client.create_storage_client_from_config')
    @patch('backend.database.client.MinIOStorageConfig')
    def test_minio_client_file_exists_false(self, mock_config_class, mock_create_client):
        """Test MinioClient.file_exists returns False when file does not exist"""
        MinioClient._instance = None

        mock_storage_client = MagicMock()
        mock_storage_client.file_exists.return_value = False
        mock_create_client.return_value = mock_storage_client
        mock_config_class.return_value = MagicMock()

        client = MinioClient()
        result = client.file_exists('file.txt', 'bucket')

        assert result is False
        mock_storage_client.file_exists.assert_called_once_with('file.txt', 'bucket')

    @patch('backend.database.client.create_storage_client_from_config')
    @patch('backend.database.client.MinIOStorageConfig')
    def test_minio_client_copy_file_success(self, mock_config_class, mock_create_client):
        """Test MinioClient.copy_file successfully copies file"""
        MinioClient._instance = None

        mock_storage_client = MagicMock()
        mock_storage_client.copy_file.return_value = (True, 'dest/file.pdf')
        mock_create_client.return_value = mock_storage_client
        mock_config = MagicMock()
        mock_config.default_bucket = 'test-bucket'
        mock_config_class.return_value = mock_config

        client = MinioClient()
        success, result = client.copy_file('source/file.pdf', 'dest/file.pdf', 'bucket')

        assert success is True
        assert result == 'dest/file.pdf'
        mock_storage_client.copy_file.assert_called_once_with(
            'source/file.pdf',
            'dest/file.pdf',
            'bucket'
        )

    @patch('backend.database.client.create_storage_client_from_config')
    @patch('backend.database.client.MinIOStorageConfig')
    def test_minio_client_copy_file_with_default_bucket(self, mock_config_class, mock_create_client):
        """Test MinioClient.copy_file uses default bucket when not specified"""
        MinioClient._instance = None

        mock_storage_client = MagicMock()
        mock_storage_client.copy_file.return_value = (True, 'dest/file.pdf')
        mock_create_client.return_value = mock_storage_client
        mock_config = MagicMock()
        mock_config.default_bucket = 'default-bucket'
        mock_config_class.return_value = mock_config

        client = MinioClient()
        success, result = client.copy_file('source/file.pdf', 'dest/file.pdf')

        assert success is True
        assert result == 'dest/file.pdf'
        mock_storage_client.copy_file.assert_called_once_with(
            'source/file.pdf',
            'dest/file.pdf',
            None
        )

    @patch('backend.database.client.create_storage_client_from_config')
    @patch('backend.database.client.MinIOStorageConfig')
    def test_minio_client_copy_file_failure(self, mock_config_class, mock_create_client):
        """Test MinioClient.copy_file handles errors properly"""
        MinioClient._instance = None

        mock_storage_client = MagicMock()
        mock_storage_client.copy_file.return_value = (False, 'Copy failed')
        mock_create_client.return_value = mock_storage_client
        mock_config = MagicMock()
        mock_config.default_bucket = 'test-bucket'
        mock_config_class.return_value = mock_config

        client = MinioClient()
        success, result = client.copy_file('source/file.pdf', 'dest/file.pdf')

        assert success is False
        assert 'Copy failed' in result


class TestGetDbSession:
    """Test cases for get_db_session context manager"""

    def test_get_db_session_with_new_session(self):
        """Test get_db_session creates and manages a new session"""
        mock_session = MagicMock()
        mock_session_maker = MagicMock(return_value=mock_session)

        # Mock db_client
        with patch('backend.database.client.db_client') as mock_db_client:
            mock_db_client.session_maker = mock_session_maker

            with get_db_session() as session:
                assert session == mock_session

            mock_session_maker.assert_called_once()
            mock_session.commit.assert_called_once()
            mock_session.close.assert_called_once()

    def test_get_db_session_with_existing_session(self):
        """Test get_db_session uses provided session"""
        mock_session = MagicMock()

        with get_db_session(mock_session) as session:
            assert session == mock_session

        # Should not commit or close when session is provided
        mock_session.commit.assert_not_called()
        mock_session.close.assert_not_called()

    def test_get_db_session_rollback_on_exception(self):
        """Test get_db_session rolls back on exception"""
        mock_session = MagicMock()
        mock_session_maker = MagicMock(return_value=mock_session)

        with patch('backend.database.client.db_client') as mock_db_client:
            mock_db_client.session_maker = mock_session_maker

            with pytest.raises(ValueError):
                with get_db_session() as session:
                    raise ValueError("Test error")

            mock_session.rollback.assert_called_once()
            mock_session.close.assert_called_once()
            mock_session.commit.assert_not_called()

    def test_get_db_session_no_rollback_on_provided_session_exception(self):
        """Test get_db_session doesn't rollback provided session on exception"""
        mock_session = MagicMock()

        with pytest.raises(ValueError):
            with get_db_session(mock_session):
                raise ValueError("Test error")

        # Should not rollback or close when session is provided
        mock_session.rollback.assert_not_called()
        mock_session.close.assert_not_called()


class TestFilterProperty:
    """Test cases for filter_property function"""

    def test_filter_property_filters_correctly(self):
        """Test filter_property filters data to match model columns"""
        mock_model = MagicMock()
        mock_model.__table__ = MagicMock()
        mock_model.__table__.columns = MagicMock()
        mock_model.__table__.columns.keys.return_value = [
            'id', 'name', 'email']

        data = {
            'id': 1,
            'name': 'test',
            'email': 'test@example.com',
            'extra_field': 'should be removed'
        }

        result = filter_property(data, mock_model)

        assert 'id' in result
        assert 'name' in result
        assert 'email' in result
        assert 'extra_field' not in result

    def test_filter_property_empty_data(self):
        """Test filter_property with empty data"""
        mock_model = MagicMock()
        mock_model.__table__ = MagicMock()
        mock_model.__table__.columns = MagicMock()
        mock_model.__table__.columns.keys.return_value = ['id', 'name']

        data = {}

        result = filter_property(data, mock_model)

        assert result == {}

    def test_filter_property_no_matching_fields(self):
        """Test filter_property when no fields match"""
        mock_model = MagicMock()
        mock_model.__table__ = MagicMock()
        mock_model.__table__.columns = MagicMock()
        mock_model.__table__.columns.keys.return_value = ['id', 'name']

        data = {
            'other_field': 'value',
            'another_field': 'value2'
        }

        result = filter_property(data, mock_model)

        assert result == {}
