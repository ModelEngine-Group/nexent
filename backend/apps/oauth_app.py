import logging

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from http import HTTPStatus
from typing import Optional

from consts.exceptions import OAuthLinkError, OAuthProviderError, UnauthorizedError
from services.oauth_service import (
    create_or_update_oauth_account,
    ensure_user_tenant_exists,
    get_authorize_url,
    get_enabled_providers,
    list_linked_accounts,
    unlink_account,
)
from utils.auth_utils import (
    calculate_expires_at,
    get_current_user_id,
    get_jwt_expiry_seconds,
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


@router.get("/callback")
async def callback(
    provider: str,
    code: str = "",
    error: Optional[str] = None,
    error_description: Optional[str] = None,
):
    """
    OAuth callback endpoint.

    Returns JSON with session data (same format as /signin) so that
    server.js forwardAuthRequest can set HttpOnly cookies and the
    frontend can handle the redirect client-side.
    """
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

    if provider not in ("github", "wechat"):
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
        from utils.auth_utils import get_supabase_admin_client

        admin_client = get_supabase_admin_client()
        if not admin_client:
            raise RuntimeError("Supabase admin client not available")

        auth_response = admin_client.auth.admin.exchange_code_for_session(code)

        if not auth_response or not auth_response.user:
            return JSONResponse(
                status_code=HTTPStatus.UNAUTHORIZED,
                content={
                    "message": "Failed to get user from OAuth provider",
                    "data": {
                        "oauth_error": "no_user",
                        "oauth_error_description": "Failed to get user from OAuth provider",
                    },
                },
            )

        user = auth_response.user
        session = auth_response.session
        user_id = user.id
        email = user.email or user.user_metadata.get("email", "")
        username = (
            user.user_metadata.get("user_name") or user.user_metadata.get("name") or ""
        )
        avatar_url = (
            user.user_metadata.get("avatar_url")
            or user.user_metadata.get("picture")
            or ""
        )

        ensure_user_tenant_exists(user_id=user_id, email=email)

        create_or_update_oauth_account(
            user_id=user_id,
            provider=provider,
            provider_user_id=user.id,
            email=email,
            username=username,
            avatar_url=avatar_url,
            access_token=session.access_token if session else None,
            refresh_token=session.refresh_token if session else None,
        )

        expiry_seconds = (
            get_jwt_expiry_seconds(session.access_token) if session else 3600
        )
        expires_at = calculate_expires_at(session.access_token) if session else 0

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
                        "access_token": session.access_token if session else "",
                        "refresh_token": session.refresh_token if session else "",
                        "expires_at": expires_at,
                        "expires_in_seconds": expiry_seconds,
                    },
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
