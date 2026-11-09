# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Authenticated owner-private question bookmark endpoints."""

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Path
from fastapi.responses import JSONResponse
from pydantic import StrictBool

from contracts.errors.exceptions import ConversationNotFoundError, TokenExpiredError, UnauthorizedError, ValidationError
from gateway.authentication.auth import get_current_user_id
from management.services.conversation.bookmarks import list_question_bookmarks, set_question_bookmark

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/conversation")
PositiveId = Annotated[int, Path(gt=0, le=2147483647)]


def _execute(authorization, operation):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        return JSONResponse(content={"code": 0, "message": "success", "data": operation(user_id, tenant_id)})
    except (TokenExpiredError, UnauthorizedError) as exc:
        raise HTTPException(status_code=401, detail="Please login first") from exc
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Conversation or question not found") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Question bookmark operation failed")
        raise HTTPException(status_code=500, detail="Question bookmark operation failed") from exc


@router.get("/{conversation_id}/question_bookmarks")
def get_bookmarks(conversation_id: PositiveId, authorization: Optional[str] = Header(None)):
    return _execute(authorization, lambda user, tenant: list_question_bookmarks(conversation_id, user, tenant))


@router.put("/{conversation_id}/question_bookmarks/{message_id}")
def put_bookmark(
    conversation_id: PositiveId,
    message_id: PositiveId,
    bookmarked: Annotated[StrictBool, Body(embed=True)],
    authorization: Optional[str] = Header(None),
):
    return _execute(
        authorization, lambda user, tenant: set_question_bookmark(conversation_id, message_id, bookmarked, user, tenant)
    )
