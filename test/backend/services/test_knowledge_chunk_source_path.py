# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-PUBLIC-CREATE-04 filters explicit file source paths before pagination."""

from dataclasses import replace

import pytest
from contracts.agentos_knowledge import KnowledgeChunks
from contracts.knowledge_chunk_projection import PUBLIC_CHUNK_SOURCE_KEY
from runtime.knowledge_base.chunks import _window

from test.backend.services.test_knowledge_chunk_view import context
from test.backend.services.test_knowledge_chunk_view import (
    lifecycle as lifecycle,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_chunk_view import (
    view as view,  # noqa: PLC0414
)


@pytest.mark.parametrize("path,selected,offset,keys,total", [
    ("manual/path", False, 0, ["base0"], 1),
    ("original/path", True, 0, ["base1"], 2),
    ("original/path", True, 1, ["base2"], 2),
    ("other/path", False, 0, [], 0),
])
def test_file_path_override_matches_raw_source_and_keeps_original_fallback(view, path, selected, offset, keys, total):
    s = view
    s.rows[0] = replace(s.rows[0], payload={**s.rows[0].payload,
        "location": {PUBLIC_CHUNK_SOURCE_KEY: {"path_or_url": ["manual/path", "another"]}}})
    request = KnowledgeChunks(knowledge_id=1, expected_revision="a" * 64, standalone_path=path,
        file_ids=[s.handle["file_id"]] if selected else [], offset=offset, limit=1)
    found, chunks = _window(s.s.record, s.vectors, request, s.resource, context=context())
    assert found == total and [chunk.chunk_id for chunk in chunks] == keys


def test_explicit_source_without_path_does_not_inherit_file_default(view):
    s = view
    s.rows[0] = replace(s.rows[0], payload={**s.rows[0].payload, "location": {PUBLIC_CHUNK_SOURCE_KEY: {}}})
    request = KnowledgeChunks(knowledge_id=1, expected_revision="a" * 64, standalone_path="original/path",
                              file_ids=[s.handle["file_id"]])
    total, chunks = _window(s.s.record, s.vectors, request, s.resource, context=context())
    assert total == 2 and [chunk.chunk_id for chunk in chunks] == ["base1", "base2"]
