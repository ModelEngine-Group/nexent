import copy
import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

from database.attachment_db import get_content_type, get_file_size_from_minio
from database.conversation_db import get_conversation
from database.conversation_share_db import (
    create_conversation_share,
    create_conversation_share_assets,
    get_active_conversation_share,
    get_share_asset,
)
from services.conversation_management_service import get_conversation_history_service

logger = logging.getLogger("conversation_share_service")

SHARE_ASSET_PLACEHOLDER_PREFIX = "__share_asset__:"
_OBJECT_NAME_KEYS = ("object_name", "objectName", "minio_object_name", "minioObjectName")


def _new_token() -> str:
    return uuid.uuid4().hex + uuid.uuid4().hex[:16]


def _new_asset_id() -> str:
    return uuid.uuid4().hex


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


def _public_preview_url(share_token: str, asset_id: str) -> str:
    return f"/api/share/{share_token}/assets/{asset_id}/preview"


def _public_download_url(share_token: str, asset_id: str) -> str:
    return f"/api/share/{share_token}/assets/{asset_id}/download"


def _extract_object_name(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None

    if raw.startswith("s3://"):
        parts = raw.replace("s3://", "", 1).split("/", 1)
        return parts[1] if len(parts) == 2 else None

    if raw.startswith("http://") or raw.startswith("https://"):
        try:
            parsed = urlparse(raw)
            path = unquote(parsed.path).lstrip("/")
        except Exception:
            return None
        markers = ("attachments/", "knowledge_base/", "images_in_attachments/", "skill-files/")
        for marker in markers:
            idx = path.find(marker)
            if idx >= 0:
                return path[idx:]
        if "/api/file/download/" in raw:
            return path.split("api/file/download/", 1)[-1]
        if "/api/file/preview/" in raw:
            return path.split("api/file/preview/", 1)[-1]
        return None

    normalized = raw.lstrip("/")
    if normalized.startswith("api/file/download/"):
        return normalized.split("api/file/download/", 1)[-1].split("?", 1)[0]
    if normalized.startswith("api/file/preview/"):
        return normalized.split("api/file/preview/", 1)[-1].split("?", 1)[0]
    if normalized.startswith(("attachments/", "knowledge_base/", "images_in_attachments/", "skill-files/")):
        return normalized
    return None


def _guess_filename(reference: Dict[str, Any], object_name: str) -> str:
    for key in ("name", "filename", "file_name", "title", "source_title"):
        value = reference.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return object_name.rsplit("/", 1)[-1]


def _register_asset(
    share_token: str,
    object_name: str,
    reference: Dict[str, Any],
    source_kind: str,
    asset_map: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    existing = asset_map.get(object_name)
    if existing:
        return existing

    filename = _guess_filename(reference, object_name)
    try:
        content_type = reference.get("type") or reference.get("contentType") or get_content_type(object_name)
    except Exception:
        content_type = reference.get("type") or reference.get("contentType") or "application/octet-stream"

    size = reference.get("size")
    if size is None:
        try:
            size = get_file_size_from_minio(object_name)
        except Exception:
            size = 0

    asset = {
        "asset_id": _new_asset_id(),
        "share_token": share_token,
        "object_name": object_name,
        "filename": filename,
        "content_type": content_type,
        "size": int(size or 0),
        "source_kind": source_kind,
        "metadata_json": _json_safe(reference),
    }
    asset["preview_url"] = _public_preview_url(share_token, asset["asset_id"])
    asset["download_url"] = _public_download_url(share_token, asset["asset_id"])
    asset_map[object_name] = asset
    return asset


def _rewrite_attachment(
    share_token: str,
    attachment: Any,
    asset_map: Dict[str, Dict[str, Any]],
    source_kind: str,
) -> Any:
    if not isinstance(attachment, dict):
        return attachment

    object_name = None
    for key in _OBJECT_NAME_KEYS:
        object_name = object_name or _extract_object_name(attachment.get(key))
    object_name = object_name or _extract_object_name(attachment.get("url"))
    object_name = object_name or _extract_object_name(attachment.get("presigned_url"))
    if not object_name:
        return attachment

    asset = _register_asset(share_token, object_name, attachment, source_kind, asset_map)
    rewritten = dict(attachment)
    rewritten["object_name"] = object_name
    rewritten["asset_id"] = asset["asset_id"]
    rewritten["preview_url"] = asset["preview_url"]
    rewritten["download_url"] = asset["download_url"]
    if not rewritten.get("url") or _extract_object_name(rewritten.get("url")):
        rewritten["url"] = asset["preview_url"]
    return rewritten


def _rewrite_search_result(
    share_token: str,
    result: Any,
    asset_map: Dict[str, Dict[str, Any]],
) -> Any:
    if not isinstance(result, dict):
        return result

    rewritten = copy.deepcopy(result)
    source_type = rewritten.get("source_type")
    search_type = rewritten.get("search_type")
    is_file_like = source_type in ("file", "datamate", "aidp") or search_type == "aidp_search" or bool(rewritten.get("filename"))
    object_name = None
    for key in _OBJECT_NAME_KEYS:
        object_name = object_name or _extract_object_name(rewritten.get(key))
    object_name = object_name or _extract_object_name(rewritten.get("url"))

    if is_file_like and object_name:
        asset = _register_asset(share_token, object_name, rewritten, "source", asset_map)
        rewritten["asset_id"] = asset["asset_id"]
        rewritten["object_name"] = object_name
        rewritten["preview_url"] = asset["preview_url"]
        rewritten["download_url"] = asset["download_url"]
        rewritten["url"] = asset["download_url"]

    score_details = rewritten.get("score_details")
    if isinstance(score_details, dict):
        for key in _OBJECT_NAME_KEYS:
            score_object_name = _extract_object_name(score_details.get(key))
            if score_object_name:
                asset = _register_asset(share_token, score_object_name, rewritten, "source", asset_map)
                rewritten["asset_id"] = asset["asset_id"]
                rewritten["object_name"] = score_object_name
                rewritten["preview_url"] = asset["preview_url"]
                rewritten["download_url"] = asset["download_url"]
                rewritten["url"] = asset["download_url"]
                break

    return rewritten


def _rewrite_markdown_s3_links(
    share_token: str,
    text: str,
    asset_map: Dict[str, Dict[str, Any]],
) -> str:
    if not isinstance(text, str) or "s3://" not in text:
        return text

    def replace(match: re.Match) -> str:
        raw = match.group(0)
        object_name = _extract_object_name(raw)
        if not object_name:
            return raw
        asset = _register_asset(share_token, object_name, {"url": raw}, "markdown", asset_map)
        return asset["preview_url"]

    return re.sub(r"s3://[^\s)\"']+", replace, text)


def _rewrite_message_assets(
    share_token: str,
    snapshot: Dict[str, Any],
    asset_map: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    result = copy.deepcopy(snapshot)

    for message in result.get("message", []):
        if isinstance(message.get("minio_files"), list):
            message["minio_files"] = [
                _rewrite_attachment(share_token, item, asset_map, "attachment")
                for item in message["minio_files"]
            ]

        if isinstance(message.get("picture"), list):
            rewritten_pictures = []
            for picture in message["picture"]:
                object_name = _extract_object_name(picture)
                if object_name:
                    asset = _register_asset(share_token, object_name, {"url": picture}, "image", asset_map)
                    rewritten_pictures.append(asset["preview_url"])
                else:
                    rewritten_pictures.append(picture)
            message["picture"] = rewritten_pictures

        if isinstance(message.get("search"), list):
            message["search"] = [
                _rewrite_search_result(share_token, item, asset_map)
                for item in message["search"]
            ]

        search_by_unit = message.get("searchByUnitId") or message.get("search_unit_id")
        if isinstance(search_by_unit, dict):
            rewritten_by_unit = {
                str(unit_id): [
                    _rewrite_search_result(share_token, item, asset_map)
                    for item in items
                ] if isinstance(items, list) else items
                for unit_id, items in search_by_unit.items()
            }
            message["searchByUnitId"] = rewritten_by_unit
            message["search_unit_id"] = rewritten_by_unit

        msg_payload = message.get("message")
        if isinstance(msg_payload, list):
            for unit in msg_payload:
                if isinstance(unit, dict) and isinstance(unit.get("content"), str):
                    unit["content"] = _rewrite_markdown_s3_links(
                        share_token, unit["content"], asset_map
                    )
        elif isinstance(msg_payload, str):
            message["message"] = _rewrite_markdown_s3_links(share_token, msg_payload, asset_map)

    return result


def _select_message_pairs(messages: List[Dict[str, Any]], selected_user_message_ids: Optional[List[int]]) -> List[Dict[str, Any]]:
    if not selected_user_message_ids:
        return messages

    selected = {int(item) for item in selected_user_message_ids}
    output: List[Dict[str, Any]] = []
    include_assistant = False
    for message in messages:
        role = message.get("role")
        message_id = message.get("message_id")
        if role == "user":
            include_assistant = bool(message_id in selected)
            if include_assistant:
                output.append(message)
            continue
        if role == "assistant" and include_assistant:
            output.append(message)
            include_assistant = False
    return output


def create_share_snapshot_service(
    conversation_id: int,
    user_id: str,
    tenant_id: str,
    mode: str = "selected",
    selected_user_message_ids: Optional[List[int]] = None,
    expire_time: Optional[datetime] = None,
) -> Dict[str, Any]:
    conversation = get_conversation(conversation_id, user_id)
    if not conversation:
        raise ValueError(f"Conversation {conversation_id} does not exist or is not accessible")

    history_payload = get_conversation_history_service(conversation_id, user_id)
    if not history_payload:
        raise ValueError(f"No history data found for conversation_id: {conversation_id}")

    snapshot = copy.deepcopy(history_payload[0])
    messages = snapshot.get("message") or []
    if mode != "all":
        messages = _select_message_pairs(messages, selected_user_message_ids)
    snapshot["message"] = messages
    snapshot["conversation_title"] = conversation.get("conversation_title") or ""

    share_token = _new_token()
    asset_map: Dict[str, Dict[str, Any]] = {}
    snapshot = _rewrite_message_assets(share_token, snapshot, asset_map)

    share_record = create_conversation_share({
        "share_token": share_token,
        "conversation_id": conversation_id,
        "tenant_id": tenant_id,
        "title": conversation.get("conversation_title") or "",
        "mode": "all" if mode == "all" else "selected",
        "selected_message_ids": _json_safe(selected_user_message_ids or []),
        "snapshot_json": _json_safe(snapshot),
        "status": "active",
        "expire_time": expire_time,
    }, user_id)

    persisted_assets = create_conversation_share_assets(
        share_token,
        [{k: v for k, v in asset.items() if k not in ("preview_url", "download_url")} for asset in asset_map.values()],
        user_id,
    )

    return {
        "share_id": share_token,
        "share_token": share_token,
        "conversation_id": conversation_id,
        "title": share_record.get("title") or "",
        "asset_count": len(persisted_assets),
    }


def get_share_snapshot_service(share_token: str) -> Dict[str, Any]:
    share = get_active_conversation_share(share_token)
    if not share:
        raise ValueError("Share not found or expired")
    return {
        "share_id": share_token,
        "title": share.get("title") or "",
        "conversation_id": share.get("conversation_id"),
        "create_time": share.get("create_time"),
        "snapshot": share.get("snapshot_json"),
    }


def get_share_asset_service(share_token: str, asset_id: str) -> Dict[str, Any]:
    share = get_active_conversation_share(share_token)
    if not share:
        raise ValueError("Share not found or expired")

    asset = get_share_asset(share_token, asset_id)
    if not asset:
        raise ValueError("Share asset not found")
    return asset
