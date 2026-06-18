import html
import logging
from http import HTTPStatus
from typing import Optional
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from services.cas_service import (
    CAS_SERVER_URL,
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
        login_url = _require_cas_server_redirect(build_login_url(redirect))
        return RedirectResponse(url=login_url, status_code=HTTPStatus.FOUND)
    except CasAuthenticationError as exc:
        logger.warning("CAS login rejected: %s", exc)
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="CAS login is not available")


@router.get("/callback")
async def callback(ticket: str = "", redirect: str = "/"):
    try:
        result = await login_with_ticket(ticket, redirect)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"message": "CAS login successful", "data": result},
        )
    except CasAuthenticationError as exc:
        logger.warning("CAS callback rejected: %s", exc)
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="CAS authentication failed")
    except Exception as exc:
        logger.error(f"CAS callback failed: {exc}")
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="CAS login failed")


@router.post("/callback")
async def callback_logout(request: Request, logout_request: Optional[str] = None):
    return await _handle_logout_request(request, logout_request, endpoint="callback")


@router.get("/renew")
async def renew():
    try:
        return RedirectResponse(url=build_renew_url(), status_code=HTTPStatus.FOUND)
    except CasAuthenticationError as exc:
        logger.warning("CAS renew rejected: %s", exc)
        return _renew_html(False, "CAS renew failed")


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
    return await _handle_logout_request(request, logout_request, endpoint="logout_callback")


async def _handle_logout_request(
    request: Request,
    logout_request: Optional[str] = None,
    endpoint: str = "unknown",
):
    logout_request = await _extract_logout_request(request, logout_request)
    logger.info(
        "CAS SLO %s received logoutRequest: present=%s length=%s",
        endpoint,
        bool(logout_request),
        len(logout_request or ""),
    )
    result = revoke_from_logout_request(logout_request)
    logger.info("CAS SLO %s revoke result: %s", endpoint, result)
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={"message": "success", "data": result},
    )


async def _extract_logout_request(request: Request, logout_request: Optional[str] = None) -> str:
    if logout_request:
        return logout_request

    query_logout_request = request.query_params.get("logoutRequest") or request.query_params.get("logout_request")
    if query_logout_request:
        return query_logout_request

    body = await request.body()
    raw_body = body.decode("utf-8") if body else ""
    if not raw_body:
        return ""

    parsed = parse_qs(raw_body)
    return (parsed.get("logoutRequest") or parsed.get("logout_request") or [raw_body])[0]


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


def _require_cas_server_redirect(url: str) -> str:
    parsed_url = urlsplit(url)
    parsed_cas = urlsplit(CAS_SERVER_URL)
    if (
        parsed_url.scheme not in {"http", "https"}
        or not parsed_url.netloc
        or parsed_url.scheme != parsed_cas.scheme
        or parsed_url.netloc != parsed_cas.netloc
    ):
        logger.warning("Blocked CAS redirect outside configured server: %s", url)
        raise CasAuthenticationError("Invalid CAS redirect URL")
    return url
