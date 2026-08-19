"""Runtime-only Agent execution endpoints."""

import logging
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

from consts.exceptions import AppException, ForbiddenError
from consts.model import AgentRequest


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/agent", include_in_schema=False)


async def _run_agent_stream(**kwargs):
    """Import the Runtime implementation only when the internal route is used."""
    from services.agent_service import run_agent_stream

    return await run_agent_stream(**kwargs)


def _stop_agent_tasks(conversation_id: int | str, user_id: str):
    """Import the Runtime cancellation implementation only when requested."""
    from services.agent_service import stop_agent_tasks

    return stop_agent_tasks(conversation_id, user_id)


class InternalAgentRequest(AgentRequest):
    """Agent request variant that rejects fields unknown to Runtime."""

    model_config = ConfigDict(extra="forbid")


class InternalAgentRunRequest(BaseModel):
    """Trusted identity and Agent payload forwarded by Northbound."""

    model_config = ConfigDict(extra="forbid")

    agent_request: InternalAgentRequest
    user_id: str = Field(strict=True, min_length=1)
    tenant_id: str = Field(strict=True, min_length=1)
    runtime_scope_id: str | None = Field(default=None, strict=True)

    @field_validator("user_id", "tenant_id")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Identity fields cannot be blank")
        return value

    @field_validator("runtime_scope_id")
    @classmethod
    def validate_runtime_scope(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("runtime_scope_id cannot be blank")
        return value


class InternalAgentStopRequest(BaseModel):
    """Trusted Runtime cancellation request."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: StrictInt | StrictStr
    user_id: str = Field(strict=True, min_length=1)

    @field_validator("conversation_id")
    @classmethod
    def validate_conversation_id(cls, value: int | str) -> int | str:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("conversation_id cannot be blank")
        return value

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("user_id cannot be blank")
        return value


@router.post("/run")
async def internal_agent_run(
    payload: InternalAgentRunRequest,
    x_request_id: Annotated[str | None, Header(alias="X-Request-Id")] = None,
):
    """Run an Agent under an identity already authenticated by Northbound."""
    logger.info(
        "Internal Agent run request_id=%s user_id=%s tenant_id=%s conversation_id=%s",
        x_request_id,
        payload.user_id,
        payload.tenant_id,
        payload.agent_request.conversation_id,
    )
    try:
        response = await _run_agent_stream(
            agent_request=payload.agent_request,
            http_request=None,
            authorization=None,
            user_id=payload.user_id,
            tenant_id=payload.tenant_id,
            skip_user_save=False,
            runtime_scope_id=payload.runtime_scope_id,
        )
        if x_request_id:
            response.headers["X-Request-Id"] = x_request_id
        return response
    except ForbiddenError as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(exc)) from exc
    except AppException:
        raise
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Internal Agent run failed request_id=%s", x_request_id)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Agent run error.",
        ) from exc


@router.post("/stop")
async def internal_agent_stop(
    payload: InternalAgentStopRequest,
    response: Response,
    x_request_id: Annotated[str | None, Header(alias="X-Request-Id")] = None,
):
    """Stop an Agent run through its Redis-backed Runtime scope."""
    logger.info(
        "Internal Agent stop request_id=%s user_id=%s conversation_id=%s",
        x_request_id,
        payload.user_id,
        payload.conversation_id,
    )
    if x_request_id:
        response.headers["X-Request-Id"] = x_request_id
    return _stop_agent_tasks(payload.conversation_id, payload.user_id)
