"""HTTP lifecycle, read, and unified action API for NL2AGENT."""

import logging
from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request

from consts.error_code import ErrorCode
from consts.exceptions import (
    AgentRunException,
    AppException,
    ForbiddenError,
    Nl2AgentExternalServiceError,
    Nl2AgentOperationError,
    Nl2AgentValidationError,
    UnauthorizedError,
)
from consts.model import Nl2AgentActionRequest, Nl2AgentActionResponse
from consts.nl2agent_response import (
    Nl2AgentSessionListResponse,
    Nl2AgentSessionStartResponse,
    Nl2AgentSessionStateResponse,
    Nl2AgentSessionSummaryResponse,
    Nl2AgentWebSkillConfigurationResponse,
)
from services.nl2agent_runtime_service import (
    dispatch_action,
    get_session_state,
    get_web_skill_configuration,
    resume_session,
    start_session,
)
from services.nl2agent_session_lifecycle_service import (
    abandon_session,
    cleanup_expired_sessions,
    list_active_sessions,
    resolve_session,
    resolve_session_by_agent,
)
from utils.auth_utils import get_current_user_info

router = APIRouter(prefix="/nl2agent")
logger = logging.getLogger("nl2agent_app")


def _current_user(
    authorization: Optional[str], http_request: Request
) -> tuple[str, str, str]:
    """Authenticate one NL2AGENT request at the HTTP boundary."""
    try:
        return get_current_user_info(authorization, http_request)
    except UnauthorizedError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail=str(exc),
        ) from exc


def _session_http_error(exc: Exception) -> Exception:
    """Convert service failures without inspecting message text."""
    if isinstance(exc, AppException):
        return exc
    if isinstance(exc, Nl2AgentValidationError):
        return AppException(
            ErrorCode.AGENTSPACE_NL2AGENT_INVALID_REQUEST,
            str(exc),
        )
    if isinstance(exc, Nl2AgentExternalServiceError):
        return AppException(
            ErrorCode.AGENTSPACE_NL2AGENT_EXTERNAL_SERVICE_FAILED,
            str(exc),
        )
    if isinstance(exc, Nl2AgentOperationError):
        return AppException(
            ErrorCode.AGENTSPACE_NL2AGENT_OPERATION_FAILED,
            str(exc),
        )
    if isinstance(exc, AgentRunException):
        return AppException(
            ErrorCode.AGENTSPACE_NL2AGENT_WORKFLOW_CONFLICT,
            str(exc),
        )
    logger.exception("NL2AGENT session operation failed")
    return AppException(
        ErrorCode.SYSTEM_INTERNAL_ERROR,
        "Failed to load or update NL2AGENT session state.",
    )


def _action_http_error(exc: Exception) -> Exception:
    """Apply the action endpoint's stable HTTP error semantics."""
    if isinstance(exc, ForbiddenError):
        return HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(exc))
    if isinstance(exc, Nl2AgentValidationError):
        return HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    if isinstance(exc, Nl2AgentExternalServiceError):
        return HTTPException(status_code=HTTPStatus.BAD_GATEWAY, detail=str(exc))
    if isinstance(exc, Nl2AgentOperationError):
        return HTTPException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    return _session_http_error(exc)


@router.get(
    "/sessions",
    response_model=Nl2AgentSessionListResponse,
    response_model_exclude_none=True,
)
async def list_sessions_api(
    http_request: Request,
    limit: int = 50,
    authorization: Optional[str] = Header(None),
):
    """List the current user's active NL2AGENT sessions."""
    user_id, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return {
            "sessions": list_active_sessions(
                tenant_id=tenant_id,
                user_id=user_id,
                limit=limit,
            )
        }
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.get(
    "/session/by-conversation/{conversation_id}",
    response_model=Optional[Nl2AgentSessionSummaryResponse],
    response_model_exclude_none=True,
)
async def resolve_session_api(
    conversation_id: int,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    """Resolve an optional owned session after browser state is lost."""
    user_id, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return resolve_session(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.get(
    "/session/by-agent/{draft_agent_id}",
    response_model=Optional[Nl2AgentSessionSummaryResponse],
    response_model_exclude_none=True,
)
async def resolve_session_by_agent_api(
    draft_agent_id: int,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    """Resolve an optional owned session for the Agent configuration page."""
    user_id, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return resolve_session_by_agent(
            draft_agent_id=draft_agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.post(
    "/session/{draft_agent_id}/resume",
    response_model=Nl2AgentSessionSummaryResponse,
    response_model_exclude_none=True,
)
async def resume_session_api(
    draft_agent_id: int,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    """Resume a final-review session in targeted editing mode."""
    user_id, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return resume_session(draft_agent_id, tenant_id, user_id)
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.post(
    "/session/{draft_agent_id}/abandon",
    response_model=Nl2AgentSessionSummaryResponse,
    response_model_exclude_none=True,
)
async def abandon_session_api(
    draft_agent_id: int,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    """Explicitly end one owned draft session."""
    user_id, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return abandon_session(
            draft_agent_id=draft_agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.post("/session/start", response_model=Nl2AgentSessionStartResponse)
async def start_session_api(
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    """Create one draft, builder Conversation, and durable workflow session."""
    user_id, tenant_id, language = _current_user(authorization, http_request)
    try:
        try:
            cleanup_expired_sessions()
        except Exception:
            logger.warning(
                "Failed to clean expired NL2AGENT sessions before start",
                exc_info=True,
            )
        return await start_session(
            user_id=user_id,
            tenant_id=tenant_id,
            language=language,
        )
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.post(
    "/session/{draft_agent_id}/actions",
    response_model=Nl2AgentActionResponse,
    response_model_exclude_none=True,
)
async def dispatch_action_api(
    draft_agent_id: int,
    payload: Nl2AgentActionRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    """Apply one strict, idempotent business action to an active session."""
    user_id, tenant_id, language = _current_user(authorization, http_request)
    try:
        return await dispatch_action(
            draft_agent_id,
            payload,
            tenant_id,
            user_id,
            language,
        )
    except Exception as exc:
        raise _action_http_error(exc) from exc


@router.get(
    "/session/{draft_agent_id}/state",
    response_model=Nl2AgentSessionStateResponse,
    response_model_exclude_none=True,
)
async def get_session_state_api(
    draft_agent_id: int,
    http_request: Request,
    authorization: Optional[str] = Header(None),
):
    """Return the authoritative read-only workflow projection."""
    user_id, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return await get_session_state(draft_agent_id, tenant_id, user_id)
    except Exception as exc:
        raise _session_http_error(exc) from exc


@router.get(
    "/session/{draft_agent_id}/web-skill/configuration",
    response_model=Nl2AgentWebSkillConfigurationResponse,
    response_model_exclude_none=True,
)
async def get_web_skill_configuration_api(
    draft_agent_id: int,
    http_request: Request,
    skill_id: Optional[int] = Query(default=None, ge=1),
    skill_name: Optional[str] = Query(default=None, min_length=1, max_length=300),
    authorization: Optional[str] = Header(None),
):
    """Return trusted, redacted configuration metadata for one Skill."""
    user_id, tenant_id, _ = _current_user(authorization, http_request)
    try:
        return get_web_skill_configuration(
            agent_id=draft_agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            skill_id=skill_id,
            skill_name=skill_name,
        )
    except Exception as exc:
        raise _session_http_error(exc) from exc
