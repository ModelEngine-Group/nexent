# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Public NL2Agent authorization and creation history."""

import logging
from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from starlette.responses import StreamingResponse

from contracts.agent import NL2AgentRunRequest
from contracts.constants.environment import ENABLE_AGENT_WORKBENCH
from contracts.errors.exceptions import AgentDraftEditError, RunModelControlsError, UnauthorizedError
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.conversation_state import conversation_belongs_to
from management.services.agent.creator_run import create_nl2agent_stream, prepare_nl2agent_snapshot
from management.services.agent.nl2agent import Nl2AgentDraftSaveError
from management.services.conversation.creation_history import persist_creation_stream, prepare_creation_history
from management.services.permission.identity.session import get_current_user_info
from nexent.core.concurrency import run_blocking
from permissions.depends import require
from permissions.models import CurrentUser

router = APIRouter(prefix="/agent", tags=["agent"])
require_agent_create_permission = require("agent:create")
logger = logging.getLogger(__name__)


@router.post("/nl2agent/run")
async def nl2agent_run_api(
    nl2agent_request: NL2AgentRunRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
    _current_user: CurrentUser = Depends(require_agent_create_permission),
):
    """Run NL2Agent; Workbench turns opt into conversation persistence."""
    if (
        nl2agent_request.persist_history or nl2agent_request.workbench_config is not None
    ) and not ENABLE_AGENT_WORKBENCH:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail={"code": "WORKBENCH_DISABLED"})

    try:
        user_id, tenant_id, language = get_current_user_info(authorization, http_request)
        actor = ServicePrincipal(user_id, tenant_id)
        if nl2agent_request.persist_history and nl2agent_request.conversation_id is not None:
            if not await run_blocking(
                "nl2agent-conversation-scope", conversation_belongs_to, nl2agent_request.conversation_id,
                user_id=user_id, tenant_id=tenant_id, lane="control-io", owner="management",
            ):
                raise ValueError("Conversation is not an accessible creation session")
        payload = await prepare_nl2agent_snapshot(nl2agent_request, actor, language)
        stream = create_nl2agent_stream(payload, actor)
        if nl2agent_request.persist_history:
            conversation_id, assistant_index = await run_blocking(
                "nl2agent-history", prepare_creation_history, lane="control-io", owner="management",
                conversation_id=nl2agent_request.conversation_id,
                mode="agent_create",
                query=nl2agent_request.query,
                minio_files=nl2agent_request.minio_files,
                workbench_config=nl2agent_request.workbench_config,
                agent_id=nl2agent_request.agent_id,
                user_id=user_id,
                tenant_id=tenant_id,
                retry_user_message_id=nl2agent_request.retry_user_message_id,
                retry_message_index=nl2agent_request.retry_message_index,
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
    except UnauthorizedError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except AgentDraftEditError as exc:
        status_code = (
            HTTPStatus.NOT_FOUND
            if exc.code == "agent_not_found"
            else HTTPStatus.FORBIDDEN
            if exc.code in {"agent_deleted", "agent_read_only"}
            else HTTPStatus.BAD_REQUEST
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": "Agent draft cannot be reused."},
        ) from exc
    except RunModelControlsError as exc:
        status = {"model_not_available": 404, "model_unavailable": 409, "model_type_invalid": 400}.get(exc.code, 422)
        raise HTTPException(status_code=status, detail={"code": exc.code}) from exc
    except Nl2AgentDraftSaveError as exc:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail={"code": exc.code, "message": "Agent context is invalid."},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Invalid Workbench creation session.",
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Agent draft cannot be reused.",
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("NL2Agent run error")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="NL2Agent run error.",
        ) from exc
