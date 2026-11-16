# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Object listing bounds, scope-bound cursors and safe provider responses."""

from dataclasses import replace
from threading import Event
from time import monotonic
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from nexent.storage.errors import (
    CapabilityUnsupported,
    InvalidInput,
    OperationCancelled,
    Unavailable,
)
from nexent.storage.models import OperationContext, PageRequest, Revision, StorageScope

from infrastructure.object_storage.port import ObjectBinding, S3ObjectStore


@pytest.fixture
def setup():
    client = MagicMock()
    factory = MagicMock(return_value=client)
    scope = StorageScope(
        "management", "tenant-a", "actor", {"files"}, resource_prefix="run/one"
    )
    binding = ObjectBinding("files", "bucket", "managed/", {"management"})
    return S3ObjectStore(scope, binding, factory), client, factory


def context():
    return OperationContext("list-test", monotonic() + 5)


def response(*keys, token=None):
    return {
        "Contents": [
            {"Key": "managed/tenant-a/run/one/" + key, "Size": 3, "ETag": '"opaque"'}
            for key in keys
        ],
        "IsTruncated": token is not None,
        **({"NextContinuationToken": token} if token else {}),
    }


def test_scoped_bounded_list_returns_neutral_metadata(setup):
    store, client, _ = setup
    client.list_objects_v2.return_value = response("artifacts/a", token="provider-page")
    first = store.list("artifacts/", PageRequest(limit=1), context=context())
    client.list_objects_v2.assert_called_once_with(
        Bucket="bucket", Prefix="managed/tenant-a/run/one/artifacts/", MaxKeys=1
    )
    item = first.items[0]
    assert item.ref.space == "files" and item.ref.key == "artifacts/a"
    assert item.ref.version == Revision('etag:"opaque"')
    assert item.size == 3 and item.sha256 is None
    assert first.next_cursor and first.next_cursor != "provider-page"
    client.list_objects_v2.return_value = response("artifacts/b")
    last = store.list(
        "artifacts/", PageRequest(limit=1, cursor=first.next_cursor), context=context()
    )
    assert [item.ref.key for item in last.items] == ["artifacts/b"]
    assert last.next_cursor is None
    assert (
        client.list_objects_v2.call_args.kwargs["ContinuationToken"] == "provider-page"
    )
    assert client.close.call_count == 2
    client.head_object.assert_not_called()


@pytest.mark.parametrize("prefix", ["", "artifacts", "artifacts/"])
def test_empty_or_partial_logical_prefix_is_supported(setup, prefix):
    store, client, _ = setup
    client.list_objects_v2.return_value = {"IsTruncated": False}
    assert store.list(prefix, PageRequest(), context=context()).items == ()
    assert (
        client.list_objects_v2.call_args.kwargs["Prefix"]
        == "managed/tenant-a/run/one/" + prefix
    )


@pytest.mark.parametrize(
    "prefix", ["/", "../x", "a//b", "a/../b/", "a\\b", "http://host", "x" * 1025, None]
)
def test_invalid_prefix_never_creates_client(setup, prefix):
    store, _, factory = setup
    with pytest.raises(InvalidInput):
        store.list(prefix, PageRequest(), context=context())
    factory.assert_not_called()


@pytest.mark.parametrize(
    "change", ["tenant", "actor", "resource", "binding", "prefix", "size"]
)
def test_cursor_is_bound_to_query_and_scope(setup, change):
    store, client, factory = setup
    client.list_objects_v2.return_value = response("a", token="next")
    cursor = store.list("", PageRequest(limit=1), context=context()).next_cursor
    factory.reset_mock()
    scope, binding = store.scope, store._binding
    if change in {"tenant", "actor", "resource"}:
        field = {
            "tenant": "tenant_id",
            "actor": "actor_id",
            "resource": "resource_prefix",
        }[change]
        scope = replace(scope, **{field: "other"})
    if change == "binding":
        binding = replace(binding, bucket="other-bucket")
    target = S3ObjectStore(scope, binding, factory)
    with pytest.raises(InvalidInput):
        target.list(
            "other" if change == "prefix" else "",
            PageRequest(limit=2 if change == "size" else 1, cursor=cursor),
            context=context(),
        )
    factory.assert_not_called()


@pytest.mark.parametrize(
    "cursor", ["garbage", "W10=", "bnVsbA==", "e30=", 123, "a" * 20000]
)
def test_malformed_cursor_never_creates_client(setup, cursor):
    store, _, factory = setup
    with pytest.raises(InvalidInput):
        store.list("", PageRequest(cursor=cursor), context=context())
    factory.assert_not_called()


def test_exact_grant_cannot_enumerate(setup):
    store, _, factory = setup
    grant = S3ObjectStore(
        replace(store.scope, resource_prefix=""),
        replace(store._binding, exact_keys={"allowed"}),
        factory,
    )
    assert "object.list" not in grant.capabilities.supported
    assert "object.list" in store.capabilities.supported
    with pytest.raises(CapabilityUnsupported):
        grant.list("", PageRequest(), context=context())
    factory.assert_not_called()


@pytest.mark.parametrize(
    "data",
    [
        {"IsTruncated": True},
        {"IsTruncated": "true"},
        {"Contents": [{"Key": "managed/tenant-b/secret", "Size": 3, "ETag": "x"}]},
        {
            "Contents": [
                {"Key": "managed/tenant-a/run/one/../secret", "Size": 3, "ETag": "x"}
            ]
        },
        {"Contents": [{"Key": "managed/tenant-a/run/one/a", "Size": -1, "ETag": "x"}]},
        {
            "Contents": [
                {"Key": "managed/tenant-a/run/one/a", "Size": True, "ETag": "x"}
            ]
        },
        {"Contents": [{"Key": "managed/tenant-a/run/one/a", "Size": 3}]},
        {
            "Contents": [{"Key": "managed/tenant-a/run/one/a", "Size": 3, "ETag": "x"}]
            * 2
        },
    ],
)
def test_invalid_provider_response_is_sanitized_and_closed(setup, data):
    store, client, _ = setup
    client.list_objects_v2.return_value = data
    with pytest.raises(Unavailable) as error:
        store.list("", PageRequest(limit=1), context=context())
    assert "secret" not in str(error.value)
    client.close.assert_called_once()


def test_directory_markers_are_not_logical_files(setup):
    store, client, _ = setup
    client.list_objects_v2.return_value = response("folder/", token="next")
    result = store.list("", PageRequest(limit=1), context=context())
    assert result.items == () and result.next_cursor


def test_provider_timeout_is_not_retried(setup):
    store, client, _ = setup
    client.list_objects_v2.side_effect = ClientError(
        {"Error": {"Code": "InternalError", "Message": "private-secret"}},
        "ListObjectsV2",
    )
    with pytest.raises(Unavailable) as error:
        store.list("", PageRequest(), context=context())
    assert "secret" not in str(error.value)
    client.list_objects_v2.assert_called_once()
    client.close.assert_called_once()


def test_cancelled_response_is_not_returned(setup):
    store, client, _ = setup
    cancelled = Event()

    def answer(**kwargs):
        cancelled.set()
        return response("a")

    client.list_objects_v2.side_effect = answer
    with pytest.raises(OperationCancelled):
        store.list(
            "",
            PageRequest(),
            context=OperationContext("cancel", monotonic() + 5, cancelled),
        )
    client.close.assert_called_once()


def test_expired_request_does_not_create_client(setup):
    from nexent.storage.errors import DeadlineExceeded

    store, _, factory = setup
    with pytest.raises(DeadlineExceeded):
        store.list(
            "", PageRequest(), context=OperationContext("expired", monotonic() - 1)
        )
    factory.assert_not_called()


def test_nonadvancing_provider_cursor_is_rejected(setup):
    store, client, _ = setup
    client.list_objects_v2.return_value = response("a", token="same")
    first = store.list("", PageRequest(limit=1), context=context())
    with pytest.raises(Unavailable):
        store.list(
            "", PageRequest(limit=1, cursor=first.next_cursor), context=context()
        )
    assert client.list_objects_v2.call_count == 2
    assert client.close.call_count == 2


def test_prefix_neighbours_are_refused_even_within_same_resource(setup):
    store, client, _ = setup
    client.list_objects_v2.return_value = response("other/a")
    with pytest.raises(Unavailable):
        store.list("artifacts/", PageRequest(), context=context())
    client.close.assert_called_once()
