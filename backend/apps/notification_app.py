"""Notification API endpoints."""
import logging
from http import HTTPStatus
from typing import Annotated, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query
from starlette.responses import JSONResponse

from consts.exceptions import NotFoundException, UnauthorizedError
from services.notification_service import list_notifications, mark_notifications_read
from utils.auth_utils import get_current_user_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_notifications_endpoint(
    only_unread: bool = Query(False, description="Return only unread notifications"),
    page: Annotated[int, Query(ge=1, description="Page number starting from 1")] = 1,
    page_size: Annotated[
        int, Query(ge=1, le=100, description="Page size from 1 to 100")
    ] = 10,
    authorization: Optional[str] = Header(None),
) -> JSONResponse:
    """List the current user's notifications."""
    try:
        user_id, _ = get_current_user_id(authorization)
        result = list_notifications(
            user_id,
            only_unread=only_unread,
            page=page,
            page_size=page_size,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "OK", "data": result},
        )
    except UnauthorizedError as exc:
        logger.warning("Unauthorized notification list access: %s", exc)
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Unexpected error listing notifications: %s", exc)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to list notifications",
        ) from exc


@router.post("/read")
async def mark_notifications_read_endpoint(
    mark_all: bool = Body(False, embed=True, description="Mark all unread as read"),
    receiver_id: Optional[int] = Body(
        None, embed=True, description="Receiver row ID when mark_all is false"
    ),
    authorization: Optional[str] = Header(None),
) -> JSONResponse:
    """Mark one or all of the current user's notifications as read."""
    try:
        user_id, _ = get_current_user_id(authorization)
        result = mark_notifications_read(
            user_id,
            mark_all=mark_all,
            receiver_id=receiver_id,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "OK", "data": result},
        )
    except UnauthorizedError as exc:
        logger.warning("Unauthorized mark-read access: %s", exc)
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc)) from exc
    except NotFoundException as exc:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Unexpected error marking notifications read: %s", exc)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to mark notifications as read",
        ) from exc
