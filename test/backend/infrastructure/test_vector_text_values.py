# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Searchable text retains legacy JSON scalar/array values while identity stays strict."""

import pytest
from nexent.storage.errors import InvalidInput
from nexent.storage.models import VectorKey, VectorRecord

from test.backend.infrastructure.test_vector_store import context
from test.backend.infrastructure.test_vector_store import (
    store as store,  # noqa: PLC0414
)


@pytest.mark.parametrize(
    "content", [12, False, 3.5, ["first", "second"], ["first", None, ["nested", 12]]]
)
def test_search_text_preserves_original_json_values(store, content):
    port, client, _ = store
    client.bulk.return_value = {"items": [{"index": {"status": 201}}]}
    port.upsert(
        (
            VectorRecord(
                VectorKey("kb", "one"),
                (1.0, 0.0),
                {"content": content, "file_id": "file"},
            ),
        ),
        context=context(),
    )
    assert (
        client.bulk.call_args.kwargs["operations"][1]["payload"]["content"] == content
    )


@pytest.mark.parametrize(
    "content",
    [
        {"object": "invalid"},
        ["ok", {"nested": "invalid"}],
        float("inf"),
        [float("nan")],
        None,
    ],
)
def test_search_text_rejects_objects_nonfinite_values_and_missing_required_body(
    store, content
):
    port, _, factory = store
    with pytest.raises(InvalidInput):
        port.upsert(
            (
                VectorRecord(
                    VectorKey("kb", "one"),
                    (1.0, 0.0),
                    {"content": content, "file_id": "file"},
                ),
            ),
            context=context(),
        )
    factory.assert_not_called()


def test_non_search_identity_fields_are_not_coerced_to_strings(store):
    port, _, factory = store
    with pytest.raises(InvalidInput):
        port.upsert(
            (
                VectorRecord(
                    VectorKey("kb", "one"),
                    (1.0, 0.0),
                    {"content": "text", "file_id": ["file"]},
                ),
            ),
            context=context(),
        )
    factory.assert_not_called()
