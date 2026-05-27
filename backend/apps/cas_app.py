import html
import logging
from http import HTTPStatus
from typing import Optional
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from services.cas_service import (
    CasAuthenticationError,
    build_login_url,
    build_renew_url,
    get_cas_config,
    login_with_ticket,
    renew_with_ticket,
    revoke_from_logout_request,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/user/cas", tags=["cas"])


@router.get("/config")
async def config():
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={"message": "success", "data": get_cas_config()},
    )


@router.get("/login")
async def login(redirect: str = Query("/", description="URL to return to after login")):
    try:
        return RedirectResponse(url=build_login_url(redirect), status_code=HTTPStatus.FOUND)
    except CasAuthenticationError as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc))


@router.get("/callback")
async def callback(ticket: str = "", redirect: str = "/"):
    try:
        result = await login_with_ticket(ticket, redirect)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "CAS login successful", "data": result},
        )
    except CasAuthenticationError as exc:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except Exception as exc:
        logger.error(f"CAS callback failed: {exc}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="CAS login failed")


@router.get("/renew")
async def renew():
    try:
        return RedirectResponse(url=build_renew_url(), status_code=HTTPStatus.FOUND)
    except CasAuthenticationError as exc:
        return _renew_html(False, str(exc))


@router.get("/renew_callback")
async def renew_callback(ticket: str = ""):
    if not ticket:
        return _renew_html(False, "CAS session is not active")
    try:
        result = await renew_with_ticket(ticket)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "CAS renew successful", "data": result},
        )
    except Exception as exc:
        logger.warning(f"CAS renew failed: {exc}")
        return _renew_html(False, "CAS renew failed")


@router.post("/logout_callback")
async def logout_callback(
    request: Request,
    logout_request: Optional[str] = None,
):
    if logout_request is None:
        body = await request.body()
        raw_body = body.decode("utf-8") if body else ""
        parsed = parse_qs(raw_body)
        logout_request = (parsed.get("logoutRequest") or [raw_body])[0]
    result = revoke_from_logout_request(logout_request)
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={"message": "success", "data": result},
    )


def _renew_html(success: bool, reason: str = "") -> HTMLResponse:
    status = "success" if success else "failed"
    safe_reason = html.escape(reason)
    return HTMLResponse(
        status_code=HTTPStatus.OK,
        content=f"""<!doctype html>
<html><body><script>
window.parent && window.parent.postMessage({{ type: "cas-renew-{status}", reason: "{safe_reason}" }}, window.location.origin);
</script></body></html>""",
    )
