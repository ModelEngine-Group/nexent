import logging
import os
from contextlib import contextmanager
from typing import Any, BinaryIO, Dict, List, Optional, Tuple

import boto3
import psycopg2.extras
from psycopg2 import extensions
from botocore.client import Config
from botocore.exceptions import ClientError
from sqlalchemy import create_engine
from sqlalchemy.orm import class_mapper, sessionmaker

from consts.const import (
    MINIO_ACCESS_KEY,
    MINIO_DEFAULT_BUCKET,
    MINIO_ENDPOINT,
    MINIO_REGION,
    MINIO_SECRET_KEY,
    NEXENT_POSTGRES_PASSWORD,
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from database.db_models import TableBase

logger = logging.getLogger("database.client")


class PostgresClient:
    _instance: Optional['PostgresClient'] = None
    _conn: Optional[psycopg2.extensions.connection] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PostgresClient, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        self.host = POSTGRES_HOST
        self.user = POSTGRES_USER
        self.password = NEXENT_POSTGRES_PASSWORD
        self.database = POSTGRES_DB
        self.port = POSTGRES_PORT
        self.engine = create_engine(
            "postgresql://",
            connect_args={
                "host": self.host,
                "user": self.user,
                "password": self.password,
                "database": self.database,
                "port": self.port,
                "client_encoding": "utf8"
            },
            echo=False,
            pool_size=10,
            pool_pre_ping=True,
            pool_timeout=30
        )
        self.session_maker = sessionmaker(bind=self.engine)

    @staticmethod
    def clean_string_values(data: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure all strings are UTF-8 encoded"""
        cleaned_data = {}
        for key, value in data.items():
            if isinstance(value, str):
                cleaned_data[key] = value.encode(
                    'utf-8', errors='ignore').decode('utf-8')
            else:
                cleaned_data[key] = value
        return cleaned_data


class MinioClient:
    _instance: Optional['MinioClient'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MinioClient, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        self.endpoint = MINIO_ENDPOINT
        self.access_key = MINIO_ACCESS_KEY
        self.secret_key = MINIO_SECRET_KEY
        self.region = MINIO_REGION
        self.default_bucket = MINIO_DEFAULT_BUCKET

        # Initialize S3 client with proxy settings
        self.client = boto3.client(
            's3',
            endpoint_url=self.endpoint,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
            config=Config(
                signature_version='s3v4',
                proxies={
                    'http': None,
                    'https': None
                }
            )
        )

        # Ensure default bucket exists
        self._ensure_bucket_exists(self.default_bucket)

    def _ensure_bucket_exists(self, bucket_name: str) -> None:
        """Ensure bucket exists, create if it doesn't"""
        try:
            self.client.head_bucket(Bucket=bucket_name)
        except ClientError:
            # Bucket doesn't exist, create it
            self.client.create_bucket(Bucket=bucket_name)
            logger.info(f"Created bucket: {bucket_name}")

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
        if object_name is None:
            object_name = os.path.basename(file_path)

        try:
            self.client.upload_file(file_path, bucket, object_name)
            file_url = f"/{bucket}/{object_name}"
            return True, file_url
        except Exception as e:
            return False, str(e)

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
        bucket = bucket or self.default_bucket
        try:
            self.client.upload_fileobj(file_obj, bucket, object_name)
            file_url = f"/{bucket}/{object_name}"
            return True, file_url
        except Exception as e:
            return False, str(e)

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
        bucket = bucket or self.default_bucket
        try:
            self.client.download_file(bucket, object_name, file_path)
            return True, f"File downloaded successfully to {file_path}"
        except Exception as e:
            return False, str(e)

    def get_file_url(self, object_name: str, bucket: Optional[str] = None, expires: int = 3600) -> Tuple[bool, str]:
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
        try:
            url = self.client.generate_presigned_url('get_object', Params={'Bucket': bucket, 'Key': object_name},
                                                     ExpiresIn=expires)
            return True, url
        except Exception as e:
            return False, str(e)

    def get_file_size(self, object_name: str, bucket: Optional[str] = None) -> int:
        bucket = bucket or self.default_bucket
        try:
            response = self.client.head_object(Bucket=bucket, Key=object_name)
            return int(response['ContentLength'])
        except ClientError as e:
            logger.error(
                f"Get file size by objectname({object_name}) failed: {e}")
            return 0

    def list_files(self, prefix: str = "", bucket: Optional[str] = None) -> List[dict]:
        """
        List files in bucket

        Args:
            prefix: Prefix filter
            bucket: Bucket name, if not specified use default bucket

        Returns:
            List[dict]: List of file information
        """
        bucket = bucket or self.default_bucket
        try:
            response = self.client.list_objects_v2(
                Bucket=bucket, Prefix=prefix)
            files = []
            if 'Contents' in response:
                for obj in response['Contents']:
                    files.append(
                        {'key': obj['Key'], 'size': obj['Size'], 'last_modified': obj['LastModified']})
            return files
        except Exception as e:
            logger.error(f"Error listing files: {str(e)}")
            return []

    def delete_file(self, object_name: str, bucket: Optional[str] = None) -> Tuple[bool, str]:
        """
        Delete file

        Args:
            object_name: Object name
            bucket: Bucket name, if not specified use default bucket

        Returns:
            Tuple[bool, str]: (Success status, Success message or error message)
        """
        bucket = bucket or self.default_bucket
        try:
            self.client.delete_object(Bucket=bucket, Key=object_name)
            return True, f"File {object_name} deleted successfully"
        except Exception as e:
            return False, str(e)

    def get_file_stream(self, object_name: str, bucket: Optional[str] = None) -> Tuple[bool, Any]:
        """
        Get file binary stream from MinIO

        Args:
            object_name: Object name
            bucket: Bucket name, if not specified use default bucket

        Returns:
            Tuple[bool, Any]: (Success status, File stream object or error message)
        """
        bucket = bucket or self.default_bucket
        try:
            response = self.client.get_object(Bucket=bucket, Key=object_name)
            return True, response['Body']
        except Exception as e:
            return False, str(e)


# Create global database and MinIO client instances
db_client = PostgresClient()
minio_client = MinioClient()


@contextmanager
def get_db_session(db_session=None):
    """
    param db_session: Optional session to use, if None, a new session will be created.
    Provide a transactional scope around a series of operations.
    """
    session = db_client.session_maker() if db_session is None else db_session
    try:
        yield session
        if db_session is None:
            session.commit()
    except Exception as e:
        if db_session is None:
            session.rollback()
        logger.error(f"Database operation failed: {str(e)}")
        raise e
    finally:
        if db_session is None:
            session.close()


def as_dict(obj):
    if isinstance(obj, TableBase):
        return {c.key: getattr(obj, c.key) for c in class_mapper(obj.__class__).columns}

    # noinspection PyProtectedMember
    return dict(obj._mapping)


def filter_property(data, model_class):
    """
    Filter the data dictionary to only include keys that correspond to columns in the model class.

    :param data: Dictionary containing the data to be filtered.
    :param model_class: The SQLAlchemy model class to filter against.
    :return: A new dictionary with only the keys that match the model's columns.
    """
    model_fields = model_class.__table__.columns.keys()
    return {key: value for key, value in data.items() if key in model_fields}
