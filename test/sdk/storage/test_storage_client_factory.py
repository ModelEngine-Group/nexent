"""
Unit tests for storage_client_factory.py
Tests the create_storage_client_from_config function
"""

import pytest
from unittest.mock import MagicMock, patch
from nexent.storage.storage_client_factory import create_storage_client_from_config
from nexent.storage.minio_config import MinIOStorageConfig
from nexent.storage.storage_client_base import StorageType


class TestCreateStorageClientFromConfig:
    """Test cases for create_storage_client_from_config function"""

    @patch('nexent.storage.storage_client_factory.MinIOStorageClient')
    def test_create_minio_client_success(self, mock_minio_client_class):
        """Test creating MinIO client with valid config"""
        # Setup
        mock_client_instance = MagicMock()
        mock_minio_client_class.return_value = mock_client_instance
        
        config = MinIOStorageConfig(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            region="us-east-1",
            default_bucket="test-bucket",
            secure=False
        )
        
        # Execute
        result = create_storage_client_from_config(config)
        
        # Assert
        assert result == mock_client_instance
        mock_minio_client_class.assert_called_once_with(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            region="us-east-1",
            default_bucket="test-bucket",
            secure=False
        )

    @patch('nexent.storage.storage_client_factory.MinIOStorageClient')
    def test_create_minio_client_with_defaults(self, mock_minio_client_class):
        """Test creating MinIO client with default values"""
        # Setup
        mock_client_instance = MagicMock()
        mock_minio_client_class.return_value = mock_client_instance
        
        config = MinIOStorageConfig(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin"
        )
        
        # Execute
        result = create_storage_client_from_config(config)
        
        # Assert
        assert result == mock_client_instance
        mock_minio_client_class.assert_called_once_with(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            region=None,
            default_bucket=None,
            secure=True
        )

    def test_create_client_invalid_config_type(self):
        """Test creating client with wrong config type for storage type"""
        # Create a mock config that claims to be MINIO but isn't MinIOStorageConfig
        class FakeConfig:
            @property
            def storage_type(self):
                return StorageType.MINIO
            
            def validate(self):
                pass
        
        config = FakeConfig()
        
        # Execute and assert
        with pytest.raises(ValueError, match="Expected MinIOStorageConfig"):
            create_storage_client_from_config(config)

    def test_create_client_unsupported_storage_type(self):
        """Test creating client with unsupported storage type"""
        # Create a mock config with unsupported storage type
        class UnsupportedConfig:
            @property
            def storage_type(self):
                # Create a fake StorageType enum value
                class FakeStorageType:
                    def __init__(self):
                        self.value = "unsupported"
                
                return FakeStorageType()
            
            def validate(self):
                pass
        
        config = UnsupportedConfig()
        
        # Execute and assert
        with pytest.raises(ValueError, match="Unsupported storage type"):
            create_storage_client_from_config(config)

    def test_create_client_validation_failure(self):
        """Test that validation is called before creating client"""
        config = MinIOStorageConfig(
            endpoint="",  # Invalid - will fail validation
            access_key="minioadmin",
            secret_key="minioadmin"
        )
        
        # Execute and assert
        with pytest.raises(ValueError, match="endpoint is required"):
            create_storage_client_from_config(config)

    @patch('nexent.storage.storage_client_factory.MinIOStorageClient')
    def test_create_client_handles_client_initialization_error(self, mock_minio_client_class):
        """Test handling of client initialization errors"""
        # Setup
        mock_minio_client_class.side_effect = Exception("Connection failed")
        
        config = MinIOStorageConfig(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin"
        )
        
        # Execute and assert
        with pytest.raises(Exception, match="Connection failed"):
            create_storage_client_from_config(config)

    @patch('nexent.storage.storage_client_factory.MinIOStorageClient')
    def test_create_minio_client_with_https_endpoint(self, mock_minio_client_class):
        """Test creating MinIO client with HTTPS endpoint"""
        mock_client_instance = MagicMock()
        mock_minio_client_class.return_value = mock_client_instance
        
        config = MinIOStorageConfig(
            endpoint="https://minio.example.com:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            secure=True
        )
        
        result = create_storage_client_from_config(config)
        
        assert result == mock_client_instance
        mock_minio_client_class.assert_called_once_with(
            endpoint="https://minio.example.com:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            region=None,
            default_bucket=None,
            secure=True
        )

    def test_create_client_with_none_config(self):
        """Test creating client with None config raises error"""
        with pytest.raises((AttributeError, TypeError)):
            create_storage_client_from_config(None)

