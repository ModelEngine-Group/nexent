# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""DPR-001/007: preserve text and conversion behavior at the new boundary."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from infrastructure.file_processing.conversion import convert_office_to_pdf
from management.services.file.cleanse import extract_uploaded_text


def test_cleansing_uses_structure_only_and_checks_source(mocker):
    import hashlib

    from contracts.agentos_knowledge import ObjectReference
    from management.services.file.cleanse import prepare_artifact

    source = ObjectReference(
        space="knowledge",
        key="file.txt",
        version="1",
        sha256=hashlib.sha256(b"source").hexdigest(),
    )
    parser = SimpleNamespace(
        file_process=Mock(
            return_value=([{"content": "one", "metadata": {"page_number": 1}}], [])
        )
    )
    value = prepare_artifact(
        b"source", "file.txt", source, "parser-1", parser=parser
    )
    assert value.blocks[0].content == "one"
    assert value.blocks[0].location == {"page_number": 1}
    assert parser.file_process.call_args.kwargs["chunking_strategy"] == "none"
    parser.file_process.reset_mock()
    with pytest.raises(ValueError, match="checksum"):
        prepare_artifact(b"changed", "file.txt", source, "parser-1", parser=parser)
    parser.file_process.assert_not_called()


def test_text_response_preserves_empty_chunks_and_output_shape(mocker):
    parser = SimpleNamespace(
        file_process=Mock(
            return_value=(
                [
                    {"content": "one"},
                    {"metadata": {}},
                    {"content": "two"},
                    {"content": ""},
                ],
                [],
            )
        )
    )
    result = extract_uploaded_text(
        b"source", "document.txt", "basic", parser=parser, clock=lambda: 10.0
    )
    assert result == dict(
        success=True,
        task_id=None,
        filename="document.txt",
        text="one\ntwo",
        chunks=["one", "two", ""],
        chunks_count=4,
        text_length=7,
        processing_time=0.0,
        chunking_strategy="basic",
    )
    parser.file_process.assert_called_once_with(
        file_data=b"source", filename="document.txt", chunking_strategy="basic"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "timeout", "failed", "missing_pdf"])
async def test_conversion_keeps_failure_semantics(tmp_path, mocker, outcome):
    import subprocess

    from infrastructure.file_processing import conversion

    source = tmp_path / "input.docx"
    source.write_bytes(b"fixture")
    if outcome == "success":
        (tmp_path / "input.pdf").write_bytes(b"%PDF")
    process = mocker.patch.object(
        conversion,
        "run_conversion_process",
        return_value=SimpleNamespace(
            returncode=1 if outcome == "failed" else 0, stdout="", stderr="failure"
        ),
    )
    if outcome == "timeout":
        process.side_effect = subprocess.TimeoutExpired("soffice", 1)

    async def blocking(_name, function, *args, **kwargs):
        kwargs.pop("lane", None)
        kwargs.pop("owner", None)
        return function(*args, **kwargs)

    mocker.patch.object(conversion, "run_blocking", side_effect=blocking)
    if outcome == "success":
        assert await convert_office_to_pdf(
            str(source), str(tmp_path), profile_dir=str(tmp_path / "profile")
        ) == str(tmp_path / "input.pdf")
    else:
        with pytest.raises(TimeoutError if outcome == "timeout" else RuntimeError):
            await convert_office_to_pdf(
                str(source), str(tmp_path), profile_dir=str(tmp_path / "profile")
            )
