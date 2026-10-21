# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Authenticated Workbench history pin endpoints."""

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Path
from fastapi.responses import JSONResponse
from pydantic import StrictBool

from consts.exceptions import ConversationNotFoundError, TokenExpiredError, UnauthorizedError, ValidationError
from management.services.conversation.pins import get_workbench_pins, update_workbench_pin
from management.services.permission.identity.authentication_helpers import get_current_user_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/conversation")


def _execute(authorization, operation):
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        return JSONResponse(content={"code": 0, "message": "success", "data": operation(user_id, tenant_id)})
    except (TokenExpiredError, UnauthorizedError) as exc:
        raise HTTPException(status_code=401, detail="Please login first") from exc
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Workbench conversation not found") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Workbench pin operation failed")
        raise HTTPException(status_code=500, detail="Workbench pin operation failed") from exc


@router.get("/workbench_pins")
def list_workbench_pins_endpoint(authorization: Optional[str] = Header(None)):
    return _execute(authorization, get_workbench_pins)


@router.put("/{conversation_id}/workbench_pin")
def set_workbench_pin_endpoint(
    conversation_id: Annotated[int, Path(gt=0, le=2147483647)],
    pinned: Annotated[StrictBool, Body(embed=True)],
    authorization: Optional[str] = Header(None),
):
    return _execute(authorization, lambda user, tenant: update_workbench_pin(conversation_id, pinned, user, tenant))
