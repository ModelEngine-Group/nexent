# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Structural extraction preserves elements without changing the old none API."""

from types import SimpleNamespace
from unittest.mock import Mock

from nexent.data_process.core import DataProcessCore
from nexent.data_process.unstructured_processor import UnstructuredProcessor


def test_structure_retains_title_table_order_and_locations(mocker):
    processor = UnstructuredProcessor()
    title = SimpleNamespace(
        category="Title",
        text="heading",
        metadata=SimpleNamespace(to_dict=lambda: {"page_number": 1}),
    )
    table = SimpleNamespace(
        category="Table",
        text="a b",
        metadata=SimpleNamespace(
            to_dict=lambda: {"page_number": 2, "text_as_html": "<table/>"}
        ),
    )
    partition = mocker.patch.object(
        processor, "_partition", return_value=[title, table]
    )
    rows = processor.process_structure(b"source", "source.docx")
    assert [row["metadata"]["element_type"] for row in rows] == ["Title", "Table"]
    assert [row["content"] for row in rows] == ["heading", "a b"]
    assert rows[1]["metadata"]["page_number"] == 2
    assert rows[1]["metadata"]["text_as_html"] == "<table/>"
    assert partition.call_args.args[1] == "none"


def test_json_structure_is_a_pinned_source_descriptor_not_final_chunks(mocker):
    processor = UnstructuredProcessor()
    partition = mocker.patch.object(processor, "_partition")
    rows = processor.process_structure(b'{"long":"value"}', "source.json")
    assert rows == [
        {
            "content": "",
            "filename": "source.json",
            "metadata": {"element_type": "JSONSource", "source_format": "json"},
        }
    ]
    partition.assert_not_called()


def test_old_none_still_merges_text_without_structural_metadata():
    processor = UnstructuredProcessor()
    result = processor._process_elements(
        [SimpleNamespace(text="one"), SimpleNamespace(text="two")], "none", "source.txt"
    )
    assert result == [{"content": "one\n\ntwo", "filename": "source.txt"}]


def test_core_dispatches_structure_without_using_final_chunking(mocker):
    core = DataProcessCore()
    selected = Mock()
    selected.process_structure.return_value = [{"content": "one"}]
    mocker.patch.object(core, "_get_processor", return_value=selected)
    mocker.patch.object(
        core, "_select_processor_by_filename", return_value=("Unstructured", None)
    )
    assert core.file_structure(b"source", "source.txt") == ([{"content": "one"}], [])
    selected.process_structure.assert_called_once_with(b"source", filename="source.txt")
    selected.process_file.assert_not_called()
