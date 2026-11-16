# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bounded immutable reads verify storage metadata and bytes without leaking streams."""

import hashlib
from contextlib import contextmanager
from io import BytesIO
from time import monotonic
from unittest.mock import Mock

import pytest
from nexent.storage.errors import DeadlineExceeded, InvalidInput
from nexent.storage.models import ObjectMetadata, ObjectRef, OperationContext, Revision
from nexent.storage.objects import read_verified_object


@pytest.mark.parametrize(
    "failure", [None, "revision", "digest", "short", "long", "limit", "deadline"]
)
def test_verified_read_closes_and_rejects_inconsistent_objects(failure):
    ref = ObjectRef("files", "artifact.json", Revision("etag:1"))
    content = b"content"
    digest = hashlib.sha256(content).hexdigest()
    metadata = ObjectMetadata(ref, len(content), "text/plain", sha256=digest)
    if failure == "revision":
        metadata = ObjectMetadata(
            ObjectRef("files", ref.key, Revision("etag:2")), len(content), "text/plain"
        )
    elif failure == "digest":
        content = b"changed"
    elif failure == "short":
        content = b"short"
    elif failure == "long":
        content += b"extra"
    reader = BytesIO(content)
    context = OperationContext("verified-read", monotonic() + 5)
    if failure == "deadline":
        context = Mock()
        context.remaining.side_effect = [5, DeadlineExceeded()]

    @contextmanager
    def open_read(*args, **kwargs):
        try:
            yield reader
        finally:
            reader.close()

    store = Mock(
        stat=Mock(return_value=metadata), open_read=Mock(side_effect=open_read)
    )
    if failure:
        with pytest.raises(DeadlineExceeded if failure == "deadline" else InvalidInput):
            read_verified_object(
                store,
                ref,
                sha256=digest,
                limit=3 if failure == "limit" else 10,
                context=context,
            )
    else:
        assert (
            read_verified_object(store, ref, sha256=digest, limit=10, context=context)
            == content
        )
    if store.open_read.called:
        assert reader.closed
    else:
        reader.close()
    assert store.stat.call_count == 1


@pytest.mark.parametrize(
    "limit,digest,version",
    [
        (True, "a" * 64, Revision("etag:1")),
        (10, "bad", Revision("etag:1")),
        (10, "a" * 64, None),
    ],
)
def test_invalid_read_arguments_do_not_reach_storage(limit, digest, version):
    store = Mock()
    with pytest.raises(InvalidInput):
        read_verified_object(
            store,
            ObjectRef("files", "file", version),
            sha256=digest,
            limit=limit,
            context=OperationContext("test", monotonic() + 5),
        )
    assert not store.mock_calls
