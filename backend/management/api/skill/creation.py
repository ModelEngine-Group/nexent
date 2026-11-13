# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging
from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from starlette.responses import StreamingResponse

from contracts.agent import NL2SkillRunRequest
from contracts.constants.environment import ENABLE_AGENT_WORKBENCH
from contracts.errors.exceptions import RunModelControlsError
from infrastructure.rdb.conversation_state import conversation_belongs_to
from management.services.conversation.creation_history import persist_creation_stream, prepare_creation_history
from management.services.permission.identity.session import get_current_user_info
from management.services.skill.creation import create_nl2skill_stream, prepare_nl2skill_snapshot
from nexent.core.concurrency import run_blocking
from permissions.depends import require
from permissions.models import CurrentUser

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
        user_id, tenant_id, user_language = get_current_user_info(authorization)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Unauthorized") from exc

    try:
        if request.persist_history and request.conversation_id is not None:
            if not await run_blocking(
                "nl2skill-conversation-scope", conversation_belongs_to, request.conversation_id,
                user_id=user_id, tenant_id=tenant_id, lane="control-io", owner="management",
            ):
                raise ValueError("Conversation is not an accessible creation session")
        payload = await run_blocking(
            "nl2skill-snapshot", prepare_nl2skill_snapshot, request, user_id, tenant_id,
            request.language or user_language or "zh", lane="control-io", owner="management",
        )
        stream = create_nl2skill_stream(payload, user_id, tenant_id)
        if request.persist_history:
            conversation_id, assistant_index = await run_blocking(
                "nl2skill-history", prepare_creation_history, lane="control-io", owner="management",
                conversation_id=request.conversation_id,
                mode="skill_create",
                query=request.query,
                minio_files=request.minio_files,
                workbench_config=request.workbench_config,
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
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Attachment access denied.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid Workbench creation session.") from exc
    except HTTPException:
        raise
    except Exception:
        logger.exception("NL2Skill run error")
        raise HTTPException(status_code=500, detail="NL2Skill run error.")
