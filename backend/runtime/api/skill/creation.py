# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging
from http import HTTPStatus
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException
from starlette.responses import StreamingResponse
from contracts.constants.environment import ENABLE_AGENT_WORKBENCH
from contracts.agent import NL2SkillRunRequest
from permissions.depends import require
from permissions.models import CurrentUser
from contracts.errors.exceptions import RunModelControlsError, WorkbenchError
from services.nl2skill_service import create_nl2skill_stream
from management.services.conversation.creator_execution import start_creation_turn
from gateway.authentication.auth import get_current_user_info

logger = logging.getLogger(__name__)


skill_creator_router = APIRouter(prefix="/skills", tags=["nl2skill"])


require_skill_create_permission = require("skill:create")


@skill_creator_router.post("/nl2skill/run")
async def nl2skill_run_api(
    request: NL2SkillRunRequest,
    authorization: Optional[str] = Header(None),
    _current_user: CurrentUser = Depends(require_skill_create_permission),
):
    """Run the shared NL2Skill using the common creator history path."""
    if request.workbench_config is not None and not ENABLE_AGENT_WORKBENCH:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail={"code": "WORKBENCH_DISABLED"})
    try:
        user_id, tenant_id, user_language = get_current_user_info(authorization)
    except Exception as e:
        logger.error(f"Unauthorized access attempt: {e}")
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        stream, conversation_id = await start_creation_turn(
            request, kind="skill", user_id=user_id, tenant_id=tenant_id,
            stream_factory=lambda effective, ref: create_nl2skill_stream(
                request=effective, tenant_id=tenant_id,
                language=request.language or user_language or "zh", system_ref=ref,
            ),
        )
        return StreamingResponse(stream, media_type="text/event-stream",
                                 headers={"conversation_id": str(conversation_id)})
    except PermissionError as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(exc)) from exc

    except WorkbenchError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code}) from exc
    except RunModelControlsError as exc:
        status = {"model_not_available": 404, "model_unavailable": 409, "model_type_invalid": 400}.get(exc.code, 422)
        raise HTTPException(status_code=status, detail={"code": exc.code}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid Workbench creation session.") from exc
    except HTTPException:
        raise
    except Exception:
        logger.exception("NL2Skill run error")
        raise HTTPException(status_code=500, detail="NL2Skill run error.")
