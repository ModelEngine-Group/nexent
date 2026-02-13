"""
Abstract base classes for storage clients and configurations

Defines the common interfaces that all storage implementations must follow.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, BinaryIO, Dict, List, Optional, Tuple


class StorageType(Enum):
    """Storage type enumeration, Defines all supported storage types."""
    MINIO = "minio"
    # Future storage types can be added here
    # S3 = "s3"
    # AZURE = "azure"
    # GCS = "gcs"


class StorageConfig(ABC):
    """Abstract storage configuration base class"""

    @property
    @abstractmethod
    def storage_type(self) -> StorageType:
        """Get storage type"""
        pass

    @abstractmethod
    def validate(self) -> None:
        """
        Validate configuration parameters

        Raises:
            ValueError: If required parameters are missing or invalid
        """
        pass


class StorageClient(ABC):
    """
    Abstract base class for storage clients
    
    All storage implementations must inherit from this class and implement
    all abstract methods.
    """

    @abstractmethod
    def upload_file(
        self,
        file_path: str,
        object_name: Optional[str] = None,
        bucket: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Upload local file to storage

        Args:
            file_path: Local file path
            object_name: Object name, if not specified use filename
            bucket: Bucket name, if not specified use default bucket

        Returns:
            Tuple[bool, str]: (Success status, File URL or error message)
        """
        pass

    @abstractmethod
    def upload_fileobj(
        self,
        file_obj: BinaryIO,
        object_name: str,
        bucket: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Upload file object to storage

        Args:
            file_obj: File object (BinaryIO)
            object_name: Object name
            bucket: Bucket name, if not specified use default bucket

        Returns:
            Tuple[bool, str]: (Success status, File URL or error message)
        """
        pass

    @abstractmethod
    def download_file(
        self,
        object_name: str,
        file_path: str,
        bucket: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Download file from storage to local

        Args:
            object_name: Object name
            file_path: Local save path
            bucket: Bucket name, if not specified use default bucket

        Returns:
            Tuple[bool, str]: (Success status, Success message or error message)
        """
        pass

    @abstractmethod
    def get_file_url(
        self,
        object_name: str,
        bucket: Optional[str] = None,
        expires: int = 3600
    ) -> Tuple[bool, str]:
        """
        Get presigned URL for file

        Args:
            object_name: Object name
            bucket: Bucket name, if not specified use default bucket
            expires: URL expiration time in seconds

        Returns:
            Tuple[bool, str]: (Success status, Presigned URL or error message)
        """
        pass

    @abstractmethod
    def get_file_stream(
        self,
        object_name: str,
        bucket: Optional[str] = None
    ) -> Tuple[bool, Any]:
        """
        Get file binary stream from storage

        Args:
            object_name: Object name
            bucket: Bucket name, if not specified use default bucket

        Returns:
            Tuple[bool, Any]: (Success status, File stream object or error message)
        """
        pass

    @abstractmethod
    def get_file_size(
        self,
        object_name: str,
        bucket: Optional[str] = None
    ) -> int:
        """
        Get file size in bytes

        Args:
            object_name: Object name
            bucket: Bucket name, if not specified use default bucket

        Returns:
            int: File size in bytes, 0 if file not found or error
        """
        pass

    @abstractmethod
    def list_files(
        self,
        prefix: str = "",
        bucket: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List files in bucket

        Args:
            prefix: Prefix filter
            bucket: Bucket name, if not specified use default bucket

        Returns:
            List[Dict[str, Any]]: List of file information dictionaries
                Each dict contains: 'key', 'size', 'last_modified'
        """
        pass

    @abstractmethod
    def delete_file(
        self,
        object_name: str,
        bucket: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Delete file from storage

        Args:
            object_name: Object name
            bucket: Bucket name, if not specified use default bucket

        Returns:
            Tuple[bool, str]: (Success status, Success message or error message)
        """
        pass

    @abstractmethod
    def copy_file(
        self,
        source_object: str,
        dest_object: str,
        bucket: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Copy a file within the same bucket.

        Args:
            source_object: Source object name
            dest_object: Destination object name
            bucket: Bucket name, if not specified use default bucket

        Returns:
            Tuple[bool, str]: (Success status, Destination object name or error message)
        """
        pass

    @abstractmethod
    def file_exists(
        self,
        object_name: str,
        bucket: Optional[str] = None
    ) -> bool:
        """
        Check if file exists in storage

        Args:
            object_name: Object name
            bucket: Bucket name, if not specified use default bucket

        Returns:
            bool: True if file exists, False otherwise
        """
        pass

