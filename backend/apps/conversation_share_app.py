import logging
from datetime import datetime
from http import HTTPStatus
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Header, HTTPException, Path as PathParam, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from consts.exceptions import FileTooLargeException, NotFoundException, UnsupportedFileTypeException
from services.conversation_share_service import (
    create_share_snapshot_service,
    get_share_asset_service,
    get_share_snapshot_service,
)
from services.file_management_service import get_file_stream_impl, get_preview_stream, resolve_preview_file
from utils.auth_utils import get_current_user_id

from .file_management_app import build_content_disposition_header

logger = logging.getLogger("conversation_share_app")

router = APIRouter(prefix="/share")


class CreateConversationShareRequest(BaseModel):
    mode: str = "selected"
    selected_user_message_ids: Optional[List[int]] = None
    expire_time: Optional[datetime] = None


def _parse_range_header(range_header: Optional[str], total_size: int) -> Optional[Tuple[int, int]]:
    if not range_header:
        return None
    if not range_header.startswith("bytes="):
        return None

    range_value = range_header[len("bytes="):].strip()
    if "," in range_value:
        return None

    start_text, _, end_text = range_value.partition("-")
    try:
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else total_size - 1
        else:
            suffix_length = int(end_text)
            if suffix_length <= 0:
                return None
            start = max(total_size - suffix_length, 0)
            end = total_size - 1
    except ValueError:
        return None

    if start < 0 or end < start or start >= total_size:
        return None
    return start, min(end, total_size - 1)


@router.post("/conversation/{conversation_id}")
async def create_conversation_share_endpoint(
    request: CreateConversationShareRequest,
    conversation_id: int,
    authorization: Optional[str] = Header(None),
):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = create_share_snapshot_service(
            conversation_id=conversation_id,
            user_id=user_id,
            tenant_id=tenant_id,
            mode=request.mode,
            selected_user_message_ids=request.selected_user_message_ids,
            expire_time=request.expire_time,
        )
        result["url"] = f"/share/{result['share_id']}"
        return {"code": 0, "message": "success", "data": result}
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Failed to create conversation share: %s", str(e), exc_info=True)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Failed to create share")


@router.get("/{share_token}")
async def get_conversation_share_endpoint(share_token: str):
    try:
        return {
            "code": 0,
            "message": "success",
            "data": get_share_snapshot_service(share_token),
        }
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error("Failed to get conversation share: %s", str(e), exc_info=True)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Failed to get share")


@router.get("/{share_token}/assets/{asset_id}/download")
async def download_share_asset_endpoint(
    share_token: str,
    asset_id: str,
    filename: Optional[str] = Query(None),
):
    try:
        asset = get_share_asset_service(share_token, asset_id)
        object_name = asset["object_name"]
        file_stream, content_type = await get_file_stream_impl(object_name=object_name)
        download_filename = filename or asset.get("filename") or object_name.rsplit("/", 1)[-1]
        return StreamingResponse(
            file_stream,
            media_type=content_type,
            headers={
                "Content-Disposition": build_content_disposition_header(download_filename),
                "Cache-Control": "public, max-age=3600",
                "ETag": f'"share-{share_token}-{asset_id}"',
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error("Failed to download share asset: %s", str(e), exc_info=True)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Failed to download asset")


@router.get("/{share_token}/assets/{asset_id}/preview")
async def preview_share_asset_endpoint(
    share_token: str,
    asset_id: str,
    filename: Optional[str] = Query(None),
    range_header: Optional[str] = Header(None, alias="range"),
):
    try:
        asset = get_share_asset_service(share_token, asset_id)
        object_name = asset["object_name"]
        actual_name, content_type, total_size = await resolve_preview_file(object_name=object_name)
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except FileTooLargeException as e:
        raise HTTPException(status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE, detail=str(e))
    except NotFoundException as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except UnsupportedFileTypeException as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Failed to resolve share asset preview: %s", str(e), exc_info=True)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Failed to preview asset")

    display_filename = filename or asset.get("filename") or object_name.rsplit("/", 1)[-1]
    common_headers = {
        "Content-Disposition": build_content_disposition_header(display_filename, inline=True),
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=3600",
        "ETag": f'"share-{share_token}-{asset_id}"',
    }

    if total_size == 0:
        return StreamingResponse(
            iter([]),
            status_code=HTTPStatus.OK,
            media_type=content_type,
            headers={**common_headers, "Content-Length": "0"},
        )

    parsed_range = _parse_range_header(range_header, total_size) if range_header else None
    if range_header and parsed_range is None:
        return StreamingResponse(
            iter([]),
            status_code=HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE,
            headers={"Content-Range": f"bytes */{total_size}"},
        )

    try:
        if parsed_range:
            start, end = parsed_range
            stream = get_preview_stream(actual_name, start, end)
            return StreamingResponse(
                stream.iter_chunks(chunk_size=64 * 1024),
                status_code=HTTPStatus.PARTIAL_CONTENT,
                media_type=content_type,
                background=BackgroundTask(stream.close),
                headers={
                    **common_headers,
                    "Content-Range": f"bytes {start}-{end}/{total_size}",
                    "Content-Length": str(end - start + 1),
                },
            )

        stream = get_preview_stream(actual_name)
        return StreamingResponse(
            stream.iter_chunks(chunk_size=64 * 1024),
            status_code=HTTPStatus.OK,
            media_type=content_type,
            background=BackgroundTask(stream.close),
            headers={**common_headers, "Content-Length": str(total_size)},
        )
    except Exception as e:
        logger.error("Failed to stream share asset preview: %s", str(e), exc_info=True)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Failed to stream asset")
