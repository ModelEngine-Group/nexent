# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""ObjectStore bounds, revision propagation and failure contracts."""

import io
from time import monotonic
from unittest.mock import MagicMock

import pytest
from nexent.storage.errors import (
    CapabilityUnsupported,
    Conflict,
    InvalidInput,
    OutcomeUnknown,
    ScopeDenied,
)
from nexent.storage.models import (
    ByteRange,
    ObjectRef,
    OperationContext,
    Revision,
    StorageScope,
)

from infrastructure.object_storage.port import ObjectBinding, S3ObjectStore


@pytest.fixture
def setup():
    client = MagicMock()
    factory = MagicMock(return_value=client)
    scope = StorageScope("management", "tenant-a", "user", frozenset({"cleanse"}))
    binding = ObjectBinding(
        "cleanse", "bucket", "artifacts/", frozenset({"management"}), writable=True
    )
    store = S3ObjectStore(scope, binding, factory)
    return store, client, OperationContext("op-1", monotonic() + 5)


def test_stat_keeps_tenant_prefix_and_opaque_etag(setup):
    store, client, context = setup
    client.head_object.return_value = {"ContentLength": 3, "ETag": "opaque"}
    metadata = store.stat(ObjectRef("cleanse", "source.txt"), context=context)
    client.head_object.assert_called_once_with(
        Bucket="bucket", Key="artifacts/tenant-a/source.txt"
    )
    assert metadata.ref.version == Revision("etag:opaque")
    assert metadata.sha256 is None
    client.close.assert_called_once()


@pytest.mark.parametrize(
    "key", ["../secret", "/secret", "a//b", "a\\b", "http://host", "a/./b"]
)
def test_unsafe_keys_make_no_request(setup, key):
    store, client, context = setup
    with pytest.raises(InvalidInput):
        store.stat(ObjectRef("cleanse", key), context=context)
    client.head_object.assert_not_called()


def test_cross_space_request_makes_no_request(setup):
    store, client, context = setup
    with pytest.raises(ScopeDenied):
        store.stat(ObjectRef("other", "source"), context=context)
    client.head_object.assert_not_called()


def test_system_scope_needs_finite_grant():
    scope = StorageScope(
        "management", None, "preview", frozenset({"cleanse"}), system=True
    )
    binding = ObjectBinding(
        "cleanse", "bucket", "", frozenset({"management"}), allow_system=True
    )
    with pytest.raises(ScopeDenied):
        S3ObjectStore(scope, binding, MagicMock())


def test_exact_grant_does_not_allow_neighbour_key():
    scope = StorageScope(
        "management", None, "preview", frozenset({"cleanse"}), system=True
    )
    binding = ObjectBinding(
        "cleanse",
        "bucket",
        "",
        frozenset({"management"}),
        allow_system=True,
        exact_keys=frozenset({"allowed"}),
    )
    factory = MagicMock()
    store = S3ObjectStore(scope, binding, factory)
    with pytest.raises(ScopeDenied):
        store.stat(
            ObjectRef("cleanse", "other"),
            context=OperationContext("op", monotonic() + 5),
        )
    factory.assert_not_called()


def test_range_version_and_close_on_reader_failure(setup):
    store, client, context = setup
    body = MagicMock()
    body.read.return_value = b"ab"
    client.get_object.return_value = {"Body": body}
    with (
        pytest.raises(RuntimeError),
        store.open_read(
            ObjectRef("cleanse", "source", Revision("etag:opaque")),
            byte_range=ByteRange(2, 4),
            context=context,
        ) as reader,
    ):
        assert reader.read(2) == b"ab"
        assert reader is not body
        raise RuntimeError("consumer failure")
    client.get_object.assert_called_once_with(
        Bucket="bucket",
        Key="artifacts/tenant-a/source",
        IfMatch="opaque",
        Range="bytes=2-3",
    )
    body.close.assert_called_once()
    client.close.assert_called_once()


def test_explicit_reader_close_is_idempotent(setup):
    store, client, context = setup
    body = MagicMock()
    client.get_object.return_value = {"Body": body}
    with store.open_read(ObjectRef("cleanse", "source"), context=context) as reader:
        reader.close()
    body.close.assert_called_once()


def test_put_hash_size_and_revision(setup):
    store, client, context = setup
    client.put_object.return_value = {"ETag": "multipart-opaque", "VersionId": "v1"}
    captured = []

    def write(**args):
        captured.append((args["Body"].read(), args["Metadata"]))
        return {"ETag": "multipart-opaque", "VersionId": "v1"}

    client.put_object.side_effect = write
    result = store.put(
        ObjectRef("cleanse", "out"),
        io.BytesIO(b"abc"),
        content_type="text/plain",
        size=3,
        context=context,
    )
    assert captured[0][0] == b"abc"
    assert captured[0][1]["sha256"] == result.sha256
    assert result.ref.version == Revision("version:v1")
    assert result.size == 3


@pytest.mark.parametrize("value,size", [(b"ab", 3), (b"abcd", 3), (b"", -1)])
def test_wrong_size_never_writes(setup, value, size):
    store, client, context = setup
    with pytest.raises(InvalidInput):
        store.put(
            ObjectRef("cleanse", "out"),
            io.BytesIO(value),
            content_type="text/plain",
            size=size,
            context=context,
        )
    client.put_object.assert_not_called()


def test_write_timeout_is_unknown_and_not_replayed(setup):
    store, client, context = setup
    client.put_object.side_effect = TimeoutError("private endpoint and secret")
    with pytest.raises(OutcomeUnknown) as error:
        store.put(
            ObjectRef("cleanse", "out"),
            io.BytesIO(b"x"),
            content_type="text/plain",
            size=1,
            context=context,
        )
    assert "secret" not in str(error.value)
    client.put_object.assert_called_once()
    client.close.assert_called_once()


def test_etag_conditional_delete_is_not_emulated(setup):
    store, client, context = setup
    with pytest.raises(CapabilityUnsupported):
        store.delete(
            ObjectRef("cleanse", "out"), expected=Revision("etag:x"), context=context
        )
    client.delete_object.assert_not_called()


def test_version_delete_and_copy_fence(setup):
    store, client, context = setup
    assert store.delete(
        ObjectRef("cleanse", "out", Revision("version:v1")), context=context
    ).deleted
    client.delete_object.assert_called_once_with(
        Bucket="bucket", Key="artifacts/tenant-a/out", VersionId="v1"
    )
    client.head_object.return_value = {"ContentLength": 3, "ETag": "source-etag"}
    client.copy_object.return_value = {"CopyObjectResult": {"ETag": "target-etag"}}
    result = store.copy(
        ObjectRef("cleanse", "source"), ObjectRef("cleanse", "target"), context=context
    )
    assert result.ref.version == Revision("etag:target-etag")
    assert client.copy_object.call_args.kwargs["CopySourceIfMatch"] == "source-etag"


def test_conflicting_read_revision_rejected(setup):
    store, client, context = setup
    with (
        pytest.raises(Conflict),
        store.open_read(
            ObjectRef("cleanse", "source", Revision("version:a")),
            expected=Revision("version:b"),
            context=context,
        ),
    ):
        pass
    client.get_object.assert_not_called()


def test_response_arriving_after_cancellation_closes_body(setup):
    from threading import Event

    from nexent.storage.errors import OperationCancelled

    store, client, _ = setup
    cancelled = Event()
    context = OperationContext("cancelled-read", monotonic() + 5, cancelled=cancelled)
    body = MagicMock()

    def response(**kwargs):
        cancelled.set()
        return {"Body": body}

    client.get_object.side_effect = response
    with (
        pytest.raises(OperationCancelled),
        store.open_read(ObjectRef("cleanse", "source"), context=context),
    ):
        pytest.fail("cancelled read reached consumer")
    body.close.assert_called_once()
    client.close.assert_called_once()


def test_acknowledgement_after_cancellation_retains_unknown_write(setup):
    from threading import Event

    store, client, _ = setup
    cancelled = Event()
    context = OperationContext("cancelled-write", monotonic() + 5, cancelled=cancelled)

    def response(**kwargs):
        cancelled.set()
        return {"ETag": "written"}

    client.put_object.side_effect = response
    with pytest.raises(OutcomeUnknown):
        store.put(
            ObjectRef("cleanse", "target"),
            io.BytesIO(b"x"),
            size=1,
            content_type="text/plain",
            context=context,
        )
    client.put_object.assert_called_once()


@pytest.mark.asyncio
async def test_blocking_adapter_rejects_event_loop_io(setup):
    store, client, context = setup
    with pytest.raises(CapabilityUnsupported):
        store.stat(ObjectRef("cleanse", "source"), context=context)
    client.head_object.assert_not_called()


@pytest.mark.parametrize(
    "code,error_name",
    [
        ("NoSuchKey", "NotFound"),
        ("PreconditionFailed", "Conflict"),
        ("AccessDenied", "ScopeDenied"),
        ("InternalError", "Unavailable"),
    ],
)
def test_provider_errors_are_sanitized(setup, code, error_name):
    from botocore.exceptions import ClientError
    from nexent.storage import errors

    store, client, context = setup
    client.head_object.side_effect = ClientError(
        {"Error": {"Code": code, "Message": "private-endpoint-secret"}}, "HeadObject"
    )
    with pytest.raises(getattr(errors, error_name)) as caught:
        store.stat(ObjectRef("cleanse", "source"), context=context)
    assert "secret" not in str(caught.value)
    client.close.assert_called_once()


def test_copy_pins_real_version_and_returns_target_version(setup):
    store, client, context = setup
    client.head_object.return_value = {
        "ContentLength": 3,
        "ETag": "source-etag",
        "VersionId": "v1",
    }
    client.copy_object.return_value = {
        "CopyObjectResult": {"ETag": "target-etag"},
        "VersionId": "v2",
    }
    result = store.copy(
        ObjectRef("cleanse", "source"), ObjectRef("cleanse", "target"), context=context
    )
    assert result.ref.version == Revision("version:v2")
    assert client.copy_object.call_args.kwargs["CopySource"]["VersionId"] == "v1"
    assert "CopySourceIfMatch" not in client.copy_object.call_args.kwargs


def test_read_only_binding_cannot_write():
    scope = StorageScope("runtime", "tenant", "actor", frozenset({"cleanse"}))
    factory = MagicMock()
    store = S3ObjectStore(
        scope, ObjectBinding("cleanse", "bucket", "", frozenset({"runtime"})), factory
    )
    with pytest.raises(ScopeDenied):
        store.put(
            ObjectRef("cleanse", "target"),
            io.BytesIO(b"x"),
            size=1,
            content_type="text/plain",
            context=OperationContext("read-only", monotonic() + 5),
        )
    factory.assert_not_called()


def test_acknowledged_write_without_revision_is_unknown(setup):
    store, client, context = setup
    client.put_object.return_value = {}
    with pytest.raises(OutcomeUnknown):
        store.put(
            ObjectRef("cleanse", "target"),
            io.BytesIO(b"x"),
            size=1,
            content_type="text/plain",
            context=context,
        )
    client.put_object.assert_called_once()
