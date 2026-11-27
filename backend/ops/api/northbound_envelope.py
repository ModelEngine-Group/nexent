# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Wrap northbound /nb responses in the published partner contract.

The /nb/ops monitoring mount reuses the internal route handlers verbatim, so
their JSON bodies arrive in the internal shape. Successes are wrapped into
``{message, data, requestId}``; failures are translated into the three-field
``{code, message, status, requestId}`` body the northbound surface publishes.
Paths outside ``/nb`` pass through untouched, keeping the browser session
contracts byte-for-byte.
"""

import json
import logging
from http import HTTPStatus

from starlette.requests import Request

from backend.http.server.northbound import is_northbound_path, northbound_envelope
from backend.http.server.request_context import get_request_id

logger = logging.getLogger(__name__)

_ENVELOPE_KEYS = {"code", "message", "status", "requestId"}


class NorthboundEnvelopeMiddleware:
    """ASGI middleware: one place where the /nb contract shapes are produced."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not is_northbound_path(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        state: dict = {"start": None, "chunks": []}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                state["start"] = dict(message)
                return
            if message["type"] != "http.response.body":
                await send(message)
                return
            state["chunks"].append(message.get("body", b""))
            if message.get("more_body"):
                return
            start = state["start"]
            raw = b"".join(state["chunks"])
            encoded = _encode(raw, start, scope)
            if encoded is None:
                # Non-JSON or undecodable body: keep the original bytes.
                await send(start)
                await send({"type": "http.response.body", "body": raw})
                return
            headers = [(k, v) for k, v in start.get("headers", []) if k.lower() != b"content-length"]
            headers.append((b"content-length", str(len(encoded)).encode("ascii")))
            start["headers"] = headers
            await send(start)
            await send({"type": "http.response.body", "body": encoded})

        await self.app(scope, receive, send_wrapper)


def _encode(raw: bytes, start: dict, scope: dict) -> bytes | None:
    """Return the contract-encoded body, or None to pass the original through."""
    status = start.get("status", 200)
    if not raw or not _is_json(start.get("headers", [])):
        return None
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        logger.warning("Northbound body could not be decoded status=%s", status)
        return None
    request_id = get_request_id(Request(scope))
    if status < 400:
        payload = northbound_envelope(body, request_id)
    else:
        payload = _error_body(body, status, request_id)
    try:
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


def _is_json(headers) -> bool:
    return any(key.lower() == b"content-type" and b"json" in value.lower() for key, value in headers)


def _error_body(body, status: int, request_id: str) -> dict:
    """Translate an internal error body into the three-field northbound shape.

    Domain bodies produced by the shared exception handlers already carry the
    contract fields and pass through unchanged; HTTPException bodies keep
    their static detail wording, and structured details (for example the 409
    uncovered-dates payload) keep their diagnostic keys.
    """
    code = None
    message = None
    extras: dict = {}
    if isinstance(body, dict):
        candidate_code = body.get("code")
        if isinstance(candidate_code, str):
            code = candidate_code
        detail = body.get("message", body.get("detail"))
        if isinstance(detail, dict):
            code = code or detail.get("code")
            message = detail.get("code")
            extras.update({key: value for key, value in detail.items() if key != "code"})
        elif isinstance(detail, str):
            message = detail
        for key, value in body.items():
            if key not in _ENVELOPE_KEYS and key != "detail" and key not in extras:
                extras[key] = value
    existing_id = body.get("requestId") if isinstance(body, dict) else None
    return {
        "code": code or f"HTTP_{status}",
        "message": message or _default_message(status),
        "status": status,
        "requestId": existing_id or request_id,
        **extras,
    }


def _default_message(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Request failed"
