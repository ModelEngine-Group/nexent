# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Public JSON values survive the neutral storage projection without changing ownership."""

import pytest
from contracts.agentos_knowledge import KnowledgeChunk
from contracts.knowledge_chunk_mutation import ChunkCreateData
from contracts.knowledge_chunk_projection import (
    PUBLIC_CHUNK_SOURCE_KEY,
    public_id_matches,
    public_path_matches,
)
from management.services.knowledge_base.chunk_browser import KnowledgeChunkBrowser
from nexent.storage.errors import ScopeDenied
from pydantic import ValidationError


@pytest.mark.parametrize(
    "content", [123, False, ["first", "second"], ["first", None, ["nested"]]]
)
def test_public_source_keeps_raw_content_filename_and_allowed_fields(content):
    source = {
        "id": ["public-a", "public-b"],
        "filename": ["a.txt", "b.txt"],
        "title": {"opaque": "title"},
        "path_or_url": "manual/path",
        "custom": {"keep": ["original", None]},
        "knowledge_id": 999,
    }
    chunk = KnowledgeChunk(
        knowledge_id=1,
        chunk_id="physical",
        content=content,
        location={PUBLIC_CHUNK_SOURCE_KEY: source},
    )
    result = KnowledgeChunkBrowser._chunk(chunk, {})
    assert result == {
        "id": ["public-a", "public-b"],
        "filename": ["a.txt", "b.txt"],
        "title": {"opaque": "title"},
        "path_or_url": "manual/path",
        "content": content,
    }
    assert "content" not in source and source["knowledge_id"] == 999


def test_public_source_distinguishes_absent_field_and_explicit_null():
    chunk = KnowledgeChunk(
        knowledge_id=1,
        chunk_id="physical",
        content="body",
        location={PUBLIC_CHUNK_SOURCE_KEY: {"title": None}},
    )
    assert KnowledgeChunkBrowser._chunk(chunk, {}) == {
        "id": "physical",
        "content": "body",
        "title": None,
    }


def test_public_projection_cannot_bypass_trusted_file_identity():
    chunk = KnowledgeChunk(
        knowledge_id=1,
        chunk_id="physical",
        file_id="a" * 32,
        file_version=1,
        chunk_index=0,
        content="body",
        location={PUBLIC_CHUNK_SOURCE_KEY: {"id": "safe", "knowledge_id": 1}},
    )
    with pytest.raises(ScopeDenied):
        KnowledgeChunkBrowser._chunk(chunk, {})


@pytest.mark.parametrize(
    "stored,requested,matched",
    [
        ("alias", "alias", True),
        (123, "123", True),
        (False, "false", True),
        (["one", "two"], "two", True),
        ([None, ["nested", 42]], "42", True),
        ({"x": "alias"}, "alias", False),
        (None, "null", False),
    ],
)
def test_public_keyword_id_matches_existing_scalar_and_array_semantics(
    stored, requested, matched
):
    assert (
        public_id_matches({PUBLIC_CHUNK_SOURCE_KEY: {"id": stored}}, requested)
        is matched
    )


def test_nontext_storage_body_needs_explicit_model_input():
    with pytest.raises(ValidationError):
        ChunkCreateData(
            content=["stored"], embedding_model={"model_id": 2, "revision": "r1"}
        )
    value = ChunkCreateData(
        content=["stored"],
        embedding_model={"model_id": 2, "revision": "r1"},
        embedding_input="original text",
    )
    assert value.content == ["stored"] and value.embedding_input == "original text"


def test_raw_path_array_matches_without_replacing_the_returned_value():
    location = {PUBLIC_CHUNK_SOURCE_KEY: {"path_or_url": ["source/a", "source/b"]}}
    assert public_path_matches(location, "source/b")
    assert location[PUBLIC_CHUNK_SOURCE_KEY]["path_or_url"] == ["source/a", "source/b"]
    assert not public_path_matches(
        {PUBLIC_CHUNK_SOURCE_KEY: {}, "path_or_url": "canonical"}, "canonical"
    )
