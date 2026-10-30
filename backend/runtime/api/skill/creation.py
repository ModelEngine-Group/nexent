# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging
from nexent.core.concurrency import run_blocking
from http import HTTPStatus
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException
from starlette.responses import StreamingResponse
from contracts.constants.environment import ENABLE_AGENT_WORKBENCH
from contracts.agent import NL2SkillRunRequest
from permissions.depends import require
from permissions.models import CurrentUser
from contracts.errors.exceptions import RunModelControlsError
from services.nl2skill_service import create_nl2skill_stream
from management.services.conversation.creation_history import prepare_creation_history, persist_creation_stream
from gateway.authentication.auth import get_current_user_id, get_current_user_info

logger = logging.getLogger(__name__)


skill_creator_router = APIRouter(prefix="/skills", tags=["nl2skill"])


require_skill_create_permission = require("skill:create")


@skill_creator_router.post("/nl2skill/run")
async def nl2skill_run_api(
    request: NL2SkillRunRequest,
    authorization: Optional[str] = Header(None),
    _current_user: CurrentUser = Depends(require_skill_create_permission),
):
    """Run NL2Skill; Workbench turns opt into conversation persistence."""
    if (request.persist_history or request.workbench_config is not None) and not ENABLE_AGENT_WORKBENCH:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail={"code": "WORKBENCH_DISABLED"})
    try:
        _, tenant_id, user_language = get_current_user_info(authorization)
    except Exception as e:
        logger.error(f"Unauthorized access attempt: {e}")
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        if request.conversation_id is not None:
            from management.services.conversation.model_preferences import read_model_preferences
            preference_user, _ = get_current_user_id(authorization)
            saved = await run_blocking("creator-model-preferences", read_model_preferences, request.conversation_id, preference_user)
            request.__dict__["_runtime_model_parameter_preferences"] = saved["model_parameter_preferences"]
            if request.model_id is None:
                request.model_id = saved.get("selected_model_id")
        stream = await create_nl2skill_stream(
            request=request,
            tenant_id=tenant_id,
            language=request.language or user_language or "zh",
        )
        if request.persist_history:
            user_id, _ = get_current_user_id(authorization)
            conversation_id, assistant_index = prepare_creation_history(
                conversation_id=request.conversation_id,
                mode="skill_create",
                query=request.query,
                minio_files=request.minio_files,
                workbench_config=request.workbench_config,
                model_parameter_preferences=request.model_parameter_preferences,
                selected_model_id=request.model_id,
                agent_id=None,
                user_id=user_id,
                tenant_id=tenant_id,
                retry_user_message_id=request.retry_user_message_id,
                retry_message_index=request.retry_message_index,
            )
            stream = persist_creation_stream(
                stream,
                conversation_id=conversation_id,
                assistant_index=assistant_index,
                user_id=user_id,
                tenant_id=tenant_id,
            )
            return StreamingResponse(
                stream,
                media_type="text/event-stream",
                headers={"conversation_id": str(conversation_id)},
            )
        return StreamingResponse(stream, media_type="text/event-stream")
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
