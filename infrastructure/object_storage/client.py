# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from typing import Any, BinaryIO, Dict, List, Optional, Tuple

from contracts.constants.environment import (
    MINIO_ACCESS_KEY,
    MINIO_DEFAULT_BUCKET,
    MINIO_ENDPOINT,
    MINIO_REGION,
    MINIO_SECRET_KEY,
)
from nexent.storage.storage_client_factory import MinIOStorageConfig, create_storage_client_from_config


class MinioClient:
    """
    MinIO client wrapper using storage SDK

    This class maintains backward compatibility with the existing MinioClient interface
    while using the new storage SDK under the hood.
    """

    _instance: Optional["MinioClient"] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MinioClient, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if MinioClient._initialized:
            return
        MinioClient._initialized = True
        # Explicitly initialize attributes so external callers never hit missing-attribute errors.
        self._storage_client = None
        self.storage_config = None

    def _ensure_initialized(self):
        """Lazily initialize the storage client on first use."""
        if not hasattr(self, "_storage_client") or self._storage_client is None:
            secure = MINIO_ENDPOINT.startswith("https://") if MINIO_ENDPOINT else True
            self.storage_config = MinIOStorageConfig(
                endpoint=MINIO_ENDPOINT,
                access_key=MINIO_ACCESS_KEY,
                secret_key=MINIO_SECRET_KEY,
                region=MINIO_REGION,
                default_bucket=MINIO_DEFAULT_BUCKET,
                secure=secure,
            )
            self._storage_client = create_storage_client_from_config(self.storage_config)
            return True
        return False

    @property
    def default_bucket(self) -> Optional[str]:
        """
        Resolve default bucket safely for callers that need bucket info.
        Falls back to configured constant when lazy init has not run yet.
        """
        try:
            self._ensure_initialized()
        except Exception:
            # Keep this accessor resilient; operational methods can still raise
            # detailed storage errors when invoked.
            pass

        if getattr(self, "storage_config", None) is not None:
            return self.storage_config.default_bucket
        return MINIO_DEFAULT_BUCKET

    def upload_file(
        self, file_path: str, object_name: Optional[str] = None, bucket: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Upload local file to MinIO

        Args:
            file_path: Local file path
            object_name: Object name, if not specified use filename
            bucket: Bucket name, if not specified use default bucket

        Returns:
            Tuple[bool, str]: (Success status, File URL or error message)
        """
        self._ensure_initialized()
        return self._storage_client.upload_file(file_path, object_name, bucket)

    def upload_fileobj(self, file_obj: BinaryIO, object_name: str, bucket: Optional[str] = None) -> Tuple[bool, str]:
        """
        Upload file object to MinIO

        Args:
            file_obj: File object
            object_name: Object name
            bucket: Bucket name, if not specified use default bucket

        Returns:
            Tuple[bool, str]: (Success status, File URL or error message)
        """
        self._ensure_initialized()
        return self._storage_client.upload_fileobj(file_obj, object_name, bucket)

    def download_file(self, object_name: str, file_path: str, bucket: Optional[str] = None) -> Tuple[bool, str]:
        """
        Download file from MinIO to local

        Args:
            object_name: Object name
            file_path: Local save path
            bucket: Bucket name, if not specified use default bucket

        Returns:
            Tuple[bool, str]: (Success status, Success message or error message)
        """
        self._ensure_initialized()
        return self._storage_client.download_file(object_name, file_path, bucket)

    def get_file_url(self, object_name: str, bucket: Optional[str] = None, expires: int = 86400) -> Tuple[bool, str]:
        """
        Get presigned URL for file

        Args:
            object_name: Object name
            bucket: Bucket name, if not specified use default bucket
            expires: URL expiration time in seconds (default 86400 = 24 hours)

        Returns:
            Tuple[bool, str]: (Success status, Presigned URL or error message)
        """
        self._ensure_initialized()
        return self._storage_client.get_file_url(object_name, bucket, expires)

    def get_file_size(self, object_name: str, bucket: Optional[str] = None) -> int:
        """
        Get file size in bytes

        Args:
            object_name: Object name
            bucket: Bucket name, if not specified use default bucket

        Returns:
            int: File size in bytes, 0 if file not found or error
        """
        self._ensure_initialized()
        return self._storage_client.get_file_size(object_name, bucket)

    def get_file_size_strict(
        self,
        object_name: str,
        bucket: Optional[str] = None,
    ) -> Optional[int]:
        """Return authoritative size, distinguishing a missing object from operational errors."""
        self._ensure_initialized()
        return self._storage_client.get_file_size_strict(object_name, bucket)

    def list_files(self, prefix: str = "", bucket: Optional[str] = None) -> List[dict]:
        """
        List files in bucket

        Args:
            prefix: Prefix filter
            bucket: Bucket name, if not specified use default bucket

        Returns:
            List[dict]: List of file information
        """
        self._ensure_initialized()
        return self._storage_client.list_files(prefix, bucket)

    def delete_file(self, object_name: str, bucket: Optional[str] = None) -> Tuple[bool, str]:
        """
        Delete file

        Args:
            object_name: Object name
            bucket: Bucket name, if not specified use default bucket

        Returns:
            Tuple[bool, str]: (Success status, Success message or error message)
        """
        self._ensure_initialized()
        return self._storage_client.delete_file(object_name, bucket)

    def get_file_stream(self, object_name: str, bucket: Optional[str] = None) -> Tuple[bool, Any]:
        """
        Get file binary stream from MinIO

        Args:
            object_name: Object name
            bucket: Bucket name, if not specified use default bucket

        Returns:
            Tuple[bool, Any]: (Success status, File stream object or error message)
        """
        self._ensure_initialized()
        return self._storage_client.get_file_stream(object_name, bucket)

    def get_file_range(self, object_name: str, start: int, end: int, bucket: Optional[str] = None) -> Tuple[bool, Any]:
        """
        Get a byte-range slice of a file from MinIO.

        Args:
            object_name: Object name
            start: Start byte offset (inclusive)
            end: End byte offset (inclusive), matching HTTP Range semantics
            bucket: Bucket name, if not specified use default bucket

        Returns:
            Tuple[bool, Any]: (True, raw_body_stream) on success, (False, error_str) on failure
        """
        self._ensure_initialized()
        return self._storage_client.get_file_range(object_name, start, end, bucket)

    def file_exists(self, object_name: str, bucket: Optional[str] = None) -> bool:
        """
        Check if file exists in MinIO

        Args:
            object_name: Object name
            bucket: Bucket name, if not specified use default bucket

        Returns:
            bool: True if file exists, False otherwise
        """
        self._ensure_initialized()
        return self._storage_client.exists(object_name, bucket)

    def copy_file(self, source_object: str, dest_object: str, bucket: Optional[str] = None) -> Tuple[bool, str]:
        """
        Copy a file within the same bucket (atomic operation)

        Args:
            source_object: Source object name
            dest_object: Destination object name
            bucket: Bucket name, if not specified use default bucket

        Returns:
            Tuple[bool, str]: (Success status, Destination object name or error message)
        """
        self._ensure_initialized()
        return self._storage_client.copy_file(source_object, dest_object, bucket)


minio_client = MinioClient()
