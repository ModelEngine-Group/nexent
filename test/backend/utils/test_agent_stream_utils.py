"""Unit tests for agent stream skill-file helpers."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from backend.utils import agent_stream_utils


class TestJsonExtraction:
    def test_extracts_nested_objects_and_skips_invalid_fragments(self):
        text = 'prefix {"outer":{"value":1}} broken {not-json} [1,2] {"ok":true}'

        assert agent_stream_utils.extract_json_objects_from_text(text) == [
            {"outer": {"value": 1}},
            {"ok": True},
        ]

    def test_extract_skill_payloads_requires_absolute_path(self):
        content = '{"file_name":"ignored"} {"absolute_path":"/tmp/a.txt"}'

        assert agent_stream_utils.extract_skill_file_upload_payloads(content) == [
            {"absolute_path": "/tmp/a.txt"}
        ]


class TestSerialization:
    def test_non_tool_content_is_unchanged(self):
        assert agent_stream_utils.serialize_stream_unit_content(
            {"type": "text", "role": "assistant"}, "hello"
        ) == "hello"

    def test_tool_content_preserves_supported_metadata(self):
        result = agent_stream_utils.serialize_stream_unit_content(
            {
                "type": "tool-call",
                "tool_name": "search",
                "tool_arguments": {"query": "nexent"},
                "role": "tool",
                "ignored": "value",
            },
            "result",
        )

        assert json.loads(result) == {
            "content": "result",
            "tool_name": "search",
            "tool_arguments": {"query": "nexent"},
            "role": "tool",
        }

    def test_transforms_fallback_fields(self):
        assert agent_stream_utils.transform_skill_files_to_standard_format(
            [{"name": "a.txt", "size": 3, "preview_url": "/preview"}]
        ) == [
            {
                "object_name": "",
                "name": "a.txt",
                "type": "file",
                "size": 3,
                "url": "",
                "presigned_url": "/preview",
                "description": "",
            }
        ]


@pytest.mark.asyncio
async def test_process_uploads_skips_unsafe_missing_and_failed_files(tmp_path):
    safe_file = tmp_path / "safe.txt"
    safe_file.write_text("safe", encoding="utf-8")
    missing_file = tmp_path / "missing.txt"

    payloads = [
        {"absolute_path": str(tmp_path / "unsafe.txt"), "file_name": "unsafe.txt"},
        {"absolute_path": str(missing_file), "file_name": "missing.txt"},
        {"absolute_path": str(safe_file), "file_name": "safe.txt"},
    ]
    upload = MagicMock(return_value={"success": False, "error": "storage unavailable"})

    with patch.object(agent_stream_utils, "is_allowed_skill_upload_path", side_effect=[False, True, True]), \
            patch.object(agent_stream_utils, "upload_fileobj", upload):
        result = await agent_stream_utils.process_skill_file_uploads(
            payloads, user_id="user-1", tenant_id="tenant-1"
        )

    assert result == []
    upload.assert_called_once()


@pytest.mark.asyncio
async def test_process_uploads_success_and_string_payload(tmp_path):
    file_path = tmp_path / "result.txt"
    file_path.write_text("result", encoding="utf-8")
    payload = json.dumps({
        "absolute_path": str(file_path),
        "file_path": "result.txt",
        "content_type": "text/plain",
    })
    upload_result = {
        "success": True,
        "object_name": "skill-files/user-1/result.txt",
        "url": "/result.txt",
        "presigned_url": "/signed-result.txt",
        "file_size": 6,
    }

    with patch.object(agent_stream_utils, "is_allowed_skill_upload_path", return_value=True), \
            patch.object(agent_stream_utils, "upload_fileobj", return_value=upload_result) as upload:
        result = await agent_stream_utils.process_skill_file_uploads(
            payload, user_id="user-1", tenant_id="tenant-1"
        )

    assert result == [{
        "status": "success",
        "file_name": "result.txt",
        "absolute_path": str(file_path),
        "object_name": "skill-files/user-1/result.txt",
        "preview_url": "/signed-result.txt",
        "url": "/result.txt",
        "presigned_url": "/signed-result.txt",
        "mime_type": "text/plain",
        "file_size": 6,
    }]
    assert upload.call_args.kwargs["prefix"] == "skill-files/user-1"


def test_process_uploads_handles_storage_exception(tmp_path):
    file_path = tmp_path / "error.txt"
    file_path.write_text("error", encoding="utf-8")

    async def run_test():
        with patch.object(agent_stream_utils, "is_allowed_skill_upload_path", return_value=True), \
                patch.object(agent_stream_utils, "upload_fileobj", side_effect=RuntimeError("storage")):
            return await agent_stream_utils.process_skill_file_uploads(
                [{"absolute_path": str(file_path)}], user_id="", tenant_id="tenant-1"
            )

    import asyncio
    assert asyncio.run(run_test()) == []


def test_safe_agent_stream_error_chunk_is_sanitized():
    chunk = agent_stream_utils.safe_agent_stream_error_chunk()
    assert chunk.startswith("data: ")
    assert chunk.endswith("\n\n")
    assert json.loads(chunk[6:].strip()) == {
        "type": "error",
        "content": agent_stream_utils.SAFE_AGENT_STREAM_ERROR_MESSAGE,
    }
