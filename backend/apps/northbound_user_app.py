"""
Northbound API for tenant user provisioning.

Exposes ``POST /nb/v1/users`` which lets a **tenant administrator** create a user
in their own tenant. Authentication reuses the northbound Bearer API key; the
caller must additionally hold the ``ADMIN`` role inside the resolved tenant.
"""
import logging
from http import HTTPStatus
from typing import Annotated, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from database.user_tenant_db import get_user_role_by_tenant
from services.user_management_service import create_user_as_tenant_admin
from consts.exceptions import (
    AppException,
    TenantResourceLimitError,
    UserRegistrationException,
)

from .northbound_app import _get_northbound_context

logger = logging.getLogger("northbound_user_app")

router = APIRouter(prefix="/nb/v1", tags=["northbound"])

__all__ = ["router"]

TENANT_ADMIN_ROLE = "ADMIN"

# Mirrors services.user_management_service.ADMIN_CREATABLE_ROLES. Declared here
# so the OpenAPI schema documents the accepted values without importing the
# service package's runtime dependencies into the route module.
ALLOWED_USER_ROLES = ("USER", "DEV", "ADMIN")


class CreateUserRequest(BaseModel):
    """Payload for creating a user through the northbound API."""

    model_config = {"extra": "forbid"}

    email: Annotated[EmailStr, Field(description="Email address of the new user")]
    initial_password: Annotated[
        str,
        Field(
            min_length=8,
            description="Initial password: at least 8 characters with uppercase, lowercase and digit",
        ),
    ]
    name: Annotated[
        Optional[str], Field(default=None, description="Display name of the new user")
    ]
    role: Annotated[
        str,
        Field(
            default="USER",
            description=f"Role assigned to the new user. One of {', '.join(ALLOWED_USER_ROLES)}",
        ),
    ]


class CreateUserResponse(BaseModel):
    """Summary of the newly created user."""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    user_email: EmailStr
    user_role: str
    tenant_id: str


async def _require_tenant_admin_context(request: Request):
    """Resolve the northbound context and ensure the caller is a tenant admin.

    The caller must hold the ``ADMIN`` role *within the tenant resolved from the
    API key*. A missing tenant relationship (no role row) is also rejected, and
    platform super administrators (``SU``) are intentionally not exempted.
    """
    ctx = await _get_northbound_context(request)
    try:
        user_role = get_user_role_by_tenant(ctx.user_id, ctx.tenant_id)
    except Exception:
        logger.exception("Failed to resolve caller role for tenant admin check")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to verify caller permissions",
        )

    if (user_role or "").upper() != TENANT_ADMIN_ROLE:
        logger.warning(
            "Rejected northbound user creation: user=%s role=%s tenant=%s",
            ctx.user_id,
            user_role or "<none>",
            ctx.tenant_id,
        )
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="This endpoint is restricted to tenant administrators.",
        )
    return ctx


@router.post(
    "/users",
    response_model=CreateUserResponse,
    status_code=HTTPStatus.CREATED,
    summary="Create a user in the caller's tenant (tenant admin only)",
)
async def create_user(payload: CreateUserRequest, request: Request):
    """Create a user belonging to the caller's tenant.

    Restricted to tenant administrators: the API key must resolve to a user whose
    role inside the resolved tenant is ``ADMIN``.

    The new user is provisioned with the supplied initial password and is
    immediately usable (email pre-confirmed). Emails are globally unique, so an
    address registered elsewhere is rejected with ``409``.
    """
    ctx = await _require_tenant_admin_context(request)

    try:
        created = await create_user_as_tenant_admin(
            tenant_id=ctx.tenant_id,
            email=payload.email,
            initial_password=payload.initial_password,
            created_by=ctx.user_id,
            name=payload.name,
            role=payload.role,
        )
    except HTTPException:
        raise
    except AppException as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.message)
    except TenantResourceLimitError as exc:
        # Must precede ValueError: TenantResourceLimitError subclasses it.
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc))
    except UserRegistrationException as exc:
        raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc))
    except Exception:
        logger.exception("Failed to create user via northbound API")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to create user",
        )

    return CreateUserResponse(**created)
