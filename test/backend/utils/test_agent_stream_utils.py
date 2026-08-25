"""Unit tests for agent stream skill-file helpers."""

import json
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# Keep these utility tests isolated from database and file-service import chains.
# The functions are patched at their import site by individual tests below.
attachment_db = types.ModuleType("database.attachment_db")
attachment_db._build_mcp_presigned_url = MagicMock(side_effect=lambda url: f"/proxy?url={url}")
attachment_db.get_file_url = MagicMock()
attachment_db.upload_fileobj = MagicMock()
sys.modules["database.attachment_db"] = attachment_db

file_management_service = types.ModuleType("services.file_management_service")
file_management_service.is_allowed_skill_upload_path = MagicMock(return_value=True)
sys.modules["services.file_management_service"] = file_management_service

from backend.utils import agent_stream_utils


class TestJsonExtraction:
    @pytest.mark.parametrize("text", ["", "plain text without JSON"])
    def test_returns_empty_when_no_json_object_exists(self, text):
        assert agent_stream_utils.extract_json_objects_from_text(text) == []

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

    def test_transforms_only_permanent_file_fields(self):
        assert agent_stream_utils.transform_skill_files_to_standard_format(
            [{"name": "a.txt", "size": 3, "preview_url": "/preview"}]
        ) == [
            {
                "object_name": "",
                "name": "a.txt",
                "type": "file",
                "size": 3,
                "url": "",
                "description": "",
            }
        ]

    def test_enriches_response_metadata_with_presigned_url_without_mutating_input(self):
        uploads = [{"object_name": "outputs/chart.png", "url": "s3://nexent/outputs/chart.png"}]

        with patch.object(
            agent_stream_utils,
            "get_file_url",
            return_value={"success": True, "url": "https://minio/signed"},
        ), patch.object(
            agent_stream_utils,
            "_build_mcp_presigned_url",
            return_value="https://api/file/fetch?signed",
        ):
            result = agent_stream_utils.enrich_file_uploads_with_presigned_urls(uploads)

        assert "presigned_url" not in uploads[0]
        assert result[0]["presigned_url"] == "https://api/file/fetch?signed"

    def test_preserves_existing_presigned_url(self):
        uploads = [{"object_name": "outputs/chart.png", "presigned_url": "existing"}]

        with patch.object(agent_stream_utils, "get_file_url") as get_file_url:
            result = agent_stream_utils.enrich_file_uploads_with_presigned_urls(uploads)

        assert result[0]["presigned_url"] == "existing"
        get_file_url.assert_not_called()


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
    assert not safe_file.exists()


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
        "url": "/result.txt",
        "mime_type": "text/plain",
        "file_size": 6,
    }]
    assert upload.call_args.kwargs["prefix"] == "skill-files/user-1"
    assert upload.call_args.kwargs["generate_presigned_url"] is False
    assert not file_path.exists()


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
    assert not file_path.exists()


@pytest.mark.asyncio
async def test_process_uploads_skips_empty_path_and_logs_cleanup_failure(tmp_path):
    file_path = tmp_path / "cleanup.txt"
    file_path.write_text("cleanup", encoding="utf-8")

    with patch.object(agent_stream_utils, "is_allowed_skill_upload_path", return_value=True), \
            patch.object(agent_stream_utils, "upload_fileobj", return_value={"success": False}), \
            patch.object(agent_stream_utils.os, "remove", side_effect=OSError("locked")), \
            patch.object(agent_stream_utils.logger, "exception") as log_exception:
        result = await agent_stream_utils.process_skill_file_uploads(
            [{"absolute_path": ""}, {"absolute_path": str(file_path)}],
            user_id="user-1",
            tenant_id="tenant-1",
        )

    assert result == []
    log_exception.assert_called_once_with(
        "[skill-file] failed to delete local artifact absolute_path=%s",
        str(file_path),
    )


@pytest.mark.asyncio
async def test_process_uploads_recovers_empty_derived_file_name(tmp_path):
    file_path = tmp_path / "fallback.txt"
    file_path.write_text("fallback", encoding="utf-8")

    with patch.object(agent_stream_utils, "is_allowed_skill_upload_path", return_value=True), \
            patch.object(agent_stream_utils.os.path, "basename", side_effect=["", "fallback.txt"]), \
            patch.object(
                agent_stream_utils,
                "upload_fileobj",
                return_value={"success": True, "object_name": "fallback"},
            ) as upload:
        await agent_stream_utils.process_skill_file_uploads(
            [{"absolute_path": str(file_path)}],
            user_id="user-1",
            tenant_id="tenant-1",
        )

    assert upload.call_args.kwargs["file_name"] == "fallback.txt"


def test_safe_agent_stream_error_chunk_is_sanitized():
    chunk = agent_stream_utils.safe_agent_stream_error_chunk()
    assert chunk.startswith("data: ")
    assert chunk.endswith("\n\n")
    assert json.loads(chunk[6:].strip()) == {
        "type": "error",
        "content": agent_stream_utils.SAFE_AGENT_STREAM_ERROR_MESSAGE,
    }
