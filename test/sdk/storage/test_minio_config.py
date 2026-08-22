"""
Unit tests for minio_config.py
Tests the MinIOStorageConfig class
"""

import pytest
from nexent.storage.minio_config import MinIOStorageConfig
from nexent.storage.storage_client_base import StorageType


class TestMinIOStorageConfig:
    """Test cases for MinIOStorageConfig class"""

    def test_init_with_all_parameters(self):
        """Test initialization with all parameters"""
        config = MinIOStorageConfig(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            region="us-east-1",
            default_bucket="test-bucket",
            secure=False
        )
        
        assert config.endpoint == "http://localhost:9000"
        assert config.access_key == "minioadmin"
        assert config.secret_key == "minioadmin"
        assert config.region == "us-east-1"
        assert config.default_bucket == "test-bucket"
        assert config.secure is False

    def test_init_with_minimal_parameters(self):
        """Test initialization with minimal required parameters"""
        config = MinIOStorageConfig(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin"
        )
        
        assert config.endpoint == "http://localhost:9000"
        assert config.access_key == "minioadmin"
        assert config.secret_key == "minioadmin"
        assert config.region is None
        assert config.default_bucket is None
        assert config.secure is True  # Default value

    def test_storage_type_property(self):
        """Test storage_type property returns MINIO"""
        config = MinIOStorageConfig(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin"
        )
        
        assert config.storage_type == StorageType.MINIO

    def test_properties(self):
        """Test all property getters"""
        config = MinIOStorageConfig(
            endpoint="https://minio.example.com",
            access_key="access123",
            secret_key="secret456",
            region="eu-west-1",
            default_bucket="my-bucket",
            secure=True
        )
        
        assert config.endpoint == "https://minio.example.com"
        assert config.access_key == "access123"
        assert config.secret_key == "secret456"
        assert config.region == "eu-west-1"
        assert config.default_bucket == "my-bucket"
        assert config.secure is True

    def test_validate_success(self):
        """Test validation with all required parameters"""
        config = MinIOStorageConfig(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin"
        )
        
        # Should not raise any exception
        config.validate()

    def test_validate_missing_endpoint(self):
        """Test validation fails when endpoint is missing"""
        config = MinIOStorageConfig(
            endpoint="",
            access_key="minioadmin",
            secret_key="minioadmin"
        )
        
        with pytest.raises(ValueError, match="endpoint is required"):
            config.validate()

    def test_validate_missing_access_key(self):
        """Test validation fails when access_key is missing"""
        config = MinIOStorageConfig(
            endpoint="http://localhost:9000",
            access_key="",
            secret_key="minioadmin"
        )
        
        with pytest.raises(ValueError, match="access_key is required"):
            config.validate()

    def test_validate_missing_secret_key(self):
        """Test validation fails when secret_key is missing"""
        config = MinIOStorageConfig(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key=""
        )
        
        with pytest.raises(ValueError, match="secret_key is required"):
            config.validate()

    def test_validate_none_endpoint(self):
        """Test validation fails when endpoint is None"""
        config = MinIOStorageConfig(
            endpoint=None,
            access_key="minioadmin",
            secret_key="minioadmin"
        )
        
        with pytest.raises(ValueError, match="endpoint is required"):
            config.validate()

    def test_validate_none_access_key(self):
        """Test validation fails when access_key is None"""
        config = MinIOStorageConfig(
            endpoint="http://localhost:9000",
            access_key=None,
            secret_key="minioadmin"
        )
        
        with pytest.raises(ValueError, match="access_key is required"):
            config.validate()

    def test_validate_none_secret_key(self):
        """Test validation fails when secret_key is None"""
        config = MinIOStorageConfig(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key=None
        )
        
        with pytest.raises(ValueError, match="secret_key is required"):
            config.validate()

    def test_property_access_after_init(self):
        """Test that properties can be accessed after initialization"""
        config = MinIOStorageConfig(
            endpoint="http://localhost:9000",
            access_key="key1",
            secret_key="secret1",
            region="us-west-2",
            default_bucket="bucket1",
            secure=False
        )
        
        # Test all properties are accessible
        assert config.storage_type == StorageType.MINIO
        assert config.endpoint == "http://localhost:9000"
        assert config.access_key == "key1"
        assert config.secret_key == "secret1"
        assert config.region == "us-west-2"
        assert config.default_bucket == "bucket1"
        assert config.secure is False

    def test_init_with_https_endpoint(self):
        """Test initialization with HTTPS endpoint"""
        config = MinIOStorageConfig(
            endpoint="https://minio.example.com:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            secure=True
        )
        
        assert config.endpoint == "https://minio.example.com:9000"
        assert config.secure is True

    def test_init_with_http_endpoint_secure_false(self):
        """Test initialization with HTTP endpoint and secure=False"""
        config = MinIOStorageConfig(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            secure=False
        )
        
        assert config.endpoint == "http://localhost:9000"
        assert config.secure is False

