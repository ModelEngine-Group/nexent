# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Optional vector scans distinguish absence from malformed stored embeddings."""

from dataclasses import replace

import pytest
from nexent.storage.errors import CapabilityUnsupported, InvalidInput, Unavailable
from nexent.storage.models import PageRequest

from infrastructure.vdb.vector_store import ElasticsearchVectorStore
from test.backend.infrastructure.test_vector_scan import context, hit
from test.backend.infrastructure.test_vector_scan import (
    store as store,  # noqa: PLC0414
)


@pytest.mark.parametrize(
    "stored", ["missing", None, [], [0.0, 0.0], [1.0], [True, 1.0]]
)
def test_only_absent_vector_is_optional_and_default_scan_stays_strict(store, stored):
    original, client, factory = store
    port = ElasticsearchVectorStore(
        original.scope,
        (replace(original._bindings["kb"], allow_unembedded=True),),
        factory,
    )
    row = hit("a")
    if stored == "missing":
        del row["_source"]["embedding"]
    else:
        row["_source"]["embedding"] = stored
    client.search.return_value = {"hits": {"hits": [row]}}
    if stored == "missing":
        assert (
            port.scan(
                "kb", None, PageRequest(), context=context(), allow_missing_vector=True
            )
            .items[0]
            .vector
            == ()
        )
    else:
        with pytest.raises(Unavailable):
            port.scan(
                "kb", None, PageRequest(), context=context(), allow_missing_vector=True
            )
    with pytest.raises(Unavailable):
        port.scan("kb", None, PageRequest(), context=context())


def test_optional_mode_requires_binding_and_cannot_reuse_strict_cursor(store):
    original, client, factory = store
    with pytest.raises(CapabilityUnsupported):
        original.scan(
            "kb", None, PageRequest(), context=context(), allow_missing_vector=True
        )
    factory.assert_not_called()
    client.search.return_value = {"hits": {"hits": [hit("a"), hit("b")]}}
    strict = original.scan("kb", None, PageRequest(limit=1), context=context())
    optional = ElasticsearchVectorStore(
        original.scope,
        (replace(original._bindings["kb"], allow_unembedded=True),),
        factory,
    )
    factory.reset_mock()
    with pytest.raises(InvalidInput):
        optional.scan(
            "kb",
            None,
            PageRequest(limit=1, cursor=strict.next_cursor),
            context=context(),
            allow_missing_vector=True,
        )
    with pytest.raises(InvalidInput):
        optional.scan(
            "kb",
            None,
            PageRequest(),
            context=context(),
            include_vector=False,
            allow_missing_vector=True,
        )
    factory.assert_not_called()
