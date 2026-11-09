# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import logging
from http import HTTPStatus
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import ValidationError as PydanticValidationError

from contracts.constants.environment import JWT_EXPIRY_SECONDS
from contracts.identity import OAuthCompleteRequest
from contracts.errors.exceptions import OAuthLinkError, OAuthProviderError, TenantResourceLimitError, UnauthorizedError, tenant_resource_limit_error_payload
from management.utils.oauth_providers import get_all_provider_definitions
from management.db.identity.oauth_account import get_oauth_account_by_provider
from management.services.permission.identity.oauth import (
    complete_pending_oauth_account,
    create_or_update_oauth_account,
    ensure_user_tenant_exists,
    exchange_code_for_provider_token,
    find_account_user_id_by_email,
    generate_pending_oauth_token,
    get_authorize_url,
    get_enabled_providers,
    get_oauth_config,
    get_pending_oauth_info,
    get_provider_user_info,
    list_linked_accounts,
    require_provider_authentication,
    require_provider_unlink,
    unlink_account,
)
from gateway.authentication.auth import (
    calculate_expires_at,
    generate_session_jwt,
    require_active_account,
    get_current_user_id,
)
from gateway.authentication.auth import parse_state, parse_pending_oauth_token
from management.services.monitor.audit import record_security_event
from management.services.permission.identity import casdoor

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/user/oauth", tags=["oauth"])


@router.get("/config")
async def get_config():
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={"message": "success", "data": get_oauth_config()},
    )


@router.get("/providers")
async def get_providers():
    providers = get_enabled_providers()
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={"message": "success", "data": providers},
    )


@router.get("/authorize")
async def authorize(provider: str, signup: bool = False):
    try:
        if provider == "casdoor":
            return _casdoor_authorization_response(signup=signup)
        if signup:
            raise OAuthProviderError("Direct signup is only supported for Casdoor")
        url = get_authorize_url(provider)
        return RedirectResponse(url=url, status_code=HTTPStatus.FOUND)
    except OAuthProviderError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"OAuth authorize failed: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="OAuth authorization failed",
        )


@router.get("/link")
async def link(provider: str, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="Not logged in")

    try:
        user_id, _ = get_current_user_id(authorization)
        require_provider_authentication(require_active_account(user_id), provider)
        if provider == "casdoor":
            return _casdoor_authorization_response(link_user_id=user_id)
        url = get_authorize_url(provider, link_user_id=user_id)
        return RedirectResponse(url=url, status_code=HTTPStatus.FOUND)
    except UnauthorizedError:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="Not logged in")
    except (OAuthProviderError, OAuthLinkError) as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"OAuth link failed: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="OAuth link failed",
        )


def _casdoor_authorization_response(link_user_id: str = "", *, signup: bool = False) -> RedirectResponse:
    url, cookie = casdoor.create_authorization(link_user_id=link_user_id, signup=signup)
    response = RedirectResponse(url=url, status_code=HTTPStatus.FOUND)
    response.set_cookie(
        casdoor.FLOW_COOKIE_NAME, cookie, max_age=casdoor.FLOW_TTL_SECONDS,
        httponly=True, secure=urlparse(casdoor.OAUTH_CALLBACK_BASE_URL).scheme == "https",
        samesite="lax", path="/",
    )
    return response


async def _handle_callback(
    http_request: Request,
    provider: str,
    code: str = "",
    state: str = "",
    error: Optional[str] = None,
    error_description: Optional[str] = None,
):
    if error:
        return JSONResponse(
            status_code=HTTPStatus.BAD_REQUEST,
            content={
                "message": "OAuth provider returned an error",
                "data": {
                    "oauth_error": error,
                    "oauth_error_description": error_description or "Unknown error",
                },
            },
        )

    if not code:
        return JSONResponse(
            status_code=HTTPStatus.BAD_REQUEST,
            content={
                "message": "No authorization code received",
                "data": {
                    "oauth_error": "no_code",
                    "oauth_error_description": "No authorization code received",
                },
            },
        )

    if provider not in get_all_provider_definitions():
        return JSONResponse(
            status_code=HTTPStatus.BAD_REQUEST,
            content={
                "message": "Unsupported OAuth provider",
                "data": {
                    "oauth_error": "unsupported_provider",
                    "oauth_error_description": f"Provider '{provider}' is not supported",
                },
            },
        )

    try:
        if provider == "casdoor":
            state_info = casdoor.validate_flow(state, http_request.cookies.get(casdoor.FLOW_COOKIE_NAME, ""))
            user_info = casdoor.authenticate(code, state_info)
        else:
            state_info = parse_state(state)
            token_data = exchange_code_for_provider_token(provider, code)
            user_info = get_provider_user_info(
                provider, token_data["access_token"], openid=token_data.get("openid", ""),
            )
        link_user_id = state_info.get("link_user_id", "")

        provider_user_id = user_info["id"]
        email = user_info["email"]
        username = user_info["username"]

        if link_user_id:
            user_id = link_user_id
        else:
            # First check if this OAuth account is already bound to a user
            existing_binding = get_oauth_account_by_provider(provider, provider_user_id)
            if existing_binding:
                user_id = existing_binding["user_id"]
            else:
                user_id = None
                if email and provider != "casdoor":
                    user_id = find_account_user_id_by_email(email)

                if not user_id:
                    pending_token = generate_pending_oauth_token(
                        provider=provider,
                        provider_user_id=provider_user_id,
                        provider_email=email,
                        provider_username=username,
                    )
                    return JSONResponse(
                        status_code=HTTPStatus.OK,
                        content={
                            "message": "OAuth account information required",
                            "data": {
                                "requires_account_completion": True,
                                "pending_token": pending_token,
                                "provider": provider,
                                "provider_username": username,
                                "provider_email": email,
                                "email_required": not bool(email),
                            },
                        },
                    )

        require_provider_authentication(require_active_account(user_id), provider)
        ensure_user_tenant_exists(user_id=user_id, email=email)

        create_or_update_oauth_account(
            user_id=user_id,
            provider=provider,
            provider_user_id=provider_user_id,
            email=email,
            username=username,
        )

        jwt_token = generate_session_jwt(
            user_id, expires_in=JWT_EXPIRY_SECONDS
        )
        expiry_seconds = JWT_EXPIRY_SECONDS
        expires_at = calculate_expires_at(jwt_token)

        record_security_event("oauth_login", request=http_request,
                              user_id=user_id, user_email=email,
                              details={"provider": provider, "linked": bool(link_user_id)})
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "OAuth login successful",
                "data": {
                    "user": {
                        "id": str(user_id),
                        "email": email,
                    },
                    "session": {
                        "access_token": jwt_token,
                        "refresh_token": "",
                        "expires_at": expires_at,
                        "expires_in_seconds": expiry_seconds,
                    },
                },
            },
        )

    except OAuthProviderError:
        logger.warning("OAuth provider authentication failed for provider=%s", provider)
        return JSONResponse(
            status_code=HTTPStatus.BAD_REQUEST if provider == "casdoor" else HTTPStatus.INTERNAL_SERVER_ERROR,
            content={"message": "OAuth login failed", "data": {
                "oauth_error": "callback_failed", "oauth_error_description": "OAuth login failed",
            }},
        )
    except TenantResourceLimitError as e:
        logger.warning(f"OAuth callback rejected by tenant resource limit for provider={provider}: {e}")
        return JSONResponse(
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
            content=tenant_resource_limit_error_payload(e),
        )
    except OAuthLinkError as e:
        logger.warning(f"OAuth callback link failed for provider={provider}: {e}")
        return JSONResponse(
            status_code=HTTPStatus.BAD_REQUEST,
            content={
                "message": "OAuth account link failed",
                "data": {
                    "oauth_error": "oauth_account_already_bound",
                    "oauth_error_description": "OAuth account is already bound to another user",
                },
            },
        )
    except Exception as e:
        logger.error(f"OAuth callback failed for provider={provider}: {e}")
        return JSONResponse(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            content={
                "message": "OAuth login failed",
                "data": {
                    "oauth_error": "callback_failed",
                    "oauth_error_description": "OAuth login failed",
                },
            },
        )


@router.get("/callback")
async def callback(
    http_request: Request,
    provider: str,
    code: str = "",
    state: str = "",
    error: Optional[str] = None,
    error_description: Optional[str] = None,
):
    response = await _handle_callback(http_request, provider, code, state, error, error_description)
    if provider == "casdoor":
        response.delete_cookie(casdoor.FLOW_COOKIE_NAME, path="/")
    return response


@router.get("/pending")
async def get_pending(
    pending_token: Optional[str] = Header(None, alias="X-OAuth-Pending-Token"),
):
    try:
        pending = get_pending_oauth_info(parse_pending_oauth_token(pending_token or ""))
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "success", "data": pending},
        )
    except OAuthLinkError as e:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except OAuthProviderError as e:
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to get pending OAuth info: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to get pending OAuth info",
        )


@router.post("/complete")
async def complete(
    request: Request,
    pending_token: Optional[str] = Header(None, alias="X-OAuth-Pending-Token"),
):
    try:
        pending_identity = parse_pending_oauth_token(pending_token or "")
        if pending_identity["provider"] == "casdoor":
            from contracts.identity import CasdoorCompleteRequest

            request_data = CasdoorCompleteRequest(**(await request.json()))
        else:
            request_data = OAuthCompleteRequest(**(await request.json()))
        result = await complete_pending_oauth_account(
            pending_identity=pending_identity,
            email=str(request_data.email) if request_data.email else None,
            password=getattr(request_data, "password", None),
            invite_code=request_data.invite_code,
        )
        completed_user = (result or {}).get("user") or {}
        record_security_event(
            "oauth_signup", request=request, user_id=completed_user.get("id"), user_email=completed_user.get("email")
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "OAuth account completed", "data": result},
        )
    except OAuthLinkError as e:
        status_code = HTTPStatus.CONFLICT if "Email already exists" in str(e) else HTTPStatus.BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(e))
    except TenantResourceLimitError as e:
        return JSONResponse(
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
            content=tenant_resource_limit_error_payload(e),
        )
    except PydanticValidationError as e:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail=e.errors(),
        )
    except OAuthProviderError as e:
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to complete OAuth account: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to complete OAuth account",
        )


@router.get("/accounts")
async def get_accounts(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="Not logged in")

    try:
        user_id, _ = get_current_user_id(authorization)
        accounts = list_linked_accounts(user_id)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "success", "data": accounts},
        )
    except UnauthorizedError:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="Not logged in")
    except Exception as e:
        logger.error(f"Failed to get OAuth accounts: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to get OAuth accounts",
        )


@router.delete("/accounts/{provider}")
async def delete_account(provider: str, http_request: Request, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="Not logged in")

    try:
        user_id, tenant_id = get_current_user_id(authorization)
        require_provider_unlink(require_active_account(user_id), provider)
        unlink_account(user_id, provider)
        record_security_event(
            "oauth_unlink", request=http_request, user_id=user_id, tenant_id=tenant_id, details={"provider": provider}
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "success",
                "data": {"provider": provider, "unlinked": True},
            },
        )
    except OAuthLinkError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except UnauthorizedError:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="Not logged in")
    except Exception as e:
        logger.error(f"Failed to unlink OAuth account: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to unlink OAuth account",
        )
