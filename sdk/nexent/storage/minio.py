"""
MinIO storage client implementation

Implements StorageClient interface using boto3 S3 client for MinIO compatibility.
"""

import logging
import os
from typing import Any, BinaryIO, Dict, List, Optional, Tuple

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from .storage_client_base import StorageClient

logger = logging.getLogger(__name__)


class MinIOStorageClient(StorageClient):
    """
    MinIO storage client implementation using boto3
    
    This client is compatible with MinIO and S3-compatible storage services.
    """

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
        Initialize MinIO storage client

        Args:
            endpoint: MinIO endpoint URL (e.g., 'http://localhost:9000')
            access_key: Access key ID
            secret_key: Secret access key
            region: AWS region name (optional, defaults to 'us-east-1')
            default_bucket: Default bucket name (optional)
            secure: Whether to use HTTPS (default: True)
        """
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region or "us-east-1"
        self.default_bucket = default_bucket
        self.secure = secure

        # Initialize S3 client with proxy settings
        self.client = boto3.client(
            's3',
            endpoint_url=self.endpoint,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
            use_ssl=self.secure,
            config=Config(
                signature_version='s3v4',
                proxies={
                    'http': None,
                    'https': None
                }
            )
        )

        # Ensure default bucket exists if provided
        if self.default_bucket:
            self._ensure_bucket_exists(self.default_bucket)

    def _ensure_bucket_exists(self, bucket_name: str) -> None:
        """
        Ensure bucket exists, create if it doesn't
        
        Args:
            bucket_name: Name of the bucket to ensure exists
            
        Raises:
            ClientError: If bucket creation fails or bucket check fails with unexpected error
        """
        try:
            self.client.head_bucket(Bucket=bucket_name)
            logger.debug(f"Bucket {bucket_name} already exists")
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == '404':
                # Bucket doesn't exist, create it
                try:
                    self.client.create_bucket(Bucket=bucket_name)
                    logger.info(f"Created bucket: {bucket_name}")
                except ClientError as create_error:
                    error_msg = f"Failed to create bucket {bucket_name}: {create_error}"
                    logger.error(error_msg)
                    raise
            else:
                # Other error (e.g., permission denied)
                error_msg = f"Failed to check bucket {bucket_name}: {e}"
                logger.error(error_msg)
                raise

    def upload_file(
        self,
        file_path: str,
        object_name: Optional[str] = None,
        bucket: Optional[str] = None
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
        bucket = bucket or self.default_bucket
        if bucket is None:
            return False, "Bucket name is required"

        if object_name is None:
            object_name = os.path.basename(file_path)

        try:
            self.client.upload_file(file_path, bucket, object_name)
            # Return path format that can be used with get_file_url() to get presigned URL
            file_url = f"/{bucket}/{object_name}"
            return True, file_url
        except Exception as e:
            logger.error(f"Failed to upload file {file_path}: {e}")
            return False, str(e)

    def upload_fileobj(
        self,
        file_obj: BinaryIO,
        object_name: str,
        bucket: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Upload file object to MinIO

        Args:
            file_obj: File object (BinaryIO)
            object_name: Object name
            bucket: Bucket name, if not specified use default bucket

        Returns:
            Tuple[bool, str]: (Success status, File URL or error message)
        """
        bucket = bucket or self.default_bucket
        if bucket is None:
            return False, "Bucket name is required"

        try:
            self.client.upload_fileobj(file_obj, bucket, object_name)
            # Return path format that can be used with get_file_url() to get presigned URL
            file_url = f"/{bucket}/{object_name}"
            return True, file_url
        except Exception as e:
            logger.error(f"Failed to upload file object {object_name}: {e}")
            return False, str(e)

    def download_file(
        self,
        object_name: str,
        file_path: str,
        bucket: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Download file from MinIO to local

        Args:
            object_name: Object name
            file_path: Local save path
            bucket: Bucket name, if not specified use default bucket

        Returns:
            Tuple[bool, str]: (Success status, Success message or error message)
        """
        bucket = bucket or self.default_bucket
        if bucket is None:
            return False, "Bucket name is required"

        try:
            self.client.download_file(bucket, object_name, file_path)
            return True, f"File downloaded successfully to {file_path}"
        except Exception as e:
            logger.error(f"Failed to download file {object_name}: {e}")
            return False, str(e)

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
        bucket = bucket or self.default_bucket
        if bucket is None:
            return False, "Bucket name is required"

        try:
            url = self.client.generate_presigned_url(
                'get_object',
                Params={'Bucket': bucket, 'Key': object_name},
                ExpiresIn=expires
            )
            return True, url
        except Exception as e:
            logger.error(f"Failed to generate presigned URL for {object_name}: {e}")
            return False, str(e)

    def get_file_stream(
        self,
        object_name: str,
        bucket: Optional[str] = None
    ) -> Tuple[bool, Any]:
        """
        Get file binary stream from MinIO

        Args:
            object_name: Object name
            bucket: Bucket name, if not specified use default bucket

        Returns:
            Tuple[bool, Any]: (Success status, File stream object or error message string)
                On success: (True, stream_object)
                On failure: (False, error_message_string)
        """
        bucket = bucket or self.default_bucket
        if bucket is None:
            return False, "Bucket name is required"

        try:
            response = self.client.get_object(Bucket=bucket, Key=object_name)
            return True, response['Body']
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == '404':
                # File not found is a normal business scenario, log at debug level
                logger.debug(f"File not found when getting stream: {object_name}")
                return False, f"File not found: {object_name}"
            else:
                # Other errors (permission, network, etc.) should be logged as errors
                error_msg = f"Failed to get file stream for {object_name}: {e}"
                logger.error(error_msg)
                return False, error_msg
        except Exception as e:
            error_msg = f"Unexpected error getting file stream for {object_name}: {e}"
            logger.error(error_msg)
            return False, error_msg

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
        bucket = bucket or self.default_bucket
        if bucket is None:
            return 0

        try:
            response = self.client.head_object(Bucket=bucket, Key=object_name)
            return int(response['ContentLength'])
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == '404':
                # File not found is a normal business scenario, log at debug level
                logger.debug(f"File not found when getting size: {object_name}")
            else:
                # Other errors (permission, network, etc.) should be logged as errors
                logger.error(f"Failed to get file size for {object_name}: {e}")
            return 0

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
        bucket = bucket or self.default_bucket
        if bucket is None:
            return []

        try:
            response = self.client.list_objects_v2(
                Bucket=bucket,
                Prefix=prefix
            )
            files = []
            if 'Contents' in response:
                for obj in response['Contents']:
                    files.append({
                        'key': obj['Key'],
                        'size': obj['Size'],
                        'last_modified': obj['LastModified']
                    })
            return files
        except Exception as e:
            logger.error(f"Error listing files: {e}")
            return []

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
        bucket = bucket or self.default_bucket
        if bucket is None:
            return False, "Bucket name is required"

        try:
            self.client.delete_object(Bucket=bucket, Key=object_name)
            return True, f"File {object_name} deleted successfully"
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == '404':
                # File not found - deletion is idempotent, log at debug level
                logger.debug(f"File not found when deleting (idempotent): {object_name}")
                return True, f"File {object_name} does not exist (already deleted)"
            else:
                # Other errors (permission, network, etc.) should be logged as errors
                logger.error(f"Failed to delete file {object_name}: {e}")
                return False, str(e)
        except Exception as e:
            logger.error(f"Failed to delete file {object_name}: {e}")
            return False, str(e)

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
        bucket = bucket or self.default_bucket
        if bucket is None:
            return False, "Bucket name is required"

        try:
            copy_source = {"Bucket": bucket, "Key": source_object}
            self.client.copy_object(
                Bucket=bucket,
                Key=dest_object,
                CopySource=copy_source
            )
            return True, dest_object
        except Exception as e:
            logger.error(f"Failed to copy object {source_object} to {dest_object}: {e}")
            return False, str(e)

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
        bucket = bucket or self.default_bucket
        if bucket is None:
            return False

        try:
            self.client.head_object(Bucket=bucket, Key=object_name)
            return True
        except ClientError:
            return False

