import logging
from contextlib import contextmanager
from typing import Any, BinaryIO, Dict, List, Optional, Tuple

import psycopg2
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
from nexent.storage.storage_client_factory import create_storage_client_from_config, MinIOStorageConfig


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
    """
    MinIO client wrapper using storage SDK

    This class maintains backward compatibility with the existing MinioClient interface
    while using the new storage SDK under the hood.
    """
    _instance: Optional['MinioClient'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MinioClient, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        # Determine if endpoint uses HTTPS
        secure = MINIO_ENDPOINT.startswith(
            'https://') if MINIO_ENDPOINT else True
        # Initialize storage client using SDK factory
        self.storage_config = MinIOStorageConfig(
            endpoint=MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            region=MINIO_REGION,
            default_bucket=MINIO_DEFAULT_BUCKET,
            secure=secure
        )
        self._storage_client = create_storage_client_from_config(
            self.storage_config)

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
        return self._storage_client.download_file(object_name, file_path, bucket)

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
        return self._storage_client.get_file_size(object_name, bucket)

    def list_files(self, prefix: str = "", bucket: Optional[str] = None) -> List[dict]:
        """
        List files in bucket

        Args:
            prefix: Prefix filter
            bucket: Bucket name, if not specified use default bucket

        Returns:
            List[dict]: List of file information
        """
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
        return self._storage_client.get_file_stream(object_name, bucket)

    def file_exists(self, object_name: str, bucket: Optional[str] = None) -> bool:
        """
        Check if file exists in MinIO

        Args:
            object_name: Object name
            bucket: Bucket name, if not specified use default bucket

        Returns:
            bool: True if file exists, False otherwise
        """
        return self._storage_client.file_exists(object_name, bucket)

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
        return self._storage_client.copy_file(source_object, dest_object, bucket)


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

    # Handle SQLAlchemy ORM objects (both TableBase and other DeclarativeBase subclasses)
    if hasattr(obj, '__class__') and hasattr(obj.__class__, '__mapper__'):
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
