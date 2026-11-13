# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Scoped S3 ObjectStore. Vendor responses and streams never escape this adapter."""

import hashlib
from contextlib import contextmanager
from dataclasses import dataclass
from typing import BinaryIO

from botocore.exceptions import BotoCoreError, ClientError
from nexent.storage.errors import (
    CapabilityUnsupported,
    Conflict,
    InvalidInput,
    NotFound,
    OutcomeUnknown,
    ScopeDenied,
    StorageError,
    Unavailable,
)
from nexent.storage.models import (
    CapabilitySet,
    DeleteReceipt,
    ObjectMetadata,
    ObjectRef,
    Revision,
    StorageScope,
)


@dataclass(frozen=True)
class ObjectBinding:
    space: str
    bucket: str
    prefix: str
    roles: frozenset[str]
    writable: bool = False
    allow_system: bool = False
    exact_keys: frozenset[str] | None = None

    def __post_init__(self):
        object.__setattr__(self, "roles", frozenset(self.roles))
        if self.exact_keys is not None:
            object.__setattr__(self, "exact_keys", frozenset(self.exact_keys))
        if (
            not self.space
            or not self.bucket
            or not self.roles
            or type(self.writable) is not bool
            or type(self.allow_system) is not bool
        ):
            raise InvalidInput()


def _key(value):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 1024
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or any(char in value for char in ("\\", ":", "\x00"))
    ):
        raise InvalidInput()
    return value


def _revision(response):
    version = response.get("VersionId")
    if version and version != "null":
        return Revision("version:" + version)
    etag = response.get("ETag")
    if not etag:
        raise Unavailable()
    return Revision("etag:" + etag)


def _version_args(revision):
    if revision is None:
        return {}
    if revision.value.startswith("version:"):
        return {"VersionId": revision.value.removeprefix("version:")}
    if revision.value.startswith("etag:"):
        return {"IfMatch": revision.value.removeprefix("etag:")}
    raise InvalidInput()


class _ObjectReader:
    """Expose bounded binary reads without exposing a driver Body/connection."""

    def __init__(self, body, context):
        self._body = body
        self._context = context
        self._closed = False

    def read(self, size=-1):
        self._context.remaining()
        try:
            value = self._body.read(size)
        except (BotoCoreError, OSError):
            raise Unavailable(operation_id=self._context.operation_id) from None
        self._context.remaining()
        return value

    def close(self):
        if not self._closed:
            self._closed = True
            self._body.close()


class S3ObjectStore:
    capabilities = CapabilitySet(
        frozenset(
            {"object.stat", "object.read", "object.put", "object.copy", "object.delete"}
        )
    )

    def __init__(self, scope: StorageScope, binding: ObjectBinding, client_factory):
        if (
            scope.service_role not in binding.roles
            or binding.space not in scope.namespaces
            or scope.system
            and not binding.allow_system
        ):
            raise ScopeDenied()
        if not binding.bucket or binding.prefix and not binding.prefix.endswith("/"):
            raise InvalidInput()
        if binding.prefix:
            _key(binding.prefix.rstrip("/"))
        # Unpartitioned legacy objects require an explicit, finite grant.
        if scope.system and binding.exact_keys is None:
            raise ScopeDenied()
        if scope.resource_prefix and binding.exact_keys is not None:
            raise CapabilityUnsupported()
        self._scope = scope
        self._binding = binding
        self._factory = client_factory

    @property
    def scope(self):
        return self._scope

    def _target(self, ref, *, write=False):
        if ref.space != self._binding.space:
            raise ScopeDenied()
        key = _key(ref.key)
        if write and not self._binding.writable:
            raise ScopeDenied()
        if self._binding.exact_keys is not None:
            if key not in self._binding.exact_keys:
                raise ScopeDenied()
            return {"Bucket": self._binding.bucket, "Key": self._binding.prefix + key}
        tenant = _key(self.scope.tenant_id)
        prefix = self.scope.resource_prefix
        if prefix:
            _key(prefix.rstrip("/"))
            prefix = prefix.rstrip("/") + "/"
        return {
            "Bucket": self._binding.bucket,
            "Key": self._binding.prefix + tenant + "/" + prefix + key,
        }

    @contextmanager
    def _client(self, context):
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise CapabilityUnsupported(operation_id=context.operation_id)
        client = self._factory(context.remaining())
        try:
            yield client
        finally:
            client.close()

    def _call(self, client, operation, context, *, write=False, **kwargs):
        context.remaining()
        try:
            response = getattr(client, operation)(**kwargs)
        except (BotoCoreError, ClientError, OSError) as error:
            code = getattr(error, "response", {}).get("Error", {}).get("Code", "")
            if code in {"NoSuchKey", "NoSuchVersion", "404", "NotFound"}:
                raise NotFound(operation_id=context.operation_id) from None
            if code in {"PreconditionFailed", "412", "ConditionalRequestConflict"}:
                raise Conflict(operation_id=context.operation_id) from None
            if code in {"AccessDenied", "403"}:
                raise ScopeDenied(operation_id=context.operation_id) from None
            # Never replay a write after an unclassified transport/provider failure.
            failure = OutcomeUnknown if write else Unavailable
            raise failure(operation_id=context.operation_id) from None
        try:
            context.remaining()
        except StorageError:
            body = response.get("Body")
            if body is not None:
                body.close()
            if write:
                raise OutcomeUnknown(operation_id=context.operation_id) from None
            raise
        return response

    @staticmethod
    def _metadata(ref, response):
        return ObjectMetadata(
            ObjectRef(ref.space, ref.key, _revision(response)),
            response["ContentLength"],
            response.get("ContentType", "application/octet-stream"),
            response.get("ETag"),
            response.get("Metadata", {}).get("sha256"),
        )

    def stat(self, ref, *, context):
        target = self._target(ref)
        with self._client(context) as client:
            response = self._call(
                client, "head_object", context, **target, **_version_args(ref.version)
            )
        return self._metadata(ref, response)

    @contextmanager
    def open_read(self, ref, *, byte_range=None, expected=None, context):
        target = self._target(ref)
        if expected is not None and ref.version is not None and expected != ref.version:
            raise Conflict(operation_id=context.operation_id)
        target.update(_version_args(expected or ref.version))
        if byte_range is not None:
            # ObjectStore uses an exclusive end; HTTP Range uses an inclusive end.
            end = "" if byte_range.end is None else str(byte_range.end - 1)
            target["Range"] = f"bytes={byte_range.start}-{end}"
        with self._client(context) as client:
            response = self._call(client, "get_object", context, **target)
            body = response["Body"]
            reader = _ObjectReader(body, context)
            try:
                yield reader
            finally:
                reader.close()

    def put(self, ref, stream: BinaryIO, *, content_type, size, context):
        target = self._target(ref, write=True)
        if (
            ref.version is not None
            or type(size) is not int
            or size < 0
            or not content_type
        ):
            raise InvalidInput()
        # Read in bounded pieces; never materialize an entire document in RAM.
        import tempfile

        digest = hashlib.sha256()
        with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as staged:
            remaining = size
            while remaining:
                context.remaining()
                chunk = stream.read(min(remaining, 1024 * 1024))
                if not chunk or len(chunk) > remaining:
                    raise InvalidInput()
                digest.update(chunk)
                staged.write(chunk)
                remaining -= len(chunk)
            if stream.read(1):
                raise InvalidInput()
            staged.seek(0)
            with self._client(context) as client:
                response = self._call(
                    client,
                    "put_object",
                    context,
                    write=True,
                    **target,
                    Body=staged,
                    ContentLength=size,
                    ContentType=content_type,
                    Metadata={"sha256": digest.hexdigest()},
                )
        try:
            revision = _revision(response)
        except Unavailable:
            raise OutcomeUnknown(operation_id=context.operation_id) from None
        return ObjectMetadata(
            ObjectRef(ref.space, ref.key, revision),
            size,
            content_type,
            response.get("ETag"),
            digest.hexdigest(),
        )

    def copy(self, source, target, *, context):
        source_target = self._target(source)
        destination = self._target(target, write=True)
        if target.version is not None:
            raise InvalidInput()
        source_metadata = self.stat(source, context=context)
        revision = _version_args(source_metadata.ref.version)
        args = {}
        if "VersionId" in revision:
            source_target["VersionId"] = revision["VersionId"]
        else:
            args["CopySourceIfMatch"] = revision["IfMatch"]
        with self._client(context) as client:
            response = self._call(
                client,
                "copy_object",
                context,
                write=True,
                **destination,
                CopySource=source_target,
                **args,
            )
        result = dict(response.get("CopyObjectResult", {}))
        result["VersionId"] = response.get("VersionId")
        try:
            revision = _revision(result)
        except Unavailable:
            raise OutcomeUnknown(operation_id=context.operation_id) from None
        return ObjectMetadata(
            ObjectRef(target.space, target.key, revision),
            source_metadata.size,
            source_metadata.content_type,
            result.get("ETag"),
            source_metadata.sha256,
        )

    def delete(self, ref, *, expected=None, context):
        target = self._target(ref, write=True)
        if expected is not None and ref.version is not None and expected != ref.version:
            raise Conflict(operation_id=context.operation_id)
        revision = _version_args(expected or ref.version)
        if "IfMatch" in revision:
            # Old MinIO servers do not guarantee atomic conditional deletes by ETag.
            raise CapabilityUnsupported(operation_id=context.operation_id)
        target.update(revision)
        with self._client(context) as client:
            self._call(client, "delete_object", context, write=True, **target)
        return DeleteReceipt(context.operation_id, True)

    def list(self, prefix, page, *, context):
        raise CapabilityUnsupported(operation_id=context.operation_id)

    def close(self):
        pass
