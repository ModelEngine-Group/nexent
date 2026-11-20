# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime text chunking retains specialized formats and rejects an unpinned JSON source."""

import hashlib

import pytest
from contracts.agentos_knowledge import CleanseArtifact, CleanseBlock, ObjectReference
from runtime.knowledge_base.chunking import chunk_text


def artifact(contents, *, source=b"source", locations=None):
    return CleanseArtifact(
        source=ObjectReference(
            space="files",
            key="source",
            version="v1",
            sha256=hashlib.sha256(source).hexdigest(),
        ),
        parser_version="v2",
        blocks=[
            CleanseBlock(
                ordinal=index,
                kind="text",
                content=text,
                sha256=hashlib.sha256(text.encode()).hexdigest(),
                location=(locations or [{}] * len(contents))[index],
            )
            for index, text in enumerate(contents)
        ],
    )


def chunk(value, filename="source.txt", strategy="none", **kwargs):
    return chunk_text(
        value,
        filename=filename,
        strategy=strategy,
        max_characters=20,
        new_after_n_chars=10,
        **kwargs,
    )


def test_none_keeps_legacy_join_and_first_language():
    value = artifact(["one", "two"], locations=[{"languages": ["eng"]}, {}])
    assert chunk(value) == [
        {"content": "one\n\ntwo", "filename": "source.txt", "language": "eng"}
    ]


@pytest.mark.parametrize("strategy", ["none", "basic", "by_title"])
def test_workbook_keeps_rendered_block_boundaries(strategy):
    value = artifact(
        ["sheet-one", "sheet-two"],
        locations=[
            {"chunk_index": 0, "file_type": "xlsx", "filename": "book.xlsx"},
            {"chunk_index": 1, "file_type": "xlsx", "filename": "book.xlsx"},
        ],
    )
    result = chunk(value, "book.xlsx", strategy)
    assert [row["content"] for row in result] == ["sheet-one", "sheet-two"]
    assert result[0]["metadata"] == {"chunk_index": 0, "file_type": "xlsx"}


@pytest.mark.parametrize("strategy", ["basic", "by_title", "none"])
def test_json_uses_original_bytes_with_existing_algorithm(strategy):
    source = b'{"hello":"world", "other": 42}'
    value = artifact(
        [""],
        source=source,
        locations=[{"element_type": "JSONSource", "source_format": "json"}],
    )
    expected = ['hello: "world"', 'other: 42']
    result = chunk(value, "source.json", strategy, json_source=source)
    assert [row["content"] for row in result] == (
        ["\n\n".join(expected)] if strategy == "none" else expected
    )
    with pytest.raises(ValueError, match="pinned source"):
        chunk(value, "source.json", strategy, json_source=b"changed")


def test_basic_restores_source_structure_for_chunker():
    value = artifact(["heading", "body"], locations=[
        {"element_type": "Title", "page_number": 4},
        {"element_type": "NarrativeText", "page_number": 4},
    ])
    result = chunk(value, "source.pdf", "basic")
    assert result[0]["content"] == "heading\n\nbody"
    assert result[0]["metadata"] == {"chunk_index": 0, "element_type": "CompositeElement", "page_number": 4}
