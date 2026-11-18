# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import logging
from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from starlette.responses import StreamingResponse

from contracts.agent import NL2SkillRunRequest
from contracts.agentos import AgentVersionReference
from contracts.errors.exceptions import AgentRunAlreadyActiveError, WorkbenchError
from management.services.conversation.creator_execution import start_creation_turn
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
    resume: bool = False,
):
    """Run the shared NL2Skill using the common creator history path."""
    if request.workbench_config is not None and not ENABLE_AGENT_WORKBENCH:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail={"code": "WORKBENCH_DISABLED"})
    try:
        user_id, tenant_id, user_language = get_current_user_info(authorization)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Unauthorized") from exc

    try:
        async def prepare_stream(effective, ref=None):
            payload = await run_blocking(
                "nl2skill-snapshot", prepare_nl2skill_snapshot, effective, user_id, tenant_id,
                request.language or user_language or "zh", lane="control-io", owner="management",
            )
            if ref is not None:
                payload = payload.model_copy(update={"system_agent": AgentVersionReference(
                    agent_id=ref.agent_id, version_no=ref.version_no,
                )})
            return create_nl2skill_stream(payload, user_id, tenant_id)

        if request.persist_history or resume:
            stream, conversation_id = await start_creation_turn(
                request, kind="skill", user_id=user_id, tenant_id=tenant_id, stream_factory=prepare_stream, resume=resume,
            )
            headers = {"conversation_id": str(conversation_id)}
            if generation := getattr(request, "_creator_generation", None):
                headers["run_id"] = generation
            return StreamingResponse(stream, media_type="text/event-stream", headers=headers)
        return StreamingResponse(await prepare_stream(request), media_type="text/event-stream")
    except AgentRunAlreadyActiveError as exc:
        raise HTTPException(status_code=409, detail={"code": "CREATOR_RUN_ACTIVE"}) from exc
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
