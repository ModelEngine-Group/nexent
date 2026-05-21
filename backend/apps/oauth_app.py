import logging

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from http import HTTPStatus
from typing import Optional

from pydantic import ValidationError as PydanticValidationError

from consts.model import OAuthCompleteRequest
from consts.exceptions import OAuthLinkError, OAuthProviderError, UnauthorizedError
from consts.oauth_providers import get_all_provider_definitions
from database.oauth_account_db import get_oauth_account_by_provider
from services.oauth_service import (
    complete_pending_oauth_account,
    create_or_update_oauth_account,
    ensure_user_tenant_exists,
    exchange_code_for_provider_token,
    find_supabase_user_id_by_email,
    generate_pending_oauth_token,
    get_authorize_url,
    get_enabled_providers,
    get_pending_oauth_info,
    get_provider_user_info,
    list_linked_accounts,
    parse_state,
    unlink_account,
)
from utils.auth_utils import (
    calculate_expires_at,
    generate_session_jwt,
    get_current_user_id,
    get_supabase_admin_client,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/user/oauth", tags=["oauth"])


@router.get("/providers")
async def get_providers():
    providers = get_enabled_providers()
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={"message": "success", "data": providers},
    )


@router.get("/authorize")
async def authorize(provider: str):
    try:
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
        url = get_authorize_url(provider, link_user_id=user_id)
        return RedirectResponse(url=url, status_code=HTTPStatus.FOUND)
    except UnauthorizedError:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="Not logged in")
    except OAuthProviderError as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"OAuth link failed: {e}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="OAuth link failed",
        )


@router.get("/callback")
async def callback(
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

    state_info = parse_state(state)
    link_user_id = state_info.get("link_user_id", "")

    try:
        token_data = exchange_code_for_provider_token(provider, code)
        provider_access_token = token_data["access_token"]

        user_info = get_provider_user_info(
            provider,
            provider_access_token,
            openid=token_data.get("openid", ""),
        )

        provider_user_id = user_info["id"]
        email = user_info["email"]
        username = user_info["username"]

        if link_user_id:
            supabase_user_id = link_user_id
        else:
            # First check if this OAuth account is already bound to a user
            existing_binding = get_oauth_account_by_provider(provider, provider_user_id)
            if existing_binding:
                supabase_user_id = existing_binding["user_id"]
            else:
                supabase_user_id = None
                if email:
                    admin_client = get_supabase_admin_client()
                    if not admin_client:
                        raise RuntimeError("Supabase admin client not available")
                    supabase_user_id = find_supabase_user_id_by_email(
                        admin_client,
                        email,
                    )

                if not supabase_user_id:
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

        ensure_user_tenant_exists(user_id=supabase_user_id, email=email)

        create_or_update_oauth_account(
            user_id=supabase_user_id,
            provider=provider,
            provider_user_id=provider_user_id,
            email=email,
            username=username,
        )

        expiry_seconds = 3600
        jwt_token = generate_session_jwt(supabase_user_id, expires_in=expiry_seconds)
        expires_at = calculate_expires_at(jwt_token)

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": "OAuth login successful",
                "data": {
                    "user": {
                        "id": str(supabase_user_id),
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


@router.get("/pending")
async def get_pending(
    pending_token: Optional[str] = Header(None, alias="X-OAuth-Pending-Token"),
):
    try:
        pending = get_pending_oauth_info(pending_token or "")
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
        request_data = OAuthCompleteRequest(**(await request.json()))
        result = await complete_pending_oauth_account(
            pending_token=pending_token or "",
            email=str(request_data.email) if request_data.email else None,
            password=request_data.password,
            invite_code=request_data.invite_code,
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "OAuth account completed", "data": result},
        )
    except OAuthLinkError as e:
        status_code = (
            HTTPStatus.CONFLICT
            if "Email already exists" in str(e)
            else HTTPStatus.BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=str(e))
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
async def delete_account(provider: str, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="Not logged in")

    try:
        user_id, _ = get_current_user_id(authorization)
        unlink_account(user_id, provider)
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
