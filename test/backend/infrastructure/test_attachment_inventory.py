# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""The legacy inventory is bounded and exposes only provider-neutral metadata."""

from datetime import UTC, datetime
from time import monotonic
from unittest.mock import Mock

import pytest
from botocore.exceptions import ReadTimeoutError
from nexent.storage.errors import InvalidInput, Unavailable
from nexent.storage.models import ObjectInventoryEntry, OperationContext

from infrastructure.attachment_inventory import AttachmentInventory


def test_inventory_reads_one_page_and_keeps_opaque_keys_and_timestamps():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    raw = Mock()
    keys = ["attachments/user:legacy/", r"attachments/user:legacy/a\b.pdf"]
    raw.list_objects_v2.return_value = {
        "Contents": [{"Key": key, "Size": i, "LastModified": now} for i, key in enumerate(keys)],
        "IsTruncated": True, "NextContinuationToken": "unused",
    }
    ctx = OperationContext("first-page", monotonic() + 5)
    inventory = AttachmentInventory("owned", Mock(return_value=raw))

    assert inventory.first_page("attachments/user:legacy/", limit=2, context=ctx) == (
        ObjectInventoryEntry(keys[0], 0, now), ObjectInventoryEntry(keys[1], 1, now),
    )
    raw.list_objects_v2.assert_called_once_with(Bucket="owned", Prefix="attachments/user:legacy/", MaxKeys=2)
    raw.close.assert_called_once()


def test_inventory_failure_closes_client_without_retry():
    raw = Mock()
    raw.list_objects_v2.side_effect = ReadTimeoutError(endpoint_url="https://private.invalid")
    ctx = OperationContext("deadline", monotonic() + 5)
    inventory = AttachmentInventory("owned", Mock(return_value=raw))
    with pytest.raises(Unavailable) as err:
        inventory.first_page("prefix", limit=1000, context=ctx)
    assert err.value.operation_id == "deadline"
    assert "private" not in str(err.value)
    raw.list_objects_v2.assert_called_once()
    raw.close.assert_called_once()


def test_inventory_rejects_unbounded_limit_before_opening_client():
    factory = Mock()
    inventory = AttachmentInventory("owned", factory)
    ctx = OperationContext("limit", monotonic() + 5)
    with pytest.raises(InvalidInput):
        inventory.first_page("", limit=1001, context=ctx)
    factory.assert_not_called()
