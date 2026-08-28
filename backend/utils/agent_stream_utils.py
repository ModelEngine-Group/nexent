"""Utilities for processing agent stream content and generated skill files."""

import json
import logging
import os
from typing import Any, Dict

from consts.agent import SAFE_AGENT_STREAM_ERROR_MESSAGE
from database.attachment_db import _build_mcp_presigned_url, get_file_url, upload_fileobj
from services.file_management_service import is_allowed_skill_upload_path

logger = logging.getLogger(__name__)


def extract_json_objects_from_text(text: str) -> list[dict]:
    """Extract all JSON objects embedded in a text blob."""
    if not text:
        return []

    decoder = json.JSONDecoder()
    results: list[dict] = []
    index = 0

    while index < len(text):
        start_index = text.find("{", index)
        if start_index < 0:
            break

        try:
            payload, end_index = decoder.raw_decode(text, start_index)
        except json.JSONDecodeError:
            index = start_index + 1
            continue

        if isinstance(payload, dict):
            results.append(payload)
        index = max(end_index, start_index + 1)

    return results


def extract_skill_file_upload_payloads(content: str) -> list[dict]:
    """Extract JSON payloads containing absolute_path from streamed tool output."""
    return [
        payload
        for payload in extract_json_objects_from_text(content)
        if payload.get("absolute_path")
    ]


def serialize_stream_unit_content(data: Dict[str, Any], content: str) -> str:
    """Preserve tool metadata in the existing message-unit content column."""
    if data.get("type") not in {"tool", "tool-call"}:
        return content

    payload: Dict[str, Any] = {"content": content}
    for field in ("tool_name", "tool_arguments", "role"):
        if field in data:
            payload[field] = data[field]
    return json.dumps(payload, ensure_ascii=False)


def transform_skill_files_to_standard_format(upload_results: list[dict]) -> list[dict]:
    """Transform skill upload results to the frontend attachment format."""
    attachments = []
    for result in upload_results:
        attachment = {
            "object_name": result.get("object_name", ""),
            "name": result.get("file_name", result.get("name", "")),
            "type": "file",
            "size": result.get("file_size", result.get("size", 0)),
            "url": result.get("url", ""),
            "description": "",
        }
        if result.get("presigned_url"):
            attachment["presigned_url"] = result["presigned_url"]
        attachments.append(attachment)
    return attachments


def enrich_file_uploads_with_presigned_urls(
    upload_results: list[dict],
    expires: int = 86400,
) -> list[dict]:
    """Add short-lived northbound URLs to response metadata without mutating tool results."""
    enriched_results: list[dict] = []
    for result in upload_results:
        enriched_result = dict(result)
        object_name = str(result.get("object_name") or "").strip()
        if object_name and not enriched_result.get("presigned_url"):
            try:
                url_result = get_file_url(object_name=object_name, expires=expires)
                if url_result.get("success") and url_result.get("url"):
                    enriched_result["presigned_url"] = _build_mcp_presigned_url(
                        url_result["url"]
                    )
                else:
                    logger.warning(
                        "Failed to generate presigned URL object_name=%s error=%s",
                        object_name,
                        url_result.get("error"),
                    )
            except Exception:
                logger.exception(
                    "Failed to enrich file upload with presigned URL object_name=%s",
                    object_name,
                )
        enriched_results.append(enriched_result)
    return enriched_results


async def process_skill_file_uploads(
    payloads: list[dict] | str,
    user_id: str,
    tenant_id: str,
) -> list[dict]:
    """Upload generated skill files to storage and return upload metadata."""

    upload_results: list[dict] = []
    structured_payloads = (
        payloads
        if isinstance(payloads, list)
        else extract_skill_file_upload_payloads(payloads)
    )
    for payload in structured_payloads:
        absolute_path = str(payload.get("absolute_path") or "").strip()
        file_name = str(
            payload.get("file_name")
            or payload.get("file_path")
            or os.path.basename(absolute_path)
        )
        mime_type = str(payload.get("mime_type") or payload.get("content_type") or "application/octet-stream")
        if not absolute_path:
            continue

        if not is_allowed_skill_upload_path(absolute_path):
            logger.warning("[skill-file] rejected unsafe path absolute_path=%s", absolute_path)
            continue

        if not file_name:
            file_name = os.path.basename(absolute_path)

        if not os.path.exists(absolute_path):
            continue

        try:
            file_size = os.path.getsize(absolute_path)
            actual_prefix = f"skill-files/{user_id}" if user_id else "skill-files"
            with open(absolute_path, "rb") as file_obj:
                upload_result = upload_fileobj(
                    file_obj=file_obj,
                    file_name=file_name,
                    prefix=actual_prefix,
                    generate_presigned_url=False,
                    file_size=file_size,
                )

            if upload_result.get("success"):
                upload_results.append(
                    {
                        "status": "success",
                        "file_name": file_name,
                        "absolute_path": absolute_path,
                        "object_name": upload_result.get("object_name"),
                        "url": upload_result.get("url"),
                        "mime_type": mime_type,
                        "file_size": upload_result.get("file_size", file_size),
                    }
                )
            else:
                error_message = upload_result.get("error") or "Upload failed"
                logger.warning(
                    "[skill-file] upload failed file_name=%s absolute_path=%s error=%s",
                    file_name,
                    absolute_path,
                    error_message,
                )
        except Exception:
            logger.exception(
                "[skill-file] failed to upload file file_name=%s absolute_path=%s",
                file_name,
                absolute_path,
            )
        finally:
            # Declared skill artifacts are ephemeral. MinIO is the sole durable store.
            try:
                if os.path.isfile(absolute_path):
                    os.remove(absolute_path)
            except OSError:
                logger.exception(
                    "[skill-file] failed to delete local artifact absolute_path=%s",
                    absolute_path,
                )

    return upload_results


def safe_agent_stream_error_chunk() -> str:
    """Return a sanitized SSE error chunk without internal exception details."""
    error_payload = json.dumps(
        {"type": "error", "content": SAFE_AGENT_STREAM_ERROR_MESSAGE},
        ensure_ascii=False,
    )
    return f"data: {error_payload}\n\n"
