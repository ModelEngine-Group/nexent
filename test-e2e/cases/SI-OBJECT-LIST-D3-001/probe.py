# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exercise current scoped listing against a dedicated real MinIO bucket."""

import hashlib
import io
import json
import time
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from nexent.storage.errors import CapabilityUnsupported, InvalidInput
from nexent.storage.models import ObjectRef, OperationContext, PageRequest, StorageScope

from infrastructure.object_storage.port import ObjectBinding, S3ObjectStore


def context():
    return OperationContext("object-list-probe", time.monotonic() + 20)


def main():
    calls = []

    def factory(remaining):
        calls.append(True)
        return boto3.client(
            "s3",
            endpoint_url="http://store:9000",
            aws_access_key_id="fixture-admin",
            aws_secret_access_key="fixture-password-12345",
            region_name="us-east-1",
            config=Config(
                signature_version="s3v4",
                connect_timeout=min(2, remaining),
                read_timeout=min(5, remaining),
                retries={"total_max_attempts": 1},
                proxies={"http": None, "https": None},
            ),
        )

    deadline = time.monotonic() + 30
    while True:
        try:
            with closing(factory(5)) as client:
                client.create_bucket(Bucket="listing-probe")
            break
        except (BotoCoreError, ClientError):
            if time.monotonic() > deadline:
                raise
            time.sleep(0.2)
    binding = ObjectBinding(
        "files", "listing-probe", "managed/", {"management"}, writable=True
    )
    scope = StorageScope(
        "management", "tenant-a", "actor", {"files"}, resource_prefix="run/one"
    )
    store = S3ObjectStore(scope, binding, factory)
    foreign = S3ObjectStore(replace(scope, tenant_id="tenant-b"), binding, factory)
    neighbour = S3ObjectStore(
        replace(scope, resource_prefix="run/two"), binding, factory
    )
    for target, keys in (
        (store, ("artifacts/a", "artifacts/b", "artifacts/c", "outside")),
        (foreign, ("artifacts/foreign",)),
        (neighbour, ("artifacts/neighbour",)),
    ):
        for key in keys:
            target.put(
                ObjectRef("files", key),
                io.BytesIO(b"abc"),
                size=3,
                content_type="text/plain",
                context=context(),
            )
    pages, cursor, first_cursor = [], None, None
    for _ in range(5):
        page = store.list(
            "artifacts/", PageRequest(limit=1, cursor=cursor), context=context()
        )
        assert len(page.items) <= 1
        for item in page.items:
            assert item.size == 3 and item.ref.version.value.startswith("etag:")
            assert (
                item.sha256 is None and item.content_type == "application/octet-stream"
            )
            pages.append(item.ref.key)
        if first_cursor is None:
            first_cursor = page.next_cursor
        cursor = page.next_cursor
        if cursor is None:
            break
    assert pages == ["artifacts/a", "artifacts/b", "artifacts/c"] and cursor is None
    assert [
        item.ref.key
        for item in foreign.list("", PageRequest(), context=context()).items
    ] == ["artifacts/foreign"]
    assert [
        item.ref.key
        for item in neighbour.list("", PageRequest(), context=context()).items
    ] == ["artifacts/neighbour"]
    assert len(store.list("", PageRequest(), context=context()).items) == 4
    before = len(calls)
    rejected = 0
    for target, prefix in (
        (foreign, "artifacts/"),
        (store, "outside"),
        (neighbour, "artifacts/"),
    ):
        try:
            target.list(
                prefix, PageRequest(limit=1, cursor=first_cursor), context=context()
            )
        except InvalidInput:
            rejected += 1
        else:
            raise AssertionError("incompatible cursor accepted")
    grant = S3ObjectStore(
        replace(scope, resource_prefix=""),
        replace(binding, exact_keys={"allowed"}),
        factory,
    )
    try:
        grant.list("", PageRequest(), context=context())
    except CapabilityUnsupported:
        rejected += 1
    else:
        raise AssertionError("finite grant enumerated bucket")
    assert len(calls) == before and rejected == 4
    hashes = {
        name: hashlib.sha256(Path("/source", name).read_bytes()).hexdigest()
        for name in (
            "infrastructure/object_storage/listing.py",
            "infrastructure/object_storage/port.py",
            "sdk/nexent/storage/models.py",
        )
    }
    print(
        json.dumps(
            {"keys": pages, "scope_rejections": rejected, "source_hashes": hashes}
        )
    )


if __name__ == "__main__":
    main()
