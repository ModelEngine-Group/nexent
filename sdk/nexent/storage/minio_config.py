"""
MinIO storage configuration

Provides configuration class for MinIO storage backend.
"""

from typing import Optional

from .storage_client_base import StorageConfig, StorageType


class MinIOStorageConfig(StorageConfig):
    """MinIO storage configuration"""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        region: Optional[str] = None,
        default_bucket: Optional[str] = None,
        secure: bool = True
    ):
        """
        Initialize MinIO storage configuration

        Args:
            endpoint: MinIO endpoint URL (e.g., 'http://localhost:9000')
            access_key: Access key ID
            secret_key: Secret access key
            region: AWS region name (optional, defaults to 'us-east-1')
            default_bucket: Default bucket name (optional)
            secure: Whether to use HTTPS (default: True)
        """
        self._endpoint = endpoint
        self._access_key = access_key
        self._secret_key = secret_key
        self._region = region
        self._default_bucket = default_bucket
        self._secure = secure

    @property
    def storage_type(self) -> StorageType:
        """Get storage type"""
        return StorageType.MINIO

    @property
    def endpoint(self) -> str:
        """Get endpoint URL"""
        return self._endpoint

    @property
    def access_key(self) -> str:
        """Get access key"""
        return self._access_key

    @property
    def secret_key(self) -> str:
        """Get secret key"""
        return self._secret_key

    @property
    def region(self) -> Optional[str]:
        """Get region"""
        return self._region

    @property
    def default_bucket(self) -> Optional[str]:
        """Get default bucket"""
        return self._default_bucket

    @property
    def secure(self) -> bool:
        """Get secure flag"""
        return self._secure

    def validate(self) -> None:
        """
        Validate MinIO configuration parameters

        Raises:
            ValueError: If required parameters are missing
        """
        if not self._endpoint:
            raise ValueError("endpoint is required for MinIO storage")
        if not self._access_key:
            raise ValueError("access_key is required for MinIO storage")
        if not self._secret_key:
            raise ValueError("secret_key is required for MinIO storage")

