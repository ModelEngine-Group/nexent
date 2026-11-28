# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Northbound success envelope: one business result, one published shape.

The northbound ``/nb/v1`` contract is ``{message, data, requestId}`` and
published partners depend on it. Business functions return bare data and each
gate wraps it:

    return northbound_envelope(result, request_id)

The implementation lives in the shared Web layer
(``backend/http/server/northbound.py``) because the ops ``/nb`` mirror wraps
responses with the same shape; re-exported here so the existing management
call sites keep working. The internal ``/api`` contract (``{code, message,
data}``) is produced by the internal routes themselves; gates share the
service implementations but never rewrite internal responses.
"""

from backend.http.server.northbound import SUCCESS_MESSAGE, northbound_envelope  # noqa: F401 - re-exported

__all__ = ["SUCCESS_MESSAGE", "northbound_envelope"]
