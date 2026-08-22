"""
Storage factory for creating storage client instances

Provides factory methods to create different types of storage clients.
"""

from .storage_client_base import StorageClient, StorageConfig, StorageType
from .minio import MinIOStorageClient
from .minio_config import MinIOStorageConfig


def create_storage_client_from_config(config: StorageConfig) -> StorageClient:
    """
    Create storage client from configuration object

    Args:
        config: StorageConfig instance (or its subclass)

    Returns:
        StorageClient: Instance of the requested storage client

    Raises:
        ValueError: If storage type is not supported or configuration is invalid

    Example:
        # Create MinIO client
        config = MinIOStorageConfig(
            endpoint="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            default_bucket="my-bucket"
        )
        client = create_storage_client_from_config(config)

        # Upload a file
        success, url = client.upload_file("local_file.txt", "remote_file.txt")
    """
    # Validate configuration
    config.validate()

    # Create client based on storage type
    if config.storage_type == StorageType.MINIO:
        if not isinstance(config, MinIOStorageConfig):
            raise ValueError(
                f"Expected MinIOStorageConfig for MINIO storage type, "
                f"got {type(config).__name__}"
            )
        return MinIOStorageClient(
            endpoint=config.endpoint,
            access_key=config.access_key,
            secret_key=config.secret_key,
            region=config.region,
            default_bucket=config.default_bucket,
            secure=config.secure
        )
    else:
        raise ValueError(f"Unsupported storage type: {config.storage_type}")
