# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Delete a tenant-scoped snapshot with per-document optimistic concurrency."""

import logging
import sys
from dataclasses import replace
from time import monotonic

from nexent.storage.errors import (
    OutcomeUnknown,
    PartialFailure,
    StorageError,
    Unavailable,
)
from nexent.storage.models import DeleteReceipt, WriteOutcome


def _numbered(items, operation_id, offset):
    return tuple(
        replace(item, operation_id=operation_id + ":" + str(offset + index))
        for index, item in enumerate(items)
    )


def delete_vectors(store, binding, query, *, context):
    receipts = []
    with store._client(context) as client:
        opened = store._call(
            client, "open_point_in_time", context, index=binding.index, keep_alive="1m"
        )
        pit = opened.get("id")
        if not isinstance(pit, str) or not pit:
            raise Unavailable()
        after = None
        try:
            while True:
                options = {
                    "pit": {"id": pit, "keep_alive": "1m"},
                    "query": query,
                    "sort": ["_shard_doc"],
                    "size": 500,
                    "seq_no_primary_term": True,
                    "source": ["_si_tenant", "_si_collection", "_si_key"],
                }
                if after is not None:
                    options["search_after"] = after
                page = store._call(client, "search", context, **options)
                pit = page.get("pit_id", pit)
                if page.get("timed_out") or page.get("_shards", {}).get("failed", 0):
                    raise Unavailable()
                hits = page.get("hits", {}).get("hits", [])
                if not hits:
                    return tuple(receipts)
                if hits[-1].get("sort") == after:
                    raise Unavailable()
                operations = []
                for hit in hits:
                    key, _, _ = store._decode(
                        binding, hit.get("_source", {}), partial=True
                    )
                    if (
                        hit.get("_id") != store._key(binding.collection, key.key)
                        or type(hit.get("_seq_no")) is not int
                        or type(hit.get("_primary_term")) is not int
                        or not isinstance(hit.get("sort"), list)
                    ):
                        raise Unavailable()
                    operations.append(
                        {
                            "delete": {
                                "_index": binding.index,
                                "_id": hit["_id"],
                                "if_seq_no": hit["_seq_no"],
                                "if_primary_term": hit["_primary_term"],
                            }
                        }
                    )
                try:
                    current = store._bulk(
                        client, operations, context, len(hits), delete=True
                    )
                except PartialFailure as error:
                    raise PartialFailure(
                        results=tuple(receipts)
                        + _numbered(error.results, context.operation_id, len(receipts)),
                        operation_id=context.operation_id,
                    ) from None
                except OutcomeUnknown:
                    unknown = tuple(
                        DeleteReceipt(
                            context.operation_id + ":unknown:" + str(i),
                            False,
                            WriteOutcome.UNKNOWN,
                        )
                        for i in range(len(hits))
                    )
                    raise PartialFailure(
                        results=tuple(receipts)
                        + _numbered(unknown, context.operation_id, len(receipts)),
                        operation_id=context.operation_id,
                    ) from None
                receipts.extend(_numbered(current, context.operation_id, len(receipts)))
                after = hits[-1]["sort"]
        except PartialFailure:
            raise
        except StorageError:
            if receipts:
                raise PartialFailure(
                    results=tuple(receipts), operation_id=context.operation_id
                ) from None
            raise
        finally:
            # Closing the snapshot has a separate bounded cleanup budget, never a data retry.
            failed = sys.exc_info()[0] is not None
            cleanup = replace(context, deadline=monotonic() + 5, cancelled=None)
            try:
                store._call(client, "close_point_in_time", cleanup, id=pit)
            except StorageError:
                if not failed:
                    raise
                logging.getLogger(__name__).warning("vector_snapshot_close_failed")
