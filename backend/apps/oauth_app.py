import logging

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from http import HTTPStatus
from typing import Optional

from consts.exceptions import OAuthLinkError, OAuthProviderError, UnauthorizedError
from consts.oauth_providers import get_all_provider_definitions
from services.oauth_service import (
    create_or_update_oauth_account,
    ensure_user_tenant_exists,
    exchange_code_for_provider_token,
    get_authorize_url,
    get_enabled_providers,
    get_provider_user_info,
    list_linked_accounts,
    unlink_account,
)
from utils.auth_utils import (
    calculate_expires_at,
    generate_session_jwt,
    get_current_user_id,
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

    from services.oauth_service import parse_state

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

        from utils.auth_utils import get_supabase_admin_client

        if link_user_id:
            supabase_user_id = link_user_id
        else:
            admin_client = get_supabase_admin_client()
            if not admin_client:
                raise RuntimeError("Supabase admin client not available")

            supabase_user_id = None
            page = 1
            while True:
                users_resp = admin_client.auth.admin.list_users(page=page, per_page=100)
                users = users_resp if len(users_resp) > 0 else []
                if not users:
                    break
                for u in users:
                    if u.email and u.email.lower() == email.lower():
                        supabase_user_id = u.id
                        break
                if supabase_user_id:
                    break
                if len(users) < 100:
                    break
                page += 1

            if not supabase_user_id:
                if not email:
                    email = f"{provider}_{provider_user_id}@oauth.nexent"
                create_resp = admin_client.auth.admin.create_user(
                    {
                        "email": email,
                        "email_confirm": True,
                        "user_metadata": {
                            "full_name": username,
                            "provider": provider,
                        },
                    }
                )
                supabase_user_id = create_resp.user.id

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

        has_password_auth = False
        from utils.auth_utils import get_supabase_admin_client

        admin_client = get_supabase_admin_client()
        if admin_client:
            try:
                user_resp = admin_client.auth.admin.get_user_by_id(user_id)
                identities = getattr(user_resp.user, "identities", None) or []
                has_password_auth = any(
                    getattr(ident, "provider", "") == "email" for ident in identities
                )
            except Exception:
                logger.warning(f"Failed to check user identities for {user_id}")

        unlink_account(user_id, provider, has_password_auth=has_password_auth)
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
