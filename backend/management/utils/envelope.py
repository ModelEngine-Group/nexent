# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Northbound success envelope: one business result, one published shape.

The northbound ``/nb/v1`` contract is ``{message, data, requestId}`` and
published partners depend on it. Business functions return bare data and each
gate wraps it:

    return northbound_envelope(result, request_id)

The internal ``/api`` contract (``{code, message, data}``) is produced by the
internal routes themselves; gates share the service implementations but never
rewrite internal responses.
"""

from typing import Any

SUCCESS_MESSAGE = "success"


def northbound_envelope(data: Any = None, request_id: str = "", message: str = SUCCESS_MESSAGE) -> dict:
    """Build the northbound ``{message, data, requestId}`` envelope."""
    return {"message": message, "data": data, "requestId": request_id}
