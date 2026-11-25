# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Request correlation ids for the shared Web layer.

The shared Web layer writes ``requestId`` into error bodies, so the helper has
to live with it rather than behind a business service. ``get_request_id`` is
pure HTTP plumbing: no settings, no database, no business import.
"""

import uuid
from typing import Optional

from fastapi import Request

REQUEST_ID_HEADER = "x-request-id"


def get_request_id(request: Optional[Request] = None) -> str:
    """Resolve the correlation id used by response envelopes and error bodies.

    Precedence: the caller-supplied ``X-Request-Id`` header, then the id bound
    to the request by the identity dependency, then a fresh identifier so a
    response always carries one.
    """
    if request is not None:
        try:
            header_value = request.headers.get(REQUEST_ID_HEADER)
        except Exception:  # pragma: no cover - defensive for non-HTTP scopes
            header_value = None
        if header_value and header_value.strip():
            return header_value.strip()
        state_value = getattr(request.state, "request_id", None)
        if state_value:
            return str(state_value)
    return str(uuid.uuid4())
