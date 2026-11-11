# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Success-response envelopes: one business result, two published shapes.

The internal ``/api`` contract is ``{code, message, data}`` and the frontend
branches on ``code == 0``. The northbound ``/nb/v1`` contract is
``{message, data, requestId}`` and published partners depend on it. Both stay
verbatim, so business functions return bare data and each entrypoint wraps it:

    # internal route
    return internal_envelope(result)

    # northbound clone of the same route
    return northbound_envelope(result, request_id)

``InternalEnvelope`` is the marker the northbound clone rewrites. A route that
returns a raw payload (no marker) is wrapped as northbound data as-is, and a
``Response`` object (stream, redirect, file) is never rewritten.
"""

from typing import Any

from starlette.responses import Response

SUCCESS_MESSAGE = "success"


class InternalEnvelope(dict):
    """Internal success envelope, marked so the northbound clone can rewrite it."""

    __slots__ = ()


def internal_envelope(data: Any = None, message: str = SUCCESS_MESSAGE) -> InternalEnvelope:
    """Build the internal ``{code, message, data}`` envelope."""
    return InternalEnvelope(code=0, message=message, data=data)


def northbound_envelope(data: Any = None, request_id: str = "", message: str = SUCCESS_MESSAGE) -> dict:
    """Build the northbound ``{message, data, requestId}`` envelope."""
    return {"message": message, "data": data, "requestId": request_id}


def is_response_instance(value: Any) -> bool:
    """Whether the route already produced a concrete HTTP response."""
    return isinstance(value, Response)


def to_northbound_payload(result: Any, request_id: str = "") -> Any:
    """Translate one route result into the northbound success contract.

    Response objects pass through untouched so streams and redirects keep their
    media type and headers.
    """
    if is_response_instance(result):
        return result
    if isinstance(result, InternalEnvelope):
        return northbound_envelope(result.get("data"), request_id, result.get("message") or SUCCESS_MESSAGE)
    return northbound_envelope(result, request_id)
