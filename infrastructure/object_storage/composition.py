# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Trusted service composition for explicitly granted legacy object keys."""

from nexent.storage.errors import InvalidInput
from nexent.storage.models import StorageScope

from infrastructure.object_storage.port import ObjectBinding, S3ObjectStore


def bind_preview_objects(object_names: frozenset[str]):
    """Bind only the source and derived preview keys selected by Management."""
    from contracts.constants import environment

    if not all(
        (
            environment.MINIO_ENDPOINT,
            environment.MINIO_ACCESS_KEY,
            environment.MINIO_SECRET_KEY,
            environment.MINIO_DEFAULT_BUCKET,
        )
    ):
        raise InvalidInput()

    def client_factory(remaining):
        import boto3
        from botocore.config import Config

        return boto3.client(
            "s3",
            endpoint_url=environment.MINIO_ENDPOINT,
            aws_access_key_id=environment.MINIO_ACCESS_KEY,
            aws_secret_access_key=environment.MINIO_SECRET_KEY,
            region_name=environment.MINIO_REGION or "us-east-1",
            config=Config(
                signature_version="s3v4",
                connect_timeout=min(5, remaining),
                read_timeout=min(30, remaining),
                retries={"total_max_attempts": 1},
                proxies={"http": None, "https": None},
            ),
        )

    scope = StorageScope(
        "management", None, "office-preview", frozenset({"files"}), system=True
    )
    binding = ObjectBinding(
        "files",
        environment.MINIO_DEFAULT_BUCKET,
        "",
        frozenset({"management"}),
        writable=True,
        allow_system=True,
        exact_keys=frozenset(object_names),
    )
    return S3ObjectStore(scope, binding, client_factory)
